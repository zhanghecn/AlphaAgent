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
        "scan_trace": [
            {
                "id": 1,
                "status": "ok",
                "started_at": "2026-08-04T10:00:00+08:00",
                "duration_ms": 2_410,
            }
        ],
    }
    requested: dict[str, int] = {}

    def get_live_recommendations(*, trend_page: int, oversold_page: int):
        requested["trend_page"] = trend_page
        requested["oversold_page"] = oversold_page
        return expected

    monkeypatch.setattr(low_suction, "get_live_recommendations", get_live_recommendations)

    response = TestClient(create_app()).get(
        "/api/low-suction/live?trend_page=3&oversold_page=4"
    )

    assert response.status_code == 200
    assert response.json()["data"] == expected
    assert requested == {"trend_page": 3, "oversold_page": 4}


def test_low_suction_live_reports_service_unavailable(monkeypatch) -> None:
    def unavailable(**_kwargs) -> dict[str, object]:
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
    monkeypatch.setattr(
        low_suction, "get_daily_backtest_rebuild_status", lambda: {"status": "idle"}
    )

    response = TestClient(create_app()).get("/api/low-suction/backtest")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ok"
    assert data["is_backtest"] is True
    assert data["report"]["coverage"] == payload["coverage"]
    assert data["rebuild"] == {"status": "idle"}
    # 交割单不从回测端点泄漏
    assert "ledger_days" not in data["report"]


def test_low_suction_backtest_rebuild_starts_and_reports_building(monkeypatch) -> None:
    monkeypatch.setattr(
        low_suction,
        "start_daily_backtest_rebuild",
        lambda: {"status": "building", "started_at": "2026-08-06T00:00:00+00:00"},
    )

    response = TestClient(create_app()).post("/api/low-suction/backtest/rebuild")

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "building"


def test_low_suction_backtest_rebuild_returns_409_when_already_running(monkeypatch) -> None:
    monkeypatch.setattr(
        low_suction,
        "start_daily_backtest_rebuild",
        lambda: {"status": "building", "already_running": True},
    )

    response = TestClient(create_app()).post("/api/low-suction/backtest/rebuild")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOW_SUCTION_BACKTEST_RUNNING"


def test_low_suction_backtest_status_endpoint_reads_state(monkeypatch) -> None:
    monkeypatch.setattr(
        low_suction,
        "get_daily_backtest_rebuild_status",
        lambda: {"status": "ready", "trade_days": 748, "finished_at": "2026-08-06T00:10:00+00:00"},
    )

    response = TestClient(create_app()).get("/api/low-suction/backtest/status")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert response.json()["data"]["trade_days"] == 748


def test_low_suction_backtest_reports_unrun_state(monkeypatch) -> None:
    monkeypatch.setattr(low_suction, "get_daily_backtest_report", lambda: None)
    monkeypatch.setattr(
        low_suction,
        "get_daily_backtest_rebuild_status",
        lambda: {
            "status": "building",
            "run_id": 27,
            "stage": "scan_candidates",
            "recent_runs": [{"id": 27, "status": "running"}],
        },
    )

    response = TestClient(create_app()).get("/api/low-suction/backtest")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "unavailable"
    assert data["rebuild"]["status"] == "building"
    assert data["rebuild"]["stage"] == "scan_candidates"


def test_low_suction_ledger_returns_recent_days(monkeypatch) -> None:
    payload = {
        "coverage": {"trade_days": 747},
        "label_convention": "D 日收盘买入、D+1 收盘结算，未扣费",
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
