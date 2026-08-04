from __future__ import annotations

from fastapi.testclient import TestClient

from alphaagent.server.api import low_suction
from alphaagent.server.main import create_app


def test_low_suction_swing_research_has_an_independent_endpoint(monkeypatch) -> None:
    expected = {
        "research_version": "cross-regime-support-reclaim-proxy-v1",
        "research_kind": "dynamic_leader_cross_regime_pullback",
        "contract": {"holding_style": "d1_loss_then_structural"},
    }
    monkeypatch.setattr(low_suction, "get_swing_research", lambda: expected)

    response = TestClient(create_app()).get("/api/reverse-wrap/swing-research")

    assert response.status_code == 200
    assert response.json()["data"] == expected


def test_low_suction_swing_research_reports_retired_status_unavailable(
    monkeypatch,
) -> None:
    def unavailable() -> dict[str, object]:
        raise ValueError("retired status unavailable")

    monkeypatch.setattr(low_suction, "get_swing_research", unavailable)

    response = TestClient(create_app()).get("/api/reverse-wrap/swing-research")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LOW_SUCTION_RESEARCH_UNAVAILABLE"


def test_low_suction_strategy_has_an_independent_read_only_endpoint(monkeypatch) -> None:
    expected = {
        "strategy_version": "low-suction-swing-paper-v1",
        "execution_mode": "paper",
        "broker_orders_enabled": False,
        "session": {"status": "market_closed", "trade_date": "2026-07-19"},
    }
    monkeypatch.setattr(
        low_suction,
        "get_swing_strategy_overview",
        lambda: expected,
        raising=False,
    )

    response = TestClient(create_app()).get("/api/reverse-wrap/strategy")

    assert response.status_code == 200
    assert response.json()["data"] == expected


def test_cross_regime_validation_has_a_read_only_endpoint(monkeypatch) -> None:
    expected = {
        "report_version": "cross-regime-validation-product-v1",
        "formal_strategy": False,
    }
    monkeypatch.setattr(
        low_suction,
        "get_cross_regime_validation",
        lambda: expected,
    )

    response = TestClient(create_app()).get(
        "/api/reverse-wrap/cross-regime-validation"
    )

    assert response.status_code == 200
    assert response.json()["data"] == expected


def test_low_suction_history_endpoint_reads_materialized_overview(monkeypatch) -> None:
    expected = {
        "latest_run": {
            "run_id": "replay-1",
            "evidence_level": "exploratory_survivorship_proxy",
        },
        "latest_strict_run": None,
        "formal_strategy": False,
        "exploratory_counts_toward_qualification": False,
    }
    monkeypatch.setattr(low_suction, "get_historical_replay_overview", lambda: expected)

    response = TestClient(create_app()).get("/api/reverse-wrap/history")

    assert response.status_code == 200
    assert response.json()["data"] == expected


def test_low_suction_history_trade_filters_are_forwarded(monkeypatch) -> None:
    captured = {}

    def fake_list(**filters):
        captured.update(filters)
        return {"items": [], "total": 0, "page": 2, "page_size": 10}

    monkeypatch.setattr(low_suction, "get_historical_replay_trades", fake_list)

    response = TestClient(create_app()).get(
        "/api/reverse-wrap/history/trades",
        params={
            "run_id": "replay-1",
            "page": 2,
            "page_size": 10,
            "market_phase": "rotation",
            "outcome": "winner",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 0
    assert captured["run_id"] == "replay-1"
    assert captured["market_phase"] == "rotation"
    assert captured["outcome"] == "winner"


def test_low_suction_history_trade_detail_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(low_suction, "get_historical_replay_trade", lambda **_: None)

    response = TestClient(create_app()).get(
        "/api/reverse-wrap/history/trades/missing",
        params={"run_id": "replay-1"},
    )

    assert response.status_code == 404


def test_low_suction_forward_ledger_is_read_only_and_paginated(monkeypatch) -> None:
    expected = {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
        "historical_backfill_allowed": False,
    }
    monkeypatch.setattr(low_suction, "list_causal_forward_ledger", lambda **_: expected)

    response = TestClient(create_app()).get("/api/reverse-wrap/forward-ledger")

    assert response.status_code == 200
    assert response.json()["data"] == expected
