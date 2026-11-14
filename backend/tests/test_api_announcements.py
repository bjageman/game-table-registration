"""Announcements API integration coverage."""

from flow_helpers import closing_event, closing_message
from sqlalchemy.orm import Session as DBSession


def test_close_immediately_announces_assignments_without_duplicate_delivery(client):
    from app.discord.announcements import dispatch_due
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    delivery = client.get(path + "/announcement").json()
    assert delivery["status"] == "pending"
    assert delivery["url"].endswith("/channel/announcement")
    channel, payload = discord.send_announcement.call_args_list[0].args
    assert channel == "channel"
    assert payload["embeds"][0]["title"] == "Friday games"
    assert "Table assignments are ready." in payload["embeds"][0]["description"]
    assert "[Signup message]" in payload["embeds"][0]["description"]
    assert payload["enforce_nonce"] is True
    assert payload["allowed_mentions"]["parse"] == []
    assert client.post(path + "/close", headers=headers).status_code == 200
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert discord.send_announcement.call_count == 2
    with DBSession(client.app.state.engine) as db:
        assert db.query(Announcement).filter_by(event_id=event["id"]).count() == 2


def test_announcement_failure_retries_without_redrawing(client):
    from app.discord.announcements import dispatch_due
    from app.discord.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.send_announcement.side_effect = DiscordRequestError(429)
    assert client.post(path + "/close", headers=headers).status_code == 200
    original = client.get(path + "/assignments").json()
    assert client.get(path + "/announcement").json()["status"] == "pending"
    discord.send_announcement.side_effect = None
    with DBSession(client.app.state.engine) as db:
        db.query(Announcement).filter_by(event_id=event["id"]).update(
            {"next_attempt": 0}
        )
        db.commit()
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert client.get(path + "/assignments").json() == original
    assert discord.send_announcement.call_count == 3
    discord.end_poll.assert_not_called()


def test_ambiguous_announcement_is_reconciled_without_blind_repost(client):
    from app.discord.announcements import dispatch_due
    from app.discord.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.send_announcement.side_effect = DiscordRequestError(None)
    client.post(path + "/close", headers=headers)
    discord.send_announcement.side_effect = None
    discord.find_announcement.return_value = "accepted-but-response-lost"
    with DBSession(client.app.state.engine) as db:
        db.query(Announcement).filter_by(event_id=event["id"]).update(
            {"next_attempt": 0}
        )
        db.commit()
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert discord.send_announcement.call_count == 2
    discord.find_announcement.assert_called_once()


def test_unconfirmed_delivery_requires_explicit_repost_confirmation(client):
    from app.discord.announcements import dispatch_due
    from app.discord.discord_api import DiscordRequestError
    from app.models import Announcement

    headers, event, path, _ = closing_event(client)
    discord = client.app.state.discord
    discord.poll_message.return_value = closing_message()
    discord.send_announcement.side_effect = DiscordRequestError(None)
    client.post(path + "/close", headers=headers)
    original = client.get(path + "/assignments").json()
    discord.find_announcement.return_value = None
    with DBSession(client.app.state.engine) as db:
        db.query(Announcement).filter_by(event_id=event["id"]).update(
            {"next_attempt": 0}
        )
        db.commit()
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "needs_review"
    assert (
        client.post(path + "/announcement/retry", headers=headers, json={}).status_code
        == 409
    )
    discord.send_announcement.side_effect = None
    assert (
        client.post(
            path + "/announcement/retry", json={"confirm_repost": True}
        ).status_code
        == 403
    )
    retried = client.post(
        path + "/announcement/retry", headers=headers, json={"confirm_repost": True}
    )
    assert retried.json()["status"] == "pending"
    dispatch_due(client.app.state.engine, lambda guild, channel: discord)
    assert client.get(path + "/announcement").json()["status"] == "sent"
    assert client.get(path + "/assignments").json() == original


def test_test_population_and_announcements_are_destination_scoped(client):
    from app.models import Event

    headers, event, path, _ = closing_event(client)
    with DBSession(client.app.state.engine) as db:
        db.get(Event, event["id"]).guild_id = "other"
        db.commit()
    assert (
        client.post(
            path + "/test-users", headers=headers, json={"players": 30}
        ).status_code
        == 404
    )
    assert client.get(path + "/announcement").status_code == 404
    assert (
        client.post(
            path + "/announcement/retry", headers=headers, json={"confirm_repost": True}
        ).status_code
        == 404
    )
