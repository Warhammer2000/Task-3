"""Patch 16: replace /learn ack text with "1-3 min" wording (localized),
add new pick: ack node that warns user before Examiner LLM call kicks in."""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

def new_id():
    return str(uuid.uuid4())

# ============================================================
# /learn ack — localized via Telegram's from.language_code
# ============================================================
LEARN_ACK_BODY = (
    "={ \"chat_id\": {{ $json.chat_id }}, "
    "\"text\": \"{{ ($('Telegram Trigger1').item.json.message?.from?.language_code || '').startsWith('ru') "
    "? '\\u{1F50D} \\u0427\\u0438\\u0442\\u0430\\u044E \\u0441\\u0442\\u0430\\u0442\\u044C\\u044E "
    "\\u0438 \\u043F\\u0440\\u043E\\u0433\\u043E\\u043D\\u044F\\u044E \\u0447\\u0435\\u0440\\u0435\\u0437 "
    "Claude Opus 4.7 \\u2014 \\u043E\\u0431\\u044B\\u0447\\u043D\\u043E 1\\u20133 \\u043C\\u0438\\u043D\\u0443\\u0442\\u044B.' "
    ": '\\u{1F50D} Reading the article and distilling it with Claude Opus 4.7 \\u2014 usually 1\\u20133 minutes.' }}\" }"
)
# That expression-string is fragile. Use a simpler approach: build the text in a Code node, then send via HTTP Request.
# Actually the cleanest: add a small "build ack text" Code node before send ack.

LEARN_BUILD_ACK_JS = r"""// Build localized /learn ack text
const tgLang = $('Telegram Trigger1').item.json.message?.from?.language_code || 'en';
const ru = tgLang.startsWith('ru');
const chatId = $('Telegram Trigger1').item.json.message.chat.id;

const text = ru
  ? '🔍 Читаю статью и прогоняю через Claude Opus 4.7 для саммари — обычно 1–3 минуты, можно отойти заварить чай ☕'
  : '🔍 Reading the article and distilling it with Claude Opus 4.7 — usually 1–3 minutes, grab a coffee ☕';

const body_json = JSON.stringify({ chat_id: chatId, text });
return [{ json: { chat_id: chatId, body_json } }];"""

# Find /learn: send ack node and refactor: prepend a build node, change send to use body_json
learn_ack_idx = None
learn_ack_pos = None
for i, n in enumerate(nodes):
    if n.get('name') == '/learn: send ack (loading)':
        learn_ack_idx = i
        learn_ack_pos = n.get('position', [0, 0])
        break

if learn_ack_idx is not None:
    # Create new Code node before it
    build_ack = {
        "parameters": {"jsCode": LEARN_BUILD_ACK_JS},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [learn_ack_pos[0] - 200, learn_ack_pos[1]],
        "id": new_id(),
        "name": "/learn: build ack text"
    }
    nodes.append(build_ack)
    # Update send node to use body_json from build
    nodes[learn_ack_idx]['parameters']['jsonBody'] = '={{ $json.body_json }}'
    sys.stderr.write("Added /learn: build ack text + updated send to use body_json\n")

# Connections: insert build before send
# URL valid? main[0] currently goes to [send ack, jina fetch, react thinking]
# Replace [send ack] entry with [build ack text]; then build -> send
url_valid = connections.get('/learn: URL valid?', {})
if url_valid:
    for branch in url_valid.get('main', []):
        for tgt in branch:
            if tgt.get('node') == '/learn: send ack (loading)':
                tgt['node'] = '/learn: build ack text'
    sys.stderr.write("Rewired URL valid? -> build ack text\n")

connections['/learn: build ack text'] = {
    "main": [[{"node": "/learn: send ack (loading)", "type": "main", "index": 0}]]
}

# ============================================================
# pick: ack — warn user about Examiner generation taking 1-3 min
# ============================================================
PICK_BUILD_ACK_JS = r"""// Build localized pick ack text (fires right after material loaded)
const lang = $('lang: pg load pick').item.json.lang || 'en';
const chatId = $('pick: pg load material').item.json.chat_id;
const title = $('pick: pg load material').item.json.title || '';

const text = lang === 'ru'
  ? `🎯 Генерирую 5 senior-level вопросов по теме "${title}" через Claude Haiku 4.5 — обычно 30 секунд – 2 минуты.\n\nКак только готово — пришлю первый вопрос как Telegram-опрос.`
  : `🎯 Generating 5 senior-level questions on "${title}" with Claude Haiku 4.5 — usually 30 seconds – 2 minutes.\n\nFirst question will arrive as a Telegram poll.`;

const body_json = JSON.stringify({ chat_id: chatId, text });
return [{ json: { chat_id: chatId, body_json } }];"""

pick_build_ack = {
    "parameters": {"jsCode": PICK_BUILD_ACK_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [-400, 700],
    "id": new_id(),
    "name": "pick: build ack text"
}
pick_send_ack = {
    "parameters": {
        "method": "POST",
        "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ $json.body_json }}",
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [-200, 700],
    "id": new_id(),
    "name": "pick: send ack"
}
nodes.extend([pick_build_ack, pick_send_ack])
sys.stderr.write("Added pick: build ack text + pick: send ack\n")

# Wire: lang: pg load pick currently goes to pick: build examiner body
# Want: lang: pg load pick -> [pick: build ack text, pick: build examiner body] (parallel)
# ack chain: pick: build ack text -> pick: send ack (terminal)
lang_pick = connections.get('lang: pg load pick', {})
if lang_pick:
    # Add ack branch in parallel to existing examiner body branch
    main = lang_pick.get('main', [[]])
    if main and main[0]:
        # Append ack target to existing branch (so both run in parallel)
        main[0].append({"node": "pick: build ack text", "type": "main", "index": 0})
        lang_pick['main'] = main
        sys.stderr.write("Wired lang: pg load pick -> + pick: build ack text (parallel)\n")

connections['pick: build ack text'] = {
    "main": [[{"node": "pick: send ack", "type": "main", "index": 0}]]
}

# Save
with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write(f"\nTotal nodes: {len(nodes)}\n")
