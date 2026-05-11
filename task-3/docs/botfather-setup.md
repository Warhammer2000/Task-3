# BotFather setup — one-time, ~5 minutes

> Required before `docker compose up`. Without a bot token nothing else works.

## Steps

1. **Open Telegram → search `@BotFather` → start the chat.**

2. **Create the bot.** Send `/newbot`. BotFather will prompt:
   - **"Alright, a new bot. How are we going to call it?"** — public display name. Suggested: `Senior Interview Coach`
   - **"Good. Now let's choose a username for your bot."** — must end in `bot`. Suggested: `seniorprepcoach_bot` (try a couple of variations if taken)
   - BotFather replies with an HTTP API token: `1234567890:AAH...` — **save it as `TELEGRAM_BOT_TOKEN` in `.env`**

3. **Set the description** (visible on bot profile page, before user starts):
   ```
   /setdescription
   ```
   When prompted, paste:
   ```
   AI-powered learning coach for senior backend interview prep. Send /learn <url> → get a structured summary at senior bar; send /quiz → take a 5-question interview-style quiz on what you've learned. Built on n8n + Claude (Opus 4.7 Teacher, Haiku 4.5 Examiner) for Vention AI Challenge 2.0.
   ```

4. **Set the "about" text** (visible on the bot's user card):
   ```
   /setabouttext
   ```
   Paste:
   ```
   Senior backend interview prep — summarize a URL, then quiz yourself.
   ```

5. **Set the command menu** (so the user sees `/start /learn /quiz /stats` in Telegram's UI):
   ```
   /setcommands
   ```
   When prompted, paste this exact block:
   ```
   start - Welcome and show what I can do
   learn - Submit a URL to study (usage: /learn https://...)
   quiz - Start a quiz from your saved materials
   stats - Open your learning dashboard
   ```

6. **(Optional) Set the bot's profile picture** for polish:
   ```
   /setuserpic
   ```
   Send a 512×512 PNG.

## Verify

After the setup, from any Telegram chat tap your bot's username → you should see:
- The about-text on the user card
- A "Start" button (which sends `/start` on tap)
- After tapping "Start", the command menu (🍔 icon left of input) shows 4 commands

The bot will not respond until the n8n workflow is activated. That happens in `task-3/README.md` § 4-5.

---

## Notes

- **`setMyCommands` programmatic call**: the n8n workflow also calls `setMyCommands` on first activation as a defensive layer — if BotFather is skipped (or someone deletes the commands), the workflow re-establishes them. Both layers exist so the bot menu is always present.
- **Bot API version**: BotFather always uses the latest Bot API (currently v10.0, May 2026). All features in our workflow (MarkdownV2 spoiler entities, Web App buttons, message reactions) are supported on the default version.
- **Token security**: never paste the token into a public chat / repo / screenshot. If leaked, `/revoke` in @BotFather creates a new one and the old dies immediately.
