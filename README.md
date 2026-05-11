# AI Challenge 2.0 — Task 3

> Vention AI Challenge 2.0 · Task 3: workflowing with n8n
> Submission by Rustam (@Warhammer2000)

## Project location

The project lives in [`task-3/`](./task-3/) per brief requirement ("project placed in a task-3 folder").

- **Live bot**: `@<tbd>_bot` (added at Day 8)
- **Usage guide**: [`task-3/README.md`](./task-3/README.md)
- **Build report**: [`task-3/report.md`](./task-3/report.md)
- **n8n workflow export**: [`task-3/workflow.json`](./task-3/workflow.json)

## Brief

AI-powered personal learning assistant delivered as a Telegram bot. Users submit URLs via `/learn`, a **Teacher** AI agent (Claude Opus 4.7) creates a structured summary with 5-7 key points + main concepts + difficulty. On `/quiz`, an **Examiner** AI agent (Claude Haiku 4.5) generates 5 interview-style questions specific to the material, validates user responses, and provides explanations for incorrect answers. Persists across sessions per Telegram `chat_id`.

**Wow factor angle**: domain bias — Teacher and Examiner system prompts skew toward **senior backend interview prep** (system design tradeoffs, .NET / distributed systems / DB internals). Not a generic "learn anything" bot — a real interview-prep coach.

Built using **n8n self-hosted on Docker** (not the cloud trial — real ops signal) with Postgres 18 for persistence and Cloudflare Tunnel for the Telegram webhook. Targets **Telegram Bot API v10.0** (latest, released 2026-05-08): MarkdownV2 + spoiler tags for explanations, `setMyCommands` + `setBotDescription` for branded profile, **Web App button** for the `/stats` analytics dashboard, message-reaction capture for material ratings.
