"""Events API integration coverage."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from flow_helpers import closing_event, closing_message, event_body, login
from sqlalchemy.orm import Session as DBSession

from app.config import Settings
from app.main import create_app
from app.models import Base


@pytest.mark.parametrize("offset", [24, None])
def test_signup_deadline_is_relative_to_event_or_open_ended(client, offset):
    from app.discord import reactions

    headers = login(client)
    body = {**event_body(), "duration_hours": 0, "closes_before_hours": offset}
    created = client.post("/api/events", headers=headers, json=body)
    assert created.status_code == 201
    event = created.json()
    expected = event["starts_at"] - offset * 3600 if offset is not None else None
    assert event["closes_at"] == expected
    path = f"/api/events/{event['id']}"
    published = client.post(path + "/publish", headers=headers)
    assert published.status_code == 200
    assert published.json()["closes_at"] == expected
    assert published.json()["signup_mode"] == "reactions"
    payload = client.app.state.discord.publish.call_args.args[0]
    if offset is None:
        assert "stay open until closed manually" in str(payload)
    now = time.time()
    assert reactions.replace(client.app.state.engine, event["id"], [], now)
    reactions.change(client.app.state.engine, event["id"], "1️⃣", "1", "Mary", True, now)
    assert client.get(path + "/signups").json()[0]["players"][0]["name"] == "Mary"
    reactions.mark_gap(client.app.state.engine)
    assert any(
        row["id"] == event["id"] and row["sync"]
        for row in reactions.pending(client.app.state.engine)
    )
    assert reactions.replace(
        client.app.state.engine,
        event["id"],
        [{"id": "1", "name": "Mary", "choices": ["Clocktower"]}],
        time.time(),
    )
    assert client.post(path + "/close", headers=headers).status_code == 200


def test_recurring_events_schedule_cancel_and_stop(client):
    headers = login(client)
    body = {
        **event_body(),
        "frequency": "weekly",
        "time_zone": "America/New_York",
        "opens_before_hours": 72,
        "closes_before_hours": 24,
    }
    created = client.post("/api/recurring-series", headers=headers, json=body)
    assert created.status_code == 201, created.text
    series_id = created.json()["id"]
    scheduled = [
        row for row in client.get("/api/events").json() if row["series_id"] == series_id
    ]
    assert len(scheduled) == 4
    assert all(row["status"] == "scheduled" for row in scheduled)
    assert all(row["duration_hours"] == 48 for row in scheduled)
    assert scheduled[0]["scheduled_publish_at"] == scheduled[0]["starts_at"] - 72 * 3600
    assert (
        client.post(
            f"/api/events/{scheduled[0]['id']}/cancel-scheduled", headers=headers
        ).status_code
        == 204
    )
    replacement = [
        row for row in client.get("/api/events").json() if row["series_id"] == series_id
    ]
    assert len(replacement) == 4
    assert scheduled[0]["id"] not in {row["id"] for row in replacement}
    assert (
        client.post(
            f"/api/recurring-series/{series_id}/stop", headers=headers
        ).status_code
        == 204
    )
    assert not [
        row for row in client.get("/api/events").json() if row["series_id"] == series_id
    ]


def test_due_recurring_event_is_published_once_by_worker(tmp_path):
    from sqlalchemy import update

    from app.models import Event

    settings = Settings(
        _env_file=None,
        announcement_worker_enabled=True,
        database_url=f"sqlite:///{tmp_path}/scheduled.db",
        discord_client_id="client",
        discord_signup_mode="poll",
        discord_gateway_enabled=False,
        discord_client_secret="secret",
        discord_bot_token="token",
        discord_guild_id="guild",
        discord_channel_id="channel",
        owner_discord_id="owner",
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    app.state.discord = Mock()
    app.state.discord.identity.return_value = {"id": "owner", "username": "organizer"}
    app.state.discord.publish.return_value = {
        "id": "message",
        "poll": {
            "answers": [{"answer_id": 9}],
            "expiry": (datetime.now(UTC) + timedelta(hours=48)).isoformat(),
        },
    }
    with TestClient(app) as test_client:
        headers = login(test_client)
        body = {
            **event_body(),
            "frequency": "weekly",
            "time_zone": "America/New_York",
            "opens_before_hours": 72,
            "closes_before_hours": 24,
        }
        assert (
            test_client.post(
                "/api/recurring-series", headers=headers, json=body
            ).status_code
            == 201
        )
        first = test_client.get("/api/events").json()[0]
        with DBSession(app.state.engine) as db:
            db.execute(
                update(Event)
                .where(Event.id == first["id"])
                .values(scheduled_publish_at=time.time() - 1)
            )
            db.commit()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if test_client.get("/api/events").json()[0]["status"] == "open":
                break
            time.sleep(0.2)
        else:
            pytest.fail("Scheduled event was not published")
        assert app.state.discord.publish.call_count == 1
    app.state.engine.dispose()


def test_templates_save_reusable_details_without_an_event_date_and_are_private(client):
    headers = login(client)
    body = {
        "title": "Friday games",
        "description": "Bring friends",
        "location": "Game Store",
        "duration_hours": 24,
        "tables": [{"name": "Clocktower", "capacity": 15}],
    }
    assert client.get("/api/templates").json() == []
    assert client.post("/api/templates", json=body).status_code == 403
    created = client.post("/api/templates", headers=headers, json=body)
    assert created.status_code == 201
    assert created.json() == {
        "id": created.json()["id"],
        **body,
        "post_warning_message": False,
        "warning_hours_before_close": 1,
        "warning_message": "",
    }
    assert client.get("/api/templates").json() == [created.json()]
    assert client.get("/api/events").json() == []
    assert (
        client.post(
            "/api/templates",
            headers=headers,
            json={**body, "tables": [body["tables"][0]] * 2},
        ).status_code
        == 422
    )
    client.app.state.discord.identity.return_value = {
        "id": "second",
        "username": "Second",
    }
    login(client)
    assert client.get("/api/templates").json() == []
    client.app.state.discord.identity.return_value = {
        "id": "owner",
        "username": "organizer",
    }
    login(client)
    assert client.get("/api/templates").json() == [created.json()]


@pytest.mark.parametrize(
    "patch",
    [
        {"tables": []},
        {"tables": [{"name": "a", "capacity": 0}]},
        {"tables": [{"name": str(i)} for i in range(11)]},
        {"tables": [{"name": "a"}, {"name": "A"}]},
        {"starts_at": "2020-01-01T12:00:00+00:00"},
        {"starts_at": "2030-01-01T12:00:00"},
        {"duration_hours": 769},
        {"title": "   "},
        {"tables": [{"name": " "}]},
    ],
)
def test_validation(client, patch):
    assert (
        client.post(
            "/api/events", headers=login(client), json={**event_body(), **patch}
        ).status_code
        == 422
    )


def test_uncertain_publish_is_held(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    client.app.state.discord.publish.side_effect = TimeoutError()
    path = f"/api/events/{event['id']}/publish"
    assert client.post(path, headers=headers).status_code == 502
    assert client.get("/api/events").json()[0]["status"] == "needs_review"
    assert client.post(path, headers=headers).status_code == 409
    assert client.app.state.discord.publish.call_count == 1


def test_concurrent_publish_claim(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: (
                    client.post(
                        f"/api/events/{event['id']}/publish", headers=headers
                    ).status_code
                ),
                range(2),
            )
        )
    assert sorted(results) == [200, 409]
    assert client.app.state.discord.publish.call_count == 1


def test_health_and_configuration(client):
    assert client.get("/api/health/ready").status_code == 200
    assert client.get("/api/setup").json() == {"configured": True}


def test_signup_endpoint_is_authorized_and_scoped_to_guild(client):
    from app.models import Event

    assert client.get("/api/events/missing/signups").status_code == 401
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}/signups"
    result = client.get(path)
    assert result.status_code == 200
    assert all(t["players"] == [] for t in result.json())
    client.app.state.discord.table_signups.assert_not_called()
    with DBSession(client.app.state.engine) as db:
        row = db.get(Event, event["id"])
        row.message_id = "message"
        db.commit()
    players = [{"name": "A", "players": [{"id": "1", "name": "Mary"}]}]
    client.app.state.discord.table_signups.return_value = players
    assert client.get(path).json() == [
        {
            "name": "A",
            "players": [
                {
                    **players[0]["players"][0],
                    "weighting": 5.0,
                    "guaranteed_table": None,
                    "guaranteed_seat": False,
                }
            ],
        }
    ]
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).guild_id = "other-guild"
        db.commit()
    assert client.get(path).status_code == 404


def test_reaction_promotion_notice_has_no_table_update_heading(client):
    from app.assignments.withdrawals import withdraw
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={
                "automatic_weight_adjustment": True,
                "announce_table_changes": True,
                "post_discord_updates_to_thread": False,
            },
        ).status_code
        == 200
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    table = next(row for row in client.get(path + "/signups").json() if row["waitlist"])
    seated = table["players"][0]["id"]
    assert withdraw(client.app.state.engine, "guild", "channel", "announcement", seated)
    with DBSession(client.app.state.engine) as db:
        notice = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .one()
        )
        assert "Table Update" not in notice.payload["content"]
        assert notice.payload["content"].startswith("<@")
        assert "has been promoted to" in notice.payload["content"]
        assert (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="refresh")
            .count()
            == 1
        )


def test_table_change_notices_can_be_disabled_and_enabled(client):
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    client.put(
        "/api/settings/assignment",
        headers=headers,
        json={
            "automatic_weight_adjustment": True,
            "announce_table_changes": False,
            "post_discord_updates_to_thread": False,
        },
    )
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    table = next(row for row in client.get(path + "/signups").json() if row["waitlist"])
    seated = table["players"][0]["id"]
    assert (
        client.delete(f"{path}/manager-players/{seated}", headers=headers).status_code
        == 200
    )
    with DBSession(client.app.state.engine) as db:
        assert (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .count()
            == 0
        )
        assert (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="refresh")
            .count()
            == 1
        )
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={
                "automatic_weight_adjustment": True,
                "announce_table_changes": True,
                "post_discord_updates_to_thread": False,
            },
        ).status_code
        == 200
    )
    target_table = next(
        row for row in client.get(path + "/signups").json() if row["waitlist"]
    )
    waiting = target_table["waitlist"][0]["id"]
    assert (
        client.post(
            f"{path}/assigned-players/{waiting}",
            headers=headers,
            json={"table": target_table["name"]},
        ).status_code
        == 200
    )
    with DBSession(client.app.state.engine) as db:
        notice = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="promotion")
            .one()
        )
        assert "has been promoted from the waitlist" in notice.payload["content"]
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={
                "automatic_weight_adjustment": True,
                "announce_table_changes": False,
                "post_discord_updates_to_thread": False,
            },
        ).status_code
        == 200
    )
    before = client.app.state.discord.send_announcement.call_count
    from app.discord.announcements import deliver_event

    deliver_event(
        client.app.state.engine, client.app.state.discord, event["id"], limit=5
    )
    assert all(
        "has been promoted" not in call.args[1].get("content", "")
        for call in client.app.state.discord.send_announcement.call_args_list[before:]
    )
    with DBSession(client.app.state.engine) as db:
        saved = db.get(Announcement, notice.id)
        assert saved is not None and saved.deleted_at is not None


def test_assignment_changes_refresh_existing_discord_message_with_retry(client):
    from app.discord.announcements import dispatch_due
    from app.discord.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    # This test exercises roster edits independently of separate change notices.
    client.put(
        "/api/settings/assignment",
        headers=headers,
        json={
            "automatic_weight_adjustment": True,
            "announce_table_changes": False,
            "post_discord_updates_to_thread": False,
        },
    )
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    table = next(row for row in client.get(path + "/signups").json() if row["waitlist"])
    waiting = table["waitlist"][0]["id"]
    assert (
        client.post(
            f"{path}/assigned-players/{waiting}",
            headers=headers,
            json={"table": table["name"]},
        ).status_code
        == 200
    )
    with DBSession(client.app.state.engine) as db:
        refresh = (
            db.query(Announcement).filter_by(event_id=event["id"], kind="refresh").one()
        )
        assert refresh.state == "pending"
    assert client.get(path + "/announcement").json()["update_pending"] is True
    discord.at.return_value.edit_announcement.side_effect = DiscordRequestError(429)
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    with DBSession(client.app.state.engine) as db:
        refresh = (
            db.query(Announcement).filter_by(event_id=event["id"], kind="refresh").one()
        )
        assert refresh.state == "pending"
        refresh.next_attempt = 0
        db.commit()
    discord.at.return_value.edit_announcement.side_effect = None
    sent_before = discord.send_announcement.call_count
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert discord.send_announcement.call_count == sent_before
    channel, message_id, edit = discord.at.return_value.edit_announcement.call_args.args
    assert (channel, message_id) == ("channel", "announcement")
    assert edit["allowed_mentions"] == {"parse": [], "users": []}
    assert "<@" not in edit["content"]
    table_field = next(
        field
        for field in edit["embeds"][0]["fields"]
        if field["name"].startswith(table["name"])
    )
    assert table_field["name"].endswith("(2/1)")
    assert f"<@{waiting}>" in table_field["value"]
    with DBSession(client.app.state.engine) as db:
        row = (
            db.query(Announcement)
            .filter_by(event_id=event["id"], kind="assignment")
            .one()
        )
        assert row.payload["embeds"] == edit["embeds"]
        refresh = (
            db.query(Announcement).filter_by(event_id=event["id"], kind="refresh").one()
        )
        assert refresh.state == "sent" and refresh.deleted_at is not None
        db.add(
            Announcement(
                id="extra-assignment-part",
                event_id=event["id"],
                part=3,
                kind="assignment",
                channel_id="channel",
                payload={"content": "Old extra roster", "nonce": "extra"},
                state="sent",
                message_id="old-extra",
                created_at=time.time(),
                next_attempt=time.time(),
            )
        )
        db.commit()
    assert (
        client.delete(f"{path}/manager-players/{waiting}", headers=headers).status_code
        == 200
    )
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    _, extra_id, extra_edit = discord.at.return_value.edit_announcement.call_args.args
    assert extra_id == "old-extra"
    assert extra_edit["embeds"] == []
    assert extra_edit["content"].startswith("Assignments updated above")
    assert client.get(path + "/announcement").json()["update_pending"] is False


def test_optional_open_signup_rosters_publish_refresh_and_restore(client):
    from app.discord.open_signup_rosters import synchronize_due

    headers = login(client)
    settings = {
        "automatic_weight_adjustment": True,
        "announce_table_changes": False,
        "post_discord_updates_to_thread": False,
        "show_open_signup_players": True,
    }
    assert (
        client.get("/api/settings/assignment").json()["show_open_signup_players"]
        is True
    )
    assert client.put("/api/settings/assignment", json=settings).status_code == 403
    assert (
        client.put("/api/settings/assignment", headers=headers, json=settings).json()[
            "show_open_signup_players"
        ]
        is True
    )
    legacy = {
        key: value
        for key, value in settings.items()
        if key != "show_open_signup_players"
    }
    assert (
        client.put("/api/settings/assignment", headers=headers, json=legacy).json()[
            "show_open_signup_players"
        ]
        is True
    )
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    assert (
        client.put(
            path + "/manager-players/1",
            headers=headers,
            json={"table": "Clocktower", "name": "One"},
        ).status_code
        == 200
    )
    assert client.post(path + "/publish", headers=headers).status_code == 200
    discord = client.app.state.discord
    payload = discord.publish.call_args.args[0]
    assert "poll" in payload
    assert "Total users signed up: 1" in payload["embeds"][0]["description"]
    assert "<@1>" in payload["embeds"][0]["fields"][0]["value"]
    discord.table_signups.return_value = [
        {"name": "Clocktower", "players": [{"id": "2", "name": "Two"}]}
    ]
    synchronize_due(client.app.state.engine, lambda guild, channel: discord)
    edit = discord.edit_announcement.call_args.args[2]
    assert "Total users signed up: 2" in edit["embeds"][0]["description"]
    assert "poll" not in edit
    assert (
        client.put(
            "/api/settings/assignment",
            headers=headers,
            json={**settings, "show_open_signup_players": False},
        ).status_code
        == 200
    )
    synchronize_due(client.app.state.engine, lambda guild, channel: discord)
    restored = discord.edit_announcement.call_args.args[2]
    assert restored["embeds"] == []
    assert "Total users signed up" not in restored["content"]
    assert "Signups open for 24 hours." in restored["content"]
