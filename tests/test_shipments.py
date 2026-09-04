from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_create_update_complete_archive_restore(client) -> None:
    account = client.post("/api/accounts", json={"name": "Account A"}).json()
    team = client.post("/api/client-teams", json={"name": "Team Alpha"}).json()

    created = client.post(
        "/api/shipments",
        json={
            "account_id": account["id"],
            "country": "DE",
            "clone": "Oner",
            "client_team_id": team["id"],
            "box_weight": 8.4,
            "status": "preparing",
            "label_creation_date": "2026-09-01",
            "scanned_in_date": "2026-09-02",
            "expected_delivery_date": "2026-09-08",
            "note": "Handle with care",
        },
    )
    assert created.status_code == 201, created.text
    shipment = created.json()
    assert shipment["account"]["name"] == "Account A"
    assert shipment["client_team"]["name"] == "Team Alpha"
    assert shipment["box_weight"] == 8.4
    assert shipment["status"] == "preparing"
    assert shipment["archived"] is False
    assert shipment["delivered_date"] is None

    updated = client.patch(
        f"/api/shipments/{shipment['id']}",
        json={"country": "CA", "clone": "Durston"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "CA : Durston"

    status = client.post(
        f"/api/shipments/{shipment['id']}/status",
        json={"status": "enroute"},
    )
    assert status.status_code == 200
    assert status.json()["status"] == "enroute"

    completed = client.post(f"/api/shipments/{shipment['id']}/complete")
    assert completed.status_code == 200
    body = completed.json()
    assert body["status"] == "delivered"
    assert body["delivered_date"] is not None
    assert body["archived"] is False

    active = client.get("/api/shipments", params={"active_only": True})
    assert all(item["id"] != shipment["id"] for item in active.json()["items"])

    completed_list = client.get("/api/shipments", params={"completed_only": True})
    assert any(item["id"] == shipment["id"] for item in completed_list.json()["items"])

    archived = client.post(f"/api/shipments/{shipment['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert archived.json()["status"] == "delivered"

    archive_list = client.get("/api/shipments", params={"archived": True})
    assert any(item["id"] == shipment["id"] for item in archive_list.json()["items"])

    restored = client.post(f"/api/shipments/{shipment['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["archived"] is False
    assert restored.json()["status"] == "delivered"

    again = client.post(f"/api/shipments/{shipment['id']}/complete")
    assert again.status_code == 200
    assert again.json()["delivered_date"] == body["delivered_date"]

    reverted = client.post(
        f"/api/shipments/{shipment['id']}/status",
        json={"status": "preparing"},
    )
    assert reverted.status_code == 200
    assert reverted.json()["status"] == "preparing"
    assert reverted.json()["delivered_date"] == body["delivered_date"]


def test_active_archive_restore_keeps_status(client) -> None:
    account = client.post("/api/accounts", json={"name": "Ops"}).json()
    shipment = client.post(
        "/api/shipments",
        json={"account_id": account["id"], "country": "DE", "clone": "Oner", "status": "standby"},
    ).json()
    archived = client.post(f"/api/shipments/{shipment['id']}/archive").json()
    assert archived["archived"] is True
    assert archived["status"] == "standby"
    restored = client.post(f"/api/shipments/{shipment['id']}/restore").json()
    assert restored["archived"] is False
    assert restored["status"] == "standby"
    active = client.get("/api/shipments", params={"active_only": True}).json()
    assert any(item["id"] == shipment["id"] for item in active["items"])


def test_invalid_weight_rejected(client) -> None:
    account = client.post("/api/accounts", json={"name": "Heavy"}).json()
    response = client.post(
        "/api/shipments",
        json={
            "account_id": account["id"],
            "country": "DE",
            "clone": "Oner",
            "box_weight": -2,
        },
    )
    assert response.status_code == 400


def test_new_shipment_requires_account(client) -> None:
    response = client.post(
        "/api/shipments",
        json={"country": "DE", "clone": "Oner"},
    )
    assert response.status_code == 422


def test_reminder_rejects_past(client) -> None:
    account = client.post("/api/accounts", json={"name": "Remind"}).json()
    shipment = client.post(
        "/api/shipments",
        json={"account_id": account["id"], "country": "DE", "clone": "Oner"},
    ).json()
    response = client.put(
        f"/api/shipments/{shipment['id']}/reminder",
        json={"remind_at": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 400


def test_history_recorded(client) -> None:
    account = client.post("/api/accounts", json={"name": "Hist"}).json()
    shipment = client.post(
        "/api/shipments",
        json={
            "account_id": account["id"],
            "country": "DE",
            "clone": "Oner",
            "status": "preparing",
        },
    ).json()
    client.post(f"/api/shipments/{shipment['id']}/status", json={"status": "make_label"})
    history = client.get(f"/api/shipments/{shipment['id']}/history").json()
    assert len(history) >= 2
    assert history[-1]["new_status"] == "make_label"


def test_history_no_duplicate_on_same_status(client) -> None:
    account = client.post("/api/accounts", json={"name": "Same"}).json()
    shipment = client.post(
        "/api/shipments",
        json={"account_id": account["id"], "country": "DE", "clone": "Oner", "status": "preparing"},
    ).json()
    before = client.get(f"/api/shipments/{shipment['id']}/history").json()
    client.post(f"/api/shipments/{shipment['id']}/status", json={"status": "preparing"})
    after = client.get(f"/api/shipments/{shipment['id']}/history").json()
    assert len(after) == len(before)


def test_search_by_id_and_filters(client) -> None:
    account = client.post("/api/accounts", json={"name": "SearchAcc"}).json()
    team = client.post("/api/client-teams", json={"name": "SearchTeam"}).json()
    first = client.post(
        "/api/shipments",
        json={
            "account_id": account["id"],
            "country": "DE",
            "clone": "Oner",
            "client_team_id": team["id"],
            "status": "out_for_delivery",
        },
    ).json()
    second = client.post(
        "/api/shipments",
        json={"account_id": account["id"], "country": "CA", "clone": "Durston", "status": "preparing"},
    ).json()
    by_id = client.get("/api/shipments", params={"q": str(first["id"])}).json()
    assert any(item["id"] == first["id"] for item in by_id["items"])
    by_team = client.get("/api/shipments", params={"q": "SearchTeam"}).json()
    assert any(item["id"] == first["id"] for item in by_team["items"])
    by_status = client.get("/api/shipments", params={"status": "out_for_delivery"}).json()
    assert {item["id"] for item in by_status["items"]} == {first["id"]}
    paged = client.get("/api/shipments", params={"limit": 1, "offset": 0}).json()
    assert paged["total"] >= 2
    assert len(paged["items"]) == 1
    page_two = client.get("/api/shipments", params={"limit": 1, "offset": 1}).json()
    assert page_two["items"][0]["id"] != paged["items"][0]["id"]
    assert second["id"] in {paged["items"][0]["id"], page_two["items"][0]["id"]}


def test_dashboard_excludes_archived_and_groups_out_for_delivery(client) -> None:
    account = client.post("/api/accounts", json={"name": "Dash"}).json()
    ofd = client.post(
        "/api/shipments",
        json={"account_id": account["id"], "country": "DE", "clone": "Oner", "status": "out_for_delivery"},
    ).json()
    delivered = client.post(
        "/api/shipments",
        json={"account_id": account["id"], "country": "CA", "clone": "Durston", "status": "preparing"},
    ).json()
    client.post(f"/api/shipments/{delivered['id']}/complete")
    archived = client.post(
        "/api/shipments",
        json={"account_id": account["id"], "country": "LA", "clone": "Le Bon", "status": "enroute"},
    ).json()
    client.post(f"/api/shipments/{archived['id']}/archive")

    dash = client.get("/api/dashboard").json()
    assert dash["counts"]["out_for_delivery"] >= 1
    assert dash["counts"]["enroute"] == 0
    assert all(item["id"] != archived["id"] for item in dash["active"]["in_transit"])
    assert all(item["id"] != archived["id"] for item in dash["active"]["working"])
    assert any(item["id"] == ofd["id"] for item in dash["active"]["in_transit"])
    assert all(item["status"] != "out_for_delivery" for item in dash["active"]["working"])
    assert dash["counts"]["delivered"] >= 1


def test_malformed_edd_rejected_on_create(client) -> None:
    account = client.post("/api/accounts", json={"name": "Dates"}).json()
    response = client.post(
        "/api/shipments",
        json={
            "account_id": account["id"],
            "country": "DE",
            "clone": "Oner",
            "expected_delivery_date": "tomorrow",
        },
    )
    assert response.status_code == 400


def test_reminder_replace_and_complete_cancels(client) -> None:
    account = client.post("/api/accounts", json={"name": "Remind2"}).json()
    shipment = client.post(
        "/api/shipments",
        json={"account_id": account["id"], "country": "DE", "clone": "Oner"},
    ).json()
    first = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    second = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    created = client.put(
        f"/api/shipments/{shipment['id']}/reminder",
        json={"remind_at": first},
    )
    assert created.status_code == 200
    replaced = client.put(
        f"/api/shipments/{shipment['id']}/reminder",
        json={"remind_at": second},
    )
    assert replaced.status_code == 200
    assert replaced.json()["remind_at"] != created.json()["remind_at"]
    active = client.get(f"/api/shipments/{shipment['id']}/reminder").json()
    assert active["reminder"]["id"] == replaced.json()["id"]
    client.post(f"/api/shipments/{shipment['id']}/complete")
    after = client.get(f"/api/shipments/{shipment['id']}/reminder").json()
    assert after["reminder"] is None
    blocked = client.put(
        f"/api/shipments/{shipment['id']}/reminder",
        json={"remind_at": second},
    )
    assert blocked.status_code == 400


def test_missing_shipment_is_404(client) -> None:
    response = client.get("/api/shipments/999999")
    assert response.status_code == 404
    history = client.get("/api/shipments/999999/history")
    assert history.status_code == 404
