from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.leader_waves import (
    build_leader_wave_ledger,
)
from alphaagent.server.services.low_suction.stock_wave_pullbacks import (
    build_declared_continuation_trade,
    build_first_support_approaches,
    build_stock_wave_features,
    build_wave_pullback_trades,
    find_campaign_ignitions,
)


def _history() -> list[dict[str, object]]:
    return [
        {
            "trade_date": trade_date,
            "open_price": 10.0,
            "high_price": 10.2,
            "low_price": 9.8,
            "close_price": 10.0,
            "volume": 100.0,
        }
        for trade_date in pd.bdate_range("2025-01-02", periods=25)
    ]


def _bar(
    trade_date: pd.Timestamp,
    *,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "open_price": close,
        "high_price": high,
        "low_price": low,
        "close_price": close,
        "volume": volume,
    }


def _single_wave_bars() -> pd.DataFrame:
    rows = _history()
    dates = pd.bdate_range(pd.Timestamp(rows[-1]["trade_date"]) + pd.offsets.BDay(), periods=7)
    rows.extend(
        [
            _bar(dates[0], high=11.0, low=9.9, close=10.8, volume=200.0),
            _bar(dates[1], high=12.0, low=10.7, close=11.8, volume=160.0),
            _bar(dates[2], high=11.7, low=10.9, close=11.4, volume=70.0),
            _bar(dates[3], high=11.3, low=10.55, close=10.7, volume=90.0),
            _bar(dates[4], high=10.8, low=9.9, close=10.1, volume=180.0),
            _bar(dates[5], high=11.5, low=10.0, close=11.2, volume=120.0),
            _bar(dates[6], high=12.5, low=11.1, close=12.3, volume=150.0),
        ]
    )
    return pd.DataFrame(rows)


def _declared_continuation_bars() -> pd.DataFrame:
    rows = _history()
    dates = pd.bdate_range(pd.Timestamp(rows[-1]["trade_date"]) + pd.offsets.BDay(), periods=7)
    rows.extend(
        [
            _bar(dates[0], high=12.0, low=10.0, close=11.8, volume=200.0),
            _bar(dates[1], high=11.6, low=10.8, close=11.0, volume=120.0),
            _bar(dates[2], high=11.5, low=10.9, close=11.3, volume=90.0),
            _bar(dates[3], high=11.7, low=11.1, close=11.5, volume=80.0),
            _bar(dates[4], high=11.8, low=11.2, close=11.7, volume=85.0),
            _bar(dates[5], high=12.2, low=11.6, close=12.1, volume=130.0),
            _bar(dates[6], high=12.4, low=11.9, close=12.3, volume=140.0),
        ]
    )
    return pd.DataFrame(rows)


def _anchor(frame: pd.DataFrame) -> date:
    return pd.Timestamp(frame.iloc[25]["trade_date"]).date()


def test_features_and_ignition_are_point_in_time() -> None:
    bars = _single_wave_bars()
    features = build_stock_wave_features(bars)
    anchor = pd.Timestamp(bars.iloc[25]["trade_date"])
    ignition = find_campaign_ignitions(features)

    row = features.loc[features["trade_date"].eq(anchor)].iloc[0]
    assert row["daily_return_pct"] == pytest.approx(8.0)
    assert row["volume_ratio_prior5"] == pytest.approx(2.0)
    assert row["close_price"] > row["prior_high20"]
    assert row["ma5"] > row["ma10"] > row["ma20"]
    assert ignition["trade_date"].tolist() == [anchor]

    changed = bars.copy()
    changed.loc[changed["trade_date"].gt(anchor), [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
    ]] *= 3.0
    mutated = build_stock_wave_features(changed)
    columns = [
        "trade_date",
        "daily_return_pct",
        "prior_high20",
        "ma5",
        "ma10",
        "ma20",
        "volume_ratio_prior5",
    ]
    pd.testing.assert_frame_equal(
        features.loc[features["trade_date"].le(anchor), columns].reset_index(drop=True),
        mutated.loc[mutated["trade_date"].le(anchor), columns].reset_index(drop=True),
    )


def test_first_support_approaches_preserve_line_order_and_volume() -> None:
    bars = _single_wave_bars()
    features = build_stock_wave_features(bars)
    waves = build_leader_wave_ledger(bars, anchor_date=_anchor(bars))
    approaches = build_first_support_approaches(features, waves)

    first_wave = approaches.loc[approaches["wave_number"].eq(1)].set_index(
        "support_line"
    )
    assert list(first_wave.index) == ["ma5", "ma10", "ma20"]
    assert first_wave.loc["ma5", "approach_date"] < first_wave.loc[
        "ma10", "approach_date"
    ]
    assert first_wave.loc["ma10", "approach_date"] < first_wave.loc[
        "ma20", "approach_date"
    ]
    assert first_wave.loc["ma5", "line_distance_low_pct"] <= 2.0
    assert first_wave.loc["ma5", "volume_class_prior5"] == "contraction"
    assert first_wave.loc["ma20", "volume_class_prior5"] == "explosion"
    assert first_wave["approach_date"].is_unique
    assert first_wave["execution_selected"].all()


def test_future_mutation_cannot_change_earlier_first_approaches() -> None:
    bars = _single_wave_bars()
    features = build_stock_wave_features(bars)
    waves = build_leader_wave_ledger(bars, anchor_date=_anchor(bars))
    baseline = build_first_support_approaches(features, waves)
    cutoff = pd.Timestamp(bars.iloc[29]["trade_date"])

    changed = bars.copy()
    changed.loc[changed["trade_date"].gt(cutoff), [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
    ]] *= 2.0
    mutated = build_first_support_approaches(
        build_stock_wave_features(changed),
        waves,
    )
    columns = [
        "wave_number",
        "support_line",
        "approach_date",
        "support_price",
        "line_distance_low_pct",
        "volume_ratio_prior5",
    ]
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["approach_date"].le(cutoff), columns].reset_index(drop=True),
        mutated.loc[mutated["approach_date"].le(cutoff), columns].reset_index(drop=True),
    )


def test_same_date_approaches_keep_only_deepest_execution_line() -> None:
    bars = _single_wave_bars()
    features = build_stock_wave_features(bars)
    waves = build_leader_wave_ledger(bars, anchor_date=_anchor(bars))
    deep_date = pd.Timestamp(bars.iloc[27]["trade_date"])
    features.loc[features["trade_date"].eq(deep_date), "low_price"] = 9.8

    approaches = build_first_support_approaches(features, waves)
    same_day = approaches.loc[approaches["approach_date"].eq(deep_date)]

    assert set(same_day["support_line"]) == {"ma5", "ma10", "ma20"}
    assert same_day.loc[same_day["execution_selected"], "support_line"].tolist() == [
        "ma20"
    ]


def _trade_features_and_waves() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bars = _single_wave_bars()
    features = build_stock_wave_features(bars)
    waves = build_leader_wave_ledger(bars, anchor_date=_anchor(bars))
    approaches = build_first_support_approaches(features, waves)
    return features, waves, approaches


def test_trade_exits_at_first_higher_high_and_reports_path() -> None:
    features, waves, approaches = _trade_features_and_waves()
    trades = build_wave_pullback_trades(approaches, features, waves)
    ma5 = trades.loc[
        trades["wave_number"].eq(1) & trades["support_line"].eq("ma5")
    ].iloc[0]

    assert ma5["executable_exit_reason"] == "higher_high_confirmed"
    assert ma5["exit_date"] == waves.iloc[0]["higher_high_date"]
    assert ma5["holding_sessions"] == 4
    assert ma5["gross_return_pct"] == pytest.approx(
        (ma5["exit_price"] / ma5["entry_price"] - 1.0) * 100.0
    )
    assert ma5["net_return_pct"] == pytest.approx(ma5["gross_return_pct"] - 0.2)
    assert ma5["maximum_adverse_excursion_pct"] < 0
    assert ma5["maximum_favorable_excursion_pct"] > 0
    assert bool(ma5["eventually_made_higher_high"])
    assert trades["maximum_adverse_excursion_pct"].le(0).all()
    assert trades["maximum_favorable_excursion_pct"].ge(0).all()


def test_structural_exit_can_precede_a_later_higher_high() -> None:
    features, waves, approaches = _trade_features_and_waves()
    entry_date = pd.Timestamp(approaches.iloc[0]["approach_date"])
    later = features.loc[features["trade_date"].gt(entry_date)].index[:2]
    features.loc[later, "close_price"] = features.loc[later, "ma20"] * 0.98
    trades = build_wave_pullback_trades(approaches, features, waves)
    trade = trades.loc[
        trades["wave_number"].eq(1) & trades["support_line"].eq("ma5")
    ].iloc[0]

    assert trade["executable_exit_reason"] == "two_closes_below_ma20"
    assert trade["exit_date"] < trade["unrestricted_higher_high_date"]
    assert bool(trade["defensive_exit_preceded_later_higher_high"])


def test_trade_is_right_censored_without_exit_event() -> None:
    features, waves, approaches = _trade_features_and_waves()
    unresolved = waves.iloc[[-1]].copy()
    unresolved["higher_high_date"] = pd.NaT
    unresolved["observation_end"] = approaches.iloc[0]["approach_date"]
    one = approaches.iloc[[0]].copy()
    one["wave_number"] = int(unresolved.iloc[0]["wave_number"])
    one["peak_price"] = float(unresolved.iloc[0]["peak_price"])

    trades = build_wave_pullback_trades(one, features, unresolved)

    assert trades.iloc[0]["executable_exit_reason"] == "right_censored"
    assert pd.isna(trades.iloc[0]["exit_date"])
    assert pd.isna(trades.iloc[0]["net_return_pct"])


def test_declared_continuation_trade_uses_prior_peak_and_anchor_close() -> None:
    bars = _declared_continuation_bars()
    features = build_stock_wave_features(bars)
    anchor_date = pd.Timestamp(bars.iloc[28]["trade_date"]).date()
    result = build_declared_continuation_trade(
        features,
        anchor_date=anchor_date,
    )

    assert result["strict_ignition"] is False
    assert result["reference_peak_date"] == pd.Timestamp(bars.iloc[25]["trade_date"])
    assert result["reference_peak_price"] == 12.0
    assert result["pre_anchor_trough_price"] == 10.8
    assert result["pre_anchor_pullback_pct"] == pytest.approx(-10.0)
    assert result["entry_date"] == pd.Timestamp(anchor_date)
    assert result["entry_price"] == 11.5
    assert result["exit_date"] == pd.Timestamp(bars.iloc[30]["trade_date"])
    assert result["executable_exit_reason"] == "prior_peak_rebroken"
    assert result["net_return_pct"] == pytest.approx((12.1 / 11.5 - 1.0) * 100.0 - 0.2)
    assert result["maximum_adverse_excursion_pct"] == pytest.approx(
        (11.2 / 11.5 - 1.0) * 100.0
    )


def test_declared_continuation_trade_ignores_prices_after_exit() -> None:
    bars = _declared_continuation_bars()
    features = build_stock_wave_features(bars)
    anchor_date = pd.Timestamp(bars.iloc[28]["trade_date"]).date()
    baseline = build_declared_continuation_trade(features, anchor_date=anchor_date)
    changed = bars.copy()
    changed.loc[changed.index > 30, [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
    ]] *= 3.0
    mutated = build_declared_continuation_trade(
        build_stock_wave_features(changed),
        anchor_date=anchor_date,
    )

    compared = (
        "reference_peak_date",
        "reference_peak_price",
        "pre_anchor_pullback_pct",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "net_return_pct",
        "maximum_adverse_excursion_pct",
        "maximum_favorable_excursion_pct",
    )
    assert {key: baseline[key] for key in compared} == {
        key: mutated[key] for key in compared
    }
