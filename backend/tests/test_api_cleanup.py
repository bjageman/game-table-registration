"""Cleanup API integration coverage."""

import pytest
from fastapi import HTTPException
from flow_helpers import closing_event, closing_message, event_body, login
from sqlalchemy.orm import Session as DBSession


def test_edit_and_delete_unpublished_draft(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    body = {
        **event_body(),
        "title": "Updated games",
        "tables": [{"name": "New", "capacity": 123}],
    }
    assert client.put(path, json=body).status_code == 403
    saved = client.put(path, headers=headers, json=body)
    assert saved.status_code == 200
    assert saved.json()["title"] == "Updated games"
    assert saved.json()["tables"] == body["tables"]
    assert client.app.state.discord.publish.call_count == 0
    assert client.request("DELETE", path).status_code == 403
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get("/api/events").json() == []
    assert client.post(path + "/publish", headers=headers).status_code == 404


@pytest.mark.parametrize("status", ["publishing", "needs_review", "cancelled"])
def test_published_events_cannot_be_edited_or_deleted(client, status):
    from app.models import Event

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    with DBSession(client.app.state.engine) as db:
        row = db.get(Event, event["id"])
        row.status = status
        db.commit()
    path = f"/api/events/{event['id']}"
    assert client.put(path, headers=headers, json=event_body()).status_code == 409
    assert client.delete(path, headers=headers).status_code == 409
    assert client.get("/api/events").json()[0]["status"] == status


@pytest.mark.parametrize("delete_poll", [False, True])
def test_delete_open_signup_with_optional_discord_poll(client, delete_poll):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    assert client.post(path + "/publish", headers=headers).status_code == 200
    query = "?delete_poll=true" if delete_poll else ""
    assert client.delete(path + query).status_code == 403
    assert client.delete(path + query, headers=headers).status_code == 204
    assert client.get("/api/events").json() == []
    if delete_poll:
        client.app.state.discord.delete_poll.assert_called_once_with("message")
    else:
        client.app.state.discord.delete_poll.assert_not_called()


def test_failed_discord_deletion_preserves_signup_for_retry(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/publish", headers=headers)
    client.app.state.discord.delete_poll.side_effect = HTTPException(
        502, "Discord failed"
    )
    assert client.delete(path + "?delete_poll=true", headers=headers).status_code == 502
    assert client.get("/api/events").json()[0]["status"] == "open"
    client.app.state.discord.delete_poll.side_effect = None
    assert client.delete(path + "?delete_poll=true", headers=headers).status_code == 204


def test_cross_guild_signup_cannot_be_deleted(client):
    from app.models import Event

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    with DBSession(client.app.state.engine) as db:
        row = db.get(Event, event["id"])
        row.guild_id = "other-guild"
        row.status = "open"
        row.message_id = "message"
        db.commit()
    assert (
        client.delete(
            f"/api/events/{event['id']}?delete_poll=true", headers=headers
        ).status_code
        == 409
    )
    client.app.state.discord.delete_poll.assert_not_called()


def test_player_profile_survives_event_and_poll_deletion(client):
    headers = login(client)
    client.app.state.discord.bot.return_value = {
        "username": "mary",
        "global_name": "Mary",
    }
    path = "/api/players/123"
    assert client.get(path).json() == {
        "discord_id": "123",
        "discord_name": "Mary",
        "is_test": False,
        "guaranteed_seat": False,
        "real_name": "",
        "weighting": 5.0,
    }
    client.app.state.discord.bot.reset_mock()
    assert (
        client.get(path + "?signup_name=Mary%20from%20signups").json()["discord_name"]
        == "Mary from signups"
    )
    client.app.state.discord.bot.assert_not_called()
    assert client.put(path, json={"real_name": "Mary Smith"}).status_code == 403
    saved = client.put(path, headers=headers, json={"real_name": " Mary Smith "})
    assert saved.status_code == 200
    assert saved.json()["real_name"] == "Mary Smith"
    assert client.get(path + "?signup_name=Stale").json()["discord_name"] == "Mary"
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    event_path = f"/api/events/{event['id']}"
    client.post(event_path + "/publish", headers=headers)
    assert (
        client.delete(event_path + "?delete_poll=true", headers=headers).status_code
        == 204
    )
    assert client.get(path).json() == saved.json()
    client.app.state.discord.delete_poll.assert_called_once_with("message")
    client.app.state.discord.bot.reset_mock()
    assert client.get(path).json()["discord_name"] == "Mary"
    client.app.state.discord.bot.assert_not_called()


def test_test_profiles_reused_after_clear_and_event_deletion(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/test-users", headers=headers, json={"players": 2})
    players = client.get(path + "/signups").json()[0]["players"]
    pid = players[0]["id"]
    profile_path = f"/api/players/{pid}"
    for weight in (0, -1, 10.1, "nan", "inf"):
        assert (
            client.put(
                profile_path,
                headers=headers,
                json={"real_name": "Test", "weighting": weight},
            ).status_code
            == 422
        )
    assert (
        client.put(profile_path, json={"real_name": "Test", "weighting": 2}).status_code
        == 403
    )
    saved = client.put(
        profile_path,
        headers=headers,
        json={"real_name": "Saved Name", "weighting": 0.25},
    ).json()
    assert saved["is_test"] is True
    client.post(path + "/test-users", headers=headers, json={"players": 0})
    assert client.get(profile_path).json() == saved
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get(profile_path).json() == saved
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/test-users", headers=headers, json={"players": 3})
    reused = client.get(path + "/signups").json()[0]["players"]
    assert {p["id"] for p in players}.issubset({p["id"] for p in reused})
    assert len({p["id"] for p in reused}) == 3
    assert client.get(profile_path).json() == saved
    from app.models import PlayerProfile

    with DBSession(client.app.state.engine) as db:
        db.get(PlayerProfile, ("user:owner", "guild", pid)).guild_id = "elsewhere"
        db.commit()
    assert client.get(profile_path).status_code == 404
    assert (
        client.put(
            profile_path, headers=headers, json={"real_name": "No", "weighting": 1}
        ).status_code
        == 404
    )


def test_archive_preserves_assignments_and_discord_and_is_idempotent(client):
    from app.models import Event

    headers, event, path, _ = closing_event(client)
    assert client.post(path + "/archive", headers=headers).status_code == 409
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    run = client.get(path + "/assignments").json()
    signups = client.get(path + "/signups").json()
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).update_thread_id = "event-thread"
        db.commit()
    calls = list(client.app.state.discord.mock_calls)
    assert client.post(path + "/archive").status_code == 403
    archived = client.post(path + "/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] > 0
    assert archived.json()["status"] == "assigned"
    assert client.post(path + "/archive", headers=headers).json() == archived.json()
    client.app.state.discord.delete_thread.assert_called_with("event-thread")
    assert client.get(path + "/assignments").json() == run
    assert client.get(path + "/signups").json() == signups
    assert any(
        row["id"] == event["id"] and row["archived_at"]
        for row in client.get("/api/events").json()
    )
    # Authorization may contact Discord; archiving must not publish or delete anything.
    assert sum(
        c[0] == "send_announcement" for c in client.app.state.discord.mock_calls
    ) == sum(c[0] == "send_announcement" for c in calls)
    client.app.state.discord.delete_poll.assert_not_called()
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).channel_id = "another-channel"
        db.commit()
    assert client.post(path + "/archive", headers=headers).status_code == 404


def test_close_can_delete_signup_message_and_archive_can_delete_announcements(client):
    from app.announcements import dispatch_due

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    closed = client.post(path + "/close?delete_signup_message=true", headers=headers)
    assert closed.status_code == 200
    assert closed.json()["discord_url"] is None
    assert closed.json()["signup_deleted_at"] > 0
    scoped = client.app.state.discord.at.return_value
    scoped.delete_poll.assert_called_once_with("message")
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    archived = client.post(
        path + "/archive?delete_discord_messages=true", headers=headers
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] > 0
    assert scoped.delete_poll.call_count == 3
    while True:
        cleanup = client.post(path + "/discord-messages/delete", headers=headers)
        assert cleanup.status_code == 200
        if cleanup.json()["discord_cleanup_remaining"] == 0:
            break
    assert client.get(path + "/announcement").json()["status"] == "deleted"
    assert (
        client.post(
            path + "/announcement/retry", headers=headers, json={"confirm_repost": True}
        ).status_code
        == 409
    )
    assert (
        client.post(
            path + "/archive?delete_discord_messages=true", headers=headers
        ).status_code
        == 200
    )
    assert scoped.delete_poll.call_count == 3


@pytest.mark.parametrize("status", [403, 429, 500])
def test_thread_deletion_failure_preserves_archive_and_message_cleanup(client, status):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError
    from app.models import Event

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    client.post(path + "/close", headers=headers)
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).update_thread_id = "thread"
        db.commit()
    discord.delete_thread.side_effect = DiscordRequestError(status, 1)
    result = client.post(
        path + "/archive?delete_discord_messages=true", headers=headers
    )
    assert result.status_code == 200
    assert result.json()["archived_at"]
    assert result.json()["discord_cleanup_remaining"] == 1
    if status == 403:
        assert "Manage Threads" in result.json()["discord_cleanup_error"]
    deleted_messages = discord.at.return_value.delete_poll.call_count
    assert deleted_messages == 3
    discord.delete_thread.side_effect = None
    retried = client.post(path + "/discord-messages/delete", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["discord_cleanup_remaining"] == 0
    assert discord.at.return_value.delete_poll.call_count == deleted_messages
    with DBSession(client.app.state.engine) as db:
        assert db.get(Event, event["id"]).update_thread_id is None


def test_failed_archive_discord_cleanup_can_be_retried(client):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    scoped = client.app.state.discord.at.return_value
    scoped.delete_poll.side_effect = [
        None,
        DiscordRequestError(403),
        None,
        None,
        None,
        None,
        None,
    ]
    failed = client.post(
        path + "/archive?delete_discord_messages=true", headers=headers
    )
    assert failed.status_code == 200
    assert failed.json()["archived_at"] is not None
    assert failed.json()["discord_cleanup_remaining"] == 2
    assert "403" in failed.json()["discord_cleanup_error"]
    retried = client.post(path + "/discord-messages/delete", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["discord_cleanup_remaining"] == 0
    retried = client.post(path + "/discord-messages/delete", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["discord_cleanup_remaining"] == 0
    assert retried.json()["discord_cleanup_error"] is None
    assert scoped.delete_poll.call_count == 4
    assert (
        next(
            row for row in client.get("/api/events").json() if row["id"] == event["id"]
        )["discord_url"]
        is None
    )


def test_archive_cleanup_respects_rate_limit_and_resumes_after_plain_archive(client):
    from app.announcements import dispatch_due
    from app.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    with DBSession(client.app.state.engine) as db:
        for part in range(4, 14):
            db.add(
                Announcement(
                    id=f"extra-{part}",
                    event_id=event["id"],
                    part=part,
                    channel_id="channel",
                    payload={},
                    state="sent",
                    message_id=f"extra-{part}",
                    created_at=0,
                    next_attempt=0,
                )
            )
        db.commit()
    scoped = client.app.state.discord.at.return_value
    scoped.delete_poll.side_effect = [None, DiscordRequestError(429, 0.25)]
    first = client.post(path + "/archive?delete_discord_messages=true", headers=headers)
    assert first.status_code == 200
    assert first.json()["archived_at"] is not None
    assert first.json()["discord_cleanup_remaining"] == 12
    assert first.json()["discord_cleanup_retry_after"] == 0.25
    scoped.delete_poll.side_effect = None
    while True:
        result = client.post(path + "/discord-messages/delete", headers=headers)
        assert result.status_code == 200
        if result.json()["discord_cleanup_remaining"] == 0:
            break
    assert scoped.delete_poll.call_count == 14
    assert result.json()["discord_url"] is None
    assert (
        client.post(path + "/discord-messages/delete", headers=headers).json()[
            "discord_cleanup_remaining"
        ]
        == 0
    )


def test_discord_cleanup_can_start_after_event_was_archived_without_it(client):
    from app.announcements import dispatch_due

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    assert client.post(path + "/archive", headers=headers).status_code == 200
    first = client.post(path + "/discord-messages/delete", headers=headers)
    assert first.status_code == 200
    assert first.json()["discord_cleanup_remaining"] == 0
    last = client.post(path + "/discord-messages/delete", headers=headers)
    assert last.json()["discord_cleanup_remaining"] == 0
    assert last.json()["discord_url"] is None


def test_archive_cleanup_waits_for_queued_announcements(client):
    from app.announcements import dispatch_due

    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    archived = client.post(
        path + "/archive?delete_discord_messages=true", headers=headers
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert archived.json()["discord_cleanup_retry_after"] == 2
    client.app.state.discord.at.return_value.delete_poll.assert_not_called()
    dispatch_due(
        client.app.state.engine, lambda guild, channel: client.app.state.discord
    )
    first = client.post(path + "/discord-messages/delete", headers=headers)
    assert first.json()["discord_cleanup_remaining"] == 0


def test_assigned_signup_message_can_be_deleted_later(client):
    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    deleted = client.post(path + "/signup-message/delete", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["discord_url"] is None
    assert (
        client.post(path + "/signup-message/delete", headers=headers).status_code == 200
    )
    client.app.state.discord.at.return_value.delete_poll.assert_called_once_with(
        "message"
    )


def test_draft_cannot_be_archived(client):
    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    assert (
        client.post(f"/api/events/{event['id']}/archive", headers=headers).status_code
        == 409
    )
    assert (
        client.post("/api/events/missing/archive", headers=headers).status_code == 404
    )


@pytest.mark.parametrize("delete_poll", [False, True])
def test_delete_open_event_handles_all_tracked_roster_messages(client, delete_poll):
    from app.models import Event

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/publish", headers=headers)
    with DBSession(client.app.state.engine) as db:
        saved = db.get(Event, event["id"])
        saved.signup_roster_hash = "roster"
        saved.signup_roster_messages = [
            {"id": "message", "digest": "first"},
            {"id": "overflow", "digest": "second"},
        ]
        db.commit()
    response = client.delete(
        path + f"?delete_poll={str(delete_poll).lower()}", headers=headers
    )
    assert response.status_code == 204
    deleted = [
        call.args[0] for call in client.app.state.discord.delete_poll.call_args_list
    ]
    assert deleted == (["message", "overflow"] if delete_poll else [])


def test_partial_roster_cleanup_failure_retains_event_for_retry(client):
    from app.discord_api import DiscordRequestError
    from app.models import Event

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    path = f"/api/events/{event['id']}"
    client.post(path + "/publish", headers=headers)
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).signup_roster_messages = [
            {"id": "message", "digest": "first"},
            {"id": "overflow", "digest": "second"},
        ]
        db.commit()
    discord = client.app.state.discord
    discord.delete_poll.side_effect = [{}, DiscordRequestError(429, 1)]
    assert client.delete(path + "?delete_poll=true", headers=headers).status_code == 502
    with DBSession(client.app.state.engine) as db:
        assert db.get(Event, event["id"]).signup_roster_messages[1]["id"] == "overflow"
    discord.delete_poll.side_effect = None
    assert client.delete(path + "?delete_poll=true", headers=headers).status_code == 204
    assert [call.args[0] for call in discord.delete_poll.call_args_list].count(
        "overflow"
    ) == 2
