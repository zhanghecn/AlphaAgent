from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.ma5_case_attribution_study import (
    PRE_ENTRY_FEATURE_COLUMNS,
    attach_ma5_outcome_attribution,
    build_ma5_case_attribution_report,
    build_pre_entry_ma5_features,
    render_ma5_case_attribution_json,
    render_ma5_case_attribution_markdown,
    select_ma5_attribution_cohort,
)


def _trade_rows() -> pd.DataFrame:
    base = {
        "episode_id": "episode-1",
        "vt_symbol": "600001.SSE",
        "stock_name": "甲股",
        "sector_id": "BK0001",
        "concept_name": "甲概念",
        "time_block": "block_4",
        "causal_rank": 1,
        "signal_mode": "stabilized_reclaim",
        "primary_eligible": True,
        "support_line": "ma5",
        "wave_number": 3,
        "wave_start_date": "2026-01-20",
        "reference_peak_date": "2026-01-27",
        "reference_peak_price": 13.0,
        "pullback_confirmation_date": "2026-01-29",
        "signal_date": "2026-01-30",
        "entry_date": "2026-02-02",
        "exit_date": "2026-02-06",
        "entry_price": 11.5,
        "exit_price": 13.2,
        "signal_daily_return_pct": 2.0,
        "signal_close_to_peak_pct": -7.0,
        "pullback_confirmation_low_to_peak_pct": -9.0,
        "line_distance_close_pct": 1.5,
        "volume_ratio_prior5": 0.75,
        "volume_ratio_impulse": 0.85,
        "volume_class_prior5": "contraction",
        "impulse_gain_pct": 25.0,
        "strong_days_ge_9_5pct": 1,
        "executable_exit_reason": "higher_high_confirmed",
        "eventually_made_higher_high": True,
        "defensive_exit_preceded_later_higher_high": False,
        "holding_sessions": 5,
        "maximum_adverse_excursion_pct": -2.0,
        "maximum_favorable_excursion_pct": 8.0,
        "net_return_pct": 4.0,
    }
    second = {
        **base,
        "episode_id": "episode-2",
        "vt_symbol": "600002.SSE",
        "stock_name": "乙股",
        "sector_id": "BK0002",
        "concept_name": "乙概念",
        "time_block": "block_5",
        "signal_id": "signal-2",
        "net_return_pct": -6.0,
        "exit_price": 10.8,
        "executable_exit_reason": "two_closes_below_ma20",
        "eventually_made_higher_high": False,
        "maximum_adverse_excursion_pct": -8.0,
        "maximum_favorable_excursion_pct": 1.0,
    }
    excluded = {
        **base,
        "episode_id": "episode-3",
        "signal_id": "signal-3",
        "support_line": "ma10",
    }
    base["signal_id"] = "signal-1"
    return pd.DataFrame([base, second, excluded])


def _bars() -> tuple[pd.DataFrame, pd.DataFrame]:
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=index) for index in range(40)]
    stock_rows = []
    concept_rows = []
    for symbol, offset in (
        ("600001.SSE", 0.0),
        ("600002.SSE", -0.5),
        ("600003.SSE", 0.25),
        ("600004.SSE", -0.25),
    ):
        for index, trade_date in enumerate(dates):
            close = 9.0 + offset + index * 0.1
            stock_rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close - 0.05,
                    "high_price": close + 0.2,
                    "low_price": close - 0.2,
                    "close_price": close,
                    "volume": 1_000 + index * 10,
                }
            )
    for sector_id, direction in (("BK0001", 1.0), ("BK0002", -1.0)):
        for index, trade_date in enumerate(dates):
            base = 100.0 + index * 0.5
            if trade_date > date(2026, 1, 30):
                base += direction * (trade_date - date(2026, 1, 30)).days
            concept_rows.append(
                {
                    "sector_id": sector_id,
                    "trade_date": trade_date,
                    "open_price": base - 0.2,
                    "high_price": base + 0.5,
                    "low_price": base - 0.5,
                    "close_price": base,
                    "volume": 10_000 + index * 100,
                    "turnover": 1_000_000 + index * 10_000,
                }
            )
    return pd.DataFrame(stock_rows), pd.DataFrame(concept_rows)


def _memberships() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"sector_id": "BK0001", "vt_symbol": "600001.SSE"},
            {"sector_id": "BK0001", "vt_symbol": "600003.SSE"},
            {"sector_id": "BK0002", "vt_symbol": "600002.SSE"},
            {"sector_id": "BK0002", "vt_symbol": "600004.SSE"},
        ]
    )


def _timing() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": date(2026, 1, 30),
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "market_phase": "markup",
            }
        ]
    )


def test_select_ma5_cohort_keeps_only_closed_primary_stabilized_ma5() -> None:
    cohort = select_ma5_attribution_cohort(_trade_rows())

    assert cohort["signal_id"].tolist() == ["signal-1", "signal-2"]


def test_pre_entry_features_do_not_change_when_outcomes_are_mutated() -> None:
    cohort = select_ma5_attribution_cohort(_trade_rows())
    stock_bars, concept_bars = _bars()
    original = build_pre_entry_ma5_features(
        cohort,
        stock_bars,
        concept_bars,
        _memberships(),
        _timing(),
    )
    mutated = cohort.copy()
    mutated["net_return_pct"] = [-99.0, 99.0]
    mutated["exit_date"] = ["2027-01-01", "2027-01-02"]
    mutated["maximum_adverse_excursion_pct"] = [0.0, -100.0]
    mutated["maximum_favorable_excursion_pct"] = [100.0, 0.0]

    changed = build_pre_entry_ma5_features(
        mutated,
        stock_bars,
        concept_bars,
        _memberships(),
        _timing(),
    )

    pd.testing.assert_frame_equal(
        original.loc[:, list(PRE_ENTRY_FEATURE_COLUMNS)],
        changed.loc[:, list(PRE_ENTRY_FEATURE_COLUMNS)],
    )
    assert original["proxy_member_count"].eq(2).all()
    assert original["active_direction"].eq("GOLD").all()


def test_outcome_attribution_is_attached_after_pre_entry_features() -> None:
    cohort = select_ma5_attribution_cohort(_trade_rows())
    stock_bars, concept_bars = _bars()
    features = build_pre_entry_ma5_features(
        cohort,
        stock_bars,
        concept_bars,
        _memberships(),
        _timing(),
    )
    concept_states = pd.DataFrame(
        [
            {
                "sector_id": "BK0001",
                "trade_date": date(2026, 2, 2),
                "definition": "breakout_trend",
                "in_cycle": True,
                "sustain_qualifies": True,
            },
            {
                "sector_id": "BK0002",
                "trade_date": date(2026, 2, 2),
                "definition": "breakout_trend",
                "in_cycle": False,
                "sustain_qualifies": False,
            },
        ]
    )

    ledger = attach_ma5_outcome_attribution(
        features,
        cohort,
        concept_bars,
        concept_states,
    )

    winner = ledger.loc[ledger["signal_id"].eq("signal-1")].iloc[0]
    loser = ledger.loc[ledger["signal_id"].eq("signal-2")].iloc[0]
    assert winner["outcome_group"] == "winner"
    assert winner["failure_mechanism"] == "higher_high_rebreak_winner"
    assert winner["concept_post_5d_return_pct"] > 0
    assert loser["outcome_group"] == "loser"
    assert loser["failure_mechanism"] == "concept_and_stock_wave_ended"
    assert loser["concept_post_5d_return_pct"] < 0


def test_report_keeps_formal_metrics_null_and_renders_all_cases() -> None:
    cohort = select_ma5_attribution_cohort(_trade_rows())
    stock_bars, concept_bars = _bars()
    features = build_pre_entry_ma5_features(
        cohort,
        stock_bars,
        concept_bars,
        _memberships(),
        _timing(),
    )
    ledger = attach_ma5_outcome_attribution(
        features,
        cohort,
        concept_bars,
        pd.DataFrame(),
    )

    report = build_ma5_case_attribution_report(
        ledger,
        parent_sha256="sha256:parent",
    )

    assert report["formal_metrics"]["win_rate_pct"] is None
    assert report["coverage"]["individual_case_rows"] == 2
    assert len(report["individual_case_ledger"]) == 2
    markdown = render_ma5_case_attribution_markdown(report)
    assert "逐票" in markdown
    assert "all five historical blocks were already viewed" in markdown
    assert json.loads(render_ma5_case_attribution_json(report))["study_version"]


def test_cli_accepts_ma5_case_attribution_command() -> None:
    args = build_parser().parse_args(
        ["v2-ma5-case-attribution-study", "--format", "markdown"]
    )

    assert args.command == "v2-ma5-case-attribution-study"
    assert args.format == "markdown"
