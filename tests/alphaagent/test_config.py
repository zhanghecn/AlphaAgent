from alphaagent.server.core.config import Settings


def test_cors_origins_are_parsed() -> None:
    settings = Settings(CORS_ORIGINS="http://localhost:5173, http://localhost:8000")

    assert settings.cors_origin_list == ["http://localhost:5173", "http://localhost:8000"]


def test_expensive_startup_warmups_are_opt_in() -> None:
    default = Settings(_env_file=None)
    enabled = Settings(
        _env_file=None,
        ALPHAAGENT_STARTUP_DATA_SYNC_SCHEDULER="false",
        ALPHAAGENT_STARTUP_MARKET_CACHE_WARMUP="true",
        ALPHAAGENT_STARTUP_INTRADAY_REFRESHER="true",
    )

    assert default.startup_data_sync_scheduler is True
    assert default.startup_market_cache_warmup is False
    assert default.startup_intraday_refresher is False
    assert enabled.startup_data_sync_scheduler is False
    assert enabled.startup_market_cache_warmup is True
    assert enabled.startup_intraday_refresher is True
