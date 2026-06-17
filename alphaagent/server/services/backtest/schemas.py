"""Shared data structures for AlphaAgent backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards
from alphaagent.server.services.backtest import execution_models
from alphaagent.server.services.quant.factors import STRATEGY_ID


@dataclass
class BacktestParams:
    strategy: str = STRATEGY_ID
    start: date = date(2020, 1, 1)
    end: date | None = None
    initial_cash: float = 1_000_000
    max_positions: int = 10
    max_position_pct: float = 0.125
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    slippage_bps: float = 10
    stop_loss_pct: float = 0.07
    take_profit_pct: float = 0.18
    trailing_stop_pct: float = 0.08
    time_stop_days: int = 15
    candidate_limit: int = 20
    max_symbols: int = 5000
    min_entry_score: float = 68.0
    strict_entry: bool = True
    execution_model: str = "legacy_next_open"
    intraday_entry: bool = False
    minute_entry_required: bool = False
    minute_interval: str = "1m"
    tail_entry_start: str = "14:30"
    tail_entry_end: str = "14:30"
    tail_entry_ma5_tolerance_pct: float = 1.5
    enable_signal_rotation: bool = True
    rotation_min_score: float = 98.0
    rotation_min_score_gap: float = 8.0
    rotation_max_holding_return_pct: float = 3.0
    rotation_min_holding_days: int = 3
    persist: bool = False
    symbols: list[str] | None = None
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS

    def __post_init__(self) -> None:
        self.included_boards = normalize_included_boards(self.included_boards)
        self.execution_model = execution_models.normalize_execution_model(self.execution_model)
        self.minute_interval = execution_models.normalize_backtest_minute_interval(self.minute_interval)
        if self.execution_model == "strict_1430":
            self.intraday_entry = True
            self.minute_entry_required = True


@dataclass(frozen=True)
class MinuteBar:
    bar_time: datetime
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float | None = None
    turnover: float | None = None


@dataclass
class Position:
    vt_symbol: str
    name: str | None
    volume: int
    cost_price: float
    entry_date: date
    highest_price: float
    reason: dict[str, Any]
    last_price: float | None = None


@dataclass
class Trade:
    trade_date: date
    vt_symbol: str
    side: str
    price: float
    volume: int
    amount: float
    fee: float
    pnl: float | None = None
    reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreContext:
    financial_rows_by_symbol: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
