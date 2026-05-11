"""Patch 14: lang: pg load nodes replaced $input for downstream Code nodes
(extract title+body, build examiner body, format summary, format results).

Fix: read original input via $('source_node').item.json instead of
$input.first().json (which is now the lang lookup row {lang:'en'})."""
import json, sys, re

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# Find each affected node and rewrite $input.first().json references

# 1. /learn: extract title+body — input should come from /learn: jina fetch
for n in nodes:
    if n.get('name') == '/learn: extract title+body':
        code = n['parameters']['jsCode']
        # Replace $input.first().json with $('/learn: jina fetch').item.json
        new_code = code.replace(
            "$input.first().json.data",
            "$('/learn: jina fetch').item.json.data"
        ).replace(
            "$input.first().json.body",
            "$('/learn: jina fetch').item.json.body"
        )
        # Also handle generic $input.first().json
        new_code = new_code.replace(
            "$input.first().json",
            "$('/learn: jina fetch').item.json"
        )
        n['parameters']['jsCode'] = new_code
        sys.stderr.write("Fixed extract title+body input ref\n")

# 2. pick: build examiner body — input should come from pick: pg load material
for n in nodes:
    if n.get('name') == 'pick: build examiner body':
        code = n['parameters']['jsCode']
        new_code = code.replace(
            "$input.first().json",
            "$('pick: pg load material').item.json"
        )
        n['parameters']['jsCode'] = new_code
        sys.stderr.write("Fixed pick: build examiner body input ref\n")

# 3. /learn: format summary — input should come from /learn: pg INSERT material
for n in nodes:
    if n.get('name') == '/learn: format summary':
        code = n['parameters']['jsCode']
        new_code = code.replace(
            "$input.first().json",
            "$('/learn: pg INSERT material').item.json"
        )
        n['parameters']['jsCode'] = new_code
        sys.stderr.write("Fixed /learn: format summary input ref\n")

# 4. /stats: format — input should come from /stats: pg load
for n in nodes:
    if n.get('name') == '/stats: format':
        code = n['parameters']['jsCode']
        new_code = code.replace(
            "$input.first().json",
            "$('/stats: pg load').item.json"
        )
        n['parameters']['jsCode'] = new_code
        sys.stderr.write("Fixed /stats: format input ref\n")

# 5. ans: format results — uses $input.all() for answers from ans: pg load all answers
for n in nodes:
    if n.get('name') == 'ans: format results':
        code = n['parameters']['jsCode']
        # The first line is: const answers = $input.all().map(i => i.json);
        # That now reads from lang: pg load /ans (one item with {lang}).
        # Need to read from ans: pg load all answers instead.
        new_code = code.replace(
            "$input.all().map(i => i.json)",
            "$('ans: pg load all answers').all().map(i => i.json)"
        )
        n['parameters']['jsCode'] = new_code
        sys.stderr.write("Fixed ans: format results input ref\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
