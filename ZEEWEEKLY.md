# ZEEWEEKLY — editorial master doc

This is the editorial spec for **Zee Weekly**, the publication at [zeeweekly.com](https://zeeweekly.com/). [MASTER.md](MASTER.md) covers the *system* — this one covers the *product*: what the publication is, how an issue is assembled, what it should feel like to read, and what's out of scope.

If you're changing how posts are tagged, what the digest looks like, or why a category exists, start here. If you're changing how the pipeline runs, start in MASTER.md instead.

---

## 1. The bet

Short-form video is a great input and a terrible archive. You see something sharp, you swipe, it's gone. **Zee Weekly** is the opposite of that: a compressed, high-density weekly digest of the reels worth remembering, grouped by theme, with the recipes, claims, and key points pulled out so you don't have to rewatch.

One reader's pace. One email a week. A browsable archive that ages well.

---

## 2. Voice

- **Warm, a little witty, never cheesy.** Like a smart friend walking you through their week of saves, not a marketing department announcing itself.
- **First-person plural and direct address.** "We saved…", "you'll want to see…". Avoid the imperial "I" and avoid corporate "the team".
- **Short paragraphs. One idea each.** If a sentence has two ideas, it's two sentences.
- **No emojis. No hashtags. No signoff.** The editorial voice is the signoff.
- **Witty transitions are earned, not forced.** If you can't land a section opener that beats the plain header, use the plain header.
- **Specific beats generic.** "Discusses productivity" is out; "the 20-minute rule for kitchen prep" is in.

The blurbs under each category are a good calibration for the tone:

- *AI* — "What shipped, what broke, what's actually worth the hype."
- *Marketing* — "Hooks, pitches, and the quiet psychological heists behind a good campaign."
- *Investment* — "Markets, macro, and the ancient art of not setting money on fire."
- *Politics* — "Policy, power, and the chessboard nobody asked for."
- *Psychology* — "Small experiments on the mushy machine between your ears."
- *Fitness* — "Strength, sleep, recovery — the boring stuff that actually works."
- *Food* — "Recipes worth stealing and meals worth remembering."
- *Other* — "The stragglers, the oddballs, the couldn't-not-save-this pile."

If a new blurb doesn't sound like it belongs in that list, rewrite it.

---

## 3. Categories (the taxonomy)

Eight tags. Each post gets exactly one. "Other" is a real bucket — don't force-fit.

| Priority tier | Tags | Rule |
|---|---|---|
| Lead (always in) | `ai`, `marketing` | These are the spine of the publication. |
| Mid (included next) | `investment`, `politics` | Filled in after AI + Marketing, if the issue has room. |
| Backlog (archive-only overflow) | `psychology`, `fitness`, `food`, `other` | Only included in an issue if space remains after Lead and Mid are drained. |

Edge cases to respect:

- **Marketing vs Psychology.** If the post is about cognitive biases *as deployed in persuasion / sales / conversion*, tag `marketing`. If it's about biases as a framework for understanding yourself, tag `psychology`.
- **Fitness vs Food.** Nutrition theory tied to body composition → `fitness`. A specific recipe or meal prep → `food`. A recipe that happens to be high-protein is still `food`.
- **AI marketing content.** If it's about AI industry or AI products, tag `ai`. If it's about using AI to do marketing better, tag `marketing`.

Adding or removing a category touches: `src/prompts.py`, `src/claude_client.py` (the `Tag` literal), `src/build_site.py` (`TAG_ORDER`, `TAG_LABELS`, `TAG_BLURBS`, `PRIORITY_TIERS` in `src/issue.py`), `site/static/styles.css` (all the `--cat-X` vars + every `.cat-X` rule). After the schema change, run `python src/retag.py` to re-tag history.

---

## 4. Issue assembly (the editorial cut)

**Every issue is capped at 10 posts.** More than 10 saves in a week means the overflow lands in the archive only — not in the email.

The cut is run by `src/issue.py::cut_for_issue`:

1. Group all of the week's unsent posts by priority tier.
2. Within each tier, sort by recency (newest first).
3. Take the top 10 across the ordered tiers.
4. The remaining posts become `backlog` — still browsable on the week page (under "Also saved this week") and tag pages, but not in the email digest.

The 10-post cap is the single most important editorial rule. It forces the week to have a shape — otherwise every Friday becomes a firehose.

Tuning: the cap lives in `ISSUE_LIMIT` (`src/issue.py`). The tier ordering lives in `PRIORITY_TIERS` (same file). Change both there and the publication auto-adjusts.

---

## 5. Post anatomy

Every post renders to the same card contract:

- **Title** — 8 words max. Punchy, specific. Not the caption verbatim.
- **One-liner** — ≤20 words. What this post is actually about, in one sentence.
- **Key points** — 2–4 bullets. Concrete claims, steps, numbers. "Discusses X" is not a key point.
- **Recipe** (food only) — ingredients (with exact quantities), instructions (numbered short steps), optional prep_time + servings.
- **Byline + link** — original author handle + "Watch →" link.

These come out of `tag_reel()` via `ReelTag` (`src/claude_client.py`). Breaking this contract breaks the templates.

---

## 6. The weekly headline

Every issue has a **theme headline** — a 6–10 word editorial phrase that names the dominant tension of the week. Not the title of any single post; a synthesis across all of them.

The headline is generated by Claude Haiku 4.5 (`compose_week_theme()` in `src/claude_client.py`) and cached in `data/themes.json`, keyed by a fingerprint of the week's post set. It only regenerates when the post set changes — cheap by default, but consistently fresh.

Good headlines:
- "The week AI learned to cook"
- "Markets nervous, growth hackers sober"
- "Recovery, compounding, and quiet discipline"

Bad headlines (avoid):
- "AI and marketing news" (too generic)
- "This week: 10 amazing posts" (clickbait)
- "A busy week in tech" (filler)

The hero on the home page uses the current week's theme. Older weeks keep the theme that was generated when they were the current week.

---

## 7. Subscribe flow + email capture

Two entry points for the mailing list:

- **Inline form** — embedded in every page (bottom subscribe section).
- **Popup** — appears once per visitor, 4.5 s after first load. Dismissing or submitting sets a `localStorage` flag so it never shows again on that browser.

Both forms post to a **Google Form** whose backend Sheet is the subscriber list. Two env vars wire it up:

- `SUBSCRIBE_FORM_URL` — the Form's `formResponse` URL.
- `SUBSCRIBE_FORM_EMAIL_ENTRY` — the `entry.NNNNN` field id for the email field.

If either is unset, the popup disables itself entirely (the inline form still renders but goes nowhere). **Find the entry id** by viewing the published Form's source HTML and grepping for `entry.`; the one on the email field is what you want.

The Sheet is the list. When you want to broadcast, export the email column into Resend (or Mailchimp, or wherever you're sending from). This repo does not send to the list directly — that's intentional, so the list can outlive any particular sender.

---

## 8. Design system (at a glance)

| Element | Choice |
|---|---|
| Display font | Fraunces (variable, 9–144 optical size) |
| Body font | Source Serif 4 |
| Mono | JetBrains Mono |
| Palette | Sorbet — cream background `#FFFDFC`, navy ink `#0B1F3A` |
| Per-category color | Pink (AI), cornflower blue (Marketing), mint (Investment), butter (Politics), lavender (Psychology), matcha (Fitness), coral (Food), warm grey (Other) |
| Card grid | Magazine layout — lead post spans full width, runners-up alternate tinted fills |
| Email shell | Same palette, fonts, and per-category accents as the site. Single column, 640px max, Fraunces masthead over `Zee Weekly · Issue N° NNN`, theme headline as h1, per-category card accents mirror `--cat-X`. Defined in `src/newsletter.py::EMAIL_CSS`. |
| Email subject | `{theme} · Zee Weekly` — theme leads the inbox preview; brand reassures at the end. Fallback: `Zee Weekly · Issue N° NNN`. |
| Email sender | `Zee Weekly <onboarding@resend.dev>` until a verified domain is configured. |

All of this lives in `site/static/styles.css` (variables in the `:root` block at the top). Don't hand-code hex values inline — reference the variables. The email CSS is a standalone string inside `src/newsletter.py` — duplication on purpose, because mail clients can't load remote stylesheets.

---

## 9. What we don't do

- **No sponsors.** Not now, maybe not ever. The editorial bar would bend.
- **No daily or on-demand digests.** Friday is the cadence. That's the whole point.
- **No recommendation engine.** Zee is the recommender.
- **No comment section.** The archive is a reading surface, not a forum.
- **No auto-translate.** Multilingual reels stay in their source language with English summaries.
- **No tracking pixels, no analytics scripts, no fingerprinting.** The site is static and polite.

---

## 10. Cadence

| When | What |
|---|---|
| Any day | Share reels to the bot. Ingestion runs every 30 min. |
| Thursday night | Skim the week's saves in the archive — spot-check tags. |
| Friday 08:00 UTC | Digest is composed and sent by `newsletter.yml`. |
| Friday after send | Glance at the delivered email. Anything off, fix the prompt or retag. |
| Monthly | Confirm `ingest` runs have been green. Re-export Instagram cookies if needed. |
| Quarterly | Revisit this doc. The taxonomy and priority tiers should match how you actually think about the week. |
