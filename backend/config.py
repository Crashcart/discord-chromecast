from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Plex
    plex_url: str = "http://localhost:32400"
    plex_token: str = ""

    # Redis
    redis_url: str = "redis://redis:6379"

    # CORS — space-separated origins
    allowed_origins: str = "http://localhost:3000"

    # Discord (used by bot, not backend — kept here for shared .env)
    discord_token: str = ""
    discord_app_id: str = ""

    # Backend URL (used by bot to reach the backend)
    backend_url: str = "http://backend:8000"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split() if o.strip()]


settings = Settings()
