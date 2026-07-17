from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.stock_main_rise_audit import (
    attach_signal_ma_zones,
    build_hold_baseline_metrics,
    build_signal_ma_zone_metrics,
    build_stock_main_rise_report,
    build_stock_main_rise_features,
    classify_hold_baseline,
    execute_stock_main_rise_hold,
    render_stock_main_rise_json,
)
from alphaagent.server.services.low_suction.cli import build_parser


def _calendar() -> tuple[date, ...]:
    return tuple(pd.date_range("2025-01-02", periods=35, freq="B").date)


def _candidate() -> pd.DataFrame:
    calendar = _calendar()
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "context_date": calendar[29],
                "entry_date": calendar[30],
                "planned_exit_date": calendar[31],
                "vt_symbol": "600001.SSE",
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "recognition_rank": 1,
                "main_rise": True,
                "ma5": 999.0,
                "ma10": 999.0,
            }
        ]
    )


def _daily_bars(*, sparse: bool = False) -> pd.DataFrame:
    rows = []
    for index, trade_date in enumerate(_calendar()):
        close_price = 10.0 + index * 0.1
        rows.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": close_price - 0.03,
                "high_price": close_price + 0.2,
                "low_price": close_price - 0.2,
                "close_price": close_price,
                "volume": 100_000.0,
            }
        )
    frame = pd.DataFrame(rows)
    if sparse:
        frame = frame.loc[frame["trade_date"].ne(_calendar()[20])].copy()
    return frame


def test_builds_exact_d1_stock_trend_features_and_nested_states() -> None:
    features = build_stock_main_rise_features(
        _candidate(),
        _daily_bars(),
        trading_dates=_calendar(),
    )
    row = features.iloc[0]
    context_position = 29
    closes = [10.0 + index * 0.1 for index in range(35)]

    assert row["stock_close"] == pytest.approx(closes[context_position])
    assert row["ma5"] == pytest.approx(
        sum(closes[context_position - 4 : context_position + 1]) / 5
    )
    assert row["ma10"] == pytest.approx(
        sum(closes[context_position - 9 : context_position + 1]) / 10
    )
    assert row["ma20"] == pytest.approx(
        sum(closes[context_position - 19 : context_position + 1]) / 20
    )
    assert row["distance_from_20d_high_pct"] == pytest.approx(0.0)
    assert bool(row["feature_complete"])
    assert bool(row["concept_main_rise"])
    assert bool(row["stock_above_ma5"])
    assert bool(row["stock_trend_order"])
    assert bool(row["stock_strong_main_rise"])
    assert int(row["stock_strong_main_rise"]) <= int(row["stock_trend_order"])
    assert int(row["stock_trend_order"]) <= int(row["stock_above_ma5"])


def test_future_mutation_cannot_change_d1_features() -> None:
    baseline = build_stock_main_rise_features(
        _candidate(),
        _daily_bars(),
        trading_dates=_calendar(),
    )
    changed_bars = _daily_bars()
    changed_bars.loc[
        changed_bars["trade_date"].gt(_calendar()[29]),
        ["open_price", "high_price", "low_price", "close_price", "volume"],
    ] = [1.0, 99.0, 0.5, 1.0, 999_999.0]
    changed = build_stock_main_rise_features(
        _candidate(),
        changed_bars,
        trading_dates=_calendar(),
    )
    columns = [
        "stock_close",
        "ma5",
        "ma10",
        "ma20",
        "ma5_shift_3",
        "ma10_shift_3",
        "ma20_shift_3",
        "return_10d_pct",
        "distance_from_20d_high_pct",
        "stock_strong_main_rise",
    ]

    pd.testing.assert_frame_equal(baseline[columns], changed[columns])


def test_missing_calendar_session_fails_closed_as_incomplete() -> None:
    features = build_stock_main_rise_features(
        _candidate(),
        _daily_bars(sparse=True),
        trading_dates=_calendar(),
    )
    row = features.iloc[0]

    assert not bool(row["feature_complete"])
    assert row["feature_status"] == "incomplete_d1_history"
    assert not bool(row["stock_above_ma5"])
    assert not bool(row["stock_trend_order"])
    assert not bool(row["stock_strong_main_rise"])


def test_duplicate_daily_identity_is_rejected() -> None:
    bars = pd.concat([_daily_bars(), _daily_bars().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="daily bar identities"):
        build_stock_main_rise_features(
            _candidate(),
            bars,
            trading_dates=_calendar(),
        )


def test_outcome_or_future_columns_are_rejected_from_features() -> None:
    with pytest.raises(ValueError, match="future or outcome"):
        build_stock_main_rise_features(
            _candidate().assign(net_return_pct=8.0),
            _daily_bars(),
            trading_dates=_calendar(),
        )


def test_hold_baseline_buys_d_open_and_sells_d1_close_with_costs() -> None:
    features = build_stock_main_rise_features(
        _candidate(),
        _daily_bars(),
        trading_dates=_calendar(),
    )
    normal, stressed = execute_stock_main_rise_hold(
        features,
        _daily_bars(),
        trading_dates=_calendar(),
    )
    row = normal.iloc[0]

    assert row["entry_date"] == pd.Timestamp(_calendar()[30])
    assert row["exit_date"] == pd.Timestamp(_calendar()[31])
    assert row["entry_price_raw"] == pytest.approx(
        _daily_bars().loc[_daily_bars()["trade_date"].eq(_calendar()[30]), "open_price"].item()
    )
    assert row["exit_price_raw"] == pytest.approx(
        _daily_bars().loc[_daily_bars()["trade_date"].eq(_calendar()[31]), "close_price"].item()
    )
    assert row["status"] == "closed"
    assert stressed.iloc[0]["net_return_pct"] < row["net_return_pct"]


def test_hold_baseline_rejects_limit_up_entry() -> None:
    features = build_stock_main_rise_features(
        _candidate(),
        _daily_bars(),
        trading_dates=_calendar(),
    )
    bars = _daily_bars()
    previous_close = bars.loc[
        bars["trade_date"].eq(_calendar()[29]), "close_price"
    ].item()
    bars.loc[bars["trade_date"].eq(_calendar()[30]), "open_price"] = (
        previous_close * 1.10
    )

    normal, _ = execute_stock_main_rise_hold(
        features,
        bars,
        trading_dates=_calendar(),
    )

    assert normal.iloc[0]["status"] == "rejected"
    assert normal.iloc[0]["reason"] == "entry_at_limit_up"


def _baseline_metric(**overrides: object) -> dict[str, object]:
    metric: dict[str, object] = {
        "closed_trades": 30,
        "source_days": 20,
        "win_rate_pct": 61.0,
        "mean_net_return_pct": 1.0,
        "profit_factor": 1.5,
        "double_cost_mean_net_return_pct": 0.5,
    }
    metric.update(overrides)
    return metric


def test_hold_baseline_labels_use_strict_sample_and_win_boundaries() -> None:
    assert classify_hold_baseline(_baseline_metric()) == "high_win_baseline"
    assert (
        classify_hold_baseline(_baseline_metric(win_rate_pct=60.0))
        == "positive_baseline"
    )
    assert (
        classify_hold_baseline(_baseline_metric(win_rate_pct=50.0))
        == "not_positive_baseline"
    )
    assert (
        classify_hold_baseline(_baseline_metric(closed_trades=29))
        == "insufficient_sample"
    )


def test_hold_metrics_keep_definitions_identical_across_time_segments() -> None:
    dates = tuple(pd.date_range("2025-02-03", periods=60, freq="B"))
    features = pd.DataFrame(
        {
            "event_id": range(60),
            "entry_date": dates,
            "block": [1] * 30 + [4] * 30,
            **{definition: [True] * 60 for definition in (
                "concept_main_rise",
                "stock_above_ma5",
                "stock_trend_order",
                "stock_strong_main_rise",
            )},
        }
    )
    returns = [1.0] * 20 + [-0.5] * 10
    normal = pd.DataFrame(
        {
            "event_id": [str(index) for index in range(60)],
            "status": ["closed"] * 60,
            "net_return_pct": returns * 2,
        }
    )
    stressed = normal.assign(
        net_return_pct=[value - 0.2 for value in normal["net_return_pct"]]
    )

    metrics = build_hold_baseline_metrics(features, normal, stressed)
    strongest = metrics.loc[
        metrics["definition"].eq("stock_strong_main_rise")
        & metrics["segment"].isin(("development", "validation"))
    ]

    assert set(strongest["segment"]) == {"development", "validation"}
    assert strongest["baseline_label"].eq("high_win_baseline").all()
    assert strongest["stable_positive_baseline"].all()


def _zone_features() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": index,
                "ma5": 10.0,
                "ma10": 9.0,
                "ma20": 8.0,
                "concept_main_rise": True,
                "stock_above_ma5": index == 1,
                "stock_trend_order": index in (1, 2),
                "stock_strong_main_rise": index == 1,
            }
            for index in range(1, 5)
        ]
        + [
            {
                "event_id": 5,
                "ma5": 8.0,
                "ma10": 9.0,
                "ma20": 10.0,
                "concept_main_rise": True,
                "stock_above_ma5": False,
                "stock_trend_order": False,
                "stock_strong_main_rise": False,
            }
        ]
    )


def _zone_trades() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": range(1, 6),
            "entry_date": pd.date_range("2025-04-01", periods=5, freq="B"),
            "block": [1, 1, 4, 4, 4],
            "close_price": [10.0, 9.0, 8.0, 7.99, 9.5],
            "normal_status": ["closed"] * 5,
            "stressed_status": ["closed"] * 5,
            "net_return_pct": [1.0, 0.5, -0.5, -1.0, 0.2],
            "double_cost_net_return_pct": [0.7, 0.2, -0.8, -1.3, -0.1],
        }
    )


def test_signal_ma_zone_boundaries_and_unordered_guard_are_exact() -> None:
    attributed = attach_signal_ma_zones(_zone_trades(), _zone_features())

    assert attributed["signal_ma_zone"].tolist() == [
        "above_ma5",
        "ma5_to_ma10",
        "ma10_to_ma20",
        "below_ma20",
        "unordered_mas",
    ]
    assert attributed["signal_above_ma5"].tolist() == [True, False, False, False, True]
    assert attributed["signal_above_ma10"].tolist() == [True, True, False, False, True]
    assert attributed["signal_above_ma20"].tolist() == [True, True, True, False, False]


def test_signal_ma_zone_metrics_keep_all_zones_and_stock_definitions() -> None:
    attributed = attach_signal_ma_zones(_zone_trades(), _zone_features())
    metrics = build_signal_ma_zone_metrics(attributed)

    zone_rows = metrics.loc[
        metrics["table_id"].eq("signal_ma_zone")
        & metrics["segment"].eq("all")
    ]
    definition_rows = metrics.loc[
        metrics["table_id"].eq("d1_stock_definition")
        & metrics["segment"].eq("all")
    ]

    assert set(zone_rows["cohort_key"]) == {
        "above_ma5",
        "ma5_to_ma10",
        "ma10_to_ma20",
        "below_ma20",
        "unordered_mas",
    }
    assert set(definition_rows["cohort_key"]) == {
        "concept_main_rise",
        "stock_above_ma5",
        "stock_trend_order",
        "stock_strong_main_rise",
    }


def test_report_is_bounded_and_selects_no_formal_definition() -> None:
    dates = tuple(pd.date_range("2025-02-03", periods=60, freq="B"))
    features = pd.DataFrame(
        {
            "event_id": range(60),
            "entry_date": dates,
            "feature_complete": [True] * 60,
            "block": [1] * 30 + [4] * 30,
            **{definition: [True] * 60 for definition in (
                "concept_main_rise",
                "stock_above_ma5",
                "stock_trend_order",
                "stock_strong_main_rise",
            )},
        }
    )
    returns = [1.0] * 20 + [-0.5] * 10
    normal = pd.DataFrame(
        {
            "event_id": [str(index) for index in range(60)],
            "status": ["closed"] * 60,
            "net_return_pct": returns * 2,
        }
    )
    stressed = normal.assign(
        net_return_pct=[value - 0.2 for value in normal["net_return_pct"]]
    )
    hold_metrics = build_hold_baseline_metrics(features, normal, stressed)
    attributed = attach_signal_ma_zones(_zone_trades(), _zone_features())
    zone_metrics = build_signal_ma_zone_metrics(attributed)

    report = build_stock_main_rise_report(
        features,
        hold_metrics,
        attributed,
        zone_metrics,
        {
            "coverage": {"candidate_count": 60, "entry_signals": 5},
            "input_fingerprints": {"sample": {"sha256": "abc"}},
        },
    )
    rendered = render_stock_main_rise_json(report)

    assert report["overall_conclusion"] == "stock_main_rise_baseline_confirmed"
    assert report["formal_metrics"] is None
    assert report["selected_stock_main_rise_definition"] is None
    assert report["holdout_price_values_read"] is False
    assert report["current_membership_rows_read"] == 0
    assert report["limit_up_strategy_rows_read"] == 0
    assert '"formal_metrics": null' in rendered
    assert "NaN" not in rendered


def test_stock_main_rise_cli_exposes_no_research_knobs() -> None:
    args = build_parser().parse_args(
        ["v2-stock-main-rise-audit", "--format", "json"]
    )

    assert args.command == "v2-stock-main-rise-audit"
    for parameter in (
        "start",
        "end",
        "ma_periods",
        "slope_sessions",
        "high_distance_pct",
        "entry_rule",
        "exit_rule",
    ):
        assert not hasattr(args, parameter)
