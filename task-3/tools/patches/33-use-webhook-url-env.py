"""Patch 33: switch from $env.NGROK_DOMAIN to $env.WEBHOOK_URL.

Patch 32 parameterised the hardcoded ngrok domain via $env.NGROK_DOMAIN —
but that env var wasn't actually being passed into the n8n container.
Workflow nodes evaluating $env.NGROK_DOMAIN got 'undefined', producing
URLs like 'https://undefined/webhook/dashboard...' which Telegram
rejected: `inline keyboard button Web App URL ... Wrong HTTP URL`.

Two ways to fix:
(a) Add NGROK_DOMAIN: ${NGROK_DOMAIN} to docker-compose.yml n8n env section
(b) Use $env.WEBHOOK_URL instead — a STANDARD n8n env var that's always
    populated (n8n sets it from the container config) and already
    contains the full https://hostname

(b) wins for portability. Reviewers don't need to add a custom env var;
WEBHOOK_URL is part of any standard n8n deployment.

Switching the 4 patched locations from
  https://${$env.NGROK_DOMAIN}        →  ${$env.WEBHOOK_URL}
  https://{{ $env.NGROK_DOMAIN }}    →  {{ $env.WEBHOOK_URL }}

(WEBHOOK_URL already has the https:// scheme.)
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

OLD_EXPR_TEMPLATE = "https://{{ $env.NGROK_DOMAIN }}"
NEW_EXPR_TEMPLATE = "{{ $env.WEBHOOK_URL }}"

OLD_JS_TEMPLATE = "https://${$env.NGROK_DOMAIN}"
NEW_JS_TEMPLATE = "${$env.WEBHOOK_URL}"

count = 0
for n in nodes:
    name = n.get('name', '')
    params = n.get('parameters', {})

    if 'url' in params and isinstance(params['url'], str):
        if OLD_EXPR_TEMPLATE in params['url']:
            params['url'] = params['url'].replace(OLD_EXPR_TEMPLATE, NEW_EXPR_TEMPLATE)
            sys.stderr.write(f"Patched url in: {name}\n")
            count += 1

    if 'jsCode' in params and isinstance(params['jsCode'], str):
        if OLD_JS_TEMPLATE in params['jsCode']:
            params['jsCode'] = params['jsCode'].replace(OLD_JS_TEMPLATE, NEW_JS_TEMPLATE)
            sys.stderr.write(f"Patched jsCode in: {name}\n")
            count += 1

    if 'jsonBody' in params and isinstance(params['jsonBody'], str):
        if OLD_EXPR_TEMPLATE in params['jsonBody']:
            params['jsonBody'] = params['jsonBody'].replace(OLD_EXPR_TEMPLATE, NEW_EXPR_TEMPLATE)
            sys.stderr.write(f"Patched jsonBody in: {name}\n")
            count += 1

sys.stderr.write(f"\nTotal patches: {count}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
