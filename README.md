# Reel Newsletter Bot

> Two companion docs: [MASTER.md](MASTER.md) for architecture + operations, [ZEEWEEKLY.md](ZEEWEEKLY.md) for the editorial spec (voice, categories, issue cut, design). This README is the setup guide.

Share Instagram and Facebook posts to a Telegram bot throughout the week — get:

1. **Weekly email digest** every Friday via Resend, grouped by AI / Investment / Politics / Psychology / Food / Other
2. **Searchable public archive** at `https://zee-go.github.io/reelnewsletter/` — full-text search via Pagefind, browse by tag or week
3. **Google Sheet** with one row per post — easy to filter, export, sort
4. **In-repo backup** — `data/reels/*.json`, `data/records.csv`, `data/INDEX.md` regenerated on every ingest

**Supported URLs:**
- Instagram reels (`/reel/`), posts (`/p/`, photos or videos), carousels, IGTV (`/tv/`)
- Facebook reels, videos (`/watch`, `/video`), `fb.watch` links, photo posts

Videos are transcribed via Whisper. Photo posts and carousels are understood via Claude Vision (reads text overlays and describes image content). Recipes (tag=food) have structured ingredients + instructions extracted into the digest.

## How it works

1. You share a reel from Instagram → Telegram → your bot
2. Every 30 minutes, GitHub Actions polls Telegram, downloads each reel, transcribes the audio with Whisper, tags it with Claude, and commits a JSON record to this repo
3. Friday 08:00 UTC, another workflow composes a newsletter from the week's reels and sends it via Resend

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

### 3a. Google Sheet backup (optional but recommended)

The bot auto-appends one row per saved reel to a Google Sheet. Requires a service account (free, ~3 min).

1. Create a new Google Sheet, name it "Reel Archive". Copy the sheet ID from its URL (the long string between `/d/` and `/edit`).
2. In [Google Cloud Console](https://console.cloud.google.com/iam-admin/serviceaccounts), create a new project (or reuse one), then:
   - Enable the **Google Sheets API** (APIs & Services → Library → search → Enable)
   - IAM & Admin → Service Accounts → **Create Service Account** → give any name → Done
   - Click the new account → **Keys** → Add Key → Create → JSON → download the file
3. Open the Google Sheet → Share → paste the service account email (looks like `xxx@yyy.iam.gserviceaccount.com`) → Editor → Share.
4. Add two secrets:
   - `GSHEET_ID` — the sheet ID
   - `GSHEET_SERVICE_ACCOUNT_JSON` — the entire contents of the JSON key file (paste as-is)

If you skip this, ingest just logs "GSHEET_ID not set — skipping" and continues. Sheet export is non-blocking.

### 3b. Public archive website (optional but recommended)

The archive site is built by `.github/workflows/site.yml` and deployed to GitHub Pages.

1. **Make the repo public**: `gh repo edit zee-go/reelnewsletter --visibility public --accept-visibility-change-consequences` (GitHub Pages free tier requires public repos).
2. **Enable Pages**: repo → Settings → Pages → Source: **GitHub Actions**.
3. First deploy triggers on the next push to `data/**` or `site/**`, or via manual dispatch.
4. Site URL: `https://zee-go.github.io/reelnewsletter/`.

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
| `NEWSLETTER_FROM` | Optional — `Name <from@yourdomain>`. Default: `Reel Digest <onboarding@resend.dev>` |
| `GSHEET_ID` | Optional — Google Sheet ID for the backup |
| `GSHEET_SERVICE_ACCOUNT_JSON` | Optional — service account JSON for writing to the Sheet |

### 4. Instagram + Facebook cookies (required — Meta blocks unauthenticated downloads)

Instagram and Facebook gate most posts behind login. Without cookies, yt-dlp returns "0 items" for almost every URL. You need to export cookies from a browser where you're logged into **both** services — the same `INSTAGRAM_COOKIES` secret holds both (Netscape cookies format supports multiple domains in one file).

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
5. Let it run naturally. Friday 08:00 UTC the weekly email lands in your inbox.

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
  newsletter.yml   # composes + sends weekly digest, Fridays 08:00 UTC
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
- **Empty week**: if you save zero reels for a week, the Friday workflow logs "No reels to send" and skips the email.
