"""验证 financial_improvement 子分对 dragon 回踩盈亏的预测力。

用基线 #194 的 214 笔 SELL，每笔关联买入信号日的 financial_improvement_score，
按 financial 分桶看胜率/平均盈亏。
若高分桶不比低分桶赚得多 -> financial 权重该降（金安这类可进 top5 且不损收益）。
"""

from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import text

from alphaagent.server.db.session import session_scope


def q(sql: str, **p):
    with session_scope() as s:
        return list(s.execute(text(sql), p).mappings())


def main() -> int:
    sells = q(
        "SELECT vt_symbol, pnl, reason, raw FROM backtest_trades "
        "WHERE backtest_id=194 AND side='SELL'"
    )
    print(f"#194 SELL 共 {len(sells)} 笔\n", flush=True)

    records = []
    miss = 0
    for s in sells:
        raw = s["raw"] if isinstance(s["raw"], dict) else {}
        sig_date = raw.get("signal_date")
        if not sig_date:
            miss += 1
            continue
        fin = q(
            "SELECT financial_improvement_score FROM quant_stock_signals "
            "WHERE vt_symbol=:v AND trade_date=:d AND strategy_id='mainline_dragon_pullback' "
            "ORDER BY run_id DESC LIMIT 1",
            v=s["vt_symbol"],
            d=sig_date,
        )
        if not fin or fin[0]["financial_improvement_score"] is None:
            miss += 1
            continue
        records.append(
            {
                "vts": s["vt_symbol"],
                "pnl": float(s["pnl"]),
                "reason": s["reason"],
                "fin": float(fin[0]["financial_improvement_score"]),
                "sig": sig_date,
            }
        )
    print(f"成功关联 financial: {len(records)} 笔, 缺失/无信号: {miss} 笔\n", flush=True)

    buckets = {"<55(金安区)": [], "55-65": [], "65-75": [], ">=75(高分)": []}
    for r in records:
        f = r["fin"]
        if f < 55:
            buckets["<55(金安区)"].append(r)
        elif f < 65:
            buckets["55-65"].append(r)
        elif f < 75:
            buckets["65-75"].append(r)
        else:
            buckets[">=75(高分)"].append(r)

    print("=" * 70)
    print("financial 分桶 vs 盈亏（预测力检验）")
    print("=" * 70)
    print(f"{'桶':<16}{'笔数':>5}{'胜率':>8}{'avg_pnl':>10}{'sum_pnl':>12}{'占亏损比':>10}")
    total_loss = sum(r["pnl"] for r in records if r["pnl"] < 0)
    for name, items in buckets.items():
        if not items:
            print(f"{name:<16}{0:>5}")
            continue
        pnls = [i["pnl"] for i in items]
        wins = sum(1 for p in pnls if p > 0)
        loss_share = abs(sum(p for p in pnls if p < 0)) / abs(total_loss) * 100 if total_loss else 0
        print(
            f"{name:<16}{len(items):>5}{wins / len(items) * 100:>7.0f}%"
            f"{sum(pnls) / len(items):>10.0f}{sum(pnls):>12.0f}{loss_share:>9.0f}%"
        )

    # 金安区（financial<55）的 reason 构成
    low = buckets["<55(金安区)"]
    if low:
        print(f"\n--- financial<55（金安所在区）{len(low)}笔 reason 构成 ---")
        by_reason = defaultdict(list)
        for r in low:
            by_reason[r["reason"]].append(r["pnl"])
        for reason, pnls in sorted(by_reason.items(), key=lambda x: -len(x[1])):
            wins = sum(1 for p in pnls if p > 0)
            print(f"  {reason:<26}{len(pnls):>3}笔 胜率{wins / len(pnls) * 100:>3.0f}% avg={sum(pnls) / len(pnls):>+8.0f} sum={sum(pnls):>+9.0f}")

    # 对比：高分区的 reason 构成
    high = buckets[">=75(高分)"]
    if high:
        print(f"\n--- financial>=75（高分区）{len(high)}笔 reason 构成 ---")
        by_reason = defaultdict(list)
        for r in high:
            by_reason[r["reason"]].append(r["pnl"])
        for reason, pnls in sorted(by_reason.items(), key=lambda x: -len(x[1])):
            wins = sum(1 for p in pnls if p > 0)
            print(f"  {reason:<26}{len(pnls):>3}笔 胜率{wins / len(pnls) * 100:>3.0f}% avg={sum(pnls) / len(pnls):>+8.0f} sum={sum(pnls):>+9.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
