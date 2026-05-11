"""Patch 32: parameterise hardcoded ngrok domain in workflow.json.

`seniorprepcoach.ngrok.dev` was hardcoded in 3 webhook URLs inside the
workflow (pool-refill self-fire, /learn pool trigger, pick pool trigger,
Mini App dashboard link). If a reviewer imports workflow.json into their
own n8n, those webhook calls would hit OUR ngrok domain instead of theirs.

Fix: replace hardcoded URL with `{{ $env.NGROK_DOMAIN }}` so it resolves
from the deployer's own .env at runtime.

Not a security issue (no auth bypass — pool-refill webhook responds 200
OK to any caller and only acts on material_ids that exist in the DB),
but a real reusability bug that would break the bot for any other deployer.
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

HARDCODED = "https://seniorprepcoach.ngrok.dev"
TEMPLATE = "https://{{ $env.NGROK_DOMAIN }}"

count = 0
for n in nodes:
    name = n.get('name', '')
    params = n.get('parameters', {})

    # Patch HTTP Request node URL field
    if 'url' in params and isinstance(params['url'], str):
        if HARDCODED in params['url']:
            params['url'] = params['url'].replace(HARDCODED, TEMPLATE)
            sys.stderr.write(f"Patched url in: {name}\n")
            count += 1

    # Patch Code node jsCode strings
    if 'jsCode' in params and isinstance(params['jsCode'], str):
        if HARDCODED in params['jsCode']:
            params['jsCode'] = params['jsCode'].replace(
                HARDCODED,
                "${process.env.NGROK_DOMAIN ? 'https://' + process.env.NGROK_DOMAIN : 'https://seniorprepcoach.ngrok.dev'}"
            )
            # Simpler: just use a template literal that reads from env at runtime
            # Actually n8n Code nodes can use $env directly
            params['jsCode'] = params['jsCode'].replace(
                "${process.env.NGROK_DOMAIN ? 'https://' + process.env.NGROK_DOMAIN : 'https://seniorprepcoach.ngrok.dev'}",
                "https://${$env.NGROK_DOMAIN}"
            )
            sys.stderr.write(f"Patched jsCode in: {name}\n")
            count += 1

    # Patch JSON body fields (httpRequest sometimes has jsonBody)
    if 'jsonBody' in params and isinstance(params['jsonBody'], str):
        if HARDCODED in params['jsonBody']:
            params['jsonBody'] = params['jsonBody'].replace(HARDCODED, TEMPLATE)
            sys.stderr.write(f"Patched jsonBody in: {name}\n")
            count += 1

sys.stderr.write(f"\nTotal patches: {count}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
