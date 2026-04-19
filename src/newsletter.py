from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import resend

from claude_client import compose_newsletter, compose_week_theme
from issue import ISSUE_LIMIT, cut_for_issue

ROOT = Path(__file__).resolve().parent.parent
REELS_DIR = ROOT / "data" / "reels"
SENT_DIR = ROOT / "data" / "sent"
THEMES_FILE = ROOT / "data" / "themes.json"

SITE_URL = "https://zeeweekly.com"


def _week_key(iso_dt: str) -> str:
    """Monday of the ISO week — matches build_site._week_key."""
    dt = datetime.fromisoformat(iso_dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return monday.date().isoformat()


def _compute_issue_num() -> int:
    """Issue N° = count of distinct weeks with at least one post, including this one."""
    if not REELS_DIR.exists():
        return 1
    weeks = set()
    for p in REELS_DIR.glob("*.json"):
        try:
            rec = json.loads(p.read_text())
        except Exception:
            continue
        if rec.get("received_at"):
            weeks.add(_week_key(rec["received_at"]))
    return max(len(weeks), 1)


def _resolve_theme(reels: list[dict]) -> str:
    """Look up cached theme for the issue's week; call Haiku only if missing."""
    if not reels:
        return ""
    wid = _week_key(min(r["received_at"] for r in reels))
    try:
        themes = json.loads(THEMES_FILE.read_text()) if THEMES_FILE.exists() else {}
    except json.JSONDecodeError:
        themes = {}
    cached = themes.get(wid)
    if cached and cached.get("headline"):
        return cached["headline"]
    try:
        return compose_week_theme(reels)
    except Exception as e:  # noqa: BLE001
        print(f"  [theme] generation failed ({e}); continuing without headline.", flush=True)
        return ""


def load_unsent_reels(window_days: int) -> list[dict]:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=window_days)
    reels = []
    for path in sorted(REELS_DIR.glob("*.json")):
        rec = json.loads(path.read_text())
        if rec.get("sent_in_newsletter"):
            continue
        received = datetime.fromisoformat(rec["received_at"])
        if received < cutoff:
            continue
        rec["_path"] = str(path)
        reels.append(rec)
    return reels


def mark_sent(reels: list[dict], newsletter_id: str) -> None:
    for rec in reels:
        path = Path(rec.pop("_path"))
        rec["sent_in_newsletter"] = newsletter_id
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")


# Email CSS mirrors the zeeweekly.com palette + type system.
# Fraunces is requested via Google Fonts; mail clients that strip remote fonts
# gracefully fall back through Charter → Iowan Old Style → Georgia.
EMAIL_CSS = """
  body { margin:0; padding:0; background:#FFFDFC; color:#1A1A1A; }
  .wrap { padding:32px 16px; }
  .container {
    max-width:640px; margin:0 auto; background:#FFFFFF;
    border:1px solid #E8E2D1; border-radius:4px; overflow:hidden;
    font-family:'Source Serif 4',Georgia,serif;
    color:#1A1A1A; line-height:1.6; font-size:17px;
  }

  /* Masthead — mirrors site header */
  .masthead {
    padding:20px 32px; border-bottom:1px solid #E8E2D1;
    display:table; width:100%; box-sizing:border-box;
  }
  .masthead-left, .masthead-right {
    display:table-cell; vertical-align:middle;
    font-family:'JetBrains Mono','SF Mono',Menlo,Monaco,monospace;
    font-size:10px; letter-spacing:0.14em; text-transform:uppercase;
    color:#6b6056;
  }
  .masthead-right { text-align:right; }
  .masthead-right a { color:#6b6056; text-decoration:none; }
  .brand-dot { color:#ff6fa5; font-size:10px; }
  .brand {
    font-family:'Fraunces',Georgia,serif;
    font-weight:600; font-size:15px; letter-spacing:-0.01em;
    color:#1A1A1A; text-transform:none; text-decoration:none;
  }

  /* Hero — theme headline + issue / date */
  .hero { padding:36px 32px 8px; }
  .hero .kicker {
    font-family:'JetBrains Mono','SF Mono',Menlo,Monaco,monospace;
    font-size:10px; letter-spacing:0.14em; text-transform:uppercase;
    color:#6b6056; margin:0 0 14px;
  }
  .hero h1 {
    font-family:'Fraunces',Georgia,serif;
    font-size:30px; line-height:1.12; letter-spacing:-0.025em;
    font-weight:600; color:#1A1A1A; margin:0 0 18px; text-wrap:balance;
  }
  .hero-meta {
    font-family:'JetBrains Mono','SF Mono',Menlo,Monaco,monospace;
    font-size:11px; letter-spacing:0.08em; text-transform:uppercase;
    color:#6b6056; margin:0 0 4px;
  }
  .hero-meta .sep { color:#c9bfae; margin:0 8px; }

  /* Body */
  .body { padding:8px 32px 8px; }
  .intro {
    font-family:'Fraunces',Georgia,serif;
    font-style:italic; font-size:19px; line-height:1.5;
    color:#3a332c; margin:24px 0 32px; text-wrap:pretty;
  }

  /* Section headers — color rule + label, mirrors site */
  h2 {
    font-family:'JetBrains Mono','SF Mono',Menlo,Monaco,monospace;
    font-size:11px; font-weight:600; letter-spacing:0.16em; text-transform:uppercase;
    color:#1A1A1A; margin:40px 0 18px; padding:0 0 10px;
    border-bottom:1px solid #E8E2D1; position:relative;
  }
  h2::before {
    content:""; display:inline-block; width:14px; height:2px;
    background:#a89f8f; margin-right:10px; vertical-align:middle;
  }

  /* Cards */
  .post {
    background:#FFFFFF;
    border:1px solid #E8E2D1; border-top:3px solid #a89f8f; border-radius:3px;
    padding:22px 24px; margin:0 0 16px;
  }
  .post h3 {
    font-family:'Fraunces',Georgia,serif;
    font-size:22px; font-weight:600; line-height:1.2; letter-spacing:-0.015em;
    margin:0 0 10px; color:#1A1A1A;
  }
  .post .lead { margin:0 0 12px; color:#1A1A1A; font-size:17px; }
  .post ul, .post ol { margin:10px 0 14px; padding-left:20px; color:#3a332c; }
  .post ul li, .post ol li { margin:0 0 6px; }
  .meta {
    font-family:'JetBrains Mono','SF Mono',Menlo,Monaco,monospace;
    font-size:11px; letter-spacing:0.04em; color:#6b6056;
    margin:14px 0 0; padding-top:12px; border-top:1px solid #F0E9D8;
  }
  .meta a {
    color:#1A1A1A; text-decoration:none; font-weight:600;
    border-bottom:1.5px solid; padding-bottom:1px;
  }

  /* Per-category accent colors, matching site --cat-X */
  .cat-ai         { border-top-color:#ff6fa5; }
  .cat-ai         .meta a { border-bottom-color:#ff6fa5; }
  .cat-ai         h2::before { background:#ff6fa5; }
  .cat-marketing  { border-top-color:#6aa7f5; }
  .cat-marketing  .meta a { border-bottom-color:#6aa7f5; }
  .cat-investment { border-top-color:#5fcfbc; }
  .cat-investment .meta a { border-bottom-color:#5fcfbc; }
  .cat-politics   { border-top-color:#f5b84a; }
  .cat-politics   .meta a { border-bottom-color:#f5b84a; }
  .cat-psychology { border-top-color:#c78fd9; }
  .cat-psychology .meta a { border-bottom-color:#c78fd9; }
  .cat-fitness    { border-top-color:#7dc87a; }
  .cat-fitness    .meta a { border-bottom-color:#7dc87a; }
  .cat-food       { border-top-color:#ff9b7a; }
  .cat-food       .meta a { border-bottom-color:#ff9b7a; }
  .cat-other      { border-top-color:#a89f8f; }
  .cat-other      .meta a { border-bottom-color:#a89f8f; }

  /* Recipe — tinted body on top of food accent */
  .post.recipe { background:rgba(255,155,122,0.08); }
  .recipe-meta {
    font-family:'JetBrains Mono','SF Mono',Menlo,Monaco,monospace;
    font-size:11px; letter-spacing:0.08em; text-transform:uppercase;
    color:#6b6056; margin:0 0 14px;
  }
  .recipe p strong {
    font-family:'JetBrains Mono','SF Mono',Menlo,Monaco,monospace;
    color:#1A1A1A; font-size:11px; letter-spacing:0.14em;
    text-transform:uppercase; font-weight:600;
  }
  .recipe .ingredients, .recipe .steps { margin:6px 0 16px; }

  /* Footer — matches site footer */
  .footer {
    padding:28px 32px 32px; margin-top:8px;
    border-top:1px solid #E8E2D1;
    font-family:'JetBrains Mono','SF Mono',Menlo,Monaco,monospace;
    font-size:10px; letter-spacing:0.1em; text-transform:uppercase;
    color:#6b6056;
  }
  .footer a { color:#6b6056; text-decoration:none; }
  .footer .row { display:table; width:100%; }
  .footer .row > div { display:table-cell; vertical-align:middle; }
  .footer .right { text-align:right; }
  .footer .right a + a { margin-left:16px; }

  a { color:#1A1A1A; }
"""


def wrap_email(
    body_html: str,
    *,
    theme: str,
    issue_num: int,
    week_label: str,
    post_count: int,
) -> str:
    headline = theme or "This week, curated."
    # Match site exactly — same URL as site/templates/base.html so shared prefetch
    # caches work, and weights line up with --display-weight / h1 / meta usage.
    fonts_link = (
        "https://fonts.googleapis.com/css2?"
        "family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,400"
        "&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;0,8..60,600;1,8..60,400"
        "&family=JetBrains+Mono:wght@400;500;600"
        "&display=swap"
    )
    issue_str = f"{issue_num:03d}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Zee Weekly · Issue N° {issue_str}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{fonts_link}" rel="stylesheet">
<style>{EMAIL_CSS}</style>
</head>
<body>
<div class="wrap">
<div class="container">
  <div class="masthead">
    <div class="masthead-left">
      <span class="brand-dot">●</span>&nbsp;&nbsp;<a class="brand" href="{SITE_URL}">Zee Weekly</a>
    </div>
    <div class="masthead-right">
      Issue N° {issue_str}
    </div>
  </div>

  <div class="hero">
    <div class="kicker">Week of {week_label}</div>
    <h1>{headline}</h1>
    <div class="hero-meta">
      {post_count} pick{'s' if post_count != 1 else ''}
      <span class="sep">·</span> AI &amp; Marketing first
      <span class="sep">·</span> <a href="{SITE_URL}" style="color:inherit;">Read online →</a>
    </div>
  </div>

  <div class="body">
{body_html}
  </div>

  <div class="footer">
    <div class="row">
      <div>© 2026 Zee Weekly · Curated by Zee</div>
      <div class="right">
        <a href="{SITE_URL}">zeeweekly.com</a>
        <a href="{SITE_URL}/archive/">Archive</a>
      </div>
    </div>
  </div>
</div>
</div>
</body>
</html>"""


def send_email(html: str, subject: str, to: str) -> str:
    resend.api_key = os.environ["RESEND_API_KEY"]
    from_addr = os.environ.get("NEWSLETTER_FROM") or "Zee Weekly <onboarding@resend.dev>"
    result = resend.Emails.send(
        {"from": from_addr, "to": to, "subject": subject, "html": html}
    )
    return result.get("id", "unknown")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Write preview HTML to data/sent/preview.html without sending.")
    parser.add_argument("--window-days", type=int, default=7)
    args = parser.parse_args()

    reels = load_unsent_reels(args.window_days)
    print(f"Found {len(reels)} unsent reel(s) in the last {args.window_days} days.", flush=True)

    if not reels:
        print("No reels to send. Skipping.", flush=True)
        return 0

    issue_reels, backlog_reels = cut_for_issue(reels)
    if backlog_reels:
        print(
            f"Issue cap is {ISSUE_LIMIT}. Including {len(issue_reels)} by priority; "
            f"{len(backlog_reels)} deferred to archive-only.",
            flush=True,
        )

    now = datetime.now(tz=timezone.utc)
    week_label = now.strftime("%B %-d, %Y")
    newsletter_id = now.strftime("%Y-%m-%d")

    theme = _resolve_theme(issue_reels)
    issue_num = _compute_issue_num()
    print(f"Issue N° {issue_num:03d} · theme: {theme or '(none)'}", flush=True)

    print("Composing newsletter with Claude...", flush=True)
    body_html = compose_newsletter(issue_reels, week_label)

    if theme:
        subject = f"{theme} · Zee Weekly"
    else:
        subject = f"Zee Weekly · Issue N° {issue_num:03d}"

    full_html = wrap_email(
        body_html,
        theme=theme,
        issue_num=issue_num,
        week_label=week_label,
        post_count=len(issue_reels),
    )

    SENT_DIR.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        preview = SENT_DIR / "preview.html"
        preview.write_text(full_html)
        print(f"Dry run — wrote {preview}", flush=True)
        return 0

    to = os.environ["NEWSLETTER_TO_EMAIL"]
    email_id = send_email(full_html, subject, to)
    print(f"Sent via Resend (id={email_id}).", flush=True)

    archive = SENT_DIR / f"{newsletter_id}.html"
    archive.write_text(full_html)
    print(f"Archived to {archive}.", flush=True)

    mark_sent(reels, newsletter_id)
    print(f"Marked {len(reels)} reel(s) as sent.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
