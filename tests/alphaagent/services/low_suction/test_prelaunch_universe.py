from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.low_suction.prelaunch_universe import (
    PRELAUNCH_FEATURES,
    build_prelaunch_feature_panel,
)


DATES = tuple(pd.bdate_range("2024-09-02", periods=80))
TARGET_DATE = DATES[75]


def _symbol_bars(
    vt_symbol: str,
    *,
    name: str,
    start_index: int = 0,
    strong_index: int | None = None,
) -> list[dict[str, object]]:
    symbol, exchange = vt_symbol.split(".")
    close = 10.0
    rows = []
    for index, trade_date in enumerate(DATES[start_index:], start=start_index):
        daily_return = 0.3
        if index == strong_index:
            daily_return = 6.0
        previous_close = close
        close *= 1.0 + daily_return / 100.0
        rows.append(
            {
                "vt_symbol": vt_symbol,
                "symbol": symbol,
                "exchange": exchange,
                "name": name,
                "trade_date": trade_date,
                "open_price": previous_close,
                "high_price": max(previous_close, close) * 1.01,
                "low_price": min(previous_close, close) * 0.99,
                "close_price": close,
                "volume": 1_000_000.0 + index * 10_000.0,
                "turnover": 150_000_000.0 + index * 1_000_000.0,
            }
        )
    return rows


def _stock_bars() -> pd.DataFrame:
    rows = []
    rows.extend(_symbol_bars("600001.SSE", name="正常股份"))
    rows.extend(_symbol_bars("300001.SZSE", name="创业股份"))
    rows.extend(_symbol_bars("600002.SSE", name="*ST风险"))
    rows.extend(_symbol_bars("600003.SSE", name="次新股份", start_index=25))
    rows.extend(
        _symbol_bars(
            "600004.SSE",
            name="已有强势",
            strong_index=72,
        )
    )
    return pd.DataFrame(rows)


def test_prelaunch_universe_is_full_main_board_d1_and_first_launch_eligible() -> None:
    panel = build_prelaunch_feature_panel(
        _stock_bars(),
        target_dates=(TARGET_DATE.date(),),
    )

    assert panel[["entry_date", "vt_symbol"]].to_dict("records") == [
        {"entry_date": TARGET_DATE.date(), "vt_symbol": "600001.SSE"}
    ]
    row = panel.iloc[0]
    assert row["context_date"] == DATES[74].date()
    assert row["feature_cutoff_date"] == DATES[74].date()
    assert row["prior_sessions"] == 75
    assert row["prior_strong_days_10d"] == 0
    assert row["return_1d_pct"] == pytest.approx(0.3)
    assert row["volume_ratio_1d_to_prior5"] > 1.0
    assert row["log_turnover_median_20d"] == pytest.approx(
        np.log1p(np.median([150_000_000.0 + index * 1_000_000.0 for index in range(55, 75)]))
    )
    assert set(PRELAUNCH_FEATURES).issubset(panel.columns)


def test_feature_panel_exposes_no_d_market_or_outcome_values() -> None:
    panel = build_prelaunch_feature_panel(
        _stock_bars(),
        target_dates=(TARGET_DATE.date(),),
    )

    prohibited = {
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
        "change_pct",
        "verified_first_explosion",
        "d_return_pct",
        "net_return_pct",
    }
    assert prohibited.isdisjoint(panel.columns)


def test_d_and_future_market_values_cannot_change_d1_features() -> None:
    baseline = build_prelaunch_feature_panel(
        _stock_bars(),
        target_dates=(TARGET_DATE.date(),),
    )
    changed = _stock_bars()
    future = pd.to_datetime(changed["trade_date"]).ge(TARGET_DATE)
    changed.loc[
        future,
        [
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "turnover",
        ],
    ] = 999_999_999.0
    repeated = build_prelaunch_feature_panel(
        changed,
        target_dates=(TARGET_DATE.date(),),
    )

    pd.testing.assert_frame_equal(baseline, repeated)


@pytest.mark.parametrize(
    "column",
    ["future_return_pct", "outcome_group", "net_return_pct", "exit_price"],
)
def test_feature_panel_rejects_future_or_outcome_columns(column: str) -> None:
    with pytest.raises(ValueError, match="prohibited"):
        build_prelaunch_feature_panel(
            _stock_bars().assign(**{column: 1.0}),
            target_dates=(TARGET_DATE.date(),),
        )


def test_target_date_requires_an_observed_d_bar_without_reading_its_values() -> None:
    bars = _stock_bars()
    bars = bars.loc[
        ~(
            bars["vt_symbol"].eq("600001.SSE")
            & pd.to_datetime(bars["trade_date"]).eq(TARGET_DATE)
        )
    ]

    panel = build_prelaunch_feature_panel(
        bars,
        target_dates=(TARGET_DATE.date(),),
    )

    assert panel.empty
