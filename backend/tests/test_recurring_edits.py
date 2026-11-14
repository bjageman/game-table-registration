"""Editing a series and editing its individual unpublished occurrences."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from flow_helpers import event_body, login
from sqlalchemy.orm import Session

from app.events.recurrence import fill_schedule
from app.models import Event, RecurringSeries


def setup_schedule(client):
    headers = login(client)
    body = {
        **event_body(),
        "description": "Bring friends",
        "location": "Game Store",
        "frequency": "weekly",
        "time_zone": "America/New_York",
        "opens_before_hours": 72,
        "closes_before_hours": 24,
        "post_warning_message": True,
        "warning_hours_before_close": 2,
        "warning_message": "Last chance!",
    }
    response = client.post("/api/recurring-series", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return headers, body, response.json()["id"]


def scheduled(client, series_id):
    return [
        row for row in client.get("/api/events").json() if row["series_id"] == series_id
    ]


def test_individual_move_keeps_original_slot_and_cancel_does_not_regenerate_it(client):
    headers, body, series_id = setup_schedule(client)
    original = scheduled(client, series_id)
    first = original[0]
    changed = {
        **body,
        "starts_at": datetime.fromtimestamp(
            first["starts_at"] + 2 * 86400, UTC
        ).isoformat(),
        "title": "Wednesday only",
    }
    response = client.put(f"/api/events/{first['id']}", headers=headers, json=changed)
    assert response.status_code == 200, response.text
    assert (
        response.json()["scheduled_publish_at"]
        == first["scheduled_publish_at"] + 2 * 86400
    )
    with Session(client.app.state.engine) as db:
        fill_schedule(
            db, db.get(RecurringSeries, series_id), datetime.now(UTC).timestamp()
        )
        db.commit()
    rows = scheduled(client, series_id)
    assert len(rows) == 4
    assert rows[1:] == original[1:]
    assert first["starts_at"] not in {row["starts_at"] for row in rows}
    assert client.get("/api/recurring-series").json()[0]["title"] == body["title"]
    assert (
        client.post(
            f"/api/events/{first['id']}/cancel-scheduled", headers=headers
        ).status_code
        == 204
    )
    rows = scheduled(client, series_id)
    assert len(rows) == 4
    assert first["starts_at"] not in {row["starts_at"] for row in rows}
    assert response.json()["starts_at"] not in {row["starts_at"] for row in rows}


def test_series_edit_moves_all_unpublished_occurrences_and_preserves_published_event(
    client,
):
    headers, body, series_id = setup_schedule(client)
    first = scheduled(client, series_id)[0]
    published = client.post(f"/api/events/{first['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["series_id"] is None
    series = client.get("/api/recurring-series").json()[0]
    assert series["description"] == body["description"]
    assert series["opens_before_hours"] == 72
    new_start = datetime.fromtimestamp(series["starts_at"], UTC) + timedelta(days=2)
    edited = {
        **body,
        "title": "Wednesday games",
        "starts_at": new_start.isoformat(),
        "location": "Another Game Store",
        "tables": [{"name": "New game", "capacity": 8}],
    }
    response = client.put(
        f"/api/recurring-series/{series_id}", headers=headers, json=edited
    )
    assert response.status_code == 200, response.text
    rows = scheduled(client, series_id)
    assert len(rows) == 4
    assert rows[0]["starts_at"] == new_start.timestamp()
    for row in rows:
        assert row["title"] == edited["title"]
        assert row["tables"] == edited["tables"]
        assert row["warning_message"] == body["warning_message"]
        assert row["scheduled_publish_at"] == row["starts_at"] - 72 * 3600
        assert row["closes_at"] == row["starts_at"] - 24 * 3600
    assert (
        next(
            row for row in client.get("/api/events").json() if row["id"] == first["id"]
        )
        == published.json()
    )


def test_occurrence_becomes_individual_when_signup_open_time_arrives(client):
    headers, body, series_id = setup_schedule(client)
    first = scheduled(client, series_id)[0]
    # Exercise the same publication service as the worker at the exact opening time.
    from app.config import Settings
    from app.context import ApplicationContext
    from app.events.publication import publish_event

    context = ApplicationContext(
        client.app,
        Settings(
            _env_file=None, discord_signup_mode="poll", discord_gateway_enabled=False
        ),
        client.app.state.engine,
    )
    with patch(
        "app.events.publication.time.time", return_value=first["scheduled_publish_at"]
    ):
        result = publish_event(
            context, first["id"], client.app.state.discord, "scheduled"
        )
    assert result["status"] == "open"
    assert result["series_id"] is None
    assert len(scheduled(client, series_id)) == 3
    assert client.app.state.discord.publish.call_count == 1
    with Session(client.app.state.engine) as db:
        assert db.get(Event, first["id"]).source_series_id == series_id
        fill_schedule(
            db, db.get(RecurringSeries, series_id), first["scheduled_publish_at"]
        )
        db.commit()
    assert len(scheduled(client, series_id)) == 4
    assert (
        client.put(f"/api/events/{first['id']}", headers=headers, json=body).status_code
        == 409
    )


def test_scheduled_edit_requires_future_opening_and_active_owned_series(client):
    headers, body, series_id = setup_schedule(client)
    first = scheduled(client, series_id)[0]
    assert (
        client.put(
            f"/api/events/{first['id']}",
            headers=headers,
            json={**body, "opens_before_hours": None},
        ).status_code
        == 400
    )
    assert (
        client.put(f"/api/recurring-series/{series_id}", json=body).status_code == 403
    )
    with Session(client.app.state.engine) as db:
        db.get(RecurringSeries, series_id).created_by = "someone-else"
        db.commit()
    assert (
        client.put(
            f"/api/recurring-series/{series_id}", headers=headers, json=body
        ).status_code
        == 404
    )


def test_series_edit_leaves_due_occurrence_for_publication(client):
    headers, body, series_id = setup_schedule(client)
    first = scheduled(client, series_id)[0]
    with Session(client.app.state.engine) as db:
        event = db.get(Event, first["id"])
        event.scheduled_publish_at = datetime.now(UTC).timestamp() - 1
        db.commit()
    edited = {**body, "title": "Future games"}
    assert (
        client.put(
            f"/api/recurring-series/{series_id}", headers=headers, json=edited
        ).status_code
        == 200
    )
    rows = scheduled(client, series_id)
    assert len(rows) == 4
    due = next(row for row in rows if row["id"] == first["id"])
    assert due["title"] == body["title"]
    assert all(
        row["title"] == edited["title"] for row in rows if row["id"] != first["id"]
    )
    assert (
        client.put(f"/api/events/{first['id']}", headers=headers, json=body).status_code
        == 409
    )


def test_moving_occurrence_to_a_later_slot_does_not_generate_duplicate_date(client):
    headers, body, series_id = setup_schedule(client)
    original = scheduled(client, series_id)
    moved_start = original[0]["starts_at"] + 28 * 86400
    response = client.put(
        f"/api/events/{original[0]['id']}",
        headers=headers,
        json={
            **body,
            "starts_at": datetime.fromtimestamp(moved_start, UTC).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    assert (
        client.post(
            f"/api/events/{original[1]['id']}/publish", headers=headers
        ).status_code
        == 200
    )
    with Session(client.app.state.engine) as db:
        fill_schedule(
            db, db.get(RecurringSeries, series_id), datetime.now(UTC).timestamp()
        )
        db.commit()
    rows = scheduled(client, series_id)
    assert len(rows) == 4
    assert sum(row["starts_at"] == moved_start for row in rows) == 1
