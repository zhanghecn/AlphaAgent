"""连板双口径对账: parity_report / latest_parity_report + 数据健康接入。

sqlite 内存库真实落库(见 conftest.fake_session); 健康摘要为纯函数,
直接构造 report dict 验证 verdict/status → health 映射。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import insert

from alphaagent.server.db import schema
from alphaagent.server.services import data_sync as svc
from alphaagent.server.services.lianban.parity import (
    latest_common_trade_date,
    latest_parity_report,
    parity_report,
)

D1 = date(2026, 8, 11)
D2 = date(2026, 8, 12)

AAA = "600001.SSE"
BBB = "600002.SSE"
CCC = "000001.SZSE"
DDD = "300001.SZSE"
EEE = "600003.SSE"
SST = "600004.SSE"
GHOST = "600999.SSE"  # 不落 stocks 表, 验证名称缺失容错


def _stock(sym: str, name: str) -> dict:
    code, exchange = sym.split(".")
    return {
        "vt_symbol": sym,
        "symbol": code,
        "exchange": exchange,
        "name": name,
        "source": "test",
    }


def _pool(d: date, sym: str, name: str, pool: str = "zt") -> dict:
    return {
        "trade_date": d,
        "pool_type": pool,
        "vt_symbol": sym,
        "name": name,
        "source": "test",
    }


def _daily(
    d: date, sym: str, *, is_up: bool = True, is_st: bool = False, touched: bool = False
) -> dict:
    return {
        "trade_date": d,
        "vt_symbol": sym,
        "is_limit_up": is_up,
        "limit_up_count": 1 if is_up else 0,
        "is_one_word": False,
        "is_st": is_st,
        "board": "main",
        "touched_limit": touched,
        "source": "daily_rebuild",
    }


def _seed_stocks(session) -> None:
    session.execute(insert(schema.stocks), [
        _stock(AAA, "甲股份"), _stock(BBB, "乙股份"), _stock(CCC, "丙股份"),
        _stock(DDD, "丁股份"), _stock(EEE, "戊股份"), _stock(SST, "ST测试"),
    ])


# ── parity_report: 双侧有数据 ────────────────────────────────────────────


def test_aligned_when_both_sides_match(fake_session):
    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"), _pool(D2, BBB, "乙股份"), _pool(D2, CCC, "丙股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D2, AAA), _daily(D2, BBB), _daily(D2, CCC),
    ])

    report = parity_report(fake_session, D2)

    assert report["trade_date"] == "2026-08-12"
    assert report["status"] == "ok"
    assert report["em_count"] == 3
    assert report["daily_count"] == 3
    assert report["matched"] == 3
    assert report["diff_count"] == 0
    assert report["em_only"] == []
    assert report["daily_only"] == []
    assert report["verdict"] == "aligned"


def test_minor_diff_threshold(fake_session):
    # diff = 2: 丁股份仅东财(日线漏判), 丙股份仅日线(东财漏收)
    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"), _pool(D2, BBB, "乙股份"), _pool(D2, DDD, "丁股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D2, AAA), _daily(D2, BBB), _daily(D2, CCC),
    ])

    report = parity_report(fake_session, D2)

    assert report["status"] == "ok"
    assert report["matched"] == 2
    assert report["diff_count"] == 2
    assert report["verdict"] == "minor_diff"
    assert report["em_only"] == [{"vt_symbol": DDD, "name": "丁股份"}]
    assert report["daily_only"] == [{"vt_symbol": CCC, "name": "丙股份"}]


def test_major_diff_threshold(fake_session):
    # diff = 3: 丁/戊仅东财, 丙仅日线
    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"), _pool(D2, EEE, "戊股份"), _pool(D2, DDD, "丁股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D2, AAA), _daily(D2, CCC),
    ])

    report = parity_report(fake_session, D2)

    assert report["diff_count"] == 3
    assert report["verdict"] == "major_diff"
    # 差异名单按 vt_symbol 排序, 输出稳定
    assert report["em_only"] == [
        {"vt_symbol": DDD, "name": "丁股份"},
        {"vt_symbol": EEE, "name": "戊股份"},
    ]
    assert report["daily_only"] == [{"vt_symbol": CCC, "name": "丙股份"}]


def test_daily_side_excludes_st(fake_session):
    """日线侧 is_st=True 的涨停行不计入(对齐东财池不含 ST 的口径)。"""
    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D2, AAA), _daily(D2, SST, is_st=True),
    ])

    report = parity_report(fake_session, D2)

    assert report["daily_count"] == 1
    assert report["matched"] == 1
    assert report["diff_count"] == 0
    assert report["verdict"] == "aligned"
    assert all(item["vt_symbol"] != SST for item in report["daily_only"])


def test_touched_rows_not_counted_but_prove_daily_presence(fake_session):
    """摸板行(is_limit_up=False)不计入涨停名单, 但证明当日重建已跑 → 非 missing_daily。"""
    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D2, BBB, is_up=False, touched=True),
    ])

    report = parity_report(fake_session, D2)

    assert report["status"] == "ok"
    assert report["daily_count"] == 0
    assert report["em_only"] == [{"vt_symbol": AAA, "name": "甲股份"}]
    assert report["diff_count"] == 1
    assert report["verdict"] == "minor_diff"


def test_daily_only_name_resolution_and_unknown_symbol(fake_session):
    """daily_only 名称取 stocks 表; stocks 未收录的符号名称容错为 None。"""
    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D2, AAA), _daily(D2, GHOST),
    ])

    report = parity_report(fake_session, D2)

    assert report["daily_only"] == [{"vt_symbol": GHOST, "name": None}]


# ── parity_report: 缺侧不炸 ──────────────────────────────────────────────


def test_missing_pool(fake_session):
    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.stock_limit_up_daily), [_daily(D2, AAA)])

    report = parity_report(fake_session, D2)

    assert report["status"] == "missing_pool"
    assert report["em_count"] == 0
    assert report["daily_count"] == 1
    assert report["matched"] == 0
    assert report["diff_count"] == 0
    assert report["em_only"] == []
    assert report["daily_only"] == []


def test_missing_daily(fake_session):
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"),
    ])

    report = parity_report(fake_session, D2)

    assert report["status"] == "missing_daily"
    assert report["em_count"] == 1
    assert report["daily_count"] == 0
    assert report["em_only"] == []
    assert report["daily_only"] == []


def test_missing_both(fake_session):
    report = parity_report(fake_session, D2)

    assert report["status"] == "missing_both"
    assert report["em_count"] == 0
    assert report["daily_count"] == 0
    assert report["em_only"] == []
    assert report["daily_only"] == []


# ── latest_common_trade_date / latest_parity_report ──────────────────────


def test_latest_common_trade_date_picks_overlap(fake_session):
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D1, AAA, "甲股份"), _pool(D2, AAA, "甲股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [_daily(D1, AAA)])

    assert latest_common_trade_date(fake_session) == D1


def test_latest_common_trade_date_none_without_overlap(fake_session):
    assert latest_common_trade_date(fake_session) is None

    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [_daily(D1, AAA)])
    assert latest_common_trade_date(fake_session) is None


def test_latest_parity_report(fake_session):
    assert latest_parity_report(fake_session) is None

    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D1, AAA, "甲股份"), _pool(D2, BBB, "乙股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D1, AAA), _daily(D2, BBB),
    ])

    report = latest_parity_report(fake_session)
    assert report["trade_date"] == "2026-08-12"
    assert report["status"] == "ok"
    assert report["verdict"] == "aligned"


# ── 数据健康接入: _parity_health_summary 纯函数 + _lianban_parity_health ──


def _report(status: str = "ok", verdict: str = "aligned", diff: int = 0) -> dict:
    return {
        "trade_date": "2026-08-12",
        "status": status,
        "em_count": 3,
        "daily_count": 3,
        "matched": 3 - diff,
        "diff_count": diff,
        "em_only": [],
        "daily_only": [],
        "verdict": verdict,
    }


def test_parity_health_summary_mapping():
    assert svc._parity_health_summary(None)["health"] == "unknown"
    assert svc._parity_health_summary(_report())["health"] == "ok"
    minor = svc._parity_health_summary(_report(verdict="minor_diff", diff=2))
    assert minor["health"] == "ok"
    major = svc._parity_health_summary(_report(verdict="major_diff", diff=3))
    assert major["health"] == "warning"
    assert major["diff_count"] == 3
    assert major["trade_date"] == "2026-08-12"
    for missing in ("missing_pool", "missing_daily", "missing_both"):
        assert svc._parity_health_summary(_report(status=missing))["health"] == "warning"


@contextmanager
def _session_ctx(session):
    yield session


def test_lianban_parity_health_with_fake_session(fake_session, monkeypatch):
    """健康巡检走真实 parity 查询(session 替换为 sqlite 内存库)。"""
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "session_scope", lambda: _session_ctx(fake_session))

    assert svc._lianban_parity_health()["health"] == "unknown"  # 空库无重叠日

    _seed_stocks(fake_session)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, AAA, "甲股份"), _pool(D2, BBB, "乙股份"),
    ])
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D2, AAA), _daily(D2, BBB),
    ])
    health = svc._lianban_parity_health()
    assert health["health"] == "ok"
    assert health["trade_date"] == "2026-08-12"
    assert health["em_count"] == 2

    # 再加 3 只仅东财 → diff=3 → major_diff → warning
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D2, CCC, "丙股份"), _pool(D2, DDD, "丁股份"), _pool(D2, EEE, "戊股份"),
    ])
    health = svc._lianban_parity_health()
    assert health["health"] == "warning"
    assert health["verdict"] == "major_diff"
    assert health["diff_count"] == 3
