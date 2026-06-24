"""一次性诊断：扫描 stop_loss_pct 对收益/胜率/support_stop 的影响。

只读调用 run_backtest(persist=False)，不写库、不改任何策略代码、对主线 0.1.21 零影响。
跑完即可删除。

背景：baseline #194 的 support_stop 125 笔亏 -88 万（亏损主力），55% 止损后5日回升
（误杀），疑止损位过紧。stop_loss_pct 默认 0.07，本脚本扫描放宽后的效果。

用法：
    python scripts/stop_loss_sweep.py                       # 默认 0.07,0.08,0.09,0.10,0.12
    python scripts/stop_loss_sweep.py --stops 0.07,0.09,0.11
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

from alphaagent.server.services.backtest.engine import run_backtest
from alphaagent.server.services.backtest.schemas import BacktestParams

RANGE_START = date(2025, 3, 26)
RANGE_END = date(2026, 6, 18)
OUT_JSON = Path("/tmp/stop_loss_sweep.json")


def build_base() -> BacktestParams:
    return BacktestParams(
        start=RANGE_START,
        end=RANGE_END,
        min_entry_score=76.0,
        strict_entry=True,
        max_symbols=5000,
        max_position_pct=0.1,  # 对齐 #194（默认 0.125 会偏离）
        persist=False,
    )


def summarize(result: dict) -> dict:
    metrics = result.get("metrics") or {}
    trades = result.get("trades") or []
    sells = [t for t in trades if str(t.get("side")).upper() == "SELL"]
    reason_pnl: dict[str, dict] = {}
    for t in sells:
        reason = str(t.get("reason") or "unknown")
        bucket = reason_pnl.setdefault(reason, {"n": 0, "pnl": 0.0})
        bucket["n"] += 1
        bucket["pnl"] += float(t.get("pnl") or 0)
    support = reason_pnl.get("support_stop", {"n": 0, "pnl": 0.0})
    return {
        "total_return_pct": metrics.get("total_return_pct"),
        "annual_return_pct": metrics.get("annual_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe": metrics.get("sharpe"),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": metrics.get("profit_factor"),
        "buy_count": metrics.get("buy_count"),
        "sell_count": metrics.get("sell_count"),
        "support_stop_n": support["n"],
        "support_stop_pnl": round(support["pnl"], 0),
        "reason_breakdown": {
            k: {"n": v["n"], "pnl": round(v["pnl"], 0)}
            for k, v in sorted(reason_pnl.items(), key=lambda x: x[1]["pnl"])
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stops", default="0.07,0.08,0.09,0.10,0.12")
    args = parser.parse_args()
    stops = [float(x) for x in args.stops.split(",") if x.strip()]

    base = build_base()
    print(f"扫描 stop_loss_pct={stops}，区间 {RANGE_START}..{RANGE_END}，max_symbols=5000", flush=True)
    print(f"#194 baseline 基准: sharpe 2.38 / win 32.2% / return 83.0% / maxdd -15.6%", flush=True)

    results = []
    for stop in stops:
        params = replace(base, stop_loss_pct=stop)
        started = time.time()
        result = run_backtest(params)
        elapsed = time.time() - started
        summary = summarize(result)
        summary["stop_loss_pct"] = stop
        summary["elapsed"] = round(elapsed, 0)
        summary["status"] = result.get("status")
        results.append(summary)
        if summary["status"] == "ready":
            print(
                f"  stop={stop:.2f}: return={summary['total_return_pct']:.1f}% "
                f"win={summary['win_rate']:.1%} maxdd={summary['max_drawdown_pct']:.1f}% "
                f"sharpe={summary['sharpe']:.2f} pf={summary['profit_factor']:.2f} "
                f"support_stop={summary['support_stop_n']}笔/{summary['support_stop_pnl']:.0f} "
                f"({elapsed:.0f}s)",
                flush=True,
            )
        else:
            print(f"  stop={stop:.2f}: status={summary['status']} ({elapsed:.0f}s)", flush=True)

    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\n明细落盘: {OUT_JSON}", flush=True)

    print("\n=== 对比表 ===")
    print(f"{'stop':>6} {'return':>8} {'win':>7} {'maxdd':>8} {'sharpe':>7} {'pf':>6} {'sup_n':>6} {'sup_pnl':>10}")
    for r in results:
        if r.get("status") != "ready":
            continue
        print(
            f"{r['stop_loss_pct']:>6.2f} {r['total_return_pct']:>7.1f}% "
            f"{r['win_rate']:>6.1%} {r['max_drawdown_pct']:>7.1f}% "
            f"{r['sharpe']:>7.2f} {r['profit_factor']:>6.2f} "
            f"{r['support_stop_n']:>6} {r['support_stop_pnl']:>10.0f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
