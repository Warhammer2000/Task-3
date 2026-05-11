# -*- coding: utf-8 -*-
"""
Switch from inline-keyboard quiz delivery to Telegram sendPoll quiz mode.

Adds:
  - poll_answer to Telegram Trigger updates list
  - New Switch output for poll_answer events
  - Replaces pick: format Q1 + pick: send Q1 with sendPoll-based delivery
  - Adds capture poll_id + pg INSERT quiz_polls
  - Adds new poll_ans chain (parse, load, validate, insert, branch)
  - Rewires connections

Reuses where possible: ans: pg finalize quiz, ans: pg load all answers,
ans: format results, ans: send results.

The existing `callback:ans` path (inline-keyboard answers) is kept around
but disconnected from Switch — fallback in case poll_answer pipeline fails,
inline buttons can be reattached later.
"""
import json, sys

with open('/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# ============================================================
# Telegram Trigger — add poll_answer to updates
# ============================================================
for n in nodes:
    if n.get('name') == 'Telegram Trigger1':
        updates = n['parameters'].get('updates', [])
        if 'poll_answer' not in updates:
            updates.append('poll_answer')
            n['parameters']['updates'] = updates
            sys.stderr.write("Added poll_answer to Telegram Trigger updates\n")
        break

# ============================================================
# Switch (Route) — add a 7th output for poll_answer
# ============================================================
for n in nodes:
    if n.get('name') == 'Route':
        rules = n['parameters'].get('rules', {}).get('values', [])
        # Check if already has poll_answer rule
        has_poll_rule = any(
            any(c.get('id') == 'c-pollans' for c in r.get('conditions', {}).get('conditions', []))
            for r in rules
        )
        if not has_poll_rule:
            rules.append({
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                    "conditions": [
                        {
                            "id": "c-pollans",
                            "leftValue": "={{ $json.poll_answer ? 'yes' : 'no' }}",
                            "rightValue": "yes",
                            "operator": {"type": "string", "operation": "equals"}
                        }
                    ],
                    "combinator": "and"
                },
                "renameOutput": True,
                "outputKey": "callback:poll_answer"
            })
            n['parameters']['rules']['values'] = rules
            sys.stderr.write("Added Switch output: callback:poll_answer\n")
        break

# ============================================================
# Build/send poll body — Code node
# Used both for first Q (pick path) and subsequent Q's (poll_ans path)
# ============================================================
BUILD_POLL_BODY_JS = """// Build sendPoll quiz-mode body.
// Inputs may be:
//   (a) pick: pg INSERT quiz output — has fields: id (quiz_id), material_id, chat_id, questions (JSONB)
//   (b) poll_ans: validate output — has fields: quiz_id, chat_id, next_q_idx, questions

const ctx = $input.first().json;

const quizId = ctx.quiz_id !== undefined ? ctx.quiz_id : ctx.id;
const chatId = ctx.chat_id;
const questions = (ctx.questions && ctx.questions.questions) || ctx.questions;
const qIdx = ctx.next_q_idx !== undefined ? ctx.next_q_idx : 0;
const q = questions[qIdx];

const letters = ['A', 'B', 'C', 'D'];
// Each option: prefix with letter for clarity, then truncate to Telegram 100-char limit
const options = letters.map(L => {
  const raw = `${L}) ${q.options[L] || ''}`;
  return raw.length > 100 ? raw.slice(0, 97) + '...' : raw;
});
const correctOptionId = letters.indexOf(q.correctAnswer);
if (correctOptionId === -1) throw new Error('Invalid correctAnswer: ' + q.correctAnswer);

// Telegram explanation: 200 chars max
let explanation = q.explanation || '';
if (explanation.length > 200) explanation = explanation.slice(0, 197) + '...';

// Question text: Telegram poll question max 300 chars
let questionText = `Q${qIdx + 1} of ${questions.length}: ${q.question}`;
if (questionText.length > 300) questionText = questionText.slice(0, 297) + '...';

const body_json = JSON.stringify({
  chat_id: chatId,
  type: 'quiz',
  question: questionText,
  options: options,
  correct_option_id: correctOptionId,
  explanation: explanation,
  is_anonymous: false
});

return [{ json: {
  chat_id: chatId,
  quiz_id: quizId,
  question_id: q.id,
  question_idx: qIdx,
  correct_option_id: correctOptionId,
  body_json
} }];"""

# ============================================================
# Capture poll_id from sendPoll response, INSERT quiz_polls
# ============================================================
CAPTURE_POLL_JS = """// Extract poll.id from the sendPoll API response
const resp = $input.first().json;
const pollId = resp?.result?.poll?.id;
if (!pollId) {
  throw new Error('No poll.id in sendPoll response: ' + JSON.stringify(resp).slice(0, 300));
}

// Reach back to the build-body node for the question metadata we computed
const builder = $('pick: build poll body').isExecuted
  ? $('pick: build poll body').item.json
  : $('poll_ans: build next poll body').item.json;

return [{ json: {
  poll_id: pollId,
  quiz_id: builder.quiz_id,
  chat_id: builder.chat_id,
  question_id: builder.question_id,
  question_idx: builder.question_idx,
  correct_option_id: builder.correct_option_id
} }];"""

# ============================================================
# poll_answer parse Code
# ============================================================
POLL_ANS_PARSE_JS = """const pa = $input.first().json.poll_answer;
if (!pa) throw new Error('No poll_answer payload');
return [{ json: {
  poll_id: pa.poll_id,
  chat_id: pa.user?.id,
  selected_option_id: (pa.option_ids || [])[0]
} }];"""

# poll_ans: pg load — joins quiz_polls and quizzes
POLL_ANS_LOAD_SQL = (
    "SELECT qp.quiz_id, qp.chat_id, qp.question_id, qp.question_idx,\n"
    "       qp.correct_option_id, q.questions\n"
    "FROM app.quiz_polls qp\n"
    "JOIN app.quizzes q ON q.id = qp.quiz_id\n"
    "WHERE qp.poll_id = '{{ $json.poll_id.replace(/'/g, \"''\") }}';"
)

# poll_ans: validate Code
POLL_ANS_VALIDATE_JS = """const row = $input.first().json;
const pa = $('poll_ans: parse').item.json;

const correct = pa.selected_option_id === row.correct_option_id;
const letters = ['A','B','C','D'];
const userAnswer = letters[pa.selected_option_id] || '?';
const correctAnswer = letters[row.correct_option_id] || '?';

const questions = (row.questions && row.questions.questions) || row.questions;
const isLast = row.question_idx === questions.length - 1;
const nextIdx = row.question_idx + 1;

return [{ json: {
  quiz_id: row.quiz_id,
  chat_id: row.chat_id,
  question_id: row.question_id,
  question_idx: row.question_idx,
  next_q_idx: nextIdx,
  user_answer: userAnswer,
  correct_answer: correctAnswer,
  correct,
  is_last: isLast,
  questions
} }];"""

# poll_ans: INSERT answer (reuse existing ans: pg INSERT answer SQL — but using poll_ans data)
POLL_ANS_INSERT_SQL = (
    "INSERT INTO app.quiz_answers (quiz_id, question_id, user_answer, correct)\n"
    "VALUES (\n"
    "  {{ $json.quiz_id }},\n"
    "  '{{ $json.question_id.replace(/'/g, \"''\") }}',\n"
    "  '{{ $json.user_answer.replace(/'/g, \"''\") }}',\n"
    "  {{ $json.correct }}\n"
    ")\n"
    "ON CONFLICT (quiz_id, question_id) DO NOTHING\n"
    "RETURNING id;"
)

# INSERT quiz_polls SQL (used after sendPoll succeeds)
INSERT_QUIZ_POLLS_SQL = (
    "INSERT INTO app.quiz_polls (poll_id, quiz_id, chat_id, question_id, question_idx, correct_option_id)\n"
    "VALUES (\n"
    "  '{{ $json.poll_id.replace(/'/g, \"''\") }}',\n"
    "  {{ $json.quiz_id }},\n"
    "  {{ $json.chat_id }},\n"
    "  '{{ $json.question_id.replace(/'/g, \"''\") }}',\n"
    "  {{ $json.question_idx }},\n"
    "  {{ $json.correct_option_id }}\n"
    ")\n"
    "ON CONFLICT (poll_id) DO NOTHING\n"
    "RETURNING poll_id;"
)

# ============================================================
# NEW nodes to append
# ============================================================
new_nodes = [
    {
        "parameters": {"jsCode": BUILD_POLL_BODY_JS},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [100, 600],
        "id": "node-pick-buildpoll",
        "name": "pick: build poll body"
    },
    {
        "parameters": {
            "method": "POST",
            "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendPoll",
            "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "content-type", "value": "application/json"}]},
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ $json.body_json }}",
            "options": {"timeout": 30000}
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [300, 600],
        "id": "node-pick-sendpoll",
        "name": "pick: send poll"
    },
    {
        "parameters": {"jsCode": CAPTURE_POLL_JS},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [500, 600],
        "id": "node-pick-capture",
        "name": "pick: capture poll_id"
    },
    {
        "parameters": {
            "operation": "executeQuery",
            "query": INSERT_QUIZ_POLLS_SQL,
            "options": {}
        },
        "type": "n8n-nodes-base.postgres",
        "typeVersion": 2.6,
        "position": [700, 600],
        "id": "node-pick-pginsertpoll",
        "name": "pick: pg INSERT quiz_polls",
        "credentials": {"postgres": {"id": "hGO5xvaEVuwezYxS", "name": "Postgres account"}}
    },
    {
        "parameters": {"jsCode": POLL_ANS_PARSE_JS},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [-700, 1300],
        "id": "node-pollans-parse",
        "name": "poll_ans: parse"
    },
    {
        "parameters": {
            "operation": "executeQuery",
            "query": POLL_ANS_LOAD_SQL,
            "options": {}
        },
        "type": "n8n-nodes-base.postgres",
        "typeVersion": 2.6,
        "position": [-500, 1300],
        "id": "node-pollans-load",
        "name": "poll_ans: pg load",
        "credentials": {"postgres": {"id": "hGO5xvaEVuwezYxS", "name": "Postgres account"}}
    },
    {
        "parameters": {"jsCode": POLL_ANS_VALIDATE_JS},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [-300, 1300],
        "id": "node-pollans-validate",
        "name": "poll_ans: validate"
    },
    {
        "parameters": {
            "operation": "executeQuery",
            "query": POLL_ANS_INSERT_SQL,
            "options": {}
        },
        "type": "n8n-nodes-base.postgres",
        "typeVersion": 2.6,
        "position": [-100, 1300],
        "id": "node-pollans-insert",
        "name": "poll_ans: pg INSERT answer",
        "credentials": {"postgres": {"id": "hGO5xvaEVuwezYxS", "name": "Postgres account"}}
    },
    {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": [
                    {"id": "c-pa-last", "leftValue": "={{ $('poll_ans: validate').item.json.is_last }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true", "singleValue": True}}
                ],
                "combinator": "and"
            },
            "options": {}
        },
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [100, 1300],
        "id": "node-pollans-islast",
        "name": "poll_ans: is last Q?"
    },
    {
        "parameters": {"jsCode": BUILD_POLL_BODY_JS.replace("pick: build poll body", "poll_ans: build next poll body")},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [300, 1400],
        "id": "node-pollans-buildnext",
        "name": "poll_ans: build next poll body"
    }
]

# De-dup: skip if any with same name already present
existing_names = {n.get('name') for n in nodes}
for nn in new_nodes:
    if nn['name'] in existing_names:
        sys.stderr.write(f"Skip (already present): {nn['name']}\n")
    else:
        nodes.append(nn)
        sys.stderr.write(f"Added node: {nn['name']}\n")

# ============================================================
# Connection rewiring
# ============================================================
# 1. Route → callback:poll_answer → poll_ans: parse
if 'Route' in connections:
    main = connections['Route']['main']
    # Existing outputs: [/start, /learn, /quiz, /stats, callback:pick, callback:ans, other]
    # Adding 8th: callback:poll_answer (index 7)
    # If already has 8th, replace; otherwise append
    new_target = [{"node": "poll_ans: parse", "type": "main", "index": 0}]
    if len(main) >= 8:
        main[7] = new_target
    else:
        # Pad as needed
        while len(main) < 8:
            main.append([])
        main[7] = new_target
    sys.stderr.write("Wired Route[7] -> poll_ans: parse\n")

# 2. pick: pg INSERT quiz → pick: build poll body (replacing -> format Q1)
connections['pick: pg INSERT quiz'] = {
    "main": [[{"node": "pick: build poll body", "type": "main", "index": 0}]]
}
connections['pick: build poll body'] = {
    "main": [[{"node": "pick: send poll", "type": "main", "index": 0}]]
}
connections['pick: send poll'] = {
    "main": [[{"node": "pick: capture poll_id", "type": "main", "index": 0}]]
}
connections['pick: capture poll_id'] = {
    "main": [[{"node": "pick: pg INSERT quiz_polls", "type": "main", "index": 0}]]
}
# pg INSERT quiz_polls is terminal — no downstream

# 3. poll_ans chain
connections['poll_ans: parse'] = {
    "main": [[{"node": "poll_ans: pg load", "type": "main", "index": 0}]]
}
connections['poll_ans: pg load'] = {
    "main": [[{"node": "poll_ans: validate", "type": "main", "index": 0}]]
}
connections['poll_ans: validate'] = {
    "main": [[{"node": "poll_ans: pg INSERT answer", "type": "main", "index": 0}]]
}
connections['poll_ans: pg INSERT answer'] = {
    "main": [[{"node": "poll_ans: is last Q?", "type": "main", "index": 0}]]
}
connections['poll_ans: is last Q?'] = {
    "main": [
        # TRUE branch: last Q → finalize, load all answers, format results, send results (reuse existing)
        [{"node": "ans: pg finalize quiz", "type": "main", "index": 0}],
        # FALSE branch: build next poll
        [{"node": "poll_ans: build next poll body", "type": "main", "index": 0}]
    ]
}
connections['poll_ans: build next poll body'] = {
    "main": [[{"node": "pick: send poll", "type": "main", "index": 0}]]
}
# pick: send poll → pick: capture poll_id → pick: pg INSERT quiz_polls (reused chain)

sys.stderr.write("Rewired connections\n")

# ============================================================
# Write outputs
# ============================================================
with open('/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Wrote /tmp/db_nodes_fixed.json + /tmp/db_conn_fixed.json\n")
