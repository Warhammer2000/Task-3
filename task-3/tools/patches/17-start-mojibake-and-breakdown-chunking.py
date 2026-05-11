"""Patch 17: fix /start mojibake (rewrite with clean UTF-8 + convert to HTTP
Request) + chunk breakdown into multiple messages if > 3500 chars."""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# ============================================================
# 1. Fix /start: replace Telegram node with localized HTTP Request that
#    builds clean text in a Code node first.
# ============================================================
START_BUILD_JS = r"""// Build localized /start welcome message
const tgLang = $('Telegram Trigger1').item.json.message?.from?.language_code || 'en';
const ru = tgLang.startsWith('ru');
const chatId = $('Telegram Trigger1').item.json.message.chat.id;

const text = ru
  ? `👋 *Добро пожаловать в Senior Interview Coach!*

Я AI-бот для подготовки к senior backend интервью — построен на n8n + Claude (Opus 4.7 Teacher, Haiku 4.5 Examiner).

*Что я умею:*

📚 \`/learn [URL]\` — отправь URL статьи / документации / блог-поста → я извлеку контент и сделаю структурированное саммари (5-7 ключевых пунктов + основные концепции + уровень сложности), откалиброванное под senior-планку.

🎯 \`/quiz\` — выбери материал из своих сохранённых → я сгенерирую 5 вопросов senior-уровня с интеллектуальной валидацией ответов и объяснениями.

📊 \`/stats\` — посмотри свой learning-дашборд (материалы, пройденные квизы, средний балл) + кнопка для открытия Mini App с графиками.

🌐 \`/lang\` — переключи язык бота (English / Русский).

🔍 \`@seniorprepcoach_bot <запрос>\` — поиск по своим материалам из любого чата (inline mode).

*Попробуй прямо сейчас:*
\`/learn https://martinfowler.com/articles/microservices.html\``
  : `👋 *Welcome to Senior Interview Coach!*

I'm an AI-powered learning bot for senior backend interview prep — built on n8n + Claude (Opus 4.7 Teacher, Haiku 4.5 Examiner).

*What I can do:*

📚 \`/learn [URL]\` — submit any article / docs / blog post URL → I'll extract the content and produce a structured summary (5-7 key points + main concepts + difficulty) calibrated to the senior backend bar.

🎯 \`/quiz\` — pick from your saved materials → I'll generate 5 senior-level multiple-choice questions with intelligent answer validation and explanations.

📊 \`/stats\` — see your learning dashboard (materials, quizzes taken, average score) + Mini App with charts.

🌐 \`/lang\` — switch bot language (English / Русский).

🔍 \`@seniorprepcoach_bot <query>\` — search your materials inline from any chat.

*Try me right now:*
\`/learn https://martinfowler.com/articles/microservices.html\``;

const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
return [{ json: { chat_id: chatId, body_json } }];"""

# Find Reply /start1 node — repurpose it as build node and add new send node
start_node = None
start_idx = None
for i, n in enumerate(nodes):
    if n.get('name') == 'Reply /start1':
        start_node = n
        start_idx = i
        break

if start_node:
    old_pos = start_node.get('position', [0, 0])
    old_id = start_node['id']
    # Convert in place: was Telegram node, now becomes a Code build node
    start_node.clear()
    start_node.update({
        "parameters": {"jsCode": START_BUILD_JS},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": old_pos,
        "id": old_id,
        "name": "/start: build text"
    })
    sys.stderr.write("Repurposed Reply /start1 -> /start: build text (Code)\n")

    # Add send node
    send_node = {
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
        "position": [old_pos[0] + 200, old_pos[1]],
        "id": str(uuid.uuid4()),
        "name": "/start: send"
    }
    nodes.append(send_node)
    sys.stderr.write("Added /start: send (HTTP Request)\n")

# ============================================================
# 2. Replace ans: format results to CHUNK breakdown if > 3500 chars
# ============================================================
ANS_FORMAT_RESULTS_JS = r"""const T = {
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
    noHistoryHint: 'Send `/learn [URL]` to add your first material — once you take a quiz, your stats will show up here.',
    retentionTip: 'Tip: re-quiz a topic after a few days to test retention.',
    never: 'never',
    quizComplete: 'Quiz complete',
    youPicked: 'you picked',
    correctMark: 'Correct',
    breakdownFooter: 'Open /stats for your dashboard, or /learn [URL] for a new topic.',
    breakdownPart: 'Part',
    headlineStrong: 'Strong recall — material internalised.',
    headlineSolid: 'Solid baseline — re-skim what you missed.',
    headlineHalf: 'Halfway there — re-read and re-quiz.',
    headlineWeak: 'Worth a deep re-read — try again tomorrow.'
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
    noHistoryHint: 'Отправь `/learn [URL]` чтобы добавить первый материал — после первого квиза тут появится статистика.',
    retentionTip: 'Совет: пройди квиз заново через несколько дней — проверишь retention.',
    never: 'никогда',
    quizComplete: 'Квиз завершён',
    youPicked: 'ты выбрал',
    correctMark: 'Правильно',
    breakdownFooter: 'Открой /stats для дашборда или /learn [URL] чтобы добавить ещё материал.',
    breakdownPart: 'Часть',
    headlineStrong: 'Сильный recall — материал усвоен.',
    headlineSolid: 'Базовый уровень — повтори то, что пропустил.',
    headlineHalf: 'Половина пути — перечитай и проходи квиз снова.',
    headlineWeak: 'Стоит глубоко перечитать — попробуй завтра ещё раз.'
  }
};


const answers = $('ans: pg load all answers').all().map(i => i.json);

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

// HEADLINE (with effect)
const headlineText = `${badge} <b>${t.quizComplete}: ${correctCount}/${total} (${pct}%)</b>\n<i>${h(tagline)}</i>`;
const headlineBody = { chat_id: chatId, text: headlineText, parse_mode: 'HTML' };
if (effectId) headlineBody.message_effect_id = effectId;
const body_headline = JSON.stringify(headlineBody);

// BREAKDOWN — chunk into pieces ≤ 3500 chars
// Build per-question blocks first
const blocks = answers.map(a => {
  const q = questions.find(qq => qq.id === a.question_id);
  const mark = a.correct ? '✅' : '❌';
  const userOpt = h(q?.options?.[a.user_answer] || '');
  const correctLetter = q?.correctAnswer || '?';
  const correctOpt = h(q?.options?.[correctLetter] || '');

  let block = `${mark} <b>${a.question_id}</b> — ${t.youPicked} <i>${h(a.user_answer)}</i>: ${userOpt}`;
  if (!a.correct) {
    block += `\n     ✓ ${t.correctMark}: <b>${h(correctLetter)}</b> — ${correctOpt}`;
    if (q?.explanation) block += `\n     💡 <i>${h(q.explanation)}</i>`;
  }
  return block;
});

// Greedy pack blocks into chunks
const MAX_LEN = 3500;
const chunks = [];
let current = '';
for (const block of blocks) {
  const sep = current ? '\n\n' : '';
  if (current.length + sep.length + block.length > MAX_LEN && current) {
    chunks.push(current);
    current = block;
  } else {
    current = current + sep + block;
  }
}
if (current) chunks.push(current);

// Append footer to last chunk
chunks[chunks.length - 1] += `\n\n${t.breakdownFooter}`;

// Emit one item per chunk; HTTP Request will iterate over items
const items = chunks.map((text, i) => {
  let prefixedText = text;
  if (chunks.length > 1) {
    prefixedText = `<b>${t.breakdownPart} ${i + 1}/${chunks.length}</b>\n\n` + text;
  }
  const body_json = JSON.stringify({ chat_id: chatId, text: prefixedText, parse_mode: 'HTML' });
  return { json: { chat_id: chatId, body_headline, body_breakdown: body_json, chunk_index: i, total_chunks: chunks.length } };
});

return items;"""

for n in nodes:
    if n.get('name') == 'ans: format results':
        n['parameters']['jsCode'] = ANS_FORMAT_RESULTS_JS
        sys.stderr.write("Patched ans: format results (chunked breakdown)\n")

# ans: send breakdown will automatically iterate over the multiple items
# because n8n HTTP Request runs once per input item by default.
# Note: ans: send headline only uses the first item (executeOnce-like behavior
# is the default but n8n will actually run headline N times too — need to
# make headline only fire once)

# Best approach: split the data so headline gets one item, breakdown gets many.
# Easier: use a Split node, or just emit only one item from format results
# and handle the chunking inside the breakdown HTTP node via item iteration.
#
# Actually n8n behavior: HTTP Request runs once per input item by default.
# If format-results emits 3 items, headline runs 3 times too (sends headline 3x).
# To avoid: set "Execute Once" mode on headline node.

for n in nodes:
    if n.get('name') == 'ans: send headline':
        # Set execute once
        n['parameters'].setdefault('options', {})['neverError'] = False
        n['parameters'].setdefault('executeOnce', True)
        # n8n parameter for execute once on each item is "executeOnce" on the node itself
        # but parameters.executeOnce is the right path for newer versions
        sys.stderr.write("Set ans: send headline to execute once\n")
        # Also set it at the node level:
        n['executeOnce'] = True

# Save
with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)

# Also need to update connections — but since we just renamed Reply /start1
# in place (kept same id), and the Route already points to that id, we need
# to rewire by NAME.

with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# Route main[0] originally goes to Reply /start1; we renamed it to /start: build text
for src_name, conf in connections.items():
    for branch in conf.get('main', []):
        for tgt in branch:
            if tgt.get('node') == 'Reply /start1':
                tgt['node'] = '/start: build text'
                sys.stderr.write(f"Rewired {src_name} ref Reply /start1 -> /start: build text\n")

# Connect /start: build text -> /start: send
connections['/start: build text'] = {
    "main": [[{"node": "/start: send", "type": "main", "index": 0}]]
}
sys.stderr.write("Wired /start: build text -> /start: send\n")

with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Done.\n")
