"""top5/10/20 cohort 等权质量评估（候选独立买卖）。

复用 acceptance test 的 cohort helper：每只候选独立 D+1 开盘入场、按策略卖点逐日退出，
不读取组合成交约束。分别按 top5/10/20 汇总收益/胜率/回撤。
宿主跑：DATABASE_URL=... uv run python scripts/cohort_topn_eval.py
"""

from __future__ import annotations

import importlib.util
import statistics
from datetime import date

# 用 importlib 加载 acceptance test 模块（含 cohort helper）
_spec = importlib.util.spec_from_file_location(
    "acc_cohort", "tests/alphaagent/test_quant_strategy_acceptance.py"
)
acc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(acc)

from alphaagent.server.services.backtest.schemas import BacktestParams


def main() -> int:
    params = BacktestParams(
        start=date(2025, 9, 1),
        end=date(2026, 6, 18),
        max_symbols=5000,
        persist=False,
        reuse_signal_cache=False,
    )
    print("取 top20 候选 + bars（评分全部日期，约10分钟）...", flush=True)
    candidates, bars = acc._current_code_top_candidate_rows(params, top_n=20)
    print(f"候选数={len(candidates)}", flush=True)

    print("算 path（每只 D+1入场+卖点退出）...", flush=True)
    report = acc._candidate_path_report(candidates, bars, params, top_n=20)
    path_rows = report["rows"]
    print(f"path数={len(path_rows)}", flush=True)

    print("\n" + "=" * 64)
    print("top5/10/20 cohort 质量（候选独立等权，每只独立入场退出）")
    print("=" * 64)
    print(f"{'topN':<6}{'样本':>6}{'胜率':>8}{'均收益':>10}{'中位收益':>10}{'均回撤':>10}{'均持仓天':>10}")
    for top_n in (5, 10, 20):
        rows_n = [r for r in path_rows if r.get("rank") and r["rank"] <= top_n]
        summary = acc._candidate_metric_summary(rows_n)
        rets = [r.get("return_pct") for r in rows_n if r.get("return_pct") is not None]
        win = summary.get("win_rate") or 0
        med = statistics.median(rets) if rets else 0
        print(
            f"{top_n:<6}{len(rows_n):>6}{win * 100:>7.0f}%"
            f"{summary.get('average_return_pct', 0):>9.1f}%{med:>9.1f}%"
            f"{summary.get('average_max_drawdown_pct', 0):>9.1f}%"
            f"{summary.get('average_holding_days', 0):>9.1f}"
        )

    # top5 逐票明细：按卖点(exit_reason)分组 + 日均收益(主人法 return/days) + 示例
    top5_rows = [r for r in path_rows if r.get("rank") and r["rank"] <= 5]
    print("\n" + "=" * 64)
    print("top5 逐票明细：按卖点(exit_reason)分组")
    print("=" * 64)
    print(f"{'卖点':<26}{'笔数':>5}{'胜率':>7}{'均收益':>9}{'均天数':>7}{'日均收益':>9}")
    from collections import defaultdict
    by_exit = defaultdict(list)
    for r in top5_rows:
        by_exit[r.get("exit_reason") or "unknown"].append(r)
    for exit_r, rows in sorted(by_exit.items(), key=lambda x: -len(x[1])):
        rets = [r.get("return_pct") or 0 for r in rows]
        days = [r.get("holding_days") or 1 for r in rows]
        win = sum(1 for x in rets if x > 0) / len(rets) * 100
        avg_ret = sum(rets) / len(rets)
        avg_days = sum(days) / len(days)
        daily = avg_ret / avg_days if avg_days else 0
        print(f"{str(exit_r)[:25]:<26}{len(rows):>5}{win:>6.0f}%{avg_ret:>8.1f}%{avg_days:>6.1f}{daily:>8.2f}%")

    all_daily = [(r.get("return_pct") or 0) / (r.get("holding_days") or 1) for r in top5_rows if r.get("holding_days")]
    print(f"\ntop5 日均收益/笔(主人法 return÷days): 平均={sum(all_daily)/len(all_daily):.3f}%/天 中位={statistics.median(all_daily):.3f}%/天")

    print(f"\n--- top5 示例明细(前20只, 买→卖/卖点/天/收益/日均) ---")
    print(f"{'候选日':<11}{'rk':<3}{'代码':<12}{'买→卖':<24}{'卖点':<20}{'天':>4}{'收益':>8}{'日均':>7}")
    for r in top5_rows[:20]:
        ret = r.get("return_pct") or 0
        days = r.get("holding_days") or 1
        buy = str(r.get("entry_execute_date"))[:10]
        sell = str(r.get("exit_execute_date"))[:10]
        print(f"{str(r.get('signal_date'))[:10]:<11}{r.get('rank')!s:<3}{r.get('vt_symbol','')[:11]:<12}{buy+'→'+sell:<24}{str(r.get('exit_reason'))[:19]:<20}{days!s:>4}{ret:>7.1f}%{ret/days:>6.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
