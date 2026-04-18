"""Render the public archive site from JSON records. Output to site/_dist/."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
REELS_DIR = ROOT / "data" / "reels"
SITE_DIR = ROOT / "site"
TEMPLATES = SITE_DIR / "templates"
STATIC_SRC = SITE_DIR / "static"
DIST = SITE_DIR / "_dist"

BASE_PATH = os.environ.get("SITE_BASE_PATH", "/").rstrip("/") + "/"

TAG_ORDER = ["ai", "investment", "politics", "psychology", "food", "other"]
TAG_LABELS = {
    "ai": "AI", "investment": "Investment", "politics": "Politics",
    "psychology": "Psychology", "food": "Food", "other": "Other",
}


def url_for(name: str, **kwargs) -> str:
    if name == "index":
        return BASE_PATH
    if name == "archive":
        return f"{BASE_PATH}archive/"
    if name == "search":
        return f"{BASE_PATH}search/"
    if name == "tag":
        return f"{BASE_PATH}tag/{kwargs['tag']}/"
    if name == "reel":
        return f"{BASE_PATH}reel/{kwargs['shortcode']}/"
    if name == "week":
        return f"{BASE_PATH}week/{kwargs['week']}/"
    raise ValueError(f"unknown route: {name}")


def static(path: str) -> str:
    return f"{BASE_PATH}{path.lstrip('/')}"


def _load_records() -> list[dict]:
    records = []
    for p in sorted(REELS_DIR.glob("*.json")):
        rec = json.loads(p.read_text())
        records.append(rec)
    records.sort(key=lambda r: r.get("received_at", ""), reverse=True)
    return records


def _week_key(iso_dt: str) -> str:
    """Monday of the week that contains this date, ISO format YYYY-MM-DD."""
    dt = datetime.fromisoformat(iso_dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return monday.date().isoformat()


def _format_week_label(week_id: str) -> str:
    dt = datetime.fromisoformat(week_id)
    return dt.strftime("%B %d, %Y")


def _tag_stats(records: list[dict]) -> list[dict]:
    counts = {t: 0 for t in TAG_ORDER}
    for r in records:
        counts[r.get("tag") or "other"] = counts.get(r.get("tag") or "other", 0) + 1
    return [
        {"slug": t, "label": TAG_LABELS[t], "count": counts.get(t, 0)}
        for t in TAG_ORDER
        if counts.get(t, 0) > 0
    ]


def _week_stats(records: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for r in records:
        if not r.get("received_at"):
            continue
        k = _week_key(r["received_at"])
        buckets.setdefault(k, []).append(r)
    return [
        {"id": k, "label": _format_week_label(k), "count": len(v), "posts": v}
        for k, v in sorted(buckets.items(), reverse=True)
    ]


def _write(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)


def build() -> None:
    records = _load_records()
    tags = _tag_stats(records)
    weeks = _week_stats(records)

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(url=url_for, static=static)

    shared = {
        "tags": tags,
        "total_posts": len(records),
    }

    # Home
    _write(
        DIST / "index.html",
        env.get_template("home.html").render(
            page="home",
            recent=records[:10],
            weeks=weeks[:6],
            **shared,
        ),
    )

    # Archive (all weeks)
    _write(
        DIST / "archive" / "index.html",
        env.get_template("archive.html").render(
            page="archive",
            weeks=weeks,
            **shared,
        ),
    )

    # Search
    _write(
        DIST / "search" / "index.html",
        env.get_template("search.html").render(page="search", **shared),
    )

    # Tags
    for tag in tags:
        tag_posts = [r for r in records if (r.get("tag") or "other") == tag["slug"]]
        _write(
            DIST / "tag" / tag["slug"] / "index.html",
            env.get_template("tag.html").render(
                page="tag",
                active_tag=tag["slug"],
                label=tag["label"],
                posts=tag_posts,
                **shared,
            ),
        )

    # Individual reels
    for r in records:
        if not r.get("shortcode"):
            continue
        _write(
            DIST / "reel" / r["shortcode"] / "index.html",
            env.get_template("reel.html").render(page="reel", r=r, **shared),
        )

    # Weeks
    for w in weeks:
        _write(
            DIST / "week" / w["id"] / "index.html",
            env.get_template("week.html").render(page="week", week=w, **shared),
        )

    # Copy static assets
    if STATIC_SRC.exists():
        for item in STATIC_SRC.iterdir():
            dst = DIST / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)

    # .nojekyll so GH Pages doesn't try to Jekyll-process the output
    (DIST / ".nojekyll").write_text("")

    print(f"Built {len(records)} posts across {len(tags)} tags and {len(weeks)} weeks.")
    print(f"Output: {DIST}")


if __name__ == "__main__":
    build()
