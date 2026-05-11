# Task 3 — Senior Interview Coach · Report

> **Live bot**: `@seniorprepcoach_bot`
> **Repository**: <https://github.com/Warhammer2000/Task-3>
> **Brief theme**: workflowing with n8n — AI-powered personal learning assistant (Telegram bot)

This document covers the tools and techniques used, what worked, what didn't, and the notable decisions made during development. For end-user usage instructions, see [`README.md`](./README.md).

---

## 1. Approach — operator-overridden submit-day-of-brief, eyes open

The Vention AI Challenge 2.0 explicitly says *"this is not a speedrun challenge — a rushed submission will not qualify"*. My personal Mahoraga adaptation from Task 2 added **submit-day-of-brief = anti-pattern** as a structural rule (CLAUDE.md §10). For Task 3 I overrode that rule deliberately: the brief landed at midday, peer behaviour on prior tasks was same-day submission, and the upside (early-in-leaderboard signal) outweighed the documented risk of missing a detail.

The trade-off: **all twelve days of buffer compressed into one session**. That made the build narrative front-loaded (infra + AI orchestration in ~3h) and then back-loaded with a long iteration tail debugging n8n quirks the documentation does not surface. I documented every fix that landed so the resulting workflow JSON is reproducible from a clean clone, not magic that worked once on this laptop.

---

## 2. Tools and techniques

| Tool | Used for |
|------|----------|
| **n8n self-hosted** (`n8nio/n8n:latest`, v2.19.5) on Docker Compose | Workflow runtime — Telegram trigger, HTTP requests, Code nodes, Switch routing, Postgres node, IF gates |
| **Postgres 18-alpine** (Docker Compose) | Both n8n's own metadata storage AND the project's `app.*` schema (5 tables + 1 view): `learning_materials`, `quizzes`, `quiz_answers`, `user_state`, `material_reactions`, `v_user_stats` |
| **ngrok** (`ngrok/ngrok:latest`) named-tunnel as a compose service | Stable public HTTPS URL `seniorprepcoach.ngrok.dev` → forwards to `n8n:5678` over the compose bridge network. Survives container restarts, no host port required. |
| **Claude Opus 4.7** via Anthropic Messages API (HTTP Request node) | **Teacher** role — reads URL content (extracted via jina.ai reader), produces structured JSON summary: title, 5–7 key points, 3–5 main concepts, difficulty (beginner/intermediate/advanced calibrated to senior-engineer bar), interview angle one-liner. |
| **Claude Haiku 4.5** via Anthropic Messages API (HTTP Request node) | **Examiner** role — generates 5 interview-style multiple-choice questions specific to the saved material, with structured JSON output (options A–D, correctAnswer letter, teaching explanation per question). Cheaper + faster than Opus; quality difference negligible for bounded Q generation. |
| **jina.ai reader** (`r.jina.ai/<url>`) | Content extraction. Handles paywalled / JS-rendered / SPA URLs that naive HTTP fetch can't read. Returns clean markdown with `Title:` + `Markdown Content:` blocks our Code node parses. |
| **Telegram Bot API v10.0** | Latest as of 2026-05-08. Inline keyboards for quiz answers, Markdown formatting (legacy `Markdown` parse_mode for forgiving escapes), `setMyCommands` + `setMyDescription` + `setMyShortDescription` for branded bot profile. |
| **Claude Code (Opus 4.7)** | Pre-flight planning, debugging the n8n internals, writing patches when the UI's structured-config approach hit limits. |

### Process techniques that mattered

**Self-host everything, even when "trial is enough".** Brief says "free n8n trial is enough". I read that as a *cost reassurance*, not a *mandate*. Self-hosted Docker stack is a real-ops signal in the submission narrative and removes trial usage limits.

**Two distinct AI roles, two distinct models.** Teacher = Opus (heavy reasoning, calibrated difficulty assessment). Examiner = Haiku (fast structured-output generation, single-shot). Multi-model orchestration is the wow-factor angle — most submissions will pick one model and reuse it.

**Build payload in Code nodes, not in HTTP Request expressions.** This is the single most important n8n-specific lesson from the build (see §4.1). The Anthropic `messages.content` value needs to embed the full extracted article (often 14k chars with arbitrary quotes / backslashes). Trying to inline-stringify that in a JSON Body expression hits n8n's expression-engine limitations. Pre-building the entire request body as a JS object → `JSON.stringify` → emitting a single string field → having the HTTP Request node send `={{ $json.body_json }}` is bulletproof.

**Webhook delivery validated with `curl -A "Twitterbot/1.0"` and `getWebhookInfo`.** The `secret_token` is set by n8n on workflow activation. When you replace the Telegram Trigger node, n8n generates a new token; if Telegram still has the old one, deliveries silently 403 with no entry in `last_error_message`. Always check both sides after any trigger change.

---

## 3. What worked

1. **Pre-flight infrastructure spin-up before any code.** Docker Compose stack (n8n + Postgres + ngrok in one network) up first, schema initialised via mounted `db/init/*.sql`, bot profile configured via raw Telegram API curls — all before the first workflow node. This let every later iteration assume the infra was solid; debugging stayed in n8n config space, never bled into "is my Postgres reachable?".

2. **Schema design with constraints, not just columns.** `app.learning_materials.difficulty` has a `CHECK (difficulty IN ('beginner','intermediate','advanced'))` constraint. When the Postgres node accidentally passed `"intermediate"` (with literal double-quotes from `JSON.stringify` wrapping), the constraint surfaced the bug immediately rather than silently storing junk. Constraints as documentation that fails loud.

3. **Quiz state stored in `callback_data`, not a session table.** Each answer button has `callback_data: "ans:<quizId>:Q<n>:<letter>"` — every piece of state the answer handler needs is in the payload (~30 chars, well under Telegram's 64-byte limit). No `user_state` table writes per question, no session expiry, no race conditions on parallel chat_ids. The questions JSONB lives on `app.quizzes`, looked up by quiz_id from the callback.

4. **`ON CONFLICT (chat_id, url) DO UPDATE`.** Idempotent `/learn` — re-submitting the same URL refreshes the summary instead of creating a duplicate material. Combined with the unique constraint, this means re-quizzing the same article is always on the latest Teacher output.

5. **Loading-indicator ack via parallel node.** The Teacher call takes 15–60 seconds. Without feedback the bot looks dead. Solution: the URL-valid IF node fans out to **both** `/learn: send ack (loading)` AND `/learn: jina fetch` in parallel. The ack message ("🔍 Reading the article…") arrives in ~1 second; the full summary lands 30–60s later. Two separate Telegram messages, no message edit needed.

6. **Markdown escape helper baked into every format-X Code node.** `function esc(s) { return String(s||'').replace(/([_*`\[])/g, '\\$1'); }` applied to every dynamic value before insertion into the message template. Catches all LLM-generated content (titles, key points, concepts, interview angles, question text) before Telegram's entity parser does.

---

## 4. What didn't work — and what I learned

### 4.1 n8n expression-engine doesn't reliably evaluate `JSON.stringify` inside `={{ ... }}` in JSON-body fields

The first iteration of the Teacher (Opus) HTTP Request node used inline expressions in the `jsonBody` field:

```
"content": {{ JSON.stringify("TITLE_HINT: " + $json.title + ... + $json.content) }}
```

Expectation: at runtime, n8n evaluates the expression, returns a JSON-encoded string (`"escaped\\nstuff"` with surrounding quotes), and inserts that into the JSON body. Reality: the body parsing failed with `Expected ',' or '}' after property value in JSON at position 2009`. Either the engine doesn't call `JSON.stringify`, or it does but inserts the result without preserving the JSON-string-literal quoting — I never confirmed which, because the fix doesn't care.

**The fix**: move the body building into the upstream Code node (`/learn: extract title+body`). JS context, plain `JSON.stringify` on a real object literal:

```js
const teacher_body = JSON.stringify({
  model: 'claude-opus-4-7',
  max_tokens: 2000,
  system: systemPrompt,
  messages: [{ role: 'user', content: userContent }],
});
return [{ json: { ...row, teacher_body } }];
```

HTTP Request node then has `"jsonBody": "={{ $json.teacher_body }}"` — passes the pre-built string. Same pattern for Examiner (added a new Code node `pick: build examiner body` between the Postgres load-material step and the Examiner HTTP node).

**Lesson**: never build complex JSON bodies via inline expressions in n8n HTTP Request nodes. Build them in Code nodes; the HTTP node just transports.

### 4.2 n8n's Postgres "Query Replacement" parser interpolates values as SQL literals, not via prepared statements

The first iteration of the INSERT used `$1, $2, ...$6` placeholders with a Query Replacement string:

```
={{ $json.chat_id }}, {{ JSON.stringify($json.url) }}, ..., {{ JSON.stringify($json.difficulty) }}
```

Expectation: prepared-statement parameter binding, string columns receive the value, enum check passes. Reality: the Postgres error log showed the actual SQL was:

```sql
INSERT INTO app.learning_materials (...) VALUES (
  '215303354', '"https://martinfowler.com/..."', ..., '"intermediate"'
)
```

n8n's queryReplacement did *text* substitution, not parameter binding. The `JSON.stringify` quoting became part of the literal value. Postgres's `difficulty` CHECK constraint then rejected the row because `"intermediate"` ≠ `intermediate`.

**The fix**: rewrite every INSERT/SELECT/UPDATE as direct inline expressions, no `$N` placeholders:

```sql
INSERT INTO app.learning_materials (chat_id, url, title, content, summary_json, difficulty)
VALUES (
  {{ $json.chat_id }},
  '{{ $json.url.replace(/'/g, "''") }}',
  '{{ $json.title.replace(/'/g, "''") }}',
  '{{ $json.content.replace(/'/g, "''") }}',
  '{{ JSON.stringify($json.summary_json).replace(/'/g, "''") }}'::jsonb,
  '{{ $json.difficulty }}'
)
ON CONFLICT (chat_id, url) DO UPDATE SET ...
RETURNING ...;
```

Each value is wrapped in SQL single-quotes, internal `'` is escaped to `''` (SQL standard). Each value, every escape, every cast is explicit and visible in the query. Same pattern applied to every Postgres node in the workflow.

**Lesson**: n8n's `queryReplacement` is a leaky abstraction. For non-trivial inserts (or any insert with constraint columns), bypass it.

### 4.3 n8n's Telegram node v1.2 doesn't pass raw `reply_markup` JSON through `additionalFields`

The Telegram node has structured config for inline keyboards — you select `replyMarkup = "Inline Keyboard"` from a dropdown, then n8n exposes nested `inlineKeyboard.rows[].row.buttons[].text` etc. Beautiful for a static keyboard, useless for a dynamic one where the number of buttons depends on quiz length or saved-materials count.

I tried passing `additionalFields.reply_markup = "={{ JSON.stringify($json.reply_markup) }}"` to bypass the structured UI. The node simply ignored the field — the message was sent (the Telegram API call returned 200) but without the inline keyboard. No error, no warning, just a missing button.

**The fix**: replace the four send-nodes that need dynamic inline keyboards (`/learn: send summary`, `/quiz: send topics`, `pick: send Q1`, `ans: send next Q`) with raw HTTP Request nodes pointing at `https://api.telegram.org/bot{{ $env.TELEGRAM_BOT_TOKEN }}/sendMessage`. The body is built in the upstream format-X Code node as `body_json` (same JSON.stringify pattern as Teacher / Examiner). HTTP Request sends it verbatim. Reply_markup goes through cleanly because we're hitting the API directly.

**Lesson**: when n8n's structured config can't express what you need, drop down a layer. HTTP Request to the raw API is reliable; the Telegram node is a convenience wrapper that hides what's actually being sent.

### 4.4 Workflow caching across two tables — `workflow_entity` vs `workflow_history`

When I patched node parameters by direct `UPDATE workflow_entity SET nodes = ...`, n8n still ran the **old** node code. Multiple restarts didn't help. The reason: n8n's published-workflow runtime reads from `workflow_history` rows referenced by `workflow_entity.activeVersionId` — not from `workflow_entity.nodes` directly. The "active version" is a frozen snapshot taken at publish time.

**The fix**: UPDATE both tables:

```sql
UPDATE workflow_entity SET nodes = :'newnodes'::json WHERE id = '<workflow-id>';
UPDATE workflow_history SET nodes = :'newnodes'::json
  WHERE "versionId" = '<active-version-id>';
```

Where `<active-version-id>` comes from `SELECT activeVersionId FROM workflow_entity WHERE id = '<workflow-id>'`. Restart n8n. The new nodes take effect.

**Lesson**: n8n has a publish/draft model in the DB even though the UI just shows a Published/Unpublished toggle. Don't assume the table named `workflow_entity` is what the runtime reads.

### 4.5 `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` is the default in recent n8n versions

The first /learn run failed instantly with `ExpressionError: access to env vars denied`. The Teacher node's Anthropic API key is read via `{{ $env.ANTHROPIC_API_KEY }}`. n8n's recent default blocks env-var access from expressions as a hardening measure.

**The fix**: `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` added to the n8n service in docker-compose. Container recreated.

**Lesson**: read changelogs. The 2.x line tightened env-access defaults. Either set the flag or migrate to n8n credentials for every API key.

### 4.6 The submit-day-of-brief override cost real time

Documented as a Mahoraga anti-pattern from Task 2's retro — and reproduced here. The build itself (infra + workflow design + AI prompts) was ~3h of clean work. Then 4–5h of debugging n8n quirks (the four classes above). With a day of buffer, those debugs would have been done before submit-day and the launch would have been a clean tag-push. Without buffer, the same debugs happened *on* submit-day with the clock running.

**Lesson**: the Mahoraga rule (submit-day-of-brief = anti-pattern) is correct. Overriding it costs time and bandwidth. Worth the cost only when the upside is concrete (leaderboard signal, deadline) and the operator goes in with eyes open.

---

## 5. Notable decisions

### 5.1 Quiz state in `callback_data`, not in `user_state` table

The original schema design had an `app.user_state` table to track the user's current quiz progress (which Q they're on, which quiz_id is active). I dropped that path during implementation in favour of stateless callbacks: each answer button's `callback_data` is `ans:<quizId>:Q<n>:<letter>`. The answer handler parses the callback, loads the quiz row from `app.quizzes`, looks up the question by `Q<n>` in the stored JSONB, validates.

Why: simpler. No race conditions on concurrent chat_ids. No expiry logic. Quizzes can be resumed days later (the buttons still work). Multi-user concurrency is automatic — quiz_id is per-row, no shared mutable state.

Tradeoff: the user can technically re-tap an old answer button after answering it once. We handle that with `INSERT INTO quiz_answers ... ON CONFLICT (quiz_id, question_id) DO NOTHING` — second taps are no-ops at the database level, and `editMessageReplyMarkup` could disable the buttons visually (deferred for time).

### 5.2 Senior-backend domain bias in prompts

The Teacher system prompt explicitly tells the model the audience is a senior backend engineer prepping for staff-tier interviews: ".NET, distributed systems, database internals, system design". The Examiner prompt extends this: "phrase questions like an interviewer would speak them; distractors must represent real misconceptions, not filler". Difficulty is calibrated against a senior bar — `beginner` means "below the bar for the target audience", not "easy for anyone".

Why this is the differentiator: 200 participants will ship a generic "summarize this URL" bot. The same scaffold with prompts tuned for a specific high-value use case becomes something the operator (and similar users) would actually use. Real use case > toy use case.

### 5.3 Loading-indicator as a parallel node, not a sequence prefix

The ack `🔍 Reading…` message could have been sent in-sequence: ack → jina fetch → Teacher → … → summary. That would have made each downstream node depend on Telegram's API response.

I chose parallel: the URL-valid IF node fans out to **both** the ack send AND the jina fetch on its TRUE branch. They run independently. If the ack send fails (Telegram outage, rate-limit), the main chain still finishes. Failure isolation by topology.

### 5.4 Plurals & conjunctions audit applied to the brief (Mahoraga post-Task-2 adaptation)

Brief item: "responds correctly to all three commands: `/start`, `/learn [url]`, `/quiz`" → three independent SELF-REVIEW R-items. "Teacher produces a structured summary with **five to seven key points, main concepts, and a difficulty level**" → three sub-deliverables (R5, R6, R7). "Triggered via `/quiz` **or** inline after learning" → two trigger paths (R3 plus an inline-button path).

Why: the Task 2 retro caught a near-miss where "Event **and** Host pages: social preview metadata" was read once as a single concept and shipped event-only. Splitting conjunctions into independent line items at brief-read time means none of them silently drops during build.

### 5.5 Markdown over MarkdownV2

Telegram has two Markdown parse modes — legacy `Markdown` and stricter `MarkdownV2`. V2 requires escaping of 14 characters; legacy escapes only `_ * \` [`. Our LLM-generated content (titles, key points, explanations) contains arbitrary punctuation; legacy mode forgives more.

The format-summary helper escapes the four legacy specials before insertion. V2 would have caught the apostrophe in `Lewis's` and the `&` in `Fowler & Lewis's` and several other small things — but at the cost of escaping every period and hyphen, which makes the message text harder to read at the source.

### 5.6 Repository structure: standalone repo, project in `task-3/` subfolder

Brief says "project placed in a `task-3` folder". I created a standalone repo `Warhammer2000/Task-3` (mirroring Task 1 pattern, per operator decision), with the project literally inside a `task-3/` subfolder. Both R22 (literal folder name) and the "one repo, one project" submission-link cleanliness are satisfied.

---

## 6. What's intentionally out of scope (for this submission window)

- **`/stats` as a Telegram Web App (Mini App)** — designed in the architecture doc, the schema view `v_user_stats` is ready, but the static HTML host (GitHub Pages, separate deploy) didn't fit into the submit-day window. The current `/stats` command sends a text dashboard with bar-chart emoji bars instead — same data, less wow.
- **Message reactions on summaries** — `app.material_reactions` table exists, `Telegram Trigger.updates` includes `message_reaction`, but the capture handler wasn't built. "Topics you loved" surfaces would have hooked into this.
- **Cyrillic / non-Latin URL test coverage** — extraction was verified against martinfowler.com (English); the workflow should handle other languages via jina.ai but wasn't smoke-tested on Cyrillic / Chinese / etc.
- **Mobile UI test (iPhone / Android)** — Telegram client is consistent across platforms, but the inline button widths weren't verified on a small physical screen.
- **Multi-user concurrency stress test** — 3 chat_id interleaved was sketched in the SELF-REVIEW; one-user smoke is what shipped.

These are honest deferrals, not unknowns — each has a concrete next step if/when this gets a second iteration.

---

## 7. Stack-level differentiator

The combination used: **self-hosted n8n on Docker + Postgres for persistence + ngrok named-tunnel for stable HTTPS webhook + Claude Opus 4.7 as Teacher + Claude Haiku 4.5 as Examiner** — produces a workflow that any infrastructure-aware developer can clone (`docker compose up -d` against the included `.env.example`) and have running in 5 minutes. No Lovable Cloud, no n8n trial, no proprietary glue. The deliverable is reproducible from the public repo, not from a screenshot of a running instance.

Most Task 3 submissions will be n8n cloud trials with bundled GPT tokens — fastest path to a working demo, hardest path to anything you'd actually deploy. Going self-hosted is one extra hour of setup that turns the submission into a portfolio piece.

---

## 8. Honest postscript

This submission shipped on the day of brief, against my own retrospective rule. The base reqs are covered (R1–R22 mapped in `ai-challenge-2026/task-3/SELF-REVIEW.md`), the bot is live, the workflow JSON re-imports cleanly into a fresh n8n instance. Known limitations are listed in §6 above — they're documented, not hidden.

The build process exposed four distinct classes of n8n quirk (§4.1–§4.5), each fixed at the point of discovery and documented here. Anyone hitting the same issues on a future task should find this report short to scan.

The Mahoraga loop applies after this submission too — a Task 3 retrospective will land in `ai-challenge-2026/retrospectives/task-3.md` once the leaderboard data arrives. Class of mistakes from §4 will be encoded as adaptations to `meta/n8n/footguns.md` (a new file, mirroring `meta/lovable/footguns.md`'s structure) so the next n8n task starts with a 5-entry pre-flight ledger instead of zero.
