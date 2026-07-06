"""大盘择时金手指/银手指准确率评估脚本。

宿主跑(本地 docker postgres, 需能连到 vnpy-postgres-1):
  DATABASE_URL="postgresql+psycopg://alphaagent:***@<postgres_host>:5432/alphaagent" \
    uv run python scripts/market_timing_eval.py

输出: 金手指/银手指各档 × 5/10/20 日 胜率矩阵 + bootstrap CI + 随机/持有基准 + 时间切分。
"""

from __future__ import annotations

import sys
from datetime import date

from alphaagent.server.db import schema, session as db_session
from alphaagent.server.services.quant.market_context import compute_market_contexts
from alphaagent.server.services.quant.market_timing import backtest as bt
from alphaagent.server.services.quant.market_timing import factors as fac
from alphaagent.server.services.quant.market_timing import series as ser
from alphaagent.server.services.quant.market_timing import signal as sig

START = date(2024, 5, 28)
END = date(2026, 6, 30)


def main() -> int:
    if not db_session.is_database_configured():
        print("DATABASE_URL 未配置, 无法评估")
        return 1

    factory = db_session.get_session_factory()
    with factory() as session:
        print(f"加载综合指数序列 {START} ~ {END} ...", flush=True)
        comp = ser.load_composite_series(session, schema, START, END)
        if not comp:
            print("综合序列为空, 退出")
            return 1
        print(f"  序列 {len(comp)} 天: {comp[0].trade_date} ~ {comp[-1].trade_date}", flush=True)

        dates = [b.trade_date for b in comp]
        print("计算 market_context(含全市场广度, 较慢, 约数分钟) ...", flush=True)
        ctx_map = compute_market_contexts(session, schema, dates)
        print(f"  context 命中 {len(ctx_map)} / {len(dates)} 天", flush=True)

        print("计算因子序列 ...", flush=True)
        closes = [b.close for b in comp]
        turns = [b.turnover for b in comp]
        ctx_list = [ctx_map.get(d) for d in dates]
        factor_seq = []
        for i in range(len(dates)):
            if ctx_list[i] is None:
                continue
            ctx_window = [c for c in ctx_list[: i + 1] if c is not None]
            factor_seq.append(fac.compute_factors(ctx_window, closes[: i + 1], turns[: i + 1]))
        print(f"  因子 {len(factor_seq)} 天", flush=True)

        # bull/bear 分布(帮判断阈值是否合理)
        bulls = [f.bull_force for f in factor_seq]
        bears = [f.bear_force for f in factor_seq]
        bulls.sort(); bears.sort()
        print(
            f"  bull_force 中位={bulls[len(bulls)//2]:.1f} P20={bulls[len(bulls)//5]:.1f} "
            f"P80={bulls[len(bulls)*4//5]:.1f} | bear_force 中位={bears[len(bears)//2]:.1f} "
            f"P80={bears[len(bears)*4//5]:.1f}",
            flush=True,
        )

        print("检测信号事件(v4 候选+确认两状态) ...", flush=True)
        events = sig.detect_events(factor_seq, closes)
        gold = [e for e in events if e.direction == "GOLD"]
        silver = [e for e in events if e.direction == "SILVER"]
        confirmed = [e for e in events if e.status == sig.STATUS_CONFIRMED]
        invalidated = [e for e in events if e.status == sig.STATUS_INVALIDATED]
        pending = [e for e in events if e.status == sig.STATUS_PENDING]
        print(
            f"  事件 {len(events)} 个: 金手指={len(gold)} 银手指={len(silver)} | "
            f"已确认={len(confirmed)} 假突破否决={len(invalidated)} 待确认={len(pending)}",
            flush=True,
        )

        print("评估准确率 ...", flush=True)
        report = bt.evaluate(events, comp)

    _print_report(report)
    return 0


def _print_report(report: dict) -> None:
    print("\n" + "=" * 82)
    print("金手指/银手指 准确率矩阵 (v4 候选+确认两状态, 主表只算 CONFIRMED)")
    print("=" * 82)
    print(f"样本区间: {report['series_start']} ~ {report['series_end']}")
    header = f"{'方向':<7}{'档位':<8}{'周期':>5}{'次数':>6}{'胜率':>8}{'95%CI':>15}{'均收益':>10}{'最差':>9}"
    print(header)
    print("-" * 82)
    for b in report["buckets"]:
        label = "金手指" if b.direction == "GOLD" else "银手指"
        ci = f"[{b.ci_low * 100:.0f}%,{b.ci_high * 100:.0f}%]"
        print(
            f"{label:<7}{b.grade:<8}{b.horizon:>4}d{b.count:>6}"
            f"{b.win_rate * 100:>7.0f}%{ci:>15}{b.avg_return:>+9.2f}%{b.worst_return:>+8.2f}%"
        )

    print("\n--- 基准对比 ---")
    base = report["random_baseline_up_rate"]
    print(
        "随机基准(全样本未来N日上涨比例, 即随机信号期望胜率): "
        + ", ".join(f"{h}日={base[h] * 100:.0f}%" for h in (5, 10, 20))
    )
    if report["buy_hold_return_pct"] is not None:
        print(f"全仓持有基准(首→末): {report['buy_hold_return_pct']:+.2f}%")

    print(f"\n--- 时间切分(训练段 < {report['split_date']} ≤ 样本外) ---")
    for tag, label in (("train", "训练段"), ("test", "样本外")):
        items = report["split_winrate"].get(tag, {})
        if not items:
            print(f"  {label}: 无样本")
            continue
        parts = []
        for (d, g, h), (w, t) in sorted(items.items()):
            rate = w / t if t else 0.0
            mark = "★" if rate >= 0.6 else ("☆" if rate >= 0.5 else " ")
            parts.append(f"{mark}{d[0]}{g[0]}{h}d={w}/{t}")
        print(f"  {label}: " + " ".join(parts))

    print(
        f"\n事件总数 {report['n_events']} | "
        f"已确认 {report.get('n_confirmed', 0)} | 假突破否决 {report.get('n_invalidated', 0)} | "
        f"待确认 {report.get('n_pending', 0)} | 评估行数 {report['n_evaluable']}"
    )
    inval = report.get("invalidated_summary") or {}
    if inval:
        print("\n--- 假突破候选后续表现(对比 CONFIRMED, 揭示次日确认是否真有预测力) ---")
        for h in (5, 10, 20):
            row = inval.get(h)
            if row:
                print(
                    f"  {h}日: 样本 {row['count']} | 均收益 {row['avg_return']:+.2f}% | "
                    f"方向命中率 {row['win_rate'] * 100:.0f}%"
                )


if __name__ == "__main__":
    sys.exit(main())
