"""Append reel records to a Google Sheet. Gracefully no-ops if credentials aren't configured."""
from __future__ import annotations

import json
import os
from typing import Any

from csv_export import COLUMNS, _flatten

_HEADER = COLUMNS  # reuse canonical column order


def _get_sheet() -> Any | None:
    """Open the target sheet via service account. Return None if not configured."""
    sheet_id = os.environ.get("GSHEET_ID", "").strip()
    sa_json = os.environ.get("GSHEET_SERVICE_ACCOUNT_JSON", "").strip()
    if not sheet_id or not sa_json:
        return None

    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(
        json.loads(sa_json),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    return sh.sheet1  # first worksheet


def _ensure_header(ws) -> None:
    existing = ws.row_values(1)
    if existing != _HEADER:
        ws.update("A1", [_HEADER])


def append(record: dict) -> bool:
    """Append a record as a new row. Returns True if appended, False if skipped (dupe or not configured)."""
    ws = _get_sheet()
    if ws is None:
        print("  sheets_export: GSHEET_ID / GSHEET_SERVICE_ACCOUNT_JSON not set — skipping", flush=True)
        return False

    _ensure_header(ws)

    shortcode = record.get("shortcode", "")
    if shortcode:
        # Column B is shortcode. Pull just that column to dedupe.
        existing_shortcodes = ws.col_values(2)[1:]  # skip header
        if shortcode in existing_shortcodes:
            print(f"  sheets_export: {shortcode} already in sheet — skipping", flush=True)
            return False

    row = _flatten(record)
    ws.append_row(
        [row[c] for c in _HEADER],
        value_input_option="USER_ENTERED",
    )
    print(f"  sheets_export: appended {shortcode}", flush=True)
    return True
