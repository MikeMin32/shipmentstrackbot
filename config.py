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
    mini_app_url: str | None
    app_timezone: str
    api_host: str
    api_port: int
    environment: str
    dev_auth_enabled: bool
    dev_telegram_user_id: int | None
    enable_legacy_bot_ui: bool
    frontend_dist: Path | None
    cors_origins: tuple[str, ...]
    init_data_max_age_seconds: int

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def mini_app_url_normalized(self) -> str | None:
        if not self.mini_app_url:
            return None
        return self.mini_app_url.rstrip("/")


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


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


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
    mini_app_url = os.getenv("MINI_APP_URL", "").strip() or None
    app_timezone = os.getenv("APP_TIMEZONE", "UTC").strip() or "UTC"
    try:
        ZoneInfo(app_timezone)
    except Exception as exc:
        raise RuntimeError(f"Invalid APP_TIMEZONE: {app_timezone}") from exc

    environment = os.getenv("ENVIRONMENT", "production").strip().lower() or "production"
    if environment not in {"production", "development", "test"}:
        logger.error("Unknown ENVIRONMENT=%r; treating as production", environment)
        environment = "production"

    dev_auth_requested = _parse_bool(os.getenv("DEV_AUTH_ENABLED"), default=False)
    dev_user_raw = os.getenv("DEV_TELEGRAM_USER_ID", "").strip()
    dev_telegram_user_id = int(dev_user_raw) if dev_user_raw else None

    # Dev auth must never activate in production, even if the flag is set.
    dev_auth_enabled = False
    if dev_auth_requested:
        if environment == "production":
            logger.error(
                "DEV_AUTH_ENABLED is set but ENVIRONMENT=production; ignoring dev auth bypass"
            )
        else:
            if dev_telegram_user_id is None:
                raise RuntimeError(
                    "DEV_AUTH_ENABLED is true but DEV_TELEGRAM_USER_ID is not set."
                )
            if dev_telegram_user_id not in allowed:
                raise RuntimeError(
                    "DEV_TELEGRAM_USER_ID must be included in ALLOWED_USER_IDS."
                )
            dev_auth_enabled = True
            logger.warning(
                "DEV AUTH IS ACTIVE (environment=%s, user_id=%s). "
                "This bypasses Telegram initData validation and must never be used in production.",
                environment,
                dev_telegram_user_id,
            )

    frontend_raw = os.getenv("FRONTEND_DIST", "").strip()
    frontend_dist = Path(frontend_raw).expanduser() if frontend_raw else Path("./frontend/dist")
    if not frontend_dist.is_absolute():
        frontend_dist = Path.cwd() / frontend_dist

    cors_raw = os.getenv("CORS_ORIGINS")
    if cors_raw is None:
        cors_origins = (
            ()
            if environment == "production"
            else ("http://localhost:5173", "http://127.0.0.1:5173")
        )
    else:
        cors_origins = _parse_csv(cors_raw)
    max_age_raw = os.getenv("INIT_DATA_MAX_AGE_SECONDS", "86400").strip()
    try:
        init_data_max_age_seconds = int(max_age_raw)
    except ValueError as exc:
        raise RuntimeError("INIT_DATA_MAX_AGE_SECONDS must be an integer") from exc
    if init_data_max_age_seconds <= 0:
        raise RuntimeError("INIT_DATA_MAX_AGE_SECONDS must be a positive integer")

    return Config(
        bot_token=token,
        allowed_user_ids=allowed,
        database_path=db_path,
        mini_app_url=mini_app_url,
        app_timezone=app_timezone,
        api_host=os.getenv("API_HOST", "127.0.0.1").strip() or "127.0.0.1",
        api_port=int(os.getenv("API_PORT", "8000").strip() or "8000"),
        environment=environment,
        dev_auth_enabled=dev_auth_enabled,
        dev_telegram_user_id=dev_telegram_user_id,
        enable_legacy_bot_ui=_parse_bool(os.getenv("ENABLE_LEGACY_BOT_UI"), default=False),
        frontend_dist=frontend_dist,
        cors_origins=cors_origins,
        init_data_max_age_seconds=init_data_max_age_seconds,
    )
