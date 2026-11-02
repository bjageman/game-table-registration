import json

import pytest
from fastapi.testclient import TestClient

from app.branding import Branding, load_branding
from app.config import Settings
from app.main import create_app


def test_missing_file_uses_table_signup_defaults(tmp_path):
    assert load_branding(str(tmp_path / "missing.json")) == Branding()


def test_branding_file_is_public_and_sets_api_title(tmp_path):
    path = tmp_path / "branding.json"
    path.write_text(
        json.dumps(
            {
                "name": "  Game Night  ",
                "tagline": "Find your next table.",
                "logo_url": "https://example.org/logo.svg",
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        Settings(
            _env_file=None,
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            branding_config_file=str(path),
            discord_gateway_enabled=False,
            announcement_worker_enabled=False,
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/branding").json() == {
            "name": "Game Night",
            "tagline": "Find your next table.",
            "logo_url": "https://example.org/logo.svg",
        }
        assert client.get("/openapi.json").json()["info"]["title"] == "Game Night"
    app.state.engine.dispose()


@pytest.mark.parametrize(
    "content",
    ['{"name": " "}', '{"logo_url": "javascript:alert(1)"}', '{"unknown": 1}', "{"],
)
def test_invalid_branding_file_is_rejected(tmp_path, content):
    path = tmp_path / "branding.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid branding config"):
        load_branding(str(path))
