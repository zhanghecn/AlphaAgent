from __future__ import annotations

from datetime import date

import pandas as pd

from alphaagent.server.services.low_suction.leader_waves import (
    build_causal_wave_snapshot,
    build_leader_wave_ledger,
)


def _bars(path: list[tuple[float, float, float]]) -> pd.DataFrame:
    history_dates = pd.bdate_range("2024-11-25", periods=25)
    rows = [
        {
            "trade_date": trade_date,
            "open_price": 10.0,
            "high_price": 10.2,
            "low_price": 9.8,
            "close_price": 10.0,
            "volume": 1_000_000.0,
        }
        for trade_date in history_dates
    ]
    for offset, (high, low, close) in enumerate(path, start=1):
        rows.append(
            {
                "trade_date": history_dates[-1] + pd.offsets.BDay(offset),
                "open_price": close,
                "high_price": high,
                "low_price": low,
                "close_price": close,
                "volume": 1_000_000.0 + offset * 100_000.0,
            }
        )
    return pd.DataFrame(rows)


def _anchor(frame: pd.DataFrame) -> date:
    return pd.Timestamp(frame.iloc[25]["trade_date"]).date()


def _three_wave_bars() -> pd.DataFrame:
    return _bars(
        [
            (11.0, 10.0, 10.8),
            (12.0, 10.8, 11.8),
            (11.8, 11.2, 11.4),
            (12.5, 11.5, 12.3),
            (14.0, 12.4, 13.8),
            (13.5, 12.8, 13.0),
            (14.5, 13.0, 14.4),
        ]
    )


def test_wave_chain_requires_ordered_pullback_and_higher_high() -> None:
    bars = _three_wave_bars()
    rows = build_leader_wave_ledger(bars, anchor_date=_anchor(bars))

    assert rows["wave_number"].tolist() == [1, 2, 3]
    assert rows.iloc[0]["resolution_status"] == "continued_to_higher_high"
    assert rows.iloc[1]["resolution_status"] == "continued_to_higher_high"
    assert rows.iloc[2]["resolution_status"] == "open_at_observation_end"
    assert rows.iloc[0]["peak_price"] == 12.0
    assert rows.iloc[0]["trough_price"] == 11.2
    assert rows.iloc[0]["higher_high_price"] == 12.5


def test_same_day_high_low_cannot_confirm_a_new_wave() -> None:
    bars = _bars([(12.0, 10.0, 11.5), (11.9, 11.4, 11.7)])
    rows = build_leader_wave_ledger(bars, anchor_date=_anchor(bars))

    assert len(rows) == 1
    assert rows.iloc[0]["resolution_status"] == "open_at_observation_end"


def test_unresolved_final_pullback_with_structure_break_is_preserved() -> None:
    bars = _bars(
        [
            (12.0, 10.5, 11.8),
            (11.7, 10.9, 11.0),
            (10.8, 9.5, 9.7),
            (10.0, 9.0, 9.2),
        ]
    )
    rows = build_leader_wave_ledger(bars, anchor_date=_anchor(bars))

    assert len(rows) == 1
    assert rows.iloc[-1]["resolution_status"] == "terminal_failure_observed"
    assert pd.notna(rows.iloc[-1]["trough_date"])
    assert pd.notna(rows.iloc[-1]["structural_break_date"])


def test_unresolved_pullback_without_structure_break_is_censored() -> None:
    bars = _bars([(12.0, 10.5, 11.8), (11.8, 11.3, 11.6)])
    rows = build_leader_wave_ledger(bars, anchor_date=_anchor(bars))

    assert rows.iloc[-1]["resolution_status"] == "unresolved_pullback_censored"


def test_causal_snapshot_is_invariant_to_bars_after_cutoff() -> None:
    bars = _three_wave_bars()
    cutoff = pd.Timestamp(bars.iloc[28]["trade_date"]).date()
    baseline = build_causal_wave_snapshot(
        bars,
        anchor_date=_anchor(bars),
        cutoff_date=cutoff,
    )
    changed = bars.copy()
    future = pd.to_datetime(changed["trade_date"]).dt.date > cutoff
    changed.loc[future, ["open_price", "high_price", "low_price", "close_price"]] = [
        1.0,
        1.1,
        0.9,
        1.0,
    ]

    assert build_causal_wave_snapshot(
        changed,
        anchor_date=_anchor(changed),
        cutoff_date=cutoff,
    ) == baseline
    assert baseline["current_wave_number"] == 2
    assert baseline["feature_cutoff_date"] == cutoff.isoformat()
