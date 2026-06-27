"""一次性诊断：扫描 trend_acceleration 的 trailing_stop_pct / take_profit_pct。

根因（50/50 merge 分析）：trend 走 generic evaluate_exit（factors.py:434），固定
trailing 0.08 / take_profit 0.18。trailing 0.08 太紧把趋势股砍在回踩处（203 笔，
win avg 仅 +4558）；take_profit 0.18 强平砍掉趋势股后半段涨幅。本脚本扫描放宽后
的效果。只读 run_backtest(persist=False)，不改源码、不写库，对主线 0.1.21 零影响。
跑完即可删除。

用法：
    python scripts/trend_exit_sweep.py --phase baseline
    python scripts/trend_exit_sweep.py --phase trailing
    python scripts/trend_exit_sweep.py --phase takeprofit
    python scripts/trend_exit_sweep.py --phase all
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
from alphaagent.server.services.quant.factors import TREND_ACCELERATION_STRATEGY_ID

RANGE_START = date(2025, 3, 26)
RANGE_END = date(2026, 6, 18)
OUT_JSON = Path("/tmp/trend_exit_sweep.json")

REASON_KEYS = ("stop_loss", "take_profit", "trailing_stop", "time_stop")


def build_base() -> BacktestParams:
    return BacktestParams(
        strategy=TREND_ACCELERATION_STRATEGY_ID,
        start=RANGE_START,
        end=RANGE_END,
        min_entry_score=73.0,  # trend default_min_entry_score
        strict_entry=True,
        max_symbols=5000,
        max_position_pct=0.125,  # 默认，让 trend 充分建仓
        stop_loss_pct=0.08,  # 已落地（CPCV PBO=0.33 稳健）
        take_profit_pct=0.18,
        trailing_stop_pct=0.08,
        persist=False,
    )


def summarize(result: dict) -> dict:
    metrics = result.get("metrics") or {}
    trades = result.get("trades") or []
    sells = [t for t in trades if str(t.get("side")).upper() == "SELL"]
    reason_pnl: dict[str, dict] = {}
    for t in sells:
        reason = str(t.get("reason") or "unknown")
        bucket = reason_pnl.setdefault(reason, {"n": 0, "pnl": 0.0, "wins": 0})
        bucket["n"] += 1
        bucket["pnl"] += float(t.get("pnl") or 0)
        if float(t.get("pnl") or 0) > 0:
            bucket["wins"] += 1

    def view(key: str) -> dict:
        b = reason_pnl.get(key, {"n": 0, "pnl": 0.0, "wins": 0})
        n = b["n"]
        return {
            "n": n,
            "pnl": round(b["pnl"], 0),
            "wins": b["wins"],
            "win_rate": round(b["wins"] / n, 3) if n else None,
            "avg_pnl": round(b["pnl"] / n, 0) if n else None,
        }

    return {
        "total_return_pct": metrics.get("total_return_pct"),
        "annual_return_pct": metrics.get("annual_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe": metrics.get("sharpe"),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": metrics.get("profit_factor"),
        "buy_count": metrics.get("buy_count"),
        "sell_count": metrics.get("sell_count"),
        "stop_loss": view("stop_loss"),
        "take_profit": view("take_profit"),
        "trailing_stop": view("trailing_stop"),
        "time_stop": view("time_stop"),
    }


def run_one(base: BacktestParams, *, take_profit_pct: float, trailing_stop_pct: float) -> dict:
    params = replace(
        base,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
    )
    started = time.time()
    result = run_backtest(params)
    elapsed = time.time() - started
    summary = summarize(result)
    summary.update(
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        elapsed=round(elapsed, 0),
        status=result.get("status"),
    )
    return summary


def print_row(label: str, r: dict) -> None:
    if r.get("status") != "ready":
        print(f"  {label}: status={r.get('status')} ({r.get('elapsed')}s)", flush=True)
        return
    tp = r["take_profit"]
    tr = r["trailing_stop"]
    sl = r["stop_loss"]
    print(
        f"  {label}: return={r['total_return_pct']:.1f}% win={r['win_rate']:.1%} "
        f"maxdd={r['max_drawdown_pct']:.1f}% sharpe={r['sharpe']:.2f} pf={r['profit_factor']:.2f} "
        f"buy/sell={r['buy_count']}/{r['sell_count']} | "
        f"tp={tp['n']}/{tp['pnl']:.0f} tr={tr['n']}/{tr['pnl']:.0f}(avg{tr['avg_pnl']:.0f}) "
        f"sl={sl['n']}/{sl['pnl']:.0f} ({r['elapsed']}s)",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="all", choices=["baseline", "trailing", "takeprofit", "all"])
    args = parser.parse_args()

    base = build_base()
    print(
        f"trend_acceleration exit 扫描，区间 {RANGE_START}..{RANGE_END}，"
        f"max_symbols=5000，min_entry_score=73",
        flush=True,
    )
    print("baseline: trailing=0.08 take_profit=0.18 stop_loss=0.08\n", flush=True)

    results: list[dict] = []
    existing: list[dict] = []
    if OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text())
        except Exception:
            existing = []

    def already(tp: float, tr: float) -> dict | None:
        for r in existing + results:
            if abs(float(r.get("take_profit_pct", -1)) - tp) < 1e-9 and abs(
                float(r.get("trailing_stop_pct", -1)) - tr
            ) < 1e-9:
                return r
        return None

    def ensure(tp: float, tr: float, label: str) -> None:
        cached = already(tp, tr)
        if cached:
            print_row(label, cached)
            results.append(cached)
            return
        r = run_one(base, take_profit_pct=tp, trailing_stop_pct=tr)
        print_row(label, r)
        results.append(r)
        OUT_JSON.write_text(json.dumps(existing + results, ensure_ascii=False, indent=2, default=str))

    if args.phase in ("baseline", "all"):
        ensure(0.18, 0.08, "baseline   ")

    if args.phase in ("trailing", "all"):
        print("\n--- 扫 trailing_stop_pct（take_profit 固定 0.18）---", flush=True)
        for tr in (0.10, 0.12, 0.15, 0.20):
            ensure(0.18, tr, f"tr={tr:.2f}     ")

    if args.phase in ("takeprofit", "all"):
        print("\n--- 扫 take_profit_pct（trailing 固定 0.08）---", flush=True)
        for tp in (0.25, 0.30, 0.40):
            ensure(tp, 0.08, f"tp={tp:.2f}     ")

    OUT_JSON.write_text(json.dumps(existing + results, ensure_ascii=False, indent=2, default=str))
    print(f"\n明细落盘: {OUT_JSON}", flush=True)

    print("\n=== 对比表（return% / win% / maxdd% / sharpe / pf）===")
    for r in results:
        if r.get("status") != "ready":
            continue
        print(
            f"tp={r['take_profit_pct']:.2f} tr={r['trailing_stop_pct']:.2f}: "
            f"{r['total_return_pct']:>6.1f}% {r['win_rate']:>5.1%} "
            f"{r['max_drawdown_pct']:>6.1f}% {r['sharpe']:>5.2f} {r['profit_factor']:>5.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
