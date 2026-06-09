from alphaagent.server.core.config import Settings


def test_cors_origins_are_parsed() -> None:
    settings = Settings(CORS_ORIGINS="http://localhost:5173, http://localhost:8000")

    assert settings.cors_origin_list == ["http://localhost:5173", "http://localhost:8000"]

