"""Replace ans: send results (Telegram node) with HTTP Request so HTML + effect work."""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

count = 0
for n in nodes:
    if n.get('name') == 'ans: send results' and n.get('type','').endswith('.telegram'):
        old_pos = n.get('position', [0,0])
        old_id = n.get('id')
        new = {
            "parameters": {
                "method": "POST",
                "url": "=https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ $json.body_json }}",
                "options": {}
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": old_pos,
            "id": old_id,
            "name": "ans: send results"
        }
        n.clear()
        n.update(new)
        count += 1
        sys.stderr.write("Replaced ans: send results (telegram -> httpRequest)\n")

sys.stderr.write(f"Total: {count}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
