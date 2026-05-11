"""Mega-patch: setMessageReaction + message_effect_id + Mini App + Inline mode."""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# Find credential references (postgres + telegram) by copying from existing nodes
PG_CREDS = None
for n in nodes:
    if n.get('type', '').endswith('postgres') and n.get('credentials'):
        PG_CREDS = n['credentials']
        break

NGROK_BASE = "https://seniorprepcoach.ngrok.dev"

def new_id():
    return str(uuid.uuid4())

# ============================================================
# Phase A: setMessageReaction nodes
# ============================================================
REACT_THINKING_BODY = (
    "={{ JSON.stringify({"
    " chat_id: $('Telegram Trigger1').item.json.message.chat.id,"
    " message_id: $('Telegram Trigger1').item.json.message.message_id,"
    " reaction: [{ type: 'emoji', emoji: '\U0001F914' }]"
    " }) }}"
)
REACT_GRADUATED_BODY = (
    "={{ JSON.stringify({"
    " chat_id: $('Telegram Trigger1').item.json.message.chat.id,"
    " message_id: $('Telegram Trigger1').item.json.message.message_id,"
    " reaction: [{ type: 'emoji', emoji: '\U0001F393' }]"
    " }) }}"
)
REACT_FIRE_BODY = (
    "={{ JSON.stringify({"
    " chat_id: $('Telegram Trigger1').item.json.message.chat.id,"
    " message_id: $('Telegram Trigger1').item.json.message.message_id,"
    " reaction: [{ type: 'emoji', emoji: '\U0001F525' }]"
    " }) }}"
)

def http_request_node(name, body_expr, pos, url_endpoint='setMessageReaction'):
    return {
        "parameters": {
            "method": "POST",
            "url": f"=https://api.telegram.org/bot{{{{ $env.TELEGRAM_BOT_TOKEN }}}}/{url_endpoint}",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body_expr,
            "options": {}
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": pos,
        "id": new_id(),
        "name": name
    }

learn_react_thinking = http_request_node('learn: react thinking', REACT_THINKING_BODY, [-200, -700])
learn_react_graduated = http_request_node('learn: react graduated', REACT_GRADUATED_BODY, [1100, -700])

# ============================================================
# Phase B: message_effect_id in ans: format results
# ============================================================
FORMAT_RESULTS_JS = r"""const answers = $input.all().map(i => i.json);

// Dual-source chat_id/quiz_id: poll_ans path vs inline-keyboard path
const src = $('poll_ans: validate').isExecuted
  ? $('poll_ans: validate').item.json
  : $('ans: validate').item.json;
const chatId = src.chat_id;
const quizId = src.quiz_id;

const raw = answers[0]?.questions;
const questions = (raw && raw.questions) || raw;

const correctCount = answers.filter(a => a.correct).length;
const total = answers.length;
const pct = Math.round(100 * correctCount / total);

let badge;
let effectId;
if (pct >= 80) {
  badge = '\u{1F3C6}';
  effectId = '5104841245755180586'; // fire
} else if (pct >= 60) {
  badge = '✅';
  effectId = '5046509860389126442'; // confetti
} else if (pct >= 40) {
  badge = '⚠️';
  effectId = '5107584321108051014'; // thumbs up
} else {
  badge = '\u{1F53B}';
  effectId = '5046589136895476101'; // poop (be encouraging though - same node)
}

function esc(s) { return String(s).replace(/([_*`\[\]])/g, '\\$1'); }

const lines = [`${badge} *Quiz complete: ${correctCount}/${total} (${pct}%)*`, ''];

for (const a of answers) {
  const q = questions.find(qq => qq.id === a.question_id);
  const mark = a.correct ? '✅' : '❌';
  const userOpt = esc(q?.options?.[a.user_answer] || '');
  const correctLetter = q?.correctAnswer || '?';
  const correctOpt = esc(q?.options?.[correctLetter] || '');

  lines.push(`${mark} *${a.question_id}* — you picked _${a.user_answer}_: ${userOpt}`);
  if (!a.correct) {
    lines.push(`     ✓ Correct: *${correctLetter}* — ${correctOpt}`);
    if (q?.explanation) lines.push(`     \u{1F4A1} _${esc(q.explanation)}_`);
  }
  lines.push('');
}

lines.push(pct >= 80
  ? `_Strong recall — this material is well-internalised._`
  : pct >= 60
    ? `_Solid baseline — re-skim the points you missed._`
    : `_Worth a deeper re-read — consider running /quiz on this topic again later._`);

lines.push('');
lines.push('Use `/quiz` to test another topic, or `/learn <url>` to add a new one.');

const text = lines.join('\n');
const bodyObj = { chat_id: chatId, text, parse_mode: 'Markdown' };
if (effectId) bodyObj.message_effect_id = effectId;
const body_json = JSON.stringify(bodyObj);
return [{ json: { chat_id: chatId, text, body_json } }];"""

# ============================================================
# Phase C: Mini App webhook + dashboard
# ============================================================
MINIAPP_WEBHOOK = {
    "parameters": {
        "httpMethod": "GET",
        "path": "dashboard",
        "responseMode": "responseNode",
        "options": {}
    },
    "type": "n8n-nodes-base.webhook",
    "typeVersion": 2,
    "position": [-1400, 1200],
    "id": new_id(),
    "name": "miniapp: webhook /dashboard",
    "webhookId": new_id()
}

MINIAPP_PG_SQL = (
    "SELECT \n"
    "  COALESCE(v.materials_count, 0) AS materials_count,\n"
    "  COALESCE(v.quizzes_taken, 0) AS quizzes_taken,\n"
    "  COALESCE(v.avg_score_pct, 0) AS avg_score_pct,\n"
    "  COALESCE(v.beginner_materials, 0) AS beginner_materials,\n"
    "  COALESCE(v.intermediate_materials, 0) AS intermediate_materials,\n"
    "  COALESCE(v.advanced_materials, 0) AS advanced_materials,\n"
    "  v.last_quiz_at,\n"
    "  (SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (\n"
    "    SELECT id, title, difficulty, to_char(added_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI') AS added_at\n"
    "    FROM app.learning_materials\n"
    "    WHERE chat_id = {{ Number($json.query.chat_id) }}\n"
    "    ORDER BY added_at DESC LIMIT 20\n"
    "  ) t) AS materials,\n"
    "  (SELECT COALESCE(json_agg(row_to_json(t) ORDER BY t.finished_at), '[]'::json) FROM (\n"
    "    SELECT q.id, q.score_pct, to_char(q.finished_at AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI') AS finished_at, m.title\n"
    "    FROM app.quizzes q JOIN app.learning_materials m ON m.id = q.material_id\n"
    "    WHERE q.chat_id = {{ Number($json.query.chat_id) }} AND q.finished_at IS NOT NULL\n"
    "    ORDER BY q.finished_at DESC LIMIT 20\n"
    "  ) t) AS quizzes\n"
    "FROM (SELECT 1) dummy\n"
    "LEFT JOIN app.v_user_stats v ON v.chat_id = {{ Number($json.query.chat_id) }};"
)

MINIAPP_PG = {
    "parameters": {
        "operation": "executeQuery",
        "query": MINIAPP_PG_SQL,
        "options": {}
    },
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [-1200, 1200],
    "id": new_id(),
    "name": "miniapp: pg load",
    "credentials": PG_CREDS
}

MINIAPP_RENDER_JS = r"""// Build HTML dashboard page with Chart.js
const row = $input.first().json || {};
const materials = row.materials || [];
const quizzes = row.quizzes || [];
const total = row.materials_count || 0;
const taken = row.quizzes_taken || 0;
const avg = Math.round(row.avg_score_pct || 0);
const beg = row.beginner_materials || 0;
const inter = row.intermediate_materials || 0;
const adv = row.advanced_materials || 0;
const lastAt = row.last_quiz_at ? new Date(row.last_quiz_at).toISOString().split('T')[0] : 'never';

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

const matRows = materials.map(m => `
  <tr>
    <td><span class="diff diff-${esc(m.difficulty)}">${esc(m.difficulty)}</span></td>
    <td>${esc(m.title)}</td>
    <td class="dim">${esc(m.added_at)}</td>
  </tr>`).join('');

const quizScoresJson = JSON.stringify(quizzes.map(q => q.score_pct));
const quizLabelsJson = JSON.stringify(quizzes.map((q,i) => `Q${i+1}`));
const quizTitlesJson = JSON.stringify(quizzes.map(q => q.title));

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Senior Backend Coach — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {
    --bg: var(--tg-theme-bg-color, #0f1115);
    --fg: var(--tg-theme-text-color, #e7ecef);
    --hint: var(--tg-theme-hint-color, #8a93a0);
    --accent: var(--tg-theme-button-color, #4f8cff);
    --card: rgba(255,255,255,0.04);
    --border: rgba(255,255,255,0.08);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 16px 14px 40px;
    font: 14.5px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--fg);
  }
  h1 { font-size: 18px; margin: 0 0 4px; font-weight: 700; }
  .sub { color: var(--hint); font-size: 12.5px; margin-bottom: 18px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px; }
  .kpi { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
  .kpi .v { font-size: 22px; font-weight: 700; margin-top: 2px; }
  .kpi .l { font-size: 11.5px; color: var(--hint); text-transform: uppercase; letter-spacing: .04em; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-bottom: 14px; }
  .card h2 { font-size: 13.5px; margin: 0 0 10px; color: var(--hint); text-transform: uppercase; letter-spacing: .05em; font-weight: 600; }
  canvas { max-width: 100%; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  td { padding: 7px 4px; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  td.dim { color: var(--hint); font-size: 11.5px; white-space: nowrap; }
  .diff { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 10.5px; text-transform: uppercase; font-weight: 600; letter-spacing: .03em; }
  .diff-beginner { background: rgba(52,199,89,.15); color: #34c759; }
  .diff-intermediate { background: rgba(255,204,0,.15); color: #ffcc00; }
  .diff-advanced { background: rgba(255,59,48,.15); color: #ff453a; }
  .empty { text-align: center; color: var(--hint); padding: 24px 0; font-style: italic; }
  .charts { display: grid; grid-template-columns: 1fr; gap: 14px; }
  @media (min-width: 520px) { .charts { grid-template-columns: 1fr 1fr; } }
</style>
</head>
<body>
  <h1>📊 Your dashboard</h1>
  <div class="sub">Senior backend interview prep · last quiz ${esc(lastAt)}</div>

  <div class="grid">
    <div class="kpi"><div class="l">Materials</div><div class="v">${total}</div></div>
    <div class="kpi"><div class="l">Quizzes</div><div class="v">${taken}</div></div>
    <div class="kpi"><div class="l">Avg score</div><div class="v">${avg}%</div></div>
    <div class="kpi"><div class="l">Mastery streak</div><div class="v">${quizzes.filter(q => q.score_pct >= 60).length}</div></div>
  </div>

  <div class="charts">
    <div class="card">
      <h2>Difficulty mix</h2>
      <canvas id="diffChart" height="180"></canvas>
    </div>
    <div class="card">
      <h2>Score trend</h2>
      <canvas id="trendChart" height="180"></canvas>
    </div>
  </div>

  <div class="card">
    <h2>Library</h2>
    ${materials.length ? `<table>${matRows}</table>` : '<div class="empty">No materials yet. Use /learn &lt;url&gt; in chat.</div>'}
  </div>

<script>
  if (window.Telegram?.WebApp) {
    Telegram.WebApp.ready();
    Telegram.WebApp.expand();
  }

  const cs = getComputedStyle(document.documentElement);
  const fg = cs.getPropertyValue('--fg').trim();
  const hint = cs.getPropertyValue('--hint').trim();
  const grid = 'rgba(255,255,255,0.07)';

  Chart.defaults.color = fg;
  Chart.defaults.borderColor = grid;
  Chart.defaults.font.family = '-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';

  new Chart(document.getElementById('diffChart'), {
    type: 'doughnut',
    data: {
      labels: ['Beginner','Intermediate','Advanced'],
      datasets: [{
        data: [${beg}, ${inter}, ${adv}],
        backgroundColor: ['#34c759','#ffcc00','#ff453a'],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, font: { size: 11 } } } },
      cutout: '60%'
    }
  });

  const scores = ${quizScoresJson};
  const labels = ${quizLabelsJson};
  const titles = ${quizTitlesJson};

  new Chart(document.getElementById('trendChart'), {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        data: scores,
        borderColor: '#4f8cff',
        backgroundColor: 'rgba(79,140,255,.18)',
        tension: 0.35,
        fill: true,
        pointRadius: 4,
        pointBackgroundColor: '#4f8cff'
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: (ctx) => titles[ctx[0].dataIndex] || '' } }
      },
      scales: {
        y: { min: 0, max: 100, ticks: { callback: v => v + '%', font: { size: 10 } } },
        x: { ticks: { font: { size: 10 } } }
      }
    }
  });
</script>
</body>
</html>`;

return [{ json: { html } }];"""

MINIAPP_RENDER = {
    "parameters": {
        "jsCode": MINIAPP_RENDER_JS
    },
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [-1000, 1200],
    "id": new_id(),
    "name": "miniapp: render HTML"
}

MINIAPP_RESPOND = {
    "parameters": {
        "respondWith": "text",
        "responseBody": "={{ $json.html }}",
        "options": {
            "responseHeaders": {
                "entries": [
                    {"name": "Content-Type", "value": "text/html; charset=utf-8"},
                    {"name": "Cache-Control", "value": "no-store"}
                ]
            }
        }
    },
    "type": "n8n-nodes-base.respondToWebhook",
    "typeVersion": 1.1,
    "position": [-800, 1200],
    "id": new_id(),
    "name": "miniapp: respond HTML"
}

# ============================================================
# Phase D: Inline mode
# ============================================================
INLINE_IS_INLINE = {
    "parameters": {
        "conditions": {
            "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "loose",
                "version": 2
            },
            "conditions": [
                {
                    "id": "c-inline-q",
                    "leftValue": "={{ $json.inline_query }}",
                    "rightValue": "",
                    "operator": {
                        "type": "object",
                        "operation": "exists",
                        "singleValue": True
                    }
                }
            ],
            "combinator": "and"
        },
        "options": {}
    },
    "type": "n8n-nodes-base.if",
    "typeVersion": 2,
    "position": [-200, 1600],
    "id": new_id(),
    "name": "fallback: is inline_query?"
}

INLINE_PG_SQL = (
    "SELECT id, title, difficulty,\n"
    "       LEFT(COALESCE((summary_json->>'key_points')::text, ''), 120) AS preview\n"
    "FROM app.learning_materials\n"
    "WHERE chat_id = {{ $json.inline_query.from.id }}\n"
    "  AND title ILIKE '%{{ ($json.inline_query.query || '').replace(/'/g, \"''\").replace(/%/g, '').replace(/[\\\\]/g,'') }}%'\n"
    "ORDER BY added_at DESC\n"
    "LIMIT 20;"
)

INLINE_PG = {
    "parameters": {
        "operation": "executeQuery",
        "query": INLINE_PG_SQL,
        "options": {}
    },
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.6,
    "position": [0, 1600],
    "id": new_id(),
    "name": "inline: pg search",
    "credentials": PG_CREDS
}

INLINE_FORMAT_JS = r"""// Build answerInlineQuery payload
const rows = $input.all().map(i => i.json);
const inlineQueryId = $('Telegram Trigger1').item.json.inline_query.id;

const diffEmoji = { beginner: '\u{1F7E2}', intermediate: '\u{1F7E1}', advanced: '\u{1F534}' };

const results = rows.length ? rows.slice(0, 20).map(r => {
  const emoji = diffEmoji[r.difficulty] || '⚪️';
  return {
    type: 'article',
    id: String(r.id),
    title: r.title || 'Untitled',
    description: `${emoji} ${r.difficulty}`,
    input_message_content: {
      message_text: `\u{1F4DA} *${(r.title || 'Material').replace(/([_*\`\[\]])/g, '\\$1')}*\n\nTake a quiz to test your recall.`,
      parse_mode: 'Markdown'
    },
    reply_markup: {
      inline_keyboard: [[
        { text: '\u{1F3AF} Start quiz', callback_data: `pick:${r.id}` }
      ]]
    }
  };
}) : [{
  type: 'article',
  id: 'none',
  title: 'No materials match',
  description: 'Use /learn <url> in chat to add some',
  input_message_content: {
    message_text: '\u{1F4DA} No saved materials match this query. Send `/learn <url>` to the bot to add one.',
    parse_mode: 'Markdown'
  }
}];

const body_json = JSON.stringify({
  inline_query_id: inlineQueryId,
  results,
  cache_time: 5,
  is_personal: true
});

return [{ json: { body_json } }];"""

INLINE_FORMAT = {
    "parameters": {
        "jsCode": INLINE_FORMAT_JS
    },
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [200, 1600],
    "id": new_id(),
    "name": "inline: format results"
}

INLINE_ANSWER = http_request_node('inline: answer', '={{ $json.body_json }}', [400, 1600], url_endpoint='answerInlineQuery')

# ============================================================
# /stats: add web_app button (rewrite format + replace send with HTTP)
# ============================================================
STATS_FORMAT_JS = r"""const chatId = $('Telegram Trigger1').item.json.message.chat.id;
const row = $input.first().json;

const dashUrl = `https://seniorprepcoach.ngrok.dev/webhook/dashboard?chat_id=${chatId}`;
const reply_markup = {
  inline_keyboard: [[
    { text: '\u{1F4C8} Open full dashboard', web_app: { url: dashUrl } }
  ]]
};

if (!row || row.materials_count === undefined || row.materials_count === null || row.materials_count === 0) {
  const text = '\u{1F4CA} *No learning history yet.*\n\nSend `/learn <url>` to add your first material — once you take a quiz, your stats will show up here.';
  const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
  return [{ json: { chat_id: chatId, text, body_json } }];
}

function bar(n, total = 10) {
  const filled = Math.min(total, Math.max(0, Math.round((n / 100) * total)));
  return '█'.repeat(filled) + '░'.repeat(total - filled);
}

const score = Number(row.avg_score_pct) || 0;
const lastQuiz = row.last_quiz_at ? new Date(row.last_quiz_at).toISOString().split('T')[0] : 'never';

const lines = [
  '\u{1F4CA} *Your learning dashboard*',
  '',
  `\u{1F4DA} *Materials saved:* ${row.materials_count}`,
  `   \u{1F7E2} beginner: ${row.beginner_materials || 0}`,
  `   \u{1F7E1} intermediate: ${row.intermediate_materials || 0}`,
  `   \u{1F534} advanced: ${row.advanced_materials || 0}`,
  '',
  `\u{1F3AF} *Quizzes taken:* ${row.quizzes_taken || 0}`,
  `\u{1F4C8} *Average score:* ${score}%`,
  `      \`${bar(score)}\``,
  `\u{1F552} *Last quiz:* ${lastQuiz}`,
  '',
  '_Tip: re-quiz a topic after a few days to test retention._',
];

const text = lines.join('\n');
const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown', reply_markup });
return [{ json: { chat_id: chatId, text, body_json } }];"""

STATS_SEND_NEW = {
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
    "position": None,  # fill below
    "id": new_id(),
    "name": "/stats: send"
}

# ============================================================
# Apply node patches & replacements
# ============================================================
# Replace ans: format results jsCode
# Replace /stats: format jsCode
# Replace /stats: send with HTTP Request (keep name, same position)
# Add: learn: react thinking, learn: react graduated
# Add: miniapp webhook + 3 nodes
# Add: fallback inline IF + 3 inline nodes
# Update Telegram Trigger1 updates list

patches = {
    'ans: format results': ('jsCode', FORMAT_RESULTS_JS),
    '/stats: format':      ('jsCode', STATS_FORMAT_JS),
}

# Apply jsCode patches
replaced_telegram = False
for n in nodes:
    name = n.get('name', '')
    if name in patches:
        key, val = patches[name]
        n['parameters'][key] = val
        sys.stderr.write(f"Patched {key}: {name}\n")
    if name == 'Telegram Trigger1':
        cur = n['parameters'].get('updates', [])
        if 'inline_query' not in cur:
            cur.append('inline_query')
            n['parameters']['updates'] = cur
            sys.stderr.write("Added inline_query to Telegram Trigger updates\n")
    if name == '/stats: send' and n.get('type','').endswith('.telegram'):
        # Replace with HTTP Request, keep position + name + id (so connections stay)
        pos = n.get('position', [0,0])
        old_id = n.get('id')
        new_node = dict(STATS_SEND_NEW)
        new_node['position'] = pos
        new_node['id'] = old_id  # preserve so wiring works
        n.clear()
        n.update(new_node)
        replaced_telegram = True
        sys.stderr.write("Replaced /stats: send (telegram -> httpRequest)\n")

# Append new nodes
new_nodes = [
    learn_react_thinking,
    learn_react_graduated,
    MINIAPP_WEBHOOK,
    MINIAPP_PG,
    MINIAPP_RENDER,
    MINIAPP_RESPOND,
    INLINE_IS_INLINE,
    INLINE_PG,
    INLINE_FORMAT,
    INLINE_ANSWER,
]
nodes.extend(new_nodes)
sys.stderr.write(f"Appended {len(new_nodes)} new nodes\n")

# ============================================================
# Update connections
# ============================================================
# 1. /learn: URL valid? main[0] currently goes to [send ack (loading), jina fetch]
#    Add learn: react thinking
url_valid_targets = connections.get('/learn: URL valid?', {}).get('main', [])
if url_valid_targets:
    url_valid_targets[0].append({"node": "learn: react thinking", "type": "main", "index": 0})
    sys.stderr.write("Wired /learn: URL valid? -> learn: react thinking\n")

# 2. /learn: send summary -> learn: react graduated
connections.setdefault('/learn: send summary', {})['main'] = [
    [{"node": "learn: react graduated", "type": "main", "index": 0}]
]
sys.stderr.write("Wired /learn: send summary -> learn: react graduated\n")

# 3. Mini App chain
connections['miniapp: webhook /dashboard'] = {
    "main": [[{"node": "miniapp: pg load", "type": "main", "index": 0}]]
}
connections['miniapp: pg load'] = {
    "main": [[{"node": "miniapp: render HTML", "type": "main", "index": 0}]]
}
connections['miniapp: render HTML'] = {
    "main": [[{"node": "miniapp: respond HTML", "type": "main", "index": 0}]]
}
sys.stderr.write("Wired Mini App chain\n")

# 4. Inline chain: fallback: is poll_answer? FALSE -> fallback: is inline_query? -> TRUE: pg search, FALSE: other: reply
# Currently:
#   fallback: is poll_answer? main[0] (TRUE) -> poll_ans: parse
#   fallback: is poll_answer? main[1] (FALSE) -> other: reply
# We need to insert is_inline between FALSE and other:reply
poll_if = connections.get('fallback: is poll_answer?', {})
if poll_if:
    # main[1] is FALSE branch
    main = poll_if.get('main', [])
    while len(main) < 2:
        main.append([])
    # Take the current FALSE target
    other_reply_targets = main[1] if len(main) > 1 else []
    main[1] = [{"node": "fallback: is inline_query?", "type": "main", "index": 0}]
    poll_if['main'] = main
    connections['fallback: is poll_answer?'] = poll_if
    sys.stderr.write("Rewired fallback: is poll_answer? FALSE -> fallback: is inline_query?\n")

    connections['fallback: is inline_query?'] = {
        "main": [
            [{"node": "inline: pg search", "type": "main", "index": 0}],          # TRUE
            other_reply_targets,                                                    # FALSE -> original target
        ]
    }
    sys.stderr.write("Wired inline IF: TRUE->pg search, FALSE->original\n")

connections['inline: pg search'] = {
    "main": [[{"node": "inline: format results", "type": "main", "index": 0}]]
}
connections['inline: format results'] = {
    "main": [[{"node": "inline: answer", "type": "main", "index": 0}]]
}
sys.stderr.write("Wired inline chain\n")

# ============================================================
# Save
# ============================================================
with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)

sys.stderr.write(f"\nDONE. Total nodes now: {len(nodes)}\n")
