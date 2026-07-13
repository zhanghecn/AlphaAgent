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
from typing import Literal

from alphaagent.server.services.quant.market_timing.series import CompositeBar
from alphaagent.server.services.quant.market_timing.signal import (
    STATUS_CONFIRMED,
    STATUS_INVALIDATED,
    STATUS_PENDING,
    TimingSignal,
)

HORIZONS = (5, 10, 20)
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
