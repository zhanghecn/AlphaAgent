from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from alphaagent.server.services.low_suction.support_day_entry_variant_study import (
    STUDY_VERSION,
    build_support_day_entry_signals,
    execute_support_day_entry_trades,
)


START = date(2026, 7, 1)


def _day(offset: int) -> date:
    return START + timedelta(days=offset)


def _bar(offset: int, close: float, *, high: float | None = None, low: float | None = None,
         active: bool = True, intact: bool = True) -> dict[str, object]:
    return {
        "campaign_id": "camp-1",
        "sector_id": "BK_TEST",
        "concept_name": "测试概念",
        "vt_symbol": "600001.SSE",
        "stock_name": "测试龙头",
        "trade_date": _day(offset),
        "open_price": close,
        "high_price": high if high is not None else close,
        "low_price": low if low is not None else close,
        "close_price": close,
        "campaign_active": active,
        "structure_intact": intact,
    }


def _paths(*bars: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(bars)


def _signal(**overrides) -> dict[str, object]:
    base = {
        "signal_id": "camp-1:600001.SSE:2026-07-01:ma5",
        "campaign_id": "camp-1",
        "sector_id": "BK_TEST",
        "concept_name": "测试概念",
        "vt_symbol": "600001.SSE",
        "stock_name": "测试龙头",
        "signal_date": _day(0),
        "entry_price": 10.0,
        "wave_number": 1,
        "support_line": "ma5",
        "support_depth": 1,
        "support_price": 9.9,
        "reference_peak_price": 10.5,
        "dynamic_rank": 1,
        "market_phase": "warming",
    }
    base.update(overrides)
    return base


def _opportunity(**overrides) -> dict[str, object]:
    base = {
        "opportunity_id": "camp-1:600001.SSE:2026-07-01:ma5",
        "campaign_id": "camp-1",
        "sector_id": "BK_TEST",
        "concept_name": "测试概念",
        "vt_symbol": "600001.SSE",
        "stock_name": "测试龙头",
        "entry_date": _day(0),
        "entry_price": 10.0,
        "wave_number": 1,
        "support_line": "ma5",
        "ma5": 9.9,
        "ma10": 9.5,
        "prior_high20": 10.5,
        "dynamic_rank": 1,
    }
    base.update(overrides)
    return base


def _timing(direction: str = "GOLD", danger: str = "NORMAL", phase: str = "warming") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_date": _day(0),
                "active_direction": direction,
                "danger_state": danger,
                "market_phase": phase,
            }
        ]
    )


class TestBuildSupportDayEntrySignals:
    def test_support_price_comes_from_the_required_line(self) -> None:
        signals = build_support_day_entry_signals(
            pd.DataFrame([_opportunity(support_line="ma10")]),
            _timing(),
        )
        assert len(signals) == 1
        assert signals.iloc[0]["support_price"] == 9.5
        assert signals.iloc[0]["support_depth"] == 2
        assert signals.iloc[0]["reference_peak_price"] == 10.5

    def test_non_gold_or_danger_or_retreat_are_excluded(self) -> None:
        opportunities = pd.DataFrame([_opportunity()])
        assert build_support_day_entry_signals(opportunities, _timing(direction="SILVER")).empty
        assert build_support_day_entry_signals(opportunities, _timing(danger="DANGER")).empty
        assert build_support_day_entry_signals(opportunities, _timing(phase="retreat")).empty

    def test_tradable_phases_pass(self) -> None:
        for phase in ("uptrend", "warming", "rotation"):
            signals = build_support_day_entry_signals(
                pd.DataFrame([_opportunity()]),
                _timing(phase=phase),
            )
            assert len(signals) == 1, phase

    def test_study_version_is_frozen(self) -> None:
        assert STUDY_VERSION == "support-day-entry-variant-v1"


class TestExecuteSupportDayEntryTrades:
    def test_close_below_support_exits_as_support_broken(self) -> None:
        paths = _paths(
            _bar(0, 10.0),
            _bar(1, 9.85),
        )
        trades = execute_support_day_entry_trades(pd.DataFrame([_signal()]), paths)
        trade = trades.iloc[0]
        assert trade["exit_reason"] == "support_broken"
        assert trade["exit_price"] == 9.85
        assert trade["net_return_pct"] == round((9.85 / 10.0 - 1.0) * 100.0 - 0.2, 4)
        assert trade["holding_sessions"] == 1

    def test_winner_exit_on_reference_peak_rebreak(self) -> None:
        paths = _paths(
            _bar(0, 10.0),
            _bar(1, 10.1, high=10.2),
            _bar(2, 10.4, high=10.6),
        )
        trades = execute_support_day_entry_trades(pd.DataFrame([_signal()]), paths)
        trade = trades.iloc[0]
        assert trade["exit_reason"] == "higher_high_confirmed"
        assert trade["exit_price"] == 10.4
        assert trade["holding_sessions"] == 2

    def test_support_break_wins_over_same_bar_peak_touch(self) -> None:
        paths = _paths(
            _bar(0, 10.0),
            _bar(1, 9.8, high=10.6),
        )
        trades = execute_support_day_entry_trades(pd.DataFrame([_signal()]), paths)
        assert trades.iloc[0]["exit_reason"] == "support_broken"

    def test_structure_break_exits(self) -> None:
        paths = _paths(
            _bar(0, 10.0),
            _bar(1, 10.05, intact=False),
        )
        trades = execute_support_day_entry_trades(pd.DataFrame([_signal()]), paths)
        assert trades.iloc[0]["exit_reason"] == "structural_break"

    def test_campaign_end_exits(self) -> None:
        paths = _paths(
            _bar(0, 10.0),
            _bar(1, 10.05, active=False),
        )
        trades = execute_support_day_entry_trades(pd.DataFrame([_signal()]), paths)
        assert trades.iloc[0]["exit_reason"] == "concept_campaign_ended"

    def test_right_censored_when_no_trigger(self) -> None:
        paths = _paths(
            _bar(0, 10.0),
            _bar(1, 10.05),
        )
        trades = execute_support_day_entry_trades(pd.DataFrame([_signal()]), paths)
        trade = trades.iloc[0]
        assert trade["exit_reason"] == "right_censored"
        assert pd.isna(trade["exit_date"])
        assert trade["net_return_pct"] is None

    def test_stop_is_not_checked_on_the_entry_day(self) -> None:
        # 入场日收盘已略低于支撑线,次日收回上方:不应在入场日止损
        paths = _paths(
            _bar(0, 9.95),
            _bar(1, 10.05),
            _bar(2, 10.4, high=10.6),
        )
        trades = execute_support_day_entry_trades(
            pd.DataFrame([_signal(entry_price=9.95, support_price=10.0)]),
            paths,
        )
        trade = trades.iloc[0]
        assert trade["exit_reason"] == "higher_high_confirmed"
        assert trade["holding_sessions"] == 2

    def test_d1_fields_are_populated(self) -> None:
        paths = _paths(
            _bar(0, 10.0),
            _bar(1, 10.1, high=10.2),
            _bar(2, 10.4, high=10.6),
        )
        trades = execute_support_day_entry_trades(pd.DataFrame([_signal()]), paths)
        trade = trades.iloc[0]
        assert trade["d1_date"] == pd.Timestamp(_day(1))
        assert trade["d1_close"] == 10.1
        assert trade["d1_net_return_pct"] == round((10.1 / 10.0 - 1.0) * 100.0 - 0.2, 4)
