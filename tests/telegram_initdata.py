"""Independent Telegram Mini App initData builder for tests.

Implements the algorithm published in Telegram's WebApp docs. It does not import
HMAC helpers from api.auth — those are the code under test.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode


def build_init_data(
    user_id: int,
    bot_token: str,
    *,
    auth_date: int | None = None,
    first_name: str = "Ada",
    username: str = "ada",
    extra_user: dict | None = None,
    omit_hash: bool = False,
    tamper_hash: bool = False,
    user_json: str | None = None,
) -> str:
    if user_json is None:
        payload = {"id": user_id, "first_name": first_name, "username": username}
        if extra_user:
            payload.update(extra_user)
        user_json = json.dumps(payload, separators=(",", ":"))
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAEtest",
        "user": user_json,
    }
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    if tamper_hash:
        digest = "0" * 64
    if omit_hash:
        return urlencode(fields)
    return urlencode({**fields, "hash": digest})
