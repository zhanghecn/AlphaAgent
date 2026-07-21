from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from alphaagent.server.services.low_suction.calculated_leader_relationship import (
    build_calculated_relationship_pool,
    build_calculated_stock_features,
    build_relationship_matrices,
)


def _feature_stock_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=55)
    rows: list[dict[str, object]] = []
    paths = {
        "600001.SSE": np.full(len(dates), 0.012),
        "002001.SZSE": np.full(len(dates), 0.010),
        "600002.SSE": np.zeros(len(dates)),
        "300001.SZSE": np.full(len(dates), 0.012),
        "688001.SSE": np.full(len(dates), 0.012),
    }
    for symbol, returns in paths.items():
        returns = returns.copy()
        if symbol != "600002.SSE":
            returns[35] = 0.06
        close = 10.0
        for index, trade_date in enumerate(dates):
            close *= 1.0 + float(returns[index])
            rows.append(
                {
                    "vt_symbol": symbol,
                    "stock_name": symbol,
                    "trade_date": trade_date,
                    "open_price": close * 0.995,
                    "high_price": close * 1.01,
                    "low_price": close * 0.99,
                    "close_price": close,
                    "volume": 1_000_000.0 * (1.0 + index / 100.0),
                    "turnover": 100_000_000.0 * (1.0 + index / 100.0),
                }
            )
    return pd.DataFrame(rows)


def _through_cutoff(frame: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    columns = [
        "vt_symbol",
        "trade_date",
        "return_10d_pct",
        "ma5",
        "ma10",
        "ma20",
        "strong_days_10",
        "return_acceleration_5d_pct",
        "leader_eligible",
    ]
    return frame.loc[frame["trade_date"].le(cutoff), columns].reset_index(drop=True)


def test_feature_rows_are_strict_main_board_main_rise_only() -> None:
    rows = build_calculated_stock_features(_feature_stock_bars())
    eligible = rows.loc[rows["leader_eligible"]]

    assert set(rows["vt_symbol"]) == {
        "600001.SSE",
        "600002.SSE",
        "002001.SZSE",
    }
    assert set(eligible["vt_symbol"]) == {"600001.SSE", "002001.SZSE"}
    assert eligible["strong_days_10"].ge(1).all()
    assert eligible["main_rise_alive"].all()


def test_features_before_cutoff_ignore_future_mutations() -> None:
    bars = _feature_stock_bars()
    cutoff = pd.Timestamp("2025-03-03")
    baseline = build_calculated_stock_features(bars)
    changed = bars.copy()
    changed.loc[
        changed["trade_date"].gt(cutoff),
        ["open_price", "high_price", "low_price", "close_price"],
    ] *= 4.0
    mutated = build_calculated_stock_features(changed)

    pd.testing.assert_frame_equal(
        _through_cutoff(baseline, cutoff),
        _through_cutoff(mutated, cutoff),
    )


def _relationship_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    dates = pd.bdate_range("2025-01-02", periods=90)
    cycle_position = 48
    cycle_date = dates[cycle_position]
    phase = np.linspace(0.0, 8.0 * np.pi, len(dates))
    concept_returns = 0.004 + np.sin(phase) * 0.009
    market_returns = np.cos(phase) * 0.001
    stock_returns = {
        "600001.SSE": concept_returns + market_returns,
        "600002.SSE": concept_returns * 0.85 + market_returns + np.cos(phase) * 0.001,
        "002001.SZSE": concept_returns * 0.70 + market_returns + np.sin(phase * 0.5) * 0.001,
        "600003.SSE": -concept_returns + market_returns,
    }
    stock_rows: list[dict[str, object]] = []
    for symbol, returns in stock_returns.items():
        close = 10.0
        for trade_date, daily_return in zip(dates, returns, strict=True):
            close *= 1.0 + float(daily_return)
            stock_rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close,
                    "high_price": close * 1.01,
                    "low_price": close * 0.99,
                    "close_price": close,
                    "volume": 1_000_000.0,
                    "turnover": 100_000_000.0,
                }
            )
    concept_close = 100.0 * np.cumprod(1.0 + concept_returns + market_returns)
    concepts = pd.DataFrame(
        {
            "sector_id": "BK0001",
            "trade_date": dates,
            "close_price": concept_close,
        }
    )
    market = pd.DataFrame(
        {
            "trade_date": dates,
            "market_daily_return": market_returns,
        }
    )
    cycles = pd.DataFrame(
        [
            {
                "cycle_id": "breakout_trend:BK0001:2025",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "trade_date": cycle_date,
                "concept_return_10d": 0.08,
            }
        ]
    )
    features = pd.DataFrame(
        [
            {
                "vt_symbol": symbol,
                "stock_name": symbol,
                "trade_date": cycle_date,
                "leader_eligible": symbol != "600003.SSE",
                "first_strong_date_10d": dates[cycle_position - 5],
                "first_strong_sessions_ago_10d": 5.0,
                "strong_days_10": 2.0,
                "return_10d_pct": 10.0,
                "return_acceleration_5d_pct": 2.0,
                "distance_from_prior_high_pct": -1.0,
                "volume_ratio_5_20": 1.2,
                "turnover_median_20d": 100_000_000.0,
            }
            for symbol in stock_returns
        ]
    )
    return pd.DataFrame(stock_rows), concepts, market, cycles, features


def _causal_pool(
    stocks: pd.DataFrame,
    concepts: pd.DataFrame,
    market: pd.DataFrame,
    cycles: pd.DataFrame,
    features: pd.DataFrame,
) -> pd.DataFrame:
    matrices = build_relationship_matrices(stocks, concepts, market)
    return build_calculated_relationship_pool(
        cycles,
        features,
        matrices,
        direction="causal",
    )


def test_causal_relation_pool_finds_price_linked_stocks() -> None:
    stocks, concepts, market, cycles, features = _relationship_inputs()
    pool = _causal_pool(stocks, concepts, market, cycles, features)

    assert pool.iloc[0]["vt_symbol"] == "600001.SSE"
    assert set(pool["vt_symbol"]) == {"600001.SSE", "600002.SSE", "002001.SZSE"}
    assert pool["relationship_known_at"].eq(cycles.iloc[0]["trade_date"]).all()
    assert pool["relationship_direction"].eq("causal").all()


def test_causal_relation_pool_does_not_change_when_future_prices_change() -> None:
    stocks, concepts, market, cycles, features = _relationship_inputs()
    cycle_date = pd.Timestamp(cycles.iloc[0]["trade_date"])
    baseline = _causal_pool(stocks, concepts, market, cycles, features)
    changed_stocks = stocks.copy()
    changed_concepts = concepts.copy()
    stock_future = changed_stocks["trade_date"].gt(cycle_date)
    concept_future = changed_concepts["trade_date"].gt(cycle_date)
    changed_stocks.loc[stock_future, "close_price"] *= 3.0
    changed_concepts.loc[concept_future, "close_price"] *= 0.4
    mutated = _causal_pool(
        changed_stocks,
        changed_concepts,
        market,
        cycles,
        features,
    )

    pd.testing.assert_frame_equal(baseline, mutated)


def test_realized_relation_pool_is_known_at_forty_session_boundary() -> None:
    stocks, concepts, market, cycles, features = _relationship_inputs()
    matrices = build_relationship_matrices(stocks, concepts, market)
    pool = build_calculated_relationship_pool(
        cycles,
        features,
        matrices,
        direction="realized",
    )
    cycle_date = pd.Timestamp(cycles.iloc[0]["trade_date"])
    dates = tuple(pd.to_datetime(matrices.trading_dates))
    boundary = dates[dates.index(cycle_date) + 40]

    assert pool["relationship_known_at"].eq(boundary).all()
    assert pool["relationship_direction"].eq("realized").all()
    assert pool["relation_rank"].tolist() == list(range(1, len(pool) + 1))


def test_main_board_helper_does_not_accept_chinext_star_or_bse() -> None:
    bars = _feature_stock_bars()
    features = build_calculated_stock_features(bars)

    assert "300001.SZSE" not in set(features["vt_symbol"])
    assert "688001.SSE" not in set(features["vt_symbol"])
    assert all(
        symbol.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))
        for symbol in features["vt_symbol"]
    )


def test_relationship_cycle_date_accepts_python_date() -> None:
    stocks, concepts, market, cycles, features = _relationship_inputs()
    cycles = cycles.assign(trade_date=date.fromisoformat("2025-03-11"))
    features = features.assign(trade_date=pd.Timestamp("2025-03-11"))
    pool = _causal_pool(stocks, concepts, market, cycles, features)

    assert not pool.empty
