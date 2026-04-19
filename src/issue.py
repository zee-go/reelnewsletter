"""Editorial rules for a weekly issue: category priority + per-issue item limit.

Used by both the site builder and the newsletter composer so the "issue" shown
on zeeweekly.com and the issue sent by email agree on what's in-band and what's
overflow for the week.
"""
from __future__ import annotations

ISSUE_LIMIT = 10

# Tiers run highest priority first. Any tag not listed falls into the lowest tier.
PRIORITY_TIERS: list[list[str]] = [
    ["ai", "marketing"],
    ["investment", "politics"],
    ["psychology", "fitness", "food", "other"],
]


def _tier_map() -> dict[str, int]:
    m: dict[str, int] = {}
    for i, tags in enumerate(PRIORITY_TIERS):
        for t in tags:
            m[t] = i
    return m


def cut_for_issue(posts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split posts into (issue, backlog) by PRIORITY_TIERS then recency."""
    tier = _tier_map()
    lowest = len(PRIORITY_TIERS)
    buckets: dict[int, list[dict]] = {}
    for r in posts:
        t = tier.get(r.get("tag") or "other", lowest)
        buckets.setdefault(t, []).append(r)
    ordered: list[dict] = []
    for i in sorted(buckets.keys()):
        ordered.extend(
            sorted(buckets[i], key=lambda r: r.get("received_at", ""), reverse=True)
        )
    return ordered[:ISSUE_LIMIT], ordered[ISSUE_LIMIT:]
