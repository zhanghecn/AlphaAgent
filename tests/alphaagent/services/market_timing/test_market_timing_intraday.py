"""盘中实时 composite bar 合成的单元测试。

守护:
- 加权正确: 七大指数 change_pct 按 INDEX_WEIGHTS 加权, close = prev * (1+ret)
- 时段/数据源/成交量兜底: 非交易时段、拉取失败、volume=0 都返回 None(退化为昨日 panel)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

import pytest

from alphaagent.market.models import Quote
from alphaagent.server.services.market_timing import factors as fac
from alphaagent.server.services.market_timing import panel as mt_panel
from alphaagent.server.services.market_timing import series as ser
from alphaagent.server.services.market_timing import signal as sig

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


class _FakeIndexClient:
    def __init__(self, detail: dict) -> None:
        self._detail = detail

    def index_detail(self, symbol: str, exchange: str) -> dict:
        assert symbol == "000001"
        assert exchange == "SSE"
        return self._detail


@dataclass(frozen=True)
class _DatedContext:
    trade_date: date
    source: str = "daily"


def _factor(day: date, zone: str) -> fac.MarketTimingFactors:
    bull, bear = {
        "GOLD": (70.0, 40.0),
        "SILVER": (40.0, 70.0),
        "NEUTRAL": (50.0, 50.0),
    }[zone]
    return fac.MarketTimingFactors(
        trade_date=day,
        phase="warming" if zone == "GOLD" else "retreat",
        trend=bull,
        momentum=bull,
        breadth=bull,
        structure=50.0,
        volume=50.0,
        bull_force=bull,
        bear_force=bear,
        close_above_ma20=zone == "GOLD",
        mom_5d=None,
        mom_20d=None,
        macd_top=40.0,
        breadth_top=40.0,
        evidence={},
    )


def _structural_factor(day: date) -> fac.MarketTimingFactors:
    return replace(
        _factor(day, "NEUTRAL"),
        phase="rotation",
        bull_force=55.6,
        bear_force=75.4,
        macd_top=80.0,
        breadth_top=82.0,
        evidence={"trend_breakdown": 83.0},
    )


def _structural_panel_case() -> tuple[
    list[fac.MarketTimingFactors],
    list[float],
    list[float | None],
]:
    start = date(2026, 3, 13) - timedelta(days=20)
    closes = [100.0] * 20 + [99.0, 99.1, 98.7, 99.0, 101.0]
    factors = [
        _factor(start + timedelta(days=index), "NEUTRAL")
        for index in range(len(closes))
    ]
    factors[20] = _structural_factor(factors[20].trade_date)
    factors[22] = _structural_factor(factors[22].trade_date)
    up_ratios: list[float | None] = [1.0] * 20 + [0.0, 4 / 7, 0.0, 1.0, 1.0]
    return factors, closes, up_ratios


def _gold_failure_panel_case() -> tuple[
    list[fac.MarketTimingFactors],
    list[float],
    list[float | None],
]:
    start = date(2026, 6, 29)
    factors = [
        _factor(start, "GOLD"),
        _factor(start + timedelta(days=1), "NEUTRAL"),
        _factor(start + timedelta(days=2), "GOLD"),
        replace(
            _factor(start + timedelta(days=3), "NEUTRAL"),
            bull_force=55.0,
            bear_force=56.0,
        ),
    ]
    return factors, [100.0, 101.0, 102.0, 98.0], [1.0, 1.0, 1.0, 0.0]


def _signal(
    day: date,
    direction: str,
    status: str = sig.STATUS_CONFIRMED,
    confirm_date: date | None = None,
    setup_type: str | None = None,
) -> sig.TimingSignal:
    return sig.TimingSignal(
        trade_date=day,
        direction=direction,
        status=status,
        grade="WEAK",
        bull_force=70.0 if direction == "GOLD" else 40.0,
        bear_force=40.0 if direction == "GOLD" else 70.0,
        phase="warming" if direction == "GOLD" else "retreat",
        setup_type=(
            setup_type
            or (
                sig.SETUP_TREND_GOLD
                if direction == "GOLD"
                else sig.SETUP_TOP_SILVER
            )
        ),
        confirm_date=confirm_date,
        reasons=[],
    )


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


def test_intraday_today_bar_tracks_index_up_ratio(monkeypatch):
    monkeypatch.setattr(ser, "_is_intraday_china", lambda: True)
    monkeypatch.setattr(ser, "_china_today", lambda: date(2026, 7, 6))
    changes = [1.0, 1.0, 1.0, 1.0, -1.0, -1.0, -1.0]
    quotes = [
        _make_quote(vt_symbol, change_pct)
        for vt_symbol, change_pct in zip(_SEVEN, changes, strict=True)
    ]
    monkeypatch.setattr(ser, "RealMarketDataClient", lambda: _FakeClient(quotes))

    bar = ser.intraday_today_bar(prev_close=100.0, prev_turnover=1e9)

    assert bar is not None
    assert bar.up_ratio == pytest.approx(4 / 7)


def test_intraday_today_bar_returns_none_off_hours(monkeypatch):
    """非交易时段(周末/盘后): 直接返回 None, 不拉数据。"""
    monkeypatch.setattr(ser, "_is_intraday_china", lambda: False)
    assert ser.intraday_today_bar(100.0, 1e9) is None


def test_panel_database_freshness_is_bounded_during_session(monkeypatch):
    monkeypatch.setattr(mt_panel, "_is_intraday_china", lambda: True)
    assert (
        mt_panel._panel_fresh_seconds()
        == mt_panel.PANEL_FRESH_INTRADAY_SECONDS
    )

    monkeypatch.setattr(mt_panel, "_is_intraday_china", lambda: False)
    assert (
        mt_panel._panel_fresh_seconds()
        == mt_panel.PANEL_FRESH_OFF_HOURS_SECONDS
    )


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


def test_panel_overlay_appends_today_index_bar_after_close(monkeypatch):
    """盘后日线未同步时, /market 主图仍用今天实时快照补到今天。"""
    monkeypatch.setattr(mt_panel, "_is_live_today_overlay_window", lambda: True)
    monkeypatch.setattr(mt_panel, "_is_intraday_china", lambda now=None: False)
    monkeypatch.setattr(mt_panel, "_china_today", lambda: date(2026, 7, 9))
    monkeypatch.setattr(
        mt_panel,
        "RealMarketDataClient",
        lambda: _FakeIndexClient(
            {
                "last_price": 103.0,
                "open_price": 99.0,
                "high_price": 104.0,
                "low_price": 98.0,
                "volume": 10_000.0,
                "turnover": 2_000_000.0,
            }
        ),
    )

    base_panel = {
        "overview": {
            "latest_date": "2026-07-08",
            "factor_date": "2026-07-08",
            "quote_date": "2026-07-08",
            "index_close": 100.0,
            "index_change_pct": 0.0,
        },
        "chart": {
            "bars": [
                {
                    "date": "2026-07-08",
                    "open": 99.0,
                    "high": 101.0,
                    "low": 98.0,
                    "close": 100.0,
                    "volume": 9_000.0,
                    "turnover": 1_000_000.0,
                }
            ],
        },
    }

    panel = mt_panel._overlay_intraday(base_panel)

    assert base_panel["chart"]["bars"][-1]["date"] == "2026-07-08"
    assert panel["chart"]["bars"][-1] == {
        "date": "2026-07-09",
        "open": 99.0,
        "high": 104.0,
        "low": 98.0,
        "close": 103.0,
        "volume": 10_000.0,
        "turnover": 2_000_000.0,
    }
    assert panel["overview"]["latest_date"] == "2026-07-08"
    assert panel["overview"]["factor_date"] == "2026-07-08"
    assert panel["overview"]["quote_date"] == "2026-07-09"
    assert panel["overview"]["index_close"] == 103.0
    assert panel["overview"]["index_change_pct"] == 3.0
    assert panel["overview"]["is_intraday"] is False
    assert panel["overview"]["is_live_snapshot"] is True


def test_panel_overlay_replaces_existing_today_index_bar(monkeypatch):
    """缓存里已有今天主图时, 实时 overlay 应替换而不是追加重复日期。"""
    monkeypatch.setattr(mt_panel, "_is_live_today_overlay_window", lambda: True)
    monkeypatch.setattr(mt_panel, "_is_intraday_china", lambda now=None: True)
    monkeypatch.setattr(mt_panel, "_china_today", lambda: date(2026, 7, 9))
    monkeypatch.setattr(
        mt_panel,
        "RealMarketDataClient",
        lambda: _FakeIndexClient(
            {
                "last_price": 105.0,
                "open_price": 101.0,
                "high_price": 106.0,
                "low_price": 100.0,
                "volume": 20_000.0,
                "amount": 3_000_000.0,
            }
        ),
    )

    panel = mt_panel._overlay_intraday(
        {
            "overview": {"latest_date": "2026-07-09"},
            "chart": {
                "bars": [
                    {"date": "2026-07-08", "close": 100.0},
                    {"date": "2026-07-09", "close": 102.0},
                ],
            },
        }
    )

    assert [bar["date"] for bar in panel["chart"]["bars"]] == ["2026-07-08", "2026-07-09"]
    assert panel["chart"]["bars"][-1]["close"] == 105.0
    assert panel["chart"]["bars"][-1]["turnover"] == 3_000_000.0
    assert panel["overview"]["is_intraday"] is True


def test_carried_intraday_context_uses_target_trade_date():
    previous = _DatedContext(date(2026, 7, 10))

    carried = mt_panel._carry_context_to_date(previous, date(2026, 7, 13))

    assert carried.trade_date == date(2026, 7, 13)
    assert carried.source == previous.source
    assert previous.trade_date == date(2026, 7, 10)


def test_timing_series_carries_confirmed_direction_through_neutral_zones():
    start = date(2026, 6, 11)
    factors = [
        _factor(start + timedelta(days=index), "GOLD" if index == 0 else "NEUTRAL")
        for index in range(5)
    ]
    events = [
        _signal(
            start,
            "GOLD",
            confirm_date=start + timedelta(days=1),
        ),
        _signal(
            start + timedelta(days=3),
            "SILVER",
            status=sig.STATUS_PENDING,
        ),
    ]

    rows = mt_panel._build_timing_series(factors, events)

    assert [row["active_direction"] for row in rows] == [
        "NEUTRAL",
        "GOLD",
        "GOLD",
        "GOLD",
        "GOLD",
    ]
    assert rows[-1]["zone_direction"] == "NEUTRAL"


def test_overview_uses_active_direction_instead_of_latest_candidate_zone():
    day = date(2026, 7, 15)
    latest = _factor(day, "NEUTRAL")
    gold = _signal(
        date(2026, 6, 11),
        "GOLD",
        confirm_date=date(2026, 6, 12),
    )
    overview = mt_panel._build_overview(
        latest,
        gold,
        [
            {"date": "2026-07-14", "close": 100.0},
            {"date": str(day), "close": 99.0},
        ],
        "GOLD",
        sig.DANGER,
    )

    assert overview["current_direction"] == "GOLD"
    assert overview["latest_signal"]["confirm_date"] == "2026-06-12"
    assert overview["danger_state"] == sig.DANGER


def test_confirmation_cutoff_keeps_next_day_intraday_event_pending():
    start = date(2026, 7, 14)
    factors = [
        _factor(start, "GOLD"),
        _factor(start + timedelta(days=1), "NEUTRAL"),
    ]

    events = sig.detect_events(
        factors,
        [100.0, 101.0],
        confirmed_through=start,
    )

    assert len(events) == 1
    assert events[0].status == sig.STATUS_PENDING
    assert events[0].confirm_date is None


def test_gold_failure_silver_stays_pending_until_failure_day_is_final():
    factors, closes, up_ratios = _gold_failure_panel_case()

    intraday_events = sig.detect_events(
        factors,
        closes,
        up_ratios,
        confirmed_through=factors[-2].trade_date,
    )
    final_events = sig.detect_events(
        factors,
        closes,
        up_ratios,
        confirmed_through=factors[-1].trade_date,
    )

    intraday_failure = next(
        event
        for event in intraday_events
        if event.setup_type == sig.SETUP_GOLD_FAILURE_SILVER
    )
    final_failure = next(
        event
        for event in final_events
        if event.setup_type == sig.SETUP_GOLD_FAILURE_SILVER
    )
    assert intraday_failure.status == sig.STATUS_PENDING
    assert intraday_failure.confirm_date is None
    assert final_failure.status == sig.STATUS_CONFIRMED
    assert final_failure.confirm_date == factors[-1].trade_date
    assert sig.build_active_directions(
        [factor.trade_date for factor in factors],
        intraday_events,
    )[-1] == "GOLD"
    assert sig.build_active_directions(
        [factor.trade_date for factor in factors],
        final_events,
    )[-1] == "SILVER"


def test_timing_series_exposes_gold_failure_silver_as_the_day_event():
    factors, closes, up_ratios = _gold_failure_panel_case()
    events = sig.detect_events(factors, closes, up_ratios)

    rows = mt_panel._build_timing_series(
        factors,
        events,
        closes,
        up_ratios,
    )

    assert rows[-1]["active_direction"] == "SILVER"
    assert rows[-1]["zone_direction"] == "NEUTRAL"
    assert rows[-1]["event"] == {
        "direction": "SILVER",
        "status": sig.STATUS_CONFIRMED,
        "grade": "WEAK",
        "setup_type": sig.SETUP_GOLD_FAILURE_SILVER,
        "confirm_date": str(factors[-1].trade_date),
    }


def test_timing_series_keeps_daily_dates_and_event_confirmation():
    start = date(2026, 7, 6)
    factors = [
        _factor(start, "NEUTRAL"),
        _factor(start + timedelta(days=1), "SILVER"),
        _factor(start + timedelta(days=2), "SILVER"),
    ]
    event = _signal(
        start + timedelta(days=1),
        "SILVER",
        confirm_date=start + timedelta(days=2),
    )

    rows = mt_panel._build_timing_series(factors, [event])

    assert [row["date"] for row in rows] == ["2026-07-06", "2026-07-07", "2026-07-08"]
    assert [row["active_direction"] for row in rows] == [
        "NEUTRAL",
        "NEUTRAL",
        "SILVER",
    ]
    assert rows[0]["zone_direction"] == "NEUTRAL"
    assert rows[1]["zone_direction"] == "SILVER"
    assert rows[1]["event"] == {
        "direction": "SILVER",
        "status": sig.STATUS_CONFIRMED,
        "grade": "WEAK",
        "setup_type": sig.SETUP_TOP_SILVER,
        "confirm_date": "2026-07-08",
    }
    assert rows[2]["event"] is None


def test_timing_series_uses_reversal_gold_zone_from_close_prefix():
    closes = [100.0] * 19 + [98.0, 94.0, 93.5, 94.5]
    start = date(2026, 5, 12)
    factors = [
        _factor(start + timedelta(days=index), "SILVER")
        for index in range(len(closes))
    ]
    events = sig.detect_events(
        factors,
        closes,
        up_ratios=[1.0] * len(closes),
    )

    rows = mt_panel._build_timing_series(factors, events, closes)

    candidate = rows[-2]
    assert candidate["zone_direction"] == "GOLD"
    assert candidate["event"] is not None
    assert candidate["event"]["setup_type"] == sig.SETUP_REVERSAL_GOLD


def test_timing_series_exposes_causal_structural_danger_state():
    factors, closes, up_ratios = _structural_panel_case()
    events = sig.detect_events(factors, closes, up_ratios)

    rows = mt_panel._build_timing_series(
        factors,
        events,
        closes,
        up_ratios,
    )

    assert rows[20]["zone_direction"] == "SILVER"
    assert rows[20]["danger_state"] == sig.DANGER
    assert [row["danger_state"] for row in rows[20:24]] == [sig.DANGER] * 4
    assert rows[24]["danger_state"] == sig.NORMAL
    assert rows[20]["event"] == {
        "direction": "SILVER",
        "status": sig.STATUS_CONFIRMED,
        "grade": "STRONG",
        "setup_type": sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER,
        "confirm_date": str(factors[21].trade_date),
    }
