import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

DUAL = "{{ $('poll_ans: validate').isExecuted ? $('poll_ans: validate').item.json.quiz_id : $('ans: validate').item.json.quiz_id }}"

FINALIZE_SQL = (
    "WITH agg AS (\n"
    "  SELECT quiz_id,\n"
    "         ROUND(100.0 * SUM(CASE WHEN correct THEN 1 ELSE 0 END) / COUNT(*))::INT AS score_pct\n"
    "  FROM app.quiz_answers\n"
    "  WHERE quiz_id = " + DUAL + "\n"
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
    "WHERE qa.quiz_id = " + DUAL + "\n"
    "ORDER BY qa.question_id;"
)

PATCH = {
    'ans: pg finalize quiz':    FINALIZE_SQL,
    'ans: pg load all answers': LOAD_ANS_SQL,
}

count = 0
for n in nodes:
    name = n.get('name', '')
    if name in PATCH:
        n['parameters']['query'] = PATCH[name]
        sys.stderr.write(f"Patched: {name}\n")
        count += 1

sys.stderr.write(f"Total: {count}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)

sys.stderr.write(f"Wrote {len(json.dumps(nodes))} bytes\n")
