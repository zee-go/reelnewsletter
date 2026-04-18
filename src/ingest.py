from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import openai

import telegram
from claude_client import tag_reel

ROOT = Path(__file__).resolve().parent.parent
REELS_DIR = ROOT / "data" / "reels"
STATE_PATH = ROOT / "data" / "state.json"

ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_ALLOWED_CHAT_ID"])

INSTAGRAM_URL_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+/?[^\s]*",
    re.IGNORECASE,
)
SHORTCODE_RE = re.compile(r"/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"telegram_offset": 0}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def extract_urls(message: dict) -> list[str]:
    text = message.get("text") or message.get("caption") or ""
    urls = list(INSTAGRAM_URL_RE.findall(text))
    for entity in (message.get("entities") or []) + (message.get("caption_entities") or []):
        if entity.get("type") == "text_link" and "instagram.com" in (entity.get("url") or ""):
            if INSTAGRAM_URL_RE.match(entity["url"]):
                urls.append(entity["url"])
    seen = set()
    out = []
    for u in urls:
        u = u.rstrip(".,)")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def shortcode(url: str) -> str:
    m = SHORTCODE_RE.search(url)
    return m.group(1) if m else "unknown"


def download_reel(url: str, workdir: Path) -> dict:
    """Download video + metadata via yt-dlp. Returns dict with video_path, caption, author, duration."""
    info_path = workdir / "info.json"
    video_path = workdir / "video.%(ext)s"
    cmd = [
        "yt-dlp",
        "-o",
        str(video_path),
        "--write-info-json",
        "--no-warnings",
    ]
    cookies_file = os.environ.get("INSTAGRAM_COOKIES_FILE")
    if cookies_file and Path(cookies_file).exists():
        cmd += ["--cookies", cookies_file]
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
    if result.returncode != 0:
        raise RuntimeError(
            f"yt-dlp exited {result.returncode}. "
            f"stderr: {result.stderr[:500]} stdout: {result.stdout[:200]}"
        )

    written_info = next(workdir.glob("*.info.json"), None)
    if written_info and written_info != info_path:
        written_info.rename(info_path)
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    found_video = next(
        (p for p in workdir.iterdir() if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")),
        None,
    )
    if not found_video:
        hint = "" if cookies_file else " (hint: set INSTAGRAM_COOKIES secret — see README)"
        raise RuntimeError(
            f"yt-dlp succeeded but produced no video file.{hint} "
            f"stdout: {result.stdout[:400]}"
        )
    return {
        "video_path": found_video,
        "caption": info.get("description") or info.get("title") or "",
        "author": info.get("uploader") or info.get("channel") or "",
        "duration_s": info.get("duration") or 0,
    }


def extract_audio(video_path: Path, out_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "mp3",
            "-ab",
            "64k",
            "-loglevel",
            "error",
            str(out_path),
        ],
        check=True,
    )


def transcribe(audio_path: Path) -> str:
    client = openai.OpenAI()
    with audio_path.open("rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f)
    return result.text or ""


def process_reel(url: str, received_at: str) -> dict:
    code = shortcode(url)
    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        meta = download_reel(url, work)
        audio = work / "audio.mp3"
        extract_audio(meta["video_path"], audio)
        transcript = transcribe(audio)

    tagged = tag_reel(caption=meta["caption"], transcript=transcript, url=url)

    record = {
        "shortcode": code,
        "url": url,
        "received_at": received_at,
        "caption": meta["caption"],
        "author": meta["author"],
        "duration_s": meta["duration_s"],
        "transcript": transcript,
        "tag": tagged.tag,
        "title": tagged.title,
        "one_liner": tagged.one_liner,
        "key_points": tagged.key_points,
        "sent_in_newsletter": None,
    }
    return record


def write_record(record: dict) -> Path:
    REELS_DIR.mkdir(parents=True, exist_ok=True)
    date = record["received_at"][:10]
    out = REELS_DIR / f"{date}-{record['shortcode']}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Process but don't send Telegram replies or commit state.")
    args = parser.parse_args()

    state = load_state()
    offset = state.get("telegram_offset", 0)
    print(f"Polling Telegram from offset {offset}...", flush=True)
    updates = telegram.get_updates(offset=offset or None)
    print(f"Got {len(updates)} update(s).", flush=True)

    max_update_id = offset - 1 if offset else 0
    processed = 0
    for update in updates:
        update_id = update["update_id"]
        max_update_id = max(max_update_id, update_id)
        message = update.get("message") or update.get("channel_post")
        if not message:
            continue
        chat_id = message["chat"]["id"]
        if chat_id != ALLOWED_CHAT_ID:
            print(f"Skipping message from unauthorized chat {chat_id}", flush=True)
            continue
        urls = extract_urls(message)
        if not urls:
            continue
        received_at = datetime.fromtimestamp(message["date"], tz=timezone.utc).isoformat()
        for url in urls:
            try:
                record = process_reel(url, received_at)
            except Exception as e:
                err = f"Failed to process {url}: {e}"
                print(err, flush=True)
                if not args.dry_run:
                    telegram.send_message(chat_id, f"Error logging {url}\n{e}")
                continue
            path = write_record(record)
            processed += 1
            print(f"Saved {path.name} [{record['tag']}] {record['one_liner']}", flush=True)
            if not args.dry_run:
                reply = (
                    f"Logged [{record['tag']}] {record['title']}\n"
                    f"{record['one_liner']}"
                )
                telegram.send_message(chat_id, reply)

    new_offset = max_update_id + 1 if updates else offset
    if not args.dry_run and new_offset != offset:
        state["telegram_offset"] = new_offset
        save_state(state)
        print(f"Saved offset {new_offset}.", flush=True)

    print(f"Processed {processed} reel(s).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
