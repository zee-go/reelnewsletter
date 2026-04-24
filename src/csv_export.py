"""Rebuild data/records.csv and data/INDEX.md deterministically from all JSON reel records."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
REELS_DIR = ROOT / "data" / "reels"
CSV_PATH = ROOT / "data" / "records.csv"
INDEX_PATH = ROOT / "data" / "INDEX.md"

COLUMNS = [
    "received_at", "shortcode", "platform", "url", "author", "tag",
    "title", "one_liner", "caption", "key_points", "transcript",
    "has_video", "image_count",
    "recipe_ingredients", "recipe_instructions", "recipe_prep_time", "recipe_servings",
    "sent_in_newsletter",
]

TAG_ORDER = ["ai", "investment", "politics", "psychology", "food", "other"]
TAG_LABELS = {
    "ai": "AI", "investment": "Investment", "politics": "Politics",
    "psychology": "Psychology", "food": "Food", "other": "Other",
}


def platform_of(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.").removeprefix("m.")
    if "instagram" in host:
        return "instagram"
    if "facebook" in host or "fb.watch" in host:
        return "facebook"
    return "other"


def _flatten(rec: dict) -> dict:
    recipe = rec.get("recipe") or {}
    return {
        "received_at": rec.get("received_at", ""),
        "shortcode": rec.get("shortcode", ""),
        "platform": platform_of(rec.get("url", "")),
        "url": rec.get("url", ""),
        "author": rec.get("author", ""),
        "tag": rec.get("tag", ""),
        "title": rec.get("title", ""),
        "one_liner": rec.get("one_liner", ""),
        "caption": rec.get("caption", ""),
        "key_points": " | ".join(rec.get("key_points") or []),
        "transcript": rec.get("transcript", ""),
        "has_video": "yes" if rec.get("has_video") else "no",
        "image_count": rec.get("image_count", 0),
        "recipe_ingredients": " | ".join(recipe.get("ingredients") or []),
        "recipe_instructions": " | ".join(recipe.get("instructions") or []),
        "recipe_prep_time": recipe.get("prep_time") or "",
        "recipe_servings": recipe.get("servings") or "",
        "sent_in_newsletter": rec.get("sent_in_newsletter") or "",
    }


def load_all() -> list[dict]:
    records = []
    for path in sorted(REELS_DIR.glob("*.json")):
        records.append(json.loads(path.read_text()))
    # Newest first
    records.sort(key=lambda r: r.get("received_at", ""), reverse=True)
    return records


def rebuild() -> None:
    REELS_DIR.mkdir(parents=True, exist_ok=True)
    records = load_all()
    _write_csv(records)
    _write_index(records)


def _write_csv(records: list[dict]) -> None:
    rows = [_flatten(r) for r in records]
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _write_index(records: list[dict]) -> None:
    grouped: dict[str, list[dict]] = {t: [] for t in TAG_ORDER}
    for r in records:
        grouped.setdefault(r.get("tag") or "other", []).append(r)

    lines = [
        "# Reel Archive Index",
        "",
        f"{len(records)} post(s) archived. Auto-generated from `data/reels/*.json`.",
        "",
    ]
    for tag in TAG_ORDER:
        bucket = grouped.get(tag) or []
        if not bucket:
            continue
        lines.append(f"## {TAG_LABELS[tag]} ({len(bucket)})")
        lines.append("")
        lines.append("| Date | Title | Author | Link |")
        lines.append("|---|---|---|---|")
        for r in bucket:
            date = (r.get("received_at") or "")[:10]
            title = (r.get("title") or r.get("one_liner") or "")[:80].replace("|", "\\|")
            author = (r.get("author") or "").replace("|", "\\|")
            url = r.get("url", "")
            lines.append(f"| {date} | {title} | {author} | [watch]({url}) |")
        lines.append("")

    INDEX_PATH.write_text("\n".join(lines))


if __name__ == "__main__":
    rebuild()
    print(f"Wrote {CSV_PATH.relative_to(ROOT)} and {INDEX_PATH.relative_to(ROOT)}")
