from __future__ import annotations


def test_account_create_and_summary_counts(client) -> None:
    first = client.post("/api/accounts", json={"name": "Account A"})
    second = client.post("/api/accounts", json={"name": "Account B"})
    assert first.status_code == 201
    assert second.status_code == 201
    a_id = first.json()["id"]
    b_id = second.json()["id"]

    for _ in range(2):
        client.post(
            "/api/shipments",
            json={"account_id": a_id, "country": "DE", "clone": "Oner"},
        )
    created = client.post(
        "/api/shipments",
        json={"account_id": b_id, "country": "CA", "clone": "Durston"},
    ).json()
    client.post(f"/api/shipments/{created['id']}/complete")
    client.post(f"/api/shipments/{created['id']}/archive")

    summary = client.get("/api/accounts/summary").json()
    by_name = {row["name"]: row for row in summary}
    assert by_name["Account A"]["total"] == 2
    assert by_name["Account A"]["active"] == 2
    assert by_name["Account B"]["total"] == 1
    assert by_name["Account B"]["active"] == 0


def test_blank_account_name_rejected(client) -> None:
    response = client.post("/api/accounts", json={"name": "   "})
    assert response.status_code in {400, 422}


def test_blank_team_name_rejected(client) -> None:
    response = client.post("/api/client-teams", json={"name": "   "})
    assert response.status_code in {400, 422}
