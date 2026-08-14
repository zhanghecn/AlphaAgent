"""连板梯队日线重建:由 stock_daily_bars 全历史/增量递推每股连板状态。

纯函数 iter_limit_up_daily 逐股递推连板 streak, 只产出两类行:
  (a) is_limit_up=True 的涨停行
  (b) is_limit_up=False 且 touched_limit=True 的摸板行(炸板统计候选)
普通未涨停行不落库。

run_rebuild 是落库薄壳(判定口径见 lianban.detector):
- full=True: 流式全量重建(delete 全表重写);
- full=False 增量: 取 stock_limit_up_daily 已重建到的 max(trade_date) 为 last_done,
  处理 (last_done, target] 区间。区间首日 streak 种子取 last_done 当日的
  (vt_symbol, limit_up_count) 映射(未涨停股不在表中 → streak=0);
  每股窗口内首根的 prev_close 种子取 last_done 及之前最后一根日线 close。
  当日行先 delete 后 insert, 幂等。
- last_done 为 None(首跑)退化为 full。
- trade_date 缺省(两种模式同)取「最近完整日线交易日」: 过当日收盘闸门
  (completed_daily_bar_cutoff)且单日覆盖 >= MIN_COMPLETE_DAILY_SYMBOL_COUNT 只。
  日线部分失败时 target 回退到前一完整日 → 当晚增量 no-op, 不烧入部分覆盖日的
  错误 streak; 补偿链补齐后次日自动追上。

已知口径限制:
- 停牌股两模式口径发散: 全量模式流内递推不消费停牌日(无 bar), streak 跨停牌
  延续; 增量模式 streak 种子只查 last_done 当日映射, 停牌跨过 last_done 的股票
  按 streak=0 续推(视为断板)。以全量重建口径为准, 差异随下次 full 收敛。
- 历史 ST 状态用 stocks.name 当前快照判定: 摘帽股历史 ST 期会被按 10% 档
  (可能漏判 5% 涨停), 戴帽股历史非 ST 期会被按 5%/10% 双档判定。如需精确
  口径需引入历史名称表, 暂记为已知限制。

性能: stock_daily_bars 按 (vt_symbol, trade_date) ORDER BY 流式读取
(server-side cursor + yield_per), detector 单调用微秒级, 5000 行一批 insert;
prev_close 种子用 LATERAL 逐股 LIMIT 1 探测(索引下潜, 毫秒级);
全量 460 万行目标 < 15 分钟。
"""
from __future__ import annotations

import time
from collections.abc import Iterable, Iterator, Mapping
from datetime import date
from typing import Any, NamedTuple

from sqlalchemy import delete, desc, func, insert, lateral, select, true

from alphaagent.server.db import schema as db_schema
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff
from alphaagent.server.services.lianban.detector import classify_limit_up

_SCAN_YIELD_PER = 5000
_INSERT_CHUNK_SIZE = 5000
# 与 data_sync 同口径: 单日日线覆盖股票数 >= 3000 才算完整日(部分同步失败日不算)。
MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3000


class BarRow(NamedTuple):
    """iter_limit_up_daily 的输入行(按 (vt_symbol, trade_date) 排序)。

    prev_close 只用于该股的流内首根(流外种子); 后续根的昨收由流内递推,
    传入值一律忽略。name 允许 None(按非 ST 处理)。
    """

    vt_symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    prev_close: float | None = None
    name: str | None = None


def _field(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def iter_limit_up_daily(
    bars: Iterable[BarRow],
    *,
    seed_streaks: Mapping[str, int] | None = None,
) -> Iterator[dict]:
    """逐股递推连板状态, yield stock_limit_up_daily 行(dict)。

    bars 必须按 (vt_symbol, trade_date) 升序; 违反顺序直接 ValueError,
    宁可失败也不静默写坏连板序列。

    seed_streaks: 增量续推时每股带入流内的初始 streak(上个重建日收盘后的
    连板数); 缺省 0。只对每股流内首根生效一次。

    yield 字段: trade_date, vt_symbol, is_limit_up, limit_up_count,
    is_one_word, is_st, board, limit_price, prev_close, close_price,
    change_pct, touched_limit。
    """
    seeds = dict(seed_streaks or {})
    streaks: dict[str, int] = {}
    last_close: dict[str, float] = {}
    last_key: tuple[str, date] | None = None

    for bar in bars:
        vt_symbol = str(_field(bar, "vt_symbol"))
        trade_date = _field(bar, "trade_date")
        key = (vt_symbol, trade_date)
        if last_key is not None and key <= last_key:
            raise ValueError(
                f"bars must be sorted by (vt_symbol, trade_date): {key} after {last_key}"
            )
        last_key = key

        close_price = _field(bar, "close")
        prev_close = (
            last_close[vt_symbol]
            if vt_symbol in last_close
            else _field(bar, "prev_close")
        )
        verdict = classify_limit_up(
            symbol=vt_symbol.split(".", 1)[0],
            name=_field(bar, "name"),
            prev_close=prev_close,
            open_price=_field(bar, "open"),
            close_price=close_price,
            high_price=_field(bar, "high"),
            low_price=_field(bar, "low"),
            trade_date=trade_date,
        )

        prev_streak = (
            streaks[vt_symbol]
            if vt_symbol in streaks
            else int(seeds.get(vt_symbol, 0))
        )
        streak = prev_streak + 1 if verdict.is_limit_up else 0

        if verdict.is_limit_up or verdict.touched_limit:
            valid_prev = prev_close is not None and prev_close > 0
            yield {
                "trade_date": trade_date,
                "vt_symbol": vt_symbol,
                "is_limit_up": verdict.is_limit_up,
                "limit_up_count": streak,
                "is_one_word": verdict.is_one_word,
                "is_st": verdict.is_st,
                "board": verdict.board,
                "limit_price": verdict.limit_price,
                "prev_close": prev_close,
                "close_price": close_price,
                "change_pct": (
                    round((close_price / prev_close - 1) * 100, 2) if valid_prev else None
                ),
                "touched_limit": verdict.touched_limit,
            }

        streaks[vt_symbol] = streak
        last_close[vt_symbol] = close_price


# ── DB 辅助函数(run_rebuild 的触点, 测试可 monkeypatch) ──────────────────


def _max_trade_date(session, column) -> date | None:
    return session.execute(select(func.max(column))).scalar()


def _latest_complete_daily_date(session, schema) -> date | None:
    """最近完整日线交易日: 过当日收盘闸门且单日覆盖 >= 3000 只(同 data_sync 口径)。

    部分同步失败的交易日覆盖数不足 → 不被选为 target, 避免把错误 streak 烧入。
    """
    bars = schema.stock_daily_bars
    row = session.execute(
        select(bars.c.trade_date)
        .where(bars.c.trade_date <= completed_daily_bar_cutoff())
        .group_by(bars.c.trade_date)
        .having(func.count() >= MIN_COMPLETE_DAILY_SYMBOL_COUNT)
        .order_by(desc(bars.c.trade_date))
        .limit(1)
    ).first()
    return row[0] if row else None


def _load_name_map(session, schema) -> dict[str, str | None]:
    rows = session.execute(select(schema.stocks.c.vt_symbol, schema.stocks.c.name)).all()
    return {str(r.vt_symbol): r.name for r in rows}


def _load_seed_streaks(session, schema, last_done: date) -> dict[str, int]:
    state = schema.stock_limit_up_daily
    rows = session.execute(
        select(state.c.vt_symbol, state.c.limit_up_count).where(
            state.c.trade_date == last_done
        )
    ).all()
    return {str(r.vt_symbol): int(r.limit_up_count or 0) for r in rows}


def _load_seed_closes(session, schema, last_done: date) -> dict[str, float]:
    """每股 last_done 及之前最后一根日线的 close, 作窗口内首根的 prev_close 种子。

    LATERAL 逐股 LIMIT 1 探测(PK 索引下潜, 毫秒级); 不用 DISTINCT ON 全历史扫描。
    stock_daily_bars.vt_symbol 有 FK 指向 stocks, 故 stocks 即全集; 无匹配 bar 的
    股票 close 为 NULL(窗口内首根按新股首日处理), 不进字典。
    """
    bars = schema.stock_daily_bars
    universe = select(schema.stocks.c.vt_symbol.label("vt_symbol")).subquery()
    probe = (
        select(bars.c.close_price)
        .where(bars.c.vt_symbol == universe.c.vt_symbol, bars.c.trade_date <= last_done)
        .order_by(desc(bars.c.trade_date))
        .limit(1)
    )
    seed_close = lateral(probe, name="seed_close")
    stmt = (
        select(universe.c.vt_symbol, seed_close.c.close_price)
        .select_from(universe)
        .outerjoin(seed_close, true())
    )
    return {
        str(r.vt_symbol): float(r.close_price)
        for r in session.execute(stmt)
        if r.close_price is not None
    }


def _scan_bars(session, schema, start_exclusive: date | None, end_inclusive: date | None):
    bars = schema.stock_daily_bars
    stmt = (
        select(
            bars.c.vt_symbol,
            bars.c.trade_date,
            bars.c.open_price,
            bars.c.high_price,
            bars.c.low_price,
            bars.c.close_price,
        )
        .order_by(bars.c.vt_symbol, bars.c.trade_date)
        .execution_options(stream_results=True)
    )
    if start_exclusive is not None:
        stmt = stmt.where(bars.c.trade_date > start_exclusive)
    if end_inclusive is not None:
        stmt = stmt.where(bars.c.trade_date <= end_inclusive)
    return session.execute(stmt).yield_per(_SCAN_YIELD_PER)


def _delete_rows(session, schema, start_exclusive: date | None, end_inclusive: date | None) -> None:
    stmt = delete(schema.stock_limit_up_daily)
    state = schema.stock_limit_up_daily
    if start_exclusive is not None:
        stmt = stmt.where(state.c.trade_date > start_exclusive)
    if end_inclusive is not None:
        stmt = stmt.where(state.c.trade_date <= end_inclusive)
    session.execute(stmt)


def _insert_rows(session, schema, rows: list[dict]) -> None:
    session.execute(insert(schema.stock_limit_up_daily), list(rows))


# ── 落库薄壳 ────────────────────────────────────────────────────────────


def run_rebuild(
    session,
    schema=None,
    *,
    trade_date: date | None = None,
    full: bool = False,
) -> dict:
    """重建 stock_limit_up_daily。

    full=True: 流式全量重建(delete 全表重写); full=False: 增量——
      1. trade_date 缺省 = 最近完整日线交易日(完整日闸门, 见
         _latest_complete_daily_date; 部分覆盖日不被选中 → 增量 no-op 等补偿)
      2. last_done = stock_limit_up_daily 已重建到的 max(trade_date)
      3. last_done 为 None(首跑)退化为 full
      4. 否则处理 (last_done, trade_date] 区间: streak 种子取 last_done 当日
         (vt_symbol, limit_up_count) 映射, prev_close 种子取每股 last_done 及
         之前最后一根日线 close; 区间行 delete+insert(幂等)。

    返回 {"trade_dates": [...], "rows_written": n, "rows_read": n,
          "elapsed_seconds": x, "mode": ..., "target_date": ...}
    """
    schema = schema if schema is not None else db_schema
    started = time.monotonic()

    target = trade_date or _latest_complete_daily_date(session, schema)
    if target is None:
        return {
            "trade_dates": [],
            "rows_written": 0,
            "rows_read": 0,
            "elapsed_seconds": 0.0,
            "mode": "full" if full else "incremental",
            "target_date": None,
        }

    last_done = None if full else _max_trade_date(
        session, schema.stock_limit_up_daily.c.trade_date
    )
    if last_done is not None and target <= last_done:
        return {
            "trade_dates": [],
            "rows_written": 0,
            "rows_read": 0,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "mode": "incremental",
            "target_date": target,
        }

    if last_done is None:
        mode = "full"
        start_exclusive = None
        seed_streaks: dict[str, int] = {}
        seed_closes: dict[str, float] = {}
        # full = delete 全表重写; 仅当显式给 trade_date 快照上限时才收束删除窗口,
        # 与写入窗口保持一致(幂等)。
        delete_end = trade_date
    else:
        mode = "incremental"
        start_exclusive = last_done
        seed_streaks = _load_seed_streaks(session, schema, last_done)
        seed_closes = _load_seed_closes(session, schema, last_done)
        delete_end = target

    _delete_rows(session, schema, start_exclusive, delete_end)

    names = _load_name_map(session, schema)
    scan = _scan_bars(session, schema, start_exclusive, target)

    rows_read = 0

    def _bar_rows() -> Iterator[BarRow]:
        nonlocal rows_read
        for row in scan:
            rows_read += 1
            vt_symbol = str(row.vt_symbol)
            yield BarRow(
                vt_symbol=vt_symbol,
                trade_date=row.trade_date,
                open=row.open_price,
                high=row.high_price,
                low=row.low_price,
                close=row.close_price,
                # 只对每股流内首根生效; 全量模式为空 → 新股首日跳过判定
                prev_close=seed_closes.get(vt_symbol),
                name=names.get(vt_symbol),
            )

    rows_written = 0
    written_dates: set[date] = set()
    chunk: list[dict] = []
    for out_row in iter_limit_up_daily(_bar_rows(), seed_streaks=seed_streaks):
        chunk.append(out_row)
        written_dates.add(out_row["trade_date"])
        if len(chunk) >= _INSERT_CHUNK_SIZE:
            _insert_rows(session, schema, chunk)
            rows_written += len(chunk)
            chunk.clear()
    if chunk:
        _insert_rows(session, schema, chunk)
        rows_written += len(chunk)

    return {
        "trade_dates": sorted(written_dates),
        "rows_written": rows_written,
        "rows_read": rows_read,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "mode": mode,
        "target_date": target,
    }
