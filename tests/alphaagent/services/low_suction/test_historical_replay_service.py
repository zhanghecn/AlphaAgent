from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import historical_replay_service as service


def _selected_trade() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": "signal-1",
                "campaign_id": "campaign-1",
                "sector_id": "BK0001",
                "vt_symbol": "000001.SZSE",
                "wave_number": 2,
                "support_line": "MA10",
                "support_depth": 2,
                "support_test_date": date(2026, 6, 24),
                "dynamic_rank": 1,
                "entry_date": date(2026, 6, 25),
                "entry_price": 10.0,
                "d1_date": date(2026, 6, 26),
                "d1_close": 10.5,
                "d1_net_return_pct": 4.8,
                "exit_date": date(2026, 6, 27),
                "exit_price": 10.8,
                "exit_reason": "higher_high_confirmed",
                "holding_sessions": 2,
                "net_return_pct": 7.8,
                "market_phase": "uptrend",
                "time_block": "block_1",
                "variant": "causal-leader-pullback-three-phase-adaptive-v1",
            }
        ]
    )


def test_build_ledger_keeps_stock_concept_support_and_d1_evidence() -> None:
    signals = pd.DataFrame(
        [
            {
                "signal_id": "signal-1",
                "concept_name": "光通信",
                "support_price": 9.9,
                "signal_date": date(2026, 6, 25),
            }
        ]
    )
    memberships = pd.DataFrame(
        [{"vt_symbol": "000001.SZSE", "stock_name": "示例股份"}]
    )

    ledger = service._build_ledger(_selected_trade(), signals, memberships)

    row = ledger.iloc[0]
    assert row["stock_name"] == "示例股份"
    assert row["concept_name"] == "光通信"
    assert row["support_line"] == "MA10"
    assert row["d1_net_return_pct"] == 4.8


def test_regression_artifact_is_validation_not_trade_input(monkeypatch) -> None:
    artifact = {
        "historical_metrics": {
            "full_history": {
                "trades": 1,
                "win_rate_pct": 100.0,
                "mean_net_return_pct": 7.8,
            },
            "two_slot_cash": {
                "closed_trades": 1,
                "compound_return_pct": 1.95,
            },
        }
    }
    metrics = {
        "trades": 1,
        "positive_rate_pct": 100.0,
        "mean_net_return_pct": 7.8,
        "two_slot_cash": {"closed_trades": 1, "compound_return_pct": 1.95},
    }

    service._verify_regression(metrics, artifact)

    metrics["trades"] = 2
    with pytest.raises(ValueError, match="database replay"):
        service._verify_regression(metrics, artifact)


def test_overview_never_builds_replay(monkeypatch) -> None:
    calls: list[str | None] = []

    def fake_latest(*, evidence_level=None):
        calls.append(evidence_level)
        return None

    monkeypatch.setattr(service, "load_latest_replay_run", fake_latest)
    monkeypatch.setattr(
        service,
        "build_exploratory_three_phase_replay",
        lambda: pytest.fail("GET view must not run historical replay"),
    )

    result = service.get_historical_replay_overview()

    assert result["strict_history_available"] is False
    assert result["exploratory_counts_toward_qualification"] is False
    assert calls == [None, "strict_point_in_time"]


def test_overview_separates_all_trade_quality_from_two_slot_account(
    monkeypatch,
) -> None:
    stored = {
        "run_id": "run-1",
        "trade_count": 89,
        "metrics": {
            "trades": 89,
            "positive_rate_pct": 76.4,
            "mean_net_return_pct": 3.08,
            "two_slot_cash": {
                "signals": 89,
                "closed_trades": 81,
                "compound_return_pct": 230.07,
                "maximum_drawdown_pct": -7.89,
            },
        },
    }
    monkeypatch.setattr(
        service,
        "load_latest_replay_run",
        lambda *, evidence_level=None: None if evidence_level else stored,
    )

    run = service.get_historical_replay_overview()["latest_run"]

    assert run["metrics"]["all_trade_quality"]["trades"] == 89
    assert run["metrics"]["two_slot_compound_backtest"]["closed_trades"] == 81
    assert run["metrics"]["two_slot_compound_backtest"]["compound_return_pct"] == 230.07
