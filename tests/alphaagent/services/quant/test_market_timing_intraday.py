"""盘中实时 composite bar 合成的单元测试。

守护:
- 加权正确: 七大指数 change_pct 按 INDEX_WEIGHTS 加权, close = prev * (1+ret)
- 时段/数据源/成交量兜底: 非交易时段、拉取失败、volume=0 都返回 None(退化为昨日 panel)
"""

from __future__ import annotations

from datetime import date

import pytest

from alphaagent.market.models import Quote
from alphaagent.server.services.quant.market_timing import series as ser

_SEVEN = [
    "000001.SSE",
    "000300.SSE",
    "000905.SSE",
    "000852.SSE",
    "399001.SZSE",
    "399006.SZSE",
    "000688.SSE",
]


def _make_quote(vt: str, change_pct: float, volume: float = 1e8) -> Quote:
    sym, ex = vt.split(".")
    return Quote(
        symbol=sym,
        exchange=ex,
        vt_symbol=vt,
        name=vt,
        last_price=100.0 * (1 + change_pct / 100.0),
        change=None,
        change_pct=change_pct,
        open_price=100.0,
        high_price=101.0,
        low_price=99.0,
        previous_close=100.0,
        volume=volume,
        turnover=1e9,
        market_cap=None,
        pe=None,
        pb=None,
        turnover_rate=None,
        industry=None,
        area=None,
        trade_time=None,
        source="test",
    )


class _FakeClient:
    def __init__(self, quotes: list[Quote]) -> None:
        self._quotes = quotes

    def get_indices(self) -> list[Quote]:
        return self._quotes


class _FailingClient:
    def get_indices(self) -> list[Quote]:
        raise RuntimeError("upstream down")


def test_intraday_today_bar_weights_indices(monkeypatch):
    """盘中: 七大指数同涨 2% → 加权 ret=2%, close = prev * 1.02。"""
    monkeypatch.setattr(ser, "_is_intraday_china", lambda: True)
    monkeypatch.setattr(ser, "_china_today", lambda: date(2026, 7, 6))
    quotes = [_make_quote(vt, 2.0) for vt in _SEVEN]
    monkeypatch.setattr(ser, "RealMarketDataClient", lambda: _FakeClient(quotes))

    bar = ser.intraday_today_bar(prev_close=100.0, prev_turnover=1e9)
    assert bar is not None
    assert bar.trade_date == date(2026, 7, 6)
    assert abs(bar.return_pct - 2.0) < 1e-9
    assert abs(bar.close - 102.0) < 1e-6


def test_intraday_today_bar_weighted_mixed_changes(monkeypatch):
    """不同涨幅按权重加权(非简单平均)。上证+2%(w0.18), 科创50-1%(w0.08) 等。"""
    monkeypatch.setattr(ser, "_is_intraday_china", lambda: True)
    monkeypatch.setattr(ser, "_china_today", lambda: date(2026, 7, 6))
    # 上证涨 3%, 其余涨 1% → 加权 ret = 0.18*3 + 0.82*1 = 1.36
    pct = {vt: 1.0 for vt in _SEVEN}
    pct["000001.SSE"] = 3.0
    quotes = [_make_quote(vt, pct[vt]) for vt in _SEVEN]
    monkeypatch.setattr(ser, "RealMarketDataClient", lambda: _FakeClient(quotes))

    bar = ser.intraday_today_bar(prev_close=100.0, prev_turnover=1e9)
    assert bar is not None
    assert abs(bar.return_pct - 1.36) < 1e-9


def test_intraday_today_bar_returns_none_off_hours(monkeypatch):
    """非交易时段(周末/盘后): 直接返回 None, 不拉数据。"""
    monkeypatch.setattr(ser, "_is_intraday_china", lambda: False)
    assert ser.intraday_today_bar(100.0, 1e9) is None


def test_intraday_today_bar_none_when_fetch_fails(monkeypatch):
    """实时源拉取失败: 返回 None(调用方退化为昨日 panel)。"""
    monkeypatch.setattr(ser, "_is_intraday_china", lambda: True)
    monkeypatch.setattr(ser, "RealMarketDataClient", lambda: _FailingClient())
    assert ser.intraday_today_bar(100.0, 1e9) is None


def test_intraday_today_bar_none_when_all_volume_zero(monkeypatch):
    """所有指数 volume=0(节假日/半天/异常停牌): 返回 None。"""
    monkeypatch.setattr(ser, "_is_intraday_china", lambda: True)
    monkeypatch.setattr(ser, "_china_today", lambda: date(2026, 7, 6))
    quotes = [_make_quote(vt, 2.0, volume=0.0) for vt in _SEVEN]
    monkeypatch.setattr(ser, "RealMarketDataClient", lambda: _FakeClient(quotes))
    assert ser.intraday_today_bar(100.0, 1e9) is None


def test_intraday_today_bar_uses_previous_close_fallback(monkeypatch):
    """change_pct 缺失时, 用 last_price/previous_close 算 ret。"""
    monkeypatch.setattr(ser, "_is_intraday_china", lambda: True)
    monkeypatch.setattr(ser, "_china_today", lambda: date(2026, 7, 6))
    # change_pct=None, last=103, prev_close=100 → ret=3%
    quotes = [
        Quote(
            symbol=vt.split(".")[0], exchange=vt.split(".")[1], vt_symbol=vt, name=vt,
            last_price=103.0, change=None, change_pct=None, open_price=100.0,
            high_price=103.0, low_price=99.0, previous_close=100.0, volume=1e8,
            turnover=1e9, market_cap=None, pe=None, pb=None, turnover_rate=None,
            industry=None, area=None, trade_time=None, source="test",
        )
        for vt in _SEVEN
    ]
    monkeypatch.setattr(ser, "RealMarketDataClient", lambda: _FakeClient(quotes))
    bar = ser.intraday_today_bar(100.0, 1e9)
    assert bar is not None
    assert abs(bar.return_pct - 3.0) < 1e-9
