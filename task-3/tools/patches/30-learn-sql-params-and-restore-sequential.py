"""Patch 30: bulletproof /learn pg INSERT via param binding + restore patch 26 wiring.

Two bugs:

1. `/learn: pg INSERT material` SQL used text interpolation:
       VALUES (
         {{ $json.chat_id }},
         '{{ $json.url.replace(/'/g, \"''\") }}',
         '{{ $json.title.replace(/'/g, \"''\") }}',
         '{{ $json.content.replace(/'/g, \"''\") }}',
         '{{ JSON.stringify($json.summary_json).replace(/'/g, \"''\") }}'::jsonb,
         ...

   On a metanit.com F# tutorial, the article content contained backticks
   and patterns that interacted badly with n8n's expression engine (or
   with the regex inside the expression). Postgres got a malformed SQL
   that looked like the INSERT statement repeating recursively inside
   the content value. Error: `Syntax error at line 4 near "https"`.

   Fix: use queryReplacement with positional $1, $2, $3, $4, $5
   parameters — proper PostgreSQL parameter binding, no text escaping,
   no regex in the SQL template, immune to anything in the content.

2. Patch 26's sequential /learn wiring was lost somewhere between patches
   26-29 (perhaps a later patch's connection dump preceded a write that
   reverted it). Current state has the old parallel fan-out
   `[ack, jina, react]` from URL valid? — which means n8n silently picks
   only `jina` (per the patch 26 root-cause analysis) and ack/react die
   on the vine again.

   Fix: re-apply patch 26's sequential rewire:
       URL valid? TRUE → lang load → build ack → send ack → react
                       → jina → extract → ...
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# ============================================================
# 1. Rewrite /learn: pg INSERT material with param binding
# ============================================================
LEARN_INSERT_SQL = (
    "INSERT INTO app.learning_materials (chat_id, url, title, content, summary_json, difficulty)\n"
    "VALUES ($1, $2, $3, $4, $5::jsonb, $6)\n"
    "ON CONFLICT (chat_id, url) DO UPDATE SET\n"
    "  title = EXCLUDED.title,\n"
    "  content = EXCLUDED.content,\n"
    "  summary_json = EXCLUDED.summary_json,\n"
    "  difficulty = EXCLUDED.difficulty,\n"
    "  added_at = now()\n"
    "RETURNING id, chat_id, url, title, summary_json, difficulty;"
)

# n8n's queryReplacement is a COMMA-separated string of expressions evaluated
# at runtime and bound to $1, $2, ... — proper Postgres parameter binding.
LEARN_INSERT_PARAMS = (
    "={{ $json.chat_id }},"
    "{{ $json.url }},"
    "{{ $json.title }},"
    "{{ $json.content }},"
    "{{ JSON.stringify($json.summary_json) }},"
    "{{ $json.difficulty }}"
)

for n in nodes:
    if n.get('name') == '/learn: pg INSERT material':
        n['parameters']['query'] = LEARN_INSERT_SQL
        n['parameters'].setdefault('options', {})['queryReplacement'] = LEARN_INSERT_PARAMS
        sys.stderr.write("Rewrote /learn: pg INSERT material with $1..$6 param binding\n")

# ============================================================
# 2. Restore patch 26's sequential wiring
# ============================================================
# Find current URL valid? FALSE branch (preserve it)
url_valid_old = connections.get('/learn: URL valid?', {}).get('main', [[], []])
false_branch = url_valid_old[1] if len(url_valid_old) > 1 else [{"node": "/learn: reply invalid", "type": "main", "index": 0}]
# Normalize FALSE branch shape (it should be a flat list of targets, not wrapped)
if false_branch and isinstance(false_branch[0], list):
    false_branch = false_branch[0]
if not false_branch:
    false_branch = [{"node": "/learn: reply invalid", "type": "main", "index": 0}]

connections['/learn: URL valid?'] = {
    "main": [
        [{"node": "lang: pg load /learn", "type": "main", "index": 0}],  # TRUE: enter sequential chain
        false_branch  # FALSE: reply invalid
    ]
}

connections['lang: pg load /learn'] = {
    "main": [[{"node": "/learn: build ack text", "type": "main", "index": 0}]]
}
connections['/learn: build ack text'] = {
    "main": [[{"node": "/learn: send ack (loading)", "type": "main", "index": 0}]]
}
connections['/learn: send ack (loading)'] = {
    "main": [[{"node": "learn: react thinking", "type": "main", "index": 0}]]
}
connections['learn: react thinking'] = {
    "main": [[{"node": "/learn: jina fetch", "type": "main", "index": 0}]]
}
connections['/learn: jina fetch'] = {
    "main": [[{"node": "/learn: extract title+body", "type": "main", "index": 0}]]
}

sys.stderr.write("Restored sequential /learn chain wiring\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
