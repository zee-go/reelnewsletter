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
  body { margin:0; padding:0; background:#FFFBF0; }
  .container {
    max-width:640px; margin:0 auto; padding:40px 24px;
    background:#FFFFFF;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
    color:#0B1F3A; line-height:1.6; font-size:17px;
  }
  h1 {
    font-size:34px; line-height:1.15; margin:0 0 6px; letter-spacing:-0.015em;
    color:#0B1F3A; font-weight:700;
    font-family:Charter,'Iowan Old Style',Georgia,'Times New Roman',serif;
  }
  .date { margin:0 0 28px; color:#4A5B75; font-size:13px; font-weight:500; letter-spacing:0.1em; text-transform:uppercase; }
  .intro {
    margin:0 0 36px; color:#4A5B75; font-size:18px;
    padding-left:16px; border-left:3px solid #FFE066;
  }
  h2 {
    font-size:13px; font-weight:700; letter-spacing:0.14em; text-transform:uppercase;
    color:#0B1F3A; padding:8px 0 8px 22px; margin:40px 0 18px;
    border-bottom:1px solid #E8E2D1; position:relative;
  }
  h2::before {
    content:""; position:absolute; left:0; top:12px;
    width:12px; height:12px; background:#FFE066; border-radius:2px;
  }
  .post {
    background:#FFFFFF; border:1px solid #E8E2D1; border-radius:10px;
    padding:22px 26px; margin:0 0 20px;
  }
  .post h3 {
    font-family:Charter,'Iowan Old Style',Georgia,serif;
    font-size:21px; font-weight:600; margin:0 0 8px; color:#0B1F3A; line-height:1.25;
  }
  .post .lead { margin:0 0 12px; color:#0B1F3A; font-size:17px; }
  .post ul, .post ol { margin:10px 0 14px; padding-left:22px; color:#4A5B75; }
  .post ul li, .post ol li { margin:0 0 6px; }
  .meta {
    font-size:13px; color:#4A5B75; margin:14px 0 0;
    padding-top:12px; border-top:1px dashed #E8E2D1; letter-spacing:0.02em;
  }
  .meta a {
    color:#0B1F3A; text-decoration:none;
    border-bottom:1.5px solid #FFE066; padding-bottom:1px;
  }
  .recipe { background:#FFF4D6; border-color:#F0D98A; }
  .recipe h3 { color:#0B1F3A; }
  .recipe-meta { font-style:italic; color:#4A5B75; font-size:14px; margin:0 0 14px; }
  .recipe p strong {
    color:#0B1F3A; font-size:12px; letter-spacing:0.14em; text-transform:uppercase; font-weight:700;
  }
  .recipe .ingredients, .recipe .steps { margin:6px 0 16px; }
  a { color:#0B1F3A; }
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
    from_addr = os.environ.get("NEWSLETTER_FROM") or "Reel Digest <onboarding@resend.dev>"
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
