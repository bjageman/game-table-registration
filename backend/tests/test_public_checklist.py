"""Shared-link attendance persistence, access boundaries, and conflict handling."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from flow_helpers import closing_event, closing_message
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event


def shared_checklist(client):
    headers, event, path, _ = closing_event(client)
    client.app.state.discord.poll_message.return_value = closing_message()
    assert client.post(path + "/close", headers=headers).status_code == 200
    shared = client.post(path + "/share", headers=headers).json()["path"]
    token = shared.rsplit("/", 1)[1]
    return f"/api/public/events/{token}/checklist", event["id"], path, headers


def test_public_checkmarks_persist_and_are_shared_without_login(client):
    url, _, _, _ = shared_checklist(client)
    with TestClient(client.app) as first, TestClient(client.app) as second:
        initial = first.get(url)
        assert initial.headers["cache-control"] == "no-store"
        data = initial.json()
        assert data["revision"] == 0
        assert data["entries"] and not any(data["entries"].values())
        player = next(iter(data["entries"]))
        response = first.patch(url, json={"player_id": player, "arrived": True})
        assert response.status_code == 200
        assert response.json()["entries"][player] is True
        assert second.get(url).json() == response.json()
        assert (
            second.patch(url, json={"player_id": player, "arrived": False}).status_code
            == 200
        )
        assert first.get(url).json()["entries"][player] is False


def test_replacing_browser_version_requires_current_server_revision(client):
    url, _, _, _ = shared_checklist(client)
    initial = client.get(url).json()
    players = list(initial["entries"])
    assert len(players) >= 2
    assert (
        client.patch(url, json={"player_id": players[0], "arrived": True}).status_code
        == 200
    )
    stale = client.put(
        url, json={"revision": initial["revision"], "entries": {players[1]: True}}
    )
    assert stale.status_code == 409
    latest = client.get(url).json()
    assert latest["entries"][players[0]] is True
    response = client.put(
        url, json={"revision": latest["revision"], "entries": {players[1]: True}}
    )
    assert response.status_code == 200
    assert response.json()["entries"][players[0]] is False
    assert response.json()["entries"][players[1]] is True
    assert response.json()["revision"] > latest["revision"]


def test_simultaneous_checkins_preserve_edits_to_different_players(client):
    url, _, _, _ = shared_checklist(client)
    players = list(client.get(url).json()["entries"])[:2]

    def check(player):
        with TestClient(client.app) as public:
            return public.patch(url, json={"player_id": player, "arrived": True})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(check, players))
    assert all(response.status_code == 200 for response in responses)
    assert all(client.get(url).json()["entries"][player] for player in players)


def test_checklist_rejects_unknown_links_players_and_non_boolean_values(client):
    url, event_id, _, _ = shared_checklist(client)
    player = next(iter(client.get(url).json()["entries"]))
    for method, body in (
        ("GET", None),
        ("PATCH", {"player_id": player, "arrived": True}),
        ("PUT", {"revision": 0, "entries": {player: True}}),
    ):
        assert (
            client.request(
                method, "/api/public/events/unknown/checklist", json=body
            ).status_code
            == 404
        )
    for body in (
        {"player_id": "f" * 64, "arrived": True},
        {"player_id": player, "arrived": "yes"},
        {"player_id": "raw-discord-id", "arrived": True},
    ):
        assert client.patch(url, json=body).status_code == 422
    assert (
        client.put(url, json={"revision": 0, "entries": {"f" * 64: True}}).status_code
        == 422
    )
    with Session(client.app.state.engine) as db:
        event = db.get(Event, event_id)
        event.status = "draft"
        db.commit()
    assert client.get(url).status_code == 404
    assert (
        client.patch(url, json={"player_id": player, "arrived": True}).status_code
        == 404
    )


def test_roster_changes_keep_matching_player_checkmarks_and_hide_removed_players(
    client,
):
    url, _, path, headers = shared_checklist(client)
    roster = client.get(path + "/signups").json()
    public_roster = client.get(url.removesuffix("/checklist")).json()
    raw_player = roster[0]["players"][0]["id"]
    public_player = public_roster["tables"][0]["players"][0]["id"]
    client.patch(url, json={"player_id": public_player, "arrived": True})
    assert (
        client.delete(
            path + f"/manager-players/{raw_player}", headers=headers
        ).status_code
        == 200
    )
    assert public_player not in client.get(url).json()["entries"]
    assert (
        client.patch(
            url, json={"player_id": public_player, "arrived": False}
        ).status_code
        == 422
    )


def test_event_links_isolate_checkmarks_and_allow_archived_checklists(client):
    url, event_id, _, _ = shared_checklist(client)
    player = next(iter(client.get(url).json()["entries"]))
    client.patch(url, json={"player_id": player, "arrived": True})
    with Session(client.app.state.engine) as db:
        event = db.scalar(select(Event).where(Event.id == event_id))
        event.archived_at = 1
        old_token = event.public_share_token
        event.public_share_token = "replacement-token"
        db.commit()
    replacement = "/api/public/events/replacement-token/checklist"
    assert client.get(url).status_code == 404
    data = client.get(replacement).json()
    assert player not in data["entries"]
    assert not any(data["entries"].values())
    assert old_token != "replacement-token"
