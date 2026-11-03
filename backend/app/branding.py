"""Public, server-owned branding for the moderator UI."""

import json
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class Branding(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(default="TableSignup", min_length=1, max_length=80)
    tagline: str = Field(default="Made for your next game night.", max_length=160)
    logo_url: str | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Brand name cannot be blank")
        return value

    @field_validator("logo_url")
    @classmethod
    def valid_logo_url(cls, value: str | None) -> str | None:
        if value is not None and not (
            value.startswith("https://")
            or value.startswith("/")
            and not value.startswith("//")
        ):
            raise ValueError("Logo URL must be HTTPS or a root-relative path")
        return value


def load_branding(path: str) -> Branding:
    file = Path(path)
    if not file.exists():
        return Branding()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        return Branding.model_validate(data)
    except (OSError, ValueError) as error:
        raise ValueError(f"Invalid branding config at {file}: {error}") from error
