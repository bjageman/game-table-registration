from app.config import Settings


def test_discord_credentials_use_standard_environment_names(monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "client")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "secret")
    settings = Settings(_env_file=None)
    assert settings.discord_client_id == "client"
    assert settings.discord_client_secret == "secret"


def test_legacy_discord_environment_names_are_not_supported(monkeypatch):
    monkeypatch.delenv("DISCORD_CLIENT_ID", raising=False)
    monkeypatch.delenv("DISCORD_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("DISCORD_BOT_CLIENTID", "legacy-client")
    monkeypatch.setenv("DISCORD_BOT_CLIENTSECRET", "legacy-secret")
    settings = Settings(_env_file=None)
    assert settings.discord_client_id == ""
    assert settings.discord_client_secret == ""
    assert not settings.configured


def test_shared_app_does_not_require_a_default_server():
    settings = Settings(
        _env_file=None,
        discord_client_id="client",
        discord_client_secret="secret",
        discord_bot_token="token",
    )
    assert settings.configured


def test_test_signup_allowlist_defaults_to_owner_and_supports_additional_ids():
    from app.test_signups import allowed

    config = Settings(
        _env_file=None, owner_discord_id="owner", test_signup_user_ids="second, third "
    )
    assert allowed("owner", config)
    assert allowed("second", config)
    assert allowed("third", config)
    assert not allowed("stranger", config)
    assert not allowed("owner", Settings(_env_file=None))
