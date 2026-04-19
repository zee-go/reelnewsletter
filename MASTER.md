# MASTER — architecture & operations

This is the baseline process doc. If you're setting up the app for the first time, read [README.md](README.md) first. If you've inherited or forked this repo and want to understand how it *works*, start here.

---

## 1. What this is (30-second pitch)

A Telegram bot ingests Instagram and Facebook posts you forward to it. Every 30 minutes a GitHub Actions cron job polls Telegram, downloads each post with yt-dlp, transcribes any audio with Whisper, hands image-only posts to Claude Vision, tags the result with Claude Sonnet into one of eight categories (AI, Marketing, Investment, Politics, Psychology, Fitness, Food, Other), and commits a JSON record to `data/reels/`. Food posts also get a structured recipe extracted. Friday 08:00 UTC, a second workflow loads the week's records, caps them at 10 by priority (AI + Marketing first), asks Claude Opus to compose an HTML digest, and sends it via Resend. The hero headline for each week is synthesized by Claude Haiku from the week's post set and cached in `data/themes.json`. A static archive site rebuilds on every data push and is served at [zeeweekly.com](https://zeeweekly.com/) via GitHub Pages + Cloudflare DNS, with Pagefind providing client-side full-text search. Total ops cost: about $1/month.

---

## 2. Why it's built this way

- **GitHub Actions cron instead of a hosted worker** — $0 ops, no server to babysit, deployment is `git push`. Fine for one user; breaks past ~1 user.
- **Static site instead of SSR** — content is append-only, Pagefind handles search client-side, no database or runtime needed.
- **JSON files in the repo as source of truth** — git history is the audit log, no migrations, trivial to back up, diffable.
- **Telegram instead of a custom app** — reuses an app the user already has open. Zero onboarding.
- **Claude Sonnet for tagging, Claude Opus for composition** — tagging is high-volume and cheap; composition runs once a week and benefits from the better prose model plus adaptive thinking.
- **Resend's `onboarding@resend.dev` sender on the free tier** — 3k emails/mo free. A verified custom-domain sender is only needed if you outgrow the free tier.
- **Cloudflare DNS with CNAME flattening at the apex** — one record maps `zeeweekly.com` → `zee-go.github.io`, no need to hardcode GitHub Pages' A/AAAA IPs.

---

## 3. The pipeline (end-to-end trace)

1. You forward a reel link in Telegram to your bot.
2. `ingest.yml` cron fires every 30 min and calls `getUpdates` with an offset cursor stored in `data/state.json`.
3. `src/ingest.py` extracts the URL via regex — Instagram `/reel/`, `/p/`, `/tv/`; Facebook `/reel/`, `/watch`, `fb.watch/`, `/share/[rvp]/`.
4. `yt-dlp --cookies $INSTAGRAM_COOKIES` downloads video + audio. Photo posts use `--write-all-thumbnails --skip-download` instead.
5. For photo-only posts that don't yield thumbnails, fall back to `info.json`'s `display_url` fetched with a spoofed User-Agent and Referer.
6. Video path: `ffmpeg` extracts audio → Whisper transcribes.
7. Photo path: images are passed directly to Claude Vision.
8. Claude Sonnet `messages.parse()` tags the post into `{ai, investment, politics, psychology, food, other}`. Food posts also populate a structured `Recipe` (ingredients, instructions, prep_time, servings) when the caption/transcript supports it.
9. Record saved to `data/reels/<shortcode>.json`. `data/records.csv` and `data/INDEX.md` are regenerated; optional Google Sheet row is appended.
10. Telegram ack message is sent back to you.
11. The commit is pushed → `site.yml` fires → Jinja2 templates render to `site/_dist/` → Pagefind indexes → GitHub Pages deploys.
12. Friday 08:00 UTC, `newsletter.yml` loads the week's records → Claude Opus composes an HTML email → Resend sends it to `NEWSLETTER_TO_EMAIL`.

---

## 4. File map

| File | What it owns |
|---|---|
| `src/ingest.py` | Telegram polling, URL extraction (`shortcode()`), yt-dlp orchestration, pipeline runner |
| `src/claude_client.py` | `ReelTag` + `Recipe` pydantic models, `tag_reel()` (optional images), `compose_newsletter()` with adaptive thinking, `compose_week_theme()` on Haiku for the hero headline |
| `src/issue.py` | Issue assembly rules — `ISSUE_LIMIT` (10), `PRIORITY_TIERS`, and `cut_for_issue()` used by both the site builder and the newsletter composer |
| `src/prompts.py` | `TAG_SYSTEM_PROMPT` (categories + recipe extraction rules), `NEWSLETTER_SYSTEM_PROMPT` (voice + structure) |
| `src/newsletter.py` | `EMAIL_CSS`, Resend `send_email()` with `or` fallback pattern |
| `src/build_site.py` | Loads all JSON, groups by week/tag, per-week issue numbering, renders Jinja2 → `site/_dist/` |
| `src/csv_export.py`, `src/sheets_export.py` | Flat backups — CSV in repo, optional Google Sheet |
| `src/retag.py` | One-off script to re-run tagging against existing records when the taxonomy changes |
| `src/telegram.py` | Thin `getUpdates` / `sendMessage` wrapper |
| `.github/workflows/ingest.yml` | Cron `*/30 * * * *` |
| `.github/workflows/newsletter.yml` | Cron `0 8 * * 5` (Friday 08:00 UTC) |
| `.github/workflows/site.yml` | Triggers on push to `data/**` or `site/**` |
| `site/templates/` | `base.html`, `home.html`, `tag.html`, `week.html`, `reel.html`, `archive.html`, `search.html`, `_post.html` partial |
| `site/static/styles.css` | Sorbet palette, Fraunces / Source Serif 4 / JetBrains Mono, per-category color vars |
| `site/static/CNAME` | Single line `zeeweekly.com` — GitHub Pages reads this to bind the custom domain |

---

## 5. Category + taxonomy (the tagging contract)

| Tag | Color | Blurb |
|---|---|---|
| ai | pink `#ff6fa5` | What shipped, what broke, what's actually worth the hype. |
| marketing | cornflower `#6aa7f5` | Hooks, pitches, and the quiet psychological heists behind a good campaign. |
| investment | mint `#5fcfbc` | Markets, macro, and the ancient art of not setting money on fire. |
| politics | butter `#f5b84a` | Policy, power, and the chessboard nobody asked for. |
| psychology | lavender `#c78fd9` | Small experiments on the mushy machine between your ears. |
| fitness | matcha `#7dc87a` | Strength, sleep, recovery — the boring stuff that actually works. |
| food | coral `#ff9b7a` | Recipes worth stealing and meals worth remembering. |
| other | grey `#a89f8f` | The stragglers, the oddballs, the couldn't-not-save-this pile. |

**Rules of the contract:**

- "Other" is a legitimate bucket. Don't force-fit a post into a named category just because one exists.
- A `food` tag MUST populate `Recipe` when the caption or transcript contains ingredients or instructions. If neither is present (e.g. a food review or restaurant clip), tag `food` without a `Recipe`.
- **Issues are capped at 10 posts**, drawn in priority order: AI + Marketing first, then Investment + Politics, then Psychology/Fitness/Food/Other. Overflow is archive-only. Rules live in `src/issue.py`.
- To add or remove a category, touch all of: `src/prompts.py`, `src/claude_client.py` (the `Tag` literal), `src/build_site.py` (`TAG_ORDER`, `TAG_LABELS`, `TAG_BLURBS`), `src/issue.py` (`PRIORITY_TIERS`), `site/static/styles.css` (the `--cat-X` variables and every `.cat-X` rule), then run `python src/retag.py` to re-tag history.

---

## 6. Known pitfalls + fixes

Don't re-learn these the hard way:

- **"0 items" from yt-dlp on Instagram/Facebook.** Meta blocks anonymous downloads. Export cookies from Firefox or Chrome via the `cookies.txt` extension and store them as the `INSTAGRAM_COOKIES` secret. Safari cookies are sandboxed and blocked without Full Disk Access — don't bother.
- **Cookies file exceeds the 48 KB GitHub Secret limit.** Filter the Netscape cookies file down to just `instagram.com` and `facebook.com` lines with `awk` before uploading.
- **yt-dlp "No video formats found" on photo posts.** Add `--ignore-no-formats-error`, retry with `--write-all-thumbnails --skip-download`, and fall back to the `display_url` from `info.json` using a spoofed User-Agent + Referer.
- **Resend rejects the sender with "domain is invalid."** The free tier only allows `onboarding@resend.dev`. Also: `os.environ.get("NEWSLETTER_FROM") or "default"` — do not use the `.get(key, default)` form, because an empty-string env var defeats it.
- **Facebook share URL extracted as shortcode "unknown".** The `/share/r/...` pattern needs its own regex: `facebook\.com/share/[rvp]/([A-Za-z0-9_-]+)` → `fbs{id}`.
- **A recipe gets tagged "psychology".** You're still on the old 4-category schema. Add `food` + `other` with the structured `Recipe` model.
- **Google Workspace org policy blocks service account key creation.** Sheets export is optional and non-blocking — the CSV in the repo plus `data/INDEX.md` is the real backup. If Sheets can't work, skip it.
- **HTTPS cert not ready immediately after the DNS flip.** GitHub's Let's Encrypt provisioning runs 15–30 minutes after the DNS check succeeds. Don't try to `PUT .../pages -F https_enforced=true` until the cert exists, or you'll get a 404.
- **Prompt cache invalidation.** Any byte change anywhere in the cached prefix kills the cache. Keep timestamps, per-request IDs, and per-post content *after* the last `cache_control` breakpoint — never before it.

---

## 7. Operational cadence

- **Daily-ish:** forward reels to the bot. That's it.
- **Weekly:** Friday morning, the digest lands in your inbox. Skim, maybe forward.
- **Monthly:** check that `ingest` hasn't been silently failing — GitHub Actions → recent runs should be green. If Instagram cookies expired, re-export and update the `INSTAGRAM_COOKIES` secret.
- **When you edit prompts:** run `python src/retag.py --dry-run` on a sample, eyeball the output, then do a full run.
- **When you touch the site:** `python src/build_site.py` locally, open `site/_dist/index.html` in a browser, confirm layout before pushing.

---

## 8. Evolution paths

Brief pointers — the earlier Phase 3 plan (in git history) has more detail.

- **Open-source template** (~1 day, $0 ops) — clean up the repo, add a `DEPLOY.md`, ship as a template. Forkers run their own instance. Right for 2–5 technical friends; wrong for non-technical users.
- **Invite-only hosted** (~2–3 weeks, ~$20/mo) — single shared Telegram bot keyed by sender's user ID; per-user archives at subdomains. Right for stress-testing "does anyone use this besides me?" before committing to a full product.
- **Hosted SaaS** (~4–8 weeks, $30–100/mo) — new repo. Postgres, queue, Clerk/Supabase auth, Stripe billing, marketing site. Only worth it once the invite-only tier shows real weekly engagement.

Default: stay on single-user until you have clear signal.
