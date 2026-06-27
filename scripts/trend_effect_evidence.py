"""展示 latest_change_pct>0 门控的具体效果证据：过滤了哪些亏损、保留了哪些盈利。

读门控前的逐笔数据 /tmp/trend_entry_groups.json（含每笔进场当日涨跌 + 最终盈亏），
证明门控过滤的确实是"当日跌的追高假加速"（亏），保留的是"当日涨的真趋势"（赚）。
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median

GROUPS_JSON = Path("/tmp/trend_entry_groups.json")


def main() -> int:
    data = json.loads(GROUPS_JSON.read_text())

    print("=" * 70, flush=True)
    print("门控效果证据：latest_change_pct > 0 过滤了什么、保留了什么", flush=True)
    print("=" * 70, flush=True)

    for outcome in ["stop_loss", "trailing_stop", "take_profit", "time_stop"]:
        items = data.get(outcome, [])
        if not items:
            continue
        chgs = [it["evidence"].get("latest_change_pct") for it in items]
        chgs = [c for c in chgs if c is not None]
        n = len(chgs)
        if n == 0:
            continue
        neg = sum(1 for c in chgs if c <= 0)
        pos = sum(1 for c in chgs if c > 0)
        pnl_sum = sum(it.get("pnl") or 0 for it in items)
        label = {
            "stop_loss": "追高假加速（亏）",
            "trailing_stop": "假突破回撤（亏）",
            "take_profit": "真趋势（赚）",
            "time_stop": "超时",
        }.get(outcome, outcome)
        print(f"\n【{label} {outcome}】共 {n} 笔，总盈亏 {pnl_sum:.0f}", flush=True)
        print(
            f"  进场当日跌/平 (<=0，被门控过滤): {neg:>3} 笔 ({neg / n:.0%})  "
            f"— 这些是门控剔除的",
            flush=True,
        )
        print(
            f"  进场当日涨 (>0，被门控保留):     {pos:>3} 笔 ({pos / n:.0%})",
            flush=True,
        )
        print(f"  当日涨跌中位数: {median(chgs):+.2f}%", flush=True)

    # 具体案例：被门控过滤的追高假加速（stop_loss 组 change_pct<=0）
    sl = data.get("stop_loss", [])
    filtered = [it for it in sl if (it["evidence"].get("latest_change_pct") or 0) <= 0]
    print("\n" + "=" * 70, flush=True)
    print(f"被门控过滤的追高假加速案例（stop_loss 且当日跌/平，共 {len(filtered)} 笔）:", flush=True)
    print("  这些是门控后【不再买入】的——进场当日跌，最终 stop_loss 亏损", flush=True)
    for it in filtered[:8]:
        ev = it["evidence"]
        sig = ev.get("execution", {}).get("signal_date", "?")
        print(
            f"    {sig} 当日{ev.get('latest_change_pct'):+.2f}% "
            f"(5d {ev.get('return_5d'):.1f}%/20d {ev.get('return_20d'):.1f}%) "
            f"→ 亏损 {it.get('pnl'):.0f}",
            flush=True,
        )

    # 被门控保留的真趋势（take_profit 组 change_pct>0）
    tp = data.get("take_profit", [])
    kept = [it for it in tp if (it["evidence"].get("latest_change_pct") or 0) > 0]
    print(f"\n被门控保留的真趋势案例（take_profit 且当日涨，共 {len(kept)} 笔）:", flush=True)
    print("  这些是门控后【仍然买入】的——进场当日涨，最终 take_profit 盈利", flush=True)
    for it in kept[:8]:
        ev = it["evidence"]
        sig = ev.get("execution", {}).get("signal_date", "?")
        print(
            f"    {sig} 当日{ev.get('latest_change_pct'):+.2f}% "
            f"(5d {ev.get('return_5d'):.1f}%/20d {ev.get('return_20d'):.1f}%) "
            f"→ 盈利 {it.get('pnl'):.0f}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
