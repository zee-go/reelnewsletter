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

    full_html = (
        '<div style="max-width:640px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'
        '\'Segoe UI\',Helvetica,Arial,sans-serif;line-height:1.5;color:#111;padding:24px;">'
        f"{body_html}"
        "</div>"
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
