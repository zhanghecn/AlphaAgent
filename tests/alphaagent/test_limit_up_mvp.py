from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up.entry_backtest import build_limit_up_entry_backtest
from alphaagent.server.services.limit_up.domain import (
    analyze_d1_outcome,
    event_matches_daily_bar,
    event_fill_status,
    is_eligible_main_board,
    main_board_limit_price,
    normalize_limit_time,
    percentile_ranks,
    rank_dragon_candidates,
    reseal_observation_status,
    summarize_proxy_trades,
)
from alphaagent.server.services.limit_up.repository import deduplicate_event_rows, normalize_event_row
from alphaagent.server.services.limit_up.features import (
    market_snapshot_for_trade,
    promotion_rate_for_board,
    score_pretrade_candidates,
    timing_snapshot_as_of,
)
from alphaagent.server.services.limit_up.policy import build_daily_research_plan
from alphaagent.server.services.limit_up.sentiment import classify_sentiment_phase
from alphaagent.server.services.limit_up.service import (
    _observed_sector_membership_counts,
    build_limit_up_dashboard,
    build_limit_up_proxy_backtest,
    build_limit_up_trade_dates,
)


@pytest.fixture
def sample_limit_up_dataset() -> dict[str, object]:
    symbols = [f"60000{index}.SSE" for index in range(1, 7)]
    events = []
    for index, symbol in enumerate(symbols, start=1):
        events.append(
            {
                "vt_symbol": symbol,
                "trade_date": "2026-07-09",
                "event_type": "limit_pool_zbgc" if index == 3 else "limit_pool_zt",
                "name": f"样本{index}",
                "first_limit_time": "09:30:01" if index == 1 else f"10:{index:02d}:00",
                "last_limit_time": f"10:{index + 10:02d}:00",
                "open_times": 0 if index == 1 else index % 3 + 1,
                "limit_times": 2 if index == 2 else 1,
                "seal_amount": 120_000_000 - index * 5_000_000,
                "turnover": 500_000_000 + index * 50_000_000,
                "float_market_cap": 5_000_000_000,
                "turnover_rate": 8.0 + index,
                "is_sealed": index != 3,
            }
        )
    memberships = [
        {
            "vt_symbol": symbol,
            "sector_id": "sector_a" if index <= 3 else f"sector_{index}",
            "sector_name": "机器人" if index <= 3 else f"板块{index}",
            "sector_type": "concept",
            "rank": index,
        }
        for index, symbol in enumerate(symbols, start=1)
    ]
    sector_flows = []
    for trade_date in ("2026-07-08", "2026-07-09"):
        for index, sector_id in enumerate(("sector_a", "sector_4", "sector_5", "sector_6"), start=1):
            sector_flows.append(
                {
                    "sector_id": sector_id,
                    "sector_name": "机器人" if sector_id == "sector_a" else f"板块{sector_id[-1]}",
                    "trade_date": trade_date,
                    "period": "即时",
                    "main_net_inflow": 10_000_000_000 - index * 1_000_000_000,
                    "main_net_inflow_ratio": 8.0 - index,
                }
            )
    stock_flows = [
        {
            "vt_symbol": symbol,
            "trade_date": "2026-07-09",
            "main_net_inflow": 1_000_000_000 - index * 50_000_000,
            "main_net_inflow_ratio": 6.0 - index * 0.2,
        }
        for index, symbol in enumerate(symbols, start=1)
    ]
    sector_scores = [
        {
            "sector_id": sector_id,
            "as_of_date": "2026-07-08",
            "period": "20d",
            "heat_score": 88.0 - index,
            "momentum_score": 80.0 - index,
            "breadth_score": 72.0,
            "fund_score": 70.0,
            "sentiment_score": 75.0,
            "leader_score": 82.0,
            "continuity_score": 78.0,
            "risk_penalty": 0.0,
            "trend_state": "MAINLINE_UP",
            "confidence": 1.0,
        }
        for index, sector_id in enumerate(("sector_a", "sector_4", "sector_5", "sector_6"), start=1)
    ]
    sentiment_points = [
        {
            "date": "2026-07-08",
            "score": 62.0,
            "score_change": 8.0,
            "phase": "repair",
            "phase_label": "修复",
            "limit_up_count": 80,
            "limit_down_count": 5,
            "failed_limit_up_rate": 0.25,
            "promotion_rate": 0.32,
            "max_limit_up_streak": 5,
            "promotion_ladder": {
                "one_to_two": {"base_count": 20, "promoted_count": 8, "rate": 0.4},
                "two_to_three": {"base_count": 8, "promoted_count": 3, "rate": 0.375},
                "three_plus": {"base_count": 3, "promoted_count": 1, "rate": 1 / 3},
            },
        },
        {
            "date": "2026-07-09",
            "score": 20.0,
            "score_change": -42.0,
            "phase": "ice",
            "phase_label": "冰点",
            "limit_up_count": 20,
            "limit_down_count": 80,
            "failed_limit_up_rate": 0.6,
            "promotion_rate": 0.08,
            "max_limit_up_streak": 2,
            "promotion_ladder": {},
        },
    ]
    timing_signals = [
        {
            "date": "2026-06-30",
            "direction": "SILVER",
            "status": "CONFIRMED",
            "confirm_date": "2026-07-01",
            "grade": "WEAK",
        },
        {
            "date": "2026-07-08",
            "direction": "GOLD",
            "status": "INVALIDATED",
            "confirm_date": "2026-07-09",
            "grade": "MEDIUM",
        },
    ]
    daily_bars = []
    for index, symbol in enumerate(symbols, start=1):
        daily_bars.extend(
            [
                {
                    "vt_symbol": symbol,
                    "trade_date": "2026-07-08",
                    "open_price": 9.8,
                    "close_price": 10.0,
                    "high_price": 10.1,
                    "low_price": 9.7,
                    "turnover": 400_000_000 + index * 10_000_000,
                    "change_pct": 2.0,
                },
                {
                    "vt_symbol": symbol,
                    "trade_date": "2026-07-09",
                    "open_price": 10.1,
                    "close_price": 11.0 if index != 3 else 10.4,
                    "high_price": 11.0,
                    "low_price": 10.0,
                    "turnover": 600_000_000 + index * 10_000_000,
                    "change_pct": 10.0 if index != 3 else 4.0,
                },
                {
                    "vt_symbol": symbol,
                    "trade_date": "2026-07-10",
                    "open_price": 11.55 if index != 3 else 9.9,
                    "close_price": 11.2 if index != 3 else 9.7,
                    "high_price": 11.8,
                    "low_price": 9.5,
                    "turnover": 700_000_000,
                    "change_pct": 5.0 if index != 3 else -4.8,
                },
            ]
        )
    return {
        "events": events,
        "memberships": memberships,
        "sector_flows": sector_flows,
        "stock_flows": stock_flows,
        "sector_scores": sector_scores,
        "sentiment_points": sentiment_points,
        "timing_signals": timing_signals,
        "daily_bars": daily_bars,
        "coverage": {
            "event_start": "2026-07-09",
            "event_end": "2026-07-09",
            "event_trade_days": 1,
            "event_count": 6,
            "sector_flow_trade_days": 2,
            "membership_mode": "current_snapshot",
            "minute_or_tick_coverage": False,
        },
    }


def test_timing_snapshot_does_not_reveal_next_day_confirmation() -> None:
    signals = [
        {
            "date": "2026-06-30",
            "direction": "SILVER",
            "status": "CONFIRMED",
            "confirm_date": "2026-07-01",
            "grade": "WEAK",
        },
        {
            "date": "2026-07-08",
            "direction": "GOLD",
            "status": "INVALIDATED",
            "confirm_date": "2026-07-09",
            "grade": "MEDIUM",
        },
    ]

    before_confirmation = timing_snapshot_as_of(signals, "2026-07-08")
    after_confirmation = timing_snapshot_as_of(signals, "2026-07-09")

    assert before_confirmation["last_confirmed_direction"] == "SILVER"
    assert before_confirmation["latest_candidate"]["direction"] == "GOLD"
    assert before_confirmation["latest_candidate"]["as_of_status"] == "PENDING"
    assert after_confirmation["latest_candidate"]["as_of_status"] == "INVALIDATED"


def test_market_snapshot_uses_only_previous_trading_day() -> None:
    points = [
        {"date": "2026-07-08", "phase": "repair", "score": 65.0},
        {"date": "2026-07-09", "phase": "ice", "score": 20.0},
    ]

    snapshot = market_snapshot_for_trade(
        "2026-07-09",
        "2026-07-08",
        points,
        [],
    )

    assert snapshot["sentiment_date"] == "2026-07-08"
    assert snapshot["sentiment"]["phase"] == "repair"
    assert snapshot["data_cutoff"] == "D-1_CLOSE"


def test_market_snapshot_expires_stale_silver_signal() -> None:
    snapshot = market_snapshot_for_trade(
        "2026-07-09",
        "2026-07-08",
        [{"date": "2026-07-08", "phase": "repair", "score": 65.0}],
        [
            {
                "date": "2026-05-29",
                "direction": "SILVER",
                "status": "CONFIRMED",
                "confirm_date": "2026-06-01",
            }
        ],
        ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-07-08"],
    )

    assert snapshot["timing"]["last_confirmed_direction"] == "SILVER"
    assert snapshot["timing"]["active_direction"] is None
    assert snapshot["timing"]["signal_state"] == "STALE"


def test_board_level_uses_its_own_previous_day_success_rate() -> None:
    sentiment = {
        "promotion_ladder": {
            "first_board": {"base_count": 40, "promoted_count": 24, "rate": 0.60},
            "one_to_two": {"base_count": 20, "promoted_count": 8, "rate": 0.40},
            "two_to_three": {"base_count": 8, "promoted_count": 2, "rate": 0.25},
            "three_plus": {"base_count": 4, "promoted_count": 1, "rate": 0.25},
        }
    }

    assert promotion_rate_for_board(sentiment, 1) == 0.60
    assert promotion_rate_for_board(sentiment, 2) == 0.40
    assert promotion_rate_for_board(sentiment, 3) == 0.25
    assert promotion_rate_for_board(sentiment, 4) == 0.25


def test_sentiment_cycle_marks_broad_heavy_selling_as_ebb() -> None:
    phase = classify_sentiment_phase(
        {
            "score": 39.1,
            "score_change": 27.5,
            "up_ratio": 0.2864,
            "down_ratio": 0.6892,
            "limit_up_count": 82,
            "limit_down_count": 68,
            "failed_limit_up_rate": 0.374,
            "promotion_rate": 0.2703,
            "max_limit_up_streak": 7,
        },
        {"score": 11.6, "limit_down_count": 30, "down_ratio": 0.75},
    )

    assert phase == "ebb"


def test_pretrade_score_does_not_turn_two_bad_sectors_into_strong_candidates() -> None:
    candidates = [
        {
            "vt_symbol": "600001.SSE",
            "sector_id": "cold_a",
            "signal_board_level": 1,
            "first_limit_time": "09:30:01",
            "prior_stock": {"prior_turnover": 100_000_000, "prior_turnover_ratio_5d": 1.0},
            "prior_stock_flow": {"main_net_inflow": -100_000_000, "main_net_inflow_ratio": -4.0},
            "intraday": {"observed_sector_touch_count": 1},
        },
        {
            "vt_symbol": "600002.SSE",
            "sector_id": "cold_b",
            "signal_board_level": 1,
            "first_limit_time": "09:30:02",
            "prior_stock": {"prior_turnover": 80_000_000, "prior_turnover_ratio_5d": 1.0},
            "prior_stock_flow": {"main_net_inflow": -200_000_000, "main_net_inflow_ratio": -6.0},
            "intraday": {"observed_sector_touch_count": 1},
        },
    ]
    scored = score_pretrade_candidates(
        candidates,
        {
            "cold_a": {"main_net_inflow": -800_000_000, "main_net_inflow_ratio": -2.0},
            "cold_b": {"main_net_inflow": -1_000_000_000, "main_net_inflow_ratio": -3.0},
        },
        {
            "cold_a": {"heat_score": 42.0, "trend_state": "WEAK"},
            "cold_b": {"heat_score": 35.0, "trend_state": "WEAK"},
        },
        {
            "sentiment": {
                "phase": "ebb",
                "promotion_rate": 0.20,
                "promotion_ladder": {
                    "first_board": {"base_count": 30, "promoted_count": 12, "rate": 0.40}
                },
            },
            "timing": {"active_direction": "SILVER", "signal_state": "SILVER_ACTIVE"},
        },
    )

    assert max(float(item["dragon_score"]) for item in scored) < 60
    assert all(item["pretrade_gate_passed"] is False for item in scored)


def test_daily_research_plan_does_not_select_by_final_open_times() -> None:
    candidates = [
        {
            "vt_symbol": "600001.SSE",
            "market_dragon_rank": 1,
            "sector_dragon_rank": 1,
            "dragon_score": 82.0,
            "decision": "eligible",
            "signal_board_level": 1,
            "open_times": 0,
        },
        {
            "vt_symbol": "600002.SSE",
            "market_dragon_rank": 2,
            "sector_dragon_rank": 1,
            "dragon_score": 78.0,
            "decision": "eligible",
            "signal_board_level": 1,
            "open_times": 4,
        },
    ]
    market = {
        "sentiment": {"phase": "divergence", "phase_label": "分歧"},
        "timing": {"last_confirmed_direction": "SILVER"},
    }

    baseline = build_daily_research_plan(candidates, market)
    changed = build_daily_research_plan(
        [{**candidates[0], "open_times": 9}, {**candidates[1], "open_times": 0}],
        market,
    )

    assert [item["vt_symbol"] for item in baseline["plans"]] == ["600001.SSE"]
    assert [item["vt_symbol"] for item in changed["plans"]] == ["600001.SSE"]
    assert baseline["entry_trigger"] == "first_reseal"


def test_daily_research_plan_rejects_high_scoring_candidate_that_failed_absolute_gates() -> None:
    result = build_daily_research_plan(
        [
            {
                "vt_symbol": "600001.SSE",
                "market_dragon_rank": 1,
                "sector_dragon_rank": 1,
                "dragon_score": 90.0,
                "decision": "watch",
                "decision_reason": "fast_board_wait_reseal",
                "pretrade_gate_passed": False,
                "signal_board_level": 1,
            }
        ],
        {"sentiment": {"phase": "repair"}, "timing": {"active_direction": None}},
    )

    assert result["plans"] == []


def test_limit_up_mvp_excludes_non_main_board_and_st() -> None:
    assert is_eligible_main_board("600001.SSE", "主板样本") is True
    assert is_eligible_main_board("002001.SZSE", "深市样本") is True
    assert is_eligible_main_board("300001.SZSE", "创业样本") is False
    assert is_eligible_main_board("688001.SSE", "科创样本") is False
    assert is_eligible_main_board("920001.BSE", "北交样本") is False
    assert is_eligible_main_board("600002.SSE", "ST样本") is False
    assert is_eligible_main_board("000004.SZSE", "国华退") is False
    assert is_eligible_main_board("600182.SSE", "S佳通") is False
    assert is_eligible_main_board("600003.SSE", "N新股") is False


def test_limit_up_mvp_normalizes_limit_times() -> None:
    assert normalize_limit_time("93001") == "09:30:01"
    assert normalize_limit_time("093502") == "09:35:02"
    assert normalize_limit_time("10:15:09") == "10:15:09"
    assert normalize_limit_time(None) is None


def test_limit_up_mvp_fast_sealed_board_is_not_filled() -> None:
    event = {"first_limit_time": "09:30:01", "open_times": 0}
    assert event_fill_status(event, "conservative") == "unfilled_fast_board"
    assert event_fill_status(event, "optimistic") == "unfilled_fast_board"


def test_limit_up_mvp_resealed_board_is_conservatively_fillable() -> None:
    event = {"first_limit_time": "10:15:00", "last_limit_time": "10:30:00", "open_times": 2}
    assert event_fill_status(event, "conservative") == "filled_first_open_proxy"
    assert event_fill_status(event, "optimistic") == "filled_non_fast_proxy"


def test_failed_board_without_last_seal_time_is_not_claimed_as_reseal() -> None:
    event = {
        "event_type": "limit_pool_zbgc",
        "first_limit_time": "10:15:00",
        "last_limit_time": None,
        "open_times": 2,
        "is_sealed": False,
    }

    assert event_fill_status(event, "conservative") == "filled_first_open_proxy"
    assert reseal_observation_status(event) == "reseal_path_unverifiable"


def test_limit_up_mvp_conservative_scenario_rejects_unknown_queue() -> None:
    event = {"first_limit_time": "10:15:00", "open_times": 0}
    assert event_fill_status(event, "conservative") == "unfilled_queue_unknown"
    assert event_fill_status(event, "optimistic") == "filled_non_fast_proxy"


def test_main_board_limit_price_uses_half_up_tick_rounding() -> None:
    assert main_board_limit_price(10.01) == 11.01
    assert main_board_limit_price(9.95) == 10.95


def test_d1_outcome_classifies_continuation_premium_and_breakdown() -> None:
    signal = {"close_price": 11.0}

    continuation = analyze_d1_outcome(
        signal,
        {"open_price": 11.0, "high_price": 12.1, "low_price": 11.0, "close_price": 12.1},
        entry_price=11.0,
    )
    premium = analyze_d1_outcome(
        signal,
        {"open_price": 11.2, "high_price": 11.7, "low_price": 11.1, "close_price": 11.3},
        entry_price=11.0,
    )
    breakdown = analyze_d1_outcome(
        signal,
        {"open_price": 10.5, "high_price": 10.7, "low_price": 10.0, "close_price": 10.4},
        entry_price=11.0,
    )

    assert continuation["outcome_code"] == "continuation_limit_up"
    assert continuation["is_continuation_limit_up"] is True
    assert premium["outcome_code"] == "close_premium"
    assert breakdown["outcome_code"] == "direct_breakdown"


def test_d1_outcome_marks_high_open_dump_separately() -> None:
    result = analyze_d1_outcome(
        {"close_price": 11.0},
        {"open_price": 11.3, "high_price": 11.6, "low_price": 10.8, "close_price": 10.9},
        entry_price=11.0,
    )

    assert result["outcome_code"] == "high_open_dump"
    assert result["close_return_pct"] < 0


def test_d1_limit_after_a_failed_board_is_not_named_continuation() -> None:
    result = analyze_d1_outcome(
        {"close_price": 11.0},
        {"open_price": 11.0, "high_price": 12.1, "low_price": 11.0, "close_price": 12.1},
        entry_price=11.0,
        signal_was_sealed=False,
    )

    assert result["outcome_code"] == "next_limit_up_after_failed_board"
    assert result["is_continuation_limit_up"] is False


def test_historical_dragon_ranking_excludes_chinext_and_star_board(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    excluded_symbol = "688001.SSE"
    source_event = dict(sample_limit_up_dataset["events"][0])
    source_membership = dict(sample_limit_up_dataset["memberships"][0])
    source_bars = [
        {**bar, "vt_symbol": excluded_symbol}
        for bar in sample_limit_up_dataset["daily_bars"]
        if bar["vt_symbol"] == source_event["vt_symbol"]
    ]
    dataset = {
        **sample_limit_up_dataset,
        "events": [*sample_limit_up_dataset["events"], {**source_event, "vt_symbol": excluded_symbol}],
        "memberships": [*sample_limit_up_dataset["memberships"], {**source_membership, "vt_symbol": excluded_symbol}],
        "daily_bars": [*sample_limit_up_dataset["daily_bars"], *source_bars],
    }

    dashboard = build_limit_up_dashboard(dataset)

    assert excluded_symbol not in {item["vt_symbol"] for item in dashboard["top_dragons"]}


def test_sector_touch_counts_do_not_include_non_main_board_events() -> None:
    events = [
        {"vt_symbol": "600001.SSE", "name": "主板样本"},
        {"vt_symbol": "300001.SZSE", "name": "创业板样本"},
        {"vt_symbol": "688001.SSE", "name": "科创板样本"},
    ]
    memberships = {
        event["vt_symbol"]: [
            {"sector_id": "sector_a", "sector_name": "机器人", "sector_type": "concept"}
        ]
        for event in events
    }

    result = _observed_sector_membership_counts(events, memberships)

    assert result == {"sector_a": 1}


def test_percentile_ranks_keep_missing_values_at_zero() -> None:
    ranks = percentile_ranks({"a": 30.0, "b": 20.0, "c": 10.0, "d": None})
    assert ranks == {"a": 1.0, "b": 0.5, "c": 0.0, "d": 0.0}


def test_dragon_ranking_keeps_two_per_sector_and_five_total() -> None:
    events = [
        {
            "vt_symbol": f"60000{index}.SSE",
            "sector_id": "sector_a" if index <= 4 else f"sector_{index}",
            "dragon_score": 100.0 - index,
        }
        for index in range(1, 9)
    ]

    ranked = rank_dragon_candidates(events)

    assert len(ranked) == 5
    assert [item["market_dragon_rank"] for item in ranked] == [1, 2, 3, 4, 5]
    assert len([item for item in ranked if item["sector_id"] == "sector_a"]) == 2
    assert all(int(item["sector_dragon_rank"]) <= 2 for item in ranked)


def test_proxy_trade_summary_compounds_returns() -> None:
    summary = summarize_proxy_trades(
        [
            {"return_pct": 10.0},
            {"return_pct": -5.0},
            {"return_pct": None},
        ]
    )

    assert summary["trade_count"] == 2
    assert summary["win_rate"] == 50.0
    assert summary["average_return_pct"] == 2.5
    assert summary["total_return_pct"] == 4.5


def test_limit_up_event_row_normalizes_chinese_raw_fields() -> None:
    row = {
        "vt_symbol": "600001.SSE",
        "event_date": "20260709",
        "event_type": "limit_pool_zt",
        "raw": {
            "名称": "主板样本",
            "最新价": 11.0,
            "首次封板时间": "093502",
            "最后封板时间": "101000",
            "炸板次数": 1,
            "连板数": 2,
            "封板资金": 100000000,
            "成交额": 600000000,
            "流通市值": 5000000000,
            "换手率": 12.3,
        },
    }

    item = normalize_event_row(row)

    assert item["trade_date"] == "2026-07-09"
    assert item["first_limit_time"] == "09:35:02"
    assert item["last_limit_time"] == "10:10:00"
    assert item["limit_times"] == 2
    assert item["is_sealed"] is True


def test_limit_up_event_validation_rejects_mismatched_final_price_or_change() -> None:
    daily_bar = {"close_price": 11.0, "change_pct": 10.0}

    assert event_matches_daily_bar({"close_price": 11.0, "change_pct": 10.0}, daily_bar) is True
    assert event_matches_daily_bar({"close_price": 10.1, "change_pct": 10.0}, daily_bar) is False
    assert event_matches_daily_bar({"close_price": 11.0, "change_pct": 4.0}, daily_bar) is False


def test_failed_limit_up_event_is_not_marked_sealed() -> None:
    item = normalize_event_row(
        {
            "vt_symbol": "600002.SSE",
            "event_date": "2026-07-09",
            "event_type": "limit_pool_zbgc",
            "raw": {"名称": "炸板样本", "首次封板时间": "100001", "炸板次数": 3},
        }
    )

    assert item["trade_date"] == "2026-07-09"
    assert item["is_sealed"] is False
    assert item["open_times"] == 3


def test_limit_up_event_deduplication_keeps_latest_intraday_state() -> None:
    rows = [
        {
            "id": 1,
            "vt_symbol": "600001.SSE",
            "event_date": "20260709",
            "event_type": "limit_pool_zt",
            "created_at": "2026-07-09T10:00:00+08:00",
        },
        {
            "id": 2,
            "vt_symbol": "600001.SSE",
            "event_date": "20260709",
            "event_type": "limit_pool_zbgc",
            "created_at": "2026-07-09T15:00:00+08:00",
        },
    ]

    result = deduplicate_event_rows(rows)

    assert len(result) == 1
    assert result[0]["event_type"] == "limit_pool_zbgc"


def test_limit_up_dashboard_returns_only_five_market_dragons(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    dashboard = build_limit_up_dashboard(sample_limit_up_dataset)

    assert dashboard["status"] == "ready"
    assert dashboard["mode"] == "historical_event_replay"
    assert len(dashboard["top_dragons"]) <= 5
    assert [item["market_dragon_rank"] for item in dashboard["top_dragons"]] == list(
        range(1, len(dashboard["top_dragons"]) + 1)
    )
    assert all(item["sector_dragon_rank"] <= 2 for item in dashboard["top_dragons"])
    sector_a = [item for item in dashboard["top_dragons"] if item["sector_id"] == "sector_a"]
    assert len(sector_a) == 2
    assert {item["selection_order"] for item in sector_a} == {2, 3}
    assert dashboard["limitations"]


def test_limit_up_trade_dates_are_sorted_and_navigable(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    events = list(sample_limit_up_dataset["events"])
    events.append({**events[0], "trade_date": "2026-07-08"})
    events.append({**events[0], "trade_date": "2026-07-07"})
    dataset = {**sample_limit_up_dataset, "events": events}

    payload = build_limit_up_trade_dates(dataset)

    assert payload["dates"] == ["2026-07-08", "2026-07-09"]
    assert payload["start"] == "2026-07-08"
    assert payload["latest"] == "2026-07-09"


def test_limit_up_dashboard_selects_exact_historical_date(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    events = list(sample_limit_up_dataset["events"])
    events.append({**events[1], "trade_date": "2026-07-08", "name": "前一日样本"})
    dataset = {**sample_limit_up_dataset, "events": events}

    dashboard = build_limit_up_dashboard(dataset, target_date=date(2026, 7, 8))

    assert dashboard["status"] == "ready"
    assert dashboard["mode"] == "historical_event_replay"
    assert dashboard["trade_date"] == "2026-07-08"
    assert dashboard["navigation"]["previous"] is None
    assert dashboard["navigation"]["next"] == "2026-07-09"
    assert {item["trade_date"] for item in dashboard["top_dragons"]} == {"2026-07-08"}


def test_limit_up_dashboard_does_not_silently_replace_missing_date(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    dashboard = build_limit_up_dashboard(
        sample_limit_up_dataset,
        target_date=date(2026, 7, 7),
    )

    assert dashboard["status"] == "empty"
    assert dashboard["trade_date"] == "2026-07-07"
    assert dashboard["navigation"]["next"] == "2026-07-09"


def test_historical_ranking_is_not_changed_by_final_seal_result(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    baseline = build_limit_up_dashboard(sample_limit_up_dataset)
    changed_events = [
        {
            **event,
            "is_sealed": not bool(event["is_sealed"]),
            "open_times": 9,
            "seal_amount": 1.0,
        }
        for event in sample_limit_up_dataset["events"]
    ]
    changed = build_limit_up_dashboard(
        {**sample_limit_up_dataset, "events": changed_events}
    )

    assert [item["vt_symbol"] for item in baseline["top_dragons"]] == [
        item["vt_symbol"] for item in changed["top_dragons"]
    ]


def test_historical_dashboard_attaches_fill_and_d1_outcomes(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    dashboard = build_limit_up_dashboard(sample_limit_up_dataset)
    resealed = next(item for item in dashboard["top_dragons"] if item["open_times"] > 0)

    assert resealed["outcome"]["conservative_status"] == "filled_first_open_proxy"
    assert resealed["outcome"]["strict_reseal_status"] in {
        "reseal_observed_queue_unknown",
        "reseal_path_unverifiable",
    }
    assert resealed["outcome"]["exit_date"] == "2026-07-10"
    assert resealed["outcome"]["next_open_return_pct"] is not None
    assert resealed["outcome"]["next_close_return_pct"] is not None
    assert resealed["outcome"]["d1_analysis"]["outcome_code"] in {
        "close_premium",
        "direct_breakdown",
    }
    assert resealed["outcome"]["d1_analysis"]["supporting_factors"]


def test_limit_up_dashboard_marks_fast_board_as_waiting_for_reseal(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    events = sample_limit_up_dataset["events"]
    dashboard = build_limit_up_dashboard(
        {**sample_limit_up_dataset, "events": [events[0], *events[3:]]}
    )
    fast = next(item for item in dashboard["top_dragons"] if item["vt_symbol"] == "600001.SSE")

    assert fast["decision"] == "watch"
    assert fast["decision_reason"] == "fast_board_wait_reseal"
    assert fast["direct_board_allowed"] is False


def test_proxy_backtest_does_not_trade_fast_board(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    events = sample_limit_up_dataset["events"]
    report = build_limit_up_proxy_backtest(
        {**sample_limit_up_dataset, "events": [events[0], *events[3:]]},
        exit_mode="next_open",
    )
    fast = next(item for item in report["orders"] if item["vt_symbol"] == "600001.SSE")

    assert fast["conservative_status"] == "unfilled_fast_board"
    assert fast["optimistic_status"] == "unfilled_fast_board"
    assert all(
        trade["vt_symbol"] != "600001.SSE"
        for trade in report["scenarios"]["conservative"]["trades"]
    )


def test_proxy_backtest_replaces_early_candidate_with_stronger_late_top5(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    late_symbol = "600007.SSE"
    events = [
        *sample_limit_up_dataset["events"],
        {
            **sample_limit_up_dataset["events"][5],
            "vt_symbol": late_symbol,
            "name": "午后高分样本",
            "first_limit_time": "14:30:00",
        },
    ]
    memberships = [
        *sample_limit_up_dataset["memberships"],
        {
            "vt_symbol": late_symbol,
            "sector_id": "late_sector",
            "sector_name": "午后题材",
            "sector_type": "concept",
            "rank": 1,
        },
    ]
    sector_flows = [
        *sample_limit_up_dataset["sector_flows"],
        {
            "sector_id": "late_sector",
            "sector_name": "午后题材",
            "trade_date": "2026-07-08",
            "period": "即时",
            "main_net_inflow": 100_000_000_000,
            "main_net_inflow_ratio": 20.0,
        },
    ]
    sector_scores = [
        *sample_limit_up_dataset["sector_scores"],
        {
            "sector_id": "late_sector",
            "as_of_date": "2026-07-08",
            "period": "20d",
            "heat_score": 99.0,
            "momentum_score": 99.0,
            "breadth_score": 99.0,
            "fund_score": 99.0,
            "sentiment_score": 99.0,
            "leader_score": 99.0,
            "continuity_score": 99.0,
            "risk_penalty": 0.0,
            "trend_state": "MAINLINE_UP",
            "confidence": 1.0,
        },
    ]

    report = build_limit_up_proxy_backtest(
        {
            **sample_limit_up_dataset,
            "events": events,
            "memberships": memberships,
            "sector_flows": sector_flows,
            "sector_scores": sector_scores,
        },
        exit_mode="next_open",
    )

    assert len(report["orders"]) == 5
    assert late_symbol in {order["vt_symbol"] for order in report["orders"]}


def test_proxy_backtest_reports_conservative_and_optimistic_scenarios(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    report = build_limit_up_proxy_backtest(sample_limit_up_dataset, exit_mode="next_open")

    assert report["status"] == "ready"
    assert report["mode"] == "historical_event_proxy"
    assert report["scenarios"]["conservative"]["summary"]["trade_count"] > 0
    assert (
        report["scenarios"]["optimistic"]["summary"]["trade_count"]
        >= report["scenarios"]["conservative"]["summary"]["trade_count"]
    )
    assert report["coverage"]["minute_or_tick_coverage"] is False
    assert report["limitations"]
    conservative = report["scenarios"]["conservative"]
    assert conservative["summary"]["total_return_pct"] == conservative["equity"][-1]["total_return_pct"]
    assert conservative["summary"]["max_drawdown_pct"] is not None
    assert conservative["factor_buckets"]
    assert {row["factor"] for row in conservative["factor_buckets"]} >= {
        "market_rank",
        "board_level",
        "first_touch_time",
        "open_times",
        "prior_sector_flow",
        "final_board_status",
        "seal_to_turnover",
        "turnover_quality",
    }
    assert conservative["outcome_summary"]
    assert all("d1_analysis" in trade for trade in conservative["trades"])
    assert sum(
        row["trade_count"]
        for row in conservative["factor_buckets"]
        if row["factor"] == "market_rank"
    ) == conservative["summary"]["trade_count"]
    assert report["orders"]
    assert all("signal_board_level" in order for order in report["orders"])
    assert all("decision" in order for order in report["orders"])


@pytest.mark.parametrize("entry_mode", ["auction", "sweep", "tail", "next_auction"])
def test_entry_backtest_keeps_historical_proxy_modes_separate(
    sample_limit_up_dataset: dict[str, object],
    entry_mode: str,
) -> None:
    report = build_limit_up_entry_backtest(
        sample_limit_up_dataset,
        [],
        entry_mode=entry_mode,
        exit_mode="next_open",
    )

    assert report["entry_mode"] == entry_mode
    assert report["coverage"]["strict_snapshot_orders"] == 0
    assert all(order["source_mode"] == "historical_proxy" for order in report["orders"])


def test_research_plan_does_not_reuse_first_open_proxy_as_reseal_profit(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    report = build_limit_up_proxy_backtest(sample_limit_up_dataset, exit_mode="next_open")
    research = report["research_plan"]

    assert research["verification_status"] == "blocked_by_missing_reseal_queue_data"
    assert research["scenario"]["summary"]["filled_order_count"] == 0
    assert research["scenario"]["summary"]["trade_count"] == 0
    assert research["scenario"]["summary"]["total_return_pct"] == 0.0
    assert research["observational_first_open"]["warning"]


def test_proxy_backtest_keeps_a_d1_result_ledger_for_every_signal_day(
    sample_limit_up_dataset: dict[str, object],
) -> None:
    events = list(sample_limit_up_dataset["events"])
    events.append({**events[1], "trade_date": "2026-07-10"})
    report = build_limit_up_proxy_backtest(
        {**sample_limit_up_dataset, "events": events},
        exit_mode="next_open",
    )

    scenario = report["scenarios"]["conservative"]
    daily = scenario["daily_results"]

    assert [row["trade_date"] for row in daily] == ["2026-07-09", "2026-07-10"]
    assert daily[0]["result_date"] == "2026-07-10"
    assert daily[0]["closed_trade_count"] == len(
        [trade for trade in scenario["trades"] if trade["signal_date"] == "2026-07-09"]
    )
    assert daily[0]["win_rate"] is not None
    assert daily[0]["equity"] is not None
    assert daily[0]["drawdown_pct"] is not None
    assert daily[1]["result_date"] is None
    assert daily[1]["result_status"] == "awaiting_d1_bar"
    assert daily[1]["closed_trade_count"] == 0
    assert daily[1]["equity"] == daily[0]["equity"]
    assert scenario["summary"]["trade_day_count"] == 2
    assert all(trade["d1_open_return_pct"] == trade["return_pct"] for trade in scenario["trades"])
    assert all(trade["d1_close_return_pct"] is not None for trade in scenario["trades"])


def test_limit_up_dashboard_route_returns_service_payload(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_dashboard",
        lambda target_date=None: {
            "status": "ready",
            "trade_date": target_date.isoformat() if target_date else "2026-07-09",
            "top_dragons": [{"vt_symbol": "600001.SSE"}],
        },
    )

    response = TestClient(create_app()).get(
        "/api/limit-up/dashboard",
        params={"date": "2026-07-08"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["trade_date"] == "2026-07-08"
    assert response.json()["data"]["top_dragons"][0]["vt_symbol"] == "600001.SSE"


def test_limit_up_dates_route_returns_service_payload(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_signal_dates",
        lambda: {"status": "ready", "dates": ["2026-07-08", "2026-07-09"]},
    )

    response = TestClient(create_app()).get("/api/limit-up/dates")

    assert response.status_code == 200
    assert response.json()["data"]["dates"][-1] == "2026-07-09"


def test_limit_up_signals_route_passes_date_and_as_of(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_signals(target_date, as_of):
        captured.update(target_date=target_date, as_of=as_of)
        return {"mode": "live_snapshot", "trade_date": target_date.isoformat()}

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_signals", fake_signals)

    response = TestClient(create_app()).get(
        "/api/limit-up/signals",
        params={"date": "2026-07-09", "as_of": "2026-07-09T10:15:00+08:00"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["mode"] == "live_snapshot"
    assert str(captured["target_date"]) == "2026-07-09"
    assert captured["as_of"].hour == 10


def test_limit_up_signals_route_rejects_as_of_from_another_date(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)

    response = TestClient(create_app()).get(
        "/api/limit-up/signals",
        params={"date": "2026-07-09", "as_of": "2026-07-10T10:15:00+08:00"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_AS_OF"


def test_limit_up_trade_dates_use_lightweight_repository(monkeypatch) -> None:
    from alphaagent.server.services.limit_up import service

    service._TRADE_DATE_CACHE.clear()
    monkeypatch.setattr(
        service,
        "list_limit_up_event_dates",
        lambda: ["2026-07-09", "2026-07-10"],
    )
    monkeypatch.setattr(
        service,
        "load_limit_up_dataset",
        lambda *_args, **_kwargs: pytest.fail("date lookup must not load the full dataset"),
    )

    result = service.get_limit_up_trade_dates()

    assert result["dates"] == ["2026-07-09", "2026-07-10"]
    assert result["latest"] == "2026-07-10"
    assert result["count"] == 2
    service._TRADE_DATE_CACHE.clear()


def test_limit_up_dashboard_bounds_and_coalesces_selected_day_load(monkeypatch) -> None:
    from alphaagent.server.services.limit_up import service

    service._DASHBOARD_CACHE.clear()
    service._TRADE_DATE_CACHE.clear()
    calls: list[tuple[date | None, date | None]] = []
    monkeypatch.setattr(
        service,
        "list_limit_up_event_dates",
        lambda: ["2026-07-08", "2026-07-09", "2026-07-10"],
    )

    def fake_load(start=None, end=None):
        calls.append((start, end))
        return {"events": [], "coverage": {}}

    monkeypatch.setattr(service, "load_limit_up_dataset", fake_load)
    monkeypatch.setattr(
        service,
        "build_limit_up_dashboard",
        lambda _dataset, *, target_date=None: {
            "status": "ready",
            "trade_date": target_date.isoformat() if target_date else None,
        },
    )

    target = date(2026, 7, 9)
    first = service.get_limit_up_dashboard(target)
    second = service.get_limit_up_dashboard(target)

    assert calls == [(target, target)]
    assert first == second
    assert first["available_dates"] == ["2026-07-08", "2026-07-09", "2026-07-10"]
    assert first["navigation"] == {
        "previous": "2026-07-08",
        "next": "2026-07-10",
    }
    service._DASHBOARD_CACHE.clear()
    service._TRADE_DATE_CACHE.clear()


def test_limit_up_backtest_route_rejects_invalid_exit_mode() -> None:
    response = TestClient(create_app()).get(
        "/api/limit-up/backtest",
        params={"exit_mode": "same_close"},
    )

    assert response.status_code == 422


def test_limit_up_backtest_route_passes_dates_to_service(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_backtest(start, end, exit_mode):
        captured.update(start=start, end=end, exit_mode=exit_mode)
        return {"status": "ready", "scenarios": {}}

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_proxy_backtest", fake_backtest)

    response = TestClient(create_app()).get(
        "/api/limit-up/backtest",
        params={"start": "2026-06-01", "end": "2026-07-09", "exit_mode": "next_close"},
    )

    assert response.status_code == 200
    assert str(captured["start"]) == "2026-06-01"
    assert str(captured["end"]) == "2026-07-09"
    assert captured["exit_mode"] == "next_close"


def test_limit_up_entry_backtest_route_passes_entry_mode(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_entry_backtest(start, end, entry_mode, exit_mode):
        captured.update(
            start=start,
            end=end,
            entry_mode=entry_mode,
            exit_mode=exit_mode,
        )
        return {"status": "ready", "entry_mode": entry_mode, "trades": []}

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_history_backtest", fake_entry_backtest)

    response = TestClient(create_app()).get(
        "/api/limit-up/backtest",
        params={
            "start": "2026-06-01",
            "end": "2026-07-09",
            "entry_mode": "tail",
            "exit_mode": "next_close",
        },
    )

    assert response.status_code == 200
    assert captured["entry_mode"] == "tail"
    assert captured["exit_mode"] == "next_close"
