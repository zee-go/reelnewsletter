"""One-off utility: re-tag existing records using the current tagger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from claude_client import tag_reel

ROOT = Path(__file__).resolve().parent.parent
REELS_DIR = ROOT / "data" / "reels"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="specific JSON paths; defaults to all")
    parser.add_argument("--only-tag", help="only re-tag records currently tagged as X")
    args = parser.parse_args()

    paths = [Path(p) for p in args.files] if args.files else sorted(REELS_DIR.glob("*.json"))
    if not paths:
        print("No records to retag.")
        return 0

    for path in paths:
        rec = json.loads(path.read_text())
        if args.only_tag and rec.get("tag") != args.only_tag:
            continue
        print(f"Retagging {path.name} (was {rec.get('tag')}) ...", flush=True)
        tagged = tag_reel(
            caption=rec.get("caption", ""),
            transcript=rec.get("transcript", ""),
            url=rec["url"],
            images=None,  # already processed; skip re-downloading
        )
        rec["tag"] = tagged.tag
        rec["title"] = tagged.title
        rec["one_liner"] = tagged.one_liner
        rec["key_points"] = tagged.key_points
        rec["recipe"] = tagged.recipe.model_dump() if tagged.recipe else None
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        print(f"  → {rec['tag']}: {rec['one_liner']}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
