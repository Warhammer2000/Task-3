"""Patch 15: replace <url> with [URL] in i18n strings to avoid HTML tag parse errors.

Telegram's HTML parser treats `<url>` as an opening tag (unsupported) and
rejects the message with "can't parse entities". Switching to `[URL]` placeholder
is safe in both Markdown and HTML modes."""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

REPLACEMENTS = [
    ("/learn <url>",  "/learn [URL]"),
    ("`/learn <url>`", "`/learn [URL]`"),
    ("/learn &lt;url&gt;", "/learn [URL]"),
]

count = 0
for n in nodes:
    name = n.get('name','')
    code = n.get('parameters',{}).get('jsCode')
    if not code:
        continue
    new_code = code
    for old, new in REPLACEMENTS:
        new_code = new_code.replace(old, new)
    if new_code != code:
        n['parameters']['jsCode'] = new_code
        sys.stderr.write(f"Patched <url> in: {name}\n")
        count += 1

sys.stderr.write(f"Total: {count}\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
