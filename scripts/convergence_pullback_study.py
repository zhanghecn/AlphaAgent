"""验证 convergence 放宽的价值：涨停后回踩贴线被convergence挡的票（金安类）后续盈亏。

A组（金安类）：PULLBACK_OBSERVE + 贴MA5(-3.2~4.2) + conv>8.8 + low_suction_days=0 + 近期涨停
  → 这些贴线低吸被 convergence_ok 挡，没进买入状态
B组（对照，正常低吸被买入）：entry_signal=True + low_suction_days>=2
口径：信号日D，D+1开盘买入，持有5/10/20日收盘算收益（不止损，看方向倾向）。
若A组收益不差甚至更好 -> 放宽convergence有价值（能抓上涨票），值得改码+CPCV。
"""

from __future__ import annotations

import random
import statistics

from sqlalchemy import text

from alphaagent.server.db.session import session_scope

START, END = "2025-12-01", "2026-06-15"
SAMPLE = 800  # 每组最多采样，控制 K线查询量


def _f(col: str) -> str:
    """安全转 float：非数字字段(如boolean 'true')返回 0，避免 ::float 报错。"""
    return f"CASE WHEN (evidence->>'{col}') ~ '^-?[0-9.]' THEN (evidence->>'{col}')::float ELSE 0 END"


def collect(group: str) -> list[tuple[str, str]]:
    with session_scope() as s:
        if group == "A":  # 金安类：涨停后回踩贴线被convergence挡
            sql = f"""
                SELECT DISTINCT ON (vt_symbol, trade_date) vt_symbol, trade_date
                FROM quant_stock_signals
                WHERE strategy_id='mainline_dragon_pullback'
                  AND trade_date BETWEEN :s AND :e
                  AND (evidence->>'dragon_state') = 'PULLBACK_OBSERVE'
                  AND {_f('ma5_distance_pct')} BETWEEN -3.2 AND 4.2
                  AND {_f('ma_convergence_pct')} > 8.8
                  AND {_f('low_suction_days')} = 0
                  AND {_f('near_limit_up_count_20d')} >= 1
                ORDER BY vt_symbol, trade_date, run_id DESC
            """
        else:  # B对照：正常低吸被买入
            sql = f"""
                SELECT DISTINCT ON (vt_symbol, trade_date) vt_symbol, trade_date
                FROM quant_stock_signals
                WHERE strategy_id='mainline_dragon_pullback'
                  AND trade_date BETWEEN :s AND :e
                  AND entry_signal = true
                  AND {_f('low_suction_days')} >= 2
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
    print(f"{'持有':<8}{'笔数':>6}{'胜率':>8}{'中位收益':>10}{'均值':>10}")
    for d in (5, 10, 20):
        arr = buckets[d]
        if not arr:
            continue
        win = sum(1 for x in arr if x > 0) / len(arr) * 100
        print(f"{d}日{'':<4}{len(arr):>6}{win:>7.0f}%{statistics.median(arr)*100:>9.1f}%{statistics.mean(arr)*100:>9.1f}%")


def main() -> int:
    a = collect("A")
    b = collect("B")
    print(f"A组(金安类,涨停后贴线被conv挡): {len(a)} 条", flush=True)
    print(f"B组(对照,正常低吸被买入): {len(b)} 条", flush=True)
    a_s = a[:SAMPLE]
    b_s = b[:SAMPLE]
    stat("A组-金安类(被conv挡,未买)", a_s)
    stat("B组-正常低吸(已买入,对照)", b_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
