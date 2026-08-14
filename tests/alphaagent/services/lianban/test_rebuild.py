"""连板梯队日线重建:纯函数递推 iter_limit_up_daily + 落库薄壳 run_rebuild。

纯函数部分直接构造 BarRow 流;run_rebuild 编排部分照本仓库惯例
monkeypatch 模块内 DB 辅助函数(_max_trade_date/_load_*/_scan_bars/
_delete_rows/_insert_rows),不依赖真实数据库。
"""
from __future__ import annotations

from datetime import date
from typing import NamedTuple

import pytest

from alphaagent.server.db import schema
from alphaagent.server.services.lianban import rebuild as rb
from alphaagent.server.services.lianban.rebuild import (
    BarRow,
    iter_limit_up_daily,
    run_rebuild,
)

D0 = date(2026, 8, 7)
D1 = date(2026, 8, 10)
D2 = date(2026, 8, 11)
D3 = date(2026, 8, 12)


def _bar(vt, td, o, h, low, c, prev=None, name="测试股"):
    return BarRow(
        vt_symbol=vt,
        trade_date=td,
        open=o,
        high=h,
        low=low,
        close=c,
        prev_close=prev,
        name=name,
    )


# ── 纯函数 iter_limit_up_daily ──────────────────────────────────────────


def test_streak_chain_and_break_reset():
    # 股A 主板三日连板: prev 10.00 → 11.00 → 12.10 → 13.31 (count 1→2→3)
    # 股B: 涨停 → 断板(未摸板不 yield) → 再涨停(count 1→1)
    rows = [
        _bar("600001.SSE", D1, 10.20, 11.00, 10.10, 11.00, prev=10.00),
        # 非流内首根: 传入的 prev_close 必须被忽略(流内递推 11.00)
        _bar("600001.SSE", D2, 11.20, 12.10, 11.10, 12.10, prev=999.99),
        _bar("600001.SSE", D3, 12.30, 13.31, 12.20, 13.31, prev=999.99),
        _bar("600002.SSE", D1, 10.20, 11.00, 10.10, 11.00, prev=10.00),
        # 断板日: close 11.50 非涨停, high 11.60 未触及 12.10 → 不 yield
        _bar("600002.SSE", D2, 11.10, 11.60, 11.00, 11.50, prev=999.99),
        # prev=11.50(流内) ×1.1 = 12.65 → 再涨停, streak 重新从 1 计
        _bar("600002.SSE", D3, 11.80, 12.65, 11.70, 12.65, prev=999.99),
    ]
    out = list(iter_limit_up_daily(rows))

    a = {r["trade_date"]: r["limit_up_count"] for r in out if r["vt_symbol"] == "600001.SSE"}
    assert a == {D1: 1, D2: 2, D3: 3}

    b = [r for r in out if r["vt_symbol"] == "600002.SSE"]
    assert [r["limit_up_count"] for r in b] == [1, 1]  # 断板日无涨停行
    assert all(r["is_limit_up"] for r in b)

    # change_pct / prev_close 由流内递推值计算, 不受传入 prev_close 干扰
    a_d2 = next(r for r in out if r["vt_symbol"] == "600001.SSE" and r["trade_date"] == D2)
    assert a_d2["prev_close"] == 11.00
    assert a_d2["change_pct"] == 10.0
    assert a_d2["board"] == "main"


def test_touched_row_yielded_with_is_limit_up_false():
    # high 触板 11.00 但 close 10.50 未封 → 摸板行; 次日普通行不 yield
    rows = [
        _bar("600003.SSE", D1, 10.20, 11.00, 10.10, 10.50, prev=10.00),
        _bar("600003.SSE", D2, 10.60, 10.70, 10.40, 10.60),
    ]
    out = list(iter_limit_up_daily(rows))

    assert len(out) == 1
    r = out[0]
    assert r["trade_date"] == D1
    assert r["is_limit_up"] is False
    assert r["touched_limit"] is True
    assert r["limit_up_count"] == 0
    assert r["close_price"] == 10.50
    assert r["change_pct"] == 5.0
    # detector 契约: 未封板行 limit_price 为 None
    assert r["limit_price"] is None


def test_one_word_flag():
    rows = [_bar("600004.SSE", D1, 11.00, 11.00, 11.00, 11.00, prev=10.00)]
    out = list(iter_limit_up_daily(rows))

    assert len(out) == 1
    assert out[0]["is_limit_up"] is True
    assert out[0]["is_one_word"] is True
    assert out[0]["limit_up_count"] == 1


def test_st_stock_marked_is_st():
    # 主板 ST 5% 幅度链: 20.00 → 21.00 → 22.05
    rows = [
        _bar("600005.SSE", D1, 20.20, 21.00, 20.10, 21.00, prev=20.00, name="ST测试"),
        _bar("600005.SSE", D2, 21.20, 22.05, 21.10, 22.05, name="ST测试"),
    ]
    out = list(iter_limit_up_daily(rows))

    assert [r["limit_up_count"] for r in out] == [1, 2]
    assert all(r["is_st"] for r in out)
    assert out[1]["limit_price"] == 22.05  # 21.00 × 1.05
    assert out[1]["board"] == "main"


def test_first_bar_without_prev_close_is_skipped():
    # 新股首日无昨收: high 12.00 也不判涨停/摸板; 次日流内 prev=11.50 → 涨停
    rows = [
        _bar("600006.SSE", D1, 10.00, 12.00, 9.90, 11.50),
        _bar("600006.SSE", D2, 11.60, 12.65, 11.50, 12.65),
    ]
    out = list(iter_limit_up_daily(rows))

    assert len(out) == 1
    assert out[0]["trade_date"] == D2
    assert out[0]["limit_up_count"] == 1


def test_seed_streaks_continue_across_incremental_window():
    # 增量续推: 种子 streak 只对每股流内首根生效一次
    rows = [
        _bar("600001.SSE", D2, 12.30, 13.31, 12.20, 13.31, prev=12.10),
        _bar("600001.SSE", D3, 13.50, 14.64, 13.40, 14.64),
        _bar("600002.SSE", D2, 10.20, 11.00, 10.10, 11.00, prev=10.00),
    ]
    out = list(iter_limit_up_daily(rows, seed_streaks={"600001.SSE": 2, "600002.SSE": 3}))

    a = [r["limit_up_count"] for r in out if r["vt_symbol"] == "600001.SSE"]
    assert a == [3, 4]
    b = [r["limit_up_count"] for r in out if r["vt_symbol"] == "600002.SSE"]
    assert b == [4]


def test_unsorted_input_raises():
    rows = [
        _bar("600001.SSE", D2, 11.20, 12.10, 11.10, 12.10, prev=11.00),
        _bar("600001.SSE", D1, 10.20, 11.00, 10.10, 11.00, prev=10.00),
    ]
    with pytest.raises(ValueError, match="sorted"):
        list(iter_limit_up_daily(rows))


# ── run_rebuild 编排(monkeypatch DB 辅助函数) ───────────────────────────


class _DbBar(NamedTuple):
    vt_symbol: str
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float


def _db_bar(vt, td, o, h, low, c):
    return _DbBar(vt, td, o, h, low, c)


def _patch_rebuild(
    monkeypatch,
    *,
    bars,
    target,
    last_done,
    names=None,
    seed_streaks=None,
    seed_closes=None,
):
    """把 run_rebuild 的 DB 触点全部换成内存实现, 返回调用记录。"""
    calls = {"deleted": [], "inserted": [], "scan_windows": []}

    def fake_max(session, column):
        # target 必须走完整日闸门; 只有 last_done 允许对 state 表取 max
        assert column.table.name == "stock_limit_up_daily", (
            "default target must come from the complete-day gate, not bars max"
        )
        return last_done

    def fake_scan(session, schema_mod, start_exclusive, end_inclusive):
        calls["scan_windows"].append((start_exclusive, end_inclusive))
        return iter(list(bars))

    monkeypatch.setattr(rb, "_latest_complete_daily_date", lambda s, sch: target)
    monkeypatch.setattr(rb, "_max_trade_date", fake_max)
    monkeypatch.setattr(rb, "_load_name_map", lambda s, sch: dict(names or {}))
    monkeypatch.setattr(rb, "_load_seed_streaks", lambda s, sch, d: dict(seed_streaks or {}))
    monkeypatch.setattr(rb, "_load_seed_closes", lambda s, sch, d: dict(seed_closes or {}))
    monkeypatch.setattr(rb, "_scan_bars", fake_scan)
    monkeypatch.setattr(
        rb, "_delete_rows", lambda s, sch, start, end: calls["deleted"].append((start, end))
    )
    monkeypatch.setattr(
        rb, "_insert_rows", lambda s, sch, rows: calls["inserted"].append(list(rows))
    )
    return calls


def test_run_rebuild_first_run_degenerates_to_full(monkeypatch):
    # last_done=None 首跑: 全表 delete + 全量递推; 首日无昨收跳过
    bars = [
        _db_bar("600001.SSE", D1, 9.90, 10.20, 9.80, 10.00),
        _db_bar("600001.SSE", D2, 10.20, 11.00, 10.10, 11.00),
    ]
    calls = _patch_rebuild(
        monkeypatch, bars=bars, target=D2, last_done=None, names={"600001.SSE": "测试A"}
    )

    result = run_rebuild(object(), schema)

    assert result["mode"] == "full"
    assert calls["deleted"] == [(None, None)]  # 首跑退化 full: delete 全表重写
    assert calls["scan_windows"] == [(None, D2)]
    written = [r for chunk in calls["inserted"] for r in chunk]
    assert len(written) == 1
    assert written[0]["trade_date"] == D2
    assert written[0]["limit_up_count"] == 1
    assert written[0]["is_limit_up"] is True
    assert result["rows_written"] == 1
    assert result["rows_read"] == 2
    assert result["trade_dates"] == [D2]
    assert "elapsed_seconds" in result


def test_run_rebuild_incremental_seeds_state_and_deletes_window(monkeypatch):
    # last_done=D1: 窗口 (D1, D3], 种子 streak=2 / prev_close=12.10 续推
    bars = [
        _db_bar("600001.SSE", D2, 12.30, 13.31, 12.20, 13.31),
        _db_bar("600001.SSE", D3, 13.50, 14.64, 13.40, 14.64),
        # 窗口内新股(无种子 prev_close): 首根跳过判定
        _db_bar("600007.SSE", D2, 10.00, 12.00, 9.90, 11.50),
        _db_bar("600007.SSE", D3, 11.60, 11.80, 11.40, 11.60),
    ]
    calls = _patch_rebuild(
        monkeypatch,
        bars=bars,
        target=D3,
        last_done=D1,
        names={"600001.SSE": "测试A", "600007.SSE": "测试新股"},
        seed_streaks={"600001.SSE": 2},
        seed_closes={"600001.SSE": 12.10},
    )

    result = run_rebuild(object(), schema)

    assert result["mode"] == "incremental"
    assert calls["deleted"] == [(D1, D3)]  # 幂等: 窗口先 delete 再 insert
    assert calls["scan_windows"] == [(D1, D3)]
    written = [r for chunk in calls["inserted"] for r in chunk]
    assert [r["limit_up_count"] for r in written] == [3, 4]
    assert all(r["vt_symbol"] == "600001.SSE" for r in written)
    assert result["rows_written"] == 2
    assert result["rows_read"] == 4
    assert result["trade_dates"] == [D2, D3]


def test_run_rebuild_incremental_is_idempotent_on_rerun(monkeypatch):
    # 重跑同一窗口: 先 delete 后 insert, 两次写入内容一致
    bars = [_db_bar("600001.SSE", D2, 10.20, 11.00, 10.10, 11.00)]
    kwargs = dict(
        bars=bars,
        target=D2,
        last_done=D1,
        names={"600001.SSE": "测试A"},
        seed_streaks={},
        seed_closes={"600001.SSE": 10.00},
    )
    first_calls = _patch_rebuild(monkeypatch, **kwargs)
    first = run_rebuild(object(), schema)
    second_calls = _patch_rebuild(monkeypatch, **kwargs)
    second = run_rebuild(object(), schema)

    assert first["rows_written"] == second["rows_written"] == 1
    assert first_calls["inserted"] == second_calls["inserted"]
    assert first_calls["deleted"] == [(D1, D2)]


def test_run_rebuild_full_with_explicit_date_caps_delete_and_scan(monkeypatch):
    # full + 显式 trade_date: 删除/扫描窗口都收束到该日(与写入窗口一致)
    bars = [
        _db_bar("600001.SSE", D1, 9.90, 10.00, 9.80, 10.00),
        _db_bar("600001.SSE", D2, 10.20, 11.00, 10.10, 11.00),
    ]
    calls = _patch_rebuild(monkeypatch, bars=bars, target=D2, last_done=D1)

    result = run_rebuild(object(), schema, trade_date=D2, full=True)

    assert result["mode"] == "full"
    assert result["target_date"] == D2
    assert calls["deleted"] == [(None, D2)]
    assert calls["scan_windows"] == [(None, D2)]
    assert result["rows_written"] == 1


def test_run_rebuild_partial_coverage_day_falls_back_and_noops(monkeypatch):
    """日线部分失败日: 完整日闸门把缺省 target 回退到前一完整日。

    闸门返回 D1(完整日), 而 last_done 已是 D1 → 增量 no-op, 不烧入
    部分覆盖日的错误 streak; 补偿链补齐后闸门落到新日再自动追上。
    """
    calls = _patch_rebuild(monkeypatch, bars=[], target=D1, last_done=D1)

    result = run_rebuild(object(), schema)

    assert result["mode"] == "incremental"
    assert result["rows_written"] == 0
    assert result["trade_dates"] == []
    assert calls["deleted"] == []
    assert calls["inserted"] == []
    assert calls["scan_windows"] == []


class _RecordingSession:
    """捕获 execute 语句并返回预制结果(无真实 DB 的语句结构测试)。"""

    def __init__(self, result):
        self.statements = []
        self._result = result

    def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return self._result


class _FirstResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


def test_latest_complete_daily_date_uses_coverage_gate(monkeypatch):
    from sqlalchemy.dialects import postgresql

    monkeypatch.setattr(rb, "completed_daily_bar_cutoff", lambda: D2)
    session = _RecordingSession(_FirstResult((D2,)))

    result = rb._latest_complete_daily_date(session, schema)

    assert result == D2
    assert len(session.statements) == 1
    sql = session.statements[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    text = str(sql)
    # 同 data_sync 口径: 过收盘闸门 + 单日覆盖 >= 3000 + 取最新一日
    assert "GROUP BY" in text
    assert "HAVING count(*) >= 3000" in text
    assert "trade_date <= '2026-08-11'" in text
    assert "ORDER BY" in text and "DESC" in text
    assert "LIMIT 1" in text


def test_latest_complete_daily_date_returns_none_without_complete_day(monkeypatch):
    monkeypatch.setattr(rb, "completed_daily_bar_cutoff", lambda: D2)
    session = _RecordingSession(_FirstResult(None))

    assert rb._latest_complete_daily_date(session, schema) is None


def test_load_seed_closes_uses_lateral_per_symbol_probe():
    from sqlalchemy.dialects import postgresql

    session = _RecordingSession(iter([]))

    assert rb._load_seed_closes(session, schema, D1) == {}
    assert len(session.statements) == 1
    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    # 逐股 LIMIT 1 索引探测, 不是 DISTINCT ON 全历史扫描
    assert "LATERAL" in sql
    assert "LIMIT 1" in sql
    assert "DISTINCT ON" not in sql
    assert "FROM stocks" in sql


def test_run_rebuild_noop_when_up_to_date(monkeypatch):
    calls = _patch_rebuild(monkeypatch, bars=[], target=D2, last_done=D2)

    result = run_rebuild(object(), schema)

    assert result["rows_written"] == 0
    assert result["trade_dates"] == []
    assert calls["deleted"] == []
    assert calls["inserted"] == []
    assert calls["scan_windows"] == []


def test_run_rebuild_full_ignores_existing_progress(monkeypatch):
    # full=True: 不读已有进度, 全量重建
    bars = [
        _db_bar("600001.SSE", D1, 9.90, 10.00, 9.80, 10.00),
        _db_bar("600001.SSE", D2, 10.20, 11.00, 10.10, 11.00),
    ]
    calls = _patch_rebuild(monkeypatch, bars=bars, target=D2, last_done=D1)

    result = run_rebuild(object(), schema, full=True)

    assert result["mode"] == "full"
    assert calls["deleted"] == [(None, None)]  # full 不读已有进度, 全表重写
    assert calls["scan_windows"] == [(None, D2)]
    assert result["rows_written"] == 1


def test_run_rebuild_chunks_bulk_inserts(monkeypatch):
    monkeypatch.setattr(rb, "_INSERT_CHUNK_SIZE", 3)
    bars = [
        _db_bar(f"60000{i}.SSE", D2, 10.20, 11.00, 10.10, 11.00) for i in range(7)
    ]
    calls = _patch_rebuild(
        monkeypatch,
        bars=bars,
        target=D2,
        last_done=D1,
        seed_closes={f"60000{i}.SSE": 10.00 for i in range(7)},
    )

    result = run_rebuild(object(), schema)

    assert [len(chunk) for chunk in calls["inserted"]] == [3, 3, 1]
    assert result["rows_written"] == 7


# ── DataSyncService runner 接线 ──────────────────────────────────────────


def test_data_sync_runner_wires_run_rebuild(monkeypatch):
    """JOB_RUNNERS 指向的方法: 解析参数→开 session→调 run_rebuild→补 message。"""
    from contextlib import contextmanager

    from alphaagent.server.services import data_sync as svc

    captured: dict[str, object] = {}

    def fake_run_rebuild(session, schema_mod, *, trade_date=None, full=False):
        captured["session"] = session
        captured["schema"] = schema_mod
        captured["trade_date"] = trade_date
        captured["full"] = full
        return {
            "trade_dates": [D2],
            "rows_written": 3,
            "rows_read": 10,
            "elapsed_seconds": 0.1,
            "mode": "incremental",
            "target_date": D2,
        }

    sentinel_session = object()

    @contextmanager
    def fake_session_scope():
        yield sentinel_session

    monkeypatch.setattr(rb, "run_rebuild", fake_run_rebuild)
    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    method_name = svc.JOB_RUNNERS["rebuild_stock_limit_up_daily"]
    runner = svc.DataSyncRunner(adapter=object())
    result = getattr(runner, method_name)(
        {"trade_date": "2026-08-11", "full": "true"}
    )

    assert captured["session"] is sentinel_session
    assert captured["schema"] is schema
    assert captured["trade_date"] == D2
    assert captured["full"] is True
    assert result["message"] == "连板梯队日线重建完成：1 个交易日，3 行"
