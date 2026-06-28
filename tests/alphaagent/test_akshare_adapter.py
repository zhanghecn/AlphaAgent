import sys
from pathlib import Path

import pandas as pd
import pytest

from alphaagent.data_sources.akshare_adapter import (
    AkShareAdapter,
    AkShareSourceError,
    _bar_row_to_api,
    _eastmoney_board_kline,
    _eastmoney_board_member_row_to_api,
    _eastmoney_board_row_to_api,
    _eastmoney_hsf10_sector_rows_to_api,
    _eastmoney_quote_row_to_api,
    _eastmoney_stock_main_fund_flow,
    _eastmoney_stock_kline,
    _eastmoney_stock_hot_rank_items,
    _filter_bars_by_date,
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
            "涨跌幅": 0,
        }
    )

    assert item["open"] == 0
    assert item["close"] == 0
    assert item["volume"] == 0
    assert item["turnover"] == 0
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

    回归:盘后 eod_18h 的 sync_stock_daily_bars 走增量(start_date=上一交易日+1),
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
