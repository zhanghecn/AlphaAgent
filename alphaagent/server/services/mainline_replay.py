"""Mainline replay pure-function algorithms.

No DB / IO dependencies — accept already-queried data, return computed
results. This keeps the delta + relation logic unit-testable with fixed
fixtures (TDD) and lets the API layer stay a thin wrapper.

设计文档：docs/superpowers/specs/2026-06-28-mainline-replay-design.md
"""

from __future__ import annotations

import math
from typing import Any

# fund_strength 各维度权重（和为 1.0）。设计文档 4.1-D。
_FUND_STRENGTH_WEIGHTS = {
    "return_pct": 0.30,
    "volume_ratio": 0.30,
    "delta_fund": 0.25,
    "delta_heat": 0.15,
}

# 关联度各维度权重（设计文档 4.2）。corr=涨跌共振(主)，fund_corr=资金共振，overlap=成分重叠。
_RELATION_WEIGHTS = {"corr": 0.55, "fund_corr": 0.25, "overlap": 0.20}


# ── 区间 delta 计算（设计文档 4.1） ──


def compute_raw_sector_delta(
    *,
    bars_t1_close: float | None,
    bars_t2_close: float | None,
    range_turnover: list[float],
    prev_range_turnover: list[float],
    score_t1: dict[str, Any] | None,
    score_t2: dict[str, Any] | None,
    range_main_inflow: list[float] | None,
) -> dict[str, Any]:
    """Compute raw (pre-normalization) delta metrics for one sector over [T1, T2].

    All inputs are already-queried scalars/lists; this function does no IO.
    None inputs propagate to None outputs (caller may render "n/a").
    """
    # 行情维度（sector_daily_bars）
    return_pct: float | None = None
    if bars_t1_close and bars_t2_close and bars_t1_close != 0:
        return_pct = bars_t2_close / bars_t1_close - 1.0

    accumulated_turnover: float | None = sum(range_turnover) if range_turnover else None

    volume_ratio: float | None = None
    if range_turnover and prev_range_turnover:
        avg_prev = sum(prev_range_turnover) / len(prev_range_turnover)
        avg_curr = sum(range_turnover) / len(range_turnover)
        if avg_prev != 0:
            volume_ratio = avg_curr / avg_prev

    # 热度维度（sector_period_scores）
    delta_heat = _safe_delta(score_t2, score_t1, "heat_score")
    delta_fund = _safe_delta(score_t2, score_t1, "fund_score")

    trend_transition: str | None = None
    if score_t1 and score_t2:
        s1 = score_t1.get("trend_state")
        s2 = score_t2.get("trend_state")
        if s1 and s2:
            trend_transition = f"{s1}->{s2}"

    rank_change: int | None = None
    r1 = score_t1.get("rank_return") if score_t1 else None
    r2 = score_t2.get("rank_return") if score_t2 else None
    if r1 is not None and r2 is not None:
        rank_change = r2 - r1

    # 资金流维度（sector_fund_flows，仅近端）
    accumulated_main_inflow: float | None = None
    fund_inflow_available = bool(range_main_inflow)
    if fund_inflow_available:
        accumulated_main_inflow = sum(range_main_inflow)  # type: ignore[arg-type]

    return {
        "return_pct": return_pct,
        "accumulated_turnover": accumulated_turnover,
        "volume_ratio": volume_ratio,
        "delta_heat": delta_heat,
        "delta_fund": delta_fund,
        "trend_transition": trend_transition,
        "rank_change": rank_change,
        "accumulated_main_inflow": accumulated_main_inflow,
        "fund_inflow_available": fund_inflow_available,
    }


def _safe_delta(s2: dict | None, s1: dict | None, key: str) -> float | None:
    v1 = s1.get(key) if s1 else None
    v2 = s2.get(key) if s2 else None
    if v1 is None or v2 is None:
        return None
    return v2 - v1


def minmax_normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. Empty -> []. All-equal -> 0.5 (mid, keeps ordering sane)."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def compute_fund_strength_batch(raws: list[dict[str, Any]]) -> list[float | None]:
    """综合资金强弱 fund_strength for a batch of raw deltas.

    归一化在每个维度上对全批做 min-max，再按权重加权。
    任一维度缺失的板块返回 None（前端标注"数据不足"）。
    """
    keys = list(_FUND_STRENGTH_WEIGHTS.keys())
    normed: dict[str, list[float | None]] = {k: [None] * len(raws) for k in keys}
    for k in keys:
        col = [r.get(k) for r in raws]
        idxs = [i for i, v in enumerate(col) if v is not None]
        if not idxs:
            continue
        nn = [col[i] for i in idxs]  # type: ignore[index]
        for j, nv in enumerate(minmax_normalize(nn)):
            normed[k][idxs[j]] = nv

    out: list[float | None] = []
    for i in range(len(raws)):
        parts = [normed[k][i] for k in keys]
        if any(p is None for p in parts):
            out.append(None)
            continue
        s = sum(_FUND_STRENGTH_WEIGHTS[k] * normed[k][i] for k in keys)  # type: ignore[index]
        out.append(round(s, 4))
    return out


# ── 关联反推（设计文档 4.2） ──


def pearson(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation. Returns None if <3 pairs or zero variance."""
    n = min(len(x), len(y))
    if n < 3:
        return None
    xs, ys = x[:n], y[:n]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def _norm_corr(c: float | None) -> float:
    # 把 [-1,1] 的相关系数映射到 [0,1]（-1→0, 0→0.5, 1→1）。None→0.5 中性。
    if c is None:
        return 0.5
    return (c + 1.0) / 2.0


def _score_relation(
    corr: float | None,
    fund_corr: float | None,
    overlap: float,
    overlap_count: int,
    weights: dict[str, float],
    *,
    common_points: int,
    shared_symbols: list[str],
    relation_group: str,
) -> dict[str, Any]:
    """单候选关联打分（纯函数，被 compute_relations_aligned 共享）。"""
    score = (
        weights["corr"] * _norm_corr(corr)
        + weights["fund_corr"] * _norm_corr(fund_corr)
        + weights["overlap"] * overlap
    )
    reason_parts = [f"共振{corr:.2f}" if corr is not None else "共振n/a"]
    if fund_corr is not None:
        reason_parts.append(f"资金{fund_corr:.2f}")
    if overlap_count:
        reason_parts.append(f"重叠{overlap_count}股")
    if not overlap_count:
        reason_parts.append("无成分重叠")
    return {
        "relation_score": round(score, 4),
        "corr": round(corr, 4) if corr is not None else None,
        "fund_corr": round(fund_corr, 4) if fund_corr is not None else None,
        "overlap": round(overlap, 4),
        "overlap_count": overlap_count,
        "common_points": common_points,
        "relation_group": relation_group,
        "evidence": {
            "common_points": common_points,
            "shared_stock_count": overlap_count,
            "shared_symbols": shared_symbols[:10],
            "jaccard": round(overlap, 4),
            "price_correlation": round(corr, 4) if corr is not None else None,
            "fund_correlation": round(fund_corr, 4) if fund_corr is not None else None,
        },
        "reason": " · ".join(reason_parts),
    }


def compute_relations_aligned(
    *,
    target_map: dict[Any, float],
    candidate_maps: dict[str, dict[Any, float]],
    target_fund_map: dict[Any, float] | None = None,
    candidate_fund_maps: dict[str, dict[Any, float]] | None = None,
    target_members: set[str],
    candidate_members: dict[str, set[str]],
    relation_groups: dict[str, str] | None = None,
    target_relation_group: str = "theme",
    min_points: int = 3,
    weights: dict[str, float] | None = None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """关联反推（按共同日期自动对齐）。

    与 compute_relations 的区别：输入是 {date: value} 字典而非等长 list，
    每个候选按"与目标的共同日期"对齐（只需 ≥ min_points 个共同点），
    避免严格要求候选在所有日期都有值而过滤掉大量候选。
    """
    w = weights or _RELATION_WEIGHTS
    tgt_dates_sorted = sorted(target_map.keys())
    results: list[dict[str, Any]] = []
    for cid, cmap in candidate_maps.items():
        common = [d for d in tgt_dates_sorted if d in cmap and cmap[d] is not None]
        if len(common) < min_points:
            continue
        corr = pearson([target_map[d] for d in common], [cmap[d] for d in common])

        fund_corr: float | None = None
        if target_fund_map and candidate_fund_maps and cid in candidate_fund_maps:
            fmap = candidate_fund_maps[cid]
            fcommon = [
                d for d in common
                if d in fmap and fmap[d] is not None
                and d in target_fund_map and target_fund_map[d] is not None
            ]
            if len(fcommon) >= 3:
                fund_corr = pearson(
                    [target_fund_map[d] for d in fcommon],
                    [fmap[d] for d in fcommon],
                )

        cmembers = candidate_members.get(cid, set())
        shared = target_members & cmembers
        union = target_members | cmembers
        overlap = (len(shared) / len(union)) if union else 0.0
        overlap_count = len(shared)
        relation_group = (relation_groups or {}).get(cid, "theme")
        scored = _score_relation(
            corr,
            fund_corr,
            overlap,
            overlap_count,
            w,
            common_points=len(common),
            shared_symbols=sorted(str(s) for s in shared),
            relation_group=relation_group,
        )
        scored["sector_id"] = cid
        results.append(scored)
    if target_relation_group == "style_status":
        group_rank = {"style_status": 0, "theme": 1, "industry": 1, "region": 2}
    else:
        group_rank = {"industry": 0, "theme": 0, "region": 1, "style_status": 2}
    results.sort(
        key=lambda r: (
            group_rank.get(str(r.get("relation_group") or "theme"), 1),
            -float(r["relation_score"]),
            str(r["sector_id"]),
        )
    )
    return results[:top_n]
