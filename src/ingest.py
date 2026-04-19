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
import requests

import telegram
import csv_export
import sheets_export
from claude_client import tag_reel

ROOT = Path(__file__).resolve().parent.parent
REELS_DIR = ROOT / "data" / "reels"
STATE_PATH = ROOT / "data" / "state.json"

ALLOWED_CHAT_ID = int(os.environ["TELEGRAM_ALLOWED_CHAT_ID"])

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGES_PER_POST = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Whisper is priced per audio-second. Reels are usually <2 min; cap at 10 min
# to contain worst-case cost when someone forwards a long Facebook upload.
WHISPER_MAX_AUDIO_SECONDS = 600

URL_RE = re.compile(
    r"https?://(?:www\.|m\.)?"
    r"(?:instagram\.com/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+"
    r"|facebook\.com/\S+"
    r"|fb\.watch/\S+)",
    re.IGNORECASE,
)

IG_SHORTCODE_RE = re.compile(r"/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"telegram_offset": 0}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def extract_urls(message: dict) -> list[str]:
    text = message.get("text") or message.get("caption") or ""
    urls = list(URL_RE.findall(text))
    for entity in (message.get("entities") or []) + (message.get("caption_entities") or []):
        if entity.get("type") == "text_link":
            u = entity.get("url") or ""
            if URL_RE.match(u):
                urls.append(u)
    seen = set()
    out = []
    for u in urls:
        u = u.rstrip(".,)")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def shortcode(url: str) -> str:
    m = IG_SHORTCODE_RE.search(url)
    if m:
        return m.group(1)
    m = re.search(r"facebook\.com/reel/(\d+)", url, re.IGNORECASE)
    if m:
        return f"fb{m.group(1)}"
    m = re.search(r"facebook\.com/share/[rvp]/([A-Za-z0-9_-]+)", url, re.IGNORECASE)
    if m:
        return f"fbs{m.group(1)}"
    m = re.search(r"fb\.watch/([A-Za-z0-9_-]+)", url, re.IGNORECASE)
    if m:
        return f"fbw{m.group(1)}"
    m = re.search(r"fbid=(\d+)", url)
    if m:
        return f"fb{m.group(1)}"
    m = re.search(r"[?&]v=(\d+)", url)
    if m:
        return f"fbv{m.group(1)}"
    return "unknown"


def _ytdlp_cmd(url: str, workdir: Path, *, write_thumbnails: bool) -> list[str]:
    cmd = [
        "yt-dlp",
        "-o", str(workdir / "media_%(playlist_index|1)s_%(id)s.%(ext)s"),
        "--write-info-json",
        "--no-warnings",
        "--ignore-no-formats-error",
    ]
    if write_thumbnails:
        cmd += ["--write-all-thumbnails", "--skip-download"]
    cookies_file = os.environ.get("INSTAGRAM_COOKIES_FILE")
    if cookies_file and Path(cookies_file).exists():
        cmd += ["--cookies", cookies_file]
    cmd.append(url)
    return cmd


def _scan(workdir: Path, exts: set[str]) -> list[Path]:
    return sorted(p for p in workdir.iterdir() if p.suffix.lower() in exts)


def _load_info(workdir: Path) -> dict:
    info_path = next(workdir.glob("*.info.json"), None)
    return json.loads(info_path.read_text()) if info_path else {}


def _download_from_info(info: dict, workdir: Path) -> list[Path]:
    """Fallback: extract image URLs from info.json and download via requests."""
    candidates: list[str] = []

    def take_best_thumb(thumbs: list | None) -> str | None:
        if not thumbs:
            return None
        ranked = sorted(
            (t for t in thumbs if t.get("url")),
            key=lambda t: (t.get("width") or 0) * (t.get("height") or 0),
            reverse=True,
        )
        return ranked[0]["url"] if ranked else None

    if info.get("entries"):
        for entry in info["entries"]:
            u = entry.get("display_url") or take_best_thumb(entry.get("thumbnails"))
            if u:
                candidates.append(u)
    else:
        u = info.get("display_url") or take_best_thumb(info.get("thumbnails"))
        if u:
            candidates.append(u)

    # IG/FB CDNs block requests with no UA or a bot UA. Spoof a real browser.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.1 Safari/605.1.15"
        ),
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.instagram.com/",
    }

    out: list[Path] = []
    for i, url in enumerate(candidates[:MAX_IMAGES_PER_POST]):
        try:
            r = requests.get(url, timeout=30, headers=headers)
            r.raise_for_status()
            content = r.content
            if len(content) > MAX_IMAGE_BYTES:
                continue
            ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(ct, ".jpg")
            path = workdir / f"fallback_{i}{ext}"
            path.write_bytes(content)
            out.append(path)
        except Exception as e:
            print(f"  fallback image {i} failed: {e}", flush=True)
    return out


def download_content(url: str, workdir: Path) -> dict:
    """Download video or images + metadata. Returns dict with videos, images, caption, author, duration."""
    r1 = subprocess.run(
        _ytdlp_cmd(url, workdir, write_thumbnails=False),
        capture_output=True, text=True, cwd=workdir,
    )
    videos = _scan(workdir, VIDEO_EXTS)
    images = _scan(workdir, IMAGE_EXTS)

    if not videos and not images:
        # Photo/carousel post: re-run to grab thumbnails, then fall back to info.json
        r2 = subprocess.run(
            _ytdlp_cmd(url, workdir, write_thumbnails=True),
            capture_output=True, text=True, cwd=workdir,
        )
        images = _scan(workdir, IMAGE_EXTS)
        if not images:
            info = _load_info(workdir)
            if info:
                print(f"  photo fallback: info.json has keys {list(info)[:10]}", flush=True)
                images = _download_from_info(info, workdir)
            else:
                print(f"  photo fallback: no info.json. "
                      f"ytdlp-v1 stderr: {r1.stderr[:300]} "
                      f"ytdlp-v2 stderr: {r2.stderr[:300]}", flush=True)

    if not videos and not images:
        raise RuntimeError(
            f"yt-dlp produced no media. stderr: {r1.stderr[:400]} stdout: {r1.stdout[:200]}"
        )

    info = _load_info(workdir)
    # If we have a video, drop any thumbnails that slipped in — they're just video stills
    if videos:
        images = []
    else:
        images = [p for p in images if p.stat().st_size <= MAX_IMAGE_BYTES][:MAX_IMAGES_PER_POST]

    return {
        "videos": videos,
        "images": images,
        "caption": info.get("description") or info.get("title") or "",
        "author": info.get("uploader") or info.get("channel") or "",
        "duration_s": info.get("duration") or 0,
    }


def extract_audio(video_path: Path, out_path: Path, duration_s: int = 0) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "mp3", "-ab", "64k",
        "-loglevel", "error",
    ]
    if duration_s and duration_s > WHISPER_MAX_AUDIO_SECONDS:
        cmd += ["-t", str(WHISPER_MAX_AUDIO_SECONDS)]
        print(
            f"  Source video is {duration_s}s; capping transcript audio at "
            f"{WHISPER_MAX_AUDIO_SECONDS}s to limit Whisper cost.",
            flush=True,
        )
    cmd.append(str(out_path))
    subprocess.run(cmd, check=True)


def transcribe(audio_path: Path) -> str:
    client = openai.OpenAI()
    with audio_path.open("rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f)
    return result.text or ""


def process_reel(url: str, received_at: str) -> dict:
    code = shortcode(url)
    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        meta = download_content(url, work)
        transcript = ""
        if meta["videos"]:
            audio = work / "audio.mp3"
            extract_audio(meta["videos"][0], audio, duration_s=meta.get("duration_s", 0))
            transcript = transcribe(audio)

        # Load images as bytes before tempdir is cleaned up
        image_payloads: list[tuple[bytes, str]] = []
        for img in meta["images"]:
            media_type = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
            }.get(img.suffix.lower(), "image/jpeg")
            image_payloads.append((img.read_bytes(), media_type))

    tagged = tag_reel(
        caption=meta["caption"],
        transcript=transcript,
        url=url,
        images=image_payloads,
    )

    return {
        "shortcode": code,
        "url": url,
        "received_at": received_at,
        "caption": meta["caption"],
        "author": meta["author"],
        "duration_s": meta["duration_s"],
        "has_video": bool(meta["videos"]),
        "image_count": len(image_payloads),
        "transcript": transcript,
        "tag": tagged.tag,
        "title": tagged.title,
        "one_liner": tagged.one_liner,
        "key_points": tagged.key_points,
        "recipe": tagged.recipe.model_dump() if tagged.recipe else None,
        "sent_in_newsletter": None,
    }


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
            kind = "video" if record["has_video"] else f"{record['image_count']} image(s)"
            print(f"Saved {path.name} [{record['tag']}] ({kind}) {record['one_liner']}", flush=True)
            try:
                sheets_export.append(record)
            except Exception as e:
                print(f"  sheets_export failed (non-fatal): {e}", flush=True)
            if not args.dry_run:
                reply = (
                    f"Logged [{record['tag']}] {record['title']}\n"
                    f"{record['one_liner']}"
                )
                telegram.send_message(chat_id, reply)

    if processed:
        try:
            csv_export.rebuild()
            print(f"Rebuilt data/records.csv and data/INDEX.md.", flush=True)
        except Exception as e:
            print(f"csv_export failed (non-fatal): {e}", flush=True)

    new_offset = max_update_id + 1 if updates else offset
    if not args.dry_run and new_offset != offset:
        state["telegram_offset"] = new_offset
        save_state(state)
        print(f"Saved offset {new_offset}.", flush=True)

    print(f"Processed {processed} reel(s).", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
