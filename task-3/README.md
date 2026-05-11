# Task 3 — Senior Interview Prep Coach (Telegram + n8n)

> AI-powered personal learning assistant delivered as a Telegram bot.
> Submit a URL → get a senior-engineer-grade summary → take an interview-style quiz → track weak topics.

**Built for**: Vention AI Challenge 2.0 · Task 3 — *workflowing with n8n*

**Live bot**: `@<tbd>_bot` (final handle added Day 8)
**Process docs**: see [`ai-challenge-2026/task-3/`](https://github.com/Warhammer2000/ai-challenge-2026/tree/task-3/main/task-3) for BRIEF / PLAN / SELF-REVIEW / retrospective.

This is a **usage guide**. For technical decisions and what shipped, see [`report.md`](./report.md) (added at Day 7).

---

## What it does

| Command | What happens |
|---------|--------------|
| `/start` | Welcome message + 3-command help; bot remembers you by Telegram `chat_id`. |
| `/learn <url>` | Bot fetches the URL, the **Teacher** (Claude Opus 4.7) extracts 5-7 key points + main concepts + difficulty (beginner / intermediate / advanced, calibrated to **senior backend bar**). Reply uses MarkdownV2 with bold concepts. Inline **"🎯 Take quiz"** button kicks off Step 3 directly. |
| `/quiz` | Shows your saved materials as inline buttons; pick one → **Examiner** (Claude Haiku 4.5) generates 5 interview-style questions specific to the material. Questions arrive one-by-one with A/B/C/D inline buttons. Score reported as `X/5 (Y%)`; wrong answers get explanations behind spoiler tags. |
| `/stats` | Opens a Telegram **Web App** dashboard inside the chat: per-topic score trend, weak concepts, time per topic, materials backlog. (Bot API v10.0 feature.) |

The Teacher and Examiner are **two distinct AI roles**, each with its own system prompt and model. Examples and emphasis are biased toward .NET / distributed systems / database internals — not generic learning.

---

## Architecture (high-level)

```
Telegram client
     │  HTTPS
     ▼
Cloudflare Tunnel  ──► n8n (Docker)
                          │
                          ├─► HTTP Request (URL fetch, Readability extract)
                          ├─► Anthropic API (Opus, Haiku)
                          ├─► Postgres 18 (Docker) — learning_materials,
                          │   quizzes, quiz_attempts, user_state
                          └─► Telegram Bot API v10.0 (replies, inline buttons,
                              spoiler MarkdownV2, Web App, reactions)
```

Full C4 diagram in [`report.md`](./report.md) once it lands.

---

## Quickstart — run it yourself

### Prerequisites

- Docker Desktop or Docker Engine 24+
- Cloudflare account (free tier) with one domain — for Tunnel HTTPS endpoint
- Telegram account
- Anthropic API key with access to `claude-opus-4-7` and `claude-haiku-4-5-20251001`

### 1. Telegram bot

1. Open Telegram → DM **@BotFather** → `/newbot` → follow prompts → copy the token.
2. (Optional but recommended) Polish the bot profile via BotFather:
   - `/setdescription` → "Senior backend interview prep coach. Send a URL — get a summary and a 5-question quiz."
   - `/setabouttext` → short tagline (≤ 120 chars)
   - `/setcommands` → paste:
     ```
     start - Welcome and help
     learn - Submit a URL to learn from (usage: /learn https://...)
     quiz - Start a quiz from your saved materials
     stats - Open your learning dashboard
     ```
   *(The workflow also calls `setMyCommands` programmatically on first run — BotFather setup is optional defensive layer.)*

### 2. Cloudflare Tunnel (HTTPS for the Telegram webhook)

Telegram requires HTTPS — `localhost` won't work. Cloudflare Tunnel gives a free, persistent public hostname.

1. Install `cloudflared` ([docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/)).
2. `cloudflared tunnel login` → authorize your domain.
3. `cloudflared tunnel create task3-bot` → note the tunnel ID.
4. Add a DNS route, e.g. `task3-bot.yourdomain.tld`:
   ```bash
   cloudflared tunnel route dns task3-bot task3-bot.yourdomain.tld
   ```
5. Run the tunnel (in a separate terminal):
   ```bash
   cloudflared tunnel --url http://localhost:5678 run task3-bot
   ```
   For persistence, install as a service: `cloudflared service install <tunnel-token>`.

### 3. Configure environment

```bash
cd task-3
cp .env.example .env
# Edit .env with your real values:
#   POSTGRES_PASSWORD     → strong random string
#   N8N_ENCRYPTION_KEY    → openssl rand -hex 32
#   N8N_HOST / N8N_WEBHOOK_URL → your Cloudflare Tunnel hostname (https://...)
#   TELEGRAM_BOT_TOKEN    → BotFather token
#   ANTHROPIC_API_KEY     → your sk-ant-... key
```

### 4. Spin up the stack

```bash
docker compose up -d
docker compose logs -f n8n
# wait for: "Editor is now accessible via: https://<your-host>/"
```

Open the n8n editor at the URL above (auth uses email/password — set on first visit).

### 5. Import the workflow

1. In n8n editor → **Workflows** → **Import from File** → pick `task-3/workflow.json`.
2. Open the imported workflow → set credentials:
   - **Telegram Bot** credential → paste `TELEGRAM_BOT_TOKEN` (or reference the env var).
   - **Anthropic** credential → paste `ANTHROPIC_API_KEY`.
   - **Postgres** credential → host `postgres`, port `5432`, user/db from `.env`.
3. **Activate** the workflow (toggle top-right).
4. On activation, the Telegram Trigger node registers the webhook against `${N8N_WEBHOOK_URL}`.

### 6. Try it

In Telegram → DM your bot → `/start` → `/learn https://martinfowler.com/articles/microservices.html` → wait ~15 sec for summary → tap "🎯 Take quiz" → answer 5 questions → check `/stats`.

---

## Project layout

```
Task-3/
├── README.md                  ← repo overview (this brief)
└── task-3/                    ← per brief: "project in task-3 folder"
    ├── README.md              ← THIS FILE (usage guide)
    ├── report.md              ← build write-up (added Day 7)
    ├── docker-compose.yml     ← n8n + postgres
    ├── .env.example           ← copy → .env, fill values
    ├── workflow.json          ← n8n workflow export (re-imports cleanly)
    ├── db/init/               ← Postgres init scripts (schema)
    └── docs/                  ← C4 diagram, demo screenshots
```

---

## Common operations

```bash
# Tail n8n logs
docker compose logs -f n8n

# Connect to Postgres
docker compose exec postgres psql -U n8n -d n8n

# Backup Postgres
docker compose exec postgres pg_dump -U n8n n8n | gzip > backup-$(date +%F).sql.gz

# Stop + remove containers (volumes preserved)
docker compose down

# Nuke everything (DROPS DATABASE — be sure)
docker compose down -v
```

---

## Stack & defaults

- **n8n**: `n8nio/n8n:latest` self-hosted via Docker Compose
- **Postgres**: `postgres:18-alpine`, mapped to host port `5433` (avoids collision with default 5432)
- **Telegram Bot API**: v10.0 (May 2026) — MarkdownV2, spoiler tags, setMyCommands, Web App, message reactions
- **AI**:
  - Teacher → Claude **Opus 4.7** (heavy reasoning, summarization, difficulty assessment)
  - Examiner → Claude **Haiku 4.5** (fast question generation, structured JSON output for deterministic answer validation)
- **HTTPS**: Cloudflare Tunnel (free, persistent named tunnel)

For decisions, what worked, what didn't, see [`report.md`](./report.md).
