from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.providers import RealMarketDataClient


def test_real_market_data_client_is_akshare_backed() -> None:
    client = RealMarketDataClient()

    assert isinstance(client, AkShareAdapter)
    assert RealMarketDataClient.list_stocks is not AkShareAdapter.list_stocks
    assert RealMarketDataClient.sector_stocks is not AkShareAdapter.sector_stocks
    assert not hasattr(client, "_sina_bars")
    assert not hasattr(client, "_eastmoney_bars")


def test_stock_bars_appends_today_realtime_bar_in_trading_hours(monkeypatch) -> None:
    """交易时段 + DB最新<今天 + 实时volume>0 时,日线应 append 今天实时K线(同花顺式)。"""
    from datetime import date

    from alphaagent.market import providers

    monkeypatch.setattr(providers, "_is_intraday_china", lambda now=None: True)
    monkeypatch.setattr(providers, "_china_today", lambda: date(2026, 6, 24))
    monkeypatch.setattr(
        providers,
        "_local_stock_bars",
        lambda *a, **k: {
            "interval": "1d",
            "items": [{"trade_date": "2026-06-23", "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0, "volume": 1000.0}],
        },
    )

    client = RealMarketDataClient()
    monkeypatch.setattr(
        client,
        "stock_detail",
        lambda *a, **k: {
            "last_price": 105.0, "open_price": 103.0, "high_price": 106.0, "low_price": 102.0,
            "volume": 2000.0, "change_pct": 3.96,
        },
    )

    items = client.stock_bars("600519", "SSE", limit=10, interval="1d")["items"]
    assert len(items) == 2
    assert items[-1]["trade_date"] == "2026-06-24"
    assert items[-1]["close"] == 105.0
    assert items[-1]["volume"] == 2000.0


def test_stock_bars_skips_today_bar_on_zero_volume_holiday(monkeypatch) -> None:
    """节假日/盘前(volume=0)不补今天K线,自动过滤非交易日。"""
    from datetime import date

    from alphaagent.market import providers

    monkeypatch.setattr(providers, "_is_intraday_china", lambda now=None: True)
    monkeypatch.setattr(providers, "_china_today", lambda: date(2026, 6, 24))
    monkeypatch.setattr(
        providers,
        "_local_stock_bars",
        lambda *a, **k: {
            "interval": "1d",
            "items": [{"trade_date": "2026-06-23", "close": 101.0, "volume": 1000.0}],
        },
    )

    client = RealMarketDataClient()
    monkeypatch.setattr(
        client,
        "stock_detail",
        lambda *a, **k: {"last_price": 101.0, "open_price": 100.0, "high_price": 102.0, "low_price": 99.0, "volume": 0},
    )

    assert len(client.stock_bars("600519", "SSE", limit=10, interval="1d")["items"]) == 1


def test_stock_bars_no_today_bar_outside_trading_hours(monkeypatch) -> None:
    """非交易时段不补今天K线(DB同步前显示昨天,符合预期节奏)。"""
    from datetime import date

    from alphaagent.market import providers

    monkeypatch.setattr(providers, "_is_intraday_china", lambda now=None: False)
    monkeypatch.setattr(providers, "_china_today", lambda: date(2026, 6, 24))
    monkeypatch.setattr(
        providers,
        "_local_stock_bars",
        lambda *a, **k: {
            "interval": "1d",
            "items": [{"trade_date": "2026-06-23", "close": 101.0, "volume": 1000.0}],
        },
    )

    client = RealMarketDataClient()
    assert len(client.stock_bars("600519", "SSE", limit=10, interval="1d")["items"]) == 1
