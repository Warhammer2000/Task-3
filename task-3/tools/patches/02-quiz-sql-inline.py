import json, sys

data = json.load(sys.stdin)
nodes = data if isinstance(data, list) else data.get('nodes', [])

BUILD_EXAMINER_JS = r"""// Build the Anthropic Examiner request body as a JSON string here.
const mat = $input.first().json;

const systemPrompt = "You are the Examiner in an AI-powered learning assistant for senior backend engineers preparing for staff-tier interviews. Given a material title, summary, and full content, generate EXACTLY 5 multiple-choice questions that probe whether the reader internalized the material at senior interview level.\n\nSTYLE non-negotiable:\n1. NO trivia. No year/acronym recall.\n2. PROBE understanding: apply concept to scenario, compare approaches, identify failure mode, spot what breaks if assumption changes.\n3. INTERVIEW FRAMING: phrase as interviewer would speak it.\n4. PLAUSIBLE DISTRACTORS: wrong options represent real misconceptions.\n5. ONE CORRECT ANSWER each (single best answer).\n6. EXPLANATIONS MUST TEACH why right is right AND why distractors are wrong.\n7. NO HARDCODING.\n\nOutput JSON with EXACTLY this schema:\n{\n  \"questions\": [\n    { \"id\": \"Q1\", \"question\": \"<=280 chars\", \"options\": { \"A\": \"<=120\", \"B\": \"<=120\", \"C\": \"<=120\", \"D\": \"<=120\" }, \"correctAnswer\": \"A\"|\"B\"|\"C\"|\"D\", \"explanation\": \"<2-4 sentences>\" }, ...Q2-Q5\n  ]\n}\n\nExactly 5 questions, IDs Q1-Q5, 4 options A-D each, correctAnswer single A-D letter. Distribute correct answers across A/B/C/D.\n\nOutput ONLY the JSON. No fences, no commentary.";

const summary = mat.summary_json || {};
const keyPoints = Array.isArray(summary.key_points) ? summary.key_points.join('\n') : '';
const concepts = Array.isArray(summary.main_concepts) ? summary.main_concepts.join(', ') : '';
const userContent = 'TITLE: ' + (mat.title || '') + '\nDIFFICULTY: ' + (mat.difficulty || '') + '\n\nKEY POINTS:\n' + keyPoints + '\n\nCONCEPTS: ' + concepts + '\n\nFULL CONTENT:\n' + (mat.content || '');

const examiner_body = JSON.stringify({
  model: 'claude-haiku-4-5-20251001',
  max_tokens: 3500,
  system: systemPrompt,
  messages: [{ role: 'user', content: userContent }]
});

return [{ json: { ...mat, examiner_body } }];"""

# Inline SQL patches (use n8n {{ }} expressions, no queryReplacement)
PICK_INSERT_QUIZ_SQL = (
    "INSERT INTO app.quizzes (material_id, chat_id, questions, started_at)\n"
    "VALUES (\n"
    "  {{ $json.material_id }},\n"
    "  {{ $json.chat_id }},\n"
    "  '{{ JSON.stringify({ questions: $json.questions }).replace(/'/g, \"''\") }}'::jsonb,\n"
    "  now()\n"
    ")\n"
    "RETURNING id, material_id, chat_id, questions;"
)

ANS_INSERT_ANSWER_SQL = (
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

ANS_FINALIZE_SQL = (
    "WITH agg AS (\n"
    "  SELECT quiz_id,\n"
    "         ROUND(100.0 * SUM(CASE WHEN correct THEN 1 ELSE 0 END) / COUNT(*))::INT AS score_pct\n"
    "  FROM app.quiz_answers\n"
    "  WHERE quiz_id = {{ $('ans: validate').item.json.quiz_id }}\n"
    "  GROUP BY quiz_id\n"
    ")\n"
    "UPDATE app.quizzes q\n"
    "SET finished_at = now(), score_pct = agg.score_pct\n"
    "FROM agg\n"
    "WHERE q.id = agg.quiz_id\n"
    "RETURNING q.id, q.score_pct;"
)

ANS_LOAD_ANSWERS_SQL = (
    "SELECT qa.question_id, qa.user_answer, qa.correct, q.questions\n"
    "FROM app.quiz_answers qa\n"
    "JOIN app.quizzes q ON q.id = qa.quiz_id\n"
    "WHERE qa.quiz_id = {{ $('ans: validate').item.json.quiz_id }}\n"
    "ORDER BY qa.question_id;"
)

STATS_LOAD_SQL = "SELECT materials_count, quizzes_taken, COALESCE(avg_score_pct, 0) AS avg_score_pct, last_quiz_at, advanced_materials, intermediate_materials, beginner_materials FROM app.v_user_stats WHERE chat_id = {{ $json.message.chat.id }};"

QUIZ_SELECT_SQL = "SELECT id, title, difficulty FROM app.learning_materials WHERE chat_id = {{ $json.message.chat.id }} ORDER BY added_at DESC LIMIT 20;"

PICK_LOAD_SQL = "SELECT m.id AS material_id, m.chat_id, m.title, m.content, m.summary_json, m.difficulty FROM app.learning_materials m WHERE m.id = {{ Number(($json.callback_query.data || '').split(':')[1]) }};"

ANS_LOAD_QUIZ_SQL = "SELECT id, material_id, chat_id, questions, started_at, finished_at FROM app.quizzes WHERE id = {{ $json.quiz_id }};"

count = 0
build_node_exists = any(n.get('name') == 'pick: build examiner body' for n in nodes)
if not build_node_exists:
    nodes.append({
        "parameters": {"jsCode": BUILD_EXAMINER_JS},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [-400, 600],
        "id": "node-pick-buildbody",
        "name": "pick: build examiner body"
    })
    sys.stderr.write("Added node: pick: build examiner body\n")
    count += 1

PATCHES = {
    'pick: Examiner (Haiku)':       ('jsonBody', '={{ $json.examiner_body }}'),
    'pick: pg INSERT quiz':         ('query',    PICK_INSERT_QUIZ_SQL),
    'ans: pg INSERT answer':        ('query',    ANS_INSERT_ANSWER_SQL),
    'ans: pg finalize quiz':        ('query',    ANS_FINALIZE_SQL),
    'ans: pg load all answers':     ('query',    ANS_LOAD_ANSWERS_SQL),
    '/stats: pg load':              ('query',    STATS_LOAD_SQL),
    '/quiz: pg SELECT materials':   ('query',    QUIZ_SELECT_SQL),
    'pick: pg load material':       ('query',    PICK_LOAD_SQL),
    'ans: pg load quiz':            ('query',    ANS_LOAD_QUIZ_SQL),
}

for n in nodes:
    name = n.get('name', '')
    if name in PATCHES:
        key, val = PATCHES[name]
        n['parameters'][key] = val
        n['parameters'].setdefault('options', {}).pop('queryReplacement', None)
        sys.stderr.write(f"Patched: {name} ({key})\n")
        count += 1

sys.stderr.write(f"\nTotal: {count}\n")
sys.stdout.write(json.dumps(nodes))
