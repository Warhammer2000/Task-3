import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# Patch finalize + load_all (re-apply since we'll write same file)
DUAL_QID = "{{ $('poll_ans: validate').isExecuted ? $('poll_ans: validate').item.json.quiz_id : $('ans: validate').item.json.quiz_id }}"

FINALIZE_SQL = (
    "WITH agg AS (\n"
    "  SELECT quiz_id,\n"
    "         ROUND(100.0 * SUM(CASE WHEN correct THEN 1 ELSE 0 END) / COUNT(*))::INT AS score_pct\n"
    "  FROM app.quiz_answers\n"
    "  WHERE quiz_id = " + DUAL_QID + "\n"
    "  GROUP BY quiz_id\n"
    ")\n"
    "UPDATE app.quizzes q\n"
    "SET finished_at = now(), score_pct = agg.score_pct\n"
    "FROM agg\n"
    "WHERE q.id = agg.quiz_id\n"
    "RETURNING q.id, q.score_pct;"
)

LOAD_ANS_SQL = (
    "SELECT qa.question_id, qa.user_answer, qa.correct, q.questions\n"
    "FROM app.quiz_answers qa\n"
    "JOIN app.quizzes q ON q.id = qa.quiz_id\n"
    "WHERE qa.quiz_id = " + DUAL_QID + "\n"
    "ORDER BY qa.question_id;"
)

# Rewrite format results to use dual-source
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
if (pct >= 80) badge = '\u{1F3C6}';
else if (pct >= 60) badge = '✅';
else if (pct >= 40) badge = '⚠️';
else badge = '\u{1F53B}';

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
const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
return [{ json: { chat_id: chatId, text, body_json } }];"""

PATCH_QUERY = {
    'ans: pg finalize quiz':    FINALIZE_SQL,
    'ans: pg load all answers': LOAD_ANS_SQL,
}

PATCH_JS = {
    'ans: format results': FORMAT_RESULTS_JS,
}

count = 0
for n in nodes:
    name = n.get('name', '')
    if name in PATCH_QUERY:
        n['parameters']['query'] = PATCH_QUERY[name]
        sys.stderr.write(f"Patched query: {name}\n")
        count += 1
    if name in PATCH_JS:
        n['parameters']['jsCode'] = PATCH_JS[name]
        sys.stderr.write(f"Patched jsCode: {name}\n")
        count += 1

sys.stderr.write(f"Total: {count}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
