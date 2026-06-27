"""门控稳健性检验：指定区间跑 trend 回测。门控由容器 trend_acceleration.py 决定（外部 cp）。

用法：python trend_stability_test.py <start> <end> <label>
对比门控版(latest_change_pct>0) vs 原版，分 3 段看是否各段都赢（防窄峰过拟合）。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date

from alphaagent.server.services.backtest.engine import run_backtest
from trend_exit_sweep import build_base, summarize


def main() -> int:
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    label = sys.argv[3]
    base = replace(build_base(), start=start, end=end)
    result = run_backtest(base)
    s = summarize(result)
    sl = s["stop_loss"]
    tp = s["take_profit"]
    print(
        f"{label}: return={s['total_return_pct']:.1f}% sharpe={s['sharpe']:.2f} "
        f"maxdd={s['max_drawdown_pct']:.1f}% win={s['win_rate']:.1%} "
        f"buy={s['buy_count']} sl={sl['n']}/{sl['pnl']:.0f} tp={tp['n']}/{tp['pnl']:.0f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
