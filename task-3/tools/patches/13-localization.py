"""Patch 13: full RU/EN localization.

Adds:
- `/lang` command with [🇬🇧 English | 🇷🇺 Русский] picker
- `lang_cb` callback handler -> upserts user_state.lang -> sends confirm
- `lang: pg load` Postgres lookup node placed BEFORE each branch that
  formats user-visible text or builds an LLM prompt
- Localized strings in `/stats: format`, `/learn: format summary`,
  `ans: format results`, and (via separate edit) the LLM system prompts
  in `/learn: extract title+body` and `pick: build examiner body`.

Assumes schema migration ran already:
    ALTER TABLE app.user_state ADD COLUMN IF NOT EXISTS lang TEXT
        NOT NULL DEFAULT 'en' CHECK (lang IN ('en','ru'));
"""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# Find Postgres credentials by copying from existing pg node
PG_CREDS = None
for n in nodes:
    if n.get('type','').endswith('postgres') and n.get('credentials'):
        PG_CREDS = n['credentials']
        break

def new_id():
    return str(uuid.uuid4())

# ============================================================
# Lang lookup SQL — chat_id can come from message / callback / poll_answer / inline_query
# ============================================================
LANG_LOOKUP_SQL = (
    "SELECT COALESCE(\n"
    "  (SELECT lang FROM app.user_state WHERE chat_id = {{ Number(\n"
    "    $('Telegram Trigger1').item.json.message?.chat?.id\n"
    "    ?? $('Telegram Trigger1').item.json.callback_query?.from?.id\n"
    "    ?? $('Telegram Trigger1').item.json.poll_answer?.user?.id\n"
    "    ?? $('Telegram Trigger1').item.json.inline_query?.from?.id\n"
    "    ?? 0\n"
    "  ) }}),\n"
    "  'en'\n"
    ") AS lang;"
)

def lang_load_node(name, pos):
    return {
        "parameters": {
            "operation": "executeQuery",
            "query": LANG_LOOKUP_SQL,
            "options": {}
        },
        "type": "n8n-nodes-base.postgres",
        "typeVersion": 2.6,
        "position": pos,
        "id": new_id(),
        "name": name,
        "credentials": PG_CREDS
    }

# ============================================================
# /lang command — sends picker
# ============================================================
LANG_PICKER_JS = r"""// Build /lang picker keyboard
const chatId = $('Telegram Trigger1').item.json.message.chat.id;
const tgLang = $('Telegram Trigger1').item.json.message.from?.language_code || 'en';
const ruDefault = tgLang.startsWith('ru');

const text = ruDefault
  ? '🌐 Выбери язык бота:\n\nThis sets the language of bot replies, quiz questions, and summaries.'
  : '🌐 Choose bot language:\n\nЭто переключает язык ответов бота, квизов и summary.';

const body_json = JSON.stringify({
  chat_id: chatId,
  text,
  reply_markup: {
    inline_keyboard: [[
      { text: '🇬🇧 English', callback_data: 'lang:en' },
      { text: '🇷🇺 Русский', callback_data: 'lang:ru' }
    ]]
  }
});

return [{ json: { chat_id: chatId, body_json } }];"""

LANG_PICKER_BUILD = {
    "parameters": {"jsCode": LANG_PICKER_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [-200, 200],
    "id": new_id(),
    "name": "/lang: build picker"
}

LANG_PICKER_SEND = {
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
    "position": [0, 200],
    "id": new_id(),
    "name": "/lang: send picker"
}

# ============================================================
# lang:<en|ru> callback — upsert + confirm
# ============================================================
LANG_CB_PARSE_JS = r"""// Parse callback_data 'lang:en' or 'lang:ru'
const cq = $('Telegram Trigger1').item.json.callback_query;
const data = cq?.data || '';
const lang = data.split(':')[1];

if (!['en', 'ru'].includes(lang)) {
  throw new Error('Invalid lang: ' + lang);
}

return [{
  json: {
    chat_id: cq.from.id,
    callback_query_id: cq.id,
    lang,
    message_id: cq.message?.message_id
  }
}];"""

LANG_CB_PARSE = {
    "parameters": {"jsCode": LANG_CB_PARSE_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [-200, 400],
    "id": new_id(),
    "name": "lang_cb: parse"
}

LANG_CB_UPSERT_SQL = (
    "INSERT INTO app.user_state (chat_id, lang)\n"
    "VALUES ({{ $json.chat_id }}, '{{ $json.lang }}')\n"
    "ON CONFLICT (chat_id) DO UPDATE SET lang = EXCLUDED.lang\n"
    "RETURNING chat_id, lang;"
)

LANG_CB_UPSERT = {
    "parameters": {
        "operation": "executeQuery",
        "query": LANG_CB_UPSERT_SQL,
        "options": {}
    },
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [0, 400],
    "id": new_id(),
    "name": "lang_cb: pg upsert",
    "credentials": PG_CREDS
}

LANG_CB_CONFIRM_JS = r"""// Build confirm reply + answerCallbackQuery
const row = $input.first().json;
const chatId = $('lang_cb: parse').item.json.chat_id;
const callbackQueryId = $('lang_cb: parse').item.json.callback_query_id;
const lang = row.lang;

const text = lang === 'ru'
  ? '✅ Язык установлен: *Русский*\n\nТеперь бот будет отвечать на русском, генерировать summary и квизы тоже по-русски. Можно переключить обратно через /lang.'
  : '✅ Language set: *English*\n\nBot replies, summaries, and quizzes will now be in English. Use /lang to switch back.';

const alertText = lang === 'ru' ? 'Русский ✅' : 'English ✅';

const send_body = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
const ack_body = JSON.stringify({ callback_query_id: callbackQueryId, text: alertText });

return [{ json: { send_body, ack_body, chat_id: chatId } }];"""

LANG_CB_CONFIRM = {
    "parameters": {"jsCode": LANG_CB_CONFIRM_JS},
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [200, 400],
    "id": new_id(),
    "name": "lang_cb: build confirm"
}

LANG_CB_SEND = {
    "parameters": {
        "method": "POST",
        "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ $json.send_body }}",
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [400, 400],
    "id": new_id(),
    "name": "lang_cb: send confirm"
}

LANG_CB_ACK = {
    "parameters": {
        "method": "POST",
        "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/answerCallbackQuery",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ $('lang_cb: build confirm').item.json.ack_body }}",
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [600, 400],
    "id": new_id(),
    "name": "lang_cb: ack"
}

# ============================================================
# I18n strings dict — shared across Code nodes
# ============================================================
I18N_DICT_JS = r"""const T = {
  en: {
    keyPoints: 'Key points',
    concepts: 'Concepts',
    interviewAngle: 'Interview angle',
    takeQuizNow: '🎯 Take quiz now',
    summaryFooter: 'Tap below to test yourself with 5 interview-style questions.',
    materialsSaved: 'Materials saved',
    quizzesTaken: 'Quizzes taken',
    avgScore: 'Average score',
    lastQuiz: 'Last quiz',
    yourDashboard: 'Your learning dashboard',
    openDashboard: '📈 Open full dashboard',
    noHistory: 'No learning history yet.',
    noHistoryHint: 'Send `/learn <url>` to add your first material — once you take a quiz, your stats will show up here.',
    retentionTip: 'Tip: re-quiz a topic after a few days to test retention.',
    never: 'never',
    quizComplete: 'Quiz complete',
    youPicked: 'you picked',
    correctMark: 'Correct',
    breakdownFooter: 'Open /stats for your dashboard, or /learn <url> for a new topic.',
    headlineStrong: 'Strong recall — material internalised.',
    headlineSolid: 'Solid baseline — re-skim what you missed.',
    headlineHalf: 'Halfway there — re-read and re-quiz.',
    headlineWeak: 'Worth a deep re-read — try again tomorrow.',
    chooseDifficulty: 'beginner',
    chooseLearningMaterial: 'Choose a learning material',
    quizPickPrompt: 'Tap a material to start a quiz:',
    noMaterialsYet: 'You have no saved materials yet. Send /learn <url> to add one.',
    helpUnknown: 'Try /learn <url>, /quiz, /stats, /lang or @' + 'seniorprepcoach_bot in any chat.'
  },
  ru: {
    keyPoints: 'Ключевые моменты',
    concepts: 'Концепции',
    interviewAngle: 'Угол на интервью',
    takeQuizNow: '🎯 Пройти квиз',
    summaryFooter: 'Нажми кнопку ниже, чтобы пройти 5 вопросов senior-уровня по этому материалу.',
    materialsSaved: 'Материалов сохранено',
    quizzesTaken: 'Квизов пройдено',
    avgScore: 'Средний балл',
    lastQuiz: 'Последний квиз',
    yourDashboard: 'Твой learning-дашборд',
    openDashboard: '📈 Открыть полный дашборд',
    noHistory: 'Ещё нет истории обучения.',
    noHistoryHint: 'Отправь `/learn <url>` чтобы добавить первый материал — после первого квиза тут появится статистика.',
    retentionTip: 'Совет: пройди квиз заново через несколько дней — проверишь retention.',
    never: 'никогда',
    quizComplete: 'Квиз завершён',
    youPicked: 'ты выбрал',
    correctMark: 'Правильно',
    breakdownFooter: 'Открой /stats для дашборда или /learn <url> чтобы добавить ещё материал.',
    headlineStrong: 'Сильный recall — материал усвоен.',
    headlineSolid: 'Базовый уровень — повтори то, что пропустил.',
    headlineHalf: 'Половина пути — перечитай и проходи квиз снова.',
    headlineWeak: 'Стоит глубоко перечитать — попробуй завтра ещё раз.',
    chooseDifficulty: 'начальный',
    chooseLearningMaterial: 'Выбери материал для квиза',
    quizPickPrompt: 'Нажми на материал чтобы начать квиз:',
    noMaterialsYet: 'Сохранённых материалов пока нет. Отправь /learn <url> чтобы добавить.',
    helpUnknown: 'Попробуй /learn <url>, /quiz, /stats, /lang или @' + 'seniorprepcoach_bot в любом чате.'
  }
};
"""

# ============================================================
# Updated /stats: format with localization
# ============================================================
STATS_FORMAT_JS = I18N_DICT_JS + r"""

const chatId = $('Telegram Trigger1').item.json.message.chat.id;
const row = $input.first().json;
const lang = (row && row.lang) || $('lang: pg load /stats').item.json.lang || 'en';
const t = T[lang] || T.en;

const dashUrl = `https://seniorprepcoach.ngrok.dev/webhook/dashboard?chat_id=${chatId}&lang=${lang}`;
const reply_markup = {
  inline_keyboard: [[
    { text: t.openDashboard, web_app: { url: dashUrl } }
  ]]
};

if (!row || row.materials_count === undefined || row.materials_count === null || row.materials_count === 0) {
  const text = `📊 *${t.noHistory}*\n\n${t.noHistoryHint}`;
  const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
  return [{ json: { chat_id: chatId, text, body_json } }];
}

function bar(n, total = 10) {
  const filled = Math.min(total, Math.max(0, Math.round((n / 100) * total)));
  return '█'.repeat(filled) + '░'.repeat(total - filled);
}

const score = Number(row.avg_score_pct) || 0;
const lastQuiz = row.last_quiz_at ? new Date(row.last_quiz_at).toISOString().split('T')[0] : t.never;

const lines = [
  `📊 *${t.yourDashboard}*`,
  '',
  `📚 *${t.materialsSaved}:* ${row.materials_count}`,
  `   🟢 beginner: ${row.beginner_materials || 0}`,
  `   🟡 intermediate: ${row.intermediate_materials || 0}`,
  `   🔴 advanced: ${row.advanced_materials || 0}`,
  '',
  `🎯 *${t.quizzesTaken}:* ${row.quizzes_taken || 0}`,
  `📈 *${t.avgScore}:* ${score}%`,
  `      \`${bar(score)}\``,
  `🕒 *${t.lastQuiz}:* ${lastQuiz}`,
  '',
  `_${t.retentionTip}_`,
];

const text = lines.join('\n');
const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown', reply_markup });
return [{ json: { chat_id: chatId, text, body_json } }];"""

# ============================================================
# Updated /learn: format summary with localization
# ============================================================
LEARN_FORMAT_JS = I18N_DICT_JS + r"""

const row = $input.first().json;
const materialId = row.id;
const chatId = row.chat_id;
const title = row.title || 'Untitled';
const summary = row.summary_json;
const lang = $('lang: pg load /learn').item.json.lang || 'en';
const t = T[lang] || T.en;

function esc(s) { return String(s == null ? '' : s).replace(/([_*`\[])/g, '\\$1'); }

const diffEmoji = { beginner: '🟢', intermediate: '🟡', advanced: '🔴' }[summary.difficulty] || '⚪';

const keyPointsBlock = summary.key_points.map((p, i) => `${i + 1}. ${esc(p)}`).join('\n');
const conceptsBlock = summary.main_concepts.map((c) => `\`${esc(c)}\``).join(' · ');
const interviewBlock = summary.interview_angle ? `\n💡 *${t.interviewAngle}:* _${esc(summary.interview_angle)}_` : '';

const text = `📚 *${esc(title)}*\n${diffEmoji} _${esc(summary.difficulty)}_\n\n*${t.keyPoints}:*\n${keyPointsBlock}\n\n*${t.concepts}:* ${conceptsBlock}${interviewBlock}\n\n${t.summaryFooter}`;

const reply_markup = {
  inline_keyboard: [[{ text: t.takeQuizNow, callback_data: `pick:${materialId}` }]]
};

const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown', reply_markup });
return [{ json: { chat_id: chatId, text, reply_markup, body_json } }];"""

# ============================================================
# Updated ans: format results with localization + split + HTML + effect
# ============================================================
ANS_FORMAT_RESULTS_JS = I18N_DICT_JS + r"""

const answers = $input.all().map(i => i.json);

const src = $('poll_ans: validate').isExecuted
  ? $('poll_ans: validate').item.json
  : $('ans: validate').item.json;
const chatId = src.chat_id;
const lang = $('lang: pg load /ans').item.json.lang || 'en';
const t = T[lang] || T.en;

const raw = answers[0]?.questions;
const questions = (raw && raw.questions) || raw;

const correctCount = answers.filter(a => a.correct).length;
const total = answers.length;
const pct = Math.round(100 * correctCount / total);

let badge, effectId, tagline;
if (pct >= 80)      { badge = '🏆'; effectId = '5104841245755180586'; tagline = t.headlineStrong; }
else if (pct >= 60) { badge = '✨'; effectId = '5046509860389126442'; tagline = t.headlineSolid; }
else if (pct >= 40) { badge = '💡'; effectId = '5107584321108051014'; tagline = t.headlineHalf; }
else                { badge = '🥊'; effectId = '5104858069142078462'; tagline = t.headlineWeak; }

function h(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// SHORT HEADLINE (with effect)
const headlineText = `${badge} <b>${t.quizComplete}: ${correctCount}/${total} (${pct}%)</b>\n<i>${h(tagline)}</i>`;
const headlineBody = { chat_id: chatId, text: headlineText, parse_mode: 'HTML' };
if (effectId) headlineBody.message_effect_id = effectId;
const body_headline = JSON.stringify(headlineBody);

// LONG BREAKDOWN (no effect)
const lines = [];
for (const a of answers) {
  const q = questions.find(qq => qq.id === a.question_id);
  const mark = a.correct ? '✅' : '❌';
  const userOpt = h(q?.options?.[a.user_answer] || '');
  const correctLetter = q?.correctAnswer || '?';
  const correctOpt = h(q?.options?.[correctLetter] || '');

  lines.push(`${mark} <b>${a.question_id}</b> — ${t.youPicked} <i>${h(a.user_answer)}</i>: ${userOpt}`);
  if (!a.correct) {
    lines.push(`     ✓ ${t.correctMark}: <b>${h(correctLetter)}</b> — ${correctOpt}`);
    if (q?.explanation) lines.push(`     💡 <i>${h(q.explanation)}</i>`);
  }
  lines.push('');
}
lines.push(t.breakdownFooter);

const breakdownText = lines.join('\n');
const body_breakdown = JSON.stringify({ chat_id: chatId, text: breakdownText, parse_mode: 'HTML' });

return [{ json: { chat_id: chatId, body_headline, body_breakdown } }];"""

# ============================================================
# Teacher prompt — inject lang directive
# ============================================================
LEARN_EXTRACT_JS_FRAGMENT = """
const lang = $('lang: pg load /learn').item.json.lang || 'en';
const langDirective = lang === 'ru'
  ? '\\n\\nAll output strings (title, summary, key_points, main_concepts, interview_angle) must be in Russian. Difficulty value stays English: beginner/intermediate/advanced.'
  : '';
"""

# ============================================================
# Examiner prompt — inject lang directive
# ============================================================
PICK_BUILD_JS_FRAGMENT = """
const lang = $('lang: pg load pick').item.json.lang || 'en';
const langDirective = lang === 'ru'
  ? '\\n\\nAll output strings (question, options A/B/C/D, explanation) must be in Russian. Answer letters stay A/B/C/D.'
  : '';
"""

# ============================================================
# Apply patches
# ============================================================
# 1. Add new nodes
new_nodes = [
    LANG_PICKER_BUILD, LANG_PICKER_SEND,
    LANG_CB_PARSE, LANG_CB_UPSERT, LANG_CB_CONFIRM, LANG_CB_SEND, LANG_CB_ACK,
    lang_load_node('lang: pg load /learn', [-700, -300]),
    lang_load_node('lang: pg load /stats', [-700, 100]),
    lang_load_node('lang: pg load /ans',   [-720, -300]),
    lang_load_node('lang: pg load pick',   [-700, 500]),
    lang_load_node('lang: pg load /quiz',  [-700, 300]),
]
nodes.extend(new_nodes)

# 2. Replace code in existing nodes
patches_js = {
    '/stats: format':       STATS_FORMAT_JS,
    '/learn: format summary': LEARN_FORMAT_JS,
    'ans: format results':  ANS_FORMAT_RESULTS_JS,
}

for n in nodes:
    name = n.get('name','')
    if name in patches_js:
        n['parameters']['jsCode'] = patches_js[name]
        sys.stderr.write(f"Patched jsCode: {name}\n")
    if name == '/learn: extract title+body':
        cur = n['parameters'].get('jsCode','')
        # Inject lang fetch after first line + use in systemPrompt
        if 'lang: pg load /learn' not in cur:
            new_js = LEARN_EXTRACT_JS_FRAGMENT + cur
            # Append langDirective to systemPrompt string
            new_js = new_js.replace(
                "const systemPrompt =",
                "let systemPrompt ="
            )
            new_js = new_js.replace(
                "model: 'claude-opus-4-5'",
                "model: 'claude-opus-4-5'"  # placeholder, real edit below
            )
            # Append directive to systemPrompt before its closing semicolon
            # Find the last quote ending the systemPrompt assignment and append
            new_js = new_js.replace(
                'systemPrompt += langDirective;\n',
                ''  # remove any stale
            )
            # Insert after the prompt is declared:
            # Easy: search for first ';\n' after `systemPrompt =` and inject our directive
            idx = new_js.find('systemPrompt =')
            if idx >= 0:
                # find end of this declaration: look for `";` then newline
                semi_idx = new_js.find('";\n', idx)
                if semi_idx > 0:
                    new_js = new_js[:semi_idx+2] + '\nsystemPrompt += langDirective;\n' + new_js[semi_idx+2:]
            n['parameters']['jsCode'] = new_js
            sys.stderr.write("Injected lang directive into /learn: extract title+body\n")
    if name == 'pick: build examiner body':
        cur = n['parameters'].get('jsCode','')
        if 'lang: pg load pick' not in cur:
            new_js = PICK_BUILD_JS_FRAGMENT + cur
            new_js = new_js.replace(
                'const systemPrompt =',
                'let systemPrompt ='
            )
            idx = new_js.find('systemPrompt =')
            if idx >= 0:
                semi_idx = new_js.find('";\n', idx)
                if semi_idx > 0:
                    new_js = new_js[:semi_idx+2] + '\nsystemPrompt += langDirective;\n' + new_js[semi_idx+2:]
            n['parameters']['jsCode'] = new_js
            sys.stderr.write("Injected lang directive into pick: build examiner body\n")

# 3. Add /lang and lang_cb rules to Route Switch
for n in nodes:
    if n.get('name') == 'Route':
        rules = n['parameters'].setdefault('rules', {}).setdefault('values', [])
        # Check if /lang rule exists
        has_lang_cmd = any(
            any(c.get('id') == 'c-lang-cmd' for c in r.get('conditions', {}).get('conditions', []))
            for r in rules
        )
        if not has_lang_cmd:
            rules.append({
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                    "conditions": [{
                        "id": "c-lang-cmd",
                        "leftValue": "={{ $json.message?.text || '' }}",
                        "rightValue": "/lang",
                        "operator": {"type": "string", "operation": "startsWith"}
                    }],
                    "combinator": "and"
                },
                "renameOutput": True,
                "outputKey": "/lang"
            })
            sys.stderr.write("Added /lang Route rule\n")
        has_lang_cb = any(
            any(c.get('id') == 'c-lang-cb' for c in r.get('conditions', {}).get('conditions', []))
            for r in rules
        )
        if not has_lang_cb:
            rules.append({
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                    "conditions": [{
                        "id": "c-lang-cb",
                        "leftValue": "={{ $json.callback_query?.data || '' }}",
                        "rightValue": "lang:",
                        "operator": {"type": "string", "operation": "startsWith"}
                    }],
                    "combinator": "and"
                },
                "renameOutput": True,
                "outputKey": "lang:cb"
            })
            sys.stderr.write("Added lang:cb Route rule\n")

# ============================================================
# Connection rewiring
# ============================================================
# Find Route current rule positions
# Existing rules order is fixed; new rules appended to end.
# Need to figure out their indices to wire main[N]

route_rules = []
for n in nodes:
    if n.get('name') == 'Route':
        route_rules = n['parameters'].get('rules', {}).get('values', [])
        break

# Find indices of /lang and lang:cb rules
lang_cmd_idx = next((i for i, r in enumerate(route_rules)
                     if any(c.get('id') == 'c-lang-cmd' for c in r.get('conditions',{}).get('conditions',[]))), None)
lang_cb_idx = next((i for i, r in enumerate(route_rules)
                    if any(c.get('id') == 'c-lang-cb' for c in r.get('conditions',{}).get('conditions',[]))), None)

sys.stderr.write(f"Route rule indices: /lang={lang_cmd_idx}, lang:cb={lang_cb_idx}\n")

# Update Route's connections.main to include /lang and lang:cb branches
route_conn = connections.setdefault('Route', {})
route_main = route_conn.setdefault('main', [])
# Ensure list is long enough
while len(route_main) <= max(lang_cmd_idx or 0, lang_cb_idx or 0, 6):
    route_main.append([])
if lang_cmd_idx is not None:
    route_main[lang_cmd_idx] = [{"node": "/lang: build picker", "type": "main", "index": 0}]
if lang_cb_idx is not None:
    route_main[lang_cb_idx] = [{"node": "lang_cb: parse", "type": "main", "index": 0}]
sys.stderr.write("Wired Route -> /lang and lang:cb branches\n")

# /lang branch
connections['/lang: build picker'] = {
    "main": [[{"node": "/lang: send picker", "type": "main", "index": 0}]]
}

# lang_cb branch
connections['lang_cb: parse'] = {
    "main": [[{"node": "lang_cb: pg upsert", "type": "main", "index": 0}]]
}
connections['lang_cb: pg upsert'] = {
    "main": [[{"node": "lang_cb: build confirm", "type": "main", "index": 0}]]
}
connections['lang_cb: build confirm'] = {
    "main": [[{"node": "lang_cb: send confirm", "type": "main", "index": 0}]]
}
connections['lang_cb: send confirm'] = {
    "main": [[{"node": "lang_cb: ack", "type": "main", "index": 0}]]
}

# Wire lang loaders into existing chains
# 1. /learn: between jina fetch and extract title+body
existing = connections.get('/learn: jina fetch', {}).get('main', [[]])
if existing and existing[0]:
    target = existing[0][0]['node']
    if target == '/learn: extract title+body':
        connections['/learn: jina fetch']['main'] = [
            [{"node": "lang: pg load /learn", "type": "main", "index": 0}]
        ]
        connections['lang: pg load /learn'] = {
            "main": [[{"node": "/learn: extract title+body", "type": "main", "index": 0}]]
        }
        sys.stderr.write("Inserted lang: pg load /learn between jina fetch and extract\n")

# 2. /stats: between pg load and format
stats_pg = connections.get('/stats: pg load', {}).get('main', [[]])
if stats_pg and stats_pg[0]:
    target = stats_pg[0][0]['node']
    if target == '/stats: format':
        connections['/stats: pg load']['main'] = [
            [{"node": "lang: pg load /stats", "type": "main", "index": 0}]
        ]
        connections['lang: pg load /stats'] = {
            "main": [[{"node": "/stats: format", "type": "main", "index": 0}]]
        }
        sys.stderr.write("Inserted lang: pg load /stats between pg load and format\n")

# 3. pick callback: between pg load material and build examiner body
pick_pg = connections.get('pick: pg load material', {}).get('main', [[]])
if pick_pg and pick_pg[0]:
    target = pick_pg[0][0]['node']
    if target == 'pick: build examiner body':
        connections['pick: pg load material']['main'] = [
            [{"node": "lang: pg load pick", "type": "main", "index": 0}]
        ]
        connections['lang: pg load pick'] = {
            "main": [[{"node": "pick: build examiner body", "type": "main", "index": 0}]]
        }
        sys.stderr.write("Inserted lang: pg load pick between pg load material and build body\n")

# 4. ans final: between ans: pg load all answers and ans: format results
ans_pg = connections.get('ans: pg load all answers', {}).get('main', [[]])
if ans_pg and ans_pg[0]:
    target = ans_pg[0][0]['node']
    if target == 'ans: format results':
        connections['ans: pg load all answers']['main'] = [
            [{"node": "lang: pg load /ans", "type": "main", "index": 0}]
        ]
        connections['lang: pg load /ans'] = {
            "main": [[{"node": "ans: format results", "type": "main", "index": 0}]]
        }
        sys.stderr.write("Inserted lang: pg load /ans between pg load all and format results\n")

# Save
with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)

sys.stderr.write(f"\nTotal nodes: {len(nodes)}\n")
