"""Patch 26: /learn ack runs SEQUENTIALLY first + localized via stored lang.

Bug discovered via exec 217/243 timeline inspection:
  /learn: URL valid? main[0] was wired as parallel fan-out:
    [build ack text, jina fetch, react thinking]
  But n8n's IF node (and Postgres / Code nodes in similar situations —
  see patches 18-19) does NOT actually fan out — only one target executes.
  In every recent /learn exec, ONLY `jina fetch` ran. ack and 🤔 reaction
  were silently dropped.

Result: user typed /learn URL and saw NO feedback for 10-180 seconds
until the summary arrived. Exactly the UX problem the ack was meant
to solve.

Fix: rewire as a fully SEQUENTIAL chain:
  URL valid? TRUE
    -> lang: pg load /learn  (moved earlier; loads from user_state)
    -> /learn: build ack text  (now uses stored lang preference)
    -> /learn: send ack (loading)  (HTTP sendMessage, ~500ms)
    -> learn: react thinking  (HTTP setMessageReaction 🤔, ~400ms)
    -> /learn: jina fetch  (content extraction, 2-5s)
    -> /learn: extract title+body  (Code, was previously after jina)
    -> ... (rest unchanged through send summary -> react graduated 🎓)

Total cost: +900ms latency to summary delivery (ack send + reaction set
run sequentially before jina). Worth it for the user to see the bot is
working instead of staring at a frozen screen for up to 3 minutes.

Also: ack text now reads lang from user_state via lang: pg load /learn
(stored preference) instead of Telegram client from.language_code, so
the ack honours /lang choices. Defaults to 'en' if no row (per patch 25).
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)
with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)

# ============================================================
# 1. Rewrite /learn: build ack text to use stored lang
# ============================================================
LEARN_BUILD_ACK_JS = r"""// Build localized /learn ack text — uses stored /lang preference
const lang = $('lang: pg load /learn').item.json.lang || 'en';
const chatId = $('/learn: parse URL').item.json.chat_id;

const text = lang === 'ru'
  ? '🔍 Читаю статью и прогоняю через Claude Opus 4.7 для саммари — обычно 1–3 минуты, можно отойти заварить чай ☕'
  : '🔍 Reading the article and distilling it with Claude Opus 4.7 — usually 1–3 minutes, grab a coffee ☕';

const body_json = JSON.stringify({ chat_id: chatId, text });
return [{ json: { chat_id: chatId, body_json } }];"""

for n in nodes:
    if n.get('name') == '/learn: build ack text':
        n['parameters']['jsCode'] = LEARN_BUILD_ACK_JS
        sys.stderr.write("Patched /learn: build ack text (uses stored lang)\n")

# ============================================================
# 2. Rewire to fully sequential chain
# ============================================================
# Old wiring:
#   URL valid? main[0] = [build ack text, jina fetch, react thinking]   (parallel, n8n silently picks one)
#   /learn: jina fetch -> lang: pg load /learn -> extract title+body
#
# New wiring (sequential):
#   URL valid? main[0] = [lang: pg load /learn]
#   lang: pg load /learn -> build ack text
#   build ack text -> send ack
#   send ack -> react thinking
#   react thinking -> jina fetch
#   jina fetch -> extract title+body

connections['/learn: URL valid?'] = {
    "main": [
        [{"node": "lang: pg load /learn", "type": "main", "index": 0}],  # TRUE
        connections.get('/learn: URL valid?', {}).get('main', [[], []])[1] if len(connections.get('/learn: URL valid?', {}).get('main', [])) > 1 else [{"node": "/learn: reply invalid", "type": "main", "index": 0}]  # FALSE
    ]
}
# Ensure FALSE branch is correct
url_valid_main = connections['/learn: URL valid?']['main']
if not url_valid_main[1] or url_valid_main[1] == []:
    url_valid_main[1] = [{"node": "/learn: reply invalid", "type": "main", "index": 0}]
elif isinstance(url_valid_main[1], list) and url_valid_main[1] and isinstance(url_valid_main[1][0], list):
    url_valid_main[1] = url_valid_main[1][0]

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

sys.stderr.write("Rewired sequential: URL valid? -> lang load -> build ack -> send ack -> react -> jina -> extract\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
