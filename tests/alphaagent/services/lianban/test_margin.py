"""两市融资余额 sync_margin_balance: 沪深合并 / 窗口 / 幂等 / 容错 / latest 查询。

全部 monkeypatch margin._load_margin_module 返回的假模块, 不碰网络, 也不要求
宿主机安装 akshare; 落库用 sqlite 内存库真实验证 delete+insert 幂等
(见 conftest.fake_session)。

DataFrame 形状按 2026-08-13 容器实测的 akshare 1.18.64
macro_china_market_margin_sh/sz: 日期列为 datetime.date, 金额列为 int64(元),
深市 融券卖出量/融券余量 可为 NaN。
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.services.lianban import margin as margin_mod
from alphaagent.server.services.lianban.margin import (
    latest_margin_balance,
    sync_margin_balance,
)

TABLE = schema.market_margin_balance

# 2026-08-12 实测真值: 沪 1355236713043 元, 深 1283743xxxxx 元量级
D3 = date(2026, 8, 12)
D2 = date(2026, 8, 11)
D1 = date(2026, 8, 10)


def _margin_df(rows: list[dict]) -> pd.DataFrame:
    """按实测列序构造宏观接口 DataFrame。"""
    return pd.DataFrame(
        rows,
        columns=["日期", "融资买入额", "融资余额", "融券卖出量", "融券余量", "融券余额", "融资融券余额"],
    )


def _sh_row(d: date, balance: float, buy: float = 1.0, total: float | None = None) -> dict:
    return {
        "日期": d,
        "融资买入额": buy,
        "融资余额": balance,
        "融券卖出量": 53358620,
        "融券余量": 2857487536,
        "融券余额": 16384355332,
        "融资融券余额": total if total is not None else balance + 1e10,
    }


def _sz_row(d: date, balance: float, buy: float = 2.0, total: float | None = None) -> dict:
    # 深市实测 融券卖出量/融券余量 为 NaN
    return {
        "日期": d,
        "融资买入额": buy,
        "融资余额": balance,
        "融券卖出量": float("nan"),
        "融券余量": float("nan"),
        "融券余额": 9.0e9,
        "融资融券余额": total if total is not None else balance + 9e9,
    }


def _fake_module(sh_df: pd.DataFrame, sz_df: pd.DataFrame) -> SimpleNamespace:
    return SimpleNamespace(
        macro_china_market_margin_sh=lambda: sh_df,
        macro_china_market_margin_sz=lambda: sz_df,
    )


def _patch_module(monkeypatch: pytest.MonkeyPatch, module) -> None:
    monkeypatch.setattr(margin_mod, "_load_margin_module", lambda: module)


def _rows(session) -> list[dict]:
    result = session.execute(select(TABLE).order_by(TABLE.c.trade_date)).mappings()
    return list(result)


# ── 合并 + 幂等 ──────────────────────────────────────────────────────────


def test_sync_merges_exchanges_and_is_idempotent(fake_session, monkeypatch):
    sh = _margin_df([
        _sh_row(D1, 100.0, buy=11.0, total=110.0),
        _sh_row(D2, 200.0, buy=12.0, total=210.0),
        _sh_row(D3, 1355236713043.0, buy=100793375419.0, total=1371828633474.0),
    ])
    sz = _margin_df([
        _sz_row(D1, 50.0, buy=21.0, total=55.0),
        _sz_row(D2, 80.0, buy=22.0, total=88.0),
        _sz_row(D3, 1283743543210.0, buy=100877500000.0, total=1292941000000.0),
    ])
    _patch_module(monkeypatch, _fake_module(sh, sz))

    r1 = sync_margin_balance(fake_session)
    r2 = sync_margin_balance(fake_session)

    assert r1["rows_written"] == r2["rows_written"] == 3
    assert r1["trade_dates"] == ["2026-08-10", "2026-08-11", "2026-08-12"]
    assert r1["latest"] == {
        "trade_date": "2026-08-12",
        "margin_balance": 1355236713043.0 + 1283743543210.0,
    }

    # 幂等: 跑两次后每日仍只有一行
    total = fake_session.execute(select(func.count()).select_from(TABLE)).scalar()
    assert total == 3

    rows = {r["trade_date"]: r for r in _rows(fake_session)}
    latest = rows[D3]
    assert latest["sse_balance"] == 1355236713043.0
    assert latest["szse_balance"] == 1283743543210.0
    assert latest["margin_balance"] == 1355236713043.0 + 1283743543210.0
    assert latest["source"] == "akshare.macro_china_market_margin"
    # raw 保留两市明细(买入额/两融总额), 供审计
    assert latest["raw"]["sse"]["buy"] == 100793375419.0
    assert latest["raw"]["sse"]["total"] == 1371828633474.0
    assert latest["raw"]["szse"]["buy"] == 100877500000.0

    row_d1 = rows[D1]
    assert row_d1["margin_balance"] == 150.0
    assert row_d1["sse_balance"] == 100.0
    assert row_d1["szse_balance"] == 50.0


def test_sync_only_writes_dates_present_in_both_exchanges(fake_session, monkeypatch):
    """深市缺 D1(单边未发布) → 只写两市都有的 D2/D3, 合计不缺腿。"""
    sh = _margin_df([_sh_row(D1, 100.0), _sh_row(D2, 200.0), _sh_row(D3, 300.0)])
    sz = _margin_df([_sz_row(D2, 80.0), _sz_row(D3, 90.0)])
    _patch_module(monkeypatch, _fake_module(sh, sz))

    result = sync_margin_balance(fake_session)

    assert result["trade_dates"] == ["2026-08-11", "2026-08-12"]
    assert result["rows_written"] == 2
    assert [r["trade_date"] for r in _rows(fake_session)] == [D2, D3]


def test_sync_window_anchors_on_latest_common_date(fake_session, monkeypatch):
    """窗口以共同最新日为锚向前 lookback_days 个自然日, 不依赖本机时钟。"""
    base = D3
    sh = _margin_df([_sh_row(base - timedelta(days=i), 100.0 + i) for i in range(30)])
    sz = _margin_df([_sz_row(base - timedelta(days=i), 50.0 + i) for i in range(30)])
    _patch_module(monkeypatch, _fake_module(sh, sz))

    result = sync_margin_balance(fake_session, lookback_days=10)

    written = [r["trade_date"] for r in _rows(fake_session)]
    assert max(written) == base
    assert min(written) == base - timedelta(days=10)
    assert result["rows_written"] == len(written) == 11


def test_sync_skips_malformed_rows(fake_session, monkeypatch):
    """坏日期 / 缺失或 NaN 融资余额的行跳过; 空 DataFrame 不报错。"""
    sh = _margin_df([
        _sh_row(D3, 300.0),
        {"日期": "not-a-date", "融资买入额": 1, "融资余额": 5, "融券卖出量": 0,
         "融券余量": 0, "融券余额": 0, "融资融券余额": 5},
        {"日期": D2, "融资买入额": 1, "融资余额": None, "融券卖出量": 0,
         "融券余量": 0, "融券余额": 0, "融资融券余额": 0},
    ])
    sz = _margin_df([
        _sz_row(D3, 90.0),
        {"日期": D2, "融资买入额": 1, "融资余额": float("nan"), "融券卖出量": 0,
         "融券余量": 0, "融券余额": 0, "融资融券余额": 0},
    ])
    _patch_module(monkeypatch, _fake_module(sh, sz))

    result = sync_margin_balance(fake_session)

    assert result["trade_dates"] == ["2026-08-12"]
    rows = _rows(fake_session)
    assert len(rows) == 1
    assert rows[0]["margin_balance"] == 390.0

    # 两边都空 → 0 行, latest=None
    _patch_module(monkeypatch, _fake_module(_margin_df([]), _margin_df([])))
    empty = sync_margin_balance(fake_session)
    assert empty["rows_written"] == 0
    assert empty["trade_dates"] == []
    assert empty["latest"] is None


# ── 容错: 数据源不可用不报错, 不动旧数据 ──────────────────────────────────


def test_sync_source_unavailable_returns_zero_and_preserves_rows(fake_session, monkeypatch):
    sh = _margin_df([_sh_row(D3, 300.0)])
    sz = _margin_df([_sz_row(D3, 90.0)])
    _patch_module(monkeypatch, _fake_module(sh, sz))
    assert sync_margin_balance(fake_session)["rows_written"] == 1

    def _boom():
        raise ConnectionError("jin10 timeout")

    _patch_module(
        monkeypatch,
        SimpleNamespace(
            macro_china_market_margin_sh=_boom,
            macro_china_market_margin_sz=lambda: sz,
        ),
    )
    result = sync_margin_balance(fake_session)

    assert result["rows_written"] == 0
    assert result["trade_dates"] == []
    assert result["latest"] is None
    assert "ConnectionError" in result["error"]
    # 旧数据保留
    assert len(_rows(fake_session)) == 1


def test_sync_import_failure_is_tolerated(fake_session, monkeypatch):
    """宿主机无 akshare: import 失败同样 rows_written=0 不抛错。"""

    def _no_akshare():
        raise ModuleNotFoundError("No module named 'akshare'")

    monkeypatch.setattr(margin_mod, "_load_margin_module", _no_akshare)

    result = sync_margin_balance(fake_session)

    assert result["rows_written"] == 0
    assert "akshare" in result["error"]


# ── latest_margin_balance ────────────────────────────────────────────────


def test_latest_margin_balance_empty_table(fake_session):
    assert latest_margin_balance(fake_session) is None


def test_latest_margin_balance_single_row_change_is_none(fake_session, monkeypatch):
    _patch_module(
        monkeypatch,
        _fake_module(_margin_df([_sh_row(D3, 300.0)]), _margin_df([_sz_row(D3, 90.0)])),
    )
    sync_margin_balance(fake_session)

    latest = latest_margin_balance(fake_session)

    assert latest == {"trade_date": "2026-08-12", "margin_balance": 390.0, "change": None}


def test_latest_margin_balance_computes_change(fake_session, monkeypatch):
    """change = 最新 - 前一交易日(2.65 万亿 +95 亿 口径)。"""
    sh = _margin_df([_sh_row(D2, 200.0), _sh_row(D3, 300.0)])
    sz = _margin_df([_sz_row(D2, 80.0), _sz_row(D3, 90.0)])
    _patch_module(monkeypatch, _fake_module(sh, sz))
    sync_margin_balance(fake_session)

    latest = latest_margin_balance(fake_session)

    assert latest["trade_date"] == "2026-08-12"
    assert latest["margin_balance"] == 390.0
    assert latest["change"] == 390.0 - 280.0


# ── data_sync 注册与 runner 接线 ─────────────────────────────────────────


def test_margin_job_registered_in_data_sync():
    from alphaagent.server.services import data_sync as svc

    job = next(item for item in svc.DEFAULT_JOBS if item.id == "sync_margin_balance")
    assert job.name == "两市融资余额"
    assert job.source_id == "akshare"
    assert job.target_table == "market_margin_balance"
    assert svc.JOB_RUNNERS["sync_margin_balance"] == "_run_sync_margin_balance"

    cad = svc.JOB_CADENCES["sync_margin_balance"]
    assert cad.cadence == svc.CADENCE_EOD_DAILY
    assert cad.freshness_table == "market_margin_balance"

    assert job.id in svc._RECOMMENDED_PRIORITY
    # 尾部: 交易所晚间公布, 依赖越少越靠后; 潜龙首板盘后定版必须压在最后
    # (依赖日线 + 连板重建的全部产出)
    for schedule_id in ("eod_1900", "eod_finalize_2130"):
        schedule = next(
            item for item in svc.DEFAULT_BATCH_SCHEDULES if item["id"] == schedule_id
        )
        assert schedule["job_ids"][-3] == "sync_margin_balance"
        assert schedule["job_ids"][-2] == "qianlong_eod_finalize"
        assert schedule["job_ids"][-1] == "w2s_eod_finalize"


def test_data_sync_runner_wires_margin_sync(monkeypatch):
    """JOB_RUNNERS 指向的方法: 解析参数→开 session→调 sync_margin_balance→补 message。"""
    from contextlib import contextmanager

    from alphaagent.server.services import data_sync as svc

    captured: dict[str, object] = {}

    def fake_sync(session, *, lookback_days=10):
        captured["session"] = session
        captured["lookback_days"] = lookback_days
        return {
            "trade_dates": ["2026-08-12"],
            "rows_written": 1,
            "latest": {"trade_date": "2026-08-12", "margin_balance": 2.638979713043e12},
        }

    sentinel_session = object()

    @contextmanager
    def fake_session_scope():
        yield sentinel_session

    monkeypatch.setattr(margin_mod, "sync_margin_balance", fake_sync)
    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    method_name = svc.JOB_RUNNERS["sync_margin_balance"]
    runner = svc.DataSyncRunner(adapter=object())
    result = getattr(runner, method_name)({"lookback_days": 7})

    assert captured["session"] is sentinel_session
    assert captured["lookback_days"] == 7
    assert result["rows_written"] == 1
    assert "2026-08-12" in result["message"]


def test_data_sync_runner_surfaces_source_error_in_message(monkeypatch):
    """数据源不可用时 job 不失败, message 透出原因(运维可观测)。"""
    from contextlib import contextmanager

    from alphaagent.server.services import data_sync as svc

    def fake_sync(session, *, lookback_days=10):
        return {
            "trade_dates": [],
            "rows_written": 0,
            "latest": None,
            "error": "ConnectionError: jin10 timeout",
        }

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(margin_mod, "sync_margin_balance", fake_sync)
    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    method_name = svc.JOB_RUNNERS["sync_margin_balance"]
    runner = svc.DataSyncRunner(adapter=object())
    result = getattr(runner, method_name)({})

    assert result["rows_written"] == 0
    assert "数据源不可用" in result["message"]
    assert "ConnectionError" in result["message"]
