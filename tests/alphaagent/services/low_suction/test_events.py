from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.events import build_daily_discovery_events

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _row(**overrides: object) -> dict[str, object]:
    cutoff = datetime(2026, 7, 15, 15, 0, tzinfo=SHANGHAI)
    values: dict[str, object] = {
        "sector_id": "THEME_A",
        "concept_name": "算力",
        "trade_date": "2026-07-15",
        "cutoff": cutoff,
        "vt_symbol": "600000.SSE",
        "rank": 1,
        "is_top3": True,
        "state": "MAIN_RISE_CONFIRMED",
        "rise_cycle_id": "THEME_A:2026-07-01",
        "evidence_level": "membership_proxy",
        "open_price": 10.2,
        "close_price": 9.8,
        "previous_close": 10.0,
        "ma5": 9.6,
        "ma10": 9.5,
        "volume_ratio_5d": 0.8,
        "return_10d_pct": 12.0,
        "prior_strong_day": True,
        "sessions_since_peak": 3,
        "drawdown_from_peak_pct": -5.0,
        "concept_strength_score": 90.0,
        "leader_score": 0.9,
    }
    values.update(overrides)
    return values


def test_overlapping_families_merge_into_one_event() -> None:
    events = build_daily_discovery_events(pd.DataFrame([_row()]))

    assert len(events) == 1
    assert events.iloc[0]["family_tags"] == (
        "first_bearish_or_break_repair",
        "first_divergence",
        "second_wave_pullback",
    )
    assert events.iloc[0]["evidence_level"] == "membership_proxy"


def test_non_top3_and_non_main_rise_rows_are_excluded() -> None:
    rows = [
        _row(vt_symbol="600001.SSE", is_top3=False, rank=4),
        _row(
            vt_symbol="600002.SSE",
            state="NOT_MAIN_RISE",
            rise_cycle_id=None,
        ),
    ]

    events = build_daily_discovery_events(pd.DataFrame(rows))

    assert events.empty


def test_adjacent_signals_in_one_rise_cycle_keep_first_event() -> None:
    first = _row()
    second = _row(
        trade_date="2026-07-16",
        cutoff=first["cutoff"] + timedelta(days=1),
        close_price=9.7,
    )

    events = build_daily_discovery_events(pd.DataFrame([second, first]))

    assert len(events) == 1
    assert events.iloc[0]["trade_date"] == pd.Timestamp("2026-07-15")


def test_same_stock_same_cutoff_uses_strongest_concept() -> None:
    rows = [
        _row(sector_id="WEAK", concept_name="弱概念", concept_strength_score=70.0),
        _row(sector_id="STRONG", concept_name="强概念", concept_strength_score=95.0),
    ]

    events = build_daily_discovery_events(pd.DataFrame(rows))

    assert len(events) == 1
    assert events.iloc[0]["sector_id"] == "STRONG"
    assert events.iloc[0]["related_concepts"] == ("STRONG", "WEAK")


def test_future_rows_and_prices_cannot_change_prior_event_identity() -> None:
    prior = pd.DataFrame([_row()])
    original = build_daily_discovery_events(prior)
    future = _row(
        trade_date="2026-07-20",
        cutoff=prior.iloc[0]["cutoff"] + timedelta(days=5),
        close_price=100.0,
        rise_cycle_id="THEME_A:2026-07-20",
    )

    combined = build_daily_discovery_events(
        pd.concat([prior, pd.DataFrame([future])], ignore_index=True)
    )
    prior_again = combined.loc[combined["trade_date"] == pd.Timestamp("2026-07-15")]

    assert prior_again.iloc[0]["event_id"] == original.iloc[0]["event_id"]
    assert prior_again.iloc[0]["family_tags"] == original.iloc[0]["family_tags"]


def test_frozen_theme_taxonomy_version_is_part_of_formal_event_identity() -> None:
    first = build_daily_discovery_events(
        pd.DataFrame([_row(theme_eligibility_version="theme-v1")])
    )
    second = build_daily_discovery_events(
        pd.DataFrame([_row(theme_eligibility_version="theme-v2")])
    )

    assert first.iloc[0]["theme_eligibility_version"] == "theme-v1"
    assert first.iloc[0]["event_id"] != second.iloc[0]["event_id"]


@pytest.mark.parametrize(
    "column",
    ["future_d1_return", "outcome_win", "mfe_5d", "mae_5d", "exit_d3"],
)
def test_outcome_columns_are_rejected(column: str) -> None:
    frame = pd.DataFrame([_row()])
    frame[column] = 1.0

    with pytest.raises(ValueError, match="outcome columns"):
        build_daily_discovery_events(frame)


def test_second_wave_requires_support_and_volume_contraction() -> None:
    row = _row(
        open_price=10.0,
        close_price=10.1,
        previous_close=10.0,
        prior_strong_day=False,
        return_10d_pct=1.0,
        volume_ratio_5d=1.5,
    )

    assert build_daily_discovery_events(pd.DataFrame([row])).empty
