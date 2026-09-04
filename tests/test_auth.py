from __future__ import annotations

import time

from api.auth import InitDataError, validate_init_data
from tests.telegram_initdata import build_init_data

BOT_TOKEN = "123456:TESTTOKEN"


def test_valid_init_data() -> None:
    init_data = build_init_data(111, BOT_TOKEN)
    user = validate_init_data(init_data, BOT_TOKEN)
    assert user.id == 111
    assert user.first_name == "Ada"


def test_invalid_signature() -> None:
    init_data = build_init_data(111, BOT_TOKEN, tamper_hash=True)
    try:
        validate_init_data(init_data, BOT_TOKEN)
        raise AssertionError("expected InitDataError")
    except InitDataError as exc:
        assert "signature" in str(exc).lower()


def test_missing_hash() -> None:
    init_data = build_init_data(111, BOT_TOKEN, omit_hash=True)
    try:
        validate_init_data(init_data, BOT_TOKEN)
        raise AssertionError("expected InitDataError")
    except InitDataError as exc:
        assert "hash" in str(exc).lower()


def test_malformed_user_json() -> None:
    init_data = build_init_data(111, BOT_TOKEN, user_json="{not-json")
    try:
        validate_init_data(init_data, BOT_TOKEN)
        raise AssertionError("expected InitDataError")
    except InitDataError as exc:
        assert "user" in str(exc).lower()


def test_expired_init_data() -> None:
    init_data = build_init_data(111, BOT_TOKEN, auth_date=int(time.time()) - 100_000)
    try:
        validate_init_data(init_data, BOT_TOKEN, max_age_seconds=60)
        raise AssertionError("expected InitDataError")
    except InitDataError as exc:
        assert "expired" in str(exc).lower()


def test_future_auth_date() -> None:
    init_data = build_init_data(111, BOT_TOKEN, auth_date=int(time.time()) + 3600)
    try:
        validate_init_data(init_data, BOT_TOKEN)
        raise AssertionError("expected InitDataError")
    except InitDataError as exc:
        assert "future" in str(exc).lower()


def test_api_rejects_missing_init_data(prod_client) -> None:
    response = prod_client.get("/api/me")
    assert response.status_code == 401
    shipments = prod_client.get("/api/shipments")
    assert shipments.status_code == 401
    dashboard = prod_client.get("/api/dashboard")
    assert dashboard.status_code == 401
    health = prod_client.get("/api/health")
    assert health.status_code == 200


def test_api_rejects_invalid_signature(prod_client) -> None:
    init_data = build_init_data(111, BOT_TOKEN, tamper_hash=True)
    response = prod_client.get(
        "/api/me",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert response.status_code == 401


def test_api_rejects_unauthorized_user(prod_client) -> None:
    init_data = build_init_data(999, BOT_TOKEN)
    response = prod_client.get(
        "/api/me",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert response.status_code == 403


def test_api_accepts_valid_init_data(prod_client) -> None:
    init_data = build_init_data(111, BOT_TOKEN)
    response = prod_client.get(
        "/api/me",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["id"] == 111
    assert response.json()["dev_auth"] is False


def test_dev_auth_allows_bypass(client) -> None:
    response = client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["dev_auth"] is True
    assert response.json()["user"]["id"] == 111


def test_production_ignores_dev_auth_flag(prod_client) -> None:
    response = prod_client.get("/api/me")
    assert response.status_code == 401


def test_malformed_init_data_rejected(prod_client) -> None:
    response = prod_client.get(
        "/api/me",
        headers={"Authorization": "tma this is not query-string data"},
    )
    assert response.status_code == 401


def test_protected_lookup_routes_require_auth(prod_client) -> None:
    for path in ("/api/statuses", "/api/countries", "/api/clones", "/api/accounts", "/api/client-teams"):
        assert prod_client.get(path).status_code == 401
