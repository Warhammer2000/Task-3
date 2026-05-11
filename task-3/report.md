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

### 4.7 `parse_mode: "Markdown"` silently drops `message_effect_id`

Adding fullscreen quiz-score effects (🔥 / ✨ / 💡 / 🥊 — Bot API 7.0) looked trivial on paper: add one field to `sendMessage`. In practice, the message was delivered without animation and without an error. The Telegram API response had no `effect_id` field even though the request included `message_effect_id`.

**The diff that proved it**: TEST messages sent via curl with `message_effect_id` and `parse_mode: "Markdown"` returned a Message object with no `effect_id`. The same body with `parse_mode: "HTML"` returned a Message object **with** `effect_id`. Telegram silently strips the effect on legacy Markdown, no error returned.

**The fix**: rewrite `ans: format results` Code node to emit HTML (`<b>`, `<i>`) instead of Markdown (`*`, `_`). Then a second issue surfaced — the existing `ans: send results` was an n8n Telegram node v1.2 that hardcodes `parse_mode: "Markdown"` and ignores unknown fields like `message_effect_id`. Replaced with an HTTP Request node that passes the full JSON body.

A third issue: long messages with `parse_mode: "HTML"` still didn't auto-play the effect — they showed only the static effect indicator at the bottom. **Solution**: split the result into two messages — a short headline (≈80 chars, carries the effect, animates reliably) + the long breakdown (no effect, carries the per-question detail) — with an n8n `Wait` node (3.5 seconds) between them so the animation completes before the breakdown shoves the headline out of view.

**Lesson**: Bot API 7.0+ features have undocumented interaction edges with legacy `parse_mode` and with the n8n Telegram node's hardcoded defaults. When using effects/reactions, go straight to HTTP Request nodes and HTML formatting. Confirmation via `curl` + response-field inspection beats reading docs.

### 4.8 HTML `<url>` placeholder in i18n strings breaks Telegram's entity parser

After full RU/EN localization (see §5.7), the score-breakdown message started throwing `Bad Request: can't parse entities: Unsupported start tag "url" at byte offset 5037`. The i18n dictionary contained user-facing strings like `Open /stats or /learn <url> for a new topic.` — natural in Markdown, fatal in HTML where `<url>` looks like an opening tag.

**The fix**: replace `<url>` with `[URL]` across all i18n strings. Safe in both Markdown and HTML modes, reads naturally in both English and Russian.

**Lesson**: when switching parse modes, audit every literal `<` / `>` in template text, not just user input.

### 4.9 Inserting a Postgres lookup node mid-chain replaces `$input` for the downstream node

To add localization, five `lang: pg load *` Postgres lookup nodes were inserted **between** existing chain steps (e.g. between `/learn: jina fetch` and `/learn: extract title+body`). Each downstream Code node that referenced `$input.first().json` was suddenly reading the lang-lookup result (`{lang: 'en'}`) instead of the original upstream data — because n8n's `$input` always points to the **immediately previous** node, not the conceptual source.

The Teacher HTTP Request failed with `The value in the "JSON Body" field is not valid JSON` because the upstream Code node returned `teacher_body: undefined` (it tried to parse jina output but got the lang row instead).

**The fix**: replace `$input.first().json` with `$('<original_upstream_name>').item.json` in every affected Code node (`/learn: extract title+body`, `pick: build examiner body`, `/learn: format summary`, `/stats: format`, `ans: format results`). Now they reach back by name, surviving any future mid-chain node insertion.

**Lesson**: `$input.first()` in n8n Code nodes is a **positional** reference. If the chain shape might change, prefer named references via `$('NodeName').item.json` — they're rewire-resilient.

### 4.10 n8n's webhook re-registration is workflow-toggle-driven, not container-restart-driven

When the bot's `setWebhook` was overwritten manually (via curl) to add `inline_query` to `allowed_updates`, the call also overwrote n8n's `secret_token`. Now every Telegram delivery returned `403 Forbidden — Provided secret is not valid`. Restarting the n8n container didn't help — n8n on startup loads the existing webhook state from DB but does **not** re-call Telegram's `setWebhook`.

**The fix**: deactivate the workflow (`n8n update:workflow --id=X --active=false` + container restart) and reactivate (`--active=true` + container restart). On reactivation, n8n's Telegram Trigger node makes a fresh `setWebhook` call with its own `secret_token` and the current `allowed_updates` list from the node config.

**Lesson**: never manually `setWebhook` against a Telegram-Trigger-managed bot. Change `updates` in the trigger node config + toggle workflow off/on. Or use Telegram's `getWebhookInfo` to inspect, never to mutate.

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

### 5.7 Localization architecture: lookup-per-branch, dict-in-Code-node

Localization wasn't in the brief but the operator (Russian speaker) shipped to a Russian-speaking audience. Three architectural choices:

1. **Storage in `app.user_state.lang`** (TEXT, CHECK `IN ('en','ru')`, default `'en'`). Persists across sessions; survives container restarts. Default `'en'` so first-time users get a known starting point.
2. **Lookup-per-branch via `lang: pg load *` Postgres nodes**, not a global lookup. Five lookup nodes (`/learn`, `/stats`, `/quiz`, `pick`, `ans`) each inject `lang` into their downstream branch. Cheaper than a global pre-Route lookup (no DB call on every update), and survives the Route Switch's input-shape constraints.
3. **String dictionary inlined in each Code node** (instead of a shared lib). n8n Code nodes are independent JS sandboxes — no shared imports. The dict is defined as `const T = { en: {...}, ru: {...} }` at the top of each format-X node. Copy-paste cost paid once during the patch; runtime perf is zero overhead.

LLM-generated content (Teacher summary, Examiner questions/options/explanations) is localized via a **language directive appended to the system prompt**:

```js
let systemPrompt = "...the full English system prompt...";
systemPrompt += lang === 'ru'
  ? '\n\nAll output strings ... must be in Russian. Difficulty value stays English.'
  : '';
```

Difficulty enum stays English (`beginner` / `intermediate` / `advanced`) — it's a DB constraint value, not user-facing text. Quiz option letters stay A/B/C/D — they're keys, not labels.

**Why a `/lang` command + inline-keyboard picker** instead of auto-detect from Telegram's `from.language_code`: auto-detect would be wrong for the Russian operator who reads English content but prefers Russian UI, and vice versa. Explicit user choice → durable preference. The `/learn` ack message still uses `from.language_code` as a one-shot fallback because lang isn't loaded until later in the chain.

### 5.8 Timing-warning ack messages

After full localization shipped, the `/learn` ack still said "30–60 seconds" — under-promising for content-heavy URLs where Teacher takes 1–3 min. The quiz-pick callback had no ack at all, so users sat staring at a frozen UI for 30–120 seconds while the Examiner generated 5 questions.

Two new Code nodes (`/learn: build ack text`, `pick: build ack text`) emit localized "1–3 minutes, grab a coffee ☕" messages, wired in parallel with the LLM-call chain. Users now see explicit timing + reassurance.

**Lesson**: every async LLM call ≥ 5 seconds needs a visible-progress ack. Under-promising on timing is worse than over-promising — users abandon a "30-second wait" sooner than they abandon a "1–3 min, grab a coffee" wait.

### 5.9 Quiz pool: pre-generation + self-replenishing buffer

By far the largest UX upgrade. Original design: every `/quiz` callback triggered a synchronous Examiner LLM call (Haiku 4.5, 30-60s). The user tapped "Take quiz" and stared at a "generating..." ack for half a minute before Q1 arrived. Compounded by user feedback that Haiku quality was sometimes spotty for senior-grade question framing.

**Architecture**: a new table `app.quiz_pool` holds pre-generated quizzes, keyed by `(material_id, lang)`. Each entry is a complete 5-question set ready to ship instantly. A dedicated webhook `/webhook/pool-refill` (separate trigger chain in the same n8n workflow) maintains a target depth of **3 entries per material+lang** via a self-firing refill loop:

1. Webhook receives `{material_id, lang}`.
2. Responds **200 immediately** to the caller (fire-and-forget pattern).
3. Counts current pool entries.
4. If `< 3`: loads material content + ALL prior question stems → builds Examiner prompt with strong uniqueness directive + `temperature: 0.9` → calls Sonnet 4.5 → similarity-check the result → INSERTs into pool → fires itself again.
5. If `>= 3`: chain ends (no recursion).

This is **eventually-consistent self-organising state** — no scheduler, no cron, no external queue. Pool depth equilibrates around 3 entries via the natural feedback loop: every `/quiz` claim depletes the pool by 1, and the post-claim refill trigger pushes it back to 3.

**Pick callback fork**: the existing slow-path Examiner call is now a fallback. The pick callback first attempts an atomic pool claim:

```sql
DELETE FROM app.quiz_pool
WHERE id = (
  SELECT id FROM app.quiz_pool
  WHERE material_id = ? AND lang = ?
  ORDER BY generated_at ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED
)
RETURNING id, material_id, lang, questions;
```

- **`FOR UPDATE SKIP LOCKED`** — two users on the same material concurrently `/quiz` get different pool entries; neither blocks the other.
- **`DELETE...RETURNING`** — atomic claim. The pool entry vanishes from the pool the instant it's claimed; no "claimed but not yet started" intermediate state to garbage-collect.

If the claim returns a row, Q1 is sent within ~500ms of the callback. If the claim returns empty (pool empty for this material+lang), the existing slow-path runs (ack message + Examiner LLM call, 30-60s). Either way the user gets the quiz; only the latency differs.

**Strategy in plain terms**: *first user pays the wait, every user after gets instant quizzes*. The first `/learn` of a topic triggers an initial pool refill that runs in the background while the user reads the summary. By the time they tap "Take quiz now", 1-3 pool entries are usually ready. From quiz #2 onward, the bot is effectively instant.

**Model upgrade in the same patch**: Examiner moves from Haiku 4.5 to Sonnet 4.5. Question quality jump is significant for senior-grade framing; the speed cost (10-15s vs 5-10s per generation) is paid in background, not on the user's wait clock.

**Uniqueness guarantees**: three layers stacked.

1. **Temperature `0.9`** during pool generation (vs the default 0 for structured output) — gives the LLM enough freedom to vary phrasing/concepts across pool entries.
2. **Strong prompt directive**: every pool generation receives ALL prior question stems for this `(material, lang)` combo (`jsonb_array_elements` unpacks every question from every existing pool entry), with an explicit 5-rule "MUST satisfy" list and a self-check step. The "at most 1 overlap" escape hatch exists for genuinely small/exhausted materials — better than the LLM stalling.
3. **Post-parse similarity check** (`pool: similarity check` Code node): computes Jaccard-bigram similarity for each new question vs every prior. If anything exceeds 0.55 it's logged to `docker logs task3-n8n` for ops visibility. Hard rejection would risk infinite-loop regeneration when a material genuinely is exhausted; logging is the right tradeoff.

Verified on the Microservices Fowler/Lewis article: the first 3 pool entries cover monolith vs microservices decision risk, cross-service data boundary violation, and shared-library coupling — three distinct angles with no paraphrasing.

**Concurrency model**:

- Pool is **shared per (material, lang)**, not per user. Material X has ONE pool, not one-per-user. Two users sharing material X share the same pool. Cheaper to maintain, and `SKIP LOCKED` guarantees they don't claim the same entry.
- Each `/quiz` claim fires a top-up refill webhook. Refill is single-quiz-per-call and self-propagating until depth hits 3. Multiple users doing `/quiz` in parallel produces multiple parallel refill chains — Anthropic rate-limit (Tier 1: 50 RPM Sonnet) is the real ceiling.
- `app.user_state.chat_id` is per-user (PRIMARY KEY); pool isn't bound to chat_id at all. When a pool entry is claimed, it gets copied into `app.quizzes` with the claiming user's chat_id, and removed from the pool — user-bound tracking starts only AFTER claim.

**The `tools/warmup-pool.sh` companion script**: for materials added before the pool feature shipped (or after a database restore), this script fires refill triggers for every `(material_id, lang)` combo with `< 3` pool entries. Idempotent — safe to re-run. Documented in `tools/README.md`.

**What this gets you in numbers**:

- Cold quiz (pool empty, slow-path): 30-60s wait, same as before.
- Warm quiz (pool ≥ 1): <500ms from "tap quiz" to "Q1 arrives". A 60× speedup for the steady-state user.
- Pool refill cadence: ~40s per entry, ~2 minutes from empty to full depth-3 pool.
- Anthropic cost: same as before per quiz; we just pay the cost up-front during background time instead of on-demand during user-perceived time.

---

## 6. What's intentionally out of scope (for this submission window)

- **Cyrillic / non-Latin URL test coverage** — extraction was verified against martinfowler.com (English) and metanit.com (Russian). The workflow handles both via jina.ai. Chinese / Arabic / Hindi URLs weren't smoke-tested.
- **Mini App localization** — the Mini App HTML labels (`Materials`, `Quizzes`, `Avg score`, etc.) stayed English even when bot UX is set to Russian. Adding a `?lang=ru` query param to the dashboard URL and threading it through `miniapp: render HTML` would close this — deferred for time.
- **Inline mode localization** — `@bot search` results' description text (`No materials match`, `intermediate`, etc.) is English-only. Same fix shape as Mini App.
- **Multi-user concurrency stress test** — 3 chat_id interleaved was sketched in the SELF-REVIEW; one-user smoke is what shipped.
- **Telegram Desktop message-effects** — fullscreen animations auto-play reliably on mobile clients but Telegram Desktop 6.8.1 shows only the static effect indicator for the headline message. Confirmed via diff testing — short test messages did animate on desktop, but long format-results headlines don't. Likely a Desktop-specific throttling after consecutive poll interactions. Out of scope to fix client-side; documented for the demo (which shows mobile primarily).
- **`/lang` confirmation effect** — the lang-set confirmation could ship with its own ✨ effect for delight. Skipped because the lang change is itself the signal.

These are honest deferrals, not unknowns — each has a concrete next step if/when this gets a second iteration.

---

## 7. Stack-level differentiator

The combination used: **self-hosted n8n on Docker + Postgres for persistence + ngrok named-tunnel for stable HTTPS webhook + Claude Opus 4.7 as Teacher + Claude Haiku 4.5 as Examiner** — produces a workflow that any infrastructure-aware developer can clone (`docker compose up -d` against the included `.env.example`) and have running in 5 minutes. No Lovable Cloud, no n8n trial, no proprietary glue. The deliverable is reproducible from the public repo, not from a screenshot of a running instance.

Most Task 3 submissions will be n8n cloud trials with bundled GPT tokens — fastest path to a working demo, hardest path to anything you'd actually deploy. Going self-hosted is one extra hour of setup that turns the submission into a portfolio piece.

### Bot-API-v10 features that other submissions won't ship

Beyond the brief's required behaviour, this bot uses six Bot API 7.0+ features that most participants will not touch:

1. **`setMessageReaction`** (Bot API 7.0, Mar 2024) — bot reacts 🤔 on `/learn` receipt and 🎓 on summary delivery. The bot "breathes".
2. **`message_effect_id`** (Bot API 7.0) — fullscreen animation tier on quiz score: 🔥 (80%+), ✨ (60–79%), 💡 (40–59%), 🥊 (<40%).
3. **Telegram Mini App** via `web_app` button — `/stats` opens an embedded HTML dashboard with Chart.js (doughnut + gradient-fill line), 28-day GitHub-style activity heatmap, 7 unlock-style achievement badges, count-up animations, glassmorphism cards, Telegram theme integration, MainButton + HapticFeedback wired.
4. **Inline mode** — `@seniorprepcoach_bot <query>` from any chat searches the user's library by title. Results carry a Start-quiz callback button.
5. **`sendPoll` quiz mode** — instead of inline-keyboard answer buttons, quizzes use Telegram's native poll UI (`type: 'quiz'`, single correct option, instant feedback animation).
6. **Full RU/EN localization** — Teacher + Examiner prompts get language directive; all UX strings localized via dict; `/lang` command flips preference.

Each of those took 10–60 minutes to implement and 0–2 hours to debug (see §4.7–§4.10). Total marginal cost on top of the base brief: ~5 hours. Total marginal score impact (peer-relative): substantial — none of these features are required, and few will be voluntarily implemented.

### Engineering-process differentiator: 16 versioned patch scripts

n8n's editor UI gets slow after ~40 nodes (this workflow ended at 77). Re-importing JSON via the UI clobbers credentials. So the iteration loop was: dump current `nodes` + `connections` from Postgres → run a Python patch script → write back → `docker restart task3-n8n`. Total cycle: ~15 seconds vs ~2 min via UI.

The full set of 16 patches lives in [`tools/patches/`](./tools/patches/) with a [`tools/README.md`](./tools/README.md) that explains each patch's purpose, the bug it fixed, and the order of application. Anyone cloning this repo can rebuild the workflow from a base or learn from the documented failure modes.

---

## 8. Honest postscript

This submission shipped on the day of brief, against my own retrospective rule. The base reqs are covered (R1–R22 mapped in `ai-challenge-2026/task-3/SELF-REVIEW.md`), the bot is live, the workflow JSON re-imports cleanly into a fresh n8n instance. Known limitations are listed in §6 above — they're documented, not hidden.

The build process exposed **ten** distinct classes of n8n / Bot API quirk (§4.1–§4.10), each fixed at the point of discovery and documented here. Anyone hitting the same issues on a future task should find this report short to scan.

The Mahoraga loop applies after this submission too — a Task 3 retrospective will land in `ai-challenge-2026/retrospectives/task-3.md` once the leaderboard data arrives. Classes of mistakes from §4 will be encoded as adaptations to `meta/n8n/footguns.md` (a new file, mirroring `meta/lovable/footguns.md`'s structure) so the next n8n task starts with a 10-entry pre-flight ledger instead of zero.
