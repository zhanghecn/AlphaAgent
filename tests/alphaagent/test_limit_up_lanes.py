from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up import (
    history_engine,
    history_service,
    lane_research,
    next_session_plan,
)
from alphaagent.server.services.limit_up.lane_features import (
    attach_limit_gene_features,
    classify_financial_risk,
    intraday_path_times,
    minute_bars_to_intraday_price_path,
    path_prefix_features,
    price_path_to_return_path,
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
    merge_event_minute_price_paths,
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


def test_background_history_rebuild_refreshes_final_plan(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        history_service,
        "_now_shanghai",
        lambda: datetime(2026, 7, 20, 23, 50),
        raising=False,
    )
    monkeypatch.setattr(
        history_service,
        "rebuild_history_sync",
        lambda: calls.append("rebuild") or {"status": "ready"},
    )
    monkeypatch.setattr(
        next_session_plan,
        "refresh_next_session_plan",
        lambda phase: calls.append(phase) or {"status": "ready"},
    )

    history_service._background_rebuild()

    assert calls == ["rebuild", "final"]


def test_background_history_rebuild_does_not_save_plan_during_live_session(
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        history_service,
        "_now_shanghai",
        lambda: datetime(2026, 7, 21, 10, 5),
        raising=False,
    )
    monkeypatch.setattr(
        history_service,
        "rebuild_history_sync",
        lambda: calls.append("rebuild") or {"status": "ready"},
    )
    monkeypatch.setattr(
        next_session_plan,
        "refresh_next_session_plan",
        lambda phase: calls.append(phase) or {"status": "ready"},
    )

    history_service._background_rebuild()

    assert calls == ["rebuild"]


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


def test_limit_gene_vectorized_windows_match_group_rolling_reference() -> None:
    first = _daily_rows()
    second = _daily_rows().assign(vt_symbol="000001.SZSE")
    second["close_price"] = second["close_price"] * 1.3
    second["low_price"] = second["low_price"] * 1.3
    source = pd.concat([first, second], ignore_index=True).sample(
        frac=1,
        random_state=7,
    )
    original = source.copy(deep=True)
    expected = source.copy().sort_values(
        ["vt_symbol", "trade_date"],
        kind="stable",
    )
    expected["high_price"] = expected["close_price"]
    grouped = expected.groupby("vt_symbol", sort=False)
    expected["prior_limit_count_126"] = grouped["sealed"].transform(
        lambda values: values.shift(1).rolling(126, min_periods=1).sum()
    ).fillna(0).astype(int)
    expected["prior_touch_count_126"] = grouped["touched"].transform(
        lambda values: values.shift(1).rolling(126, min_periods=1).sum()
    ).fillna(0).astype(int)
    expected["prior_limit_count_5"] = grouped["sealed"].transform(
        lambda values: values.shift(1).rolling(5, min_periods=1).sum()
    ).fillna(0).astype(int)
    expected["prior_limit_count_10"] = grouped["sealed"].transform(
        lambda values: values.shift(1).rolling(10, min_periods=1).sum()
    ).fillna(0).astype(int)
    expected["prior_low_120"] = grouped["low_price"].transform(
        lambda values: values.shift(1).rolling(120, min_periods=20).min()
    )
    expected["prior_high_120"] = grouped["high_price"].transform(
        lambda values: values.shift(1).rolling(120, min_periods=20).max()
    )

    result = attach_limit_gene_features(source)

    pd.testing.assert_frame_equal(source, original)
    pd.testing.assert_frame_equal(
        result[
            [
                "prior_limit_count_126",
                "prior_touch_count_126",
                "prior_limit_count_5",
                "prior_limit_count_10",
            ]
        ],
        expected[
            [
                "prior_limit_count_126",
                "prior_touch_count_126",
                "prior_limit_count_5",
                "prior_limit_count_10",
            ]
        ],
    )
    pd.testing.assert_series_equal(
        result["prior_position_120"],
        (
            (grouped["close_price"].shift(1) - expected["prior_low_120"])
            / (expected["prior_high_120"] - expected["prior_low_120"]).replace(0, pd.NA)
        ).clip(lower=0, upper=1),
        check_names=False,
    )


def test_intraday_path_uses_eighty_three_minute_points() -> None:
    times = intraday_path_times()

    assert len(times) == 80
    assert times[0] == "09:30:00"
    assert times[39] == "11:27:00"
    assert times[40] == "13:00:00"
    assert times[-1] == "14:57:00"


def test_minute_bars_are_resampled_without_crossing_session_boundaries() -> None:
    bars = [
        {
            "bar_time": datetime(2026, 7, 14, 9, 31),
            "open_price": 10.10,
            "close_price": 10.20,
        },
        {
            "bar_time": datetime(2026, 7, 14, 9, 33),
            "open_price": 10.30,
            "close_price": 10.50,
        },
        {
            "bar_time": datetime(2026, 7, 14, 13, 1),
            "open_price": 10.80,
            "close_price": 10.90,
        },
        {
            "bar_time": datetime(2026, 7, 14, 13, 3),
            "open_price": 10.90,
            "close_price": 11.00,
        },
    ]

    prices = minute_bars_to_intraday_price_path(bars)
    returns = price_path_to_return_path(prices, previous_close=10.0)

    assert len(prices) == 80
    assert prices[0] == 10.10
    assert prices[1] == 10.50
    assert prices[40] == 10.80
    assert prices[41] == 11.00
    assert returns[0] == 1.0
    assert returns[1] == 5.0
    assert returns[40] == 8.0
    assert returns[41] == 10.0


def test_event_preview_wins_over_minute_price_fallback() -> None:
    preview_key = ("600001.SSE", date(2026, 7, 14))
    fallback_key = ("600002.SSE", date(2026, 7, 14))
    events = {
        preview_key: {
            "vt_symbol": preview_key[0],
            "trade_date": preview_key[1],
            "time_preview": [1.0, 2.0, 3.0],
            "path_source": "ths.limit_up_pool",
        },
        fallback_key: {
            "vt_symbol": fallback_key[0],
            "trade_date": fallback_key[1],
            "time_preview": [],
            "path_source": None,
        },
    }
    minute_paths = {
        preview_key: {
            "path": [10.0] * 80,
            "source": "stock_minute_bars:tdx_public_hq",
            "bar_count": 240,
        },
        fallback_key: {
            "path": [11.0] * 80,
            "source": "stock_minute_bars:tdx_public_hq",
            "bar_count": 240,
        },
    }

    merged = merge_event_minute_price_paths(events, minute_paths)

    assert "minute_price_path" not in merged[preview_key]
    assert merged[preview_key]["path_source"] == "ths.limit_up_pool"
    assert merged[fallback_key]["minute_price_path"] == [11.0] * 80
    assert merged[fallback_key]["path_source"] == "stock_minute_bars:tdx_public_hq"
    assert merged[fallback_key]["minute_path_bar_count"] == 240


def test_minute_fallback_prefix_ignores_prices_after_signal_time() -> None:
    prices = [10.0 + index * 0.10 for index in range(80)]
    baseline = history_engine._event_intraday_path(
        {"time_preview": [], "minute_price_path": prices},
        previous_close=10.0,
    )
    changed_prices = list(prices)
    changed_prices[13] = 1.0
    changed = history_engine._event_intraday_path(
        {"time_preview": [], "minute_price_path": changed_prices},
        previous_close=10.0,
    )

    baseline_prefix = path_prefix_features(baseline, "10:06:00")
    changed_prefix = path_prefix_features(changed, "10:06:00")

    assert baseline_prefix == changed_prefix
    assert baseline_prefix["point_count"] == 13


def test_minute_fallback_reaches_first_board_intraday_support_gate() -> None:
    key = ("600001.SSE", date(2026, 7, 14))
    returns = [0.5] * 9 + [2.0, 3.0, 4.5, 6.5, 8.0, 9.8]
    prices = [10.0 * (1 + value / 100) for value in returns] + [None] * 65
    merged = merge_event_minute_price_paths(
        {
            key: {
                "vt_symbol": key[0],
                "trade_date": key[1],
                "time_preview": [],
            }
        },
        {
            key: {
                "path": prices,
                "source": "stock_minute_bars:tdx_public_hq",
                "bar_count": 15,
            }
        },
    )

    path = history_engine._event_intraday_path(
        merged[key],
        previous_close=10.0,
    )
    evaluated = evaluate_lane_candidate(
        _candidate(path_prefix=path_prefix_features(path, "10:12:00"))
    )

    assert "intraday_support_unavailable" not in evaluated["blockers"]
    assert "intraday_support_confirmed" in evaluated["favorable_factors"]
    assert evaluated["decision"] == "eligible"


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


def _weak_market_attack_candidate(**overrides: object) -> dict[str, object]:
    candidate = _candidate(
        prior_touch_count_126=3,
        prior_industry_heat_score=60.0,
        prior_industry_leader_rank=2,
        prior_market_phase="mixed",
        prior_market_failed_rate=0.30,
        financial_snapshot=None,
        path_prefix={
            **dict(_candidate()["path_prefix"]),
            "approach_3point_pct": 0.0,
            "recent_15m_min_pct": 5.0,
            "recent_15m_change_pct": 0.0,
            "recent_15m_drawdown_pct": 0.0,
        },
    )
    candidate.update(overrides)
    return candidate


def test_non_consecutive_third_limit_is_routed_to_two_to_three() -> None:
    candidate = _candidate(prior_streak=0, prior_limit_count_5=2, target_board=3)

    assert classify_board_lane(candidate) == "two_to_three"


def test_one_to_two_is_not_an_active_research_lane() -> None:
    assert BOARD_LANES == ("first_board", "two_to_three", "high_board")

    with pytest.raises(ValueError, match="removed"):
        evaluate_lane_candidate(
            _candidate(prior_streak=1, prior_limit_count_5=1, target_board=2)
        )


def test_lane_selection_ignores_current_day_final_board_outcome() -> None:
    candidates = [
        _candidate(
            vt_symbol="600001.SSE",
            outcome={"touched": True, "sealed": True},
        ),
        _candidate(
            vt_symbol="600002.SSE",
            outcome={"touched": True, "sealed": False},
            prior_industry_leader_rank=2,
        ),
    ]
    flipped = [
        {
            **candidate,
            "outcome": {
                "touched": not bool(candidate["outcome"]["touched"]),
                "sealed": not bool(candidate["outcome"]["sealed"]),
            },
        }
        for candidate in candidates
    ]

    baseline = select_daily_lane_portfolio(candidates)
    changed = select_daily_lane_portfolio(flipped)

    selection_fields = ("vt_symbol", "decision", "rank_score", "pool_rank")
    assert [
        tuple(row[field] for field in selection_fields)
        for row in baseline["candidate_pool"]["first_board"]
    ] == [
        tuple(row[field] for field in selection_fields)
        for row in changed["candidate_pool"]["first_board"]
    ]
    assert [row["vt_symbol"] for row in baseline["selected"]] == [
        row["vt_symbol"] for row in changed["selected"]
    ]


def test_recent_nonconsecutive_limit_stays_in_first_board_lane() -> None:
    candidate = _candidate(
        prior_streak=0,
        prior_limit_count_5=1,
        target_board=1,
        previous_limit_up=False,
    )

    assert classify_board_lane(candidate) == "first_board"


def test_short_cycle_deep_pullback_is_first_board_return_setup() -> None:
    result = evaluate_lane_candidate(
        _candidate(
            prior_streak=0,
            prior_limit_count_5=1,
            target_board=1,
            previous_limit_up=False,
            trade_days_since_prior_limit=3,
            pullback_from_prior_limit_pct=-9.42,
            prior_change_pct=-2.31,
            auction_gap_pct=2.04,
            prior_position_120=0.81,
        )
    )

    assert result["lane"] == "first_board"
    assert "return_board" in result["setup_tags"]
    assert "not_first_board_after_cooling" not in result["blockers"]
    assert "low_position_missing" not in result["blockers"]


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


def test_first_board_evaluation_reuses_support_score(monkeypatch) -> None:
    calls = 0
    original = lane_research.first_board_support_score

    def counted(candidate):
        nonlocal calls
        calls += 1
        return original(candidate)

    monkeypatch.setattr(lane_research, "first_board_support_score", counted)

    result = evaluate_lane_candidate(_candidate())

    assert result["decision"] == "eligible"
    assert calls == 1


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


def test_weak_market_theme_attack_softens_only_the_frozen_three_blockers() -> None:
    result = evaluate_lane_candidate(_weak_market_attack_candidate())

    assert result["decision"] == "eligible"
    assert result["first_board_route"] == "weak_market_theme_attack"
    assert result["premium_gate_passed"] is True
    assert "weak_market_theme_attack" in result["setup_tags"]
    assert "weak_market_theme_attack_setup" in result["favorable_factors"]
    assert not {
        "first_board_touch_gene_weak",
        "financial_report_unavailable",
        "first_board_repair_setup_missing",
    }.intersection(result["blockers"])


def test_weak_market_theme_attack_keeps_thresholds_and_hard_risks() -> None:
    below_support_path = {
        **dict(_weak_market_attack_candidate()["path_prefix"]),
        "recent_15m_min_pct": 4.995,
    }
    cases = (
        ("first_board_touch_gene_weak", {"prior_touch_count_126": 2}),
        ("first_board_touch_gene_weak", {"path_prefix": below_support_path}),
        ("first_board_repair_setup_missing", {"prior_industry_heat_score": 59.99}),
        ("first_board_repair_setup_missing", {"prior_industry_leader_rank": 3}),
        ("first_board_repair_setup_missing", {"prior_market_phase": "broad_rise"}),
        ("first_board_repair_setup_missing", {"prior_market_phase": "repair"}),
        (
            "first_board_profit_growth_weak",
            {"financial_snapshot": {"net_profit_yoy": 9.99}},
        ),
        (
            "low_position_missing",
            {
                "prior_position_120": 0.82,
                "pullback_from_prior_limit_pct": -2.0,
                "trade_days_since_prior_limit": 2,
            },
        ),
        (
            "fundamental_risk",
            {"financial_risk": {"level": "blocked", "blocked": True}},
        ),
    )

    for expected_blocker, overrides in cases:
        result = evaluate_lane_candidate(
            _weak_market_attack_candidate(**overrides)
        )
        assert result["decision"] == "blocked"
        assert expected_blocker in result["blockers"]


def test_weak_market_theme_attack_does_not_read_final_outcomes() -> None:
    candidate = _weak_market_attack_candidate(
        outcome={"touched": True, "sealed": True, "next_close_return_pct": 10.0}
    )
    changed = {
        **candidate,
        "outcome": {
            "touched": False,
            "sealed": False,
            "next_close_return_pct": -10.0,
        },
    }

    baseline = evaluate_lane_candidate(candidate)
    flipped = evaluate_lane_candidate(changed)

    for field in (
        "decision",
        "blockers",
        "first_board_route",
        "setup_tags",
        "premium_gate_passed",
        "rank_score",
    ):
        assert baseline[field] == flipped[field]


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
            prior_streak=2,
            prior_limit_count_5=2,
            target_board=3,
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
    two_to_three = evaluate_lane_candidate(
        _candidate(
            prior_streak=2,
            prior_limit_count_5=2,
            target_board=3,
            signal_time="09:25:00",
            prior_board={"is_sealed": True},
        )
    )

    assert two_to_three["decision"] == "blocked"
    assert "prior_board_path_incomplete" in two_to_three["blockers"]


def test_first_board_does_not_use_previous_day_industry_rank_as_live_core_proxy() -> None:
    third = evaluate_lane_candidate(_candidate(prior_industry_leader_rank=3))
    unknown = evaluate_lane_candidate(_candidate(prior_industry_leader_rank=None))
    relay = evaluate_lane_candidate(
        _candidate(
            prior_streak=2,
            prior_limit_count_5=2,
            target_board=3,
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
    assert result["action"] == "observe"
    assert result["setup_type"] == "high_board_weak_to_strong"


def test_selection_allows_empty_days_and_never_exceeds_four_candidates() -> None:
    candidates = [
        _candidate(vt_symbol="600001.SSE"),
        _candidate(vt_symbol="600003.SSE", prior_streak=2, prior_limit_count_5=2, target_board=3, signal_time="09:25:00"),
        _candidate(vt_symbol="600004.SSE", prior_streak=3, prior_limit_count_5=3, target_board=4, signal_time="09:25:00", has_l2=True, prior_market_phase="broad_rise", prior_industry_heat_rank=1),
        _candidate(vt_symbol="600005.SSE", industry_id="BK1002"),
    ]

    selected = select_daily_lane_portfolio(candidates)
    retreat = select_daily_lane_portfolio(
        [
            _candidate(
                prior_market_phase="retreat",
                prior_market_failed_rate=0.20,
                prior_industry_heat_score=59.99,
            )
        ]
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


def test_history_replay_indexes_event_evidence_once(monkeypatch) -> None:
    class CountingEventIndex(dict):
        items_calls = 0

        def items(self):
            self.items_calls += 1
            return super().items()

    first_date = date(2026, 7, 17)
    second_date = date(2026, 7, 20)
    events = CountingEventIndex(
        {
            ("600001.SSE", first_date): {"first_limit_time": "10:00:00"},
            ("600002.SSE", second_date): {"first_limit_time": "10:30:00"},
        }
    )
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp(first_date), pd.Timestamp(second_date)],
            "prev_close": [10.0, 11.0],
        }
    )
    observed: list[dict[str, object]] = []
    monkeypatch.setattr(
        history_engine,
        "_route_candidates_from_day",
        lambda *_args, **_kwargs: {mode: [] for mode in history_engine.ENTRY_MODES},
    )

    def fake_board_candidates(*_args, current_event_evidence=None, **_kwargs):
        observed.append(dict(current_event_evidence or {}))
        return []

    monkeypatch.setattr(
        history_engine,
        "_board_lane_candidates_from_day",
        fake_board_candidates,
    )
    monkeypatch.setattr(
        history_engine,
        "_day_market_context_from_day",
        lambda *_args, **_kwargs: {},
    )

    history_engine.build_history_replays(
        frame,
        warmup_days=0,
        holdout_days=0,
        event_evidence=events,
    )

    assert events.items_calls == 1
    assert observed == [
        {"600001.SSE": {"first_limit_time": "10:00:00"}},
        {"600002.SSE": {"first_limit_time": "10:30:00"}},
    ]


def test_history_replay_uses_daily_position_index(monkeypatch) -> None:
    first_date = date(2026, 7, 17)
    second_date = date(2026, 7, 20)
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp(second_date), pd.Timestamp(first_date)],
            "vt_symbol": ["600002.SSE", "600001.SSE"],
            "prev_close": [11.0, 10.0],
        }
    )
    groupby_type = type(frame.groupby("trade_date", sort=False))

    def fail_get_group(*_args, **_kwargs):
        pytest.fail("daily replay must not copy every wide group through get_group")

    monkeypatch.setattr(groupby_type, "get_group", fail_get_group)
    observed: list[date] = []

    def fake_routes(day, **_kwargs):
        observed.append(day.iloc[0]["trade_date"].date())
        return {mode: [] for mode in history_engine.ENTRY_MODES}

    monkeypatch.setattr(history_engine, "_route_candidates_from_day", fake_routes)
    monkeypatch.setattr(
        history_engine,
        "_board_lane_candidates_from_day",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        history_engine,
        "_day_market_context_from_day",
        lambda *_args, **_kwargs: {},
    )

    result = history_engine.build_history_replays(
        frame,
        warmup_days=0,
        holdout_days=0,
    )

    assert observed == [first_date, second_date]
    assert [row["trade_date"] for row in result] == [
        first_date.isoformat(),
        second_date.isoformat(),
    ]


def test_history_replay_materializes_only_potential_candidate_rows(
    monkeypatch,
) -> None:
    trade_date = date(2026, 7, 20)
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime([trade_date] * 3),
            "vt_symbol": ["600001.SSE", "600002.SSE", "600003.SSE"],
            "prev_close": [10.0, 10.0, 10.0],
            "open_price": [10.3, 10.0, 10.0],
            "auction_gap_pct": [3.0, 0.0, 0.0],
        }
    )
    observed: list[list[str]] = []

    def fake_routes(day, **_kwargs):
        observed.append(day["vt_symbol"].tolist())
        return {mode: [] for mode in history_engine.ENTRY_MODES}

    monkeypatch.setattr(history_engine, "_route_candidates_from_day", fake_routes)
    monkeypatch.setattr(
        history_engine,
        "_board_lane_candidates_from_day",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        history_engine,
        "_day_market_context_from_day",
        lambda *_args, **_kwargs: {},
    )

    history_engine.build_history_replays(
        frame,
        warmup_days=0,
        holdout_days=0,
        event_evidence={
            ("600002.SSE", trade_date): {"first_limit_time": "10:00:00"},
        },
    )

    assert observed == [["600001.SSE", "600002.SSE"]]


def test_prior_market_features_are_attached_by_date_index() -> None:
    frame = pd.DataFrame(
        {
            "expected_prev_trade_date": [
                pd.Timestamp("2026-07-16"),
                pd.Timestamp("2026-07-17"),
                pd.NaT,
            ]
        }
    )
    market = pd.DataFrame(
        {
            "advancing_rate": [0.34, 0.65],
            "sealed_count": [20, 40],
            "failed_rate": [0.5, 0.2],
            "max_board": [3, 5],
            "first_board_count": [15, 30],
            "one_to_two_rate": [0.2, 0.4],
            "two_to_three_rate": [0.1, 0.3],
        },
        index=pd.to_datetime(["2026-07-16", "2026-07-17"]),
    )

    history_engine._attach_prior_market_features(frame, market)

    assert frame["prior_market_advancing_rate"].tolist()[:2] == [0.34, 0.65]
    assert frame["prior_market_sealed_count"].tolist()[:2] == [20.0, 40.0]
    assert frame["prior_market_phase"].astype(str).tolist() == [
        "retreat",
        "broad_rise",
        "unknown",
    ]


def test_history_replay_resolves_each_analog_bucket_once_per_day(
    monkeypatch,
) -> None:
    trade_date = date(2026, 7, 20)
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp(trade_date)],
            "prev_close": [10.0],
        }
    )
    candidates = [
        {
            "vt_symbol": f"{600000 + index}.SSE",
            "entry_mode": "auction",
            "target_board": 1,
            "known_at_signal": {
                "auction_gap_pct": 3.5,
                "prior_change_pct": 1.0,
                "prior_turnover_rate": 5.0,
                "prior_amount_ratio_5d": 1.1,
                "prior_market_phase": "broad_rise",
            },
            "outcome": {},
        }
        for index in range(20)
    ]
    monkeypatch.setattr(
        history_engine,
        "_route_candidates_from_day",
        lambda *_args, **_kwargs: {
            "auction": candidates,
            "sweep": [],
            "tail": [],
            "next_auction": [],
        },
    )
    monkeypatch.setattr(
        history_engine,
        "_board_lane_candidates_from_day",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        history_engine,
        "_day_market_context_from_day",
        lambda *_args, **_kwargs: {},
    )
    original_resolve = history_engine._resolve_analog
    resolve_calls = 0

    def counted_resolve(*args, **kwargs):
        nonlocal resolve_calls
        resolve_calls += 1
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(history_engine, "_resolve_analog", counted_resolve)

    history_engine.build_history_replays(
        frame,
        warmup_days=0,
        holdout_days=0,
    )

    assert resolve_calls == 1


def test_history_relay_requires_current_day_event_and_uses_limit_entry() -> None:
    trade_date = date(2026, 7, 10)
    day = pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp(trade_date),
                "prev_trade_date": pd.Timestamp("2026-07-09"),
                "next_trade_date": pd.Timestamp("2026-07-13"),
                "vt_symbol": "600001.SSE",
                "name": "接力样本",
                "prev_close": 10.0,
                "open_price": 10.3,
                "close_price": 11.0,
                "next_open_price": 12.0,
                "next_close_price": 12.5,
                "limit_price": 11.0,
                "auction_gap_pct": 3.0,
                "prior_streak": 2,
                "prior_limit_count_5": 2,
            }
        ]
    )
    path = [0.0] * 80
    path[12] = 9.8  # 10:06
    event = {
        "first_limit_time": "10:06:00",
        "time_preview": path,
        "path_source": "test",
    }

    ready = history_engine._board_lane_candidates_from_day(
        day,
        trade_date,
        event_evidence={("600001.SSE", trade_date): event},
        financial_index={},
        total_cost_rate=0.0031,
    )[0]
    missing = history_engine._board_lane_candidates_from_day(
        day,
        trade_date,
        event_evidence={},
        financial_index={},
        total_cost_rate=0.0031,
    )[0]

    assert ready["relay_trigger_status"] == "ready"
    assert ready["buy_time"] == "10:06:00"
    assert ready["signal_kind"] == "first_touch"
    assert ready["entry_price"] == 11.0
    assert missing["relay_trigger_status"] == "event_missing"
    assert missing["buy_time"] is None
    assert missing["entry_price"] is None


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
            "600002.SSE", "high_board", industry_id="BK2", rank_score=80
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
        "600003.SSE",
        "600002.SSE",
    ]
    assert len(result["selected"]) == 4
    assert result["selection_policy"] == "diversified_then_ranked_v1"


def test_daily_portfolio_enforces_industry_limit_and_symbol_deduplication() -> None:
    candidates = [
        _pre_evaluated_candidate(
            "600001.SSE", "first_board", industry_id="BK1", rank_score=100
        ),
        _pre_evaluated_candidate(
            "600001.SSE", "high_board", industry_id="BK1", rank_score=99
        ),
        _pre_evaluated_candidate(
            "600002.SSE", "high_board", industry_id="BK1", rank_score=98
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
        "600003.SSE",
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
        "lane_label": {
            "first_board": "首板",
            "two_to_three": "二进三",
            "high_board": "高板",
        }.get(lane, lane),
        "decision": "eligible",
        "action": "buy_first_board" if lane == "first_board" else "buy_intraday",
        "signal_date": trade_date,
        "entry_date": trade_date,
        "result_date": result_date,
        "entry_price": 11.0,
        "buy_time": "10:12:00",
        "signal_time": "10:12:00",
        "signal_kind": "first_touch",
        "relay_trigger_status": "ready" if lane != "first_board" else None,
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
            "candidate_pool": lanes,
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


def test_product_ledger_uses_scheduled_account_when_lane_is_omitted(monkeypatch) -> None:
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_day",
        lambda *_args: _lane_replay_day(),
    )
    monkeypatch.setattr(
        history_service,
        "get_scheduled_history_backtest",
        lambda *_args, **_kwargs: {
            "trades": [
                {
                    "lane": "first_board",
                    "vt_symbol": "600001.SSE",
                    "name": "固定窗口样本",
                    "buy_date": "2026-06-10",
                    "buy_time": "10:12:00",
                    "buy_price": 11.0,
                    "sell_date": "2026-06-11",
                    "sell_time": "15:00:00",
                    "sell_price": 11.6,
                    "return_pct": 5.0,
                    "d1_outcome": "d1_premium",
                    "d_board_status": "sealed",
                    "execution_confidence": "three_minute_path_without_queue",
                    "exit_price_source": "daily_close",
                }
            ],
            "orders": [
                {
                    "side": "BUY",
                    "status": "filled",
                    "trade_date": "2026-06-10",
                }
            ],
            "validation": {"passed": False, "status": "research_only", "checks": []},
            "coverage": {"daily_close_count": 1},
            "execution_schedule": {"exit_time": "15:00"},
        },
    )

    ledger = history_service.get_history_ledger(date(2026, 6, 10), lane=None)

    assert ledger["lane"] is None
    assert ledger["exit_mode"] == "next_close"
    assert ledger["selected_count"] == 1
    assert ledger["trades"][0]["sell_time"] == "15:00:00"


def test_lane_ledger_uses_candidate_dynamic_exit_decision(monkeypatch) -> None:
    day = _lane_replay_day()
    candidate = day["lane_portfolio"]["selected"][0]
    candidate["dynamic_exit"] = {
        "mode": "auction_exit",
        "reason": "高板强竞价兑现",
        "policy_version": "limit-up-dynamic-exit-v1",
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
        exit_mode="dynamic",
    )

    assert ledger["exit_mode"] == "dynamic"
    assert ledger["trades"][0]["sell_time"] == "09:30:00"
    assert ledger["trades"][0]["return_pct"] == 3.2
    assert ledger["trades"][0]["dynamic_exit"]["mode"] == "auction_exit"


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


def test_independent_lane_next_1430_uses_scheduled_exit_prices(monkeypatch) -> None:
    day = _lane_replay_day(lane="two_to_three", return_pct=10.0)
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
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_1430_prices",
        lambda requests: [
            {
                "vt_symbol": symbol,
                "trade_date": trade_date.isoformat(),
                "price_1430": 11.5,
                "price_1430_source": "minute_1430",
            }
            for symbol, trade_date in requests
        ],
    )

    report = history_service.get_lane_history_backtest(
        None,
        None,
        lane="two_to_three",
        exit_mode="next_1430",
        account_config=history_service.cash_backtest.CashBacktestConfig(
            max_positions=2,
            commission_rate=0,
            minimum_commission=0,
            stamp_tax_rate=0,
            transfer_fee_rate=0,
            slippage_bps=0,
        ),
    )
    assert report["summary"]["trade_count"] == 1
    assert report["trades"][0]["sell_time"] == "14:30:00"
    assert report["trades"][0]["sell_price"] == 11.5
    assert report["trades"][0]["exit_price_source"] == "minute_1430"
    assert report["signal_summary"]["average_return_pct"] == 4.5455
    assert report["exit_summary"]["minute_1430_count"] == 1
    assert report["coverage"]["minute_1430_count"] == 1
    assert report["coverage"]["exit_price_missing_count"] == 0


def test_exact_1430_filter_removes_every_order_without_a_minute_price() -> None:
    orders = [
        {"vt_symbol": "600001.SSE", "result_date": "2026-07-17"},
        {"vt_symbol": "600002.SSE", "result_date": "2026-07-17"},
        {"vt_symbol": "600003.SSE", "result_date": "2026-07-17"},
    ]
    bars = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-17",
            "price_1430": 11.5,
            "price_1430_source": "minute_1430",
        },
        {
            "vt_symbol": "600002.SSE",
            "trade_date": "2026-07-17",
            "price_1430": 12.0,
            "price_1430_source": "daily_close_proxy",
        },
    ]

    selected, audit = history_service._filter_orders_with_exact_1430(orders, bars)

    assert [order["vt_symbol"] for order in selected] == ["600001.SSE"]
    assert audit == {
        "input_count": 3,
        "selected_count": 1,
        "excluded_no_exact_1430_count": 2,
    }


def test_daily_close_filter_removes_an_order_without_an_official_close() -> None:
    orders = [
        {"vt_symbol": "600001.SSE", "result_date": "2026-07-17"},
        {"vt_symbol": "600002.SSE", "result_date": "2026-07-17"},
    ]
    bars = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-17",
            "open_price": 11.0,
            "close_price": 11.5,
        },
        {
            "vt_symbol": "600002.SSE",
            "trade_date": "2026-07-17",
            "open_price": 12.0,
            "price_1430": 12.2,
            "price_1430_source": "minute_1430",
        },
    ]

    selected, audit = history_service._filter_orders_with_daily_close(orders, bars)

    assert [order["vt_symbol"] for order in selected] == ["600001.SSE"]
    assert audit == {
        "input_count": 2,
        "selected_count": 1,
        "excluded_no_daily_close_count": 1,
    }


def test_exit_price_attachment_removes_a_legacy_close_proxy(monkeypatch) -> None:
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_1430_prices",
        lambda _requests: [],
    )
    orders = [{"vt_symbol": "600001.SSE", "result_date": "2026-07-17"}]
    bars = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": "2026-07-17",
            "close_price": 12.0,
            "price_1430": 12.0,
            "price_1430_source": "daily_close_proxy",
        }
    ]

    attached, coverage = history_service._attach_scheduled_exit_prices(bars, orders)

    assert "price_1430" not in attached[0]
    assert "price_1430_source" not in attached[0]
    assert coverage["daily_close_proxy_count"] == 0
    assert coverage["excluded_no_exact_1430_count"] == 1


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


def test_portfolio_backtest_uses_scheduled_two_position_cash_account(monkeypatch) -> None:
    day = _lane_replay_day(lane="first_board", return_pct=8.0)
    development_day = _lane_replay_day(
        trade_date="2026-04-13",
        lane="first_board",
        return_pct=4.0,
    )
    first = day["lane_portfolio"]["selected"][0]
    relay = {
        **first,
        "vt_symbol": "600002.SSE",
        "name": "接力样本",
        "lane": "two_to_three",
        "signal_kind": "first_touch",
        "signal_time": "10:06:00",
        "buy_time": "10:06:00",
        "relay_trigger_status": "ready",
        "entry_price": 11.0,
        "limit_price": 11.0,
        "outcome": {
            **first["outcome"],
            "entry_day_close_price": 11.0,
            "next_open_price": 12.0,
            "next_close_price": 12.5,
            "next_open_return_pct": 8.78,
            "next_close_return_pct": 13.33,
        },
    }
    second_first = {
        **first,
        "vt_symbol": "600003.SSE",
        "name": "首板负样本",
        "signal_time": "10:08:00",
        "buy_time": "10:08:00",
        "entry_price": 10.0,
        "limit_price": 10.0,
        "outcome": {
            **first["outcome"],
            "entry_day_close_price": 10.0,
            "next_open_price": 9.2,
            "next_close_price": 9.2,
            "next_open_return_pct": -8.0,
            "next_close_return_pct": -8.0,
        },
    }
    day["lane_portfolio"]["selected"] = [first, relay, second_first]
    day["lane_portfolio"]["candidate_pool"]["first_board"] = [
        first,
        second_first,
    ]
    day["lane_portfolio"]["candidate_pool"]["two_to_three"] = [relay]
    day["board_lanes"]["two_to_three"] = [relay]
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_range",
        lambda _version, start, end, _compact: (
            [development_day, day] if start is None and end is None else [day]
        ),
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_daily_bars",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        history_service.first_board_stock_gene_research,
        "attach_prior_stock_gene_evidence_to_orders",
        lambda _days, orders: [
            {
                **order,
                **(
                    {
                        "stock_d1_sample_count": (
                            4 if order.get("vt_symbol") == "600003.SSE" else 5
                        ),
                        "stock_gene_combined_win_rate": 30.0,
                    }
                    if order.get("lane") == "first_board"
                    else {}
                ),
            }
            for order in orders
        ],
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_1430_prices",
        lambda _requests: (_ for _ in ()).throw(
            AssertionError("formal next-close replay must not query 14:30 prices")
        ),
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_post_auction_prices",
        lambda _requests: [],
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_auction_evidence",
        lambda _requests: [],
        raising=False,
    )
    history_service._BACKTEST_REPORT_CACHE.clear()

    report = history_service.get_lane_history_backtest(
        date(2026, 6, 10),
        date(2026, 6, 10),
        lane="portfolio",
        exit_mode="next_close",
    )

    assert report["lane"] == "portfolio"
    assert report["mode"] == "scheduled_unified_intraday_cash_replay"
    assert report["exit_mode"] == "next_close"
    assert report["account_config"]["initial_cash"] == 100_000
    assert report["account_config"]["max_positions"] == 2
    assert report["summary"] == report["execution_summary"]
    assert report["summary"]["signal_count"] == 2
    assert report["summary"]["trade_count"] == 2
    assert report["summary"]["total_return_pct"] == report["daily_results"][-1]["total_return_pct"]
    assert report["execution_schedule"]["entry_windows"] == [
        "10:00-11:30",
        "13:00-14:30",
    ]
    assert report["execution_schedule"]["exit_time"] == "15:00"
    assert report["execution_comparability"]["status"] == "candidate_proxy_only"
    assert report["execution_comparability"]["live_equivalent"] is False
    assert "intraday_sector_fund_flow" in report["execution_comparability"]["missing_evidence"]
    assert report["coverage"]["exit_price_request_count"] == 2
    assert report["coverage"]["daily_close_count"] == 2
    assert report["coverage"]["daily_close_missing_count"] == 0
    assert report["exit_summary"]["mode"] == "next_close"
    assert report["exit_summary"]["close_exit_count"] == 2
    assert set(report["stress_tests"]) == {"double_cost"}
    assert report["stress_tests"]["double_cost"]["total_return_pct"] is not None
    diagnostics = report["drawdown_diagnostics"]
    assert diagnostics["diagnostics_version"] == (
        "limit-up-drawdown-diagnostics-v1"
    )
    assert diagnostics["board_outcome_attribution"]["actionability"] == (
        "outcome_only_not_entry_filter"
    )
    assert diagnostics["recommendation_regime"]["time_validation"]["count"] == 2
    exit_research = diagnostics["exit_research"]
    assert "shadow_exit" not in diagnostics
    assert exit_research["formal_strategy_changed"] is False
    assert exit_research["withdrawn_policy"]["status"] == (
        "invalidated_same_price_decision_fill_lookahead"
    )
    assert exit_research["withdrawn_policy"]["published_metrics"] is None
    assert exit_research["precommitted_limit_research"]["account_performance"] is None
    assert exit_research["post_auction_research"]["account_performance"] is None
    assert report["position_sizing_audit"]["selected_max_positions"] == 2
    assert report["position_sizing_audit"]["selection_rule"] == (
        "pre_validation_maximum_return_with_drawdown_not_below_minus_10_pct"
    )
    assert report["position_sizing_audit"]["selection_cutoff_exclusive"] == "2026-04-14"
    assert report["position_sizing_audit"]["development_sample"]["signal_count"] == 1
    assert report["portfolio_policy"]["included_lanes"] == [
        "first_board",
        "two_to_three",
    ]
    assert report["portfolio_policy"]["excluded_lanes"] == ["high_board"]
    assert report["profitability_filter"]["minimum_d1_samples"] == 5
    assert report["profitability_filter"]["minimum_combined_rate"] == 30.0
    assert report["profitability_filter"]["audit"]["input_count"] == 3
    assert report["profitability_filter"]["audit"]["selected_count"] == 2
    assert report["profitability_filter"]["audit"]["reason_counts"] == {
        "not_first_board": 1,
        "qualified": 1,
        "same_stock_d1_samples_below_5": 1,
    }
    assert report["profitability_filter"]["selected_summary"] == report["summary"]
    assert report["profitability_filter"]["unfiltered_summary"]["signal_count"] == 3
    quality = report["recommendation_quality"]
    assert quality["mode"] == "independent_standard_slot_daily_equal_weight"
    assert quality["position_constraints_applied"] is False
    assert quality["standard_slot_cash"] == 50_000
    assert quality["summary"]["signal_count"] == 2
    assert quality["summary"]["trade_count"] == 2
    assert quality["summary"]["win_rate"] == 100.0
    assert quality["summary"]["average_return_pct"] is not None
    assert quality["summary"]["total_return_pct"] is not None
    assert quality["summary"]["max_drawdown_pct"] is not None
    assert report["signal_summary"] == quality["summary"]
    selected_quality = report["profitability_filter"][
        "selected_recommendation_quality"
    ]
    unfiltered_quality = report["profitability_filter"][
        "unfiltered_recommendation_quality"
    ]
    assert selected_quality["summary"]["signal_count"] == 2
    assert unfiltered_quality["summary"]["signal_count"] == 3
    quality_delta = report["profitability_filter"]["delta"]
    assert quality_delta["recommendation_win_rate_pct_points"] == pytest.approx(
        33.3333
    )
    assert quality_delta["recommendation_average_return_pct_points"] > 0
    assert report["relay_comparison"]["selected_variant"] == (
        "first_board_two_to_three"
    )
    assert report["relay_comparison"]["configured_variant"] == (
        "first_board_two_to_three"
    )
    assert report["relay_comparison"]["gate_selected_variant"] == (
        "first_board_two_to_three"
    )
    assert report["relay_comparison"]["configuration_matches_gate"] is True
    combined = report["relay_comparison"]["variants"][
        "first_board_two_to_three"
    ]
    assert combined["passed"] is True
    assert combined["summary"]["signal_count"] == 2
    assert "one_to_two_audit" not in report

    monkeypatch.setattr(
        history_service.scheduled_execution,
        "PRODUCT_EXECUTION_LANES",
        ("first_board",),
    )
    history_service._BACKTEST_REPORT_CACHE.clear()
    first_only = history_service.get_lane_history_backtest(
        date(2026, 6, 10),
        date(2026, 6, 10),
        lane="portfolio",
        exit_mode="next_close",
    )

    assert first_only["relay_comparison"]["configured_variant"] == "first_board"
    assert first_only["relay_comparison"]["gate_selected_variant"] == (
        "first_board_two_to_three"
    )
    assert first_only["relay_comparison"]["configuration_matches_gate"] is True

    monkeypatch.setattr(
        history_service.scheduled_execution,
        "PRODUCT_EXECUTION_LANES",
        ("first_board", "high_board"),
    )
    history_service._BACKTEST_REPORT_CACHE.clear()
    configured = history_service.get_lane_history_backtest(
        date(2026, 6, 10),
        date(2026, 6, 10),
        lane="portfolio",
        exit_mode="next_close",
    )

    assert configured["portfolio_policy"]["included_lanes"] == [
        "first_board",
        "high_board",
    ]
    assert configured["relay_comparison"]["selected_variant"] == (
        "first_board_high_board"
    )
    assert configured["relay_comparison"]["configured_variant"] == (
        "first_board_high_board"
    )
    assert configured["relay_comparison"]["configuration_matches_gate"] is False


def test_scheduled_backtest_reuses_full_report_across_trade_limits(monkeypatch) -> None:
    build_calls: list[tuple[date | None, date | None]] = []

    def fake_build(start, end, **_kwargs):
        build_calls.append((start, end))
        return {
            "orders": [{"id": value} for value in range(3)],
            "trades": [{"id": value} for value in range(3)],
            "skipped_orders": [{"id": value} for value in range(3)],
        }

    monkeypatch.setattr(history_service, "_build_scheduled_history_backtest", fake_build)
    history_service._BACKTEST_REPORT_CACHE.clear()

    latest = history_service.get_scheduled_history_backtest(None, None, trade_limit=1)
    expanded = history_service.get_scheduled_history_backtest(None, None, trade_limit=2)
    complete = history_service.get_scheduled_history_backtest(None, None, trade_limit=None)

    assert build_calls == [(None, None)]
    assert [row["id"] for row in latest["trades"]] == [2]
    assert [row["id"] for row in expanded["trades"]] == [1, 2]
    assert [row["id"] for row in complete["trades"]] == [0, 1, 2]
    assert [row["id"] for row in latest["orders"]] == [2]
    assert [row["id"] for row in latest["skipped_orders"]] == [2]
    history_service._BACKTEST_REPORT_CACHE.clear()


def test_scheduled_backtest_cache_avoids_recursive_copy(monkeypatch) -> None:
    class DeepCopyGuard:
        def __deepcopy__(self, _memo):
            raise AssertionError("large backtest report was recursively copied")

    guard = DeepCopyGuard()
    monkeypatch.setattr(
        history_service,
        "_build_scheduled_history_backtest",
        lambda _start, _end: {
            "orders": [],
            "trades": [],
            "skipped_orders": [],
            "diagnostics": {"guard": guard},
        },
    )
    history_service._BACKTEST_REPORT_CACHE.clear()

    first = history_service.get_scheduled_history_backtest(
        None,
        None,
        trade_limit=None,
    )
    second = history_service.get_scheduled_history_backtest(
        None,
        None,
        trade_limit=None,
    )

    assert first is not second
    assert first["diagnostics"]["guard"] is guard
    assert second["diagnostics"]["guard"] is guard
    history_service._BACKTEST_REPORT_CACHE.clear()


def test_scheduled_position_sizing_uses_only_pre_validation_orders(monkeypatch) -> None:
    orders = [
        {"entry_date": "2026-04-13", "vt_symbol": "600001.SSE"},
        {"entry_date": "2026-04-14", "vt_symbol": "600002.SSE"},
    ]

    def fake_simulate(selected, _bars, _trade_dates, _exit_mode, config):
        summaries = {
            1: (20.0, -12.0),
            2: (10.0, -6.0),
            3: (5.0, -3.0),
            4: (3.0, -2.0),
        }
        total_return, drawdown = summaries[config.max_positions]
        return {
            "execution_summary": {
                "signal_count": len(selected),
                "total_return_pct": total_return,
                "max_drawdown_pct": drawdown,
            }
        }

    monkeypatch.setattr(history_service, "_simulate_account", fake_simulate)

    audit = history_service._scheduled_position_sizing_audit(orders, [], [])

    assert audit["development_sample"]["signal_count"] == 1
    assert audit["validation_sample"]["signal_count"] == 1
    assert audit["development_variants"]["1"]["signal_count"] == 1
    assert audit["validation_variants"]["1"]["signal_count"] == 1
    assert audit["selected_by_development"] == 2
    assert audit["selection_matches_frozen_policy"] is True


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
    assert response.json()["data"]["exit_mode"] == "dynamic"


def test_history_backtest_api_accepts_shared_portfolio_scope(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_lane_history_backtest",
        lambda start, end, lane, exit_mode: {
            "status": "ready",
            "lane": lane,
            "exit_mode": "next_1430" if lane == "portfolio" else exit_mode,
            "account_config": {"initial_cash": 100_000, "max_positions": 2},
        },
    )

    response = TestClient(create_app()).get(
        "/api/limit-up/history/backtest",
        params={"lane": "portfolio"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["lane"] == "portfolio"
    assert response.json()["data"]["exit_mode"] == "next_1430"
    assert response.json()["data"]["account_config"]["initial_cash"] == 100_000
    assert response.json()["data"]["account_config"]["max_positions"] == 2


def test_dynamic_lane_backtest_coalesces_repeated_requests(monkeypatch) -> None:
    calls = 0
    day = _lane_replay_day()
    day["lane_portfolio"]["selected"][0]["dynamic_exit"] = {"mode": "tail_exit"}

    def load_history_range(*_args):
        nonlocal calls
        calls += 1
        return [day]

    history_service._BACKTEST_REPORT_CACHE.clear()
    monkeypatch.setattr(
        history_service.history_repository,
        "load_history_range",
        load_history_range,
    )
    monkeypatch.setattr(
        history_service.history_repository,
        "load_account_daily_bars",
        lambda *_args: [],
    )

    first = history_service.get_lane_history_backtest(
        None,
        None,
        lane="first_board",
        exit_mode="dynamic",
    )
    second = history_service.get_lane_history_backtest(
        None,
        None,
        lane="first_board",
        exit_mode="dynamic",
    )

    assert calls == 1
    assert first == second


def test_default_backtest_warmup_primes_portfolio_then_lane_validation(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        history_service,
        "BACKTEST_SCOPES",
        ("portfolio", "first_board", "high_board"),
    )
    monkeypatch.setattr(
        history_service,
        "get_lane_history_backtest",
        lambda *_args, lane, **_kwargs: calls.append(f"backtest:{lane}"),
    )
    monkeypatch.setattr(
        history_service,
        "get_lane_validation_snapshot",
        lambda exit_mode: calls.append(f"validation:{exit_mode}"),
    )
    monkeypatch.setattr(
        history_service,
        "get_sector_warmup_research",
        lambda *_args: calls.append("research:sector_warmup"),
    )

    history_service._warm_default_backtests()

    assert calls == [
        "backtest:portfolio",
        "validation:dynamic",
        "backtest:first_board",
        "backtest:high_board",
    ]
