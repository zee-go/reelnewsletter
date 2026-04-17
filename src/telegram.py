from __future__ import annotations

import os

import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
BASE = f"https://api.telegram.org/bot{TOKEN}"


def get_updates(offset: int | None = None, timeout: int = 0) -> list[dict]:
    params: dict = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(f"{BASE}/getUpdates", params=params, timeout=timeout + 30)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getUpdates failed: {data}")
    return data["result"]


def send_message(chat_id: int | str, text: str, *, disable_web_preview: bool = True) -> None:
    r = requests.post(
        f"{BASE}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_preview,
        },
        timeout=30,
    )
    r.raise_for_status()
