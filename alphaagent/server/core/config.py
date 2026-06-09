"""Runtime configuration for the AlphaAgent server."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    alphaagent_env: str = Field(default="local", alias="ALPHAAGENT_ENV")
    api_host: str = Field(default="0.0.0.0", alias="ALPHAAGENT_API_HOST")
    api_port: int = Field(default=8000, alias="ALPHAAGENT_API_PORT")
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:8000", alias="CORS_ORIGINS")
    database_url: str = Field(default="", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://host.docker.internal:6379/0", alias="REDIS_URL")
    market_timeout_seconds: float = Field(default=8.0, alias="MARKET_TIMEOUT_SECONDS")
    market_page_size: int = Field(default=50, alias="MARKET_PAGE_SIZE")

    @property
    def cors_origin_list(self) -> list[str]:
        """Return parsed CORS origins."""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached server settings."""

    return Settings()
