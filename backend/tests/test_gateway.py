import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from sqlalchemy.orm import Session
from test_signups import custom_client as custom_client
from test_signups import publish

from app.gateway import SignupGateway
from app.main import create_app
from app.models import Event, TableSignup


def component(event, action="open", *, private=None):
    if private is None:
        private = action != "open"
    return SimpleNamespace(
        id=9000 + {"open": 0, "select": 1, "withdraw": 2}[action],
        application_id=123,
        type=discord.InteractionType.component,
        guild_id="guild",
        channel_id="channel",
        user=SimpleNamespace(id=1, name="Player", global_name="Player One", bot=False),
        data={
            "custom_id": f"signup:{action}:{event['id']}",
            "component_type": 3 if action == "select" else 2,
            "values": ["1"],
        },
        message=SimpleNamespace(
            id=999 if private else "message",
            flags=discord.MessageFlags(ephemeral=private),
            author=SimpleNamespace(id=123),
        ),
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def test_gateway_opens_private_menu_and_saves_and_withdraws(custom_client):
    client, _, config = custom_client
    _, event, _ = publish(custom_client)

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        assert gateway.intents.value == 0
        opening = component(event)
        await gateway.on_interaction(opening)
        opening.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        shown = opening.edit_original_response.call_args.kwargs
        assert "Saved tables: None" in shown["content"]
        assert shown["allowed_mentions"].to_dict()["parse"] == []
        select = shown["view"].children[0]
        assert isinstance(select, discord.ui.Select)
        assert [option.label for option in select.options] == ["A", "B"]
        assert select.max_values == 2
        selecting = component(event, "select")
        await gateway.on_interaction(selecting)
        selecting.response.defer.assert_awaited_once_with(
            ephemeral=True, thinking=False
        )
        saved = selecting.edit_original_response.call_args.kwargs
        assert "Saved tables: B" in saved["content"]
        assert saved["view"].children[0].options[1].default
        with Session(client.app.state.engine) as db:
            assert db.get(TableSignup, (event["id"], "1")).choices == ["B"]
        withdrawing = component(event, "withdraw")
        await gateway.on_interaction(withdrawing)
        assert (
            "withdrawn"
            in withdrawing.edit_original_response.call_args.kwargs["content"]
        )
        with Session(client.app.state.engine) as db:
            assert db.get(TableSignup, (event["id"], "1")) is None
        await gateway.close()

    asyncio.run(check())


def test_public_message_is_never_updated_by_selection_errors(custom_client):
    client, _, config = custom_client
    _, event, _ = publish(custom_client)

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        forged_source = component(event, "select", private=False)
        await gateway.on_interaction(forged_source)
        forged_source.response.defer.assert_awaited_once_with(
            ephemeral=True, thinking=True
        )
        assert (
            "original event"
            in forged_source.edit_original_response.call_args.kwargs["content"]
        )
        assert forged_source.edit_original_response.call_args.kwargs["view"] is None
        await gateway.close()

    asyncio.run(check())


def test_defer_failure_does_not_save_a_selection(custom_client):
    client, _, config = custom_client
    _, event, _ = publish(custom_client)

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        selecting = component(event, "select")
        selecting.response.defer.side_effect = discord.HTTPException(
            SimpleNamespace(status=503, reason="Unavailable"), "Unavailable"
        )
        await gateway.on_interaction(selecting)
        selecting.edit_original_response.assert_not_awaited()
        with Session(client.app.state.engine) as db:
            assert db.get(TableSignup, (event["id"], "1")) is None
        await gateway.close()

    asyncio.run(check())


def test_gateway_reports_database_failure_privately(custom_client, monkeypatch):
    client, _, config = custom_client
    _, event, _ = publish(custom_client)
    monkeypatch.setattr("app.gateway.handle", Mock(side_effect=RuntimeError("DB down")))

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        selecting = component(event, "select")
        await gateway.on_interaction(selecting)
        assert (
            "Could not save"
            in selecting.edit_original_response.call_args.kwargs["content"]
        )
        assert selecting.edit_original_response.call_args.kwargs["view"] is None
        await gateway.close()

    asyncio.run(check())


def test_gateway_handles_discord_reply_failure_without_losing_selection(custom_client):
    client, _, config = custom_client
    _, event, _ = publish(custom_client)

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        selecting = component(event, "select")
        selecting.edit_original_response.side_effect = discord.HTTPException(
            SimpleNamespace(status=503, reason="Unavailable"), "Unavailable"
        )
        await gateway.on_interaction(selecting)
        with Session(client.app.state.engine) as db:
            assert db.get(TableSignup, (event["id"], "1")).choices == ["B"]
        await gateway.close()

    asyncio.run(check())


@pytest.mark.parametrize(
    "app_id,endpoint", [(456, None), (123, "https://old.example/interactions")]
)
def test_gateway_rejects_mismatched_app_or_webhook_configuration(
    custom_client, app_id, endpoint
):
    client, _, config = custom_client

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        gateway.application_info = AsyncMock(
            return_value=SimpleNamespace(
                id=app_id,
                interactions_endpoint_url=endpoint,
            )
        )
        with pytest.raises(RuntimeError):
            await gateway.setup_hook()
        await gateway.close()

    asyncio.run(check())


def test_gateway_accepts_matching_application_without_webhook(custom_client):
    client, _, config = custom_client

    async def check():
        gateway = SignupGateway(client.app.state.engine, config)
        gateway.application_info = AsyncMock(
            return_value=SimpleNamespace(
                id=123,
                interactions_endpoint_url=None,
            )
        )
        await gateway.setup_hook()
        unrelated = component({"id": "other"})
        unrelated.data["custom_id"] = "unrelated:button"
        await gateway.on_interaction(unrelated)
        unrelated.response.defer.assert_not_awaited()
        await gateway.close()

    asyncio.run(check())


def test_api_lifespan_starts_and_closes_gateway(custom_client, monkeypatch):
    from fastapi.testclient import TestClient

    _, _, config = custom_client
    config.discord_gateway_enabled = True
    gateway = Mock(run_listener=AsyncMock(), close=AsyncMock())
    factory = Mock(return_value=gateway)
    monkeypatch.setattr("app.main.SignupGateway", factory)
    app = create_app(config)
    with TestClient(app):
        assert app.state.gateway is gateway
    gateway.run_listener.assert_awaited_once()
    gateway.close.assert_awaited_once()
    app.state.engine.dispose()


def test_disconnected_gateway_blocks_publication_before_posting(custom_client):
    from test_flow import event_body, login

    client, _, config = custom_client
    headers = login(client)
    record = client.post("/api/events", headers=headers, json=event_body()).json()
    config.discord_gateway_enabled = True
    response = client.post(f"/api/events/{record['id']}/publish", headers=headers)
    assert response.status_code == 503
    assert "listener is not connected" in response.json()["detail"]
    client.app.state.discord.publish.assert_not_called()
    with Session(client.app.state.engine) as db:
        assert db.get(Event, record["id"]).status == "draft"
