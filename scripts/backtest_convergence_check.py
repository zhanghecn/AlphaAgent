"""convergence 放宽后全盘回测，对比 #194 基线（convergence 旧）。

reuse_signal_cache=False 强制用新 convergence 代码重算全部信号（不复用落库旧信号）。
#194 基线: 收益82.99% / 胜率32.24% / max_dd-15.59% / sharpe~2.38 / buy224 sell214。
若新回测收益/胜率不显著下降 -> convergence 放宽整体安全，可保留。
"""

from __future__ import annotations

import time
from datetime import date

from alphaagent.server.services.backtest.engine import run_backtest
from alphaagent.server.services.backtest.schemas import BacktestParams


def main() -> int:
    params = BacktestParams(
        start=date(2025, 3, 26),
        end=date(2026, 6, 18),
        min_entry_score=76.0,
        strict_entry=True,
        max_symbols=5000,
        persist=False,
        reuse_signal_cache=False,  # 强制新 convergence 重算
    )
    t = time.time()
    r = run_backtest(params)
    print(f"耗时 {time.time() - t:.0f}s  status={r.get('status')}", flush=True)
    m = r.get("metrics", {}) or {}
    print("=" * 60, flush=True)
    print("convergence 放宽后全盘回测（新代码）:", flush=True)
    print(
        f"  收益={m.get('total_return_pct')}  胜率={m.get('win_rate')}  "
        f"max_dd={m.get('max_drawdown_pct')}  sharpe={m.get('sharpe_ratio')}  "
        f"PF={m.get('profit_factor')}",
        flush=True,
    )
    print("  buy={}, sell={}".format(m.get("buy_count"), m.get("sell_count")), flush=True)
    print("#194 基线（convergence 旧）: 收益82.99% 胜率32.24% max_dd-15.59% sharpe~2.38", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
