from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.event_neutral_days import (
    build_event_neutral_comparison_days,
    build_event_neutral_days,
)


def _calendar() -> tuple[date, ...]:
    return tuple(pd.date_range("2025-06-16", "2025-07-11", freq="B").date)


def _source_date() -> date:
    return date(2025, 7, 1)


def _recognition_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": _source_date(),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股份",
                "recognition_rank": 1,
            },
            {
                "event_id": 2,
                "source_date": date(2025, 7, 2),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股份",
                "recognition_rank": 1,
            },
        ]
    )


def _stock_bars() -> pd.DataFrame:
    rows = []
    for index, trade_date in enumerate(_calendar()):
        close_price = 10.0 + index * 0.1
        rows.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": close_price - 0.05,
                "high_price": close_price + 0.2,
                "low_price": close_price - 0.2,
                "close_price": close_price,
                "volume": 1_000.0,
            }
        )
    return pd.DataFrame(rows)


def _cycle_states(
    *,
    sector_id: str = "BK0963",
    cycle_id: str = "cycle-1",
    relative_percentile: float = 0.9,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "sector_id": sector_id,
                "definition": "breakout_trend",
                "in_cycle": True,
                "cycle_id": cycle_id,
                "relative_percentile": relative_percentile,
            }
            for trade_date in _calendar()
        ]
    )


def _timing() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_date": trade_date,
                "active_direction": "SILVER",
                "danger_state": "NORMAL",
                "market_phase": "recovery",
            }
            for trade_date in _calendar()
        ]
    )


def _build(
    candidates: pd.DataFrame | None = None,
    bars: pd.DataFrame | None = None,
    states: pd.DataFrame | None = None,
    *,
    discovery_end: date = date(2025, 7, 11),
) -> pd.DataFrame:
    return build_event_neutral_days(
        _recognition_candidates() if candidates is None else candidates,
        _stock_bars() if bars is None else bars,
        _cycle_states() if states is None else states,
        _timing(),
        trading_dates=_calendar(),
        discovery_end=discovery_end,
    )


def _build_comparison(
    candidates: pd.DataFrame | None = None,
    bars: pd.DataFrame | None = None,
    states: pd.DataFrame | None = None,
    *,
    discovery_end: date = date(2025, 7, 11),
) -> pd.DataFrame:
    return build_event_neutral_comparison_days(
        _recognition_candidates() if candidates is None else candidates,
        _stock_bars() if bars is None else bars,
        _cycle_states() if states is None else states,
        _timing(),
        trading_dates=_calendar(),
        discovery_end=discovery_end,
    )


def test_keeps_earliest_spell_and_all_five_neutral_offsets() -> None:
    result = _build()

    assert result["recognition_event_id"].tolist() == [1, 1, 1, 1, 1]
    assert result["spell_session_offset"].tolist() == [1, 2, 3, 4, 5]
    assert result["entry_date"].tolist() == list(
        pd.date_range("2025-07-02", "2025-07-08", freq="B").date
    )
    assert result["planned_exit_date"].iloc[-1] == date(2025, 7, 9)


def test_observation_day_cycle_close_is_not_used_for_same_day_eligibility() -> None:
    changed = _cycle_states()
    changed.loc[
        changed["trade_date"].eq(date(2025, 7, 4)),
        "cycle_id",
    ] = "cycle-2"

    result = _build(states=changed)

    assert 3 in set(result["spell_session_offset"])
    assert 4 not in set(result["spell_session_offset"])


def test_comparison_retains_d1_cycle_mismatch_as_non_main_rise() -> None:
    changed = _cycle_states()
    changed.loc[
        changed["trade_date"].eq(date(2025, 7, 4)),
        "cycle_id",
    ] = "cycle-2"

    result = _build_comparison(states=changed)

    same_day = result.loc[result["spell_session_offset"].eq(3)].iloc[0]
    next_day = result.loc[result["spell_session_offset"].eq(4)].iloc[0]
    assert bool(same_day["main_rise"])
    assert not bool(next_day["main_rise"])


def test_comparison_collision_prefers_exact_main_rise_spell() -> None:
    candidates = pd.concat(
        [
            _recognition_candidates().iloc[:1],
            _recognition_candidates().iloc[:1].assign(
                event_id=3,
                sector_id="BK9999",
                concept_name="低空经济",
                cycle_id="cycle-2",
            ),
        ],
        ignore_index=True,
    )
    non_main_rise_states = _cycle_states(
        sector_id="BK9999",
        cycle_id="different-cycle",
        relative_percentile=0.99,
    )
    states = pd.concat(
        [
            _cycle_states(relative_percentile=0.8),
            non_main_rise_states,
        ],
        ignore_index=True,
    )

    result = _build_comparison(candidates=candidates, states=states)

    assert result["sector_id"].eq("BK0963").all()
    assert result["main_rise"].astype(bool).all()
    assert not result.duplicated(["vt_symbol", "entry_date"]).any()


def test_supports_and_timing_are_frozen_at_previous_close() -> None:
    baseline = _build()
    changed_bars = _stock_bars()
    changed_bars.loc[
        changed_bars["trade_date"].eq(date(2025, 7, 2)),
        ["open_price", "high_price", "low_price", "close_price"],
    ] = [99.0, 100.0, 1.0, 88.0]
    changed = _build(bars=changed_bars)
    support_columns = [
        "signal_close",
        "previous_high",
        "ma5",
        "ma10",
        "active_direction",
    ]

    pd.testing.assert_series_equal(
        baseline.loc[0, support_columns],
        changed.loc[0, support_columns],
    )
    assert baseline.loc[0, "context_date"] == _source_date()


def test_observation_and_exit_stay_inside_discovery() -> None:
    result = _build(discovery_end=date(2025, 7, 4))

    assert result["spell_session_offset"].tolist() == [1, 2]


def test_cross_concept_collision_uses_previous_day_relative_strength() -> None:
    candidates = pd.concat(
        [
            _recognition_candidates().iloc[:1],
            _recognition_candidates().iloc[:1].assign(
                event_id=3,
                sector_id="BK9999",
                concept_name="低空经济",
                cycle_id="cycle-2",
            ),
        ],
        ignore_index=True,
    )
    states = pd.concat(
        [
            _cycle_states(relative_percentile=0.8),
            _cycle_states(
                sector_id="BK9999",
                cycle_id="cycle-2",
                relative_percentile=0.95,
            ),
        ],
        ignore_index=True,
    )

    result = _build(candidates=candidates, states=states)

    assert result["sector_id"].eq("BK9999").all()
    assert result["cycle_relative_percentile"].eq(0.95).all()


def test_outcome_columns_are_rejected() -> None:
    candidates = _recognition_candidates().assign(net_return_pct=9.0)

    with pytest.raises(ValueError, match="outcome"):
        _build(candidates=candidates)
