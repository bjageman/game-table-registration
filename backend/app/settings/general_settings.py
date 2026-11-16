"""General Settings contract; the legacy assignment endpoint remains stable."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class GeneralSettingsValues(BaseModel):
    create_discord_event: bool = True
    review_assignments_before_discord: bool = True
    model_config = {"extra": "forbid"}
    automatic_weight_adjustment: bool = True
    announce_table_changes: bool = True
    post_discord_updates_to_thread: bool = True
    timezone: str | None = Field(default=None, max_length=64)
    show_open_signup_players: bool = True
    dm_waitlist_promotions: bool = True
    dm_assignments: bool = True

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("Choose a valid timezone") from error
        return value


class GeneralSettingsInput(GeneralSettingsValues):
    # Keep these fields required for compatibility with existing clients.
    automatic_weight_adjustment: bool = Field(...)
    announce_table_changes: bool = Field(...)


BOOLEAN_DEFAULTS: dict[str, bool] = {
    name: value
    for name, value in GeneralSettingsValues().model_dump().items()
    if isinstance(value, bool)
}


def settings_values(saved: object) -> dict[str, object]:
    return {name: getattr(saved, name) for name in GeneralSettingsValues.model_fields}
