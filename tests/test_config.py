from __future__ import annotations

import pytest

from config import load_config


def test_invalid_allowed_user_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111, not-an-id")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("DEV_AUTH_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="non-integer"):
        load_config()


def test_dev_auth_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEV_TELEGRAM_USER_ID", "111")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    config = load_config()
    assert config.is_production
    assert config.dev_auth_enabled is False
    assert config.cors_origins == ()


def test_unknown_environment_is_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEV_TELEGRAM_USER_ID", "111")
    config = load_config()
    assert config.environment == "production"
    assert config.dev_auth_enabled is False


def test_empty_allowed_user_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", " , , ")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("DEV_AUTH_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="did not contain any valid user IDs"):
        load_config()


def test_allowed_user_ids_strips_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", " 111 , 222 ")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("DEV_AUTH_ENABLED", raising=False)
    config = load_config()
    assert config.allowed_user_ids == frozenset({111, 222})


def test_invalid_init_data_max_age(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("ALLOWED_USER_IDS", "111")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("INIT_DATA_MAX_AGE_SECONDS", "nope")
    monkeypatch.delenv("DEV_AUTH_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="INIT_DATA_MAX_AGE_SECONDS"):
        load_config()
