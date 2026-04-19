from __future__ import annotations

import base64
import io
from typing import Literal

import anthropic
from PIL import Image
from pydantic import BaseModel, Field

from prompts import NEWSLETTER_SYSTEM_PROMPT, TAG_SYSTEM_PROMPT

_client = anthropic.Anthropic()

# Vision-token cost grows with pixel count. Instagram photos are often 2000×2000+;
# for classification we get the same signal from a 1024px downscale.
VISION_MAX_DIM = 1024
VISION_JPEG_QUALITY = 82


def _resize_for_vision(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Downscale + re-encode to keep Vision input cheap. Returns (bytes, media_type)."""
    try:
        img = Image.open(io.BytesIO(data))
        if max(img.size) <= VISION_MAX_DIM and media_type == "image/jpeg":
            return data, media_type
        img = img.convert("RGB") if img.mode not in ("RGB", "L") else img
        img.thumbnail((VISION_MAX_DIM, VISION_MAX_DIM), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:  # noqa: BLE001 — corrupted image, fall through to original bytes
        print(f"  [vision] resize failed ({e}); sending original.")
        return data, media_type


def _log_usage(label: str, usage) -> None:
    """Print token accounting so we can spot silent cache invalidation or cost spikes."""
    if usage is None:
        return
    input_t = getattr(usage, "input_tokens", 0) or 0
    output_t = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_note = ""
    if cache_read or cache_create:
        billable_in = input_t  # fresh tokens this call, excluding cached
        cache_note = f" · cache_read={cache_read} cache_create={cache_create}"
        if cache_read == 0 and cache_create > 0:
            cache_note += " (MISS — fresh write)"
        elif cache_read > 0:
            cache_note += " (HIT)"
    else:
        billable_in = input_t
    print(f"  [usage:{label}] in={billable_in} out={output_t}{cache_note}", flush=True)

Tag = Literal["ai", "marketing", "investment", "politics", "psychology", "fitness", "food", "other"]


class Recipe(BaseModel):
    ingredients: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    prep_time: str | None = None
    servings: str | None = None


class ReelTag(BaseModel):
    tag: Tag
    title: str = Field(max_length=80)
    one_liner: str = Field(max_length=200)
    key_points: list[str] = Field(min_length=1, max_length=4)
    recipe: Recipe | None = None


def tag_reel(
    caption: str,
    transcript: str,
    url: str,
    images: list[tuple[bytes, str]] | None = None,
) -> ReelTag:
    """Tag a post. `images` is a list of (bytes, media_type) tuples for Claude vision."""
    blocks: list[dict] = []
    for data, media_type in images or []:
        data, media_type = _resize_for_vision(data, media_type)
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(data).decode(),
            },
        })

    text = (
        f"URL: {url}\n\n"
        f"Caption:\n{caption or '(none)'}\n\n"
        f"Transcript:\n{transcript or '(none — this is a photo/image post, analyze the images above)'}"
    )
    blocks.append({"type": "text", "text": text})

    response = _client.messages.parse(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": TAG_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": blocks}],
        output_format=ReelTag,
    )
    _log_usage("tag", getattr(response, "usage", None))
    return response.parsed_output


def compose_week_theme(posts: list[dict]) -> str:
    """One-line editorial headline for a week, synthesized from its posts. Uses Haiku for cost."""
    if not posts:
        return "The reels, rewound."
    lines = []
    for r in posts:
        tag = r.get("tag", "other")
        title = (r.get("title") or r.get("one_liner", ""))[:80]
        lines.append(f"[{tag}] {title}")
    user = (
        f"Here are this week's {len(posts)} saved posts:\n\n"
        + "\n".join(lines)
        + "\n\nWrite one short editorial headline (6–10 words) that names the dominant theme "
        "or tension of the week. Be specific, a little witty. No quotes, no trailing period, "
        "no 'this week' filler — just the headline."
    )
    response = _client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=80,
        messages=[{"role": "user", "content": user}],
    )
    _log_usage("theme", getattr(response, "usage", None))
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text.strip('"').strip("'").rstrip(".")


def compose_newsletter(reels: list[dict], week_label: str) -> str:
    """Compose a weekly newsletter HTML fragment from a list of reel records."""
    reel_blocks = []
    for r in reels:
        block = (
            "---\n"
            f"tag: {r['tag']}\n"
            f"title: {r.get('title') or r.get('one_liner', '')[:60]}\n"
            f"url: {r['url']}\n"
            f"one_liner: {r.get('one_liner', '')}\n"
            f"key_points: {r.get('key_points', [])}\n"
            f"author: {r.get('author') or '(unknown)'}\n"
        )
        if r.get("recipe"):
            rec = r["recipe"]
            block += (
                f"recipe:\n"
                f"  ingredients: {rec.get('ingredients', [])}\n"
                f"  instructions: {rec.get('instructions', [])}\n"
                f"  prep_time: {rec.get('prep_time') or '(none)'}\n"
                f"  servings: {rec.get('servings') or '(none)'}\n"
            )
        reel_blocks.append(block)
    user_content = (
        f"Compose this week's newsletter. Week: {week_label}. "
        f"{len(reels)} posts were saved.\n\n"
        + "\n".join(reel_blocks)
    )

    with _client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=32000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=[
            {
                "type": "text",
                "text": NEWSLETTER_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        final = stream.get_final_message()

    _log_usage("newsletter", getattr(final, "usage", None))
    return "".join(b.text for b in final.content if b.type == "text").strip()
