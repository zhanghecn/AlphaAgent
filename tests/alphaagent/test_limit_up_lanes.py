from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up import history_engine, history_service
from alphaagent.server.services.limit_up.lane_features import (
    attach_limit_gene_features,
    classify_financial_risk,
    intraday_path_times,
    path_prefix_features,
    select_latest_published_report,
)
from alphaagent.server.services.limit_up.lane_research import (
    BOARD_LANES,
    classify_board_lane,
    evaluate_lane_candidate,
    first_board_support_score,
    select_daily_lane_portfolio,
)
from alphaagent.server.services.limit_up.lane_repository import (
    build_financial_index,
    financial_report_as_of,
    financial_snapshot_as_of,
    merge_rich_event_rows,
)


def _daily_rows() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=132)
    close = [10.0] * len(dates)
    frame = pd.DataFrame(
        {
            "vt_symbol": "600001.SSE",
            "trade_date": dates,
            "close_price": close,
            "low_price": [9.5] * len(dates),
            "sealed": False,
            "touched": False,
        }
    )
    frame.loc[5, ["sealed", "touched", "close_price"]] = [True, True, 11.0]
    frame.loc[100, ["sealed", "touched", "close_price"]] = [True, True, 12.0]
    frame.loc[101:130, "close_price"] = 10.2
    frame.loc[131, ["sealed", "touched", "close_price"]] = [True, True, 11.22]
    return frame


def test_limit_gene_features_are_shifted_before_signal_day() -> None:
    result = attach_limit_gene_features(_daily_rows())

    signal = result.iloc[131]
    assert signal["prior_limit_count_126"] == 2
    assert signal["prior_touch_count_126"] == 2
    assert signal["prior_limit_count_5"] == 0
    assert signal["trade_days_since_prior_limit"] == 31
    assert round(signal["pullback_from_prior_limit_pct"], 2) == -15.0

    after = result.iloc[130]
    assert after["prior_limit_count_126"] == 2
    assert after["prior_position_120"] < 0.5


def test_current_day_limit_never_enters_its_own_gene_count() -> None:
    frame = _daily_rows()
    result = attach_limit_gene_features(frame)

    assert result.iloc[5]["prior_limit_count_126"] == 0
    assert result.iloc[100]["prior_limit_count_126"] == 1
    assert result.iloc[131]["prior_limit_count_126"] == 2


def test_intraday_path_uses_eighty_three_minute_points() -> None:
    times = intraday_path_times()

    assert len(times) == 80
    assert times[0] == "09:30:00"
    assert times[39] == "11:27:00"
    assert times[40] == "13:00:00"
    assert times[-1] == "14:57:00"


def test_path_prefix_excludes_samples_after_signal_time() -> None:
    path = [0.0] * 80
    path[9] = 9.8   # 09:57, first completed touch
    path[10] = 8.8  # 10:00, break
    path[11] = 9.9  # 10:03, reseal
    path[12] = -5.0 # future value must not leak into a 10:03 signal

    at_break = path_prefix_features(path, "10:00:00")
    at_reseal = path_prefix_features(path, "10:03:00")

    assert at_break["point_count"] == 11
    assert at_break["touch_count"] == 1
    assert at_break["reseal_count"] == 0
    assert at_reseal["point_count"] == 12
    assert at_reseal["reseal_count"] == 1
    assert at_reseal["minimum_pct"] == 0.0
    assert at_reseal["last_pct"] == 9.9


def test_path_prefix_describes_recent_support_instead_of_full_session_floor() -> None:
    path = [0.0, 0.5, 1.0, 1.5, 1.8, 2.0, 2.4, 2.8, 3.4]
    path.extend([4.0, 5.0, 6.5, 7.5, 8.8, 9.8])
    path.extend([-5.0] * (80 - len(path)))

    at_signal = path_prefix_features(path, "10:12:00")
    after_signal_changed = list(path)
    after_signal_changed[15] = 10.0
    with_future_change = path_prefix_features(after_signal_changed, "10:12:00")

    assert at_signal["minimum_pct"] == 0.0
    assert at_signal["recent_15m_min_pct"] == 4.0
    assert at_signal["recent_15m_change_pct"] == 5.8
    assert at_signal["recent_15m_range_pct"] == 5.8
    assert at_signal["recent_15m_drawdown_pct"] == 0.0
    assert at_signal["recent_30m_min_pct"] == 1.8
    assert at_signal["recent_30m_change_pct"] == 8.0
    assert {
        key: with_future_change[key]
        for key in (
            "recent_15m_min_pct",
            "recent_15m_change_pct",
            "recent_15m_range_pct",
            "recent_15m_drawdown_pct",
            "recent_30m_min_pct",
            "recent_30m_change_pct",
        )
    } == {
        key: at_signal[key]
        for key in (
            "recent_15m_min_pct",
            "recent_15m_change_pct",
            "recent_15m_range_pct",
            "recent_15m_drawdown_pct",
            "recent_30m_min_pct",
            "recent_30m_change_pct",
        )
    }


def test_financial_risk_only_uses_reports_published_by_signal_date() -> None:
    reports = [
        {
            "publish_date": "2026-03-20",
            "report_date": "2025-12-31",
            "net_profit": 120_000_000,
            "deducted_net_profit": 90_000_000,
            "revenue_yoy": 12.0,
            "debt_asset_ratio": 42.0,
            "cash_flow_quality": 0.8,
        },
        {
            "publish_date": "2026-07-20",
            "report_date": "2026-06-30",
            "net_profit": -300_000_000,
            "deducted_net_profit": -350_000_000,
            "revenue_yoy": -55.0,
            "debt_asset_ratio": 91.0,
            "cash_flow_quality": -2.0,
        },
    ]

    selected = select_latest_published_report(reports, date(2026, 7, 10))
    risk = classify_financial_risk(selected)

    assert selected is not None
    assert selected["report_date"] == "2025-12-31"
    assert risk["level"] == "clear"
    assert risk["blocked"] is False


def test_financial_risk_blocks_confirmed_multi_factor_deterioration() -> None:
    risk = classify_financial_risk(
        {
            "publish_date": "2026-06-18",
            "net_profit": -300_000_000,
            "deducted_net_profit": -350_000_000,
            "revenue_yoy": -55.0,
            "debt_asset_ratio": 91.0,
            "cash_flow_quality": -2.0,
        }
    )

    assert risk["level"] == "blocked"
    assert risk["blocked"] is True
    assert set(risk["reasons"]) == {
        "loss_making",
        "revenue_collapse",
        "high_leverage",
        "weak_cash_flow",
    }


def _candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "vt_symbol": "600001.SSE",
        "name": "主板样本",
        "industry_id": "BK1001",
        "industry_name": "机器人",
        "prior_streak": 0,
        "target_board": 1,
        "signal_time": "10:12:00",
        "signal_kind": "first_touch",
        "prior_limit_count_126": 3,
        "prior_touch_count_126": 8,
        "prior_seal_success_rate_126": 0.75,
        "prior_limit_count_5": 0,
        "trade_days_since_prior_limit": 18,
        "pullback_from_prior_limit_pct": -12.0,
        "prior_position_120": 0.28,
        "auction_gap_pct": 3.2,
        "prior_turnover_rate": 9.0,
        "prior_amount_ratio_5d": 1.6,
        "prior_amplitude_pct": 7.0,
        "prior_low_change_pct": -2.0,
        "prior_industry_heat_score": 72.0,
        "prior_industry_heat_rank": 2,
        "prior_industry_count": 30,
        "prior_industry_leader_rank": 1,
        "prior_market_phase": "repair",
        "prior_market_failed_rate": 0.40,
        "prior_market_one_to_two_rate": 0.30,
        "prior_market_two_to_three_rate": 0.25,
        "financial_risk": {"level": "clear", "blocked": False, "reasons": []},
        "financial_snapshot": {
            "publish_date": "2026-06-30",
            "period_type": "quarterly",
            "net_profit_yoy": 18.0,
        },
        "path_prefix": {
            "point_count": 15,
            "last_pct": 9.8,
            "touch_count": 1,
            "break_count": 0,
            "reseal_count": 0,
            "minimum_pct": 0.0,
            "approach_3point_pct": 3.0,
            "recent_15m_min_pct": 4.0,
            "recent_15m_change_pct": 5.8,
            "recent_15m_range_pct": 5.8,
            "recent_15m_drawdown_pct": 0.0,
            "recent_30m_min_pct": 1.8,
            "recent_30m_change_pct": 8.0,
        },
        "outcome": {"sealed": True, "next_open_return_pct": 2.0},
    }
    candidate.update(overrides)
    return candidate


def test_non_consecutive_third_limit_is_routed_to_two_to_three() -> None:
    candidate = _candidate(prior_streak=0, prior_limit_count_5=2, target_board=3)

    assert classify_board_lane(candidate) == "two_to_three"


def test_first_board_requires_gene_low_position_and_post_ten_signal() -> None:
    no_gene = evaluate_lane_candidate(_candidate(prior_limit_count_126=0))
    too_high = evaluate_lane_candidate(
        _candidate(
            prior_position_120=0.82,
            pullback_from_prior_limit_pct=-2.0,
            trade_days_since_prior_limit=2,
        )
    )
    too_early = evaluate_lane_candidate(_candidate(signal_time="09:42:00"))
    eligible = evaluate_lane_candidate(_candidate())

    assert no_gene["decision"] == "blocked"
    assert "limit_up_gene_missing" in no_gene["blockers"]
    assert "low_position_missing" in too_high["blockers"]
    assert "first_touch_too_early" in too_early["blockers"]
    assert eligible["decision"] == "eligible"
    assert eligible["lane"] == "first_board"


def test_first_board_requires_strong_touch_gene_profit_growth_and_divergence() -> None:
    weak_touch_gene = evaluate_lane_candidate(_candidate(prior_touch_count_126=5))
    missing_report = evaluate_lane_candidate(_candidate(financial_snapshot=None))
    weak_profit = evaluate_lane_candidate(
        _candidate(financial_snapshot={"net_profit_yoy": 9.99})
    )
    no_divergence = evaluate_lane_candidate(_candidate(prior_market_failed_rate=0.3499))

    assert "first_board_touch_gene_weak" in weak_touch_gene["blockers"]
    assert "financial_report_unavailable" in missing_report["blockers"]
    assert "first_board_profit_growth_weak" in weak_profit["blockers"]
    assert "first_board_repair_setup_missing" in no_divergence["blockers"]
    assert evaluate_lane_candidate(_candidate())["decision"] == "eligible"


def test_first_board_uses_support_gate_without_v8_four_to_six_range() -> None:
    missing = evaluate_lane_candidate(_candidate(path_prefix=None))
    fading_path = {
        "point_count": 15,
        "last_pct": 6.0,
        "touch_count": 1,
        "break_count": 1,
        "reseal_count": 0,
        "minimum_pct": 0.0,
        "approach_3point_pct": -2.0,
        "recent_15m_min_pct": 6.0,
        "recent_15m_change_pct": -2.0,
        "recent_15m_range_pct": 3.8,
        "recent_15m_drawdown_pct": -3.8,
        "recent_30m_min_pct": 1.0,
        "recent_30m_change_pct": 5.0,
    }
    fading = evaluate_lane_candidate(
        _candidate(path_prefix=fading_path)
    )
    strong_high_floor_path = {
        **dict(_candidate()["path_prefix"]),
        "recent_15m_min_pct": 8.2,
    }
    strong_high_floor = evaluate_lane_candidate(
        _candidate(path_prefix=strong_high_floor_path)
    )
    supported = evaluate_lane_candidate(_candidate())

    assert "intraday_support_unavailable" in missing["blockers"]
    assert "intraday_support_breakdown" in fading["blockers"]
    assert supported["decision"] == "eligible"
    assert strong_high_floor["decision"] == "eligible"
    assert "intraday_support_confirmed" in supported["favorable_factors"]
    assert "first_board_seal_gate_confirmed" in supported["favorable_factors"]
    assert "first_board_local_setup_unconfirmed" not in strong_high_floor["blockers"]
    assert "intraday_support_out_of_range" not in supported["blockers"]
    assert supported["support_score"] == first_board_support_score(supported)
    assert float(supported["support_score"]) > float(fading["support_score"])


def test_first_board_repair_branch_is_not_deleted_by_shared_retreat_gate() -> None:
    first_board = evaluate_lane_candidate(
        _candidate(prior_market_phase="retreat", prior_market_failed_rate=0.55)
    )
    relay = evaluate_lane_candidate(
        _candidate(
            prior_streak=1,
            prior_limit_count_5=1,
            target_board=2,
            signal_time="09:25:00",
            prior_market_phase="retreat",
            prior_market_failed_rate=0.55,
            prior_board={
                "is_sealed": True,
                "first_limit_time": "10:08:00",
                "last_limit_time": "10:20:00",
                "open_times": 1,
            },
        )
    )

    assert first_board["decision"] == "eligible"
    assert "prior_divergence_repair_setup" in first_board["favorable_factors"]
    assert {"market_retreat", "market_failed_rate_high"} <= set(relay["blockers"])


def test_first_board_heat_is_a_score_not_a_fixed_hard_gate() -> None:
    hot = evaluate_lane_candidate(_candidate(prior_industry_heat_score=72.0))
    rotating = evaluate_lane_candidate(_candidate(prior_industry_heat_score=42.0))

    assert hot["decision"] == "eligible"
    assert rotating["decision"] == "eligible"
    assert "industry_not_hot" not in rotating["blockers"]
    assert float(hot["entry_quality_score"]) > float(rotating["entry_quality_score"])


def test_one_to_two_uses_previous_board_quality_and_auction_strength() -> None:
    eligible = evaluate_lane_candidate(
        _candidate(
            prior_streak=1,
            prior_limit_count_5=1,
            target_board=2,
            signal_time="09:25:00",
            prior_board={
                "is_sealed": True,
                "first_limit_time": "10:08:00",
                "last_limit_time": "10:20:00",
                "open_times": 1,
                "seal_to_turnover_ratio": 0.06,
            },
        )
    )
    weak = evaluate_lane_candidate(
        _candidate(
            prior_streak=1,
            prior_limit_count_5=1,
            target_board=2,
            signal_time="09:25:00",
            auction_gap_pct=7.8,
            prior_turnover_rate=31.0,
        )
    )

    assert eligible["lane"] == "one_to_two"
    assert eligible["decision"] == "eligible"
    assert weak["decision"] == "blocked"
    assert {"auction_gap_out_of_range", "prior_turnover_extreme"} <= set(weak["blockers"])


def test_two_to_three_marks_core_auction_quality() -> None:
    result = evaluate_lane_candidate(
        _candidate(
            prior_streak=2,
            target_board=3,
            auction_gap_pct=3.2,
            prior_turnover_rate=14.0,
            prior_amount_ratio_5d=1.6,
            prior_low_change_pct=0.5,
            prior_market_failed_rate=0.30,
            prior_market_two_to_three_rate=0.35,
            prior_board={
                "is_sealed": True,
                "first_limit_time": "10:08:00",
                "last_limit_time": "14:20:00",
                "open_times": 4,
            },
        )
    )

    assert result["decision"] == "eligible"
    assert result["two_to_three_quality_tier"] == "A"
    assert result["two_to_three_risk_count"] == 0
    assert result["two_to_three_risk_flags"] == []
    assert {
        "prior_board_full_turnover_reseal",
        "prior_amount_ratio_balanced",
        "financial_snapshot_available",
        "prior_low_held_positive",
        "prior_market_failed_rate_controlled",
        "prior_market_two_to_three_active",
    } <= set(result["favorable_factors"])


def test_two_to_three_blocks_four_visible_risks() -> None:
    result = evaluate_lane_candidate(
        _candidate(
            prior_streak=2,
            target_board=3,
            auction_gap_pct=5.5,
            prior_turnover_rate=8.0,
            prior_amount_ratio_5d=1.0,
            financial_snapshot=None,
            prior_low_change_pct=-1.0,
            prior_market_failed_rate=0.40,
            prior_market_two_to_three_rate=0.35,
            prior_board={
                "is_sealed": True,
                "first_limit_time": "10:08:00",
                "last_limit_time": "14:20:00",
                "open_times": 4,
            },
        )
    )

    assert result["decision"] == "blocked"
    assert result["two_to_three_risk_count"] == 6
    assert result["two_to_three_risk_flags"] == [
        "auction_gap_outside_core",
        "prior_turnover_outside_core",
        "prior_amount_ratio_outside_core",
        "financial_snapshot_missing",
        "prior_low_below_zero",
        "prior_market_failed_rate_high",
    ]
    assert "two_to_three_risk_stack" in result["blockers"]


def test_non_two_to_three_candidate_has_stable_quality_fields() -> None:
    result = evaluate_lane_candidate(_candidate())

    assert result["two_to_three_quality_tier"] is None
    assert result["two_to_three_risk_count"] == 0
    assert result["two_to_three_risk_flags"] == []


def test_relay_lane_requires_auditable_previous_board_evidence() -> None:
    one_to_two = evaluate_lane_candidate(
        _candidate(
            prior_streak=1,
            prior_limit_count_5=1,
            target_board=2,
            signal_time="09:25:00",
            prior_board=None,
        )
    )
    two_to_three = evaluate_lane_candidate(
        _candidate(
            prior_streak=2,
            prior_limit_count_5=2,
            target_board=3,
            signal_time="09:25:00",
            prior_board={"is_sealed": True},
        )
    )

    assert one_to_two["decision"] == "blocked"
    assert "prior_board_evidence_missing" in one_to_two["blockers"]
    assert two_to_three["decision"] == "blocked"
    assert "prior_board_path_incomplete" in two_to_three["blockers"]


def test_first_board_does_not_use_previous_day_industry_rank_as_live_core_proxy() -> None:
    third = evaluate_lane_candidate(_candidate(prior_industry_leader_rank=3))
    unknown = evaluate_lane_candidate(_candidate(prior_industry_leader_rank=None))
    relay = evaluate_lane_candidate(
        _candidate(
            prior_streak=1,
            prior_limit_count_5=1,
            target_board=2,
            signal_time="09:25:00",
            prior_industry_leader_rank=3,
            prior_board={
                "is_sealed": True,
                "first_limit_time": "10:08:00",
                "last_limit_time": "10:20:00",
                "open_times": 1,
            },
        )
    )

    assert third["decision"] == "eligible"
    assert unknown["decision"] == "eligible"
    assert relay["decision"] == "blocked"
    assert "stock_not_industry_top2" in relay["blockers"]


def test_high_board_intraday_is_observation_only_without_l2() -> None:
    result = evaluate_lane_candidate(
        _candidate(
            prior_streak=3,
            prior_limit_count_5=3,
            target_board=4,
            signal_time="09:25:00",
            prior_market_phase="broad_rise",
            prior_industry_heat_rank=1,
            has_l2=False,
        )
    )

    assert result["lane"] == "high_board"
    assert result["decision"] == "watch"
    assert "high_board_requires_l2" in result["blockers"]


def test_high_board_auction_accepts_prior_divergence_weak_to_strong_without_l2() -> None:
    result = evaluate_lane_candidate(
        _candidate(
            prior_streak=3,
            prior_limit_count_5=3,
            target_board=4,
            signal_time="09:25:00",
            signal_kind="auction",
            auction_gap_pct=3.5,
            prior_market_phase="repair",
            prior_industry_heat_rank=1,
            has_l2=False,
            prior_board={
                "is_sealed": True,
                "open_times": 2,
                "first_limit_time": "09:46:00",
                "last_limit_time": "14:08:00",
            },
        )
    )

    assert result["lane"] == "high_board"
    assert result["decision"] == "eligible"
    assert result["action"] == "buy_auction"
    assert result["setup_type"] == "high_board_weak_to_strong"


def test_selection_allows_empty_days_and_never_exceeds_four_candidates() -> None:
    candidates = [
        _candidate(vt_symbol="600001.SSE"),
        _candidate(vt_symbol="600002.SSE", prior_streak=1, prior_limit_count_5=1, target_board=2, signal_time="09:25:00"),
        _candidate(vt_symbol="600003.SSE", prior_streak=2, prior_limit_count_5=2, target_board=3, signal_time="09:25:00"),
        _candidate(vt_symbol="600004.SSE", prior_streak=3, prior_limit_count_5=3, target_board=4, signal_time="09:25:00", has_l2=True, prior_market_phase="broad_rise", prior_industry_heat_rank=1),
        _candidate(vt_symbol="600005.SSE", industry_id="BK1002"),
    ]

    selected = select_daily_lane_portfolio(candidates)
    retreat = select_daily_lane_portfolio(
        [_candidate(prior_market_phase="retreat", prior_market_failed_rate=0.20)]
    )

    assert tuple(selected["lanes"]) == BOARD_LANES
    assert len(selected["selected"]) <= 4
    assert all(len(selected["lanes"][lane]) <= 4 for lane in BOARD_LANES)
    assert retreat["selected"] == []
    assert retreat["action"] == "empty"


def test_selection_preserves_the_complete_daily_candidate_pool() -> None:
    candidates = [
        _candidate(vt_symbol="600001.SSE", signal_time="10:08:00"),
        _candidate(vt_symbol="600002.SSE", signal_time="10:32:00"),
    ]

    result = select_daily_lane_portfolio(candidates)

    assert len(result["lanes"]["first_board"]) == 2
    assert [
        row["vt_symbol"] for row in result["candidate_pool"]["first_board"]
    ] == ["600001.SSE", "600002.SSE"]
    assert [
        row["pool_rank"] for row in result["candidate_pool"]["first_board"]
    ] == [1, 2]
    assert result["candidate_count"] == 2


def test_history_replay_persists_pool_separately_from_final_selection(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2026-06-10")],
            "prev_close": [10.0],
        }
    )
    candidates = [
        _candidate(vt_symbol="600001.SSE", signal_time="10:08:00"),
        _candidate(vt_symbol="600002.SSE", signal_time="10:32:00"),
    ]
    monkeypatch.setattr(
        history_engine,
        "_route_candidates_from_day",
        lambda *_args, **_kwargs: {mode: [] for mode in history_engine.ENTRY_MODES},
    )
    monkeypatch.setattr(
        history_engine,
        "_board_lane_candidates_from_day",
        lambda *_args, **_kwargs: candidates,
    )
    monkeypatch.setattr(
        history_engine,
        "_day_market_context_from_day",
        lambda *_args, **_kwargs: {},
    )

    replay = history_engine.build_history_replays(
        frame,
        warmup_days=0,
        holdout_days=0,
    )[0]

    assert len(replay["board_candidate_pool"]["first_board"]) == 2
    assert len(replay["board_lanes"]["first_board"]) == 2
    assert len(replay["lane_portfolio"]["selected"]) == 2
    assert replay["lane_portfolio"]["candidate_pool"] == replay["board_candidate_pool"]


def _pre_evaluated_candidate(
    symbol: str,
    lane: str,
    *,
    industry_id: str,
    rank_score: float,
    quality_tier: str | None = None,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "lane": lane,
        "decision": "eligible",
        "industry_id": industry_id,
        "industry_name": industry_id,
        "rank_score": rank_score,
        "two_to_three_quality_tier": quality_tier,
    }


def test_daily_portfolio_selects_multiple_candidates_from_one_lane() -> None:
    candidates = [
        _pre_evaluated_candidate(
            f"60000{index}.SSE",
            "two_to_three",
            industry_id=f"BK{index % 3}",
            rank_score=100 - index,
            quality_tier="A",
        )
        for index in range(1, 6)
    ]
    with patch(
        "alphaagent.server.services.limit_up.lane_research.evaluate_lane_candidate",
        side_effect=lambda candidate: dict(candidate),
    ):
        result = select_daily_lane_portfolio(candidates)

    assert len(result["selected"]) == 4
    assert {row["lane"] for row in result["selected"]} == {"two_to_three"}
    assert result["selected_counts_by_lane"] == {"two_to_three": 4}


def test_daily_portfolio_diversifies_before_filling_extra_slots() -> None:
    candidates = [
        _pre_evaluated_candidate(
            "600001.SSE", "first_board", industry_id="BK1", rank_score=80
        ),
        _pre_evaluated_candidate(
            "600002.SSE", "one_to_two", industry_id="BK2", rank_score=80
        ),
        _pre_evaluated_candidate(
            "600003.SSE",
            "two_to_three",
            industry_id="BK3",
            rank_score=100,
            quality_tier="A",
        ),
        _pre_evaluated_candidate(
            "600004.SSE",
            "two_to_three",
            industry_id="BK4",
            rank_score=90,
            quality_tier="A",
        ),
        _pre_evaluated_candidate(
            "600005.SSE",
            "two_to_three",
            industry_id="BK5",
            rank_score=85,
            quality_tier="A",
        ),
    ]
    with patch(
        "alphaagent.server.services.limit_up.lane_research.evaluate_lane_candidate",
        side_effect=lambda candidate: dict(candidate),
    ):
        result = select_daily_lane_portfolio(candidates)

    assert [row["vt_symbol"] for row in result["selected"][:3]] == [
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    ]
    assert len(result["selected"]) == 4
    assert result["selection_policy"] == "diversified_then_ranked_v1"


def test_daily_portfolio_enforces_industry_limit_and_symbol_deduplication() -> None:
    candidates = [
        _pre_evaluated_candidate(
            "600001.SSE", "first_board", industry_id="BK1", rank_score=100
        ),
        _pre_evaluated_candidate(
            "600001.SSE", "one_to_two", industry_id="BK1", rank_score=99
        ),
        _pre_evaluated_candidate(
            "600002.SSE", "one_to_two", industry_id="BK1", rank_score=98
        ),
        _pre_evaluated_candidate(
            "600003.SSE", "two_to_three", industry_id="BK1", rank_score=97
        ),
        _pre_evaluated_candidate(
            "600004.SSE", "two_to_three", industry_id="BK2", rank_score=96
        ),
    ]
    with patch(
        "alphaagent.server.services.limit_up.lane_research.evaluate_lane_candidate",
        side_effect=lambda candidate: dict(candidate),
    ):
        result = select_daily_lane_portfolio(candidates)

    assert [row["vt_symbol"] for row in result["selected"]] == [
        "600001.SSE",
        "600002.SSE",
        "600004.SSE",
    ]
    assert result["selected_counts_by_industry"] == {"BK1": 2, "BK2": 1}


def test_daily_portfolio_returns_empty_when_max_total_is_zero() -> None:
    candidate = _pre_evaluated_candidate(
        "600001.SSE", "first_board", industry_id="BK1", rank_score=100
    )
    with patch(
        "alphaagent.server.services.limit_up.lane_research.evaluate_lane_candidate",
        side_effect=lambda row: dict(row),
    ):
        result = select_daily_lane_portfolio([candidate], max_total=0)

    assert result["action"] == "empty"
    assert result["selected"] == []
    assert result["selected_count"] == 0
    assert result["candidate_count"] == 1


def test_final_board_result_cannot_change_pretrade_decision_or_rank() -> None:
    sealed = evaluate_lane_candidate(_candidate(outcome={"sealed": True}))
    failed = evaluate_lane_candidate(_candidate(outcome={"sealed": False}))

    assert sealed["decision"] == failed["decision"]
    assert sealed["rank_score"] == failed["rank_score"]
    assert sealed["blockers"] == failed["blockers"]


def test_event_versions_keep_latest_status_and_richest_intraday_path() -> None:
    rows = [
        {
            "id": 1,
            "vt_symbol": "600001.SSE",
            "event_date": "20260710",
            "event_type": "limit_pool_zt",
            "source": "ths.limit_up_pool",
            "updated_at": "2026-07-10T16:00:00+08:00",
            "raw": {
                "名称": "主板样本",
                "首次封板时间": "10:06:00",
                "分时路径": [1.0, 9.8, 8.5, 9.9],
                "涨停形态": "换手板",
                "近一年封板率": 0.75,
            },
        },
        {
            "id": 2,
            "vt_symbol": "600001.SSE",
            "event_date": "2026-07-10",
            "event_type": "limit_pool_zbgc",
            "source": "akshare.stock_ztb_em",
            "updated_at": "2026-07-10T19:00:00+08:00",
            "raw": {"名称": "主板样本", "首次封板时间": "10:06:00"},
        },
    ]

    merged = merge_rich_event_rows(rows)
    event = merged[("600001.SSE", date(2026, 7, 10))]

    assert event["is_sealed"] is False
    assert event["time_preview"] == [1.0, 9.8, 8.5, 9.9]
    assert event["limit_up_shape"] == "换手板"
    assert event["historical_seal_rate"] == 0.75
    assert event["status_source"] == "akshare.stock_ztb_em"
    assert event["path_source"] == "ths.limit_up_pool"


def test_financial_index_never_returns_a_future_publication() -> None:
    index = build_financial_index(
        [
            {
                "vt_symbol": "600001.SSE",
                "publish_date": "2026-03-20",
                "report_date": "2025-12-31",
                "net_profit_yoy": 18.0,
            },
            {
                "vt_symbol": "600001.SSE",
                "publish_date": "2026-07-20",
                "report_date": "2026-06-30",
                "net_profit_yoy": -40.0,
            },
        ]
    )

    report = financial_report_as_of(index, "600001.SSE", date(2026, 7, 10))
    snapshot = financial_snapshot_as_of(index, "600001.SSE", date(2026, 7, 10))

    assert report is not None
    assert report["report_date"] == "2025-12-31"
    assert snapshot is not None
    assert snapshot["publish_date"] == "2026-03-20"
    assert snapshot["net_profit_yoy"] == 18.0


def _lane_replay_day(
    trade_date: str = "2026-06-10",
    *,
    lane: str = "first_board",
    return_pct: float = 3.2,
    phase: str = "locked_holdout",
) -> dict[str, object]:
    result_date = (date.fromisoformat(trade_date) + timedelta(days=1)).isoformat()
    candidate = {
        **_candidate(),
        "lane": lane,
        "lane_label": {"first_board": "首板", "one_to_two": "一进二"}.get(lane, lane),
        "decision": "eligible",
        "action": "buy_first_board" if lane == "first_board" else "buy_auction",
        "signal_date": trade_date,
        "entry_date": trade_date,
        "result_date": result_date,
        "entry_price": 11.0,
        "buy_time": "10:12:00" if lane == "first_board" else "09:30:00",
        "sell_time_next_open": "09:30:00",
        "sell_time_next_close": "15:00:00",
        "execution_confidence": "three_minute_path_without_queue",
        "source_mode": "intraday_path_prefix",
        "validation_phase": phase,
        "outcome": {
            "touched": True,
            "sealed": True,
            "next_open_price": 11.4,
            "next_close_price": 11.6,
            "next_open_return_pct": return_pct,
            "next_close_return_pct": return_pct + 1.0,
        },
    }
    lanes = {name: [] for name in BOARD_LANES}
    lanes[lane] = [candidate]
    return {
        "trade_date": trade_date,
        "strategy_version": "limit-up-history-v4",
        "validation_phase": phase,
        "board_lanes": lanes,
        "lane_portfolio": {
            "action": "normal",
            "selected": [candidate],
            "lanes": lanes,
        },
        "coverage": {"reliable_trade_days": 600, "intraday_path_trade_days": 233},
    }


def test_lane_ledger_exposes_d_buy_and_d1_sell_times(monkeypatch) -> None:
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_day",
        lambda *_args: _lane_replay_day(),
    )
    monkeypatch.setattr(
        history_service,
        "get_lane_validation_status",
        lambda *_args, **_kwargs: {
            "passed": True,
            "status": "validated",
            "checks": [],
        },
    )

    ledger = history_service.get_history_ledger(
        date(2026, 6, 10),
        lane="first_board",
        exit_mode="next_open",
    )

    trade = ledger["trades"][0]
    assert trade["buy_date"] == "2026-06-10"
    assert trade["buy_time"] == "10:12:00"
    assert trade["sell_date"] == "2026-06-11"
    assert trade["sell_time"] == "09:30:00"
    assert trade["return_pct"] == 3.2


def test_lane_ledger_keeps_unvalidated_pick_as_observation(monkeypatch) -> None:
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_day",
        lambda *_args: _lane_replay_day(),
    )
    monkeypatch.setattr(
        history_service,
        "get_lane_validation_status",
        lambda *_args, **_kwargs: {
            "passed": False,
            "status": "research_only",
            "checks": [],
        },
    )

    ledger = history_service.get_history_ledger(
        date(2026, 6, 10),
        lane="first_board",
        exit_mode="next_open",
    )

    assert ledger["action"] == "observe"
    assert ledger["selected_count"] == 0
    assert ledger["observation_count"] == 1
    assert ledger["trades"] == []
    assert ledger["observations"][0]["return_pct"] == 3.2
    assert ledger["validation"]["status"] == "research_only"


def test_lane_ledger_distinguishes_no_touch_from_failed_board(monkeypatch) -> None:
    day = _lane_replay_day()
    candidate = day["lane_portfolio"]["selected"][0]
    candidate["outcome"] = {
        **candidate["outcome"],
        "touched": False,
        "sealed": False,
    }
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_day",
        lambda *_args: day,
    )
    monkeypatch.setattr(
        history_service,
        "get_lane_validation_status",
        lambda *_args, **_kwargs: {
            "passed": True,
            "status": "validated",
            "checks": [],
        },
    )

    ledger = history_service.get_history_ledger(
        date(2026, 6, 10),
        lane="first_board",
        exit_mode="next_open",
    )

    assert ledger["trades"][0]["d_board_status"] == "no_limit"


def test_lane_backtest_only_counts_daily_selected_portfolio(monkeypatch) -> None:
    selected = _lane_replay_day()
    empty = _lane_replay_day("2026-06-12", return_pct=-8.0)
    empty["lane_portfolio"] = {
        "action": "empty",
        "selected": [],
        "lanes": empty["board_lanes"],
    }
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_range",
        lambda *_args: [selected, empty],
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_daily_bars",
        lambda *_args: [],
    )

    report = history_service.get_lane_history_backtest(
        None,
        None,
        lane="first_board",
        exit_mode="next_open",
    )

    assert report["summary"]["signal_count"] == 1
    assert report["summary"]["trade_count"] == 1
    assert report["summary"]["win_rate"] == 100.0
    assert report["trades"][0]["signal_date"] == "2026-06-10"


def test_lane_backtest_equal_weights_multiple_selected_candidates(monkeypatch) -> None:
    day = _lane_replay_day(lane="two_to_three", return_pct=10.0)
    first = day["lane_portfolio"]["selected"][0]
    first.update(
        {
            "industry_id": "BK1",
            "industry_name": "机器人",
            "two_to_three_quality_tier": "A",
            "two_to_three_risk_count": 0,
            "two_to_three_risk_flags": [],
        }
    )
    second = {
        **first,
        "vt_symbol": "600002.SSE",
        "name": "主板样本二",
        "industry_id": "BK2",
        "industry_name": "算力",
        "outcome": {
            **first["outcome"],
            "next_open_return_pct": -2.0,
        },
    }
    day["lane_portfolio"]["selected"] = [first, second]
    day["board_lanes"]["two_to_three"] = [first, second]
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_range",
        lambda *_args: [day],
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_day",
        lambda *_args: day,
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_daily_bars",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        history_service,
        "get_lane_validation_status",
        lambda *_args, **_kwargs: {
            "passed": True,
            "status": "validated",
            "checks": [],
        },
    )

    report = history_service.get_lane_history_backtest(
        None,
        None,
        lane="two_to_three",
        exit_mode="next_open",
    )
    ledger = history_service.get_history_ledger(
        date(2026, 6, 10),
        lane="two_to_three",
        exit_mode="next_open",
    )

    assert report["signal_summary"]["total_return_pct"] == 4.0
    assert report["summary"]["initial_cash"] == 100_000
    assert report["summary"]["total_return_pct"] != 4.0
    assert report["summary"]["trade_count"] == 2
    assert report["summary"]["trade_day_count"] == 1
    assert report["summary"]["average_trades_per_day"] == 2.0
    assert report["summary"]["max_trades_per_day"] == 2
    assert report["summary"]["max_industry_concentration_pct"] == 50.0
    assert len(report["trades"]) == 2
    assert len(ledger["trades"]) == 2
    assert ledger["trades"][0]["two_to_three_quality_tier"] == "A"
    assert ledger["trades"][0]["two_to_three_risk_flags"] == []


def test_portfolio_scale_reports_full_single_industry_concentration() -> None:
    summary = history_service._portfolio_scale_summary(
        [
            {
                "entry_date": "2026-06-10",
                "industry_id": "BK1",
                "return_pct": 10.0,
            },
            {
                "entry_date": "2026-06-10",
                "industry_id": "BK1",
                "return_pct": -2.0,
            },
        ]
    )

    assert summary["max_industry_concentration_pct"] == 100.0


def test_lane_validation_requires_samples_after_rule_freeze(monkeypatch) -> None:
    rows = [
        _lane_replay_day(
            f"2025-08-{day:02d}",
            lane="high_board",
            phase="expanding_oos",
        )
        for day in range(1, 31)
    ]
    rows.extend(
        _lane_replay_day(
            f"2026-05-{day:02d}",
            lane="high_board",
            phase="locked_holdout",
        )
        for day in range(1, 31)
    )
    for index, row in enumerate(rows, start=100):
        candidate = row["lane_portfolio"]["selected"][0]
        candidate["vt_symbol"] = f"600{index:03d}.SSE"
        candidate["name"] = f"验证样本{index}"
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_range",
        lambda *_args: rows,
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_daily_bars",
        lambda *_args: [],
    )

    report = history_service.get_lane_history_backtest(
        None,
        None,
        lane="high_board",
        exit_mode="next_open",
    )

    checks = {check["phase"]: check for check in report["validation"]["checks"]}
    assert checks["expanding_oos"]["passed"] is True
    assert checks["locked_holdout"]["passed"] is True
    assert checks["post_freeze_forward"]["trade_count"] == 0
    assert checks["post_freeze_forward"]["passed"] is False
    assert report["validation"]["passed"] is False


def test_portfolio_backtest_uses_one_shared_100k_cash_account(monkeypatch) -> None:
    day = _lane_replay_day(lane="first_board", return_pct=8.0)
    first = day["lane_portfolio"]["selected"][0]
    relay = {
        **first,
        "vt_symbol": "600002.SSE",
        "name": "接力样本",
        "lane": "two_to_three",
        "signal_kind": "auction",
        "buy_time": "09:30:00",
        "entry_price": 10.0,
        "limit_price": 11.0,
        "outcome": {
            **first["outcome"],
            "entry_day_close_price": 10.0,
            "next_open_price": 9.8,
            "next_close_price": 9.5,
            "next_open_return_pct": -2.31,
            "next_close_return_pct": -5.31,
        },
    }
    day["lane_portfolio"]["selected"] = [first, relay]
    day["board_lanes"]["two_to_three"] = [relay]
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_range",
        lambda *_args: [day],
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_daily_bars",
        lambda *_args: [],
    )

    report = history_service.get_lane_history_backtest(
        None,
        None,
        lane="portfolio",
        exit_mode="next_close",
    )

    assert report["lane"] == "portfolio"
    assert report["account_config"]["initial_cash"] == 100_000
    assert report["account_config"]["max_positions"] == 4
    assert report["summary"] == report["execution_summary"]
    assert report["summary"]["trade_count"] == 2
    assert report["summary"]["total_return_pct"] == report["daily_results"][-1]["total_return_pct"]
    assert report["signal_summary"]["total_return_pct"] != report["summary"]["total_return_pct"]


def test_lane_ledger_api_accepts_date_and_board_lane(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_history_ledger",
        lambda trade_date, lane, exit_mode: {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "lane": lane,
            "exit_mode": exit_mode,
            "trades": [],
        },
    )

    response = TestClient(create_app()).get(
        "/api/limit-up/history/ledger",
        params={"date": "2026-06-10", "lane": "two_to_three"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["lane"] == "two_to_three"
