"""大盘择时金手指/银手指历史表现评估脚本。

宿主跑(本地 docker postgres, 需能连到 vnpy-postgres-1):
  DATABASE_URL="postgresql+psycopg://alphaagent:***@<postgres_host>:5432/alphaagent" \
    uv run python scripts/market_timing_eval.py

输出: 确认后表现、全部候选表现、bootstrap CI、随机/持有基准和时间切分。
"""

from __future__ import annotations

import sys
from datetime import date
from statistics import mean

from alphaagent.server.db import schema, session as db_session
from alphaagent.server.services.quant.market_context import compute_market_contexts
from alphaagent.server.services.quant.market_timing import backtest as bt
from alphaagent.server.services.quant.market_timing import factors as fac
from alphaagent.server.services.quant.market_timing import series as ser
from alphaagent.server.services.quant.market_timing import signal as sig

START = date(2024, 5, 28)
END = date.today()


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
        factor_bars = []
        for i in range(len(dates)):
            if ctx_list[i] is None:
                continue
            ctx_window = [c for c in ctx_list[: i + 1] if c is not None]
            factor_seq.append(fac.compute_factors(ctx_window, closes[: i + 1], turns[: i + 1]))
            factor_bars.append(comp[i])
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

        print("检测信号事件(v7 通用 setup+结构危险区+次日确认) ...", flush=True)
        events = sig.detect_events(
            factor_seq,
            [bar.close for bar in factor_bars],
            [bar.up_ratio for bar in factor_bars],
        )
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

        print("评估历史表现 ...", flush=True)
        report = bt.evaluate(events, factor_bars)
        danger_report = _evaluate_danger_states(factor_seq, factor_bars)

    _print_report(report)
    _print_danger_report(danger_report)
    return 0


def _evaluate_danger_states(
    factors: list[fac.MarketTimingFactors],
    bars: list[ser.CompositeBar],
) -> dict:
    closes = [bar.close for bar in bars]
    up_ratios = [bar.up_ratio for bar in bars]
    states = sig.build_danger_states(factors, closes, up_ratios)
    structural_flags = [
        sig.is_structural_breakdown(
            factor,
            closes,
            index,
            up_ratios[index],
        )
        for index, factor in enumerate(factors)
    ]
    raw_entries = [
        index
        for index, active in enumerate(structural_flags)
        if active and (index == 0 or not structural_flags[index - 1])
    ]
    episode_starts = [
        index
        for index, state in enumerate(states)
        if state == sig.DANGER and (index == 0 or states[index - 1] == sig.NORMAL)
    ]
    return {
        "raw_entries": len(raw_entries),
        "episodes": _episode_metrics(episode_starts, closes),
        "danger_days": _state_metrics(states, sig.DANGER, closes),
        "normal_days": _state_metrics(states, sig.NORMAL, closes),
    }


def _episode_metrics(indices: list[int], closes: list[float]) -> dict:
    valid = [index for index in indices if index + 5 < len(closes)]
    returns = [
        (closes[index + 5] / closes[index] - 1.0) * 100.0
        for index in valid
    ]
    drawdowns = [
        (min(closes[index + 1 : index + 6]) / closes[index] - 1.0) * 100.0
        for index in valid
    ]
    return {
        "total": len(indices),
        "evaluable": len(valid),
        "avg_return_5d": mean(returns) if returns else None,
        "down_rate_5d": mean(value < 0 for value in returns) if returns else None,
        "drawdown_3_rate": mean(value <= -3 for value in drawdowns) if drawdowns else None,
    }


def _state_metrics(states: list[str], target: str, closes: list[float]) -> dict:
    valid = [
        index
        for index, state in enumerate(states)
        if state == target and index + 5 < len(closes)
    ]
    next_returns = [
        (closes[index + 1] / closes[index] - 1.0) * 100.0
        for index in valid
    ]
    drawdowns = [
        (min(closes[index + 1 : index + 6]) / closes[index] - 1.0) * 100.0
        for index in valid
    ]
    return {
        "count": len(valid),
        "avg_return_1d": mean(next_returns) if next_returns else None,
        "drawdown_3_rate": mean(value <= -3 for value in drawdowns) if drawdowns else None,
    }


def _print_report(report: dict) -> None:
    print("\n" + "=" * 82)
    print("金手指/银手指历史表现（观察性统计，非成交收益）")
    print("=" * 82)
    print(f"样本区间: {report['series_start']} ~ {report['series_end']}")
    _print_bucket_table(
        "确认后表现（仅 CONFIRMED，从确认日收盘起算）",
        report["buckets"],
    )
    _print_bucket_table(
        "全部候选表现（不经过次日筛选，从候选日收盘起算）",
        report["candidate_buckets"],
    )

    basis = report["evaluation_basis"]
    print(
        "\n评估起点: "
        f"确认后={basis['confirmed_start']} | 候选={basis['candidate_start']} | "
        f"可执行收益={basis['executable']}"
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
        f"待确认 {report.get('n_pending', 0)} | "
        f"确认后评估行 {report['n_evaluable']} | 候选评估行 {report['n_candidate_evaluable']}"
    )


def _print_danger_report(report: dict) -> None:
    episodes = report["episodes"]
    danger = report["danger_days"]
    normal = report["normal_days"]
    print("\n--- v7 结构危险区（观察性风险富集，日级样本存在序列相关） ---")
    print(
        f"原始条件重入 {report['raw_entries']} 次 | "
        f"独立阶段 {episodes['total']} 个（可评估 {episodes['evaluable']} 个）"
    )
    if episodes["evaluable"]:
        print(
            f"独立阶段未来5日: 平均 {episodes['avg_return_5d']:+.2f}% | "
            f"下跌率 {episodes['down_rate_5d'] * 100:.1f}% | "
            f"最大回撤<=-3% {episodes['drawdown_3_rate'] * 100:.1f}%"
        )
    print(
        f"危险状态 {danger['count']} 日: 次日平均 {danger['avg_return_1d']:+.3f}% | "
        f"未来5日最大回撤<=-3% {danger['drawdown_3_rate'] * 100:.1f}%"
    )
    print(
        f"正常状态 {normal['count']} 日: 次日平均 {normal['avg_return_1d']:+.3f}% | "
        f"未来5日最大回撤<=-3% {normal['drawdown_3_rate'] * 100:.1f}%"
    )


def _print_bucket_table(title: str, buckets: list[bt.BucketStat]) -> None:
    print(f"\n--- {title} ---")
    header = f"{'方向':<7}{'档位':<8}{'周期':>5}{'次数':>6}{'胜率':>8}{'95%CI':>15}{'均收益':>10}{'最差':>9}"
    print(header)
    print("-" * 82)
    for b in buckets:
        label = "金手指" if b.direction == "GOLD" else "银手指"
        ci = f"[{b.ci_low * 100:.0f}%,{b.ci_high * 100:.0f}%]"
        print(
            f"{label:<7}{b.grade:<8}{b.horizon:>4}d{b.count:>6}"
            f"{b.win_rate * 100:>7.0f}%{ci:>15}{b.avg_return:>+9.2f}%{b.worst_return:>+8.2f}%"
        )


if __name__ == "__main__":
    sys.exit(main())
