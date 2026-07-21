from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.forward_leader_identity import (
    FORWARD_LEADER_RANKING_VERSION,
)
from alphaagent.server.services.low_suction.swing_strategy import (
    IDENTITY_MODE,
    STRATEGY_VERSION,
    SwingSignalInputError,
    SwingStrategyInputs,
    build_swing_signal_capture,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
CAPTURED_AT = datetime(2026, 7, 20, 14, 50, 20, tzinfo=SHANGHAI)


def _stock_bars() -> pd.DataFrame:
    dates = tuple(
        timestamp.date()
        for timestamp in pd.bdate_range(end="2026-07-17", periods=27)
    )
    path = [
        (11.0, 10.0, 11.0),
        (12.0, 10.8, 11.8),
        (11.8, 11.2, 11.4),
        (12.5, 11.5, 12.3),
        (14.0, 12.4, 13.8),
        (13.5, 13.0, 13.0),
        (14.5, 13.0, 14.4),
    ]
    rows: list[dict[str, object]] = []
    closes = [10.0] * 20 + [item[2] for item in path]
    for index, trade_date in enumerate(dates):
        if index < 20:
            high, low, close = 10.2, 9.8, 10.0
        else:
            high, low, close = path[index - 20]
        previous = closes[index - 1] if index else close
        rows.append(
            {
                "vt_symbol": "000001.SZSE",
                "trade_date": trade_date,
                "open_price": close,
                "high_price": high,
                "low_price": low,
                "close_price": close,
                "volume": 10_000_000.0 + index * 100_000.0,
                "turnover": 150_000_000.0,
                "change_pct": (close / previous - 1.0) * 100.0,
                "source": "test.daily",
            }
        )
    return pd.DataFrame(rows)


def _calendar() -> tuple[date, ...]:
    return tuple(pd.to_datetime(_stock_bars()["trade_date"]).dt.date)


def _source_date() -> date:
    return _calendar()[-1]


def _signal_date() -> date:
    return _source_date() + timedelta(days=3)


def _leader_rows(vt_symbol: str = "000001.SZSE") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_trade_date": _source_date(),
                "ranking_version": FORWARD_LEADER_RANKING_VERSION,
                "identity_mode": IDENTITY_MODE,
                "sector_id": "BK_TEST",
                "sector_name": "测试主升",
                "vt_symbol": vt_symbol,
                "rank": 1,
                "is_top3": True,
                "cycle_id": "breakout_trend:BK_TEST:2026-07-08",
                "cycle_start": _calendar()[20],
                "input_fingerprint": "sha256:leader",
                "raw": {"stock_name": "测试龙头"},
            }
        ]
    )


def _leader_history(vt_symbol: str = "000001.SZSE") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_trade_date": trade_date,
                "ranking_version": FORWARD_LEADER_RANKING_VERSION,
                "identity_mode": IDENTITY_MODE,
                "sector_id": "BK_TEST",
                "vt_symbol": vt_symbol,
                "rank": 1,
                "is_top3": True,
            }
            for trade_date in _calendar()[20:]
        ]
    )


def _concept_bars() -> pd.DataFrame:
    dates = _calendar()
    return pd.DataFrame(
        [
            {
                "sector_id": "BK_TEST",
                "concept_name": "测试主升",
                "trade_date": trade_date,
                "close_price": 100.0 + index,
                "source": "test.concept",
            }
            for index, trade_date in enumerate(dates)
        ]
    )


def _benchmark_bars() -> pd.DataFrame:
    rows = []
    for symbol_offset, vt_symbol in enumerate(
        ("000300.SSE", "000905.SSE", "000852.SSE")
    ):
        rows.extend(
            {
                "vt_symbol": vt_symbol,
                "trade_date": trade_date,
                "close_price": 1000.0 + symbol_offset * 100.0 + index,
                "source": "test.index",
            }
            for index, trade_date in enumerate(_calendar())
        )
    return pd.DataFrame(rows)


def _stock_quotes(
    *,
    vt_symbol: str = "000001.SZSE",
    trade_time: datetime | None = None,
    last_price: float = 14.42,
    previous_close: float = 14.4,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": vt_symbol,
                "name": "测试龙头",
                "trade_time": trade_time or CAPTURED_AT - timedelta(seconds=5),
                "last_price": last_price,
                "open_price": 14.1,
                "high_price": 14.45,
                "low_price": 13.6,
                "previous_close": previous_close,
                "volume": 13_000_000.0,
                "turnover": 190_000_000.0,
                "source": "test.quote",
            }
        ]
    )


def _concept_quotes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sector_id": "BK_TEST",
                "captured_at": CAPTURED_AT - timedelta(seconds=2),
                "change_pct": 0.5,
                "source": "test.board.quote",
            }
        ]
    )


def _benchmark_quotes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": vt_symbol,
                "trade_time": CAPTURED_AT - timedelta(seconds=4),
                "last_price": 1028.0 + offset * 100.0,
                "source": "test.index.quote",
            }
            for offset, vt_symbol in enumerate(
                ("000300.SSE", "000905.SSE", "000852.SSE")
            )
        ]
    )


def _inputs() -> SwingStrategyInputs:
    return SwingStrategyInputs(
        source_trade_date=_source_date(),
        signal_trade_date=_signal_date(),
        captured_at=CAPTURED_AT,
        leader_rows=_leader_rows(),
        leader_history=_leader_history(),
        stock_bars=_stock_bars(),
        concept_bars=_concept_bars(),
        benchmark_bars=_benchmark_bars(),
        stock_quotes=_stock_quotes(),
        concept_quotes=_concept_quotes(),
        benchmark_quotes=_benchmark_quotes(),
        completed_dates=_calendar(),
        open_positions=pd.DataFrame(columns=["vt_symbol", "sector_id"]),
    )


def test_signal_uses_d_minus_one_top3_and_1450_provisional_ma5() -> None:
    capture = build_swing_signal_capture(_inputs())

    assert capture.strategy_version == STRATEGY_VERSION
    assert capture.status == "ready"
    assert len(capture.candidates) == 1
    signal = capture.candidates[0]
    assert signal.signal_eligible is True
    assert signal.recommendation_state == "recommended"
    assert signal.feature_cutoff_at == datetime(
        2026, 7, 20, 14, 50, tzinfo=SHANGHAI
    )
    assert signal.support_line == "ma5"
    assert signal.confirmed_higher_highs == 2
    assert signal.strong_days_ge_9_5pct >= 1
    assert signal.reference_peak_price == pytest.approx(14.5)
    assert signal.provisional_close == pytest.approx(14.42)
    assert signal.provisional_ma5 < signal.provisional_close


def test_intraday_preview_uses_observation_time_as_feature_cutoff() -> None:
    preview_at = datetime(2026, 7, 20, 10, 30, tzinfo=SHANGHAI)
    inputs = replace(
        _inputs(),
        captured_at=preview_at,
        stock_quotes=_stock_quotes(trade_time=preview_at),
        concept_quotes=_concept_quotes().assign(captured_at=preview_at),
        benchmark_quotes=_benchmark_quotes().assign(trade_time=preview_at),
    )

    capture = build_swing_signal_capture(inputs, preview=True)

    assert capture.feature_cutoff_at == preview_at
    assert capture.candidates[0].feature_cutoff_at == preview_at


def test_intraday_preview_rejects_lunch_break() -> None:
    preview_at = datetime(2026, 7, 20, 12, 30, tzinfo=SHANGHAI)
    inputs = replace(_inputs(), captured_at=preview_at)

    with pytest.raises(SwingSignalInputError, match="outside_intraday_preview_window"):
        build_swing_signal_capture(inputs, preview=True)


def test_signal_rejects_quote_observed_after_capture() -> None:
    future_quote = CAPTURED_AT + timedelta(seconds=1)
    inputs = replace(_inputs(), stock_quotes=_stock_quotes(trade_time=future_quote))

    with pytest.raises(SwingSignalInputError, match="future quote"):
        build_swing_signal_capture(inputs)


def test_future_or_outcome_columns_are_never_signal_inputs() -> None:
    bars = _stock_bars().assign(future_return_pct=99.0)

    with pytest.raises(SwingSignalInputError, match="future or outcome"):
        build_swing_signal_capture(replace(_inputs(), stock_bars=bars))


def test_non_main_board_candidate_is_never_recommended() -> None:
    inputs = replace(
        _inputs(),
        leader_rows=_leader_rows("300001.SZSE"),
        leader_history=_leader_history("300001.SZSE"),
        stock_bars=_stock_bars().assign(vt_symbol="300001.SZSE"),
        stock_quotes=_stock_quotes(vt_symbol="300001.SZSE"),
    )

    capture = build_swing_signal_capture(inputs)

    assert len(capture.candidates) == 1
    assert capture.candidates[0].signal_eligible is False
    assert capture.candidates[0].decision_reason == "unsupported_board"


def test_missing_prior_strong_day_keeps_candidate_out_of_recommendations() -> None:
    bars = _stock_bars().copy()
    strong_date = _source_date()
    bars.loc[bars["trade_date"].eq(strong_date), "close_price"] = 13.9
    bars.loc[bars["trade_date"].eq(strong_date), "open_price"] = 13.9
    bars.loc[bars["trade_date"].eq(strong_date), "change_pct"] = (
        13.9 / 13.0 - 1.0
    ) * 100.0

    capture = build_swing_signal_capture(
        replace(
            _inputs(),
            stock_bars=bars,
            stock_quotes=_stock_quotes(previous_close=13.9),
        )
    )

    assert capture.candidates[0].signal_eligible is False
    assert capture.candidates[0].decision_reason == "prior_strong_day_missing"
    assert capture.recommendation_count == 0


def test_open_concept_position_prevents_a_second_recommendation() -> None:
    positions = pd.DataFrame(
        [{"vt_symbol": "600001.SSE", "sector_id": "BK_TEST"}]
    )

    capture = build_swing_signal_capture(
        replace(_inputs(), open_positions=positions)
    )

    signal = capture.candidates[0]
    assert signal.signal_eligible is True
    assert signal.recommendation_state == "skipped"
    assert signal.portfolio_reason == "same_concept_position"
    assert capture.recommendation_count == 0
