"""Application configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    allowed_user_ids: frozenset[int]
    database_path: Path
    app_timezone: str


def _parse_allowed_user_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError as exc:
            raise RuntimeError(
                f"ALLOWED_USER_IDS contains a non-integer value: {part!r}"
            ) from exc
    return frozenset(ids)


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    allowed_raw = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not allowed_raw:
        raise RuntimeError(
            "ALLOWED_USER_IDS is not set. Provide a comma-separated list of Telegram user IDs."
        )

    allowed = _parse_allowed_user_ids(allowed_raw)
    if not allowed:
        raise RuntimeError("ALLOWED_USER_IDS did not contain any valid user IDs.")

    db_path = Path(os.getenv("DATABASE_PATH", "./data/shipments.db")).expanduser()
    app_timezone = os.getenv("APP_TIMEZONE", "UTC").strip() or "UTC"
    try:
        ZoneInfo(app_timezone)
    except Exception as exc:
        raise RuntimeError(f"Invalid APP_TIMEZONE: {app_timezone}") from exc

    return Config(
        bot_token=token,
        allowed_user_ids=allowed,
        database_path=db_path,
        app_timezone=app_timezone,
    )
