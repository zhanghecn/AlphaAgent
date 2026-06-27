"""跑单次 trend 回测（exit 固定 tr=0.10/tp=0.18 赢家配置），输出 stop_loss/return 摘要。

A' 测试：门控由容器内 trend_acceleration.py 决定（外部 sed 覆盖 return_5d 上限），
本脚本只负责跑回测 + 摘要。本地主线 trend_acceleration.py 零影响（测完 cp 原版恢复）。
"""

from __future__ import annotations

import sys
from dataclasses import replace

from alphaagent.server.services.backtest.engine import run_backtest
from trend_exit_sweep import build_base, summarize


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "current"
    base = replace(build_base(), trailing_stop_pct=0.08, take_profit_pct=0.18)
    result = run_backtest(base)
    s = summarize(result)
    if s.get("status") != "ready" and "total_return_pct" not in s:
        print(f"{label}: status={result.get('status')}", flush=True)
        return 1
    sl = s["stop_loss"]
    tp = s["take_profit"]
    tr = s["trailing_stop"]
    print(
        f"{label}: return={s['total_return_pct']:.1f}% win={s['win_rate']:.1%} "
        f"maxdd={s['max_drawdown_pct']:.1f}% sharpe={s['sharpe']:.2f} pf={s['profit_factor']:.2f} "
        f"buy/sell={s['buy_count']}/{s['sell_count']} | "
        f"tp={tp['n']}/{tp['pnl']:.0f} tr={tr['n']}/{tr['pnl']:.0f} sl={sl['n']}/{sl['pnl']:.0f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
