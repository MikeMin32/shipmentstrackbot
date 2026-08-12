"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    allowed_user_ids: frozenset[int]
    database_path: Path


def _parse_allowed_user_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
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
    return Config(
        bot_token=token,
        allowed_user_ids=allowed,
        database_path=db_path,
    )
