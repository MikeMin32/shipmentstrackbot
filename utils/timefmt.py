"""UTC datetime helpers for EDD and reminders."""

from __future__ import annotations

from datetime import datetime, timezone

UTC_INPUT_FORMAT = "%Y-%m-%d %H:%M"
UTC_DISPLAY_FORMAT = "%Y-%m-%d %H:%M"
# Machine-readable ISO 8601 UTC storage
UTC_STORE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

INVALID_UTC_DATETIME_MESSAGE = (
    "❌ Invalid date/time format.\n\n"
    "Please use:\n"
    "<code>YYYY-MM-DD HH:MM</code>\n\n"
    "Example:\n"
    "<code>2026-08-09 18:00</code>"
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso() -> str:
    return to_store(now_utc())


def parse_utc_datetime(text: str) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM' strictly as UTC (timezone-aware)."""
    naive = datetime.strptime(text.strip(), UTC_INPUT_FORMAT)
    return naive.replace(tzinfo=timezone.utc)


def to_store(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(UTC_STORE_FORMAT)


def try_parse_stored(value: str | None) -> datetime | None:
    """Parse stored datetime values; return None for legacy free-text."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    # Preferred ISO forms
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except ValueError:
            pass

    for fmt in (
        UTC_STORE_FORMAT,
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        UTC_INPUT_FORMAT,
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def format_utc_display(value: str | None, *, empty: str = "—") -> str:
    """
    Display stored value as 'YYYY-MM-DD HH:MM UTC'.
    Legacy unparseable free-text is shown unchanged (no invented date).
    """
    if value is None:
        return empty
    raw = str(value).strip()
    if not raw:
        return empty
    dt = try_parse_stored(raw)
    if dt is None:
        return raw
    return f"{dt.strftime(UTC_DISPLAY_FORMAT)} UTC"


def normalize_stored_utc(value: str | None) -> str | None:
    """If value is a known datetime form, rewrite to ISO UTC; else leave as-is."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    dt = try_parse_stored(raw)
    if dt is None:
        return raw
    return to_store(dt)


# Backwards-compatible aliases used by older call sites
REMINDER_INPUT_FORMAT = UTC_INPUT_FORMAT


def parse_reminder_utc(text: str) -> datetime:
    return parse_utc_datetime(text)
