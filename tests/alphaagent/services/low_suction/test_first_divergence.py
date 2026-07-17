from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.first_divergence import (
    build_first_divergence_candidates,
)
from alphaagent.server.services.low_suction.cli import build_parser


def _recognition_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 7, 1),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "recognition_rank": 1,
            },
            {
                "event_id": 2,
                "source_date": date(2025, 7, 2),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "recognition_rank": 1,
            },
        ]
    )


def _calendar() -> tuple[date, ...]:
    return tuple(pd.date_range("2025-07-01", "2025-07-11", freq="B").date)


def _stock_bars(*, first_negative_offset: int = 2) -> pd.DataFrame:
    dates = _calendar()
    closes = [10.0]
    for index in range(1, len(dates)):
        previous = closes[-1]
        closes.append(previous - 0.2 if index == first_negative_offset else previous + 0.1)
    return pd.DataFrame(
        {
            "vt_symbol": "600001.SSE",
            "trade_date": dates,
            "close_price": closes,
            "volume": 1_000.0,
        }
    )


def _cycle_states(*, cycle_id: str = "cycle-1") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "sector_id": "BK0963",
                "definition": "breakout_trend",
                "in_cycle": True,
                "cycle_id": cycle_id,
                "relative_percentile": 0.9,
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


def test_first_divergence_keeps_earliest_spell_and_first_negative_close() -> None:
    result = build_first_divergence_candidates(
        _recognition_candidates(),
        _stock_bars(first_negative_offset=2),
        _cycle_states(),
        _timing(),
        trading_dates=_calendar(),
        discovery_end=date(2025, 7, 11),
    )

    assert len(result) == 1
    assert result.loc[0, "event_id"] == 1
    assert result.loc[0, "recognition_source_date"] == date(2025, 7, 1)
    assert result.loc[0, "source_date"] == date(2025, 7, 3)
    assert result.loc[0, "divergence_date"] == date(2025, 7, 3)
    assert result.loc[0, "entry_date"] == date(2025, 7, 4)
    assert result.loc[0, "planned_exit_date"] == date(2025, 7, 7)
    assert result.loc[0, "active_direction"] == "SILVER"


def test_negative_close_after_five_sessions_is_rejected() -> None:
    result = build_first_divergence_candidates(
        _recognition_candidates().iloc[:1],
        _stock_bars(first_negative_offset=6),
        _cycle_states(),
        _timing(),
        trading_dates=_calendar(),
        discovery_end=date(2025, 7, 11),
    )

    assert result.empty


def test_first_negative_close_outside_same_cycle_rejects_spell() -> None:
    states = _cycle_states()
    states.loc[states["trade_date"].eq(date(2025, 7, 3)), "cycle_id"] = "cycle-2"

    result = build_first_divergence_candidates(
        _recognition_candidates().iloc[:1],
        _stock_bars(first_negative_offset=2),
        states,
        _timing(),
        trading_dates=_calendar(),
        discovery_end=date(2025, 7, 11),
    )

    assert result.empty


def test_observation_and_exit_must_remain_inside_discovery() -> None:
    result = build_first_divergence_candidates(
        _recognition_candidates().iloc[:1],
        _stock_bars(first_negative_offset=4),
        _cycle_states(),
        _timing(),
        trading_dates=_calendar(),
        discovery_end=date(2025, 7, 7),
    )

    assert result.empty


def test_cross_concept_collision_keeps_strongest_divergence_state() -> None:
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
            _cycle_states().assign(relative_percentile=0.8),
            _cycle_states(cycle_id="cycle-2").assign(
                sector_id="BK9999",
                relative_percentile=0.95,
            ),
        ],
        ignore_index=True,
    )

    result = build_first_divergence_candidates(
        candidates,
        _stock_bars(first_negative_offset=2),
        states,
        _timing(),
        trading_dates=_calendar(),
        discovery_end=date(2025, 7, 11),
    )

    assert len(result) == 1
    assert result.loc[0, "event_id"] == 3
    assert result.loc[0, "sector_id"] == "BK9999"
    assert result.loc[0, "relative_percentile"] == pytest.approx(0.95)


def test_market_timing_is_frozen_at_divergence_close() -> None:
    timing = _timing()
    timing.loc[timing["source_date"].eq(date(2025, 7, 1)), "active_direction"] = "GOLD"
    timing.loc[timing["source_date"].eq(date(2025, 7, 3)), "active_direction"] = "SILVER"

    result = build_first_divergence_candidates(
        _recognition_candidates().iloc[:1],
        _stock_bars(first_negative_offset=2),
        _cycle_states(),
        timing,
        trading_dates=_calendar(),
        discovery_end=date(2025, 7, 11),
    )

    assert result.loc[0, "active_direction"] == "SILVER"


def test_outcome_columns_are_rejected_from_candidate_discovery() -> None:
    candidates = _recognition_candidates().iloc[:1].assign(net_return_pct=8.0)

    with pytest.raises(ValueError, match="outcome"):
        build_first_divergence_candidates(
            candidates,
            _stock_bars(first_negative_offset=2),
            _cycle_states(),
            _timing(),
            trading_dates=_calendar(),
            discovery_end=date(2025, 7, 11),
        )


def test_candidate_audit_cli_exposes_no_research_parameters() -> None:
    args = build_parser().parse_args(
        ["v2-first-divergence-audit", "--format", "json"]
    )

    assert args.command == "v2-first-divergence-audit"
    assert not hasattr(args, "horizon")
    assert not hasattr(args, "start")
    assert not hasattr(args, "end")
