from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from alphaagent.server.services.limit_up.preboard_momentum_data import (
    official_five_minute_close_times,
)
from alphaagent.server.services.limit_up.preboard_touch_model import PRIMARY_VARIANT
from alphaagent.server.services.limit_up.preboard_touch_study import (
    build_preboard_touch_report,
    chronological_touch_split,
    render_preboard_touch_markdown,
)


def test_touch_split_uses_fit_calibration_and_validation_dates() -> None:
    dates = [date(2026, 7, 1) + timedelta(days=index) for index in range(6)]

    fit_dates, calibration_dates, validation_dates = chronological_touch_split(
        [dates[0], dates[0], *dates[1:]],
        fit_session_count=3,
        calibration_session_count=1,
    )

    assert fit_dates == tuple(dates[:3])
    assert calibration_dates == (dates[3],)
    assert validation_dates == tuple(dates[4:])


def test_report_separates_recommendations_from_next_open_fills() -> None:
    signal_dates = (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3))
    manifest = pd.DataFrame(
        [
            _manifest_row(signal_date, symbol, touched=touched)
            for signal_date in signal_dates
            for symbol, touched in (("600001.SSE", True), ("600002.SSE", False))
        ]
    )
    minute_rows = pd.DataFrame(
        [
            row
            for signal_date in signal_dates
            for symbol, touched in (("600001.SSE", True), ("600002.SSE", False))
            for row in _complete_bars(signal_date, symbol, touched=touched)
        ]
    )
    daily_rows = pd.DataFrame(
        [
            _daily_row(trade_date, symbol)
            for trade_date in (*signal_dates, date(2026, 7, 4))
            for symbol in ("600001.SSE", "600002.SSE")
        ]
    )

    report = build_preboard_touch_report(
        manifest,
        minute_rows,
        daily_rows,
        trade_dates=[*signal_dates, date(2026, 7, 4)],
        fit_session_count=1,
        calibration_session_count=1,
        minimum_calibration_signals=1,
    )

    assert report["status"] == "ready"
    assert report["validation_kind"] == "viewed_historical_time_validation"
    validation = report["variants"][PRIMARY_VARIANT]["validation"]
    prediction = validation["prediction"]
    fills = validation["fillable_recommendations"]
    assert prediction["signal_count"] <= 2
    assert prediction["fillable_signal_count"] <= prediction["signal_count"]
    assert fills["signal_count"] == prediction["fillable_signal_count"]
    assert "touch_precision_pct" in prediction
    assert "fillable_touch_precision_pct" in prediction
    assert "touch_latency_trading_minutes" in prediction
    assert "gain_distribution_pct" in prediction
    assert set(prediction["touch_by_gain_bucket"]) == {
        "3_to_5",
        "5_to_7",
        "7_to_9",
        "9_plus",
    }
    assert "3_to_5" in validation["fillable_recommendations_by_gain_bucket"]
    assert validation["two_position_account"]["execution_version"] == "limit-up-cash-v5"
    assert report["contract"]["recommendation_uses_next_open"] is False
    assert "下一根开盘不参与推荐" in render_preboard_touch_markdown(report)


def test_single_variant_replay_is_explicitly_diagnostic_only() -> None:
    signal_dates = (date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3))
    manifest = pd.DataFrame(
        [
            _manifest_row(signal_date, symbol, touched=touched)
            for signal_date in signal_dates
            for symbol, touched in (("600001.SSE", True), ("600002.SSE", False))
        ]
    )
    minutes = pd.DataFrame(
        [
            row
            for signal_date in signal_dates
            for symbol, touched in (("600001.SSE", True), ("600002.SSE", False))
            for row in _complete_bars(signal_date, symbol, touched=touched)
        ]
    )
    daily = pd.DataFrame(
        [
            _daily_row(trade_date, symbol)
            for trade_date in (*signal_dates, date(2026, 7, 4))
            for symbol in ("600001.SSE", "600002.SSE")
        ]
    )

    report = build_preboard_touch_report(
        manifest,
        minutes,
        daily,
        trade_dates=[*signal_dates, date(2026, 7, 4)],
        fit_session_count=1,
        calibration_session_count=1,
        minimum_calibration_signals=1,
        model_variants=("history_gate_intraday_logistic",),
        primary_variant="history_gate_intraday_logistic",
        diagnostic_only=True,
    )

    assert report["variant_order"] == ["history_gate_intraday_logistic"]
    assert report["selection_scope"] == "single_variant_diagnostic_replay"
    assert report["decision"] == "diagnostic_only_not_formal_decision"


def _manifest_row(
    signal_date: date,
    symbol: str,
    *,
    touched: bool,
) -> dict[str, object]:
    result_date = signal_date + timedelta(days=1)
    return {
        "vt_symbol": symbol,
        "name": "Alpha Touch" if touched else "Alpha Fail",
        "trade_date": pd.Timestamp(signal_date),
        "open_price": 10.20,
        "close_price": 11.0 if touched else 10.45,
        "high_price": 11.0 if touched else 10.75,
        "low_price": 10.10,
        "previous_close": 10.0,
        "limit_price": 11.0,
        "result_date": result_date,
        "d1_trade_date": pd.Timestamp(result_date),
        "d1_close_price": 11.15 if touched else 10.20,
        "touched_limit": touched,
        "sealed_limit": touched,
        "prior_limit_count_126": 6,
        "prior_touch_count_126": 8,
        "prior_seal_success_rate_126": 0.75,
        "stock_d1_sample_count": 5,
        "stock_d1_win_rate": 60.0,
        "stock_d1_average_return_pct": 1.0,
        "stock_gene_combined_win_rate": 45.0,
    }


def _complete_bars(
    signal_date: date,
    symbol: str,
    *,
    touched: bool,
) -> list[dict[str, object]]:
    slots = official_five_minute_close_times()
    closes = [10.35 + min(index, 6) * 0.01 for index in range(len(slots))]
    if touched:
        closes[9] = 11.0
        closes[10:] = [11.0] * (len(slots) - 10)
    volumes = [100.0 + index for index in range(len(slots))]
    rows: list[dict[str, object]] = []
    previous = 10.20
    for index, (slot, close, volume) in enumerate(
        zip(slots, closes, volumes, strict=True)
    ):
        high = max(previous, close) + 0.02
        if touched and index == 9:
            high = 11.0
        elif touched and index > 9:
            high = 11.0
        else:
            high = min(high, 10.98)
        rows.append(
            {
                "vt_symbol": symbol,
                "trade_date": pd.Timestamp(signal_date),
                "bar_time": datetime.fromisoformat(f"{signal_date.isoformat()}T{slot}:00"),
                "interval": "5m",
                "open_price": previous,
                "high_price": high,
                "low_price": min(previous, close) - 0.02,
                "close_price": close,
                "volume": volume,
                "turnover": volume * close,
                "source": "fixture",
            }
        )
        previous = close
    return rows


def _daily_row(trade_date: date, symbol: str) -> dict[str, object]:
    positive = symbol == "600001.SSE"
    close = 11.15 if positive else 10.20
    return {
        "vt_symbol": symbol,
        "trade_date": trade_date,
        "open_price": 10.20,
        "close_price": close,
        "high_price": max(close, 10.40),
        "low_price": 10.00,
    }
