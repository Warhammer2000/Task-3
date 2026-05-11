"""Patch 27: /learn: jina fetch URL changed to named ref.

Bug from patch 26 sequential rewire:

  Old chain:  URL valid? -> jina fetch     ($json.url worked: URL valid?'s
                                            data flowed straight in)
  New chain:  URL valid? -> ... -> react thinking -> jina fetch
              ($json.url undefined: react thinking's $json is the Telegram
              API response, which has no url field)

  Result: HTTP Request URL = "https://r.jina.ai/undefined" → jina returns
  its landing page placeholder text → extract title+body sees < 200 chars
  → extraction_failed=true → Teacher body undefined → Anthropic call 400.

Fix: replace $json.url with $('/learn: parse URL').item.json.url — the
named-node reference that survives any future mid-chain insertion (same
lesson as patch 14 for downstream Code nodes).
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

for n in nodes:
    if n.get('name') == '/learn: jina fetch':
        old_url = n['parameters'].get('url', '')
        new_url = old_url.replace("$json.url", "$('/learn: parse URL').item.json.url")
        if new_url != old_url:
            n['parameters']['url'] = new_url
            sys.stderr.write(f"Patched /learn: jina fetch URL\n  before: {old_url}\n  after:  {new_url}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
