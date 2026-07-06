from __future__ import annotations

from datetime import date

from alphaagent.server.services.quant.factors import DRAGON_PULLBACK_STRATEGY_ID, SignalScore
from alphaagent.server.services.quant import screening_payloads


def test_recommendation_to_api_explains_low_suction_factors() -> None:
    score = SignalScore(
        vt_symbol="002407.SZSE",
        trade_date=date(2026, 6, 9),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.5,
        liquidity_score=80.0,
        risk_score=70.0,
        entry_signal=True,
        evidence={
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "ma5_distance_pct": 1.74,
            "ma10_distance_pct": 0.14,
            "ma_convergence_pct": 2.8,
            "support_type": "ma5_reclaim",
            "failed_rules": [],
        },
    )

    payload = screening_payloads.recommendation_to_api(1, score)

    explain = payload["strategy_explain"]
    assert explain["strategy_id"] == DRAGON_PULLBACK_STRATEGY_ID
    assert explain["strategy_name"] == "主线龙回头回踩低吸"
    assert explain["candidate_family"] == "low_suction_launch"
    assert explain["candidate_family_label"] == "低吸首启"
    assert "低吸首启" in explain["setup_labels"]
    factor_labels = {row["label"] for row in explain["positive_factors"]}
    assert {"低吸蓄势", "MA5距离", "MA10距离", "均线收敛"} <= factor_labels
    assert explain["research_only"] is False


def test_recommendation_row_to_api_explains_bottom_reclaim_repair() -> None:
    payload = screening_payloads.recommendation_row_to_api(
        {
            "trade_date": date(2026, 6, 9),
            "vt_symbol": "002407.SZSE",
            "stock_name": "多氟多",
            "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
            "strategy_version": "0.1.42",
            "rank": 7,
            "action": "WATCH",
            "total_score": 78.2,
            "reason": {
                "setup_type": "oversold_rebound_start",
                "entry_setup": "oversold_rebound_start",
                "setup_family": "oversold_rebound_start",
                "rebound_subtype": "bottom_reclaim",
                "bottom_reclaim": True,
                "bottom_reclaim_notes": ["首次收复MA5", "贴近MA10起步"],
                "drawdown_from_20d_high_pct": -22.5,
                "rebound_from_20d_low_pct": 7.8,
                "ma5_distance_pct": 1.74,
                "ma10_distance_pct": 0.14,
                "ma20_distance_pct": -5.28,
                "bottom_ma_repair_stage": "ma10_reclaim",
                "bottom_ma_repair_strength_score": 82.0,
                "bottom_ma_repair_strength_bucket": "strong_repair",
                "ma5_distance_delta_3d": 3.8,
                "ma10_distance_delta_3d": 8.0,
                "timing_window": "after_silver_6_20",
                "market_phase": "retreat",
                "not_used_for_signal_score": True,
                "failed_rules": ["reclaim_confirmation"],
            },
        }
    )

    explain = payload["strategy_explain"]
    assert payload["name"] == "多氟多"
    assert explain["candidate_family"] == "bottom_reclaim"
    assert explain["candidate_family_label"] == "超跌反弹起步"
    assert "MA10已收复" in explain["setup_labels"]
    assert "底部强修复" in explain["setup_labels"]
    assert explain["not_used_for_signal_score"] is True
    assert explain["research_only"] is True
    factor_labels = {row["label"] for row in explain["positive_factors"]}
    assert {"20日高点回撤", "20日低点反弹", "底部均线修复", "MA10三日修复"} <= factor_labels
    market_values = {row["value"] for row in explain["market_context"]}
    assert {"银手指后6-20日", "退潮"} <= market_values
    assert explain["risk_factors"][0]["label"] == "弱转强确认不足"


def test_recommendation_to_api_explains_scored_oversold_rebound_as_default_route() -> None:
    score = SignalScore(
        vt_symbol="603260.SSE",
        trade_date=date(2026, 6, 9),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=84.2,
        liquidity_score=80.0,
        risk_score=55.0,
        entry_signal=True,
        evidence={
            "setup_type": "oversold_rebound_start",
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "rebound_subtype": "secondary_breakout_confirm",
            "secondary_breakout_confirm": True,
            "bottom_reclaim": False,
            "drawdown_from_20d_high_pct": -14.1,
            "rebound_from_20d_low_pct": 11.7,
            "bottom_ma_repair_strength_score": 82.0,
            "failed_rules": [],
        },
    )

    payload = screening_payloads.recommendation_to_api(1, score)

    explain = payload["strategy_explain"]
    assert explain["strategy_id"] == DRAGON_PULLBACK_STRATEGY_ID
    assert explain["candidate_family"] == "secondary_breakout_confirm"
    assert explain["candidate_family_label"] == "超跌反弹二次确认"
    assert explain["research_only"] is False
    assert explain["not_used_for_signal_score"] is False
    assert payload["reason"]["signal_label"] == "超跌反弹二次确认"
