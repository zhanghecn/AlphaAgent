"""五池归档 archive_daily_pools: 解析 / 幂等 / 不可用池保留旧数据 / 截断告警。

全部 monkeypatch AkShareAdapter.limit_up_pools, 不碰网络; 落库用 sqlite 内存库
真实验证 delete+insert 幂等(见 conftest.fake_session)。

时间字段(first/last_limit_time)由适配器 _zt_pool_row_to_api 统一规范成
HH:MM:SS, archive 只透传(None/空串容错为 None), 不再自行归一化。
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.db import schema
from alphaagent.server.services.lianban import archive as archive_mod
from alphaagent.server.services.lianban.archive import (
    POOL_TYPES,
    _parse_limit_stat,
    archive_daily_pools,
)

D = date(2026, 8, 12)

TABLE = schema.limit_up_pool_snapshots


def _zt_item() -> dict:
    """东财 2026-08-12 涨停池真实形状(蓝盾光电), 时间已被适配器规范化。"""
    return {
        "symbol": "300862",
        "exchange": "SZSE",
        "vt_symbol": "300862.SZSE",
        "name": "蓝盾光电",
        "close_price": 32.84,
        "change_pct": 19.985,
        "limit_up_price": 32.84,
        "volume_ratio": 1.5,
        "turnover_rate": 1.37,
        "first_limit_time": "09:25:00",
        "last_limit_time": "09:48:00",
        "limit_up_count": 3,
        "limit_amount": 637629978.0,
        "raw": {
            "序号": 1,
            "代码": "300862",
            "名称": "蓝盾光电",
            "涨跌幅": 19.985,
            "最新价": 32.84,
            "成交额": 68193574,
            "换手率": 1.37,
            "封板资金": 637629978,
            "首次封板时间": "092500",
            "最后封板时间": "094800",
            "炸板次数": 1,
            "涨停统计": "3/3",
            "连板数": 3,
            "所属行业": "通用设备",
        },
    }


def _zt_item_colon_time() -> dict:
    """raw 缺炸板次数/涨停统计/所属行业/成交额 → 对应列为 None。"""
    return {
        "symbol": "600001",
        "exchange": "SSE",
        "vt_symbol": "600001.SSE",
        "name": "测试股",
        "close_price": 12.65,
        "change_pct": 10.0,
        "volume_ratio": None,
        "turnover_rate": 3.2,
        "first_limit_time": "09:48:00",
        "last_limit_time": "13:05:00",
        "limit_up_count": 1,
        "limit_amount": 1.0,
        "raw": {"代码": "600001", "名称": "测试股"},
    }


def _zbgc_item() -> dict:
    return {
        "symbol": "002415",
        "exchange": "SZSE",
        "vt_symbol": "002415.SZSE",
        "name": "炸板股",
        "close_price": 20.1,
        "change_pct": 8.5,
        "first_limit_time": "10:00:00",
        "last_limit_time": "14:00:00",
        "limit_up_count": None,
        "limit_amount": 5.0,
        "raw": {"代码": "002415", "炸板次数": 4, "涨停统计": "1/1", "所属行业": "电子"},
    }


def _strong_item() -> dict:
    """空时间(None/"")与字符串炸板次数的容错。"""
    return {
        "symbol": "000001",
        "exchange": "SZSE",
        "vt_symbol": "000001.SZSE",
        "name": "强势股甲",
        "close_price": 10.0,
        "change_pct": 5.0,
        "first_limit_time": None,
        "last_limit_time": "",
        "limit_up_count": None,
        "limit_amount": None,
        "raw": {"代码": "000001", "涨停统计": "13/9", "炸板次数": "2"},
    }


def _fake_pools() -> dict:
    return {
        "trade_date": "20260812",
        "source": "akshare.stock_ztb_em",
        "updated_at": "2026-08-12T11:00:00+00:00",
        "pools": {
            "zt": {"label": "涨停池", "total": 2, "items": [_zt_item(), _zt_item_colon_time()]},
            "zbgc": {"label": "炸板池", "total": 1, "items": [_zbgc_item()]},
            "dtgc": {"label": "跌停池", "total": 0, "items": [], "status": "unavailable"},
            "zt_previous": {"label": "昨日涨停", "total": 0, "items": []},
            "strong": {"label": "强势股", "total": 1, "items": [_strong_item()]},
        },
    }


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    monkeypatch.setattr(
        AkShareAdapter, "limit_up_pools", lambda self, trade_date=None, **kw: payload
    )


def _rows(session, pool_type: str) -> list[dict]:
    result = session.execute(
        select(TABLE).where(TABLE.c.pool_type == pool_type)
    ).mappings()
    return list(result)


# ── 解析 + 幂等 ──────────────────────────────────────────────────────────


def test_archive_parses_and_is_idempotent(fake_session, monkeypatch):
    _patch_adapter(monkeypatch, _fake_pools())

    n1 = archive_daily_pools(fake_session, D)
    n2 = archive_daily_pools(fake_session, D)

    assert n1["rows_written"] == n2["rows_written"] == 4
    assert n1["trade_date"] == "2026-08-12"
    assert n1["pools"] == {"zt": 2, "zbgc": 1, "dtgc": 0, "zt_previous": 0, "strong": 1}
    assert n1["unavailable"] == ["dtgc"]
    assert n1["truncated"] == []

    # 幂等: 跑两次后同 (pool_type, vt_symbol) 仍只有一行
    dupes = fake_session.execute(
        select(TABLE.c.pool_type, TABLE.c.vt_symbol, func.count())
        .group_by(TABLE.c.pool_type, TABLE.c.vt_symbol)
        .having(func.count() > 1)
    ).all()
    assert dupes == []
    total = fake_session.execute(select(func.count()).select_from(TABLE)).scalar()
    assert total == 4

    # zt 首行: 全字段解析
    row = next(r for r in _rows(fake_session, "zt") if r["vt_symbol"] == "300862.SZSE")
    assert row["trade_date"] == D
    assert row["name"] == "蓝盾光电"
    assert row["close_price"] == 32.84
    assert row["change_pct"] == 19.985
    assert row["turnover_rate"] == 1.37
    assert row["volume_ratio"] == 1.5
    assert row["limit_amount"] == 637629978.0
    assert row["limit_up_count"] == 3
    assert row["first_limit_time"] == "09:25:00"
    assert row["last_limit_time"] == "09:48:00"
    assert row["break_count"] == 1
    assert row["limit_stat_days"] == 3
    assert row["limit_stat_boards"] == 3
    assert row["industry"] == "通用设备"
    assert row["amount"] == 68193574.0
    assert row["source"] == "akshare.stock_ztb_em"
    assert row["raw"]["代码"] == "300862"
    assert row["raw"]["涨停统计"] == "3/3"

    # zt 次行: raw 缺字段 → None
    row2 = next(r for r in _rows(fake_session, "zt") if r["vt_symbol"] == "600001.SSE")
    assert row2["first_limit_time"] == "09:48:00"
    assert row2["last_limit_time"] == "13:05:00"
    assert row2["break_count"] is None
    assert row2["limit_stat_days"] is None
    assert row2["limit_stat_boards"] is None
    assert row2["industry"] is None
    assert row2["amount"] is None

    # strong 行: None/"" 时间 → None; 字符串炸板次数 → int
    strong = _rows(fake_session, "strong")[0]
    assert strong["first_limit_time"] is None
    assert strong["last_limit_time"] is None
    assert strong["break_count"] == 2
    assert strong["limit_stat_days"] == 13
    assert strong["limit_stat_boards"] == 9

    # zbgc 行
    zbgc = _rows(fake_session, "zbgc")[0]
    assert zbgc["break_count"] == 4
    assert zbgc["first_limit_time"] == "10:00:00"
    assert zbgc["industry"] == "电子"


def test_archive_pool_counts_cover_all_five_pool_types():
    assert POOL_TYPES == ("zt", "zbgc", "dtgc", "zt_previous", "strong")


def test_archive_requests_full_untruncated_pools(fake_session, monkeypatch):
    """归档路径必须向适配器要全量(per_pool_limit=None), 不吃 live 的 200 行截断。"""
    captured: dict[str, object] = {}

    def fake_limit_up_pools(self, trade_date=None, *, per_pool_limit=200):
        captured["trade_date"] = trade_date
        captured["per_pool_limit"] = per_pool_limit
        return _fake_pools()

    monkeypatch.setattr(AkShareAdapter, "limit_up_pools", fake_limit_up_pools)

    archive_daily_pools(fake_session, D)

    assert captured["trade_date"] == "20260812"
    assert captured["per_pool_limit"] is None


# ── 涨停统计解析 ─────────────────────────────────────────────────────────


def test_limit_stat_parsing():
    assert _parse_limit_stat("13/9") == (13, 9)
    assert _parse_limit_stat("1/1") == (1, 1)
    assert _parse_limit_stat(None) == (None, None)
    assert _parse_limit_stat("") == (None, None)
    assert _parse_limit_stat("abc") == (None, None)
    assert _parse_limit_stat("-") == (None, None)
    assert _parse_limit_stat("3/") == (3, None)
    assert _parse_limit_stat("/3") == (None, 3)


# ── 不可用池: 跳过不抹数据; 正常但空: 显式清零 ────────────────────────────


def test_unavailable_pool_is_skipped_without_touching_rows(fake_session, monkeypatch):
    """接口不可用/池 key 缺失 → 跳过该池(不 delete 不 insert), 透出 unavailable。"""
    payload = {
        "trade_date": "20260812",
        "source": "akshare.stock_ztb_em",
        "pools": {
            # zt 接口不可用; 其余四池干脆缺失(视同 unavailable)
            "zt": {"label": "涨停池", "total": 0, "items": [], "status": "unavailable"},
        },
    }
    _patch_adapter(monkeypatch, payload)

    result = archive_daily_pools(fake_session, D)

    assert result["rows_written"] == 0
    assert result["pools"] == {pool: 0 for pool in POOL_TYPES}
    assert result["unavailable"] == list(POOL_TYPES)
    assert result["truncated"] == []
    total = fake_session.execute(select(func.count()).select_from(TABLE)).scalar()
    assert total == 0


def test_unavailable_pool_preserves_existing_rows(fake_session, monkeypatch):
    """核心回归: 先归档好数据 → 重跑遇 unavailable → 该池旧数据保留;
    正常返回但 items 为空的池 → delete+insert 0 行(明确的"当日无数据")。"""
    _patch_adapter(monkeypatch, _fake_pools())
    archive_daily_pools(fake_session, D)
    assert len(_rows(fake_session, "zt")) == 2
    assert len(_rows(fake_session, "strong")) == 1

    second = _fake_pools()
    second["pools"]["zt"] = {
        "label": "涨停池", "total": 0, "items": [], "status": "unavailable",
    }
    # zbgc 池 key 整个缺失, 视同 unavailable
    del second["pools"]["zbgc"]
    # dtgc/strong 正常返回但当日无数据
    second["pools"]["dtgc"] = {"label": "跌停池", "total": 0, "items": []}
    second["pools"]["strong"] = {"label": "强势股", "total": 0, "items": []}
    _patch_adapter(monkeypatch, second)

    result = archive_daily_pools(fake_session, D)

    assert result["unavailable"] == ["zt", "zbgc"]
    assert result["rows_written"] == 0
    # 不可用池: 旧行保留
    assert len(_rows(fake_session, "zt")) == 2
    assert len(_rows(fake_session, "zbgc")) == 1
    # 正常但空的池: 旧行被显式清掉
    assert _rows(fake_session, "strong") == []


def test_truncated_pool_is_flagged(fake_session, monkeypatch):
    """防御: total > len(items)(仍被截断)时透出 truncated 告警, 行照写。"""
    payload = _fake_pools()
    payload["pools"]["zt"] = {
        "label": "涨停池",
        "total": 5,  # 适配器说全量 5 行, 实际只给了 2 行
        "items": [_zt_item(), _zt_item_colon_time()],
    }
    _patch_adapter(monkeypatch, payload)

    result = archive_daily_pools(fake_session, D)

    assert result["truncated"] == ["zt"]
    assert result["pools"]["zt"] == 2
    assert len(_rows(fake_session, "zt")) == 2


def test_duplicate_and_empty_vt_symbol_items_are_dropped(fake_session, monkeypatch):
    dup = _zt_item()
    payload = _fake_pools()
    payload["pools"]["zt"] = {
        "label": "涨停池",
        "total": 3,
        "items": [dup, dict(dup), {**_zt_item_colon_time(), "vt_symbol": ""}],
    }
    for pool in ("zbgc", "dtgc", "zt_previous", "strong"):
        payload["pools"][pool] = {"label": pool, "total": 0, "items": []}
    _patch_adapter(monkeypatch, payload)

    result = archive_daily_pools(fake_session, D)

    assert result["pools"]["zt"] == 1
    # total=3 与 payload items 数一致(去重发生在 archive 层), 不算截断
    assert result["truncated"] == []
    rows = _rows(fake_session, "zt")
    assert [r["vt_symbol"] for r in rows] == ["300862.SZSE"]


# ── data_sync runner 接线 ────────────────────────────────────────────────


def test_data_sync_runner_wires_archive(monkeypatch):
    """JOB_RUNNERS 指向的方法: 解析参数→开 session→调 archive_daily_pools→补 message。"""
    from contextlib import contextmanager

    from alphaagent.server.services import data_sync as svc

    captured: dict[str, object] = {}

    def fake_archive(session, trade_date, *, adapter=None):
        captured["session"] = session
        captured["trade_date"] = trade_date
        captured["adapter"] = adapter
        return {
            "trade_date": trade_date.isoformat(),
            "pools": {"zt": 2, "zbgc": 0, "dtgc": 0, "zt_previous": 0, "strong": 0},
            "rows_written": 2,
            "unavailable": ["dtgc"],
            "truncated": [],
        }

    sentinel_session = object()
    sentinel_adapter = object()

    @contextmanager
    def fake_session_scope():
        yield sentinel_session

    monkeypatch.setattr(archive_mod, "archive_daily_pools", fake_archive)
    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    method_name = svc.JOB_RUNNERS["sync_limit_up_pool_snapshots"]
    runner = svc.DataSyncRunner(adapter=sentinel_adapter)
    result = getattr(runner, method_name)({"trade_date": "2026-08-12"})

    assert captured["session"] is sentinel_session
    assert captured["trade_date"] == D
    assert captured["adapter"] is sentinel_adapter
    assert result["rows_written"] == 2
    # 不可用池在 message 里透出(运维可观测)
    assert "dtgc" in result["message"]


def test_data_sync_runner_rejects_invalid_trade_date(monkeypatch):
    """手动传非法 trade_date 直接报错, 不静默回落到当天。"""
    from alphaagent.server.services import data_sync as svc

    method_name = svc.JOB_RUNNERS["sync_limit_up_pool_snapshots"]
    runner = svc.DataSyncRunner(adapter=object())

    with pytest.raises(svc.DataSyncError, match="trade_date"):
        getattr(runner, method_name)({"trade_date": "not-a-date"})
