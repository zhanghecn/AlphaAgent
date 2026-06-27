"""测 trend 结构性 sell（trend_acceleration_sell_reason）全样本表现 + 完整 reason 分布。

simulation.py 已加 trend 专用 sell（ma20 支撑止损/profit_protection/ma10 trailing）。
本脚本跑 trend 全样本，对比 baseline（generic evaluate_exit，trend_exit_sweep 的
tp=0.18/tr=0.08/sl=0.08: return 47.9%/sharpe 1.17）。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from alphaagent.server.services.backtest.engine import run_backtest
from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant.factors import TREND_ACCELERATION_STRATEGY_ID

RANGE_START = date(2025, 3, 26)
RANGE_END = date(2026, 6, 18)
OUT_JSON = Path("/tmp/trend_structural.json")


def main() -> int:
    params = BacktestParams(
        strategy=TREND_ACCELERATION_STRATEGY_ID,
        start=RANGE_START,
        end=RANGE_END,
        min_entry_score=73.0,
        strict_entry=True,
        max_symbols=5000,
        max_position_pct=0.125,
        stop_loss_pct=0.08,
        take_profit_pct=0.18,
        trailing_stop_pct=0.08,  # 新 sell 不用 trailing，参数保留无害
        persist=False,
    )
    result = run_backtest(params)
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

    print("\n=== trend 结构性 sell（trend_acceleration_sell_reason）===", flush=True)
    print(
        f"return={metrics.get('total_return_pct'):.1f}% win={metrics.get('win_rate'):.1%} "
        f"maxdd={metrics.get('max_drawdown_pct'):.1f}% sharpe={metrics.get('sharpe'):.2f} "
        f"pf={metrics.get('profit_factor'):.2f} buy/sell={metrics.get('buy_count')}/{metrics.get('sell_count')}",
        flush=True,
    )
    print("\nbaseline 对比: return=47.9% win=41.0% maxdd=-21.6% sharpe=1.17 pf=1.25", flush=True)
    print("\n--- reason 分布（按 pnl 升序）---", flush=True)
    for reason, b in sorted(reason_pnl.items(), key=lambda x: x[1]["pnl"]):
        n = b["n"]
        avg = b["pnl"] / n if n else 0
        print(
            f"  {reason:<28} n={n:>4} pnl={b['pnl']:>10.0f} avg={avg:>8.0f} win={b['wins']}/{n}",
            flush=True,
        )

    summary = {
        "total_return_pct": metrics.get("total_return_pct"),
        "win_rate": metrics.get("win_rate"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe": metrics.get("sharpe"),
        "profit_factor": metrics.get("profit_factor"),
        "buy_count": metrics.get("buy_count"),
        "sell_count": metrics.get("sell_count"),
        "reason_breakdown": {
            k: {"n": v["n"], "pnl": round(v["pnl"], 0), "wins": v["wins"]}
            for k, v in reason_pnl.items()
        },
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"\n明细落盘: {OUT_JSON}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
