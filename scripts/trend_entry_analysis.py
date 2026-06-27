"""数据驱动分析 trend 进场：关联 BUY entry evidence → SELL outcome，分组对比特征。

目标：找出 take_profit 组（真趋势，赚）vs stop_loss 组（追高假加速，亏）的进场特征差异，
确定真正的优化方向（而非 A' 的 return_5d 盲调）。

只读 run_backtest(persist=False)，不改源码。跑完即可删除。
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from statistics import median

from alphaagent.server.services.backtest.engine import run_backtest
from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant.factors import TREND_ACCELERATION_STRATEGY_ID

RANGE_START = date(2025, 3, 26)
RANGE_END = date(2026, 6, 18)

FEATURES = [
    "return_5d", "return_20d", "return_60d",
    "ma5_distance_pct", "ma20_distance_pct", "ma60_distance_pct",
    "volume_ratio_5d_20d", "latest_change_pct", "max_drawdown_60d",
    "acceleration_score", "trend_quality_score", "risk_score", "liquidity_score",
    "turnover20",
]


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    params = BacktestParams(
        strategy=TREND_ACCELERATION_STRATEGY_ID,
        start=RANGE_START,
        end=RANGE_END,
        min_entry_score=73.0,
        strict_entry=True,
        max_symbols=5000,
        max_position_pct=0.125,
        persist=False,
    )
    result = run_backtest(params)
    trades = result.get("trades") or []
    print(f"total trades={len(trades)}\n", flush=True)

    for t in trades:
        if str(t.get("side")).upper() == "BUY":
            print("=== BUY sample ===", flush=True)
            print(f"reason={t.get('reason')!r}", flush=True)
            raw = t.get("raw")
            print(f"raw type={type(raw).__name__}", flush=True)
            if isinstance(raw, dict):
                print("raw keys:", sorted(raw.keys()), flush=True)
            break
    for t in trades:
        if str(t.get("side")).upper() == "SELL":
            print("\n=== SELL sample ===", flush=True)
            print(f"keys: {list(t.keys())}  reason={t.get('reason')!r}", flush=True)
            break

    # FIFO 配对：按 trade_date 排序确保时间序，BUY evidence 排队，SELL pop 配对
    trades_sorted = sorted(
        trades,
        key=lambda t: (str(t.get("trade_date") or ""), str(t.get("vt_symbol") or "")),
    )
    pending: dict[str, deque] = defaultdict(deque)
    groups: dict[str, list] = defaultdict(list)  # outcome -> [(evidence, pnl)]
    buy_with_ev = 0
    sell_matched = 0
    sell_unmatched = 0
    for t in trades_sorted:
        side = str(t.get("side")).upper()
        vts = str(t.get("vt_symbol") or "")
        reason = t.get("reason")
        if side == "BUY":
            raw = t.get("raw")
            if isinstance(raw, dict):
                pending[vts].append(raw)
                buy_with_ev += 1
        elif side == "SELL":
            outcome = reason if isinstance(reason, str) else "unknown"
            if pending[vts]:
                entry_ev = pending[vts].popleft()
                groups[outcome].append((entry_ev, to_float(t.get("pnl"))))
                sell_matched += 1
            else:
                sell_unmatched += 1
    print(
        f"\n[debug] buy_with_evidence={buy_with_ev} sell_matched={sell_matched} "
        f"sell_unmatched={sell_unmatched}",
        flush=True,
    )
    print(f"[debug] group sizes: {dict({k: len(v) for k, v in groups.items()})}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("=== 分组规模 ===", flush=True)
    for outcome, items in sorted(groups.items(), key=lambda x: -len(x[1])):
        pnl_sum = sum((p or 0) for _, p in items)
        print(f"  {outcome:<24} n={len(items):>4}  pnl_sum={pnl_sum:>10.0f}", flush=True)

    key_groups = ["take_profit", "stop_loss", "trailing_stop", "time_stop"]
    present = [g for g in key_groups if groups.get(g)]
    if len(present) < 2:
        print("\n分组不足，无法对比", flush=True)
        return 0

    print("\n=== entry 特征分组对比（上行=mean 下行=median）===", flush=True)
    print(f"{'feature':<24}" + "".join(f"{g:>20}" for g in present), flush=True)
    for feat in FEATURES:
        row = f"{feat:<24}"
        row2 = f"{'':<24}"
        for g in present:
            vals = [to_float(ev.get(feat)) for ev, _ in groups[g]]
            vals = [v for v in vals if v is not None]
            if vals:
                row += f"{sum(vals) / len(vals):>20.2f}"
                row2 += f"{f'm{median(vals):.2f}':>20}"
            else:
                row += f"{'n/a':>20}"
                row2 += f"{'':>20}"
        print(row, flush=True)
        print(row2, flush=True)

    out = {o: [{"evidence": ev, "pnl": p} for ev, p in items] for o, items in groups.items()}
    Path("/tmp/trend_entry_groups.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str)
    )
    print("\n明细落盘: /tmp/trend_entry_groups.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
