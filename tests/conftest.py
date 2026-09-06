from __future__ import annotations

from pathlib import Path

from config import Config


def make_config(tmp_path: Path, **overrides: object) -> Config:
    values: dict = {
        "bot_token": "123456:TESTTOKEN",
        "allowed_user_ids": frozenset({111, 222}),
        "database_path": tmp_path / "shipments.db",
        "app_timezone": "UTC",
        "edd_reminder_hour": 9,
    }
    values.update(overrides)
    return Config(**values)  # type: ignore[arg-type]
