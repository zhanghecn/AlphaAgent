from alphaagent.server.core.config import get_settings
from alphaagent.server.db import session as db_session


def test_get_engine_uses_configured_pool_settings(monkeypatch):
    captured = {}

    class FakeEngine:
        def dispose(self):
            pass

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeEngine()

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/alphaagent")
    monkeypatch.setenv("DATABASE_POOL_SIZE", "12")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "7")
    monkeypatch.setenv("DATABASE_POOL_TIMEOUT_SECONDS", "45")
    get_settings.cache_clear()
    db_session.reset_engine()
    monkeypatch.setattr(db_session, "create_engine", fake_create_engine)

    try:
        db_session.get_engine()
    finally:
        db_session.reset_engine()
        get_settings.cache_clear()

    assert captured["url"] == "postgresql+psycopg://user:pass@localhost:5432/alphaagent"
    assert captured["kwargs"]["pool_size"] == 12
    assert captured["kwargs"]["max_overflow"] == 7
    assert captured["kwargs"]["pool_timeout"] == 45.0
    assert captured["kwargs"]["pool_pre_ping"] is True
