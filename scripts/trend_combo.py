"""组合验证：trailing 0.10（单维度赢家）× take_profit 放宽，看是否叠加。

B 扫描结论：trailing 0.10 单维度 return 64.7%（+16.8pp），take_profit 放宽单维度
收益有限（tp=0.40 也只 55%）。但 tp=0.40 时 trailing_stop 转正(+29万)，暗示
"宽 trailing + 宽 tp"（让趋势充分奔跑）可能叠加。本脚本验证组合点。

只读 run_backtest(persist=False)，不改源码、不写库。跑完即可删除。
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

from alphaagent.server.services.backtest.engine import run_backtest
from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant.factors import TREND_ACCELERATION_STRATEGY_ID
from trend_exit_sweep import build_base, summarize

RANGE_START = date(2025, 3, 26)
RANGE_END = date(2026, 6, 18)
OUT_JSON = Path("/tmp/trend_combo.json")

# (take_profit, trailing) 组合点。trailing 0.10 固定 × tp 放宽，加几个对照。
COMBOS: list[tuple[float, float]] = [
    (0.18, 0.10),  # 赢家单维度（复现验证）
    (0.25, 0.10),
    (0.30, 0.10),
    (0.40, 0.10),
    (0.40, 0.12),  # 极宽对照（让趋势狂奔）
]


def run_one(base: BacktestParams, *, take_profit_pct: float, trailing_stop_pct: float) -> dict:
    params = replace(base, take_profit_pct=take_profit_pct, trailing_stop_pct=trailing_stop_pct)
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
    base = build_base()
    print(f"trend 组合验证，区间 {RANGE_START}..{RANGE_END}\n", flush=True)
    results: list[dict] = []
    for tp, tr in COMBOS:
        r = run_one(base, take_profit_pct=tp, trailing_stop_pct=tr)
        print_row(f"tp={tp:.2f} tr={tr:.2f}", r)
        results.append(r)
        OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))

    print(f"\n明细落盘: {OUT_JSON}\n", flush=True)
    print("=== 组合对比表 ===")
    print(f"{'tp':>6} {'tr':>6} {'return':>8} {'win':>7} {'maxdd':>8} {'sharpe':>7} {'pf':>6}")
    for r in results:
        if r.get("status") != "ready":
            continue
        print(
            f"{r['take_profit_pct']:>6.2f} {r['trailing_stop_pct']:>6.2f} "
            f"{r['total_return_pct']:>7.1f}% {r['win_rate']:>6.1%} "
            f"{r['max_drawdown_pct']:>7.1f}% {r['sharpe']:>7.2f} {r['profit_factor']:>6.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
