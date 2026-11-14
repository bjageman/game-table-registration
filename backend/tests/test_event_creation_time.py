"""Event creation dates are persisted and do not change on edits."""

import time

from flow_helpers import event_body, login


def test_event_creation_time_survives_edits_and_reload(client):
    headers = login(client)
    body = event_body()
    before = time.time()
    response = client.post("/api/events", headers=headers, json=body)
    assert response.status_code == 201
    event = response.json()
    assert before <= event["created_at"] <= time.time()
    updated = client.put(
        f"/api/events/{event['id']}",
        headers=headers,
        json={**body, "title": "Updated event"},
    )
    assert updated.status_code == 200
    assert updated.json()["created_at"] == event["created_at"]
    saved = next(
        row for row in client.get("/api/events").json() if row["id"] == event["id"]
    )
    assert saved["created_at"] == event["created_at"]
