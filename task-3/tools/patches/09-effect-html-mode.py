"""Convert ans: format results from Markdown to HTML so effects apply."""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

FORMAT_RESULTS_JS_HTML = r"""const answers = $input.all().map(i => i.json);

const src = $('poll_ans: validate').isExecuted
  ? $('poll_ans: validate').item.json
  : $('ans: validate').item.json;
const chatId = src.chat_id;

const raw = answers[0]?.questions;
const questions = (raw && raw.questions) || raw;

const correctCount = answers.filter(a => a.correct).length;
const total = answers.length;
const pct = Math.round(100 * correctCount / total);

let badge, effectId;
if (pct >= 80)      { badge = '\u{1F3C6}'; effectId = '5104841245755180586'; }  // fire
else if (pct >= 60) { badge = '✨';   effectId = '5046509860389126442'; }  // confetti
else if (pct >= 40) { badge = '\u{1F4A1}'; effectId = '5107584321108051014'; }  // thumbs up
else                { badge = '\u{1F94A}'; effectId = '5104858069142078462'; }  // thumbs down

// HTML escape (required by parse_mode: HTML)
function h(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

const lines = [`${badge} <b>Quiz complete: ${correctCount}/${total} (${pct}%)</b>`, ''];

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

lines.push(pct >= 80
  ? `<i>Strong recall — this material is well-internalised.</i>`
  : pct >= 60
    ? `<i>Solid baseline — re-skim the points you missed.</i>`
    : pct >= 40
      ? `<i>Halfway there — re-read the missed sections and run /quiz again.</i>`
      : `<i>Worth a deep re-read — try the material once more and re-quiz tomorrow.</i>`);

lines.push('');
lines.push('Open /stats for your full dashboard, or /learn &lt;url&gt; to add another topic.');

const text = lines.join('\n');
const bodyObj = { chat_id: chatId, text, parse_mode: 'HTML' };
if (effectId) bodyObj.message_effect_id = effectId;
const body_json = JSON.stringify(bodyObj);
return [{ json: { chat_id: chatId, text, body_json } }];"""

count = 0
for n in nodes:
    if n.get('name') == 'ans: format results':
        n['parameters']['jsCode'] = FORMAT_RESULTS_JS_HTML
        count += 1
        sys.stderr.write("Patched ans: format results -> HTML mode\n")

sys.stderr.write(f"Total: {count}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
