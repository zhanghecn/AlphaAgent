"""金手指/银手指历史表现评估。

- 多周期胜率(5/10/20 日): 金手指判对=未来收益>0, 银手指判对=<0。
- bootstrap 95% 置信区间: 强信号样本少, 给胜率加 CI, 区间过宽=样本不足。
- 随机基准: 全样本未来 N 日上涨比例(证明胜率 > 基准非偶然)。
- 全仓持有基准: 首→末收益。
- 时间切分: 前 80% / 后 20% 各档胜率(检测过拟合)。

未来收益只在本模块计算, 不进入 factors/signal, 物理隔离。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from statistics import pstdev
from typing import Literal

from alphaagent.server.services.market_timing.factors import MarketTimingFactors
from alphaagent.server.services.market_timing.series import CompositeBar
from alphaagent.server.services.market_timing.signal import (
    STATUS_CONFIRMED,
    STATUS_INVALIDATED,
    STATUS_PENDING,
    TimingSignal,
)

HORIZONS = (5, 10, 20)
STATE_HORIZONS = (1, 3, 5, 10, 20)
SETUP_RECOVERY_GOLD = "RECOVERY_GOLD"
RECOVERY_R1_REPAIR = "R1_REPAIR"
RECOVERY_R2_BULL_CROSS = "R2_BULL_CROSS"
RECOVERY_R3_MA20 = "R3_MA20"
RECOVERY_VARIANTS = (
    RECOVERY_R1_REPAIR,
    RECOVERY_R2_BULL_CROSS,
    RECOVERY_R3_MA20,
)
RECOVERY_UP_RATIO_MIN = 0.50
RECOVERY_BEAR_MAX = 65.0
_BOOT_SEED = 20260701  # 固定种子, 保证可复现(Math.random 在 workflow 外可用)
EvaluationStart = Literal["trade_date", "confirm_date"]


@dataclass
class BucketStat:
    direction: str
    grade: str
    horizon: int
    count: int
    win_rate: float
    avg_return: float
    worst_return: float       # 金手指=最小收益(最差), 银手指=最大收益(最差)
    ci_low: float
    ci_high: float


@dataclass
class StateBucketStat:
    period: str
    direction: str
    horizon: int
    count: int
    hit_rate: float
    avg_return: float
    avg_directional_return: float
    avg_adverse_excursion: float
    worst_adverse_excursion: float
    adverse_3pct_rate: float


def _future_returns(series: list[CompositeBar], idx: int) -> dict[int, float | None]:
    base = series[idx].close
    n = len(series)
    out: dict[int, float | None] = {}
    for h in HORIZONS:
        j = idx + h
        out[h] = (series[j].close / base - 1.0) * 100.0 if j < n else None
    return out


def _is_correct(direction: str, ret: float) -> bool:
    return ret > 0 if direction == "GOLD" else ret < 0


def _bootstrap_ci(corrects: list[bool], n_boot: int = 1000, ci: float = 0.95) -> tuple[float, float]:
    if not corrects:
        return 0.0, 0.0
    n = len(corrects)
    rng = random.Random(_BOOT_SEED)
    rates: list[float] = []
    for _ in range(n_boot):
        wins = sum(1 for _ in range(n) if corrects[rng.randrange(n)])
        rates.append(wins / n)
    rates.sort()
    lo = rates[int((1 - ci) / 2 * n_boot)]
    hi = rates[min(int((1 + ci) / 2 * n_boot), n_boot - 1)]
    return lo, hi


def _evaluate_rows(
    events: list[TimingSignal],
    series: list[CompositeBar],
    *,
    start_date_field: EvaluationStart,
) -> list[dict]:
    date_idx = {b.trade_date: i for i, b in enumerate(series)}
    rows: list[dict] = []
    for ev in events:
        start_date = getattr(ev, start_date_field)
        idx = date_idx.get(start_date)
        if idx is None:
            continue
        for h, r in _future_returns(series, idx).items():
            if r is None:
                continue
            rows.append(
                {
                    "date": start_date,
                    "candidate_date": ev.trade_date,
                    "confirm_date": ev.confirm_date,
                    "start_date": start_date,
                    "direction": ev.direction,
                    "setup_type": ev.setup_type,
                    "status": ev.status,
                    "grade": ev.grade,
                    "horizon": h,
                    "return": r,
                    "correct": _is_correct(ev.direction, r),
                }
            )
    return rows


def _build_buckets(rows: list[dict]) -> list[BucketStat]:
    buckets: list[BucketStat] = []
    for direction in ("GOLD", "SILVER"):
        for grade in ("STRONG", "MEDIUM", "WEAK"):
            for h in HORIZONS:
                subset = [
                    r for r in rows
                    if r["direction"] == direction and r["grade"] == grade and r["horizon"] == h
                ]
                if not subset:
                    continue
                corrects = [r["correct"] for r in subset]
                rets = [r["return"] for r in subset]
                wr = sum(corrects) / len(corrects)
                ci_lo, ci_hi = _bootstrap_ci(corrects)
                buckets.append(
                    BucketStat(
                        direction=direction,
                        grade=grade,
                        horizon=h,
                        count=len(subset),
                        win_rate=wr,
                        avg_return=sum(rets) / len(rets),
                        worst_return=min(rets) if direction == "GOLD" else max(rets),
                        ci_low=ci_lo,
                        ci_high=ci_hi,
                    )
                )
    return buckets


def _random_baseline(series: list[CompositeBar]) -> dict[int, float]:
    """全样本未来 N 日上涨比例(随机信号期望胜率)。"""
    out: dict[int, float] = {}
    n = len(series)
    for h in HORIZONS:
        valid = [i for i in range(n) if i + h < n]
        if not valid:
            out[h] = 0.0
            continue
        ups = sum(1 for i in valid if series[i + h].close / series[i].close - 1.0 > 0)
        out[h] = ups / len(valid)
    return out


def _split_winrate(rows: list[dict], split_date: date) -> dict[str, dict[tuple[str, str, int], list[int]]]:
    out: dict[str, dict[tuple[str, str, int], list[int]]] = {"train": {}, "test": {}}
    for r in rows:
        tag = "train" if r["date"] < split_date else "test"
        key = (r["direction"], r["grade"], r["horizon"])
        win_tot = out[tag].setdefault(key, [0, 0])
        win_tot[1] += 1
        if r["correct"]:
            win_tot[0] += 1
    return out


def _summarize_by_horizon(
    events: list[TimingSignal], series: list[CompositeBar]
) -> dict[int, dict]:
    """按 horizon 汇总事件的平均收益/胜率(从候选日起算)。

    保留 INVALIDATED 候选的旧审计摘要。它与确认后 buckets 的起点不同，
    不应直接横向比较；未经次日筛选的主对照应使用 candidate_buckets。
    """
    if not events:
        return {}
    rows = _evaluate_rows(events, series, start_date_field="trade_date")
    out: dict[int, dict] = {}
    for h in HORIZONS:
        sub = [r for r in rows if r["horizon"] == h]
        if not sub:
            continue
        rets = [r["return"] for r in sub]
        corrects = [r["correct"] for r in sub]
        out[h] = {
            "count": len(sub),
            "avg_return": round(sum(rets) / len(rets), 4),
            "win_rate": round(sum(corrects) / len(corrects), 4),
        }
    return out


def evaluate(
    events: list[TimingSignal], series: list[CompositeBar]
) -> dict:
    """分别评估确认后表现和未经次日状态筛选的全部候选表现。

    - rows/buckets: 只含 CONFIRMED，从确认日收盘起算。
    - candidate_rows/candidate_buckets: 包含所有候选，从候选日收盘起算。
    - 两组都是观察性表现，不是包含成交价、滑点和费用的可执行收益。
    """
    confirmed = [e for e in events if e.status == STATUS_CONFIRMED]
    invalidated = [e for e in events if e.status == STATUS_INVALIDATED]
    pending = [e for e in events if e.status == STATUS_PENDING]

    rows = _evaluate_rows(confirmed, series, start_date_field="confirm_date")
    buckets = _build_buckets(rows)
    candidate_rows = _evaluate_rows(events, series, start_date_field="trade_date")
    candidate_buckets = _build_buckets(candidate_rows)

    # 时间切分: 前 80% 为训练段(调阈值), 后 20% 为样本外
    split_date = series[int(len(series) * 0.8)].trade_date if series else None
    split_stats = _split_winrate(rows, split_date) if split_date else {"train": {}, "test": {}}

    # 全仓持有基准
    buy_hold = (series[-1].close / series[0].close - 1) * 100 if len(series) >= 2 else None

    return {
        "buckets": buckets,
        "rows": rows,
        "candidate_buckets": candidate_buckets,
        "candidate_rows": candidate_rows,
        "evaluation_basis": {
            "confirmed_start": "confirm_date_close",
            "candidate_start": "candidate_date_close",
            "executable": False,
        },
        "random_baseline_up_rate": _random_baseline(series),
        "buy_hold_return_pct": buy_hold,
        "split_date": split_date,
        "split_winrate": split_stats,
        "n_events": len(events),
        "n_confirmed": len(confirmed),
        "n_invalidated": len(invalidated),
        "n_pending": len(pending),
        "n_evaluable": len(rows),
        "n_candidate_evaluable": len(candidate_rows),
        "invalidated_summary": _summarize_by_horizon(invalidated, series),
        "series_start": series[0].trade_date if series else None,
        "series_end": series[-1].trade_date if series else None,
    }


def _direction_run_ranges(
    directions: list[str],
) -> list[tuple[str, int, int]]:
    runs: list[tuple[str, int, int]] = []
    current: str | None = None
    start = 0
    for index, direction in enumerate(directions):
        if direction not in {"GOLD", "SILVER"}:
            if current is not None:
                runs.append((current, start, index - 1))
                current = None
            continue
        if direction == current:
            continue
        if current is not None:
            runs.append((current, start, index - 1))
        current = direction
        start = index
    if current is not None:
        runs.append((current, start, len(directions) - 1))
    return runs


def _state_run_summary(directions: list[str]) -> dict:
    coverage = {
        direction: sum(value == direction for value in directions)
        for direction in ("GOLD", "SILVER", "NEUTRAL")
    }
    ranges = _direction_run_ranges(directions)
    runs = [
        (direction, end - start + 1)
        for direction, start, end in ranges
    ]

    run_count: dict[str, int] = {}
    avg_run_days: dict[str, float] = {}
    short_run_count: dict[str, int] = {}
    for direction in ("GOLD", "SILVER"):
        lengths = [
            run_length
            for run_direction, run_length in runs
            if run_direction == direction
        ]
        run_count[direction] = len(lengths)
        avg_run_days[direction] = sum(lengths) / len(lengths) if lengths else 0.0
        short_run_count[direction] = sum(run_length <= 3 for run_length in lengths)

    latest_direction = next(
        (
            direction
            for direction in reversed(directions)
            if direction in {"GOLD", "SILVER"}
        ),
        "NEUTRAL",
    )
    return {
        "coverage_days": coverage,
        "run_count": run_count,
        "avg_run_days": avg_run_days,
        "short_run_count": short_run_count,
        "transition_count": sum(
            left[0] != right[0]
            for left, right in zip(runs, runs[1:], strict=False)
        ),
        "latest_direction": latest_direction,
    }


def evaluate_direction_states(
    directions: list[str],
    series: list[CompositeBar],
    *,
    split_date: date,
) -> dict:
    """评估逐日持续金银状态；未来价格只用于标签。"""
    if len(directions) != len(series):
        raise ValueError("directions 与 series 长度必须一致")

    rows: list[dict] = []
    for index, direction in enumerate(directions):
        if direction not in {"GOLD", "SILVER"}:
            continue
        base = series[index].close
        if base <= 0:
            continue
        for horizon in STATE_HORIZONS:
            end_index = index + horizon
            if end_index >= len(series):
                continue
            future_returns = [
                (series[future_index].close / base - 1.0) * 100.0
                for future_index in range(index + 1, end_index + 1)
            ]
            final_return = future_returns[-1]
            if direction == "GOLD":
                directional_return = final_return
                adverse_excursion = min(0.0, min(future_returns))
                adverse_3pct = adverse_excursion <= -3.0
            else:
                directional_return = -final_return
                adverse_excursion = max(0.0, max(future_returns))
                adverse_3pct = adverse_excursion >= 3.0
            rows.append(
                {
                    "date": series[index].trade_date,
                    "period": (
                        "EARLY"
                        if series[index].trade_date < split_date
                        else "LATE"
                    ),
                    "direction": direction,
                    "horizon": horizon,
                    "return": final_return,
                    "directional_return": directional_return,
                    "correct": directional_return > 0,
                    "adverse_excursion": adverse_excursion,
                    "adverse_3pct": adverse_3pct,
                }
            )

    buckets: list[StateBucketStat] = []
    for period in ("ALL", "EARLY", "LATE"):
        for direction in ("GOLD", "SILVER"):
            for horizon in STATE_HORIZONS:
                subset = [
                    row
                    for row in rows
                    if row["direction"] == direction
                    and row["horizon"] == horizon
                    and (period == "ALL" or row["period"] == period)
                ]
                if not subset:
                    continue
                count = len(subset)
                adverse_values = [row["adverse_excursion"] for row in subset]
                buckets.append(
                    StateBucketStat(
                        period=period,
                        direction=direction,
                        horizon=horizon,
                        count=count,
                        hit_rate=sum(row["correct"] for row in subset) / count,
                        avg_return=sum(row["return"] for row in subset) / count,
                        avg_directional_return=(
                            sum(row["directional_return"] for row in subset) / count
                        ),
                        avg_adverse_excursion=sum(adverse_values) / count,
                        worst_adverse_excursion=(
                            min(adverse_values)
                            if direction == "GOLD"
                            else max(adverse_values)
                        ),
                        adverse_3pct_rate=(
                            sum(row["adverse_3pct"] for row in subset) / count
                        ),
                    )
                )

    return {
        "buckets": buckets,
        "rows": rows,
        "runs": _state_run_summary(directions),
        "split_date": split_date,
        "evaluation_basis": {
            "start": "state_date_close",
            "executable": False,
            "overlapping_daily_samples": True,
        },
        "series_start": series[0].trade_date if series else None,
        "series_end": series[-1].trade_date if series else None,
    }


def _should_enter_volatility_hysteresis_silver(
    factor: MarketTimingFactors,
    series: list[CompositeBar],
    returns: list[float],
    index: int,
) -> bool:
    up_ratio = series[index].up_ratio
    if (
        up_ratio is None
        or up_ratio > 0.25
        or factor.bear_force < factor.bull_force
        or factor.mom_5d is None
        or factor.mom_5d >= 0
    ):
        return False

    breakdown = float(factor.evidence.get("trend_breakdown") or 0.0)
    trend_failure = not factor.close_above_ma20 and breakdown >= 60.0
    shock = False
    if index >= 21:
        prior_volatility = pstdev(returns[index - 20 : index])
        shock = (
            returns[index] <= -1.5
            and returns[index] <= -2.0 * prior_volatility
        )
    return trend_failure or shock


def build_volatility_hysteresis_directions(
    factors: list[MarketTimingFactors],
    series: list[CompositeBar],
    events: list[TimingSignal],
) -> list[str]:
    """构造研究用波动迟滞状态，不修改生产事件。"""
    if len(factors) != len(series):
        raise ValueError("factors 与 series 长度必须一致")
    if any(
        factor.trade_date != bar.trade_date
        for factor, bar in zip(factors, series, strict=True)
    ):
        raise ValueError("factors 与 series 日期必须对齐")

    confirmed_by_date = {
        event.confirm_date: event.direction
        for event in events
        if event.status == STATUS_CONFIRMED
        and event.confirm_date is not None
    }
    returns = [0.0]
    for index in range(1, len(series)):
        previous_close = series[index - 1].close
        current_close = series[index].close
        returns.append(
            (current_close / previous_close - 1.0) * 100.0
            if previous_close > 0
            else 0.0
        )

    active = "NEUTRAL"
    directions: list[str] = []
    for index, (factor, bar) in enumerate(zip(factors, series, strict=True)):
        confirmed = confirmed_by_date.get(bar.trade_date)
        if confirmed in {"GOLD", "SILVER"}:
            active = confirmed
        if (
            active == "GOLD"
            and _should_enter_volatility_hysteresis_silver(
                factor,
                series,
                returns,
                index,
            )
        ):
            active = "SILVER"
        directions.append(active)
    return directions


def _recovery_grade(bull_force: float) -> str:
    if bull_force >= 72.0:
        return "STRONG"
    if bull_force >= 66.0:
        return "MEDIUM"
    return "WEAK"


def _matches_recovery_gold(
    variant: str,
    factor: MarketTimingFactors,
    series: list[CompositeBar],
    index: int,
) -> bool:
    up_ratio = series[index].up_ratio
    if up_ratio is None or up_ratio < RECOVERY_UP_RATIO_MIN:
        return False

    closes = [bar.close for bar in series[: index + 1]]
    above_ma5 = (
        len(closes) >= 5
        and closes[-1] > sum(closes[-5:]) / 5.0
    )
    if variant == RECOVERY_R1_REPAIR:
        return above_ma5 and factor.bear_force < RECOVERY_BEAR_MAX

    broad_bull_cross = (
        factor.mom_5d is not None
        and factor.mom_5d > 0
        and factor.bull_force >= factor.bear_force
    )
    if variant == RECOVERY_R2_BULL_CROSS:
        return above_ma5 and broad_bull_cross
    return factor.close_above_ma20 and broad_bull_cross


def _recovery_gold_confirmed(
    factors: list[MarketTimingFactors],
    series: list[CompositeBar],
    candidate_index: int,
) -> bool:
    confirm_index = candidate_index + 1
    if confirm_index >= len(series):
        return False
    up_ratio = series[confirm_index].up_ratio
    factor = factors[confirm_index]
    return bool(
        series[confirm_index].close > series[candidate_index].close
        and up_ratio is not None
        and up_ratio >= RECOVERY_UP_RATIO_MIN
        and factor.bull_force >= factor.bear_force
    )


def build_recovery_gold_state(
    factors: list[MarketTimingFactors],
    series: list[CompositeBar],
    base_events: list[TimingSignal],
    *,
    variant: str,
) -> dict:
    """构造研究用银转金状态；基础 v9 事件始终优先。"""
    if variant not in RECOVERY_VARIANTS:
        raise ValueError(f"unknown recovery variant: {variant}")
    if len(factors) != len(series):
        raise ValueError("factors 与 series 长度必须一致")
    if any(
        factor.trade_date != bar.trade_date
        for factor, bar in zip(factors, series, strict=True)
    ):
        raise ValueError("factors 与 series 日期必须对齐")

    base_by_confirm: dict[date, str] = {}
    for event in base_events:
        if (
            event.status != STATUS_CONFIRMED
            or event.confirm_date is None
            or event.direction not in {"GOLD", "SILVER"}
        ):
            continue
        current = base_by_confirm.get(event.confirm_date)
        if current != "SILVER" or event.direction == "SILVER":
            base_by_confirm[event.confirm_date] = event.direction

    recovery_by_confirm: dict[date, bool] = {}
    recovery_events: list[TimingSignal] = []
    directions: list[str] = []
    active = "NEUTRAL"
    recovery_zone = False

    for index, (factor, bar) in enumerate(zip(factors, series, strict=True)):
        base_direction = base_by_confirm.get(bar.trade_date)
        if base_direction is not None:
            active = base_direction
        elif recovery_by_confirm.get(bar.trade_date):
            active = "GOLD"

        if base_direction is not None:
            recovery_zone = False
            directions.append(active)
            continue

        matches = active == "SILVER" and _matches_recovery_gold(
            variant,
            factor,
            series,
            index,
        )
        entered = matches and not recovery_zone
        recovery_zone = matches if active == "SILVER" else False
        if entered:
            confirm_index = index + 1
            if confirm_index >= len(series):
                status = STATUS_PENDING
                confirm_date = None
            else:
                confirm_date = series[confirm_index].trade_date
                blocked = confirm_date in base_by_confirm
                confirmed = (
                    not blocked
                    and _recovery_gold_confirmed(
                        factors,
                        series,
                        index,
                    )
                )
                status = (
                    STATUS_CONFIRMED
                    if confirmed
                    else STATUS_INVALIDATED
                )
                if confirmed:
                    recovery_by_confirm[confirm_date] = True
            recovery_events.append(
                TimingSignal(
                    trade_date=bar.trade_date,
                    direction="GOLD",
                    status=status,
                    grade=_recovery_grade(factor.bull_force),
                    bull_force=factor.bull_force,
                    bear_force=factor.bear_force,
                    phase=factor.phase,
                    setup_type=SETUP_RECOVERY_GOLD,
                    confirm_date=confirm_date,
                    reasons=[
                        f"variant={variant}",
                        f"up_ratio={bar.up_ratio:.2f}",
                        f"bull={factor.bull_force:.1f}",
                        f"bear={factor.bear_force:.1f}",
                        status,
                    ],
                )
            )
        directions.append(active)

    return {
        "directions": directions,
        "events": recovery_events,
    }


def evaluate_recovery_gold_runs(
    base_directions: list[str],
    recovery_events: list[TimingSignal],
    series: list[CompositeBar],
) -> list[dict]:
    """按基础 v9 银区间判断恢复确认是否真正避开后续反弹。"""
    if len(base_directions) != len(series):
        raise ValueError("base_directions 与 series 长度必须一致")

    index_by_date = {
        bar.trade_date: index
        for index, bar in enumerate(series)
    }
    confirmed_dates = sorted(
        event.confirm_date
        for event in recovery_events
        if event.status == STATUS_CONFIRMED
        and event.confirm_date is not None
    )
    rows: list[dict] = []
    for direction, start, end in _direction_run_ranges(base_directions):
        if direction != "SILVER":
            continue
        start_date = series[start].trade_date
        end_date = series[end].trade_date
        recovery_date = next(
            (
                value
                for value in confirmed_dates
                if start_date <= value <= end_date
            ),
            None,
        )
        recovery_index = index_by_date.get(recovery_date)
        if recovery_index is None:
            outcome = "NO_RECOVERY"
            return_5d = None
            advanced_days = 0
        elif recovery_index + 5 >= len(series):
            outcome = "IMMATURE"
            return_5d = None
            advanced_days = end - recovery_index + 1
        else:
            return_5d = (
                series[recovery_index + 5].close
                / series[recovery_index].close
                - 1.0
            ) * 100.0
            outcome = (
                "IMPROVED"
                if return_5d > 0
                else "FALSE_RECOVERY"
            )
            advanced_days = end - recovery_index + 1
        rows.append(
            {
                "run_start": start_date,
                "run_end": end_date,
                "open_run": end == len(series) - 1,
                "recovery_confirm_date": recovery_date,
                "advanced_days": advanced_days,
                "return_5d": return_5d,
                "outcome": outcome,
            }
        )
    return rows


def _silver_five_day_bucket(report: dict) -> StateBucketStat | None:
    return next(
        (
            item
            for item in report["buckets"]
            if item.period == "ALL"
            and item.direction == "SILVER"
            and item.horizon == 5
        ),
        None,
    )


def evaluate_silver_run_leave_one_out(
    base_directions: list[str],
    candidate_directions: list[str],
    series: list[CompositeBar],
) -> list[dict]:
    """逐个删除基础银区间，检查整体改善是否依赖单一区间。"""
    if (
        len(base_directions) != len(series)
        or len(candidate_directions) != len(series)
    ):
        raise ValueError("方向序列与 series 长度必须一致")
    if not series:
        return []

    rows: list[dict] = []
    for direction, start, end in _direction_run_ranges(base_directions):
        if direction != "SILVER":
            continue
        omitted = set(range(start, end + 1))
        base_filtered = [
            "NEUTRAL" if index in omitted else value
            for index, value in enumerate(base_directions)
        ]
        candidate_filtered = [
            "NEUTRAL" if index in omitted else value
            for index, value in enumerate(candidate_directions)
        ]
        base_bucket = _silver_five_day_bucket(
            evaluate_direction_states(
                base_filtered,
                series,
                split_date=series[0].trade_date,
            )
        )
        candidate_bucket = _silver_five_day_bucket(
            evaluate_direction_states(
                candidate_filtered,
                series,
                split_date=series[0].trade_date,
            )
        )
        row: dict[str, object] = {
            "omitted_start": series[start].trade_date,
            "omitted_end": series[end].trade_date,
        }
        for name, bucket in (
            ("base", base_bucket),
            ("candidate", candidate_bucket),
        ):
            row[f"{name}_count"] = bucket.count if bucket else 0
            row[f"{name}_hit_rate"] = bucket.hit_rate if bucket else None
            row[f"{name}_avg_return"] = bucket.avg_return if bucket else None
            row[f"{name}_adverse_3pct_rate"] = (
                bucket.adverse_3pct_rate
                if bucket
                else None
            )
        rows.append(row)
    return rows
