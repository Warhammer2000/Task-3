# Senior Interview Prep Coach — Telegram Bot

> AI-powered personal learning assistant. Submit a URL → get a senior-engineer-grade summary → take an interview-style quiz → track weak topics on a Mini App dashboard.

**Built for**: Vention AI Challenge 2.0 · Task 3 — *workflowing with n8n*

## Submission artifacts (quick links)

| What | Where |
|------|-------|
| **Live Telegram bot** | [@seniorprepcoach_bot](https://t.me/seniorprepcoach_bot) — tap **Start**, send `/learn <url>`, then `/quiz` |
| **n8n workflow JSON** | [`workflow.json`](./workflow.json) — 95 nodes, re-imports cleanly into any n8n instance |
| **Build report** | [`report.md`](./report.md) — tools, what worked, what didn't, 11 distinct bug classes documented, full pool-architecture write-up in §5.9 |
| **Database schema** | [`db/init/01_schema.sql`](./db/init/01_schema.sql) — 6 tables + 1 view, auto-loaded on first Postgres boot |
| **Docker compose** | [`docker-compose.yml`](./docker-compose.yml) — n8n + Postgres + ngrok |
| **Build tooling** | [`tools/`](./tools/) — 23 versioned patch scripts + [`tools/README.md`](./tools/README.md) explaining each |

The bot is live right now — easiest way to evaluate is to message it directly. The walkthrough below shows what you'll see.

---

## How to use

1. Open Telegram, find [@seniorprepcoach_bot](https://t.me/seniorprepcoach_bot), tap **Start**.
2. Send a URL with the `/learn` command:
   ```
   /learn https://martinfowler.com/articles/microservices.html
   ```
   The bot reacts 🤔 → posts an "🔍 Reading the article…" ack → ~1–3 min later you get a structured summary (5–7 key points, main concepts, difficulty) with a 🎯 **Take quiz now** button. Bot also reacts 🎓 on your original `/learn` message when the summary is delivered.
3. Tap **Take quiz** (or send `/quiz` later and pick a topic). The bot generates 5 multiple-choice questions specific to that material via Claude Haiku — questions arrive as native Telegram polls with single-tap voting.
4. Answer all 5. The bot delivers a **headline** ("🏆 Quiz complete: 4/5 (80%)") with a fullscreen animation effect (🔥 / ✨ / 💡 / 🥊 depending on score), then 3.5 seconds later the full **breakdown** with the correct answer for each question and an explanation.
5. Send `/stats` to see your dashboard summary in chat — tap **📈 Open full dashboard** to open the Telegram **Mini App** with charts, an activity heatmap, and achievement badges.
6. Switch language any time with `/lang` — pick **🇬🇧 English** or **🇷🇺 Русский**. All summaries, quizzes, explanations, and UX strings update.
7. From any other chat, type `@seniorprepcoach_bot <topic>` to search your library inline — tap a result to send the quiz button into that chat.

---

## Commands

| Command | What it does |
|---------|--------------|
| `/start` | Welcome message and command list. |
| `/learn <url>` | Save a learning material. Bot fetches the URL via [jina.ai reader](https://r.jina.ai), the **Teacher** (Claude Opus 4.7) extracts a structured summary (5–7 key points, main concepts, difficulty calibrated to a **senior backend bar**, interview angle), and the material is stored. Replies with summary + 🎯 Take quiz button. |
| `/quiz` | Lists your saved materials as tappable buttons. Pick one → the **Examiner** (Claude Haiku 4.5) generates 5 interview-style multiple-choice questions specific to that material. Questions arrive as Telegram polls (native quiz UI with single correct option). |
| `/stats` | In-chat summary (materials saved per difficulty, quizzes taken, average score, last quiz date) + **📈 Open full dashboard** button → Telegram Mini App with charts and 28-day activity heatmap. |
| `/lang` | Inline-keyboard picker [🇬🇧 English ǀ 🇷🇺 Русский]. Choice persists in `app.user_state.lang`; affects bot UX, summary content (Teacher gets directive), and quiz content (Examiner gets directive). |
| `@seniorprepcoach_bot <query>` | Inline mode in any chat. Searches your library by title; tap a result to send a material card with a Start-quiz button. |

---

## What makes this submission different

Beyond the brief's required behavior, this bot uses Bot API 7.0+ features that **most participants will not touch**, plus a self-replenishing quiz cache that delivers near-instant quizzes:

- **Quiz pool with self-replenishing buffer** — after the very first `/learn` on a topic, a background worker pre-generates **3 quizzes** for that material via Claude Sonnet 4.5. When the user taps "Take quiz now", the bot atomically claims a pre-generated quiz from the pool (`DELETE...FOR UPDATE SKIP LOCKED RETURNING`) and ships Q1 in **<500ms** instead of waiting 30-60s for an Examiner call. Each claim fires a top-up refill webhook that maintains pool depth = 3. **First user pays the wait; subsequent users get instant quizzes.** Concurrency-safe (two users on same material claim different pool entries). Pool variety enforced via temperature 0.9 + uniqueness directive passing all prior question stems to Sonnet + post-parse Jaccard-bigram similarity check. See [`report.md` §5.9](./report.md) for the full architecture.
- **`setMessageReaction`** — bot reacts 🤔 on `/learn` receipt and 🎓 when the summary is delivered, on the user's original message. The bot "breathes".
- **`message_effect_id`** — quiz score headline ships with a fullscreen animation: 🔥 fire (80%+), ✨ confetti (60–79%), 💡 thumbs up (40–59%), 🥊 thumbs down (<40%). Mobile clients render the animation; desktop falls back to a static effect icon.
- **Telegram Mini App** (`web_app` button) — `/stats` opens an embedded HTML dashboard inside Telegram via the Mini App platform: KPI cards with count-up animations, doughnut for difficulty mix, gradient-fill score-trend line, GitHub-style 28-day activity heatmap, 7 achievement badges that unlock based on real data, library and recent-quiz listings. Theme params from Telegram are inherited so it adapts to the user's dark/light client.
- **Inline mode** — `@seniorprepcoach_bot search` from any chat, anywhere. Search across the user's library by title.
- **`sendPoll` quiz mode** — instead of inline-keyboard buttons, quizzes use Telegram's native poll UI with `type: 'quiz'`, single-correct-option, instant feedback animations.
- **Full RU/EN localization** — Teacher and Examiner system prompts get an appended language directive so summaries and quizzes are in the user's chosen language; all UX text (commands help, ack messages, dashboard labels, score messages, explanations) localized via a dictionary loaded from `app.user_state.lang`.

---

## Architecture

```
Telegram client (mobile / desktop / web)
       │  HTTPS
       ▼
ngrok named-tunnel (seniorprepcoach.ngrok.dev)
       │  forwards to n8n:5678 over Docker bridge network
       ▼
n8n (Docker, v2.19.5, self-hosted)
       │
       ├─► HTTP Request → r.jina.ai/<url>         (content extraction)
       ├─► HTTP Request → api.anthropic.com       (Teacher: Opus 4.7)
       ├─► HTTP Request → api.anthropic.com       (Examiner: Sonnet 4.5,
       │                                           in BOTH pool refill chain
       │                                           and slow-path fallback)
       ├─► Postgres 18-alpine (Docker)            (persistence layer)
       │       └─ app.learning_materials, app.quizzes, app.quiz_answers,
       │          app.user_state, app.material_reactions, app.v_user_stats,
       │          app.quiz_pool (pre-generated quiz buffer)
       ├─► HTTP Request → api.telegram.org        (sendMessage, sendPoll,
       │                                           setMessageReaction,
       │                                           answerInlineQuery, answerCallbackQuery)
       ├─► Webhook node serving GET /dashboard    (Mini App HTML — Chart.js)
       └─► Webhook node serving POST /pool-refill (self-firing pool replenisher)
```

95 nodes total. Workflow file: [`workflow.json`](./workflow.json) (re-imports cleanly into a fresh n8n instance).

---

## Run it yourself

### Prerequisites

- Docker Desktop / Docker Engine 24+
- A Telegram bot token (chat with [@BotFather](https://t.me/BotFather) → `/newbot`)
- An Anthropic API key with access to `claude-opus-4-5` and `claude-haiku-4-5-20251001`
- An ngrok account (free) — for the persistent HTTPS endpoint Telegram requires

### 1. Clone and configure

```bash
git clone https://github.com/Warhammer2000/Task-3.git
cd Task-3/task-3
cp .env.example .env
```

Edit `.env`:

```bash
POSTGRES_PASSWORD=...               # any strong random string
N8N_ENCRYPTION_KEY=...              # openssl rand -hex 32
TELEGRAM_BOT_TOKEN=...              # from BotFather
ANTHROPIC_API_KEY=sk-ant-...        # from console.anthropic.com
NGROK_AUTHTOKEN=...                 # from dashboard.ngrok.com/get-started/your-authtoken
NGROK_DOMAIN=yourname.ngrok.dev     # your reserved named tunnel domain
```

### 2. Bring up the stack

```bash
docker compose up -d
docker compose logs -f n8n
# wait for: "Editor is now accessible via: https://<your-ngrok-domain>"
```

Three containers come up:

| Container | Purpose |
|-----------|---------|
| `task3-postgres` | Postgres 18-alpine, port `5434:5432`. Auto-runs `db/init/01_schema.sql` on first boot to create the `app.*` schema. |
| `task3-n8n` | n8n editor on port `5679:5678`. Webhook endpoint is `/webhook/task3-telegram-trigger/webhook` exposed via ngrok. |
| `task3-ngrok` | Provides the public HTTPS endpoint `https://<your-ngrok-domain>` that forwards to `n8n:5678` over the Docker network. |

### 3. Import the workflow

1. Open the n8n editor at `https://<your-ngrok-domain>` (you'll set an email + password on first visit).
2. **Workflows** → **Import from File** → select `task-3/workflow.json`.
3. Open the imported workflow. Three credentials need binding (n8n shows red borders):
   - **Telegram Bot** credential → paste `${TELEGRAM_BOT_TOKEN}`.
   - **Anthropic** credential → paste `${ANTHROPIC_API_KEY}`.
   - **Postgres** credential → host `postgres`, port `5432`, user/db/password from `.env`.
4. Toggle **Active** (top-right). On activation, n8n calls Telegram's `setWebhook` with the ngrok URL + `allowed_updates: [message, inline_query, callback_query, poll_answer]`.

### 4. (Optional) Enable inline mode

To get the `@bot search` feature, open [@BotFather](https://t.me/BotFather):

1. `/setinline` → choose your bot → enter placeholder text (e.g. `search your materials`).

### 5. Try it

```
/start
/learn https://martinfowler.com/articles/microservices.html
# wait ~1–2 min for the summary — while you read it, the pool refill
# webhook fires in background and Sonnet 4.5 starts generating 3 quizzes
# tap "🎯 Take quiz now" — by this point 1–3 pool entries are ready,
# so Q1 arrives in <500ms (instead of waiting another 30-60s)
# answer the 5 polls
# /stats → 📈 Open full dashboard
# /lang → 🇷🇺 Русский → /quiz again to see localized output
```

If you import an existing database (or add materials before the pool feature is wired up), warm the pool for all existing materials at once:

```bash
bash tools/warmup-pool.sh both       # fires refill for every material × {en, ru}
# monitor progress:
docker compose exec postgres psql -U n8n -d n8n -c \
  "SELECT material_id, lang, COUNT(*) FROM app.quiz_pool GROUP BY 1,2 ORDER BY 1,2;"
```

---

## Project layout

```
Task-3/
└── task-3/                          ← per brief "project in task-3 folder"
    ├── README.md                    ← this file (user guide)
    ├── report.md                    ← decisions + what worked + what didn't
    ├── workflow.json                ← n8n workflow export (77 nodes)
    ├── docker-compose.yml           ← n8n + postgres + ngrok
    ├── .env.example                 ← copy → .env, fill values
    ├── db/init/01_schema.sql        ← Postgres schema (auto-loaded)
    ├── docs/                        ← architecture diagram, demo screenshots
    ├── prompts/                     ← Teacher & Examiner system prompts (versioned)
    └── tools/
        ├── README.md                ← how patches were built and applied
        └── patches/                 ← 16 chronological build-step scripts
```

---

## Common operations

```bash
# Tail n8n logs
docker compose logs -f n8n

# Connect to Postgres
docker compose exec postgres psql -U n8n -d n8n
# Inside psql:
#   \dt app.*
#   SELECT id, title, difficulty FROM app.learning_materials ORDER BY id DESC LIMIT 5;
#   SELECT id, score_pct, finished_at FROM app.quizzes ORDER BY id DESC LIMIT 5;

# Re-set bot webhook after changing the tunnel URL
curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"https://$NGROK_DOMAIN/webhook/task3-telegram-trigger/webhook\",\"allowed_updates\":[\"message\",\"inline_query\",\"callback_query\",\"poll_answer\"]}"
# NOTE: this drops n8n's secret_token. Better way: toggle workflow off/on in
# the editor — n8n re-registers the webhook with its own secret.

# Backup database
docker compose exec postgres pg_dump -U n8n n8n | gzip > backup-$(date +%F).sql.gz

# Reset (DROPS database — data is gone)
docker compose down -v
```

---

## Stack & defaults

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Workflow runtime | n8n self-hosted (`n8nio/n8n:latest`, v2.19.5) | No trial limits, full env access, full Postgres node features. |
| Database | Postgres 18-alpine, host port `5434` | Both n8n metadata and project `app.*` schema in one DB. Port 5434 avoids collision with default 5432 used by side projects. |
| Public HTTPS | ngrok named-tunnel as a compose service | Persistent domain across restarts. Telegram needs HTTPS for webhooks. |
| Teacher LLM | Claude Opus 4.7 | Heavy reasoning, calibrated difficulty assessment, long-context article digestion. |
| Examiner LLM | Claude Haiku 4.5 | Fast structured-JSON output, cheap, sufficient for bounded question generation. |
| URL fetch | `r.jina.ai/<url>` | Handles paywalled / JS-rendered / SPA URLs. Returns clean markdown. |
| Bot API | Telegram Bot API v10.0+ (2026) | Mini Apps via `web_app` button, `setMessageReaction`, `message_effect_id`, native quiz polls. |

For decisions, what worked, what didn't, the four classes of n8n quirk discovered, and how each was fixed — see [`report.md`](./report.md).
