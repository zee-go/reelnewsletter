from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import resend

from claude_client import compose_newsletter

ROOT = Path(__file__).resolve().parent.parent
REELS_DIR = ROOT / "data" / "reels"
SENT_DIR = ROOT / "data" / "sent"


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


EMAIL_CSS = """
  body { margin:0; padding:0; background:#f5f3ef; }
  .container {
    max-width:640px; margin:0 auto; padding:40px 24px;
    background:#ffffff;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
    color:#1a1a1a; line-height:1.55; font-size:16px;
  }
  h1 {
    font-size:28px; line-height:1.2; margin:0 0 4px; letter-spacing:-0.02em;
    color:#0f172a; font-weight:700;
  }
  .date { margin:0 0 24px; color:#64748b; font-size:14px; font-weight:500; letter-spacing:0.04em; text-transform:uppercase; }
  .intro { margin:0 0 32px; color:#334155; font-size:17px; }
  h2 {
    font-size:13px; font-weight:700; letter-spacing:0.12em; text-transform:uppercase;
    color:#0891b2; border-top:1px solid #e2e8f0; padding-top:24px; margin:32px 0 16px;
  }
  .post { margin:0 0 28px; padding:0; }
  .post h3 { font-size:18px; font-weight:600; margin:0 0 6px; color:#0f172a; line-height:1.3; }
  .post .lead { margin:0 0 12px; color:#1e293b; }
  .post ul, .post ol { margin:0 0 12px; padding-left:20px; color:#334155; }
  .post ul li, .post ol li { margin:0 0 6px; }
  .meta { font-size:14px; color:#64748b; margin:0; }
  .meta a { color:#0891b2; text-decoration:none; border-bottom:1px solid #bae6fd; }
  .meta a:hover { color:#0e7490; border-bottom-color:#0891b2; }
  .recipe { background:#fefce8; border:1px solid #fde68a; border-radius:8px; padding:20px 24px; }
  .recipe h3 { color:#78350f; }
  .recipe .lead { color:#713f12; }
  .recipe-meta { font-style:italic; color:#92400e; font-size:14px; margin:0 0 12px; }
  .ingredients, .steps { margin:8px 0 16px; }
  .recipe p strong { color:#78350f; font-size:14px; letter-spacing:0.04em; text-transform:uppercase; }
  a { color:#0891b2; }
"""


def wrap_email(body_html: str, title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{EMAIL_CSS}</style>
</head>
<body>
<div class="container">
{body_html}
</div>
</body>
</html>"""


def send_email(html: str, subject: str, to: str) -> str:
    resend.api_key = os.environ["RESEND_API_KEY"]
    from_addr = os.environ.get("NEWSLETTER_FROM", "Reel Digest <newsletter@resend.dev>")
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

    now = datetime.now(tz=timezone.utc)
    week_label = now.strftime("%B %d, %Y")
    newsletter_id = now.strftime("%Y-%m-%d")

    print("Composing newsletter with Claude...", flush=True)
    body_html = compose_newsletter(reels, week_label)
    subject = f"Reel digest — week of {week_label}"

    full_html = wrap_email(body_html, subject)

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
