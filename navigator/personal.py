"""Parent-entered information, stored only in a local file.

Nothing here is cached, logged or sent anywhere. The file lives in
local_data/, which is excluded from version control.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "local_data"
DATA_FILE = DATA_DIR / "my_child.json"

DATE_FIELDS = [
    "paed_referral_date",
    "paed_accepted_date",
    "autism_referral_date",
    "autism_accepted_date",
]
TEXT_FIELDS = ["current_stage", "contact_notes"]


def _to_jsonable(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in DATE_FIELDS:
        value = record.get(key)
        out[key] = value.isoformat() if isinstance(value, date) else None
    for key in TEXT_FIELDS:
        out[key] = record.get(key) or ""
    out["checklist"] = {k: sorted(v) for k, v in (record.get("checklist") or {}).items()}
    out["saved_at"] = datetime.now().isoformat(timespec="seconds")
    return out


def _from_jsonable(data: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for key in DATE_FIELDS:
        value = data.get(key)
        try:
            record[key] = date.fromisoformat(value) if value else None
        except ValueError:
            record[key] = None
    for key in TEXT_FIELDS:
        record[key] = str(data.get(key) or "")
    record["checklist"] = {k: set(v) for k, v in (data.get("checklist") or {}).items()}
    record["saved_at"] = data.get("saved_at")
    return record


def load(path: Path = DATA_FILE) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return _from_jsonable(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return None


def save(record: dict[str, Any], path: Path = DATA_FILE) -> str:
    """Write the record atomically, readable only by this user. Returns saved_at."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _to_jsonable(record)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp, path)
    return payload["saved_at"]


def delete(path: Path = DATA_FILE) -> bool:
    if path.exists():
        path.unlink()
        return True
    return False


def elapsed(start: date, today: date) -> tuple[int, int, int]:
    """(total days, whole weeks, remaining days) from start to today."""
    days = (today - start).days
    return days, days // 7, days % 7


def describe_elapsed(start: date, today: date) -> str:
    days, weeks, rest = elapsed(start, today)
    if days < 0:
        return "This date is in the future."
    week_text = f"{weeks} week{'s' if weeks != 1 else ''}"
    day_text = f"{rest} day{'s' if rest != 1 else ''}"
    return f"{week_text} and {day_text} ({days} days)"


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(start.day, days_in_month))
