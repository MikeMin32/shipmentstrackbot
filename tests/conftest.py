from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from config import Config


def make_config(tmp_path: Path, **overrides: object) -> Config:
    values: dict = {
        "bot_token": "123456:TESTTOKEN",
        "allowed_user_ids": frozenset({111, 222}),
        "database_path": tmp_path / "shipments.db",
        "mini_app_url": "https://tracker.example.test",
        "app_timezone": "UTC",
        "api_host": "127.0.0.1",
        "api_port": 8000,
        "environment": "test",
        "dev_auth_enabled": True,
        "dev_telegram_user_id": 111,
        "enable_legacy_bot_ui": False,
        "frontend_dist": tmp_path / "missing-frontend",
        "cors_origins": (),
        "init_data_max_age_seconds": 86400,
    }
    values.update(overrides)
    return Config(**values)  # type: ignore[arg-type]


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return make_config(tmp_path)


@pytest.fixture
def client(config: Config) -> TestClient:
    app = create_app(config)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def prod_config(tmp_path: Path) -> Config:
    return make_config(
        tmp_path,
        environment="production",
        dev_auth_enabled=False,
        dev_telegram_user_id=None,
    )


@pytest.fixture
def prod_client(prod_config: Config) -> TestClient:
    app = create_app(prod_config)
    with TestClient(app) as test_client:
        yield test_client
