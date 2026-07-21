from __future__ import annotations

import inspect

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.main_rise_structural_exit_study import (
    build_reference_cases,
    build_structural_cash_inputs,
    build_structural_exit_report,
    build_structural_exit_trades,
    choose_structural_rule,
    evaluate_structural_rule_grid,
    final_structural_gates,
    prepare_concept_exit_features,
    prepare_stock_exit_features,
    render_main_rise_structural_exit_markdown,
)
from alphaagent.server.services.low_suction.main_rise_weak_to_strong_study import (
    SIGNAL_FEATURE_COLUMNS,
    WeakToStrongRule,
)


SIGNAL_DATE = pd.Timestamp("2026-01-05")


def test_stock_and_concept_features_are_causal_daily_rolls() -> None:
    stock = prepare_stock_exit_features(_stock_bars(mode="target"))
    concept = prepare_concept_exit_features(_concept_bars())

    signal_stock = stock.loc[stock["trade_date"].eq(SIGNAL_DATE)].iloc[0]
    signal_concept = concept.loc[concept["trade_date"].eq(SIGNAL_DATE)].iloc[0]

    assert signal_stock["ma20"] == pytest.approx(10.0)
    assert bool(signal_concept["concept_structure_intact"])


def test_structural_exit_prefers_earlier_higher_high() -> None:
    trade = build_structural_exit_trades(
        _signals(),
        _stock_bars(mode="target"),
        _concept_bars(),
    ).iloc[0]

    assert trade["exit_reason"] == "higher_high_confirmed"
    assert trade["exit_date"] == pd.Timestamp("2026-01-08")
    assert trade["entry_reference_high"] == pytest.approx(10.5)
    assert trade["net_return_pct"] == pytest.approx(5.8)


def test_two_consecutive_closes_below_ma20_trigger_stock_defense() -> None:
    trade = build_structural_exit_trades(
        _signals(),
        _stock_bars(mode="stock_break"),
        _concept_bars(),
    ).iloc[0]

    assert trade["exit_reason"] == "two_closes_below_ma20"
    assert trade["exit_date"] == pd.Timestamp("2026-01-07")
    assert trade["net_return_pct"] == pytest.approx(-12.2)


def test_concept_break_defers_to_next_available_stock_close() -> None:
    trade = build_structural_exit_trades(
        _signals(),
        _stock_bars(mode="concept_break_suspension"),
        _concept_bars(break_date="2026-01-06"),
    ).iloc[0]

    assert trade["concept_break_date"] == pd.Timestamp("2026-01-06")
    assert trade["exit_reason"] == "concept_structure_broken"
    assert trade["exit_date"] == pd.Timestamp("2026-01-07")


def test_same_day_higher_high_has_attribution_precedence() -> None:
    trade = build_structural_exit_trades(
        _signals(),
        _stock_bars(mode="same_day_target"),
        _concept_bars(break_date="2026-01-06"),
    ).iloc[0]

    assert trade["higher_high_date"] == pd.Timestamp("2026-01-06")
    assert trade["concept_break_date"] == pd.Timestamp("2026-01-06")
    assert trade["exit_reason"] == "higher_high_confirmed"


def test_no_structural_exit_remains_right_censored_without_fallback() -> None:
    trade = build_structural_exit_trades(
        _signals(),
        _stock_bars(mode="censored"),
        _concept_bars(),
    ).iloc[0]

    assert trade["exit_reason"] == "right_censored"
    assert pd.isna(trade["exit_date"])
    assert pd.isna(trade["net_return_pct"])


def test_structural_grid_has_no_outcome_or_d1_input() -> None:
    parameters = inspect.signature(evaluate_structural_rule_grid).parameters

    assert "outcomes" not in parameters
    assert all("d1" not in name for name in parameters)


def test_structural_grid_never_reports_block5_during_nomination() -> None:
    features = pd.DataFrame(
        [_signal_feature(SIGNAL_DATE + pd.offsets.BDay(index), index + 1)
         for index in range(5)]
    )
    stock = _multi_signal_stock_bars(features)
    concept = _concept_bars(end="2026-01-20")

    grid, trades_by_rule = evaluate_structural_rule_grid(
        features,
        stock,
        concept,
        rules=(_rule(),),
    )

    assert len(grid) == 1
    assert not any("block5" in column.lower() for column in grid.columns)
    assert set(trades_by_rule) == {"test-structural-rule"}
    validation_trade = trades_by_rule["test-structural-rule"].loc[
        lambda frame: frame["block"].eq(4)
    ].iloc[0]
    assert validation_trade["exit_reason"] == "split_boundary_censored"
    assert pd.isna(validation_trade["exit_date"])


def test_choose_structural_rule_uses_only_qualified_rows() -> None:
    grid = pd.DataFrame(
        [
            _grid_row("rejected", qualified=False, validation_rate=90.0),
            _grid_row("qualified-b", qualified=True, validation_rate=61.0),
            _grid_row("qualified-a", qualified=True, validation_rate=62.0),
        ]
    )

    selected = choose_structural_rule(grid)

    assert selected is not None
    assert selected.version == "qualified-a"


def test_cash_inputs_use_signal_close_and_only_closed_trades() -> None:
    closed = build_structural_exit_trades(
        _signals(),
        _stock_bars(mode="target"),
        _concept_bars(),
    )
    censored = build_structural_exit_trades(
        _signals(signal_id="censored"),
        _stock_bars(mode="censored"),
        _concept_bars(),
    )

    combined = pd.DataFrame.from_records(
        [closed.iloc[0].to_dict(), censored.iloc[0].to_dict()]
    )
    cash = build_structural_cash_inputs(combined)

    assert cash["signal_id"].tolist() == ["signal-1"]
    assert cash["entry_price_raw_override"].tolist() == [10.0]
    assert cash["exit_price_mode"].tolist() == ["close"]
    assert cash["causal_rank"].tolist() == [1]


def test_final_gates_report_cash_and_holdout_failure_exactly() -> None:
    metrics = pd.DataFrame(
        [
            _metric("all", 120, 61.0, 1.0, 1.3),
            _metric("block_1", 20, 61.0, 1.0, 1.3),
            _metric("block_2", 20, 61.0, 1.0, 1.3),
            _metric("block_3", 20, 61.0, 1.0, 1.3),
            _metric("block_4", 35, 61.0, 1.0, 1.3),
            _metric("block_5", 25, 61.0, 1.0, 1.3),
        ]
    )
    cash = _cash_result(closed=59, win=61.0, compound=61.0, drawdown=-10.0)

    qualified, failures = final_structural_gates(metrics, cash)

    assert not qualified
    assert failures == ["block5_closed_trades_below_30", "cash_closed_trades_below_60"]


def test_report_and_cli_keep_reused_history_non_production() -> None:
    report = build_structural_exit_report(
        coverage={
            "feature_start": "2024-07-16",
            "feature_end": "2026-07-17",
            "development_outcome_end_exclusive": "2025-09-30",
            "validation_outcome_end_exclusive": "2026-02-26",
        },
        fingerprints={
            "features": {"rows": 10, "digest": "sha256:test-fingerprint"}
        },
        grid=pd.DataFrame(
            [_grid_row("grid-rule", qualified=False, validation_rate=55.0)]
        ),
        selected_rule=_rule(),
        trades=pd.DataFrame(),
        metrics=pd.DataFrame(),
        cash_result={},
        qualified=False,
        failed_gates=["historical_gate_failed"],
        reference_cases=pd.DataFrame(),
        d1_diagnostics={},
    )
    markdown = render_main_rise_structural_exit_markdown(report)
    args = build_parser().parse_args(["v2-main-rise-structural-exit-study"])

    assert report["production_ready"] is False
    assert report["formal_metrics"] is None
    assert report["contract"]["d1_role"] == "diagnostic_only"
    assert report["contract"]["exit_execution_assumption"] == (
        "same_close_research_proxy"
    )
    assert "## 32-Rule Nomination Grid" in markdown
    assert "`grid-rule`" in markdown
    assert "## Input Fingerprints" in markdown
    assert "`sha256:test-fingerprint`" in markdown
    assert "2025-09-30" in markdown
    assert "historical_gate_failed" in markdown
    assert args.command == "v2-main-rise-structural-exit-study"


def test_reference_cases_keep_a_named_rejection_without_reading_outcomes() -> None:
    feature = _signal_feature(SIGNAL_DATE, 4)
    feature.update(
        {
            "vt_symbol": "002636.SZSE",
            "stock_name": "Jinan Guoji",
            "support_zone": "ma10",
            "pullback_opportunity_ordinal": 1,
        }
    )

    cases = build_reference_cases(
        pd.DataFrame(),
        pd.DataFrame([feature]),
        _rule(),
        maximum_feature_block=4,
    )

    case = cases.iloc[0]
    assert case["vt_symbol"] == "002636.SZSE"
    assert case["case_status"] == "rejected_reference_case"
    assert case["rejection_reason"] == "first_pullback_did_not_hold_ma5"
    assert pd.isna(case["d1_net_return_pct"])


def _signals(*, signal_id: str = "signal-1") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": signal_id,
                "rule_version": "test-structural-rule",
                "trade_date": SIGNAL_DATE,
                "vt_symbol": "000001.SZSE",
                "stock_name": "Synthetic",
                "sector_id": "BK1",
                "concept_name": "Concept",
                "close_price": 10.0,
                "prior_high20": 10.5,
                "leader_rank": 1,
                "block": 1,
                "pullback_opportunity_ordinal": 1,
                "support_zone": "ma5",
            }
        ]
    )


def _stock_bars(*, mode: str) -> pd.DataFrame:
    dates = tuple(pd.bdate_range(end=SIGNAL_DATE, periods=20))
    rows = [_bar(day, 10.0, 10.2, 9.8) for day in dates]
    paths = {
        "target": [
            _bar("2026-01-06", 10.1, 10.4, 9.9),
            _bar("2026-01-07", 10.2, 10.4, 10.0),
            _bar("2026-01-08", 10.6, 10.7, 10.2),
        ],
        "stock_break": [
            _bar("2026-01-06", 9.0, 10.3, 8.9),
            _bar("2026-01-07", 8.8, 9.2, 8.7),
            _bar("2026-01-08", 9.0, 9.1, 8.8),
        ],
        "concept_break_suspension": [
            _bar("2026-01-07", 10.1, 10.4, 9.9),
            _bar("2026-01-08", 10.2, 10.4, 10.0),
        ],
        "same_day_target": [
            _bar("2026-01-06", 10.6, 10.8, 9.9),
            _bar("2026-01-07", 10.5, 10.7, 10.2),
        ],
        "censored": [
            _bar("2026-01-06", 10.1, 10.4, 9.9),
            _bar("2026-01-07", 10.2, 10.4, 10.0),
            _bar("2026-01-08", 10.1, 10.4, 9.9),
        ],
    }
    rows.extend(paths[mode])
    return pd.DataFrame(rows)


def _bar(
    trade_date: object,
    close_price: float,
    high_price: float,
    low_price: float,
    *,
    symbol: str = "000001.SZSE",
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "trade_date": pd.Timestamp(trade_date),
        "open_price": close_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
    }


def _concept_bars(
    *,
    break_date: str | None = None,
    end: str = "2026-01-12",
) -> pd.DataFrame:
    dates = tuple(pd.bdate_range(end=end, periods=45))
    rows = []
    for index, trade_date in enumerate(dates):
        close = 100.0 + index * 0.2
        if break_date is not None and trade_date >= pd.Timestamp(break_date):
            close = 70.0
        rows.append(
            {
                "sector_id": "BK1",
                "trade_date": trade_date,
                "open_price": close,
                "high_price": close + 0.2,
                "low_price": close - 0.2,
                "close_price": close,
            }
        )
    return pd.DataFrame(rows)


def _rule() -> WeakToStrongRule:
    return WeakToStrongRule(
        version="test-structural-rule",
        minimum_return60_pct=20.0,
        minimum_top3_days10=4,
        minimum_new_high_days20=2,
        maximum_volume_ratio=1.2,
    )


def _signal_feature(trade_date: pd.Timestamp, block: int) -> dict[str, object]:
    symbol = f"00000{block}.SZSE"
    row = {column: 1.0 for column in SIGNAL_FEATURE_COLUMNS}
    row.update(
        {
            "sector_id": "BK1",
            "concept_name": "Concept",
            "trade_date": pd.Timestamp(trade_date),
            "vt_symbol": symbol,
            "stock_name": symbol,
            "open_price": 9.9,
            "high_price": 10.2,
            "low_price": 9.7,
            "close_price": 10.0,
            "daily_return_pct": 2.0,
            "prior_daily_return_pct": -2.0,
            "return20_pct": 25.0,
            "return60_pct": 45.0,
            "ma5": 9.8,
            "ma10": 9.5,
            "ma20": 9.0,
            "ma60": 8.0,
            "prior_high20": 10.5,
            "episode_pullback_low": 9.7,
            "drawdown_from_prior_high_pct": -5.0,
            "volume_ratio5": 1.0,
            "close_location": 0.8,
            "concept_daily_return_pct": 1.0,
            "concept_prior_daily_return_pct": -1.0,
            "concept_relative_pct": 0.8,
            "leader_score": 0.9,
            "leader_rank": 1,
            "prior_leader_rank": 1,
            "member_count": 10,
            "top3_days5": 4,
            "top3_days10": 7,
            "new_high_days20": 3,
            "main_rise_active": True,
            "main_rise_active_sessions": 10,
            "main_rise_gain_pct": 20.0,
            "confirmed_restart_count": 0,
            "pullback_opportunity_ordinal": 1,
            "pullback_duration": 2,
            "weak_to_strong_day": True,
            "pullback_block_reason": None,
            "concept_restrength": True,
            "active_direction": "GOLD",
            "danger_state": "NORMAL",
            "support_zone": "ma5",
            "block": block,
        }
    )
    return row


def _multi_signal_stock_bars(features: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feature in features.to_dict("records"):
        dates = pd.bdate_range(end=feature["trade_date"], periods=20)
        rows.extend(
            _bar(day, 10.0, 10.2, 9.8, symbol=feature["vt_symbol"])
            for day in dates
        )
        rows.append(
            _bar(
                pd.Timestamp(feature["trade_date"]) + pd.offsets.BDay(1),
                10.6,
                10.7,
                10.0,
                symbol=feature["vt_symbol"],
            )
        )
    return pd.DataFrame(rows).drop_duplicates(["vt_symbol", "trade_date"])


def _grid_row(
    version: str,
    *,
    qualified: bool,
    validation_rate: float,
) -> dict[str, object]:
    return {
        **_rule().__dict__,
        "version": version,
        "selection_qualified": qualified,
        "validation_positive_rate_pct": validation_rate,
        "validation_mean_return_pct": 1.0,
        "validation_profit_factor": 1.5,
        "development_mean_return_pct": 1.0,
    }


def _metric(
    segment: str,
    closed: int,
    positive_rate: float,
    mean: float,
    profit_factor: float,
) -> dict[str, object]:
    return {
        "segment": segment,
        "entries": closed,
        "closed_trades": closed,
        "censored_trades": 0,
        "positive_rate_pct": positive_rate,
        "mean_return_pct": mean,
        "median_return_pct": mean,
        "profit_factor": profit_factor,
        "compound_return_pct": 10.0,
        "maximum_drawdown_pct": -5.0,
        "median_holding_sessions": 3.0,
    }


def _cash_result(
    *,
    closed: int,
    win: float,
    compound: float,
    drawdown: float,
) -> dict[str, object]:
    return {
        "closed_trades": closed,
        "cash_win_rate_pct": win,
        "compound_return_pct": compound,
        "maximum_drawdown_pct": drawdown,
        "minimum_cash": 1.0,
    }
