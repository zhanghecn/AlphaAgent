from __future__ import annotations

from fastapi.testclient import TestClient

from alphaagent.server.api import low_suction
from alphaagent.server.main import create_app


def test_low_suction_live_has_an_independent_endpoint(monkeypatch) -> None:
    expected = {
        "status": "ok",
        "trade_date": "2026-08-04",
        "provisional": False,
        "trend": {"total": 1, "items": [{"vt_symbol": "600396.SSE", "score": 82.5}]},
        "oversold": {"total": 0, "items": []},
    }
    monkeypatch.setattr(low_suction, "get_live_recommendations", lambda: expected)

    response = TestClient(create_app()).get("/api/low-suction/live")

    assert response.status_code == 200
    assert response.json()["data"] == expected


def test_low_suction_live_reports_service_unavailable(monkeypatch) -> None:
    def unavailable() -> dict[str, object]:
        raise RuntimeError("database down")

    monkeypatch.setattr(low_suction, "get_live_recommendations", unavailable)

    response = TestClient(create_app()).get("/api/low-suction/live")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LOW_SUCTION_LIVE_UNAVAILABLE"


def test_low_suction_backtest_reads_materialized_report(monkeypatch) -> None:
    payload = {
        "version": "low-suction-daily-backtest-v1",
        "coverage": {"trade_days": 747},
        "families": {"trend_pullback": {"bands": {}}},
        "position_sim": {"combined": {"compound_pct": 33.85}},
        "ledger_days": [{"trade_date": "2026-07-31", "legs": []}],
    }
    monkeypatch.setattr(low_suction, "get_daily_backtest_report", lambda: payload)

    response = TestClient(create_app()).get("/api/low-suction/backtest")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["is_backtest"] is True
    assert data["report"]["coverage"] == payload["coverage"]
    # 交割单不从回测端点泄漏
    assert "ledger_days" not in data["report"]


def test_low_suction_backtest_reports_unrun_state(monkeypatch) -> None:
    monkeypatch.setattr(low_suction, "get_daily_backtest_report", lambda: None)

    response = TestClient(create_app()).get("/api/low-suction/backtest")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "unavailable"


def test_low_suction_ledger_returns_recent_days(monkeypatch) -> None:
    payload = {
        "coverage": {"trade_days": 747},
        "label_convention": "D+1 收盘到收盘，未扣费",
        "ledger_days": [
            {
                "trade_date": "2026-07-31",
                "day_return_pct": 0.42,
                "legs": [{"vt_symbol": "600396.SSE", "stock_name": "华电辽能"}],
            }
        ],
    }
    monkeypatch.setattr(low_suction, "get_daily_backtest_report", lambda: payload)

    response = TestClient(create_app()).get("/api/low-suction/ledger")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["ledger_days"] == payload["ledger_days"]
    assert data["coverage"] == payload["coverage"]


def test_low_suction_ledger_reports_service_unavailable(monkeypatch) -> None:
    def unavailable() -> dict[str, object] | None:
        raise RuntimeError("database down")

    monkeypatch.setattr(low_suction, "get_daily_backtest_report", unavailable)

    response = TestClient(create_app()).get("/api/low-suction/ledger")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LOW_SUCTION_LEDGER_UNAVAILABLE"
