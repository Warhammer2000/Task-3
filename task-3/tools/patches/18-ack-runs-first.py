"""Patch 18: reorder pick: ack to run BEFORE pick: build examiner body
in the multi-target connection list. n8n executes branches sequentially
in list order — putting ack first means it fires within ~500ms instead
of after the 25-second Examiner call completes."""
import json, sys

with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

lang_pick = connections.get('lang: pg load pick', {})
if not lang_pick:
    sys.stderr.write("lang: pg load pick not found in connections\n")
    sys.exit(1)

main = lang_pick.get('main', [[]])
if not main or not main[0]:
    sys.stderr.write("Empty main on lang: pg load pick\n")
    sys.exit(1)

# Reorder: ack first, then examiner body
targets = main[0]
ack_targets = [t for t in targets if t.get('node') == 'pick: build ack text']
other_targets = [t for t in targets if t.get('node') != 'pick: build ack text']

if not ack_targets:
    sys.stderr.write("pick: build ack text not found in main[0]\n")
    sys.exit(1)

main[0] = ack_targets + other_targets
sys.stderr.write(f"Reordered lang: pg load pick main[0]: {[t['node'] for t in main[0]]}\n")

with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
