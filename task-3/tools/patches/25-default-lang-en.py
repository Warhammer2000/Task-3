"""Patch 25: default lang is ALWAYS English on first /start.

Patch 24 auto-detected language from Telegram client's from.language_code,
so a Russian-Telegram user got Russian bot by default. User decision: too
clever, prefer English as universal default. Users who want Russian can
explicitly /lang ru.

Also align /start: build text — its welcome message is the FIRST thing
users see, so it too should default to English (not branch on client
language_code). Users who switch via /lang see the next message in their
chosen language; the welcome itself is universal English.
"""
import json, sys

with open('C:/tmp/db_nodes.json', 'r', encoding='utf-8') as f:
    nodes = json.load(f)

# ============================================================
# 1. /start: pg seed lang — always 'en'
# ============================================================
START_UPSERT_SQL = (
    "INSERT INTO app.user_state (chat_id, lang)\n"
    "VALUES (\n"
    "  {{ $('Telegram Trigger1').item.json.message.chat.id }},\n"
    "  'en'\n"
    ")\n"
    "ON CONFLICT (chat_id) DO NOTHING\n"
    "RETURNING chat_id, lang;"
)

for n in nodes:
    if n.get('name') == '/start: pg seed lang':
        n['parameters']['query'] = START_UPSERT_SQL
        sys.stderr.write("Patched /start: pg seed lang -> always 'en'\n")

# ============================================================
# 2. /start: build text — drop the client-lang branch, always English
# ============================================================
START_BUILD_JS = r"""// Build /start welcome message — always English (universal default).
// Russian-preferring users can switch via /lang at any time.
const chatId = $('Telegram Trigger1').item.json.message.chat.id;

const text = `👋 *Welcome to Senior Interview Coach!*

I'm an AI-powered learning bot for senior backend interview prep — built on n8n + Claude (Opus 4.7 Teacher, Sonnet 4.5 Examiner).

*What I can do:*

📚 \`/learn [URL]\` — submit any article / docs / blog post URL → I'll extract the content and produce a structured summary (5-7 key points + main concepts + difficulty) calibrated to the senior backend bar.

🎯 \`/quiz\` — pick a saved material → I'll generate 5 senior-level multiple-choice questions with intelligent answer validation and explanations.

📊 \`/stats\` — see your learning dashboard (materials, quizzes taken, average score) + button to open the Mini App with charts and an activity heatmap.

🌐 \`/lang\` — switch bot language (English / Русский).

🔍 \`@seniorprepcoach_bot <query>\` — search your saved materials inline from any chat.

*Try it right now:*
\`/learn https://martinfowler.com/articles/microservices.html\``;

const body_json = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
return [{ json: { chat_id: chatId, body_json } }];"""

for n in nodes:
    if n.get('name') == '/start: build text':
        n['parameters']['jsCode'] = START_BUILD_JS
        sys.stderr.write("Patched /start: build text -> English-only\n")

with open('C:/tmp/db_nodes_fixed.json', 'w', encoding='utf-8') as f:
    json.dump(nodes, f, ensure_ascii=False)
sys.stderr.write("Saved.\n")
