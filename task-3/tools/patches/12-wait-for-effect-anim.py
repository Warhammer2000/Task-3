"""Add 3.5s Wait node between headline and breakdown so effect animation plays."""
import json, sys, uuid

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# Find headline position to place wait between them
headline_pos = None
for n in nodes:
    if n.get('name') == 'ans: send headline':
        headline_pos = n['position']
        break

wait_node = {
    "parameters": {
        "amount": 3.5,
        "unit": "seconds"
    },
    "type": "n8n-nodes-base.wait",
    "typeVersion": 1.1,
    "position": [headline_pos[0] + 100, headline_pos[1]] if headline_pos else [0, 0],
    "id": str(uuid.uuid4()),
    "name": "ans: wait for effect",
    "webhookId": str(uuid.uuid4())
}

# Check if wait already exists
if not any(n.get('name') == 'ans: wait for effect' for n in nodes):
    nodes.append(wait_node)
    sys.stderr.write("Added ans: wait for effect (3.5s)\n")
else:
    sys.stderr.write("Wait node already present\n")

# Rewire: headline -> wait -> breakdown
connections['ans: send headline'] = {
    "main": [[{"node": "ans: wait for effect", "type": "main", "index": 0}]]
}
connections['ans: wait for effect'] = {
    "main": [[{"node": "ans: send breakdown", "type": "main", "index": 0}]]
}
sys.stderr.write("Rewired: headline -> wait (3.5s) -> breakdown\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
