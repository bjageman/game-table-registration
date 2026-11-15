"""Batch event reads and keep roster work proportional to its actual members."""

from collections import Counter
from contextlib import contextmanager

import pytest
from flow_helpers import login
from sqlalchemy import event as sql_events
from sqlalchemy.orm import Session

from app.assignments.roster import build_current_roster
from app.models import (
    Announcement,
    DiscordScheduledEvent,
    Event,
    EventTableRemoval,
    EventWaitlistAddition,
    EventWithdrawal,
    LotteryRun,
    PlayerProfile,
)


@contextmanager
def recorded_queries(engine):
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    sql_events.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        sql_events.remove(engine, "before_cursor_execute", record)


@pytest.mark.parametrize("count", [1, 30])
def test_event_list_batches_related_reads_and_preserves_scope_and_order(client, count):
    login(client)
    engine = client.app.state.engine
    with Session(engine) as db:
        for index in range(count):
            db.add(
                Event(
                    id=f"event-{index}",
                    guild_id="guild",
                    channel_id="channel",
                    created_by="owner",
                    title=f"Event {index}",
                    starts_at=100 + index,
                    duration_hours=24,
                    tables=[],
                    status="review",
                    close_pairs={"1": "2"},
                )
            )
        db.add(
            Event(
                id="other",
                guild_id="other",
                channel_id="elsewhere",
                created_by="owner",
                title="Outside destination",
                starts_at=0,
                duration_hours=24,
                tables=[],
            )
        )
        db.flush()
        for index in range(count):
            event_id = f"event-{index}"
            db.add(
                DiscordScheduledEvent(
                    event_id=event_id, state="failed", error="Scheduled event error"
                )
            )
            db.add(
                Announcement(
                    id=f"announcement-{index}",
                    event_id=event_id,
                    part=0,
                    channel_id="channel",
                    payload={},
                    created_at=0,
                    next_attempt=0,
                    error="Delivery error",
                )
            )
            db.add(
                LotteryRun(
                    event_id=event_id,
                    version="test",
                    seed="test",
                    created_by="owner",
                    created_at=0,
                    snapshot={"players": []},
                    result={
                        "assignments": {},
                        "tables": [],
                        "waitlist": [],
                        "pairing_conflicts": [
                            {"players": ["1", "2"], "message": "Pair needs attention"}
                        ],
                    },
                )
            )
        db.commit()
    with recorded_queries(engine) as statements:
        response = client.get("/api/events")
    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == [f"event-{index}" for index in range(count)]
    assert all(
        row["has_discord_event"] and row["assignment_publication_pending"]
        for row in rows
    )
    assert all(
        row["discord_event_error"] == "Scheduled event error"
        and row["assignment_publication_error"] == "Delivery error"
        for row in rows
    )
    assert all(row["pairing_warnings"] == ["Pair needs attention"] for row in rows)
    for table in (
        "discord_scheduled_events",
        "announcements",
        "lottery_runs",
        "event_withdrawals",
        "event_manual_assignments",
        "event_waitlist_additions",
        "event_manager_signups",
        "event_table_removals",
    ):
        assert (
            sum(f"FROM {table} " in sql.replace("\n", " ") for sql, _ in statements)
            == 1
        )


def test_large_roster_preserves_waitlist_priority_after_rejoining_and_table_removal(
    promotion_db,
):
    with Session(promotion_db) as db:
        run = db.get(LotteryRun, "event")
        people = [
            {"id": str(i), "name": f"Player {i}", "choices": ["Table A"]}
            for i in range(1, 1001)
        ]
        run.snapshot = {"players": people}
        run.result = {
            "assignments": {"1": "Table A"},
            "waitlist": [p["id"] for p in people[1:]],
            "tables": [
                {"name": "Table A", "players": people[:1], "waitlist": people[1:]}
            ],
        }
        db.add(
            EventWithdrawal(
                event_id="event", discord_id="2", table_name="Table A", withdrawn_at=10
            )
        )
        db.add(
            EventWaitlistAddition(
                event_id="event",
                discord_id="2",
                discord_name="Player 2",
                table_name="Table A",
                added_at=20,
            )
        )
        db.add(
            EventTableRemoval(event_id="event", discord_id="3", table_name="Table A")
        )
        db.commit()
        with recorded_queries(promotion_db) as statements:
            result = build_current_roster(db, run)
        assert result["assignments"] == {"1": "Table A"}
        expected = [str(i) for i in range(4, 1001)] + ["2"]
        assert result["waitlist"] == ["2"] + [str(i) for i in range(4, 1001)]
        assert [p["id"] for p in result["tables"][0]["waitlist"]] == expected
        assert (
            Counter(sql.split("FROM ")[1].split()[0] for sql, _ in statements)[
                "event_waitlist_additions"
            ]
            == 1
        )


def test_roster_only_loads_member_profiles_and_keeps_personal_profiles_private(client):
    from flow_helpers import event_body

    headers = login(client)
    event = client.post("/api/events", headers=headers, json=event_body()).json()
    engine = client.app.state.engine
    with Session(engine) as db:
        saved = db.get(Event, event["id"])
        saved.test_signups = {
            "players": [
                {"id": "test-member", "name": "Test member", "choices": ["Clocktower"]}
            ]
        }
        db.add_all(
            [
                PlayerProfile(
                    scope_key="user:owner",
                    guild_id="guild",
                    discord_id=f"unrelated-{i}",
                    real_name="Unrelated private name",
                )
                for i in range(100)
            ]
        )
        db.add(
            PlayerProfile(
                scope_key="user:owner",
                guild_id="guild",
                discord_id="test-member",
                real_name="Visible name",
            )
        )
        db.add(
            PlayerProfile(
                scope_key="user:elsewhere",
                guild_id="guild",
                discord_id="test-member",
                real_name="Other private name",
            )
        )
        db.commit()
    loaded = []

    def remember_loaded(session, instance):
        if isinstance(instance, PlayerProfile):
            loaded.append(instance)

    sql_events.listen(Session, "loaded_as_persistent", remember_loaded)
    try:
        response = client.get(f"/api/events/{event['id']}/signups")
    finally:
        sql_events.remove(Session, "loaded_as_persistent", remember_loaded)
    assert response.status_code == 200
    assert response.json()[0]["players"][0]["display_name"] == "Visible name"
    assert [(p.scope_key, p.discord_id) for p in loaded] == [
        ("user:owner", "test-member")
    ]
    assert (
        "Other private name" not in response.text
        and "Unrelated private name" not in response.text
    )
