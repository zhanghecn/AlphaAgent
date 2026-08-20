from contextlib import contextmanager

from alphaagent.server.api import market_timing


def test_timing_panel_get_reads_materialized_panel_without_calculating(monkeypatch) -> None:
    stored = {
        "overview": {"direction": "NEUTRAL"},
        "data_origin": "local_db",
        "storage_table": "market_timing_panel",
    }

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(market_timing, "is_database_configured", lambda: True)
    monkeypatch.setattr(market_timing, "session_scope", fake_session_scope)
    monkeypatch.setattr(market_timing, "load_stored_market_timing_panel", lambda *_args: stored)
    monkeypatch.setattr(
        market_timing,
        "refresh_market_timing_panel",
        lambda *_args: (_ for _ in ()).throw(AssertionError("GET must not calculate")),
    )

    response = market_timing.get_panel()

    assert response == {"success": True, "data": stored, "error": None, "request_id": "req_local"}


def test_timing_panel_get_reports_initializing_when_worker_has_no_snapshot(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(market_timing, "is_database_configured", lambda: True)
    monkeypatch.setattr(market_timing, "session_scope", fake_session_scope)
    monkeypatch.setattr(market_timing, "load_stored_market_timing_panel", lambda *_args: None)

    response = market_timing.get_panel()

    assert response.status_code == 503
    assert b"MARKET_TIMING_INITIALIZING" in response.body
