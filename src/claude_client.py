from __future__ import annotations

import base64
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from prompts import NEWSLETTER_SYSTEM_PROMPT, TAG_SYSTEM_PROMPT

_client = anthropic.Anthropic()

Tag = Literal["ai", "investment", "politics", "psychology"]


class ReelTag(BaseModel):
    tag: Tag
    title: str = Field(max_length=80)
    one_liner: str = Field(max_length=200)
    key_points: list[str] = Field(min_length=1, max_length=4)


def tag_reel(
    caption: str,
    transcript: str,
    url: str,
    images: list[tuple[bytes, str]] | None = None,
) -> ReelTag:
    """Tag a post. `images` is a list of (bytes, media_type) tuples for Claude vision."""
    blocks: list[dict] = []
    for data, media_type in images or []:
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
    return response.parsed_output


def compose_newsletter(reels: list[dict], week_label: str) -> str:
    """Compose a weekly newsletter HTML fragment from a list of reel records."""
    reel_blocks = []
    for r in reels:
        reel_blocks.append(
            "---\n"
            f"tag: {r['tag']}\n"
            f"title: {r.get('title') or r.get('one_liner', '')[:60]}\n"
            f"url: {r['url']}\n"
            f"one_liner: {r.get('one_liner', '')}\n"
            f"key_points: {r.get('key_points', [])}\n"
            f"author: {r.get('author') or '(unknown)'}\n"
        )
    user_content = (
        f"Compose this week's newsletter. Week: {week_label}. "
        f"{len(reels)} reels were saved.\n\n"
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

    return "".join(b.text for b in final.content if b.type == "text").strip()
