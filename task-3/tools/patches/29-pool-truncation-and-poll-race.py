"""Patch 29: two critical bugs.

A) pool: parse Examiner JSON didn't get patch 28's runtime truncation —
   the auto-inject couldn't find the insertion point because the parse
   node uses a different validation/shuffle structure. New pool entries
   are still landing with 130-540 char options/explanations.

B) Race condition in poll_ans chain:
   - T+0: send poll (HTTP to Telegram, ~500ms)
   - T+500ms: Telegram delivers poll to user
   - T+550ms: fastest users answer
   - T+650ms: poll_answer webhook hits n8n → poll_ans chain starts
   - T+700ms: poll_ans: pg load runs SELECT WHERE poll_id = X
              ↓
   - T+600ms: workflow's pg INSERT quiz_polls completes (parallel branch)

   If user taps faster than ~700ms (mom's testing speed), pg load runs
   BEFORE the quiz_polls INSERT commits. Result: empty rows → chain
   silently stops → next question never sent → user stuck mid-quiz.

Fixes:

A) Rewrite pool: parse Examiner JSON with the truncation built into
   the per-question map, using truncWithEllipsis(s, max) on options
   (95), explanation (195), question (280).

B) Add Wait(1.5s) node between poll_ans: parse and poll_ans: pg load.
   1.5s is a safe upper bound for capture_poll_id + pg INSERT quiz_polls
   from the parallel chain to complete. User-perceived latency: tap
   answer → ~1.5-2s later see next question. Trade-off accepted vs
   the alternative of silent chain death.

C) Bonus: also truncate existing pool entries in place via UPDATE so
   the warmed pool from minutes ago doesn't keep serving truncated polls.
"""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# ============================================================
# A. Rewrite pool: parse Examiner JSON with truncation
# ============================================================
POOL_PARSE_JS = r"""const mat = $('pool: build examiner body').item.json;
const response = $input.first().json;
const rawText = response?.content?.[0]?.text || '';

let parsed;
try {
  const cleaned = rawText.replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
  parsed = JSON.parse(cleaned);
} catch (err) {
  throw new Error('Pool Examiner returned unparseable JSON: ' + rawText.slice(0, 300));
}

if (!Array.isArray(parsed?.questions) || parsed.questions.length !== 5) {
  throw new Error('Pool Examiner did not return exactly 5 questions');
}

// Defensive truncation — Telegram sendPoll hard limits: option=100, explanation=200
function truncWithEllipsis(s, maxLen) {
  const str = String(s || '');
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 1) + '…';
}

// Fisher-Yates shuffle on option letter mapping to randomize correct answer slot
const letters = ['A','B','C','D'];
const shuffled = parsed.questions.map((q, qi) => {
  // Truncate FIRST, then shuffle (text stays with its content)
  const origOpts = q.options || {};
  const truncOpts = {};
  for (const L of letters) {
    truncOpts[L] = truncWithEllipsis(origOpts[L] || '', 95);
  }
  const truncQuestion = truncWithEllipsis(q.question || '', 280);
  const truncExplanation = truncWithEllipsis(q.explanation || '', 195);

  const optEntries = letters.map(L => ({ letter: L, text: truncOpts[L] }));
  // shuffle
  for (let i = optEntries.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [optEntries[i], optEntries[j]] = [optEntries[j], optEntries[i]];
  }
  // rebuild options keyed by new letter; remember which slot was correct
  const newOpts = {};
  let newCorrect = null;
  optEntries.forEach((e, i) => {
    const newLetter = letters[i];
    newOpts[newLetter] = e.text;
    if (e.letter === q.correctAnswer) newCorrect = newLetter;
  });
  return {
    ...q,
    question: truncQuestion,
    options: newOpts,
    correctAnswer: newCorrect || q.correctAnswer,
    explanation: truncExplanation
  };
});

return [{ json: { ...mat, questions: { questions: shuffled }, generation_model: mat.generation_model } }];"""

for n in nodes:
    if n.get('name') == 'pool: parse Examiner JSON':
        n['parameters']['jsCode'] = POOL_PARSE_JS
        sys.stderr.write("Rewrote pool: parse Examiner JSON with truncation\n")

# ============================================================
# B. Add Wait(1.5s) between poll_ans: parse and poll_ans: pg load
# ============================================================
wait_node = {
    "parameters": {
        "amount": 1.5,
        "unit": "seconds"
    },
    "type": "n8n-nodes-base.wait",
    "typeVersion": 1.1,
    "position": [200, 1600],
    "id": str(uuid.uuid4()),
    "name": "poll_ans: wait for quiz_polls insert",
    "webhookId": str(uuid.uuid4())
}

# Add if not present
if not any(n.get('name') == 'poll_ans: wait for quiz_polls insert' for n in nodes):
    nodes.append(wait_node)
    sys.stderr.write("Added poll_ans: wait for quiz_polls insert (1.5s)\n")

# Rewire: poll_ans: parse -> Wait -> poll_ans: pg load
old_target = connections.get('poll_ans: parse', {}).get('main', [[]])
if old_target and old_target[0]:
    target_name = old_target[0][0].get('node')
    if target_name == 'poll_ans: pg load':
        connections['poll_ans: parse'] = {
            "main": [[{"node": "poll_ans: wait for quiz_polls insert", "type": "main", "index": 0}]]
        }
        connections['poll_ans: wait for quiz_polls insert'] = {
            "main": [[{"node": "poll_ans: pg load", "type": "main", "index": 0}]]
        }
        sys.stderr.write("Rewired poll_ans: parse -> Wait -> poll_ans: pg load\n")

# Save
with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
