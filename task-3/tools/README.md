# tools/

Build & patch tooling for the n8n workflow that backs the bot. The final, importable workflow is `../workflow.json` — these scripts document how it was assembled iteratively.

## Why patches and not raw workflow edits

n8n's editor UI gets slow once a workflow exceeds ~40 nodes (this one ended at 62). Re-importing JSON via the UI also clobbers credentials. So the iteration loop was:

1. Dump current `nodes` + `connections` JSON from `workflow_entity` / `workflow_history` (Postgres).
2. Run a Python patch script that mutates the dump in memory (add nodes, rewire connections, swap node types, replace `jsCode` / `query` / `jsonBody`).
3. Write the result back to both tables.
4. `docker restart task3-n8n` to pick up changes.

This kept iteration time at ~15 seconds end-to-end vs. ~2 minutes per re-import via UI.

## Order of application (chronological)

| # | Script | What it did | Why it was needed |
|---|--------|-------------|-------------------|
| 01 | `01-megabuild-utf8.py` | Initial 30+ node build with UTF-8 safe encoding pipeline | Windows Python defaults to cp1251 — emoji and Cyrillic in JS code nodes were getting double-encoded mojibake (`рџ”»`). Solution: explicit `encoding='utf-8'` on file open, `PYTHONIOENCODING=utf-8` for stdout, run patch entirely in Linux container via `docker exec` to avoid Windows codec layer. |
| 02 | `02-quiz-sql-inline.py` | Rewrote all SQL queries to use inline `{{ ... }}` expressions instead of `queryReplacement` | n8n Postgres node `queryReplacement` does *text* substitution, not parameter binding. With `JSON.stringify` wrapping, literal quotes ended up as part of values, blowing up CHECK constraints (`'intermediate'` instead of `intermediate`). |
| 03 | `03-quiz-chain-rewire.py` | Injected `pick: build examiner body` Code node between `pg load material` and `Examiner (Haiku)` | HTTP Request `jsonBody` parser choked at byte 2009 on the inline `{{ ... }}` JSON. Building the body string in JS upstream avoided n8n's expression interpolation entirely. |
| 04 | `04-sendpoll-quiz-mode.py` | Added 10 nodes implementing Telegram `sendPoll` quiz mode (vs. inline-keyboard buttons) | Telegram's native quiz UI is more polished; gives instant correctness feedback, native explanations, doesn't bloat chat with N callback messages. |
| 05 | `05-finalize-dual-source.py` | `ans: pg finalize quiz` & `ans: pg load all answers` SQL changed to read `quiz_id` from `poll_ans: validate` OR `ans: validate` via `.isExecuted` ternary | Two converging paths into finalize (inline-kb vs poll). The path-not-taken node hadn't executed, so its reference threw `ExpressionError: Node 'X' hasn't been executed`. |
| 06 | `06-format-dual-source.py` | Same dual-source pattern in `ans: format results` jsCode | Code node was reading `$('ans: validate').item.json.chat_id` — broke for poll-answer path. |
| 07 | `07-wow-features.py` | Added 10 nodes: `setMessageReaction` calls (🤔 / 🎓 on `/learn`), Mini App webhook → Postgres → HTML dashboard, `inline_query` handler, `web_app` button on `/stats`, `message_effect_id` on score reply | Differentiator features. Bot API 7.0 features (reactions, effects) added Mar 2024 — few entries will use them. Mini App via `web_app` inline button + n8n Webhook+RespondToWebhook nodes serving HTML; Chart.js for charts. |
| 08 | `08-miniapp-v2-redesign.py` | Mini App HTML v2: glassmorphism, animated gradient hero, count-up KPIs, achievement strip (7 badges), 28-day activity heatmap, score-trend chart with gradient fill, library w/ best-score bars, Telegram WebApp theme & MainButton integration | First Mini App was functional but generic. Rebuilt with care for sub-second load + native-feeling animations. |
| 09 | `09-effect-html-mode.py` | Convert `ans: format results` text from Markdown to HTML formatting | **Bug discovered via diff testing**: `parse_mode: "Markdown"` (legacy) **silently drops** `message_effect_id` — Telegram delivers the message without the effect and without an error. `parse_mode: "HTML"` echoes `effect_id` back in the response and the animation plays. Reproduced with curl. |
| 10 | `10-ans-send-http-request.py` | Replace n8n Telegram node v1.2 (`ans: send results`) with HTTP Request | The Telegram node hardcodes `parse_mode: Markdown` and discards unknown fields like `message_effect_id`. Also threw `Bad Request: message is too long` once HTML angle-brackets entered the text (suspect double-encoding). HTTP Request gives full control of the JSON body. |
| 11 | `11-split-result-msg.py` | Split final score into TWO messages: short headline with effect + long breakdown without | Telegram message effects only animate reliably on **short** messages (likely a client heuristic — long messages get static effect indicator only). Headline ≈ 80 chars carries the effect, breakdown carries the 5-question detail. |
| 12 | `12-wait-for-effect-anim.py` | Inserted n8n `Wait` node (3.5 sec) between headline and breakdown | Without the gap the breakdown shoves in instantly and pushes the headline out of view *before the animation finishes*. 3.5s lets the fullscreen effect complete. |

## How to re-apply on a fresh n8n

The fastest path is to import `../workflow.json` via the n8n editor UI (Settings → Import from File). All patches are already baked in.

The patch scripts here are kept for **traceability** — they document each design decision and the bug that motivated it. If you ever need to rebuild from a different base, the scripts demonstrate the pattern: dump → mutate JSON → write back → restart.

## Encoding caveat (Windows)

Every script in this folder reads/writes with `encoding='utf-8'` explicitly. Don't run them via `python script.py | python other.py` without `PYTHONIOENCODING=utf-8` set — Windows defaults stdin/stdout to cp1251, which destroys emoji and Cyrillic.
