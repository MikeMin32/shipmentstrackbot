"""Telegram Mini App initData validation.

The frontend must send Telegram.WebApp.initData. This module validates the
HMAC signature using the bot token and returns the authenticated user.
initDataUnsafe is never trusted for authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)


class InitDataError(Exception):
    """Raised when initData is missing, malformed, or has an invalid signature."""


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
    now: int | None = None,
) -> TelegramUser:
    """Validate Telegram Mini App initData and return the authenticated user.

    Algorithm (Telegram WebApp docs):
    1. Parse the query-string payload.
    2. Separate the hash from the remaining fields.
    3. Build data_check_string from sorted key=value pairs joined by newlines.
    4. secret_key = HMAC_SHA256(bot_token, key="WebAppData")
    5. computed_hash = HMAC_SHA256(data_check_string, key=secret_key)
    6. Compare hashes in constant time.
    7. Reject stale auth_date values.
    """
    if not init_data or not init_data.strip():
        raise InitDataError("Missing Telegram initData")

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True, keep_blank_values=True))
    except ValueError as exc:
        raise InitDataError("Malformed Telegram initData") from exc

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("Telegram initData is missing hash")
    if len(received_hash) != 64 or any(ch not in "0123456789abcdef" for ch in received_hash.lower()):
        logger.warning("Telegram initData hash is not a 64-char hex digest")
        raise InitDataError("Invalid Telegram initData signature")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash.lower()):
        logger.warning("Telegram initData signature mismatch")
        raise InitDataError("Invalid Telegram initData signature")

    auth_date_raw = pairs.get("auth_date")
    if not auth_date_raw:
        raise InitDataError("Telegram initData is missing auth_date")
    try:
        auth_date = int(auth_date_raw)
    except ValueError as exc:
        raise InitDataError("Telegram initData has invalid auth_date") from exc

    current = int(now if now is not None else time.time())
    if max_age_seconds > 0 and current - auth_date > max_age_seconds:
        raise InitDataError("Telegram initData has expired")
    if auth_date > current + 60:
        raise InitDataError("Telegram initData auth_date is in the future")

    user_raw = pairs.get("user")
    if not user_raw:
        raise InitDataError("Telegram initData is missing user")
    try:
        payload = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("Telegram initData user payload is invalid") from exc

    try:
        user_id = int(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InitDataError("Telegram initData user id is invalid") from exc

    first_name = str(payload.get("first_name") or "")
    last_name = payload.get("last_name")
    username = payload.get("username")
    language_code = payload.get("language_code")
    return TelegramUser(
        id=user_id,
        first_name=first_name,
        last_name=str(last_name) if last_name else None,
        username=str(username) if username else None,
        language_code=str(language_code) if language_code else None,
    )


def extract_init_data(authorization: str | None, x_init_data: str | None) -> str | None:
    """Read initData from Authorization: tma <data> or X-Telegram-Init-Data."""
    if authorization:
        scheme, _, remainder = authorization.partition(" ")
        if scheme.lower() == "tma" and remainder.strip():
            return remainder.strip()
    if x_init_data and x_init_data.strip():
        return x_init_data.strip()
    return None
