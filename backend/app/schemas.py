import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator


class TableInput(BaseModel):
    name: str = Field(min_length=1, max_length=35)
    capacity: int = Field(default=15, ge=1, le=999)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Table name cannot be blank")
        return value.strip()


class EventInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    starts_at: datetime
    duration_hours: int = Field(ge=1, le=768)
    tables: list[TableInput] = Field(min_length=1, max_length=10)
    timezone: str = "UTC"
    opens_at: datetime | None = None
    signup_closes_at: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA timezone") from None
        return value

    @model_validator(mode="after")
    def validate_event(self) -> "EventInput":
        if not self.title.strip():
            raise ValueError("Event title cannot be blank")
        for value in [self.starts_at, self.opens_at, self.signup_closes_at]:
            if value is not None and value.tzinfo is None:
                raise ValueError("Event times must include a timezone")
        if (self.opens_at is None) != (self.signup_closes_at is None):
            raise ValueError("Provide both signup opening and closing times")
        if self.opens_at is not None and self.signup_closes_at is not None:
            opening, closing = (
                self.opens_at.timestamp(),
                self.signup_closes_at.timestamp(),
            )
            if not time.time() < opening < closing < self.starts_at.timestamp():
                raise ValueError("Require now < signup opening < closing < event start")
            if closing - opening > 768 * 3600:
                raise ValueError("Signup windows cannot exceed 32 days")
        elif self.starts_at.timestamp() <= time.time() + self.duration_hours * 3600:
            raise ValueError("Event must start after the signup window ends")
        if len({table.name.casefold() for table in self.tables}) != len(self.tables):
            raise ValueError("Table names must be unique")
        return self
