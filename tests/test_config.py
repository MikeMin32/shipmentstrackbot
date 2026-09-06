from __future__ import annotations

import pytest

from config import load_config


def test_invalid_allowed_user_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111, not-an-id")
    with pytest.raises(RuntimeError, match="non-integer"):
        load_config()


def test_empty_allowed_user_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", " , , ")
    with pytest.raises(RuntimeError, match="did not contain any valid user IDs"):
        load_config()


def test_allowed_user_ids_strips_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", " 111 , 222 ")
    monkeypatch.setenv("APP_TIMEZONE", "UTC")
    config = load_config()
    assert config.allowed_user_ids == frozenset({111, 222})
    assert config.app_timezone == "UTC"
    assert config.edd_reminder_hour == 9


def test_invalid_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111")
    monkeypatch.setenv("APP_TIMEZONE", "Not/AZone")
    with pytest.raises(RuntimeError, match="Invalid APP_TIMEZONE"):
        load_config()


def test_invalid_edd_reminder_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111")
    monkeypatch.setenv("APP_TIMEZONE", "UTC")
    monkeypatch.setenv("EDD_REMINDER_HOUR", "25")
    with pytest.raises(RuntimeError, match="EDD_REMINDER_HOUR"):
        load_config()


def test_missing_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("ALLOWED_USER_IDS", "111")
    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        load_config()
