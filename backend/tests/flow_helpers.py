"""Shared API workflow setup; no test collection side effects."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session as DBSession


def login(client):
    response = client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    response = client.get(
        f"/api/auth/callback?state={state}&code=code", follow_redirects=False
    )
    assert response.status_code == 307
    return {
        "Origin": "http://localhost:5180",
        "X-CSRF-Token": client.get("/api/me").json()["csrf"],
    }


def connect_test_organization(
    client, organization_id, guild_id="guild", channel_id="channel"
):
    from app.models import Organization

    with DBSession(client.app.state.engine) as db:
        organization = db.get(Organization, organization_id)
        organization.guild_id = guild_id
        organization.channel_id = channel_id
        db.commit()


def event_body():
    return {
        "title": "Friday games",
        "starts_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "duration_hours": 24,
        "tables": [{"name": "Clocktower", "capacity": 15}],
    }


def set_assignment_review(client, headers, enabled):
    settings = client.get("/api/settings/assignment").json()
    settings["review_assignments_before_discord"] = enabled
    response = client.put("/api/settings/assignment", headers=headers, json=settings)
    assert response.status_code == 200


def closing_event(client, *, review=False):
    headers = login(client)
    set_assignment_review(client, headers, review)
    body = {
        **event_body(),
        "tables": [{"name": "A", "capacity": 1}, {"name": "B", "capacity": 1}],
    }
    base = client.app.state.discord
    base.publish.return_value["poll"]["answers"] = [
        {"answer_id": 9, "poll_media": {"text": "A · 1 seats"}},
        {"answer_id": 42, "poll_media": {"text": "B · 1 seats"}},
    ]
    event = client.post("/api/events", headers=headers, json=body).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/publish", headers=headers)
    users = {
        9: [
            {"id": "1", "username": "Mary"},
            {"id": "2", "username": "Dan"},
            {"id": "3", "username": "Shirley"},
        ],
        42: [{"id": "1", "username": "Mary"}, {"id": "4", "username": "Carl"}],
    }
    base.voter_users.side_effect = lambda message_id, answer_id: users[answer_id]
    return headers, event, path, users


def closing_message(finalized=True, future=False, counts=None):
    return {
        "poll": {
            "expiry": (
                datetime.now(UTC) + timedelta(hours=1)
                if future
                else datetime.now(UTC) - timedelta(seconds=1)
            ).isoformat(),
            "answers": [
                {"answer_id": 9, "poll_media": {"text": "A · 1 seats"}},
                {"answer_id": 42, "poll_media": {"text": "B · 1 seats"}},
            ],
            "results": {
                "is_finalized": finalized,
                "answer_counts": counts
                if counts is not None
                else [{"id": 9, "count": 3}, {"id": 42, "count": 2}],
            },
        }
    }
