"""Common event details retain distinct event/template scheduling constraints."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas import EventInput, EventTemplateInput


@pytest.mark.parametrize("schema", [EventInput, EventTemplateInput])
@pytest.mark.parametrize(
    "change, message",
    [
        ({"title": "   "}, "Event title cannot be blank"),
        (
            {
                "tables": [
                    {"name": "Straße", "capacity": 1},
                    {"name": "STRASSE", "capacity": 1},
                ]
            },
            "Table names must be unique",
        ),
    ],
)
def test_shared_details_validation(schema, change, message):
    data = {
        "title": "Game night",
        "duration_hours": 24,
        "starts_at": datetime.now(UTC) + timedelta(days=7),
        "tables": [{"name": "Game A", "capacity": 10}],
        **change,
    }
    with pytest.raises(ValidationError, match=message):
        schema(**data)


def test_event_can_have_manual_closing_while_template_requires_duration():
    details = {
        "title": "Game night",
        "duration_hours": 0,
        "tables": [{"name": "Game A", "capacity": 10}],
    }
    assert (
        EventInput(
            **details, starts_at=datetime.now(UTC) + timedelta(days=7)
        ).duration_hours
        == 0
    )
    with pytest.raises(ValidationError):
        EventTemplateInput(**details)
