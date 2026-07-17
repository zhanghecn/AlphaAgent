from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.outcome_group_study import (
    build_outcome_cohort_metrics,
    build_outcome_group_signals,
    build_outcome_group_report,
    build_winner_loser_profiles,
    classify_development_cohort,
    classify_volume_ratio,
    label_outcome_group_trades,
    render_outcome_group_json,
)
from alphaagent.server.services.low_suction.cli import build_parser


def _candidate() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "recognition_event_id": 11,
                "leader_spell_id": "BK0963:cycle-1:600001.SSE",
                "recognition_source_date": date(2025, 6, 30),
                "context_date": date(2025, 7, 1),
                "source_date": date(2025, 7, 2),
                "entry_date": date(2025, 7, 2),
                "planned_exit_date": date(2025, 7, 3),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股份",
                "recognition_rank": 1,
                "cycle_relative_percentile": 0.9,
                "spell_session_offset": 2,
                "signal_close": 10.0,
                "previous_high": 10.5,
                "ma5": 9.8,
                "ma10": 9.5,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "market_phase": "recovery",
                "main_rise": True,
                "is_top3": True,
                "rank_mode": "event_recognition_proxy",
                "evidence_level": "event_recognition_neutral_day_falsification",
            }
        ]
    )


def _minute_bars(*, no_pullback: bool = False, future_close: float | None = None) -> pd.DataFrame:
    morning = [
        datetime(2025, 7, 2, 9, 35) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    afternoon = [
        datetime(2025, 7, 2, 13, 5) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    times = [*morning, *afternoon]
    closes = [10.20, 10.10, 10.05, 10.00, 9.90, *([9.95] * 43)]
    if no_pullback:
        closes = [10.20] * 48
    if future_close is not None:
        closes[5:] = [future_close] * 43
    opens = [10.20, *closes[:-1]]
    opens[4] = 9.95
    volumes = [100.0, 200.0, 300.0, 600.0, *([250.0] * 44)]
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 7, 2),
                "bar_time": bar_time,
                "interval": "5m",
                "open_price": open_price,
                "high_price": max(open_price, close_price) + 0.02,
                "low_price": min(open_price, close_price) - 0.02,
                "close_price": close_price,
                "volume": volume,
                "turnover": close_price * volume,
                "source": "tdx_public_hq",
            }
            for bar_time, open_price, close_price, volume in zip(
                times,
                opens,
                closes,
                volumes,
                strict=True,
            )
        ]
    )


def _daily_bars() -> pd.DataFrame:
    dates = tuple(pd.date_range("2025-06-23", "2025-07-03", freq="B").date)
    volumes = [100.0] * len(dates)
    volumes[dates.index(date(2025, 7, 1))] = 250.0
    rows = []
    for trade_date, volume in zip(dates, volumes, strict=True):
        close = 10.5 if trade_date == date(2025, 7, 3) else 10.0
        rows.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": close,
                "high_price": close + 0.2,
                "low_price": close - 0.2,
                "close_price": close,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (0.7999, "contraction"),
        (0.8, "normal"),
        (1.4999, "normal"),
        (1.5, "expansion"),
        (2.4999, "expansion"),
        (2.5, "explosion"),
    ],
)
def test_volume_class_boundaries_are_frozen(ratio: float, expected: str) -> None:
    assert classify_volume_ratio(ratio) == expected


def test_selects_first_pullback_and_attaches_only_pre_entry_volume() -> None:
    signals = build_outcome_group_signals(
        _candidate(),
        _minute_bars(),
        _daily_bars(),
    )
    row = signals.iloc[0]

    assert len(signals) == 1
    assert signals.groupby("event_id").size().max() == 1
    assert row["observed_at"] == datetime(2025, 7, 2, 9, 50)
    assert row["entry_time"] == datetime(2025, 7, 2, 9, 55)
    assert row["entry_price_raw"] == pytest.approx(9.95)
    assert row["intraday_volume_ratio"] == pytest.approx(3.0)
    assert row["intraday_volume_class"] == "explosion"
    assert row["daily_volume_ratio"] == pytest.approx(2.5)
    assert row["daily_volume_class"] == "explosion"
    assert row["leader_rank_group"] == "rank_1"
    assert row["main_rise_group"] == "main_rise"
    assert row["market_regime"] == "GOLD/NORMAL"


def test_no_trade_when_price_never_reaches_previous_close() -> None:
    signals = build_outcome_group_signals(
        _candidate(),
        _minute_bars(no_pullback=True),
        _daily_bars(),
    )

    assert signals.empty


def test_future_bars_do_not_change_selected_signal_or_features() -> None:
    baseline = build_outcome_group_signals(
        _candidate(),
        _minute_bars(),
        _daily_bars(),
    )
    changed = build_outcome_group_signals(
        _candidate(),
        _minute_bars(future_close=30.0),
        _daily_bars(),
    )
    columns = [
        "observation_id",
        "observed_at",
        "entry_time",
        "entry_price_raw",
        "intraday_volume_ratio",
        "daily_volume_ratio",
    ]

    pd.testing.assert_frame_equal(baseline[columns], changed[columns])


def test_outcome_columns_are_rejected_before_signal_construction() -> None:
    with pytest.raises(ValueError, match="future or outcome"):
        build_outcome_group_signals(
            _candidate().assign(net_return_pct=9.0),
            _minute_bars(),
            _daily_bars(),
        )


def test_selected_signal_uses_existing_d1_cash_execution() -> None:
    signals = build_outcome_group_signals(
        _candidate(),
        _minute_bars(),
        _daily_bars(),
    )
    trades = label_outcome_group_trades(
        signals,
        _daily_bars(),
        trading_dates=tuple(pd.date_range("2025-06-23", "2025-07-03", freq="B").date),
    )
    row = trades.iloc[0]

    assert row["normal_status"] == "closed"
    assert row["exit_price_raw"] == pytest.approx(10.5)
    assert row["net_return_pct"] > 0
    assert row["outcome_group"] == "winner"
    assert row["double_cost_net_return_pct"] < row["net_return_pct"]


def _metric(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "closed_trades": 30,
        "source_days": 20,
        "win_rate_pct": 61.0,
        "mean_net_return_pct": 1.0,
        "profit_factor": 1.2,
        "double_cost_mean_net_return_pct": 0.5,
    }
    values.update(overrides)
    return values


def test_development_high_and_low_gates_are_strict() -> None:
    assert classify_development_cohort(_metric()) == "high_candidate"
    assert (
        classify_development_cohort(_metric(win_rate_pct=60.0)) == "neutral"
    )
    assert (
        classify_development_cohort(
            _metric(
                win_rate_pct=44.0,
                mean_net_return_pct=-1.0,
                profit_factor=0.8,
                double_cost_mean_net_return_pct=-1.3,
            )
        )
        == "low_candidate"
    )
    assert (
        classify_development_cohort(_metric(closed_trades=29)) == "neutral"
    )


def _synthetic_trades() -> pd.DataFrame:
    rows = []
    for index in range(180):
        development = index < 90
        winning = index % 3 != 0
        rows.append(
            {
                "observation_id": str(index),
                "entry_date": date(2025, 1, 1) + timedelta(days=index),
                "block": 1 if development else 4,
                "normal_status": "closed",
                "stressed_status": "closed",
                "net_return_pct": 1.0 if winning else -0.5,
                "double_cost_net_return_pct": 0.7 if winning else -0.8,
                "outcome_group": "winner" if winning else "loser",
                "daily_volume_ratio": 0.7 if winning else 2.6,
                "daily_volume_class": "contraction" if winning else "explosion",
                "intraday_volume_ratio": 0.7 if winning else 2.6,
                "intraday_volume_class": "contraction" if winning else "explosion",
                "recognition_rank": 1 if winning else 2,
                "leader_rank_group": "rank_1" if winning else "rank_2_3",
                "main_rise": winning,
                "main_rise_group": "main_rise" if winning else "non_main_rise",
                "active_direction": "GOLD" if winning else "SILVER",
                "danger_state": "NORMAL",
                "market_regime": "GOLD/NORMAL" if winning else "SILVER/NORMAL",
                "spell_session_offset": 1,
                "signal_minutes_from_open": 20,
                "distance_to_previous_close_pct": -1.0,
            }
        )
    return pd.DataFrame(rows)


def test_cohorts_keep_same_identity_across_development_and_validation() -> None:
    metrics = build_outcome_cohort_metrics(_synthetic_trades())
    contraction = metrics.loc[
        metrics["table_id"].eq("daily_volume")
        & metrics["cohort_key"].eq("daily_volume_class=contraction")
    ]

    assert set(contraction["segment"]) == {"development", "validation"}
    assert contraction["development_class"].eq("high_candidate").all()
    assert contraction["validation_status"].eq("high_confirmed").all()


def test_winner_loser_profiles_are_descriptive_not_signal_fields() -> None:
    profiles = build_winner_loser_profiles(_synthetic_trades())

    assert set(profiles["outcome_group"]) == {"winner", "loser"}
    winners = profiles.loc[profiles["outcome_group"].eq("winner")].iloc[0]
    losers = profiles.loc[profiles["outcome_group"].eq("loser")].iloc[0]
    assert winners["median_daily_volume_ratio"] < losers["median_daily_volume_ratio"]
    assert winners["rank_1_share_pct"] > losers["rank_1_share_pct"]


def test_report_retains_all_cohorts_and_never_exposes_formal_metrics() -> None:
    report = build_outcome_group_report(
        _candidate(),
        _synthetic_trades().iloc[:1],
        _synthetic_trades(),
        {
            "coverage": {
                "comparison_candidates": 180,
                "main_rise_candidates": 120,
                "non_main_rise_candidates": 60,
                "entry_signals": 180,
                "no_pullback_signal": 0,
            },
            "input_fingerprints": {"sample": {"sha256": "abc"}},
        },
    )
    rendered = render_outcome_group_json(report)

    assert report["overall_conclusion"] == "confirmed_high_and_low_cohorts"
    assert report["formal_metrics"] is None
    assert report["formal_rule_selected"] is False
    assert report["holdout_price_values_read"] is False
    assert report["current_membership_rows_read"] == 0
    assert report["limit_up_strategy_rows_read"] == 0
    assert report["confirmed_high_cohorts"]
    assert report["confirmed_low_cohorts"]
    assert '"formal_metrics": null' in rendered
    assert "NaN" not in rendered


def test_study_cli_has_no_threshold_date_or_entry_parameters() -> None:
    args = build_parser().parse_args(
        ["v2-outcome-group-study", "--format", "json"]
    )

    assert args.command == "v2-outcome-group-study"
    for parameter in (
        "start",
        "end",
        "entry_depth",
        "high_win_rate",
        "volume_thresholds",
    ):
        assert not hasattr(args, parameter)
