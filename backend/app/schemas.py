"""Validated API request bodies."""

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


class SignupWarningInput(BaseModel):
    post_warning_message: bool = False
    warning_hours_before_close: int = Field(default=1, ge=1, le=767)
    warning_message: str = Field(default="", max_length=1600)

    @field_validator("warning_message")
    @classmethod
    def clean_warning(cls, value: str) -> str:
        return value.strip()


class EventInput(SignupWarningInput):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=200)
    starts_at: datetime
    duration_hours: int = Field(
        ge=0,
        le=768,
        description="Publication duration; zero uses an explicit or manual deadline",
    )
    opens_before_hours: int | None = Field(default=None, ge=2, le=768)
    closes_before_hours: int | None = Field(default=None, ge=1, le=767)
    tables: list[TableInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_event(self) -> "EventInput":
        if not self.title.strip():
            raise ValueError("Event title cannot be blank")
        if (
            self.post_warning_message
            and not self.duration_hours
            and self.closes_before_hours is None
        ):
            raise ValueError("Set a signup closing time to post a warning message")
        if self.starts_at.tzinfo is None:
            raise ValueError("Event time must include a timezone")
        if self.starts_at.timestamp() <= time.time() + self.duration_hours * 3600:
            raise ValueError("Event must start after the signup window ends")
        if (
            self.closes_before_hours is not None
            and self.starts_at.timestamp() - self.closes_before_hours * 3600
            <= time.time()
        ):
            raise ValueError("Signup closing time must be in the future")
        if self.opens_before_hours is not None and (
            self.closes_before_hours is None
            or self.opens_before_hours <= self.closes_before_hours
        ):
            raise ValueError("Signups must open before they close")
        if len({table.name.casefold() for table in self.tables}) != len(self.tables):
            raise ValueError("Table names must be unique")
        return self


class RecurringInput(EventInput):
    frequency: str
    time_zone: str = Field(max_length=100)
    opens_before_hours: int = Field(ge=2, le=768)
    closes_before_hours: int = Field(ge=1, le=767)

    @model_validator(mode="after")
    def validate_recurrence(self) -> "RecurringInput":
        if self.frequency not in {"daily", "weekly", "monthly"}:
            raise ValueError("Choose a daily, weekly, or monthly schedule")
        try:
            zone = ZoneInfo(self.time_zone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Choose a valid time zone") from error
        local = self.starts_at.astimezone(zone).replace(tzinfo=None)
        if local.replace(tzinfo=zone).timestamp() != self.starts_at.timestamp():
            raise ValueError("Event time must match the selected time zone")
        if self.closes_before_hours >= self.opens_before_hours:
            raise ValueError("Signups must open before they close")
        opening = datetime.fromtimestamp(
            self.starts_at.timestamp() - self.opens_before_hours * 3600, zone
        )
        now = datetime.now(zone)
        if opening <= now:
            raise ValueError(
                f"Open signup of {opening:%b %d, %Y, %I:%M:%S %p %Z} needs to "
                f"start after the current time {now:%b %d, %Y, %I:%M:%S %p %Z}."
            )
        return self


class EventTemplateInput(SignupWarningInput):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=200)
    duration_hours: int = Field(ge=1, le=768)
    tables: list[TableInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_template(self) -> "EventTemplateInput":
        if not self.title.strip():
            raise ValueError("Event title cannot be blank")
        if len({table.name.casefold() for table in self.tables}) != len(self.tables):
            raise ValueError("Table names must be unique")
        return self


class AssignmentSettingsInput(BaseModel):
    review_assignments_before_discord: bool = True
    model_config = {"extra": "forbid"}
    automatic_weight_adjustment: bool
    announce_table_changes: bool
    post_discord_updates_to_thread: bool = True
    timezone: str | None = Field(default=None, max_length=64)
    show_open_signup_players: bool = True
    dm_waitlist_promotions: bool = True

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("Choose a valid timezone") from error
        return value


class PlayerPairInput(BaseModel):
    model_config = {"extra": "forbid"}
    partner_id: str | None
    replace_partner_id: str | None = None


class PlayerProfileInput(BaseModel):
    model_config = {"extra": "forbid"}
    real_name: str | None = Field(default=None, max_length=100)
    guaranteed_seat: bool | None = None
    weighting: float | None = Field(default=None, ge=0.1, le=10.0, allow_inf_nan=False)

    @field_validator("real_name")
    @classmethod
    def clean_real_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class EventPlayerSettingInput(BaseModel):
    model_config = {"extra": "forbid"}
    weighting: float | None = Field(default=None, ge=0.1, le=10.0, allow_inf_nan=False)
    guaranteed_table: str | None = None


class ManagerSignupInput(BaseModel):
    model_config = {"extra": "forbid"}
    table: str = Field(min_length=1, max_length=35)
    name: str = Field(min_length=1, max_length=100)


class AssignedAddInput(BaseModel):
    model_config = {"extra": "forbid"}
    table: str = Field(min_length=1, max_length=35)


class OrganizationInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class OrganizationSelectionInput(BaseModel):
    organization_id: str | None = None


class OrganizationMemberInput(BaseModel):
    user_id: str
    role: str


class TestPopulationInput(BaseModel):
    players: int = Field(default=30, ge=0, le=1000)


class RetryAnnouncementInput(BaseModel):
    confirm_repost: bool = False
