"""Patch 28b: add runtime truncation to pick: parse Examiner JSON.

Patch 28's auto-injection couldn't find the insertion point in
pick: parse Examiner JSON because the validation/shuffle logic is
structured differently from pool: parse Examiner JSON. This patch
adds truncation INSIDE the per-question for-loop (right after
shuffle finalises q.options).
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

PICK_PARSE_JS = r"""const mat = $('pick: pg load material').item.json;
const response = $input.first().json;
const rawText = response?.content?.[0]?.text || '';

let parsed;
try {
  const cleaned = rawText.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
  parsed = JSON.parse(cleaned);
} catch (err) {
  throw new Error('Examiner returned unparseable JSON: ' + rawText.slice(0, 300));
}

if (!Array.isArray(parsed.questions) || parsed.questions.length !== 5) {
  throw new Error('Examiner did not return 5 questions, got: ' + (parsed.questions || []).length);
}

// Defensive truncation — Telegram sendPoll hard limits: option=100, explanation=200.
function truncWithEllipsis(s, maxLen) {
  const str = String(s || '');
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 1) + '…';
}

// Validate each question + RANDOMIZE option order so correctAnswer isn't always A
const letters = ['A','B','C','D'];
for (let i = 0; i < 5; i++) {
  const q = parsed.questions[i];
  if (!q.id) q.id = `Q${i + 1}`;
  if (!q.options || !q.options.A || !q.options.B || !q.options.C || !q.options.D) {
    throw new Error(`Q${i + 1} missing options A-D`);
  }
  q.correctAnswer = String(q.correctAnswer || '').toUpperCase();
  if (!letters.includes(q.correctAnswer)) {
    throw new Error(`Q${i + 1} has invalid correctAnswer: ${q.correctAnswer}`);
  }
  q.explanation = q.explanation || '';

  // Truncate option text BEFORE shuffle (text stays with its content)
  for (const L of letters) {
    q.options[L] = truncWithEllipsis(q.options[L], 95);
  }
  q.question = truncWithEllipsis(q.question, 280);
  q.explanation = truncWithEllipsis(q.explanation, 195);

  // Shuffle option order to spread correctAnswer across A/B/C/D
  const correctText = q.options[q.correctAnswer];
  const wrongTexts = letters.filter(l => l !== q.correctAnswer).map(l => q.options[l]);
  // Fisher-Yates shuffle wrongTexts
  for (let j = wrongTexts.length - 1; j > 0; j--) {
    const k = Math.floor(Math.random() * (j + 1));
    [wrongTexts[j], wrongTexts[k]] = [wrongTexts[k], wrongTexts[j]];
  }
  // Pick random target slot for the correct answer
  const targetLetter = letters[Math.floor(Math.random() * 4)];
  const newOptions = {};
  let wi = 0;
  for (const L of letters) {
    if (L === targetLetter) newOptions[L] = correctText;
    else newOptions[L] = wrongTexts[wi++];
  }
  q.options = newOptions;
  q.correctAnswer = targetLetter;
}

return [{ json: { material_id: mat.material_id, chat_id: mat.chat_id, questions: parsed.questions } }];"""

for n in nodes:
    if n.get('name') == 'pick: parse Examiner JSON':
        n['parameters']['jsCode'] = PICK_PARSE_JS
        sys.stderr.write("Patched pick: parse Examiner JSON with truncation\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
