from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import ma_pullback_study as study
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.ma_pullback_study import (
    build_ma_pullback_cohort_trades,
    build_ma_pullback_metrics,
    build_ma_pullback_report,
    build_ma_pullback_signals,
    build_pullback_round_panel,
    evaluate_ma_pullback_hypothesis,
    label_ma_pullback_trades,
    render_ma_pullback_json,
    render_ma_pullback_markdown,
    run_ma_pullback_study,
)


def _candidate_rows() -> pd.DataFrame:
    recognition_date = date(2025, 6, 23)
    contexts = tuple(pd.bdate_range("2025-06-23", periods=5).date)
    entries = tuple(pd.bdate_range("2025-06-24", periods=5).date)
    exits = tuple(pd.bdate_range("2025-06-25", periods=5).date)
    return pd.DataFrame(
        [
            {
                "event_id": index,
                "recognition_event_id": 100,
                "leader_spell_id": "BK0963:cycle-1:600001.SSE",
                "recognition_source_date": recognition_date,
                "context_date": context_date,
                "source_date": entry_date,
                "entry_date": entry_date,
                "planned_exit_date": exit_date,
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股份",
                "recognition_rank": 1,
                "cycle_relative_percentile": 0.9,
                "spell_session_offset": index,
                "signal_close": 10.0,
                "previous_high": 10.2,
                "ma5": 9.8,
                "ma10": 9.5,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "market_phase": "recovery",
                "main_rise": True,
                "is_top3": True,
                "rank_mode": "event_recognition_proxy",
                "evidence_level": "test",
            }
            for index, (context_date, entry_date, exit_date) in enumerate(
                zip(contexts, entries, exits, strict=True),
                start=1,
            )
        ]
    )


def _daily_bars(
    *,
    post_recognition_closes: tuple[float, float, float, float] = (
        9.8,
        10.0,
        9.7,
        9.9,
    ),
) -> pd.DataFrame:
    dates = tuple(pd.bdate_range("2025-05-15", "2025-07-02").date)
    close_by_date = {trade_date: 8.0 + index * 0.05 for index, trade_date in enumerate(dates)}
    close_by_date[date(2025, 6, 20)] = 9.0
    close_by_date[date(2025, 6, 23)] = 10.0
    for trade_date, close in zip(
        pd.bdate_range("2025-06-24", periods=4).date,
        post_recognition_closes,
        strict=True,
    ):
        close_by_date[trade_date] = close
    close_by_date[date(2025, 6, 30)] = 10.1
    close_by_date[date(2025, 7, 1)] = 10.4
    close_by_date[date(2025, 7, 2)] = 10.5
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": close,
                "high_price": close + 0.2,
                "low_price": close - 0.2,
                "close_price": close,
                "volume": 100_000.0 + index * 1_000.0,
            }
            for index, (trade_date, close) in enumerate(close_by_date.items())
        ]
    )


def _trading_dates() -> tuple[date, ...]:
    return tuple(pd.bdate_range("2025-05-15", "2025-07-02").date)


def test_pullback_rounds_require_a_completed_positive_rebound() -> None:
    panel = build_pullback_round_panel(
        _candidate_rows(),
        _daily_bars(),
        trading_dates=_trading_dates(),
    )

    assert panel["pullback_round"].tolist() == [1, 1, 2, 2, 3]
    assert panel["pullback_round_group"].tolist() == [
        "first",
        "first",
        "second",
        "second",
        "third_plus",
    ]
    assert panel.loc[panel["spell_session_offset"].eq(1), "completed_rebound"].item() is False
    assert panel.loc[panel["spell_session_offset"].eq(3), "completed_rebound"].item() is True


def test_flat_completed_day_does_not_create_a_second_pullback() -> None:
    panel = build_pullback_round_panel(
        _candidate_rows(),
        _daily_bars(post_recognition_closes=(9.8, 9.8, 9.7, 9.9)),
        trading_dates=_trading_dates(),
    )

    assert panel["pullback_round"].tolist()[:4] == [1, 1, 1, 1]


def test_future_daily_returns_do_not_change_an_earlier_pullback_round() -> None:
    baseline = build_pullback_round_panel(
        _candidate_rows(),
        _daily_bars(),
        trading_dates=_trading_dates(),
    )
    changed = build_pullback_round_panel(
        _candidate_rows(),
        _daily_bars(post_recognition_closes=(9.8, 10.0, 30.0, 1.0)),
        trading_dates=_trading_dates(),
    )

    earlier = baseline["spell_session_offset"].le(3)
    columns = [
        "event_id",
        "context_date",
        "pullback_round",
        "completed_rebound",
    ]
    pd.testing.assert_frame_equal(
        baseline.loc[earlier, columns].reset_index(drop=True),
        changed.loc[earlier, columns].reset_index(drop=True),
    )


def _signal_candidates() -> pd.DataFrame:
    rows = []
    for event_id, (symbol, entry_date, pullback_round) in enumerate(
        (
            ("600001.SSE", date(2025, 7, 1), 1),
            ("600002.SSE", date(2025, 7, 2), 2),
        ),
        start=1,
    ):
        rows.append(
            {
                "event_id": event_id,
                "source_date": entry_date,
                "entry_date": entry_date,
                "planned_exit_date": entry_date + timedelta(days=1),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": symbol,
                "recognition_rank": event_id,
                "signal_close": 10.2,
                "active_direction": "GOLD" if event_id == 1 else "SILVER",
                "danger_state": "NORMAL",
                "market_phase": "recovery",
                "leader_spell_id": f"BK0963:cycle-1:{symbol}",
                "recognition_source_date": date(2025, 6, 30),
                "context_date": entry_date - timedelta(days=1),
                "spell_session_offset": pullback_round,
                "stock_close": 10.2,
                "ma5": 10.0,
                "ma10": 9.5,
                "ma20": 9.0,
                "pullback_round": pullback_round,
                "pullback_round_group": "first" if pullback_round == 1 else "second",
                "completed_rebound": pullback_round == 2,
                "concept_main_rise": True,
                "stock_above_ma5": True,
                "stock_trend_order": True,
                "stock_strong_main_rise": event_id == 1,
                "daily_volume_ratio": 0.7 if event_id == 1 else 1.8,
                "daily_volume_class": "contraction" if event_id == 1 else "expansion",
            }
        )
    return pd.DataFrame(rows)


def _minute_times(entry_date: date) -> list[datetime]:
    morning = [
        datetime.combine(entry_date, datetime.min.time()).replace(hour=9, minute=35)
        + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    afternoon = [
        datetime.combine(entry_date, datetime.min.time()).replace(hour=13, minute=5)
        + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    return [*morning, *afternoon]


def _signal_minute_bars() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    specifications = (
        (
            "600001.SSE",
            date(2025, 7, 1),
            [10.10, 9.95, 10.02, 10.05, *([10.08] * 44)],
            [10.05, 9.90, 9.98, 10.00, *([10.04] * 44)],
        ),
        (
            "600002.SSE",
            date(2025, 7, 2),
            [10.05, 9.80, 9.45, 9.55, *([9.70] * 44)],
            [9.95, 9.70, 9.40, 9.48, *([9.60] * 44)],
        ),
    )
    for symbol, entry_date, closes, lows in specifications:
        opens = [10.2, *closes[:-1]]
        volumes = [100.0, 120.0, 130.0, 150.0, *([140.0] * 44)]
        for bar_time, open_price, low_price, close_price, volume in zip(
            _minute_times(entry_date),
            opens,
            lows,
            closes,
            volumes,
            strict=True,
        ):
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": entry_date,
                    "bar_time": bar_time,
                    "interval": "5m",
                    "open_price": open_price,
                    "high_price": max(open_price, close_price) + 0.03,
                    "low_price": low_price,
                    "close_price": close_price,
                    "volume": volume,
                    "turnover": close_price * volume,
                    "source": "tdx_public_hq",
                }
            )
    return pd.DataFrame(rows)


def test_adaptive_signal_uses_ma5_first_and_ma10_second() -> None:
    signals = build_ma_pullback_signals(_signal_candidates(), _signal_minute_bars())
    adaptive = signals.loc[signals["rule_arm"].eq("adaptive_ma5_ma10")]

    assert len(adaptive) == 2
    first = adaptive.loc[adaptive["pullback_round"].eq(1)].iloc[0]
    second = adaptive.loc[adaptive["pullback_round"].eq(2)].iloc[0]
    assert first["reference_line"] == "ma5"
    assert first["observed_at"] == datetime(2025, 7, 1, 9, 45)
    assert first["entry_time"] == datetime(2025, 7, 1, 9, 50)
    assert first["entry_price_raw"] == pytest.approx(10.02)
    assert second["reference_line"] == "ma10"
    assert second["observed_at"] == datetime(2025, 7, 2, 9, 50)
    assert second["entry_time"] == datetime(2025, 7, 2, 9, 55)
    assert second["entry_price_raw"] == pytest.approx(9.55)
    assert not signals.duplicated(["event_id", "rule_arm"]).any()


def test_signal_requires_completed_bar_reclaim_and_is_future_invariant() -> None:
    baseline = build_ma_pullback_signals(
        _signal_candidates().iloc[[0]],
        _signal_minute_bars().loc[lambda frame: frame["vt_symbol"].eq("600001.SSE")],
    )
    changed_bars = _signal_minute_bars().loc[
        lambda frame: frame["vt_symbol"].eq("600001.SSE")
    ].copy()
    future = changed_bars["bar_time"].gt(datetime(2025, 7, 1, 9, 50))
    changed_bars.loc[future, ["open_price", "high_price", "low_price", "close_price"]] = (
        30.0
    )
    changed_bars.loc[future, "turnover"] = changed_bars.loc[future, "volume"] * 30.0
    changed = build_ma_pullback_signals(_signal_candidates().iloc[[0]], changed_bars)

    columns = [
        "observation_id",
        "rule_arm",
        "observed_at",
        "entry_time",
        "entry_price_raw",
    ]
    pd.testing.assert_frame_equal(baseline[columns], changed[columns])
    adaptive = baseline.loc[baseline["rule_arm"].eq("adaptive_ma5_ma10")].iloc[0]
    assert adaptive["observed_at"] != datetime(2025, 7, 1, 9, 40)


def _execution_daily_bars() -> pd.DataFrame:
    rows = []
    for symbol, entry_date, entry_close, exit_close in (
        ("600001.SSE", date(2025, 7, 1), 10.1, 10.6),
        ("600002.SSE", date(2025, 7, 2), 9.7, 9.2),
    ):
        for trade_date, close in (
            (entry_date - timedelta(days=1), 10.2),
            (entry_date, entry_close),
            (entry_date + timedelta(days=1), exit_close),
        ):
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close,
                    "high_price": close + 0.2,
                    "low_price": close - 0.2,
                    "close_price": close,
                    "volume": 100_000.0,
                }
            )
    return pd.DataFrame(rows)


def test_labels_reuse_d1_cash_execution_and_double_cost() -> None:
    signals = build_ma_pullback_signals(_signal_candidates(), _signal_minute_bars())
    adaptive = signals.loc[signals["rule_arm"].eq("adaptive_ma5_ma10")].copy()
    trades = label_ma_pullback_trades(
        adaptive,
        _execution_daily_bars(),
        trading_dates=tuple(pd.date_range("2025-06-30", "2025-07-03").date),
    )

    assert trades["normal_status"].eq("closed").all()
    assert trades["stressed_status"].eq("closed").all()
    assert trades["double_cost_net_return_pct"].le(trades["net_return_pct"]).all()
    assert trades.loc[trades["vt_symbol"].eq("600001.SSE"), "net_return_pct"].item() > 0
    assert trades.loc[trades["vt_symbol"].eq("600002.SSE"), "net_return_pct"].item() < 0


def _metric_trades() -> pd.DataFrame:
    dates = tuple(pd.bdate_range("2025-01-02", periods=50).date)
    rows = []
    for index, entry_date in enumerate(dates):
        block = index % 3 + 1 if index < 30 else index % 2 + 4
        pullback_round = 1 if index % 2 else 2
        for arm, value in (
            ("adaptive_ma5_ma10", 1.0 if index % 4 else -0.5),
            ("always_ma5", 0.8 if index % 3 else -1.0),
            ("always_ma10", 0.6 if index % 2 else -1.2),
            ("reversed_ma10_ma5", 0.5 if index % 2 else -1.3),
        ):
            rows.append(
                {
                    "observation_id": f"{arm}-{index}",
                    "event_id": index,
                    "entry_date": entry_date,
                    "block": block,
                    "rule_arm": arm,
                    "reference_line": {
                        "adaptive_ma5_ma10": "ma5" if pullback_round == 1 else "ma10",
                        "always_ma5": "ma5",
                        "always_ma10": "ma10",
                        "reversed_ma10_ma5": "ma10" if pullback_round == 1 else "ma5",
                    }[arm],
                    "pullback_round": pullback_round,
                    "pullback_round_group": "first" if pullback_round == 1 else "second",
                    "concept_main_rise": True,
                    "stock_trend_order": True,
                    "stock_strong_main_rise": index % 3 == 0,
                    "daily_volume_class": "contraction",
                    "intraday_volume_class": "normal",
                    "leader_rank_group": "rank_1",
                    "market_regime": "GOLD/NORMAL",
                    "normal_status": "closed",
                    "stressed_status": "closed",
                    "net_return_pct": value,
                    "double_cost_net_return_pct": value - 0.2,
                }
            )
    return pd.DataFrame(rows)


def test_metrics_preserve_time_split_compounding_and_fixed_decision() -> None:
    cohort_trades = build_ma_pullback_cohort_trades(_metric_trades())
    metrics = build_ma_pullback_metrics(cohort_trades)
    decision = evaluate_ma_pullback_hypothesis(metrics)

    adaptive = metrics.loc[
        metrics["table_id"].eq("arm_comparison")
        & metrics["cohort_key"].eq("adaptive_ma5_ma10")
    ].set_index("segment")
    assert adaptive.loc["development", "closed_trades"] == 30
    assert adaptive.loc["validation", "closed_trades"] == 20
    assert adaptive.loc["all", "source_days"] == 50
    assert adaptive.loc["all", "compound_return_pct"] > 0
    assert adaptive.loc["all", "maximum_drawdown_pct"] <= 0
    assert decision["adaptive_arm"] == "adaptive_ma5_ma10"
    assert decision["adaptive_advantage"] is True


def test_round_reference_comparison_uses_one_canonical_arm_per_price_rule() -> None:
    trades = _metric_trades()
    cohorts = build_ma_pullback_cohort_trades(trades)
    direct = cohorts.loc[cohorts["table_id"].eq("round_reference_comparison")]

    assert set(direct["cohort_key"]) == {
        "first|ma5",
        "first|ma10",
        "second|ma5",
        "second|ma10",
    }
    assert not direct.duplicated(["event_id", "cohort_key"]).any()


def _report_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pullback_panel = _signal_candidates()
    signals = build_ma_pullback_signals(pullback_panel, _signal_minute_bars())
    trades = signals.assign(
        block=1,
        normal_status="closed",
        stressed_status="closed",
        net_return_pct=1.0,
        double_cost_net_return_pct=0.7,
    )
    metrics = build_ma_pullback_metrics(build_ma_pullback_cohort_trades(trades))
    return pullback_panel, signals, trades, metrics


def test_report_is_deterministic_and_keeps_production_claims_closed() -> None:
    panel, signals, trades, metrics = _report_frames()
    decision = evaluate_ma_pullback_hypothesis(metrics)
    report = build_ma_pullback_report(
        panel,
        signals,
        trades,
        metrics,
        decision,
        metadata={
            "coverage": {"comparison_candidates": 2, "minute_rows": 96},
            "input_fingerprints": {"test": {"sha256": "abc"}},
            "discovery_start": date(2025, 1, 1),
            "discovery_end": date(2025, 7, 1),
        },
    )

    payload = render_ma_pullback_json(report)
    markdown = render_ma_pullback_markdown(report)
    assert '"formal_metrics": null' in payload
    assert '"formal_rule_selected": false' in payload
    assert "NaN" not in payload
    assert "第一轮回调" in markdown
    assert "D-1 MA5" in markdown
    assert "第二轮回调" in markdown
    assert "D-1 MA10" in markdown
    assert "事件 Rank1-3 代理" in markdown


def test_runner_and_cli_expose_only_frozen_study_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    frames = _report_frames()
    decision = evaluate_ma_pullback_hypothesis(frames[-1])
    monkeypatch.setattr(
        study,
        "load_ma_pullback_study_data",
        lambda: (
            *frames,
            decision,
            {
                "coverage": {"comparison_candidates": 2, "minute_rows": 96},
                "input_fingerprints": {},
                "discovery_start": date(2025, 1, 1),
                "discovery_end": date(2025, 7, 1),
            },
        ),
    )

    report = run_ma_pullback_study()
    args = build_parser().parse_args(["v2-ma-pullback-study", "--format", "json"])
    assert report["frozen_contract"]["arms"]["adaptive_ma5_ma10"] == {
        "first": "ma5",
        "second": "ma10",
    }
    assert args.command == "v2-ma-pullback-study"
    assert not hasattr(args, "threshold")
    assert not hasattr(args, "rule")
