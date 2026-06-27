"""验证"低吸≥3天+启动+无承接"(金安6-4类)形态后续盈亏。

金安6-4: 低吸3天 + 当日涨4.39%(启动) + state=PULLBACK_OBSERVE(脱离MA5无承接) + entry=False
当前策略只买"承接"(贴MA5)，不认"低吸后启动"。若这类票后续盈亏好，值得加"低吸启动确认"买点。

A组(金安6-4类): low_suction_days>=3 AND latest_change_pct>3 AND dragon_state='PULLBACK_OBSERVE'
B组(对照,低吸承接被买): low_suction_days>=3 AND entry_signal=true
持有5/10/20日收益(D+1开盘买)。
"""

from __future__ import annotations

import random
import statistics

from sqlalchemy import text

from alphaagent.server.db.session import session_scope

START, END = "2025-09-01", "2026-06-15"
SAMPLE = 800


def _f(col: str) -> str:
    return f"CASE WHEN (evidence->>'{col}') ~ '^-?[0-9.]' THEN (evidence->>'{col}')::float ELSE 0 END"


def collect(group: str) -> list[tuple[str, str]]:
    with session_scope() as s:
        if group == "A":  # 金安6-4类：低吸≥3 + 启动 + 无承接(PULLBACK_OBSERVE)
            sql = f"""
                SELECT DISTINCT ON (vt_symbol, trade_date) vt_symbol, trade_date
                FROM quant_stock_signals
                WHERE strategy_id='mainline_dragon_pullback'
                  AND trade_date BETWEEN :s AND :e
                  AND (evidence->>'dragon_state') = 'PULLBACK_OBSERVE'
                  AND {_f('low_suction_days')} >= 3
                  AND {_f('latest_change_pct')} > 3
                ORDER BY vt_symbol, trade_date, run_id DESC
            """
        else:  # B对照：低吸≥3 + 被买入
            sql = f"""
                SELECT DISTINCT ON (vt_symbol, trade_date) vt_symbol, trade_date
                FROM quant_stock_signals
                WHERE strategy_id='mainline_dragon_pullback'
                  AND trade_date BETWEEN :s AND :e
                  AND entry_signal = true
                  AND {_f('low_suction_days')} >= 3
                ORDER BY vt_symbol, trade_date, run_id DESC
            """
        rows = list(s.execute(text(sql), {"s": START, "e": END}).mappings())
    out = [(str(r["vt_symbol"]), str(r["trade_date"])) for r in rows]
    random.seed(42)
    return out


def hold_returns(vt: str, sig_date: str) -> dict[int, float] | None:
    with session_scope() as s:
        bars = s.execute(
            text(
                "SELECT open_price, close_price FROM stock_daily_bars "
                "WHERE vt_symbol=:v AND trade_date>:d ORDER BY trade_date LIMIT 21"
            ),
            {"v": vt, "d": sig_date},
        ).all()
    if len(bars) < 21:
        return None
    entry = float(bars[0][0])
    return {d: float(bars[d][1]) / entry - 1 for d in (5, 10, 20)}


def stat(label: str, samples: list[tuple[str, str]]) -> None:
    buckets: dict[int, list[float]] = {5: [], 10: [], 20: []}
    for vt, d in samples:
        r = hold_returns(vt, d)
        if not r:
            continue
        for k, v in r.items():
            buckets[k].append(v)
    print(f"\n【{label}】有效样本={sum(len(v) for v in buckets.values()) // 3}")
    print(f"{'持有':<8}{'笔数':>6}{'胜率':>8}{'中位':>10}{'均值':>10}")
    for d in (5, 10, 20):
        arr = buckets[d]
        if not arr:
            continue
        win = sum(1 for x in arr if x > 0) / len(arr) * 100
        print(f"{d}日{'':<4}{len(arr):>6}{win:>7.0f}%{statistics.median(arr)*100:>9.1f}%{statistics.mean(arr)*100:>9.1f}%")


def main() -> int:
    a = collect("A")
    b = collect("B")
    print(f"A组(金安6-4类,低吸≥3+启动+无承接): {len(a)} 条", flush=True)
    print(f"B组(对照,低吸≥3+承接被买入): {len(b)} 条", flush=True)
    stat("A组-低吸启动无承接(金安6-4类)", a[:SAMPLE])
    stat("B组-低吸承接被买入(对照)", b[:SAMPLE])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
