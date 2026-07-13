from __future__ import annotations

from datetime import date

from alphaagent.server.db import schema
from alphaagent.server.services.backtest import engine, queries
from alphaagent.server.services.quant import screening_loaders, strategy_replay
from alphaagent.server.services.quant.factors import Bar


class _MappingResult:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def mappings(self) -> _MappingResult:
        return self

    def all(self) -> list[dict[str, object]]:
        return [self.row]


class _Session:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def execute(self, _statement: object) -> _MappingResult:
        return _MappingResult(self.row)


def test_daily_bar_loaders_preserve_turnover_rate_and_positional_change_pct() -> None:
    trade_date = date(2026, 7, 10)
    vt_symbol = "600000.SSE"
    row: dict[str, object] = {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "open_price": 10.0,
        "high_price": 11.0,
        "low_price": 9.9,
        "close_price": 10.8,
        "volume": 1_000_000.0,
        "turnover": 108_000_000.0,
        "change_pct": 8.0,
        "turnover_rate": 7.25,
    }
    session = _Session(row)

    loaded_bars = [
        engine._daily_bar_from_mapping(row),
        engine._load_all_bars(session, [vt_symbol], trade_date, trade_date)[vt_symbol][0],
        queries._daily_bars_by_symbol(session, schema, [vt_symbol], trade_date, trade_date)[vt_symbol][0],
        screening_loaders.load_bars(session, [vt_symbol], trade_date, lookback_days=1)[vt_symbol][0],
        strategy_replay._load_all_bars(session, [vt_symbol], trade_date, trade_date)[vt_symbol][0],
    ]

    assert {(bar.change_pct, bar.turnover_rate) for bar in loaded_bars} == {(8.0, 7.25)}

    positional_bar = Bar(trade_date, 10.0, 11.0, 9.9, 10.8, 1_000_000.0, 108_000_000.0, 8.0)
    assert positional_bar.change_pct == 8.0
    assert positional_bar.turnover_rate is None
