import importlib
import os
import sys
import threading
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.data_sources.akshare_adapter import (
    AkShareAdapter,
    AkShareSourceError,
    _bar_row_to_api,
    _compact_stock_row_to_api,
    _eastmoney_board_daily_quote,
    _eastmoney_board_kline,
    _eastmoney_board_member_row_to_api,
    _eastmoney_board_row_to_api,
    _eastmoney_hsf10_sector_rows_to_api,
    _eastmoney_quote_row_to_api,
    _eastmoney_stock_main_fund_flow,
    _eastmoney_stock_kline,
    _eastmoney_stock_hot_rank_items,
    _filter_bars_by_date,
    _financial_performance_row_to_api,
    _financial_row_to_api,
    _sina_member_row_to_api,
    _tencent_stock_kline_full,
)
from alphaagent.market.cache import market_cache
from alphaagent.market.providers import RealMarketDataClient


def test_akshare_source_info_reads_integrated_source_tree() -> None:
    adapter = AkShareAdapter()

    info = adapter.info().to_api()

    assert info["name"] == "akshare"
    assert info["version"] != "unknown"
    assert Path(str(info["package_dir"])).joinpath("_version.py").exists()


def test_adapter_exposes_akshare_submodules_without_full_init() -> None:
    sys.modules.pop("akshare", None)

    adapter = AkShareAdapter()
    adapter._install_namespace_package()

    module = sys.modules["akshare"]
    assert str(adapter.package_dir) in list(module.__path__)
    assert not hasattr(module, "stock_zh_a_spot_em")


def test_eastmoney_board_kline_parses_bk_history(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "klines": [
                        "2026-06-25,10.00,10.50,10.70,9.90,12345,678900.00,2.0,1.5,0.15,3.0",
                        "2026-06-26,10.50,10.80,10.90,10.30,22345,778900.00,2.1,2.86,0.30,3.2",
                    ]
                }
            }

    captured: dict[str, object] = {}

    def fake_get(url, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter.requests.get", fake_get)

    df = _eastmoney_board_kline("BK0459", "industry", limit=2, start_date="20260601", end_date="20260630")

    assert captured["params"]["secid"] == "90.BK0459"
    assert list(df["close"]) == [10.5, 10.8]
    assert list(df["change_pct"]) == [1.5, 2.86]


def test_eastmoney_board_kline_continues_after_http_200_empty_payload(
    monkeypatch,
) -> None:
    responses = [
        {"data": {"klines": []}},
        {
            "data": {
                "klines": [
                    "2026-07-17,10.00,10.50,10.70,9.90,12345,"
                    "678900.00,2.0,5.0,0.50,3.0"
                ]
            }
        },
    ]
    requested_urls: list[str] = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, **kwargs):
        del kwargs
        requested_urls.append(url)
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter.requests.get",
        fake_get,
    )

    frame = _eastmoney_board_kline(
        "BK0459",
        "industry",
        limit=1,
        start_date="20260701",
        end_date="20260718",
    )

    assert len(requested_urls) == 2
    assert frame.iloc[0]["date"] == date(2026, 7, 17)
    assert frame.iloc[0]["close"] == pytest.approx(10.5)


def test_eastmoney_board_daily_quote_parses_verified_completed_bar(
    monkeypatch,
) -> None:
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "f43": 298379,
                    "f44": 319273,
                    "f45": 296518,
                    "f46": 309123,
                    "f47": 8539633,
                    "f48": 18472485669.0,
                    "f57": "BK0949",
                    "f58": "氦气概念",
                    "f59": 2,
                    "f60": 311235,
                    "f86": 1784273972,
                    "f170": -413,
                }
            }

    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter.requests.get",
        lambda *args, **kwargs: FakeResponse(),
    )

    frame = _eastmoney_board_daily_quote(
        "BK0949",
        now=datetime(2026, 7, 18, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    row = frame.iloc[0]
    assert row["date"] == date(2026, 7, 17)
    assert row["open"] == pytest.approx(3091.23)
    assert row["high"] == pytest.approx(3192.73)
    assert row["low"] == pytest.approx(2965.18)
    assert row["close"] == pytest.approx(2983.79)
    assert row["volume"] == pytest.approx(8539633)
    assert row["turnover"] == pytest.approx(18472485669)
    assert row["change_pct"] == pytest.approx(-4.13)
    assert row["previous_close"] == pytest.approx(3112.35)
    assert row["source_detail"] == "eastmoney.board_quote_daily"
    assert row["source_timestamp"] == "2026-07-17T15:39:32+08:00"


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"f86": None}, "timestamp"),
        ({"f57": "BK0000"}, "code"),
        ({"f44": 290000}, "OHLC"),
        ({"f86": 1784268000}, "incomplete"),
    ],
)
def test_eastmoney_board_daily_quote_rejects_invalid_or_incomplete_rows(
    monkeypatch,
    patch,
    message,
) -> None:
    payload = {
        "f43": 298379,
        "f44": 319273,
        "f45": 296518,
        "f46": 309123,
        "f47": 8539633,
        "f48": 18472485669.0,
        "f57": "BK0949",
        "f58": "氦气概念",
        "f59": 2,
        "f60": 311235,
        "f86": 1784273972,
        "f170": -413,
    }
    payload.update(patch)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": payload}

    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter.requests.get",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(AkShareSourceError, match=message):
        _eastmoney_board_daily_quote(
            "BK0949",
            now=datetime(2026, 7, 17, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        )


def test_sector_daily_bars_uses_completed_official_quote_after_kline_failure(
    monkeypatch,
) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()
    quote_frame = pd.DataFrame(
        [
            {
                "date": date(2026, 7, 17),
                "open": 3091.23,
                "close": 2983.79,
                "high": 3192.73,
                "low": 2965.18,
                "volume": 8539633,
                "turnover": 18472485669,
                "change_pct": -4.13,
                "previous_close": 3112.35,
                "source_detail": "eastmoney.board_quote_daily",
                "source_timestamp": "2026-07-17T15:39:32+08:00",
            }
        ]
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_board_kline",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AkShareSourceError("history unavailable")
        ),
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_board_daily_quote",
        lambda *args, **kwargs: quote_frame,
    )
    monkeypatch.setattr(
        adapter,
        "_sector_daily_bars_ths",
        lambda *args, **kwargs: pytest.fail("official quote must precede THS"),
    )

    data = adapter.sector_daily_bars("BK0949", board_type="theme", limit=30)

    assert data["source"] == "eastmoney.board_kline"
    assert data["items"][0]["trade_date"] == "2026-07-17"
    assert data["items"][0]["raw"] == {
        "source_detail": "eastmoney.board_quote_daily",
        "source_timestamp": "2026-07-17T15:39:32+08:00",
        "previous_close": 3112.35,
    }


def test_sector_daily_bars_uses_eastmoney_before_ths(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    def fake_board_kline(sector_id, board_type, limit, start_date=None, end_date=None):
        return pd.DataFrame(
            [
                {
                    "date": "2026-06-26",
                    "open": 10,
                    "close": 11,
                    "high": 12,
                    "low": 9,
                    "volume": 100,
                    "turnover": 200,
                    "change_pct": 3.2,
                }
            ]
        )

    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._eastmoney_board_kline", fake_board_kline)

    data = adapter.sector_daily_bars("BK0459", board_type="industry", limit=1)

    assert data["source"] == "eastmoney.board_kline"
    assert data["items"][0]["trade_date"] == "2026-06-26"
    assert data["items"][0]["close"] == 11
    assert data["items"][0]["change_pct"] == 3.2


def test_sector_daily_bars_defaults_to_800_sessions(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()
    captured: dict[str, object] = {}

    def fake_board_kline(sector_id, board_type, limit, start_date=None, end_date=None):
        captured.update(
            {
                "sector_id": sector_id,
                "board_type": board_type,
                "limit": limit,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return pd.DataFrame(
            [
                {
                    "date": "2026-06-26",
                    "open": 10,
                    "close": 11,
                    "high": 12,
                    "low": 9,
                    "volume": 100,
                    "turnover": 200,
                    "change_pct": 3.2,
                }
            ]
        )

    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_board_kline",
        fake_board_kline,
    )

    data = adapter.sector_daily_bars("BK0490", board_type="concept")

    assert captured["limit"] == 800
    assert data["source"] == "eastmoney.board_kline"


def test_bar_row_to_api_preserves_zero_values() -> None:
    item = _bar_row_to_api(
        {
            "日期": "2026-06-26",
            "开盘价": 0,
            "收盘价": 0,
            "最高价": 0,
            "最低价": 0,
            "成交量": 0,
            "成交额": 0,
            "换手率": 0,
            "涨跌幅": 0,
        }
    )

    assert item["open"] == 0
    assert item["close"] == 0
    assert item["volume"] == 0
    assert item["turnover"] == 0
    assert item["turnover_rate"] == 0
    assert item["change_pct"] == 0


def test_a_share_spot_normalizes_tencent_rows(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    class FakeModule:
        @staticmethod
        def stock_zh_a_spot_tx():
            return pd.DataFrame(
                [
                    {
                        "code": "sh600487",
                        "name": "亨通光电",
                        "zxj": "15.26",
                        "zd": "0.38",
                        "zdf": "2.55",
                        "zdf_d5": "5.10",
                        "zdf_d10": "7.20",
                        "zdf_d20": "12.30",
                        "turnover": "123456",
                        "zsz": "2370.70",
                        "ltsz": "2350.31",
                    }
                ]
            )

    monkeypatch.setattr("importlib.import_module", lambda name: FakeModule)

    data = adapter.a_share_spot(limit=1)

    assert data["items"][0]["vt_symbol"] == "600487.SSE"
    assert data["items"][0]["name"] == "亨通光电"
    assert data["items"][0]["last_price"] == 15.26
    assert data["items"][0]["turnover"] == 1234560000
    assert data["items"][0]["market_cap"] == 237070000000
    assert data["items"][0]["float_market_cap"] == 235031000000
    assert data["items"][0]["return_20d"] == 12.30


def test_a_share_spot_uses_prefixed_exchange_for_bse(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    class FakeModule:
        @staticmethod
        def stock_zh_a_spot_tx():
            return pd.DataFrame(
                [
                    {
                        "code": "bj920206",
                        "name": "N彩客",
                        "zxj": "98.50",
                        "zdf": "225.30",
                        "turnover": "37888",
                        "zsz": "70.47",
                        "ltsz": "14.04",
                    }
                ]
            )

    monkeypatch.setattr("importlib.import_module", lambda name: FakeModule)

    item = adapter.a_share_spot(limit=1)["items"][0]

    assert item["symbol"] == "920206"
    assert item["exchange"] == "BSE"
    assert item["vt_symbol"] == "920206.BSE"


def test_all_stock_quotes_fetches_every_page_and_deduplicates(monkeypatch) -> None:
    import alphaagent.data_sources.akshare_adapter as adapter_module

    pages = {
        0: ([{"code": "sh600000", "name": "浦发银行", "zxj": "10", "zdf": "1"}], 401),
        200: ([{"code": "sz000001", "name": "平安银行", "zxj": "11", "zdf": "2"}], 401),
        400: ([{"code": "sh600000", "name": "浦发银行", "zxj": "10", "zdf": "1"}], 401),
    }

    def fake_page(_module, offset, count, sort="price"):
        assert count == 200
        assert sort == "price"
        rows, total = pages[offset]
        return pd.DataFrame(rows), total

    monkeypatch.setattr(adapter_module, "_stock_zh_a_spot_tx_page", fake_page)

    payload = adapter_module.AkShareAdapter()._all_stock_quotes_uncached(max_workers=2)

    assert payload["total"] == 2
    assert {item["vt_symbol"] for item in payload["items"]} == {
        "600000.SSE",
        "000001.SZSE",
    }
    assert all("raw" not in item for item in payload["items"])
    assert payload["source"] == "tencent.full_a_share_pages"


def test_compact_tencent_quote_keeps_point_in_time_momentum_and_main_flow() -> None:
    row = _compact_stock_row_to_api(
        {
            "code": "sh600000",
            "name": "浦发银行",
            "zxj": "10.50",
            "zdf": "5.00",
            "speed": "1.25",
            "zf": "6.80",
            "turnover": "1000",
            "zljlr": "120",
            "zllr": "610",
            "zllc": "490",
        }
    )

    assert row["quote_speed"] == 1.25
    assert row["quote_amplitude_pct"] == 6.8
    assert row["quote_main_net_inflow"] == 1_200_000
    assert row["quote_main_inflow"] == 6_100_000
    assert row["quote_main_outflow"] == 4_900_000
    assert row["quote_main_net_inflow_ratio"] == 12.0


def test_all_stock_quotes_cache_isolates_callers_without_recursive_copy(
    monkeypatch,
) -> None:
    import alphaagent.data_sources.akshare_adapter as adapter_module

    adapter_module._FULL_MARKET_QUOTE_CACHE.clear()
    calls = 0

    def load_snapshot(*, max_workers):
        nonlocal calls
        del max_workers
        calls += 1
        return {
            "items": [
                {
                    "vt_symbol": "600000.SSE",
                    "name": "浦发银行",
                    "change_pct": 1.0,
                }
            ],
            "total": 1,
        }

    adapter = adapter_module.AkShareAdapter()
    monkeypatch.setattr(adapter, "_all_stock_quotes_uncached", load_snapshot)

    first = adapter.all_stock_quotes(max_workers=2)
    first["items"][0]["name"] = "caller mutation"
    first["items"].append({"vt_symbol": "000001.SZSE"})
    second = adapter.all_stock_quotes(max_workers=2)

    assert calls == 1
    assert second["items"] == [
        {
            "vt_symbol": "600000.SSE",
            "name": "浦发银行",
            "change_pct": 1.0,
        }
    ]


def test_all_stock_quotes_rejects_a_partial_page_failure(monkeypatch) -> None:
    import alphaagent.data_sources.akshare_adapter as adapter_module

    def fake_page(_module, offset, count, sort="price"):
        if offset:
            raise TimeoutError("page timed out")
        return pd.DataFrame([{"code": "sh600000", "name": "浦发银行"}]), 201

    monkeypatch.setattr(adapter_module, "_stock_zh_a_spot_tx_page", fake_page)

    with pytest.raises(TimeoutError, match="page timed out"):
        adapter_module.AkShareAdapter()._all_stock_quotes_uncached(max_workers=2)


def test_all_stock_ohlcv_spot_fetches_complete_sina_pages_and_deduplicates(
    monkeypatch,
) -> None:
    import alphaagent.data_sources.akshare_adapter as adapter_module

    requested_pages: list[int] = []
    pages = {
        1: [
            {
                "symbol": "sh600000",
                "code": "600000",
                "name": "浦发银行",
                "trade": "10.50",
                "open": "10.20",
                "high": "10.70",
                "low": "10.10",
                "volume": "123456",
                "amount": "1296288",
                "ticktime": "10:15:00",
            }
        ],
        2: [
            {
                "symbol": "sz000001",
                "code": "000001",
                "name": "平安银行",
                "trade": "11.20",
                "open": "11.00",
                "high": "11.30",
                "low": "10.90",
                "volume": "654321",
                "amount": "7328395",
                "ticktime": "10:15:00",
            },
            {
                "symbol": "sh600000",
                "code": "600000",
                "name": "浦发银行",
                "trade": "10.50",
                "open": "10.20",
                "high": "10.70",
                "low": "10.10",
                "volume": "123456",
                "amount": "1296288",
                "ticktime": "10:15:00",
            },
        ],
    }

    monkeypatch.setattr(
        adapter_module,
        "_sina_sector_member_count",
        lambda node: 501 if node == "hs_a" else pytest.fail("unexpected node"),
    )

    def fake_rows(node: str, page: int, page_size: int, sort: str):
        assert node == "hs_a"
        assert page_size == 500
        assert sort == "symbol"
        requested_pages.append(page)
        return pages[page]

    monkeypatch.setattr(adapter_module, "_sina_sector_member_rows", fake_rows)

    payload = adapter_module.AkShareAdapter()._all_stock_ohlcv_spot_uncached(
        max_workers=2
    )

    assert sorted(requested_pages) == [1, 2]
    assert payload["source"] == "sina.market_center.hs_a_ohlcv"
    assert payload["source_total"] == 501
    assert payload["total"] == 2
    items = {item["vt_symbol"]: item for item in payload["items"]}
    assert set(items) == {"600000.SSE", "000001.SZSE"}
    assert items["600000.SSE"] == {
        "symbol": "600000",
        "exchange": "SSE",
        "vt_symbol": "600000.SSE",
        "name": "浦发银行",
        "last_price": 10.5,
        "open_price": 10.2,
        "high_price": 10.7,
        "low_price": 10.1,
        "volume": 123456.0,
        "turnover": 1296288.0,
        "turnover_rate": None,
        "trade_time": "10:15:00",
        "source": "sina.market_center.hs_a_ohlcv",
    }


def test_all_stock_ohlcv_spot_rejects_unavailable_sina_count(monkeypatch) -> None:
    import alphaagent.data_sources.akshare_adapter as adapter_module

    monkeypatch.setattr(
        adapter_module,
        "_sina_sector_member_count",
        lambda _node: None,
    )

    with pytest.raises(AkShareSourceError, match="stock count unavailable"):
        adapter_module.AkShareAdapter()._all_stock_ohlcv_spot_uncached(max_workers=1)


def test_all_stock_ohlcv_spot_force_refresh_bypasses_cached_snapshot(monkeypatch) -> None:
    import alphaagent.data_sources.akshare_adapter as adapter_module

    adapter_module._FULL_MARKET_OHLCV_SPOT_CACHE.clear()
    calls: list[int] = []
    adapter = adapter_module.AkShareAdapter()

    def load_snapshot(*, max_workers: int) -> dict[str, object]:
        calls.append(max_workers)
        return {"items": [{"vt_symbol": "600000.SSE", "last_price": len(calls)}]}

    monkeypatch.setattr(adapter, "_all_stock_ohlcv_spot_uncached", load_snapshot)

    assert adapter.all_stock_ohlcv_spot(max_workers=2)["items"][0]["last_price"] == 1
    assert adapter.all_stock_ohlcv_spot(max_workers=2)["items"][0]["last_price"] == 1
    assert adapter.all_stock_ohlcv_spot(max_workers=2, force_refresh=True)["items"][0]["last_price"] == 2
    assert calls == [2, 2]


def test_stock_detail_uses_fast_tencent_quote(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    class FakeResponse:
        text = (
            'v_sh600487="1~亨通光电~600487~100.85~96.12~92.55~1243049~661907~'
            '577572~100.80~27~100.74~182~100.73~51~100.70~1~100.68~90~'
            '100.85~7~100.86~567~100.87~1~100.88~1048~100.89~188~~'
            '20260608102722~4.73~4.92~100.88~92.55~100.85/1243049/12001902312~'
            '1243049~1200190~5.08~77.04~~100.88~92.55~8.67~2465.97~2487.36~'
            '7.67~105.73~86.51~2.53~-1460~96.55~56.26~92.80~~~~1.88~'
            '1200190.2312";'
        )

        @staticmethod
        def raise_for_status() -> None:
            return None

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeResponse())

    item = adapter.stock_detail("600487", "SSE")

    assert item["vt_symbol"] == "600487.SSE"
    assert item["name"] == "亨通光电"
    assert item["last_price"] == 100.85
    assert item["change_pct"] == 4.92
    assert item["source"] == "tencent.qt.gtimg"


def test_list_stocks_uses_ttl_cache(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()
    calls = {"count": 0}

    def fake_page(page: int, page_size: int, sort: str):
        del page, page_size, sort
        calls["count"] += 1
        return {
            "items": [{"vt_symbol": "600487.SSE", "symbol": "600487", "name": "亨通光电"}],
            "page": 1,
            "page_size": 50,
            "total": 1,
            "source": "fake",
        }

    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._sina_all_a_page", fake_page)

    first = adapter.list_stocks(page=1, page_size=50, sort="price")
    second = adapter.list_stocks(page=1, page_size=50, sort="price")

    assert first["items"][0]["vt_symbol"] == "600487.SSE"
    assert second["items"][0]["vt_symbol"] == "600487.SSE"
    assert calls["count"] == 1


def test_change_pct_list_keeps_sina_as_the_formal_quote_source(monkeypatch) -> None:
    adapter = AkShareAdapter()
    calls: list[str] = []

    def sina_page(page: int, page_size: int, sort: str):
        calls.append("sina")
        assert (page, page_size, sort) == (1, 100, "change_pct")
        return {
            "items": [{"vt_symbol": "600001.SSE", "last_price": 10.2}],
            "page": page,
            "page_size": page_size,
            "total": 1,
            "source": "sina.market_center.hs_a",
        }

    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._sina_all_a_page",
        sina_page,
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_all_a_page",
        lambda *_args, **_kwargs: pytest.fail(
            "formal change ranking must not switch to EastMoney"
        ),
    )

    result = adapter._list_stocks_uncached(1, 100, "change_pct", "desc")

    assert result["source"] == "sina.market_center.hs_a"
    assert result["items"][0]["last_price"] == 10.2
    assert calls == ["sina"]


def test_change_pct_list_uses_eastmoney_only_after_sina_failure(monkeypatch) -> None:
    adapter = AkShareAdapter()
    calls: list[str] = []
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_all_a_page",
        lambda *_args, **_kwargs: calls.append("eastmoney")
        or {"items": [], "source": "eastmoney.push2delay.clist"},
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._sina_all_a_page",
        lambda *_args, **_kwargs: calls.append("sina")
        or (_ for _ in ()).throw(AkShareSourceError("sina unavailable")),
    )

    result = adapter._list_stocks_uncached(1, 100, "change_pct", "desc")

    assert result["source"] == "eastmoney.push2delay.clist"
    assert calls == ["sina", "eastmoney"]


def test_research_quote_flow_page_reads_fresh_eastmoney_rows(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()
    calls: list[tuple[int, int, str, str]] = []

    def eastmoney_page(page: int, page_size: int, sort: str, order: str):
        calls.append((page, page_size, sort, order))
        return {
            "items": [
                {
                    "vt_symbol": "600001.SSE",
                    "quote_observed_at": "2026-07-21T02:05:00+00:00",
                    "quote_speed": 1.2,
                    "quote_amplitude_pct": 6.4,
                    "quote_main_net_inflow": 12_000_000.0,
                    "quote_main_net_inflow_ratio": 2.63,
                }
            ],
            "source": "eastmoney.push2delay.clist",
        }

    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_all_a_page",
        eastmoney_page,
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_stock_page_is_fresh",
        lambda _payload: True,
    )

    result = adapter.research_quote_flow_page(1, 100)

    assert calls == [(1, 100, "change_pct", "desc")]
    assert result["items"][0]["quote_main_net_inflow_ratio"] == 2.63


def test_research_quote_flow_page_rejects_stale_eastmoney_rows(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_all_a_page",
        lambda *_args, **_kwargs: {"items": [{"vt_symbol": "600001.SSE"}]},
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_stock_page_is_fresh",
        lambda _payload: False,
    )

    with pytest.raises(AkShareSourceError, match="stale"):
        adapter.research_quote_flow_page(1, 100)


def test_eastmoney_change_page_freshness_uses_row_source_time() -> None:
    import alphaagent.data_sources.akshare_adapter as adapter_module

    now = datetime(2026, 7, 21, 10, 5, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    fresh = {
        "items": [
            {"quote_observed_at": "2026-07-21T02:05:00+00:00"}
            for _index in range(10)
        ]
    }
    stale = {
        "items": [
            {"quote_observed_at": "2026-07-21T02:04:00+00:00"}
            for _index in range(10)
        ]
    }

    assert adapter_module._eastmoney_stock_page_is_fresh(fresh, now=now)
    assert not adapter_module._eastmoney_stock_page_is_fresh(stale, now=now)


def test_limit_up_pool_uses_short_ttl_only_for_current_date(monkeypatch) -> None:
    adapter = AkShareAdapter()
    calls: list[tuple[str, int]] = []

    def fake_get_or_set(key: str, ttl_seconds: int, loader):
        calls.append((key, ttl_seconds))
        return loader()

    monkeypatch.setattr(market_cache, "get_or_set", fake_get_or_set)
    monkeypatch.setattr(
        adapter,
        "_limit_up_pools_uncached",
        lambda trade_date: {"trade_date": trade_date, "pools": {}},
    )

    today = date.today().strftime("%Y%m%d")
    adapter.limit_up_pools(today)
    adapter.limit_up_pools("20200102")

    assert calls == [
        (f"limit_up_pools:{today}", adapter.LIVE_LIMIT_POOL_TTL_SECONDS),
        ("limit_up_pools:20200102", adapter.LIMIT_POOL_TTL_SECONDS),
    ]


def test_live_board_quotes_do_not_use_the_daily_board_cache(monkeypatch) -> None:
    adapter = AkShareAdapter()
    calls: list[tuple[str, int]] = []

    def fake_get_or_set(key: str, ttl_seconds: int, loader):
        calls.append((key, ttl_seconds))
        return loader()

    monkeypatch.setattr(market_cache, "get_or_set", fake_get_or_set)
    monkeypatch.setattr(
        adapter,
        "_board_names_uncached",
        lambda board_type, limit: {
            "type": board_type,
            "items": [{"id": "BK_TEST", "change_pct": 1.2}],
            "total": 1,
            "updated_at": "2026-07-20T06:50:00+00:00",
        },
    )

    payload = adapter.live_board_quotes("concept", limit=1000)

    assert payload["items"][0]["id"] == "BK_TEST"
    assert calls == [("live_board_quotes:concept:1000", 10)]


def test_limit_up_pool_sources_are_fetched_concurrently(monkeypatch) -> None:
    adapter = AkShareAdapter()
    monkeypatch.setenv("HTTP_PROXY", "http://unused-proxy.invalid")
    started: list[str] = []
    lock = threading.Lock()
    all_started = threading.Event()

    def source(name: str):
        def load(*, date: str):
            assert date == "20260713"
            assert "HTTP_PROXY" not in os.environ
            with lock:
                started.append(name)
                if len(started) == 5:
                    all_started.set()
            assert all_started.wait(timeout=1)
            return pd.DataFrame()

        return load

    module = SimpleNamespace(
        stock_zt_pool_em=source("zt"),
        stock_zt_pool_previous_em=source("zt_previous"),
        stock_zt_pool_strong_em=source("strong"),
        stock_zt_pool_zbgc_em=source("zbgc"),
        stock_zt_pool_dtgc_em=source("dtgc"),
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter.importlib.import_module",
        lambda _name: module,
    )

    result = adapter._limit_up_pools_uncached("20260713")

    assert set(started) == {"zt", "zt_previous", "strong", "zbgc", "dtgc"}
    assert set(result["pools"]) == set(started)
    assert all(
        pool.get("status") != "unavailable"
        for pool in result["pools"].values()
    )
    assert os.environ["HTTP_PROXY"] == "http://unused-proxy.invalid"


def test_limit_up_pool_requests_have_a_bounded_timeout(monkeypatch) -> None:
    module = importlib.import_module("akshare.stock_feature.stock_ztb_em")
    timeouts: list[object] = []

    class Response:
        def json(self):
            return {"data": None}

    def fake_get(_url, *, params, timeout):
        assert params["date"] == "20260713"
        timeouts.append(timeout)
        return Response()

    monkeypatch.setattr(module.requests, "get", fake_get)

    result = module.stock_zt_pool_em(date="20260713")

    assert result.empty
    assert timeouts == [module.REQUEST_TIMEOUT_SECONDS]


def test_source_status_cache_keeps_datetime_values(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    monkeypatch.setattr(adapter, "list_stocks", lambda page=1, page_size=1: {"items": []})
    monkeypatch.setattr(adapter, "stock_bars", lambda *args, **kwargs: {"items": [{"close": 1}]})
    monkeypatch.setattr(adapter, "stock_business", lambda *args, **kwargs: {"summary": "ok"})
    monkeypatch.setattr(adapter, "board_names", lambda *args, **kwargs: {"items": []})

    first = adapter.source_status()
    second = adapter.source_status()

    assert first[0].to_api()["checked_at"]
    assert second[0].to_api()["checked_at"]


def test_financial_row_to_api_maps_publish_and_cash_flow_fields() -> None:
    item = _financial_row_to_api(
        {
            "REPORT_DATE": "2026-03-31 00:00:00",
            "NOTICE_DATE": "2026-04-30 00:00:00",
            "OPERATE_INCOME": 100_000_000,
            "NETPROFIT": 12_000_000,
            "DEDUCT_PARENT_NETPROFIT": 10_000_000,
            "NETCASH_OPERATE": 18_000_000,
        }
    )

    assert item["report_date"] == "2026-03-31 00:00:00"
    assert item["publish_date"] == "2026-04-30 00:00:00"
    assert item["revenue"] == 100_000_000
    assert item["net_profit"] == 12_000_000
    assert item["deducted_net_profit"] == 10_000_000
    assert item["operating_cash_flow"] == 18_000_000


def test_financial_row_to_api_does_not_treat_quarterly_change_as_yoy() -> None:
    item = _financial_row_to_api(
        {
            "REPORT_DATE": "2026-03-31 00:00:00",
            "PARENT_NETPROFIT": -11_700_143.61,
            "NETPROFIT": -3_276_119.8,
            "PARENT_NETPROFIT_QOQ": 70.0043,
            "NETPROFIT_QOQ": 85.9097,
            "TOTAL_OPERATE_INCOME_QOQ": -28.5024,
        }
    )

    assert item["net_profit"] == -11_700_143.61
    assert item["net_profit_yoy"] is None
    assert item["net_profit_qoq"] == 70.0043
    assert item["revenue_yoy"] is None
    assert item["revenue_qoq"] == -28.5024


def test_financial_performance_row_maps_parent_profit_yoy() -> None:
    item = _financial_performance_row_to_api(
        {
            "SECURITY_CODE": "000670",
            "SECUCODE": "000670.SZ",
            "SECURITY_NAME_ABBR": "盈方微",
            "REPORTDATE": "2026-03-31 00:00:00",
            "NOTICE_DATE": "2026-04-21 00:00:00",
            "TOTAL_OPERATE_INCOME": 933_292_145.7,
            "PARENT_NETPROFIT": -11_700_143.61,
            "YSTZ": 24.2824,
            "SJLTZ": 10.30,
            "YSHZ": -28.5024,
            "SJLHZ": 70.0043,
            "BASIC_EPS": -0.0142,
            "DEDUCT_PARENT_NETPROFIT": -18_500_000,
            "MGJYXJJE": -0.026257730722,
            "WEIGHTAVG_ROE": -30.8,
            "XSMLL": 3.1045,
        }
    )

    assert item["vt_symbol"] == "000670.SZSE"
    assert item["report_date"] == "2026-03-31 00:00:00"
    assert item["publish_date"] == "2026-04-21 00:00:00"
    assert item["revenue_yoy"] == 24.2824
    assert item["revenue_qoq"] == -28.5024
    assert item["net_profit"] == -11_700_143.61
    assert item["net_profit_yoy"] == 10.30
    assert item["net_profit_qoq"] == 70.0043
    assert item["deducted_net_profit"] == -18_500_000
    assert item["net_margin"] == -1.2536
    assert item["cash_flow_quality"] == 1.8491


def test_stock_financial_performance_reads_every_page(monkeypatch) -> None:
    adapter = AkShareAdapter()
    requested_pages: list[str] = []

    class FakeResponse:
        def __init__(self, page: str) -> None:
            self.page = page

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "result": {
                    "pages": 2,
                    "data": [
                        {
                            "SECURITY_CODE": f"60000{self.page}",
                            "SECUCODE": f"60000{self.page}.SH",
                            "REPORTDATE": "2026-03-31 00:00:00",
                            "NOTICE_DATE": "2026-04-30 00:00:00",
                            "SJLTZ": float(self.page),
                        }
                    ],
                }
            }

    def fake_get(url, *, params, headers, timeout):
        del url, headers, timeout
        page = str(params["pageNumber"])
        requested_pages.append(page)
        return FakeResponse(page)

    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter.requests.get", fake_get)

    payload = adapter._stock_financial_performance_uncached("2026-03-31")

    assert requested_pages == ["1", "2"]
    assert [item["vt_symbol"] for item in payload["items"]] == [
        "600001.SSE",
        "600002.SSE",
    ]


def test_stock_fund_flows_prefers_eastmoney_main_rank_table(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    def fake_main_flow(period: str):
        assert period == "即时"
        return (
            pd.DataFrame(
                [
                    {
                        "代码": "600000",
                        "名称": "浦发银行",
                        "今日排行榜-主力净额": 123_000_000,
                        "今日排行榜-主力净占比": 6.2,
                        "今日排行榜-今日排名": 3,
                        "今日排行榜-今日涨跌": 1.5,
                    },
                    {
                        "代码": "000001",
                        "名称": "平安银行",
                        "今日排行榜-主力净占比": -1.1,
                        "今日排行榜-今日排名": 200,
                    },
                ]
            ),
            "akshare.stock_main_fund_flow",
        )

    monkeypatch.setattr(adapter, "_stock_main_fund_flow", fake_main_flow)
    monkeypatch.setattr(adapter, "_stock_ths_fund_flow", lambda period: (_ for _ in ()).throw(AssertionError(period)))

    data = adapter.stock_fund_flows("600000", "SSE", period="即时", limit=10)

    assert data["source"] == "akshare.stock_main_fund_flow"
    assert data["items"][0]["vt_symbol"] == "600000.SSE"
    assert data["items"][0]["main_net_inflow"] == 123_000_000
    assert data["items"][0]["main_net_inflow_pct"] == 6.2
    assert data["items"][0]["main_rank"] == 3
    assert len(data["items"]) == 1


def test_sector_fund_flows_use_eastmoney_rank_table(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()
    calls: list[dict[str, object]] = []

    def fake_clist_get(hosts, params, timeout):
        del hosts, timeout
        calls.append(dict(params))
        assert params["fs"] == "m:90 t:3"
        assert params["fid"] == "f62"
        return {
            "data": {
                "total": 1,
                "diff": [
                    {
                        "f12": "BK1134",
                        "f14": "算力概念",
                        "f3": 1.42,
                        "f62": 11_423_465_472,
                        "f184": 3.04,
                        "f66": 14_252_535_808,
                        "f72": -2_829_070_336,
                        "f78": -9_135_968_256,
                        "f84": -2_305_550_848,
                        "f204": "工业富联",
                        "f205": "601138",
                        "f104": 72,
                        "f105": 24,
                        "f106": 4,
                        "f124": 1_781_768_387,
                    }
                ],
            }
        }

    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._eastmoney_clist_get", fake_clist_get)

    data = adapter.sector_fund_flows("concept", "即时")
    item = data["items"][0]

    assert data["source"] == "eastmoney.sector_fund_flow_rank"
    assert len(calls) == 1
    assert item["id"] == "BK1134"
    assert item["name"] == "算力概念"
    assert item["trade_date"] == "2026-06-18"
    assert item["rank"] == 1
    assert item["main_net_inflow"] == 11_423_465_472
    assert item["main_net_inflow_pct"] == 3.04
    assert item["leader_stock"] == "工业富联"
    assert item["rise_count"] == 72
    assert item["fall_count"] == 24
    assert item["flat_count"] == 4
    assert item["source_updated_at"] == "2026-06-18T07:39:47+00:00"


def test_sector_fund_flows_map_5d_industry_fields(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    def fake_clist_get(hosts, params, timeout):
        del hosts, timeout
        assert params["fs"] == "m:90 t:2"
        assert params["fid"] == "f164"
        return {
            "data": {
                "total": 1,
                "diff": [
                    {
                        "f12": "BK1201",
                        "f14": "电子",
                        "f109": 12.6,
                        "f164": 52_022_050_816,
                        "f165": 1.07,
                        "f166": 54_207_250_432,
                        "f168": -2_185_199_616,
                        "f170": -55_269_019_648,
                        "f172": 3_528_388_608,
                        "f257": "兆易创新",
                        "f258": "603986",
                        "f124": 1_781_768_387,
                    }
                ],
            }
        }

    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._eastmoney_clist_get", fake_clist_get)

    item = adapter.sector_fund_flows("industry", "5日")["items"][0]

    assert item["id"] == "BK1201"
    assert item["change_pct"] == 12.6
    assert item["main_net_inflow"] == 52_022_050_816
    assert item["main_net_inflow_pct"] == 1.07
    assert item["leader_stock_code"] == "603986"


def test_eastmoney_stock_main_fund_flow_fetches_multiple_pages(monkeypatch) -> None:
    calls: list[int] = []

    def fake_clist_get(hosts, params, timeout):
        del hosts, timeout
        page = int(params["pn"])
        calls.append(page)
        start = (page - 1) * 100
        return {
            "data": {
                "total": 250,
                "diff": [
                    {
                        "f12": f"{start + index:06d}",
                        "f14": f"股票{start + index}",
                        "f62": start + index,
                        "f184": 1.0,
                        "f225": start + index,
                    }
                    for index in range(100)
                ],
            }
        }

    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._eastmoney_clist_get", fake_clist_get)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    df = _eastmoney_stock_main_fund_flow(limit=250)

    assert calls == [1, 2, 3]
    assert len(df) == 250
    assert df.iloc[-1]["代码"] == "000249"


def test_stock_fund_flows_falls_back_to_ths_stock_code_column(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    def fail_main_flow(period: str):
        del period
        raise AkShareSourceError("main flow unavailable")

    def fake_ths_flow(period: str):
        assert period == "即时"
        return (
            pd.DataFrame(
                [
                    {
                        "股票代码": "000001",
                        "股票简称": "平安银行",
                        "净额": 88_000_000,
                        "涨跌幅": 2.3,
                    }
                ]
            ),
            "akshare.stock_fund_flow_individual",
        )

    monkeypatch.setattr(adapter, "_stock_main_fund_flow", fail_main_flow)
    monkeypatch.setattr(adapter, "_stock_ths_fund_flow", fake_ths_flow)

    item = adapter.stock_fund_flows("000001", "SZSE", period="即时", limit=5)["items"][0]

    assert item["vt_symbol"] == "000001.SZSE"
    assert item["name"] == "平安银行"
    assert item["main_net_inflow"] == 88_000_000


def test_stock_hot_ranks_retries_transient_failures(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_stock_hot_rank_items",
        lambda limit: [
            {
                "symbol": "600000",
                "exchange": "SSE",
                "vt_symbol": "600000.SSE",
                "name": "浦发银行",
                "rank": 1,
                "rank_change": -2,
                "raw": {},
            }
        ],
    )

    data = adapter.stock_hot_ranks(limit=5)

    assert data["source"] == "eastmoney.stockrank"
    assert data["items"][0]["vt_symbol"] == "600000.SSE"
    assert data["items"][0]["rank"] == 1


def test_eastmoney_stock_hot_rank_items_keep_rank_when_quote_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_stock_hot_rank_raw",
        lambda limit: [{"sc": "SH600000", "rk": 1, "rc": -2}],
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_batch_quotes",
        lambda secids: (_ for _ in ()).throw(ConnectionError("quote down")),
    )

    items = _eastmoney_stock_hot_rank_items(limit=5)

    assert items[0]["vt_symbol"] == "600000.SSE"
    assert items[0]["rank"] == 1
    assert items[0]["rank_change"] == -2
    assert items[0]["name"] is None


def test_eastmoney_stock_hot_rank_raw_retries_then_raises(monkeypatch) -> None:
    from alphaagent.data_sources import akshare_adapter

    calls = {"count": 0}

    class FakeSession:
        trust_env = False

        def post(self, *args, **kwargs):
            del args, kwargs
            calls["count"] += 1
            raise ConnectionError("still down")

        def close(self):
            return None

    monkeypatch.setattr("requests.Session", lambda: FakeSession())
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    with pytest.raises(AkShareSourceError, match="stock hot rank unavailable"):
        akshare_adapter._eastmoney_stock_hot_rank_raw(limit=5)

    assert calls["count"] == 3


def test_eastmoney_stock_hot_rank_raw_caps_page_size(monkeypatch) -> None:
    from alphaagent.data_sources import akshare_adapter

    seen_payloads: list[dict[str, object]] = []

    class FakeResponse:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"data": [{"sc": "SH600000", "rk": 1, "rc": 0}]}

    class FakeSession:
        trust_env = False

        def post(self, *args, **kwargs):
            del args
            seen_payloads.append(kwargs["json"])
            return FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr("requests.Session", lambda: FakeSession())

    rows = akshare_adapter._eastmoney_stock_hot_rank_raw(limit=200)

    assert rows[0]["sc"] == "SH600000"
    assert seen_payloads[0]["pageSize"] == 100


def test_stock_bars_return_latest_tail_records(monkeypatch) -> None:
    adapter = AkShareAdapter()

    class FakeModule:
        @staticmethod
        def stock_zh_a_hist_tx(symbol: str, start_date: str, end_date: str, adjust: str):
            del symbol, start_date, end_date, adjust
            return pd.DataFrame(
                [
                    {"date": "2020-01-01", "open": 1, "close": 1, "high": 1, "low": 1, "amount": 100},
                    {"date": "2026-06-04", "open": 2, "close": 2, "high": 2, "low": 2, "amount": 200},
                    {"date": "2026-06-05", "open": 3, "close": 3, "high": 3, "low": 3, "amount": 300},
                ]
            )

    monkeypatch.setattr("importlib.import_module", lambda name: FakeModule)
    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._tencent_stock_kline_full", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._tencent_stock_kline", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._eastmoney_stock_kline", lambda *args, **kwargs: pd.DataFrame())

    data = adapter.stock_bars("600487", "SSE", limit=2, interval="1d")

    assert [item["trade_date"] for item in data["items"]] == ["2026-06-04", "2026-06-05"]


def test_stock_bars_prefers_tencent_full_kline_turnover(monkeypatch) -> None:
    market_cache.clear()
    adapter = AkShareAdapter()

    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._tencent_stock_kline_full",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "date": "2026-06-12",
                    "open": 89.99,
                    "close": 89.88,
                    "high": 93.28,
                    "low": 86.92,
                    "volume": 843772,
                    "turnover": 7580017890,
                }
            ]
        ),
    )
    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._eastmoney_stock_kline", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr("alphaagent.data_sources.akshare_adapter._tencent_stock_kline", lambda *args, **kwargs: pd.DataFrame())

    data = adapter.stock_bars("002636", "SZSE", limit=1, interval="1d")

    assert data["source"] == "tencent.stock_kline_full"
    assert data["items"][0]["turnover"] == 7580017890


def test_tencent_stock_kline_full_converts_turnover_wan_yuan(monkeypatch) -> None:
    class FakeResponse:
        text = (
            'kline_data={"code":0,"msg":"","data":{"sz002636":{"day":['
            '["2026-06-12","89.99","89.88","93.28","86.92","843772.00",{},"11.65","758001.79","0.00","0.00"]'
            "]}}}"
        )

        @staticmethod
        def raise_for_status() -> None:
            return None

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeResponse())

    df = _tencent_stock_kline_full("002636", "SZSE", "1d", 5)

    assert df.iloc[0]["volume"] == 843772
    assert df.iloc[0]["turnover"] == pytest.approx(7580017900)


def test_bar_row_to_api_accepts_minute_day_column() -> None:
    item = _bar_row_to_api(
        {
            "day": "2026-06-11 14:56:00",
            "open": "10.1",
            "high": "10.2",
            "low": "10.0",
            "close": "10.15",
            "volume": "1200",
        }
    )

    assert item["trade_date"] == "2026-06-11 14:56:00"
    assert item["close"] == 10.15
    assert item["volume"] == 1200


def test_eastmoney_stock_kline_supports_minute_interval(monkeypatch) -> None:
    class FakeResponse:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "data": {
                    "klines": [
                        "2026-06-11 14:56,10.0,10.1,10.2,9.9,1200,12120,0,1.0,0.1,2.0",
                    ]
                }
            }

    seen_params: list[dict[str, object]] = []

    def fake_get(url, params, timeout):
        del url, timeout
        seen_params.append(params)
        return FakeResponse()

    monkeypatch.setattr("requests.get", fake_get)

    df = _eastmoney_stock_kline("600000", "SSE", "1m", 5, start_date="2026-06-01", end_date="2026-06-11")

    assert seen_params[0]["klt"] == "1"
    assert seen_params[0]["beg"] == "20260601"
    assert seen_params[0]["end"] == "20260611"
    assert len(df) == 1
    assert str(df.iloc[0]["date"]).startswith("2026-06-11 14:56")
    assert df.iloc[0]["close"] == 10.1


def test_filter_bars_by_date_drops_out_of_range_minute_rows() -> None:
    df = pd.DataFrame(
        [
            {"date": "2026-01-08 14:56:00", "close": 10.0},
            {"date": "2026-06-11 14:56:00", "close": 12.0},
        ]
    )

    filtered = _filter_bars_by_date(df, "2026-01-08", "2026-01-08")

    assert len(filtered) == 1
    assert filtered.iloc[0]["close"] == 10.0


def test_sina_member_row_converts_market_caps_from_wan_yuan() -> None:
    item = _sina_member_row_to_api(
        {
            "symbol": "sh600487",
            "code": "600487",
            "name": "亨通光电",
            "trade": "96.12",
            "amount": "1418168378",
            "mktcap": "1879706.055",
            "nmc": "1802680.125",
        }
    )

    assert item["vt_symbol"] == "600487.SSE"
    assert item["turnover"] == 1418168378
    assert item["market_cap"] == 18797060550
    assert item["float_market_cap"] == 18026801250
    assert item["source"] == "akshare.stock_classify_sina"


def test_sina_member_row_uses_prefixed_exchange_for_bse() -> None:
    item = _sina_member_row_to_api(
        {
            "symbol": "bj920206",
            "code": "920206",
            "name": "N彩客",
            "trade": "98.5",
            "amount": "378880000",
            "mktcap": "704700",
        }
    )

    assert item["exchange"] == "BSE"
    assert item["vt_symbol"] == "920206.BSE"


def test_sina_member_row_uses_code_fallback_for_bse() -> None:
    item = _sina_member_row_to_api(
        {
            "symbol": "bj920206",
            "code": "920206",
            "name": "N彩客",
            "trade": "98.5",
            "amount": "378880000",
            "mktcap": "704700",
        }
    )

    assert item["exchange"] == "BSE"
    assert item["vt_symbol"] == "920206.BSE"


def test_eastmoney_row_uses_code_fallback_for_bse() -> None:
    item = _eastmoney_quote_row_to_api(
        {
            "f12": "920206",
            "f13": 0,
            "f14": "N彩客",
            "f2": 88.7,
            "f3": 192.93,
            "f20": 6346150335,
        }
    )

    assert item["exchange"] == "BSE"
    assert item["vt_symbol"] == "920206.BSE"


def test_eastmoney_stock_page_exposes_realtime_momentum_and_flow_fields() -> None:
    import alphaagent.data_sources.akshare_adapter as adapter_module

    requested_fields = set(adapter_module._eastmoney_quote_fields().split(","))
    assert {"f7", "f22", "f62", "f124", "f184"}.issubset(requested_fields)

    item = _eastmoney_quote_row_to_api(
        {
            "f12": "600001",
            "f13": 1,
            "f14": "测试股份",
            "f2": 10.5,
            "f3": 5.0,
            "f7": 7.2,
            "f22": 1.4,
            "f62": 125_000_000,
            "f124": 1_784_532_895,
            "f184": 8.6,
        }
    )

    assert item["quote_observed_at"] == "2026-07-20T07:34:55+00:00"
    assert item["quote_amplitude_pct"] == 7.2
    assert item["quote_speed"] == 1.4
    assert item["quote_main_net_inflow"] == 125_000_000
    assert item["quote_main_net_inflow_ratio"] == 8.6


def test_eastmoney_board_row_exposes_realtime_metrics() -> None:
    item = _eastmoney_board_row_to_api(
        {
            "f12": "BK1036",
            "f14": "半导体",
            "f3": 1.23,
            "f20": 123456789,
            "f104": 71,
            "f105": 42,
            "f128": "赛微微电",
            "f136": 15.88,
        },
        "industry",
    )

    assert item["id"] == "BK1036"
    assert item["name"] == "半导体"
    assert item["type"] == "industry"
    assert item["stock_count"] == 113
    assert item["change_pct"] == 1.23
    assert item["source"] == "eastmoney.push2.board"


def test_eastmoney_board_member_row_uses_quote_shape() -> None:
    item = _eastmoney_board_member_row_to_api(
        {
            "f12": "600487",
            "f13": 1,
            "f14": "亨通光电",
            "f2": 10.01,
            "f3": 2.34,
            "f6": 123456789,
            "f20": 987654321,
        }
    )

    assert item["vt_symbol"] == "600487.SSE"
    assert item["name"] == "亨通光电"
    assert item["change_pct"] == 2.34
    assert item["source"] == "eastmoney.push2.board"


def test_eastmoney_clist_reuses_thread_session(monkeypatch) -> None:
    from alphaagent.data_sources import akshare_adapter

    created_sessions: list[object] = []
    requested_urls: list[str] = []

    class FakeResponse:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {"rc": 0, "data": {"diff": []}}

    class FakeSession:
        trust_env = True

        def get(self, url, **kwargs):
            del kwargs
            requested_urls.append(url)
            return FakeResponse()

    def create_session() -> FakeSession:
        session = FakeSession()
        created_sessions.append(session)
        return session

    monkeypatch.setattr(
        akshare_adapter,
        "_EASTMONEY_SESSION_LOCAL",
        threading.local(),
        raising=False,
    )
    monkeypatch.setattr(akshare_adapter.requests, "Session", create_session)

    hosts = ("https://push2.example.test",)
    akshare_adapter._eastmoney_clist_get(hosts, {"pn": 1})
    akshare_adapter._eastmoney_clist_get(hosts, {"pn": 2})

    assert len(created_sessions) == 1
    assert created_sessions[0].trust_env is False
    assert requested_urls == [
        "https://push2.example.test/api/qt/clist/get",
        "https://push2.example.test/api/qt/clist/get",
    ]


def test_eastmoney_hsf10_sector_rows_confirm_real_stock_memberships() -> None:
    items = _eastmoney_hsf10_sector_rows_to_api(
        [
            {"BOARD_CODE": "1215", "BOARD_NAME": "通信", "BOARD_RANK": 1, "IS_PRECISE": None},
            {"BOARD_CODE": "159", "BOARD_NAME": "江苏板块", "BOARD_RANK": 4, "IS_PRECISE": "0"},
            {"BOARD_CODE": "1660", "BOARD_NAME": "光纤概念", "BOARD_RANK": 20, "IS_PRECISE": "1"},
        ]
    )

    assert [item["id"] for item in items] == ["BK1215", "BK1660", "BK0159"]
    by_id = {item["id"]: item for item in items}
    assert by_id["BK1215"]["type"] == "industry"
    assert by_id["BK0159"]["type"] == "region"
    assert by_id["BK1660"]["type"] == "concept"
    assert all(item["confirmed"] is True for item in items)
    assert by_id["BK1660"]["is_precise"] is True


def test_runtime_market_client_uses_akshare_public_methods() -> None:
    assert issubclass(RealMarketDataClient, AkShareAdapter)
    assert RealMarketDataClient.list_stocks is not AkShareAdapter.list_stocks
    assert RealMarketDataClient.sector_stocks is not AkShareAdapter.sector_stocks
    assert RealMarketDataClient.stock_bars is not AkShareAdapter.stock_bars
    assert RealMarketDataClient.stock_business is AkShareAdapter.stock_business


def test_runtime_market_client_prefers_local_synced_bars(monkeypatch) -> None:
    local_payload = {"items": [{"trade_date": "2026-06-05", "close": 10}], "source": "postgresql.stock_daily_bars"}
    monkeypatch.setattr("alphaagent.market.providers._local_stock_bars", lambda *args, **kwargs: local_payload)
    monkeypatch.setattr("alphaagent.market.providers._is_intraday_china", lambda: False)

    client = RealMarketDataClient()

    assert client.stock_bars("600487", "SSE") is local_payload


def test_runtime_market_client_prefers_local_synced_stock_list(monkeypatch) -> None:
    local_payload = {"items": [{"vt_symbol": "600487.SSE"}], "source": "postgresql.stocks"}
    monkeypatch.setattr("alphaagent.market.providers._local_list_stocks", lambda *args, **kwargs: local_payload)

    client = RealMarketDataClient()

    assert client.list_stocks(page=1, page_size=50) is local_payload


def _kline_row(date_str: str, close: float = 1.0) -> dict:
    from datetime import date as _date

    year, month, day = (int(part) for part in date_str.split("-"))
    return {
        "date": _date(year, month, day),
        "open": close,
        "close": close,
        "high": close,
        "low": close,
        "volume": 1,
        "turnover_rate": 0.0,
        "turnover": 0.0,
    }


def test_daily_bars_incremental_prefers_tencent_when_covered(monkeypatch) -> None:
    """日线增量同步(带 start_date)在 tencent 覆盖范围内时应优先 tencent_full,避免落到慢源 akshare。

    回归:盘后 eod_1900 的 sync_stock_daily_bars 走增量(start_date=上一交易日+1),
    此前因 tencent 被硬性排除而全部 fallback 到 akshare.stock_zh_a_hist(单股 ~3s),
    导致 4057 只股票要 ~1 小时,候选生成被拖到 21:00 之后。
    """
    adapter = AkShareAdapter()
    tencent_df = pd.DataFrame([_kline_row("2026-06-16"), _kline_row("2026-06-22")])
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._tencent_stock_kline_full",
        lambda *args, **kwargs: tencent_df,
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_stock_kline",
        lambda *args, **kwargs: pd.DataFrame(),
    )

    def _fail_akshare_import(name, *args, **kwargs):
        raise AssertionError("akshare 兜底不应在 tencent 覆盖 start_date 时触发")

    monkeypatch.setattr("importlib.import_module", _fail_akshare_import)

    _df, source = adapter._stock_bars("600519", "1d", 250, "2026-06-22", None)

    assert source == "tencent.stock_kline_full"


def test_daily_bars_long_history_skips_tencent_when_not_covering(monkeypatch) -> None:
    """start_date 早于 tencent 返回数据的最早日期时,应跳过 tencent 走 eastmoney,避免漏掉中间历史。

    tencent 只能返回近期 N 根,长历史回填必须 fallback,否则 _filter_bars_by_date(>=start_date)
    会把近期数据全留下、漏掉 start_date 到近期之间的数据。
    """
    adapter = AkShareAdapter()
    tencent_df = pd.DataFrame([_kline_row("2026-06-22")])  # tencent 只有近期一根
    eastmoney_df = pd.DataFrame([_kline_row("2024-01-02", 2.0), _kline_row("2024-01-03", 2.0)])
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._tencent_stock_kline_full",
        lambda *args, **kwargs: tencent_df,
    )
    monkeypatch.setattr(
        "alphaagent.data_sources.akshare_adapter._eastmoney_stock_kline",
        lambda *args, **kwargs: eastmoney_df,
    )

    _df, source = adapter._stock_bars("600519", "1d", 250, "2024-01-01", None)

    assert source == "eastmoney.stock_kline"
