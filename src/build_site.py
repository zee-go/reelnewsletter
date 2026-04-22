"""Render the public archive site from JSON records. Output to site/_dist/."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from issue import ISSUE_LIMIT, PRIORITY_TIERS, cut_for_issue  # noqa: F401

THEMES_FILE = Path(__file__).resolve().parent.parent / "data" / "themes.json"

ROOT = Path(__file__).resolve().parent.parent
REELS_DIR = ROOT / "data" / "reels"
SITE_DIR = ROOT / "site"
TEMPLATES = SITE_DIR / "templates"
STATIC_SRC = SITE_DIR / "static"
DIST = SITE_DIR / "_dist"

BASE_PATH = os.environ.get("SITE_BASE_PATH", "/").rstrip("/") + "/"

# Optional Google Form email-capture wiring. If both env vars are set, the site
# will post subscribe-form submissions to the Form (which auto-appends to its Sheet).
SUBSCRIBE_FORM_URL = os.environ.get("SUBSCRIBE_FORM_URL", "").strip()
SUBSCRIBE_FORM_ENTRY = os.environ.get("SUBSCRIBE_FORM_EMAIL_ENTRY", "").strip()

TAG_ORDER = ["ai", "marketing", "investment", "politics", "psychology", "fitness", "food", "other"]
TAG_LABELS = {
    "ai": "AI", "marketing": "Marketing", "investment": "Investment", "politics": "Politics",
    "psychology": "Psychology", "fitness": "Fitness", "food": "Food", "other": "Other",
}
TAG_BLURBS = {
    "ai": "What shipped, what broke, what's actually worth the hype.",
    "marketing": "Hooks, pitches, and the quiet psychological heists behind a good campaign.",
    "investment": "Markets, macro, and the ancient art of not setting money on fire.",
    "politics": "Policy, power, and the chessboard nobody asked for.",
    "psychology": "Small experiments on the mushy machine between your ears.",
    "fitness": "Strength, sleep, recovery — the boring stuff that actually works.",
    "food": "Recipes worth stealing and meals worth remembering.",
    "other": "The stragglers, the oddballs, the couldn't-not-save-this pile.",
}

# Small pill descriptors shown under each section header — pure flavor,
# mirrors the infographic inspiration's "collage · craft textures · AI polish".
TAG_PILLS = {
    "ai": ["halftone", "automation", "vibe coding"],
    "marketing": ["hooks", "conversion", "brand"],
    "investment": ["markets", "macro", "patience"],
    "politics": ["power", "policy", "regulation"],
    "psychology": ["habits", "biases", "the mushy machine"],
    "fitness": ["strength", "sleep", "recovery"],
    "food": ["recipes", "kitchen craft", "snacks"],
    "other": ["stragglers", "oddballs", "keepers"],
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


def _platform(url: str) -> str:
    host = urlparse(url or "").netloc.lower().removeprefix("www.").removeprefix("m.")
    if "instagram" in host:
        return "instagram"
    if "facebook" in host or "fb.watch" in host:
        return "facebook"
    return ""


def _load_records() -> list[dict]:
    records = []
    for p in sorted(REELS_DIR.glob("*.json")):
        rec = json.loads(p.read_text())
        rec["platform"] = _platform(rec.get("url", ""))
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


def _sections_for(records: list[dict]) -> list[dict]:
    """Group records by tag into ordered section dicts suitable for the magazine layout."""
    buckets: dict[str, list[dict]] = {t: [] for t in TAG_ORDER}
    for r in records:
        buckets[r.get("tag") or "other"].append(r)
    return [
        {
            "slug": t,
            "label": TAG_LABELS[t],
            "blurb": TAG_BLURBS[t],
            "pills": TAG_PILLS.get(t, []),
            "count": len(buckets[t]),
            "posts": buckets[t],
        }
        for t in TAG_ORDER
        if buckets[t]
    ]


def _week_stats(records: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for r in records:
        if not r.get("received_at"):
            continue
        k = _week_key(r["received_at"])
        buckets.setdefault(k, []).append(r)
    # Sorted oldest-first for issue numbering, then we reverse for display.
    sorted_keys = sorted(buckets.keys())
    weeks = []
    for i, k in enumerate(sorted_keys, start=1):
        all_posts = sorted(buckets[k], key=lambda r: r.get("received_at", ""), reverse=True)
        issue_posts, backlog_posts = cut_for_issue(all_posts)
        weeks.append({
            "id": k,
            "label": _format_week_label(k),
            "count": len(issue_posts),
            "total_count": len(all_posts),
            "backlog_count": len(backlog_posts),
            "posts": issue_posts,
            "backlog": backlog_posts,
            "issue_num": i,
            "sections": _sections_for(issue_posts),
            "subject": _derive_subject(issue_posts),
        })
    return list(reversed(weeks))


def _derive_subject(posts: list[dict]) -> str:
    if not posts:
        return "Weekly digest"
    # Use the highest-ranked (lead) post's title as the issue subject
    return posts[0].get("title") or posts[0].get("one_liner") or "Weekly digest"


def _derive_letter(total_posts: int, tags: list[dict], latest_week: dict | None) -> str:
    if total_posts == 0:
        return ("Nothing in the archive yet. Forward a reel to the bot and it'll land here — "
                "transcribed, tagged, and distilled into Friday's digest.")
    topic_bits = ", ".join(t["label"] for t in tags[:-1])
    if len(tags) > 1:
        topic_bits += f" and {tags[-1]['label']}"
    elif tags:
        topic_bits = tags[0]["label"]
    latest_bit = ""
    if latest_week:
        latest_bit = f" This week leans {latest_week['sections'][0]['label'].lower()}."
    return (
        f"Welcome to the archive. {total_posts} posts saved and counting, across "
        f"{topic_bits}. Everything here started as a reel in my feed, got pulled into "
        f"a Telegram bot, transcribed, and sorted.{latest_bit} Skim by category, browse by week, "
        f"or use search to hunt a specific take."
    )


def _load_themes() -> dict:
    if THEMES_FILE.exists():
        try:
            return json.loads(THEMES_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_themes(themes: dict) -> None:
    THEMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    THEMES_FILE.write_text(json.dumps(themes, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _week_fingerprint(posts: list[dict]) -> str:
    """Stable id for a week's post set — used to invalidate cached themes only when posts change."""
    keys = sorted(p.get("shortcode", "") for p in posts)
    return str(hash(tuple(keys)))


def _resolve_theme(week: dict, themes: dict, generate_if_missing: bool) -> str:
    """Return the theme headline for a week, generating and caching it on first miss."""
    wid = week["id"]
    fp = _week_fingerprint(week["posts"])
    cached = themes.get(wid)
    if cached and cached.get("fingerprint") == fp:
        return cached["headline"]
    if not generate_if_missing:
        return week.get("subject") or "Weekly digest"
    try:
        from claude_client import compose_week_theme
        headline = compose_week_theme(week["posts"])
    except Exception as e:  # noqa: BLE001 — local dev without ANTHROPIC_API_KEY, or network hiccup
        print(f"  [theme] generation failed ({e}); falling back to lead title.")
        return week.get("subject") or "Weekly digest"
    themes[wid] = {"fingerprint": fp, "headline": headline}
    return headline


def _derive_hero_title(latest_week: dict | None) -> str:
    if not latest_week:
        return "The reels, rewound."
    return latest_week.get("theme") or latest_week.get("subject") or "Weekly digest"


def _write(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)


def build() -> None:
    records = _load_records()
    tags = _tag_stats(records)
    weeks = _week_stats(records)
    themes = _load_themes()

    # Resolve theme headline per week. Only the latest week can trigger an API call
    # (older weeks use cache or fall back to subject) — keeps builds cheap and deterministic.
    for i, w in enumerate(weeks):
        w["theme"] = _resolve_theme(w, themes, generate_if_missing=(i == 0))

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

    latest_week = weeks[0] if weeks else None
    shared = {
        "tags": tags,
        "total_posts": len(records),
        "latest_issue_num": latest_week["issue_num"] if latest_week else 1,
        "latest_issue_date": latest_week["label"] if latest_week else "",
        "current_week_label": f"Week of {latest_week['label']}" if latest_week else None,
        "subscribe_form_url": SUBSCRIBE_FORM_URL,
        "subscribe_form_entry": SUBSCRIBE_FORM_ENTRY,
    }

    # Home
    home_sections = _sections_for(
        (latest_week["posts"] if latest_week else records[:10])
    )
    _write(
        DIST / "index.html",
        env.get_template("home.html").render(
            page="home",
            sections_on_home=home_sections,
            weeks=weeks,
            hero_title=_derive_hero_title(latest_week),
            letter=_derive_letter(len(records), tags, latest_week),
            signoff="That's the week. — Z",
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
                blurb=TAG_BLURBS[tag["slug"]],
                pills=TAG_PILLS.get(tag["slug"], []),
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

    _save_themes(themes)

    print(f"Built {len(records)} posts across {len(tags)} tags and {len(weeks)} weeks.")
    print(f"Output: {DIST}")


if __name__ == "__main__":
    build()
