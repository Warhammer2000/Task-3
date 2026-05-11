"""Split quiz result into 2 messages: short headline with effect + long breakdown."""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

def new_id():
    return str(uuid.uuid4())

# New ans: format results — produces TWO body_jsons:
# - body_headline: short message with effect ("🔥 Quiz complete: 4/5 (80%)\nStrong recall!")
# - body_breakdown: long detailed message without effect
FORMAT_RESULTS_JS = r"""const answers = $input.all().map(i => i.json);

const src = $('poll_ans: validate').isExecuted
  ? $('poll_ans: validate').item.json
  : $('ans: validate').item.json;
const chatId = src.chat_id;

const raw = answers[0]?.questions;
const questions = (raw && raw.questions) || raw;

const correctCount = answers.filter(a => a.correct).length;
const total = answers.length;
const pct = Math.round(100 * correctCount / total);

let badge, effectId, tagline;
if (pct >= 80)      { badge = '\u{1F3C6}'; effectId = '5104841245755180586'; tagline = 'Strong recall — material internalised.'; }
else if (pct >= 60) { badge = '✨';   effectId = '5046509860389126442'; tagline = 'Solid baseline — re-skim what you missed.'; }
else if (pct >= 40) { badge = '\u{1F4A1}'; effectId = '5107584321108051014'; tagline = 'Halfway there — re-read and re-quiz.'; }
else                { badge = '\u{1F94A}'; effectId = '5104858069142078462'; tagline = 'Worth a deep re-read — try again tomorrow.'; }

function h(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// === SHORT HEADLINE (with effect) ===
const headlineText = `${badge} <b>Quiz complete: ${correctCount}/${total} (${pct}%)</b>\n<i>${h(tagline)}</i>`;
const headlineBody = { chat_id: chatId, text: headlineText, parse_mode: 'HTML' };
if (effectId) headlineBody.message_effect_id = effectId;
const body_headline = JSON.stringify(headlineBody);

// === LONG BREAKDOWN (no effect) ===
const lines = [];
for (const a of answers) {
  const q = questions.find(qq => qq.id === a.question_id);
  const mark = a.correct ? '✅' : '❌';
  const userOpt = h(q?.options?.[a.user_answer] || '');
  const correctLetter = q?.correctAnswer || '?';
  const correctOpt = h(q?.options?.[correctLetter] || '');

  lines.push(`${mark} <b>${a.question_id}</b> — you picked <i>${h(a.user_answer)}</i>: ${userOpt}`);
  if (!a.correct) {
    lines.push(`     ✓ Correct: <b>${h(correctLetter)}</b> — ${correctOpt}`);
    if (q?.explanation) lines.push(`     \u{1F4A1} <i>${h(q.explanation)}</i>`);
  }
  lines.push('');
}
lines.push('Open /stats for your dashboard, or /learn &lt;url&gt; for a new topic.');

const breakdownText = lines.join('\n');
const breakdownBody = { chat_id: chatId, text: breakdownText, parse_mode: 'HTML' };
const body_breakdown = JSON.stringify(breakdownBody);

return [{ json: { chat_id: chatId, body_headline, body_breakdown } }];"""

# Find ans: send results (HTTP Request) and replace with sequential 2-step:
#   ans: send headline (with effect) -> ans: send breakdown (no effect)

# Find the existing ans: send results node
send_results = None
send_results_idx = None
for i, n in enumerate(nodes):
    if n.get('name') == 'ans: send results':
        send_results = n
        send_results_idx = i
        break

if send_results is None:
    sys.stderr.write("ERROR: ans: send results not found\n")
    sys.exit(1)

# Repurpose existing node as "ans: send headline" — sends short message with effect
old_id = send_results['id']
old_pos = send_results['position']

send_results['parameters'] = {
    "method": "POST",
    "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage",
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={{ $json.body_headline }}",
    "options": {}
}
send_results['name'] = 'ans: send headline'

# Add new ans: send breakdown node
breakdown_node = {
    "parameters": {
        "method": "POST",
        "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ $('ans: format results').item.json.body_breakdown }}",
        "options": {}
    },
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [old_pos[0] + 200, old_pos[1]],
    "id": new_id(),
    "name": "ans: send breakdown"
}
nodes.append(breakdown_node)

# Patch the format results jsCode
for n in nodes:
    if n.get('name') == 'ans: format results':
        n['parameters']['jsCode'] = FORMAT_RESULTS_JS
        sys.stderr.write("Patched ans: format results JS (split output)\n")

# Connection updates:
# 1. Rename old "ans: send results" -> "ans: send headline" in connections
if 'ans: send results' in connections:
    connections['ans: send headline'] = connections.pop('ans: send results')

# 2. Wire ans: format results -> ans: send headline (was -> ans: send results)
# Find connections from ans: format results and rewire
for src_name, conf in list(connections.items()):
    if src_name == 'ans: format results':
        for branch in conf.get('main', []):
            for tgt in branch:
                if tgt.get('node') == 'ans: send results':
                    tgt['node'] = 'ans: send headline'
        sys.stderr.write("Rewired ans: format results -> ans: send headline\n")

# 3. ans: send headline -> ans: send breakdown
connections.setdefault('ans: send headline', {})['main'] = [
    [{"node": "ans: send breakdown", "type": "main", "index": 0}]
]
sys.stderr.write("Wired ans: send headline -> ans: send breakdown\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)

sys.stderr.write("Done.\n")
