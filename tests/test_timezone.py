from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from api.main import create_app
from tests.conftest import make_config


def test_delivered_date_uses_app_timezone(tmp_path: Path) -> None:
    tz_name = "Pacific/Kiritimati"
    config = make_config(tmp_path, app_timezone=tz_name)
    app = create_app(config)
    with TestClient(app) as client:
        account = client.post("/api/accounts", json={"name": "TZ"}).json()
        shipment = client.post(
            "/api/shipments",
            json={"account_id": account["id"], "country": "DE", "clone": "Oner"},
        ).json()
        completed = client.post(f"/api/shipments/{shipment['id']}/complete")
        assert completed.status_code == 200
        expected = datetime.now(ZoneInfo(tz_name)).date().isoformat()
        assert completed.json()["delivered_date"] == expected
