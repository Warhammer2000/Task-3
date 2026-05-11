"""Patch 20: lang loader runs BEFORE ack, ack reads stored preference.

Chain: pg load material -> lang: pg load pick -> build ack text -> send ack -> build examiner body -> Examiner -> ...

Trade-off: ack now waits 1 extra DB roundtrip (~15ms) but honors the user's
/lang preference instead of Telegram client language.
"""
import json, sys

with open('C:/tmp/db_conn.json', 'r', encoding='utf-8') as f:
    connections = json.load(f)
with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# 1. Update pick: build ack text to read lang from lang: pg load pick again
PICK_BUILD_ACK_JS = r"""// Build localized pick ack text — uses stored /lang preference
const lang = $('lang: pg load pick').item.json.lang || 'en';
const chatId = $('pick: pg load material').item.json.chat_id;
const title = $('pick: pg load material').item.json.title || '';

const text = lang === 'ru'
  ? `🎯 Генерирую 5 senior-level вопросов по теме "${title}" через Claude Haiku 4.5 — обычно 30 секунд – 2 минуты.\n\nКак только готово — пришлю первый вопрос как Telegram-опрос.`
  : `🎯 Generating 5 senior-level questions on "${title}" with Claude Haiku 4.5 — usually 30 seconds – 2 minutes.\n\nFirst question will arrive as a Telegram poll.`;

const body_json = JSON.stringify({ chat_id: chatId, text });
return [{ json: { chat_id: chatId, body_json } }];"""

for n in nodes:
    if n.get('name') == 'pick: build ack text':
        n['parameters']['jsCode'] = PICK_BUILD_ACK_JS
        sys.stderr.write("Patched pick: build ack text (reads stored lang)\n")

# 2. Rewire: pg load material -> lang: pg load pick -> build ack text -> send ack -> build examiner body
connections['pick: pg load material'] = {
    "main": [[{"node": "lang: pg load pick", "type": "main", "index": 0}]]
}
connections['lang: pg load pick'] = {
    "main": [[{"node": "pick: build ack text", "type": "main", "index": 0}]]
}
connections['pick: build ack text'] = {
    "main": [[{"node": "pick: send ack", "type": "main", "index": 0}]]
}
connections['pick: send ack'] = {
    "main": [[{"node": "pick: build examiner body", "type": "main", "index": 0}]]
}
sys.stderr.write("Rewired chain: pg load -> lang load -> build ack -> send ack -> build examiner\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
with open('C:/tmp/db_conn_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(connections, f, ensure_ascii=False)
