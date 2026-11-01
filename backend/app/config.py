from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    test_signup_user_ids: str = ""
    announcement_worker_enabled: bool = True
    database_url: str = "sqlite:///./local.db"
    public_url: str = "http://localhost:5180"
    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    discord_channel_id: str = ""
    owner_discord_id: str = ""
    moderator_role_ids: str = ""

    @property
    def configured(self) -> bool:
        return all(
            (
                self.discord_client_id,
                self.discord_client_secret,
                self.discord_bot_token,
            )
        )

    @property
    def callback_url(self) -> str:
        return f"{self.public_url}/api/auth/callback"
