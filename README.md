# Reel Newsletter Bot

Share Instagram reels to a Telegram bot throughout the week — get a weekly email digest Monday morning, grouped by AI / Investment / Politics / Psychology.

## How it works

1. You share a reel from Instagram → Telegram → your bot
2. Every 30 minutes, GitHub Actions polls Telegram, downloads each reel, transcribes the audio with Whisper, tags it with Claude, and commits a JSON record to this repo
3. Monday 08:00 UTC, another workflow composes a newsletter from the week's reels and sends it via Resend

Cost: ~$1/month.

## Setup

### 1. Create the Telegram bot

1. Open Telegram → DM `@BotFather`
2. `/newbot` → pick a name → save the **bot token**
3. Start a chat with your new bot and send any message
4. Get your chat ID: visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser, find your chat's `id` field (a number)

### 2. API keys

- **Anthropic** — [console.anthropic.com](https://console.anthropic.com) → API Keys
- **OpenAI** — [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (used for Whisper)
- **Resend** — [resend.com](https://resend.com) → API Keys (3k emails/mo free)

### 3. Push this repo to GitHub, then add secrets

Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From BotFather |
| `TELEGRAM_ALLOWED_CHAT_ID` | Your chat ID (integer) |
| `ANTHROPIC_API_KEY` | From Anthropic console |
| `OPENAI_API_KEY` | From OpenAI platform |
| `RESEND_API_KEY` | From Resend |
| `NEWSLETTER_TO_EMAIL` | Where to send the digest |
| `NEWSLETTER_FROM` | Optional — `Name <from@yourdomain>`. Default: `Reel Digest <newsletter@resend.dev>` |

### 4. Instagram cookies (required — Instagram blocks unauthenticated downloads)

Instagram gates most posts behind login. Without cookies, yt-dlp returns "0 items" for almost every URL. You need to export cookies from a browser where you're logged into Instagram.

**Option A — Firefox (easiest, recommended):**

1. Log into `instagram.com` in Firefox
2. Install the [cookies.txt extension](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/) (or use `yt-dlp --cookies-from-browser firefox --cookies-to-stdout`)
3. With the extension: go to instagram.com → click the extension → "Export as" → copy the Netscape-format cookies file contents

**Option B — use a throwaway account:**

Create a new Instagram account just for this bot (reduces risk to your main account), log in once, export cookies.

**Then add the cookies to GitHub Secrets:**

```bash
gh secret set INSTAGRAM_COOKIES < /path/to/cookies.txt
```

Cookies expire periodically — if ingest starts failing, re-export and update the secret.

### 5. First run

1. Actions → `ingest` → Run workflow. Should exit cleanly (no reels yet).
2. Share a reel to your Telegram bot.
3. Actions → `ingest` → Run workflow again. Should download, transcribe, tag, and commit a JSON under `data/reels/`. Bot replies to you in Telegram.
4. Actions → `newsletter` → Run workflow with `dry_run: true`. Download the `newsletter-preview` artifact and open `preview.html` to check the output.
5. Let it run naturally. Monday 08:00 UTC the weekly email lands in your inbox.

## Local development

```bash
pip install -r requirements.txt
brew install ffmpeg  # or apt-get install ffmpeg on Linux

export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_ALLOWED_CHAT_ID=...
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export RESEND_API_KEY=...
export NEWSLETTER_TO_EMAIL=...

python src/ingest.py --dry-run      # process but don't mark read / commit
python src/newsletter.py --dry-run  # writes data/sent/preview.html
```

## Layout

```
.github/workflows/
  ingest.yml       # polls Telegram every 30 min
  newsletter.yml   # composes + sends weekly digest, Mondays 08:00 UTC
src/
  ingest.py        # Telegram → download → Whisper → Claude → JSON
  newsletter.py    # JSON → Claude → Resend email
  telegram.py      # thin getUpdates/sendMessage wrapper
  claude_client.py # tagging (Sonnet 4.6) + composing (Opus 4.7 adaptive thinking)
  prompts.py       # system prompts
data/
  reels/*.json     # one file per reel
  sent/*.html      # archive of sent newsletters
  state.json       # Telegram offset cursor
```

## Known risks

- **Instagram may block yt-dlp** on GitHub Actions IPs. Mitigation: fallback to `instaloader` with a session cookie stored as a secret. Swap the `download_reel` implementation in `src/ingest.py` if this happens.
- **Non-English reels**: Whisper is multilingual but quality varies. Pass a `language` hint in `src/ingest.py` if you find the transcripts are poor.
- **Empty week**: if you save zero reels for a week, the Monday workflow logs "No reels to send" and skips the email.
