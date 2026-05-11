"""Patch 24: close two remaining localization leaks.

Leak 1: `/quiz: build topic keyboard` builds the prompt text and "saved
material(s)" string in hard-coded English, ignoring user lang preference.

Leak 2: First-time `/start` user has no row in app.user_state, so the
first `/learn` summary defaults to lang='en' even when their Telegram
client is Russian — UX inconsistent until they manually `/lang ru`.

Fix:
- /quiz: insert `lang: pg load /quiz` between `pg SELECT materials` and
  `build topic keyboard`. Rewrite the keyboard JS to read materials via
  $('/quiz: pg SELECT materials').all() and lang via $('lang: pg load /quiz')
  and emit localized text.
- /start: add `/start: pg upsert lang` step that seeds user_state.lang
  from the user's Telegram client `from.language_code` on the very first
  /start. Idempotent (ON CONFLICT DO UPDATE). Subsequent commands now
  find a row and honour it.
"""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# Find Postgres credentials
PG_CREDS = None
for n in nodes:
    if n.get('type','').endswith('postgres') and n.get('credentials'):
        PG_CREDS = n['credentials']
        break

def new_id():
    return str(uuid.uuid4())

# ============================================================
# 1. /start: pg upsert lang (auto-detect from Telegram client)
# ============================================================
START_UPSERT_SQL = (
    "INSERT INTO app.user_state (chat_id, lang)\n"
    "VALUES (\n"
    "  {{ $('Telegram Trigger1').item.json.message.chat.id }},\n"
    "  CASE\n"
    "    WHEN COALESCE($$"
    "{{ ($('Telegram Trigger1').item.json.message.from?.language_code || '').replace(/[^a-z-]/g,'') }}"
    "$$, '') LIKE 'ru%' THEN 'ru'\n"
    "    ELSE 'en'\n"
    "  END\n"
    ")\n"
    "ON CONFLICT (chat_id) DO NOTHING\n"
    "RETURNING chat_id, lang;"
)

start_upsert = {
    "parameters": {"operation": "executeQuery", "query": START_UPSERT_SQL, "options": {}},
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [-400, 0],
    "id": new_id(),
    "name": "/start: pg seed lang",
    "credentials": PG_CREDS
}
if not any(n.get('name') == '/start: pg seed lang' for n in nodes):
    nodes.append(start_upsert)
    sys.stderr.write("Added /start: pg seed lang\n")

# Rewire: Route[0] (start) -> /start: pg seed lang -> /start: build text -> /start: send
# Find current wiring of Route to /start: build text
for src_name, conf in connections.items():
    if src_name == 'Route':
        for branch in conf.get('main', []):
            for tgt in branch:
                if tgt.get('node') == '/start: build text':
                    tgt['node'] = '/start: pg seed lang'
                    sys.stderr.write("Rewired Route[/start] -> pg seed lang\n")

connections['/start: pg seed lang'] = {
    "main": [[{"node": "/start: build text", "type": "main", "index": 0}]]
}

# ============================================================
# 2. /quiz: add lang loader + localize topic keyboard
# ============================================================
quiz_lang_load = {
    "parameters": {
        "operation": "executeQuery",
        "query": (
            "SELECT COALESCE(\n"
            "  (SELECT lang FROM app.user_state WHERE chat_id = {{ Number(\n"
            "    $('Telegram Trigger1').item.json.message?.chat?.id\n"
            "    ?? $('Telegram Trigger1').item.json.callback_query?.from?.id\n"
            "    ?? 0\n"
            "  ) }}),\n"
            "  'en'\n"
            ") AS lang;"
        ),
        "options": {}
    },
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [-700, 200],
    "id": new_id(),
    "name": "lang: pg load /quiz",
    "credentials": PG_CREDS
}
if not any(n.get('name') == 'lang: pg load /quiz' for n in nodes):
    nodes.append(quiz_lang_load)
    sys.stderr.write("Added lang: pg load /quiz\n")

# Rewire: /quiz: pg SELECT materials -> lang: pg load /quiz -> /quiz: build topic keyboard
quiz_select_main = connections.get('/quiz: pg SELECT materials', {}).get('main', [[]])
if quiz_select_main and quiz_select_main[0]:
    if quiz_select_main[0][0].get('node') == '/quiz: build topic keyboard':
        connections['/quiz: pg SELECT materials'] = {
            "main": [[{"node": "lang: pg load /quiz", "type": "main", "index": 0}]]
        }
        connections['lang: pg load /quiz'] = {
            "main": [[{"node": "/quiz: build topic keyboard", "type": "main", "index": 0}]]
        }
        sys.stderr.write("Inserted lang: pg load /quiz between SELECT and build keyboard\n")

# Localized topic keyboard JS
QUIZ_BUILD_KEYBOARD_JS = r"""const T = {
  en: {
    pickTopic: '📚 *Pick a topic to quiz on:*',
    youHaveMaterial: (n) => `You have ${n} saved material${n === 1 ? '' : 's'}.`,
    noMaterials: '📭 *No saved materials yet.*\n\nSend `/learn [URL]` first.'
  },
  ru: {
    pickTopic: '📚 *Выбери материал для квиза:*',
    youHaveMaterial: (n) => `У тебя ${n} сохранённ${n === 1 ? 'ый материал' : 'ых материала'}.`,
    noMaterials: '📭 *Сохранённых материалов пока нет.*\n\nОтправь `/learn [URL]` чтобы добавить.'
  }
};

const chatId = $('Telegram Trigger1').item.json.message.chat.id;
const rows = $('/quiz: pg SELECT materials').all().map(i => i.json);
const lang = $('lang: pg load /quiz').item.json.lang || 'en';
const t = T[lang] || T.en;

let text, reply_markup;
if (!rows || rows.length === 0 || !rows[0].id) {
  text = t.noMaterials;
  reply_markup = undefined;
} else {
  const diffEmoji = { beginner: '🟢', intermediate: '🟡', advanced: '🔴' };
  const inline_keyboard = rows.map((r) => [{
    text: `${diffEmoji[r.difficulty] || '⚪'} ${(r.title || 'Untitled').slice(0, 60)}`,
    callback_data: `pick:${r.id}`
  }]);
  text = `${t.pickTopic}\n\n${t.youHaveMaterial(rows.length)}`;
  reply_markup = { inline_keyboard };
}

const payload = { chat_id: chatId, text, parse_mode: 'Markdown' };
if (reply_markup) payload.reply_markup = reply_markup;
const body_json = JSON.stringify(payload);
return [{ json: { chat_id: chatId, body_json } }];"""

for n in nodes:
    if n.get('name') == '/quiz: build topic keyboard':
        n['parameters']['jsCode'] = QUIZ_BUILD_KEYBOARD_JS
        sys.stderr.write("Patched /quiz: build topic keyboard (localized)\n")

# ============================================================
# Save
# ============================================================
with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
