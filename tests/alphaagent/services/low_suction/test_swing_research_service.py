from __future__ import annotations

import json

import pytest

from alphaagent.server.services.low_suction.swing_research_service import (
    REPORT_PATH,
    get_swing_research,
)


def test_swing_research_exposes_the_cross_regime_proxy_without_full_ledger_load() -> None:
    research = get_swing_research()

    assert research["research_version"] == "cross-regime-support-reclaim-proxy-v1"
    assert research["research_kind"] == "dynamic_leader_cross_regime_pullback"
    assert research["policy_version"] == "causal-leader-pullback-cross-regime-v3"
    assert research["formal_strategy"] is False
    assert research["historical_proxy_gate_passed"] is True
    assert REPORT_PATH.stat().st_size < 1_000_000
    assert research["contract"]["holding_style"] == "d1_loss_then_structural"
    assert research["contract"]["portfolio"]["capacity"] == 4
    assert research["coverage"]["policy_confirmations"] == 234
    assert research["coverage"]["selected_trades"] == 107
    assert research["performance"]["closed_trades"] == 105
    assert research["performance"]["win_rate_pct"] == pytest.approx(66.6666667)
    assert research["performance"]["signal_win_rate_pct"] == pytest.approx(
        67.2897196
    )
    assert research["performance"]["compound_return_pct"] == pytest.approx(
        82.0273629
    )
    assert research["performance"]["maximum_drawdown_pct"] == pytest.approx(
        -4.0879360
    )
    assert research["performance"]["mean_trade_return_pct"] == pytest.approx(
        2.3158331
    )
    assert research["performance"]["profit_factor"] == pytest.approx(2.8683240)
    assert len(research["cases"]) == 107
    assert tuple(row["id"] for row in research["time_blocks"]) == (
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    )

    serialized = json.dumps(research, ensure_ascii=False)
    assert "leader-ma5-close-proxy-v1" not in serialized
    assert "prebreakout-ignition-diffusion-v1" not in serialized
    assert "5 分钟线" not in serialized
    assert any(
        "分钟线和资金流均未参与信号选择" in boundary
        for boundary in research["boundaries"]
    )


def test_swing_research_exposes_two_qualified_market_phases() -> None:
    research = get_swing_research()
    phases = {row["id"]: row for row in research["market_phases"]}

    assert tuple(phases) == ("rotation", "warming")
    assert phases["rotation"]["closed_trades"] == 42
    assert phases["rotation"]["win_rate_pct"] == pytest.approx(69.0476190)
    assert phases["warming"]["closed_trades"] == 65
    assert phases["warming"]["win_rate_pct"] == pytest.approx(66.1538462)
    assert research["qualification"]["qualified_market_phases"] == [
        "rotation",
        "warming",
    ]
    assert research["qualification"]["formal_blockers"] == [
        "sequential_cross_regime_validation_failed",
        "strict_historical_membership_missing",
        "same_close_execution_is_research_proxy",
    ]


def test_swing_research_exposes_sequential_regime_failure() -> None:
    research = get_swing_research()
    audit = research["sequential_audit"]
    phases = {row["id"]: row for row in audit["validation_market_phases"]}

    assert research["research_status"] == (
        "historical_proxy_point_gate_passed_sequential_regime_failed"
    )
    assert research["qualification"]["full_history_point_gate_passed"] is True
    assert research["qualification"]["sequential_cross_regime_passed"] is False
    assert audit["validation"]["closed_trades"] == 48
    assert audit["validation"]["win_rate_pct"] == pytest.approx(66.6666667)
    assert phases["rotation"]["closed_trades"] == 20
    assert phases["rotation"]["win_rate_pct"] == pytest.approx(80.0)
    assert phases["warming"]["closed_trades"] == 28
    assert phases["warming"]["win_rate_pct"] == pytest.approx(57.1428571)
    assert audit["confidence"][
        "validation_wilson_95_lower_win_rate_pct"
    ] == pytest.approx(52.5401097)


def test_swing_research_keeps_stability_limitations_visible() -> None:
    research = get_swing_research()
    stability = research["stability"]

    assert stability["all_five_blocks_above_60pct"] is True
    assert stability["wilson_95_lower_win_rate_pct"] == pytest.approx(
        57.9359691
    )
    assert any("2026 warming" in warning for warning in stability["warnings"])
    assert research["evidence_boundary"] == {
        "same_close_research_proxy": True,
        "strict_historical_membership": False,
        "point_in_time_executable": False,
        "forward_validation_required": True,
    }
