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
from alphaagent.server.services.market_context import compute_market_contexts
from alphaagent.server.services.market_timing import backtest as bt
from alphaagent.server.services.market_timing import factors as fac
from alphaagent.server.services.market_timing import series as ser
from alphaagent.server.services.market_timing import signal as sig

START = date(2024, 5, 28)
END = date.today()
STATE_SPLIT = date(2025, 7, 1)


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

        print("检测信号事件(v9 精度银+金失败保护+次日审计) ...", flush=True)
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
        state_directions = _build_state_variants(
            factor_seq,
            factor_bars,
            events,
        )
        state_reports = {
            name: bt.evaluate_direction_states(
                directions,
                factor_bars,
                split_date=STATE_SPLIT,
            )
            for name, directions in state_directions.items()
        }
        recovery_variants = _build_recovery_variants(
            factor_seq,
            factor_bars,
            events,
        )
        recovery_reports = {
            name: bt.evaluate_direction_states(
                result["directions"],
                factor_bars,
                split_date=STATE_SPLIT,
            )
            for name, result in recovery_variants.items()
        }
        base_directions = recovery_variants["V9_CURRENT"]["directions"]
        recovery_run_reports = {
            name: bt.evaluate_recovery_gold_runs(
                base_directions,
                result["events"],
                factor_bars,
            )
            for name, result in recovery_variants.items()
        }
        recovery_leave_one_out = {
            name: bt.evaluate_silver_run_leave_one_out(
                base_directions,
                result["directions"],
                factor_bars,
            )
            for name, result in recovery_variants.items()
            if name != "V9_CURRENT"
        }

    _print_report(report)
    _print_danger_report(danger_report)
    _print_state_comparison(state_directions, state_reports, factor_bars)
    _print_recovery_comparison(
        recovery_variants,
        recovery_reports,
        recovery_run_reports,
        recovery_leave_one_out,
    )
    return 0


def _build_state_variants(
    factors: list[fac.MarketTimingFactors],
    bars: list[ser.CompositeBar],
    events: list[sig.TimingSignal],
) -> dict[str, list[str]]:
    dates = [bar.trade_date for bar in bars]
    v8_events = [
        event
        for event in events
        if event.setup_type != sig.SETUP_GOLD_FAILURE_SILVER
    ]
    return {
        "V8_STRICT": sig.build_active_directions(dates, v8_events),
        "V9_CURRENT": sig.build_active_directions(dates, events),
        "VOL_HYSTERESIS": bt.build_volatility_hysteresis_directions(
            factors,
            bars,
            v8_events,
        ),
    }


def _build_recovery_variants(
    factors: list[fac.MarketTimingFactors],
    bars: list[ser.CompositeBar],
    events: list[sig.TimingSignal],
) -> dict[str, dict]:
    dates = [bar.trade_date for bar in bars]
    variants: dict[str, dict] = {
        "V9_CURRENT": {
            "directions": sig.build_active_directions(dates, events),
            "events": [],
        }
    }
    for variant in bt.RECOVERY_VARIANTS:
        variants[variant] = bt.build_recovery_gold_state(
            factors,
            bars,
            events,
            variant=variant,
        )
    if any(
        len(result["directions"]) != len(bars)
        for result in variants.values()
    ):
        raise RuntimeError("恢复金状态序列与行情长度不一致")
    return variants


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


def _print_state_comparison(
    variants: dict[str, list[str]],
    reports: dict[str, dict],
    bars: list[ser.CompositeBar],
) -> None:
    print("\n" + "=" * 110)
    print("持续金银状态对照（日级样本重叠，观察性统计，非成交收益）")
    print("=" * 110)
    print(f"固定切分: EARLY < {STATE_SPLIT} <= LATE")

    v8 = variants["V8_STRICT"]
    v9 = variants["V9_CURRENT"]
    first_difference = next(
        (
            (bars[index].trade_date, v8[index], v9[index])
            for index in range(len(bars))
            if v8[index] != v9[index]
        ),
        None,
    )
    print(f"v8/v9 首个状态差异: {first_difference or '无'}")

    print("\n--- 状态运行摘要 ---")
    print(
        f"{'版本':<18}{'金天数':>8}{'银天数':>8}{'金区间':>8}"
        f"{'银区间':>8}{'转换':>8}{'短金':>8}{'短银':>8}{'最新':>10}"
    )
    for name, report in reports.items():
        runs = report["runs"]
        print(
            f"{name:<18}"
            f"{runs['coverage_days']['GOLD']:>8}"
            f"{runs['coverage_days']['SILVER']:>8}"
            f"{runs['run_count']['GOLD']:>8}"
            f"{runs['run_count']['SILVER']:>8}"
            f"{runs['transition_count']:>8}"
            f"{runs['short_run_count']['GOLD']:>8}"
            f"{runs['short_run_count']['SILVER']:>8}"
            f"{runs['latest_direction']:>10}"
        )

    print("\n--- 未来 5 日核心指标 ---")
    print(
        f"{'版本':<18}{'区间':<8}{'方向':<8}{'天数':>7}{'命中':>8}"
        f"{'均收益':>10}{'方向均收益':>12}{'3%不利':>10}{'平均不利':>11}{'最坏不利':>11}"
    )
    for name, report in reports.items():
        for period in ("ALL", "EARLY", "LATE"):
            for direction in ("GOLD", "SILVER"):
                bucket = next(
                    (
                        item
                        for item in report["buckets"]
                        if item.period == period
                        and item.direction == direction
                        and item.horizon == 5
                    ),
                    None,
                )
                if bucket is None:
                    continue
                direction_label = "金" if direction == "GOLD" else "银"
                print(
                    f"{name:<18}{period:<8}{direction_label:<8}{bucket.count:>7}"
                    f"{bucket.hit_rate * 100:>7.1f}%"
                    f"{bucket.avg_return:>+9.2f}%"
                    f"{bucket.avg_directional_return:>+11.2f}%"
                    f"{bucket.adverse_3pct_rate * 100:>9.1f}%"
                    f"{bucket.avg_adverse_excursion:>+10.2f}%"
                    f"{bucket.worst_adverse_excursion:>+10.2f}%"
                )

    print("\n--- 全样本多周期方向稳定性 ---")
    print(
        f"{'版本':<18}{'方向':<8}{'周期':>7}{'天数':>8}{'命中':>9}"
        f"{'均收益':>11}{'方向均收益':>13}{'3%不利':>11}"
    )
    for name, report in reports.items():
        for direction in ("GOLD", "SILVER"):
            for horizon in bt.STATE_HORIZONS:
                bucket = next(
                    (
                        item
                        for item in report["buckets"]
                        if item.period == "ALL"
                        and item.direction == direction
                        and item.horizon == horizon
                    ),
                    None,
                )
                if bucket is None:
                    continue
                direction_label = "金" if direction == "GOLD" else "银"
                print(
                    f"{name:<18}{direction_label:<8}{horizon:>6}d{bucket.count:>8}"
                    f"{bucket.hit_rate * 100:>8.1f}%"
                    f"{bucket.avg_return:>+10.2f}%"
                    f"{bucket.avg_directional_return:>+12.2f}%"
                    f"{bucket.adverse_3pct_rate * 100:>10.1f}%"
                )
    print("\n口径: 状态日收盘起算 | executable=False | overlapping_daily_samples=True")


def _find_state_bucket(
    report: dict,
    period: str,
    direction: str,
    horizon: int,
) -> bt.StateBucketStat | None:
    return next(
        (
            item
            for item in report["buckets"]
            if item.period == period
            and item.direction == direction
            and item.horizon == horizon
        ),
        None,
    )


def _recovery_decision_checks(
    name: str,
    reports: dict[str, dict],
    run_rows: list[dict],
    leave_one_out: list[dict],
) -> list[tuple[str, bool, str]]:
    base_report = reports["V9_CURRENT"]
    report = reports[name]
    early_silver = _find_state_bucket(report, "EARLY", "SILVER", 5)
    late_silver = _find_state_bucket(report, "LATE", "SILVER", 5)
    silver_5d = _find_state_bucket(report, "ALL", "SILVER", 5)
    silver_10d = _find_state_bucket(report, "ALL", "SILVER", 10)
    gold_5d = _find_state_bucket(report, "ALL", "GOLD", 5)
    base_silver_5d = _find_state_bucket(base_report, "ALL", "SILVER", 5)
    base_gold_5d = _find_state_bucket(base_report, "ALL", "GOLD", 5)

    split_avg_pass = bool(
        early_silver
        and late_silver
        and early_silver.avg_return < 0
        and late_silver.avg_return < 0
    )
    split_hit_pass = bool(
        early_silver
        and late_silver
        and early_silver.hit_rate >= 0.60
        and late_silver.hit_rate >= 0.60
    )
    silver_10d_pass = bool(
        silver_10d
        and silver_10d.avg_return <= 0
        and silver_10d.hit_rate >= 0.55
    )
    silver_risk_pass = bool(
        silver_5d
        and base_silver_5d
        and silver_5d.worst_adverse_excursion
        <= base_silver_5d.worst_adverse_excursion
        and silver_5d.adverse_3pct_rate
        <= base_silver_5d.adverse_3pct_rate
    )
    gold_risk_pass = bool(
        gold_5d
        and base_gold_5d
        and gold_5d.avg_return > 0
        and gold_5d.adverse_3pct_rate
        <= base_gold_5d.adverse_3pct_rate + 0.01
    )
    runs = report["runs"]
    churn_pass = bool(
        runs["transition_count"] <= 12
        and runs["short_run_count"]["GOLD"] <= 2
    )
    improved = sum(row["outcome"] == "IMPROVED" for row in run_rows)
    false_recovery = sum(
        row["outcome"] == "FALSE_RECOVERY"
        for row in run_rows
    )
    run_pass = improved >= 3 and false_recovery <= 1
    loo_pass = bool(leave_one_out) and all(
        row["candidate_avg_return"] is not None
        and row["base_avg_return"] is not None
        and row["candidate_avg_return"] <= row["base_avg_return"]
        and row["candidate_adverse_3pct_rate"] is not None
        and row["base_adverse_3pct_rate"] is not None
        and row["candidate_adverse_3pct_rate"]
        <= row["base_adverse_3pct_rate"]
        for row in leave_one_out
    )

    def _split_detail(attribute: str, scale: float = 1.0) -> str:
        early = getattr(early_silver, attribute) * scale if early_silver else None
        late = getattr(late_silver, attribute) * scale if late_silver else None
        return f"EARLY={early:.2f} LATE={late:.2f}" if early is not None and late is not None else "缺样本"

    return [
        ("分段银5日均收益<0", split_avg_pass, _split_detail("avg_return")),
        ("分段银5日命中>=60%", split_hit_pass, _split_detail("hit_rate", 100.0)),
        (
            "银10日均收益<=0且命中>=55%",
            silver_10d_pass,
            (
                f"ret={silver_10d.avg_return:+.2f}% hit={silver_10d.hit_rate * 100:.1f}%"
                if silver_10d
                else "缺样本"
            ),
        ),
        (
            "银5日反弹风险不高于v9",
            silver_risk_pass,
            (
                f"worst={silver_5d.worst_adverse_excursion:+.2f}% adverse3={silver_5d.adverse_3pct_rate * 100:.1f}%"
                if silver_5d
                else "缺样本"
            ),
        ),
        (
            "金5日收益为正且3%不利增幅<=1pp",
            gold_risk_pass,
            (
                f"ret={gold_5d.avg_return:+.2f}% adverse3={gold_5d.adverse_3pct_rate * 100:.1f}%"
                if gold_5d
                else "缺样本"
            ),
        ),
        (
            "转换<=12且短金<=2",
            churn_pass,
            f"transitions={runs['transition_count']} short_gold={runs['short_run_count']['GOLD']}",
        ),
        (
            "改善银区间>=3且误恢复<=1",
            run_pass,
            f"improved={improved} false={false_recovery}",
        ),
        ("逐银区间留一均不劣于v9", loo_pass, f"folds={len(leave_one_out)}"),
    ]


def _print_recovery_comparison(
    variants: dict[str, dict],
    reports: dict[str, dict],
    run_reports: dict[str, list[dict]],
    leave_one_out: dict[str, list[dict]],
) -> None:
    print("\n" + "=" * 118)
    print("银状态恢复金研究（生产 v9 不变，研究 setup 不进入页面）")
    print("=" * 118)

    print("\n--- 恢复事件与状态运行 ---")
    print(
        f"{'版本':<18}{'候选':>7}{'确认':>7}{'否决':>7}{'待定':>7}"
        f"{'金天数':>9}{'银天数':>9}{'转换':>8}{'短金':>8}{'最新':>10}"
    )
    for name, result in variants.items():
        events = result["events"]
        runs = reports[name]["runs"]
        print(
            f"{name:<18}{len(events):>7}"
            f"{sum(event.status == sig.STATUS_CONFIRMED for event in events):>7}"
            f"{sum(event.status == sig.STATUS_INVALIDATED for event in events):>7}"
            f"{sum(event.status == sig.STATUS_PENDING for event in events):>7}"
            f"{runs['coverage_days']['GOLD']:>9}"
            f"{runs['coverage_days']['SILVER']:>9}"
            f"{runs['transition_count']:>8}"
            f"{runs['short_run_count']['GOLD']:>8}"
            f"{runs['latest_direction']:>10}"
        )

    print("\n--- 恢复候选事件 ---")
    print(
        f"{'版本':<18}{'候选日':<12}{'确认日':<12}{'状态':<14}"
        f"{'档位':<10}{'多头':>8}{'空头':>8}"
    )
    for name in bt.RECOVERY_VARIANTS:
        for event in variants[name]["events"]:
            print(
                f"{name:<18}{str(event.trade_date):<12}"
                f"{str(event.confirm_date or '-'): <12}{event.status:<14}"
                f"{event.grade:<10}{event.bull_force:>8.1f}{event.bear_force:>8.1f}"
            )

    print("\n--- 金银 5 日分段与银 10 日核心指标 ---")
    print(
        f"{'版本':<18}{'分段':<8}{'方向':<6}{'周期':>6}{'天数':>8}"
        f"{'命中':>9}{'均收益':>11}{'3%不利':>11}{'最坏不利':>12}"
    )
    for name, report in reports.items():
        keys = [
            (period, direction, 5)
            for period in ("ALL", "EARLY", "LATE")
            for direction in ("GOLD", "SILVER")
        ]
        keys.append(("ALL", "SILVER", 10))
        for period, direction, horizon in keys:
            bucket = _find_state_bucket(report, period, direction, horizon)
            if bucket is None:
                continue
            print(
                f"{name:<18}{period:<8}{direction:<6}{horizon:>5}d{bucket.count:>8}"
                f"{bucket.hit_rate * 100:>8.1f}%"
                f"{bucket.avg_return:>+10.2f}%"
                f"{bucket.adverse_3pct_rate * 100:>10.1f}%"
                f"{bucket.worst_adverse_excursion:>+11.2f}%"
            )

    print("\n--- 全样本 1/3/5/10/20 日方向稳定性 ---")
    print(
        f"{'版本':<18}{'方向':<7}{'周期':>7}{'天数':>8}{'命中':>9}"
        f"{'均收益':>11}{'方向均收益':>13}{'3%不利':>11}"
    )
    for name, report in reports.items():
        for direction in ("GOLD", "SILVER"):
            for horizon in bt.STATE_HORIZONS:
                bucket = _find_state_bucket(report, "ALL", direction, horizon)
                if bucket is None:
                    continue
                print(
                    f"{name:<18}{direction:<7}{horizon:>6}d{bucket.count:>8}"
                    f"{bucket.hit_rate * 100:>8.1f}%"
                    f"{bucket.avg_return:>+10.2f}%"
                    f"{bucket.avg_directional_return:>+12.2f}%"
                    f"{bucket.adverse_3pct_rate * 100:>10.1f}%"
                )

    for name in bt.RECOVERY_VARIANTS:
        print(f"\n--- {name} 逐基础银区间 ---")
        print(
            f"{'基础开始':<12}{'基础结束':<12}{'开放':>7}{'恢复确认':<12}"
            f"{'提前天数':>10}{'确认后5日':>12}{'分类':>18}"
        )
        for row in run_reports[name]:
            return_5d = (
                f"{row['return_5d']:+.2f}%"
                if row["return_5d"] is not None
                else "-"
            )
            print(
                f"{str(row['run_start']):<12}{str(row['run_end']):<12}"
                f"{str(row['open_run']):>7} {str(row['recovery_confirm_date'] or '-'): <12}"
                f"{row['advanced_days']:>10}{return_5d:>12}{row['outcome']:>18}"
            )

        print(f"\n--- {name} 逐银区间留一 ---")
        print(
            f"{'删除开始':<12}{'删除结束':<12}{'v9均收益':>12}{'研究均收益':>12}"
            f"{'v9不利':>10}{'研究不利':>10}{'通过':>8}"
        )
        for row in leave_one_out[name]:
            passed = bool(
                row["candidate_avg_return"] is not None
                and row["base_avg_return"] is not None
                and row["candidate_avg_return"] <= row["base_avg_return"]
                and row["candidate_adverse_3pct_rate"] is not None
                and row["base_adverse_3pct_rate"] is not None
                and row["candidate_adverse_3pct_rate"]
                <= row["base_adverse_3pct_rate"]
            )
            print(
                f"{str(row['omitted_start']):<12}{str(row['omitted_end']):<12}"
                f"{row['base_avg_return']:>+11.2f}%"
                f"{row['candidate_avg_return']:>+11.2f}%"
                f"{row['base_adverse_3pct_rate'] * 100:>9.1f}%"
                f"{row['candidate_adverse_3pct_rate'] * 100:>9.1f}%"
                f"{str(passed):>8}"
            )

        checks = _recovery_decision_checks(
            name,
            reports,
            run_reports[name],
            leave_one_out[name],
        )
        print(f"\n--- {name} 决策门槛 ---")
        for label, passed, detail in checks:
            print(f"{'PASS' if passed else 'FAIL':<5} {label}: {detail}")
        print(f"OVERALL: {'PASS' if all(item[1] for item in checks) else 'REJECT'}")

    print("\n口径: 状态日收盘起算 | executable=False | 生产 v9 未修改")


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
