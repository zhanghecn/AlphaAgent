"""Tests for the spot synthetic tail appended by the qianlong backtest engine.

昨日信号「次日开盘卖」的退出价在 09:25 集合竞价即定格;日线表 EOD 才写,
回测引擎用现货快照拼一根合成尾行让昨日账日间即可定版。新鲜度锚点是
「拉取发生于当日 A 股交易时段」(新浪 ticktime 午休/盘后可能无日期)。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.qianlong.backtest import (
    MIN_FRESH_SPOT_SYMBOLS,
    _append_spot_synthetic_today,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
TODAY = date(2026, 8, 27)
MAIN = {"600519.SSE", "000001.SZSE"}
MIDDAY = datetime(2026, 8, 27, 12, 30, tzinfo=SHANGHAI)


def _bars(latest: date) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600519.SSE",
                "trade_date": latest,
                "open_price": 10.0, "high_price": 10.5, "low_price": 9.8,
                "close_price": 10.4, "volume": 12345.0,
                "turnover_rate": 1.2, "change_pct": 3.1,
            },
        ]
    )


def _spot_snapshot(vt_symbol: str = "600519.SSE"):
    return {
        "items": [
            {
                "vt_symbol": vt_symbol,
                "trade_time": f"{TODAY} 11:30:00",
                "open_price": 1304.0,
                "volume": 1336302.0,  # 股
            },
        ]
    }


def test_tail_appends_synthetic_today_bar(monkeypatch) -> None:
    from alphaagent.data_sources import akshare_adapter as adapter_module
    from alphaagent.server.services.qianlong import backtest as backtest_module

    # 全市场新鲜度门槛针对真实快照;单元测试只造两行桩数据
    monkeypatch.setattr(backtest_module, "MIN_FRESH_SPOT_SYMBOLS", 1)
    monkeypatch.setattr(
        adapter_module.AkShareAdapter,
        "all_stock_ohlcv_spot",
        lambda self: _spot_snapshot(),
    )

    out = _append_spot_synthetic_today(
        _bars(TODAY - timedelta(days=1)), main_symbols=MAIN, today=TODAY, now=MIDDAY)

    assert len(out) == 2
    tail = out.iloc[-1]
    assert tail["vt_symbol"] == "600519.SSE"
    assert tail["trade_date"] == TODAY
    # 今开进入 open/close/high/low;快照股 → 日线手
    assert tail["open_price"] == 1304.0
    assert tail["close_price"] == 1304.0
    assert tail["volume"] == pytest.approx(13363.02)


def test_tail_skipped_outside_trading_session(monkeypatch) -> None:
    """非交易时段(夜间批处理/周末)不启用合成尾。

    夜间 EOD 日线已含今日 bar,本就不需要尾插;此时拉到的快照无法证明
    属于今日,ticktime 又可能不带日期——宁缺毋滥。
    """
    from alphaagent.data_sources import akshare_adapter as adapter_module

    monkeypatch.setattr(
        adapter_module.AkShareAdapter,
        "all_stock_ohlcv_spot",
        lambda self: pytest.fail("spot should not be reached"),
    )
    bars = _bars(TODAY - timedelta(days=1))

    night = MIDDAY.replace(hour=22, minute=35)
    out = _append_spot_synthetic_today(bars, main_symbols=MAIN, today=TODAY, now=night)
    assert len(out) == 1

    weekend = MIDDAY.replace(day=29)  # 2026-08-29 周六
    out = _append_spot_synthetic_today(bars, main_symbols=MAIN, today=weekend.date(), now=weekend)
    assert len(out) == 1


def test_tail_skipped_when_fresh_rows_below_threshold(monkeypatch) -> None:
    """快照异常稀薄(封禁降级失败等)时不产半截数据。"""
    from alphaagent.data_sources import akshare_adapter as adapter_module
    from alphaagent.server.services.qianlong import backtest as backtest_module

    # 阈值=3,只造 2 行有效数据 → 判定不足,静默跳过
    monkeypatch.setattr(backtest_module, "MIN_FRESH_SPOT_SYMBOLS", 3)
    rows = [
        {**_spot_snapshot()["items"][0], "vt_symbol": symbol}
        for symbol in ("600001.SSE", "000002.SZSE")
    ]
    monkeypatch.setattr(
        adapter_module.AkShareAdapter,
        "all_stock_ohlcv_spot",
        lambda self: {"items": rows},
    )
    bars = _bars(TODAY - timedelta(days=1))

    out = _append_spot_synthetic_today(
        bars,
        main_symbols={"600001.SSE", "000002.SZSE", *MAIN},
        today=TODAY, now=MIDDAY)

    assert len(out) == 1


def test_tail_skipped_when_today_bar_already_present(monkeypatch) -> None:
    """EOD 后今日真实 bar 已在库中,不得重复追加。"""
    from alphaagent.data_sources import akshare_adapter as adapter_module

    monkeypatch.setattr(
        adapter_module.AkShareAdapter,
        "all_stock_ohlcv_spot",
        lambda self: pytest.fail("spot should not be reached"),
    )
    bars = _bars(TODAY)

    out = _append_spot_synthetic_today(
        bars, main_symbols=MAIN, today=TODAY, now=MIDDAY)

    assert len(out) == 1


def test_tail_survives_source_failure(monkeypatch) -> None:
    """降级链也失败时回测退回原口径,绝不能拖垮 rebuild 主流程。"""
    from alphaagent.data_sources import akshare_adapter as adapter_module

    def broken(self):
        raise RuntimeError("sina blocked & eastmoney stale")

    monkeypatch.setattr(adapter_module.AkShareAdapter, "all_stock_ohlcv_spot", broken)
    bars = _bars(TODAY - timedelta(days=1))

    out = _append_spot_synthetic_today(
        bars, main_symbols=MAIN, today=TODAY, now=MIDDAY)

    assert len(out) == 1
