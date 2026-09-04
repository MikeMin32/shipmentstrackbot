"""Date-only helpers for operational shipment fields (YYYY-MM-DD)."""

from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from utils.timefmt import try_parse_stored

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_TIMEZONE = "UTC"


def parse_iso_date(value: str) -> date:
    """Parse a strict YYYY-MM-DD value."""
    raw = value.strip()
    if not ISO_DATE_RE.match(raw):
        raise ValueError("Date must be YYYY-MM-DD")
    return date.fromisoformat(raw)


def to_iso_date(value: date) -> str:
    return value.isoformat()


def today_in_timezone(tz_name: str | None = None) -> date:
    """Application-local 'today' for delivered_date and similar fields."""
    name = (tz_name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(name)
    except Exception as exc:
        raise ValueError(f"Invalid timezone: {name}") from exc
    return datetime.now(tz).date()


def extract_date_component(value: str | None) -> str | None:
    """
    Extract YYYY-MM-DD from a stored value.

    Accepts date-only strings and legacy datetimes. Unparseable free-text
    is returned as None so callers can leave the original value untouched.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if ISO_DATE_RE.match(raw):
        try:
            date.fromisoformat(raw)
        except ValueError:
            return None
        return raw

    dt = try_parse_stored(raw)
    if dt is not None:
        return dt.date().isoformat()
    return None


def coerce_iso_date(value: str | None) -> str | None:
    """Normalize a user/API date to YYYY-MM-DD, or None if empty."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    extracted = extract_date_component(raw)
    if extracted is None:
        raise ValueError("Date must be YYYY-MM-DD")
    return extracted
