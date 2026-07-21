from __future__ import annotations

import pytest

from alphaagent.server.services.low_suction.cross_regime_validation import (
    build_sequential_regime_audit,
)


def test_validation_uses_only_blocks_four_and_five() -> None:
    trades, signals = _evidence_rows()

    audit = build_sequential_regime_audit(
        trades,
        signals,
        bootstrap_draws=200,
    )

    assert audit["split"] == {
        "development_blocks": ["block_1", "block_2", "block_3"],
        "validation_blocks": ["block_4", "block_5"],
        "validation_policy": "frozen_rule_rejection_only",
    }
    assert audit["development"]["closed_trades"] == 60
    assert audit["validation"]["closed_trades"] == 40
    assert [row["id"] for row in audit["validation_time_blocks"]] == [
        "block_4",
        "block_5",
    ]


def test_validation_fails_when_one_material_phase_is_below_sixty_percent() -> None:
    trades, signals = _evidence_rows()

    audit = build_sequential_regime_audit(
        trades,
        signals,
        bootstrap_draws=200,
    )

    phases = {row["id"]: row for row in audit["validation_market_phases"]}
    assert phases["rotation"]["win_rate_pct"] == pytest.approx(80.0)
    assert phases["warming"]["win_rate_pct"] == pytest.approx(55.0)
    assert audit["qualification"]["sequential_cross_regime_passed"] is False
    assert (
        "validation_phase_win_rate<=60pct:warming"
        in audit["qualification"]["failed_gates"]
    )
    assert audit["qualification"]["qualified_validation_phases"] == [
        "rotation"
    ]


def test_cost_stress_reprices_every_trade_without_changing_count() -> None:
    trades, signals = _evidence_rows()

    audit = build_sequential_regime_audit(
        trades,
        signals,
        bootstrap_draws=200,
    )

    double_cost = audit["cost_stress"][1]
    assert double_cost["extra_cost_pct"] == pytest.approx(0.2)
    assert double_cost["full_history"]["closed_trades"] == 100
    assert double_cost["validation"]["closed_trades"] == 40
    assert double_cost["validation"]["mean_net_return_pct"] == pytest.approx(
        audit["validation"]["mean_net_return_pct"] - 0.2
    )


def test_audit_rejects_missing_or_duplicate_signal_identity() -> None:
    trades, signals = _evidence_rows()

    with pytest.raises(ValueError, match="signal identities must be unique"):
        build_sequential_regime_audit(
            trades,
            [*signals, signals[0]],
            bootstrap_draws=10,
        )

    with pytest.raises(ValueError, match="trade signal is missing"):
        build_sequential_regime_audit(
            [*trades, {**trades[0], "signal_id": "missing"}],
            signals,
            bootstrap_draws=10,
        )


def test_cluster_bootstrap_and_concentration_are_deterministic() -> None:
    trades, signals = _evidence_rows()

    first = build_sequential_regime_audit(
        trades,
        signals,
        bootstrap_draws=200,
        bootstrap_seed=7,
    )
    second = build_sequential_regime_audit(
        trades,
        signals,
        bootstrap_draws=200,
        bootstrap_seed=7,
    )

    assert first["confidence"] == second["confidence"]
    assert first["concentration"] == second["concentration"]
    assert first["confidence"]["bootstrap_draws"] == 200
    assert first["concentration"]["symbol"]["id"] == "600001.SSE"


def _evidence_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    trades: list[dict[str, object]] = []
    signals: list[dict[str, object]] = []
    for block in range(1, 6):
        phase = "rotation" if block == 4 else "warming"
        for position in range(20):
            signal_id = f"signal-{block}-{position}"
            if block == 4:
                won = position < 16
            elif block == 5:
                won = position < 11
            else:
                won = position < 14
            net_return = 2.0 if won else -1.0
            entry_date = f"202{block}-01-{position + 1:02d}"
            trades.append(
                {
                    "variant": "cross_regime_support_reclaim_confirmation",
                    "signal_id": signal_id,
                    "campaign_id": f"campaign-{block}-{position // 2}",
                    "entry_date": entry_date,
                    "time_block": f"block_{block}",
                    "market_phase": phase,
                    "vt_symbol": "600001.SSE" if position < 2 else f"600{position + 1:03d}.SSE",
                    "net_return_pct": net_return,
                }
            )
            signals.append(
                {
                    "signal_id": signal_id,
                    "concept_name": "集中概念" if position < 2 else f"概念{position}",
                }
            )
    return trades, signals
