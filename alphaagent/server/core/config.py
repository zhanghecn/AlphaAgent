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
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175,http://localhost:5176,http://127.0.0.1:5176,http://localhost:5177,http://127.0.0.1:5177,http://localhost:8000,http://127.0.0.1:8000,http://localhost:8001,http://127.0.0.1:8001,http://localhost:8002,http://127.0.0.1:8002,http://localhost:8003,http://127.0.0.1:8003",
        alias="CORS_ORIGINS",
    )
    database_url: str = Field(default="", alias="DATABASE_URL")
    database_pool_size: int = Field(default=20, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=20, alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout_seconds: float = Field(default=60.0, alias="DATABASE_POOL_TIMEOUT_SECONDS")
    redis_url: str = Field(default="redis://host.docker.internal:6379/0", alias="REDIS_URL")
    market_timeout_seconds: float = Field(default=8.0, alias="MARKET_TIMEOUT_SECONDS")
    market_page_size: int = Field(default=50, alias="MARKET_PAGE_SIZE")
    startup_data_sync_scheduler: bool = Field(
        default=True,
        alias="ALPHAAGENT_STARTUP_DATA_SYNC_SCHEDULER",
    )
    startup_backtest_warmup: bool = Field(
        default=False,
        alias="ALPHAAGENT_STARTUP_BACKTEST_WARMUP",
    )
    startup_next_session_plan_warmup: bool = Field(
        default=False,
        alias="ALPHAAGENT_STARTUP_NEXT_SESSION_PLAN_WARMUP",
    )
    startup_market_cache_warmup: bool = Field(
        default=False,
        alias="ALPHAAGENT_STARTUP_MARKET_CACHE_WARMUP",
    )
    startup_intraday_refresher: bool = Field(
        default=False,
        alias="ALPHAAGENT_STARTUP_INTRADAY_REFRESHER",
    )
    tushare_token: str = Field(default="", alias="TUSHARE_TOKEN")
    tushare_api_url: str = Field(default="https://api.tushare.pro", alias="TUSHARE_API_URL")
    tushare_timeout_seconds: float = Field(default=12.0, alias="TUSHARE_TIMEOUT_SECONDS")

    @property
    def cors_origin_list(self) -> list[str]:
        """Return parsed CORS origins."""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached server settings."""

    return Settings()
