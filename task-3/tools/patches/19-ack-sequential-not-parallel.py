"""Patch 19: make pick: ack a SEQUENTIAL link (pg load -> ack -> lang load -> examiner)
instead of parallel branch.

n8n's execution engine does depth-first traversal of multi-target branches —
the full subtree of one target completes before the next target starts.
Putting ack as a parallel sibling of examiner means ack runs AFTER the whole
examiner chain (25s+). Inlining ack as a sequential link makes it run before
the slow LLM call.

Ack uses Telegram's from.language_code as fallback (instant, no DB).
"""
import json, sys

with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)
with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# ============================================================
# 1. Update pick: build ack text to use Telegram from.language_code
#    (no dependency on lang: pg load pick which runs later)
# ============================================================
PICK_BUILD_ACK_JS = r"""// Build localized pick ack text — uses Telegram's from.language_code
// since this node runs BEFORE lang: pg load pick to keep latency low.
const tgLang = $('Telegram Trigger1').item.json.callback_query?.from?.language_code || 'en';
const ru = tgLang.startsWith('ru');
const chatId = $('pick: pg load material').item.json.chat_id;
const title = $('pick: pg load material').item.json.title || '';

const text = ru
  ? `🎯 Генерирую 5 senior-level вопросов по теме "${title}" через Claude Haiku 4.5 — обычно 30 секунд – 2 минуты.\n\nКак только готово — пришлю первый вопрос как Telegram-опрос.`
  : `🎯 Generating 5 senior-level questions on "${title}" with Claude Haiku 4.5 — usually 30 seconds – 2 minutes.\n\nFirst question will arrive as a Telegram poll.`;

const body_json = JSON.stringify({ chat_id: chatId, text });
return [{ json: { chat_id: chatId, body_json } }];"""

for n in nodes:
    if n.get('name') == 'pick: build ack text':
        n['parameters']['jsCode'] = PICK_BUILD_ACK_JS
        sys.stderr.write("Patched pick: build ack text (uses tg from.language_code)\n")

# ============================================================
# 2. Rewire: pg load material -> build ack text -> send ack -> lang: pg load pick -> build examiner body -> ...
# ============================================================

# Current: pg load material -> lang: pg load pick -> [build ack text, build examiner body]
# Target:  pg load material -> build ack text -> send ack -> lang: pg load pick -> build examiner body

# Step 1: pg load material -> build ack text only
connections['pick: pg load material'] = {
    "main": [[{"node": "pick: build ack text", "type": "main", "index": 0}]]
}
sys.stderr.write("Wired pg load material -> build ack text\n")

# Step 2: build ack text -> send ack
connections['pick: build ack text'] = {
    "main": [[{"node": "pick: send ack", "type": "main", "index": 0}]]
}

# Step 3: send ack -> lang: pg load pick
connections['pick: send ack'] = {
    "main": [[{"node": "lang: pg load pick", "type": "main", "index": 0}]]
}
sys.stderr.write("Wired send ack -> lang: pg load pick\n")

# Step 4: lang: pg load pick -> build examiner body ONLY (no more parallel ack)
connections['lang: pg load pick'] = {
    "main": [[{"node": "pick: build examiner body", "type": "main", "index": 0}]]
}
sys.stderr.write("Simplified lang: pg load pick -> build examiner body (no parallel ack)\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
sys.stderr.write("Done.\n")
