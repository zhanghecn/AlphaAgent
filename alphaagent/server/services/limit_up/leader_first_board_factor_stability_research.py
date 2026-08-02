"""潜龙首板因子时间稳定性门（Phase 0）：holdout/月度方向/阈值/共线性/双目标。

动机：morning-window 研究已证明 D-1 因子月度方向可全部翻转、holdout 未锁定
的因子不得加权重。本脚本对 wave 口径深度因子（见
``leader_first_board_deep_factor_research``）做上线前稳定性裁决：

1. **时间 holdout**：按月排序，最后 ``HOLDOUT_TEST_MONTHS`` 个月为 test，其余为
   train；因子须在 train/test 方向一致且 test |AUC-0.5| 达标。
2. **逐月方向稳定性**：逐月 AUC/方向，与全样本方向一致的月份占比须达标。
3. **阈值稳定性**：分位阈值用 train 期定义，test 期验证分桶成龙率单调性。
4. **滞后温度重测**：``market_first_board_count_d`` 全日口径盘中不可知（未来
   函数），改用 D-1 滞后/近 5 日均值口径重测 AUC——量化全日口径的虚高幅度。
5. **共线性族**：Spearman 相关矩阵，识别「强者恒强」「市场温度」等高度同源的
   因子族，给出族代表与权重上限建议。
6. **双目标一致性**：排序目标是成龙率，赚钱靠 D+1——因子对两个标签的 AUC
   方向须一致（温度因子例外，仅作风控门）。
7. **L3 组合 holdout**：先验组合在 train/test 分别验证是否仍超基线。

白名单裁决规则（确定性，见 ``evaluate_whitelist``）：holdout 方向一致
且 test |AUC-0.5|>=0.05 且逐月一致性>=0.7 且双目标一致（风控门因子豁免）。

研究脚本只读 PostgreSQL，只写 ``memory/06_backtests`` 证据文件，绝不触碰
实时表、API、portfolio 或 ``actionable_recommendations``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    _auc,
    _auc_direction,
)
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    DAILY_FORWARD_DAYS,
    DAILY_LOOKBACK_DAYS,
    DEFAULT_BOARD_GAP_MODE,
    DEFAULT_MIN_CONSECUTIVE_BOARDS,
    SECTOR_LOOKBACK_DAYS,
    _bool,
    _number,
    _sample_float,
    build_factor_samples,
    evaluate_combos,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_limit_up_dataset,
    load_sector_daily_bars,
    load_sector_memberships_all,
)

STUDY_VERSION = "leader-first-board-factor-stability-v1"
HOLDOUT_TEST_MONTHS = 3
MIN_MONTH_SAMPLES = 60
MIN_MONTH_POSITIVES = 5
MONTHLY_AGREEMENT_MIN = 0.7
HOLDOUT_EFFECT_MIN = 0.05  # test |AUC-0.5| 达标线（即 AUC>=0.55 或 <=0.45）
THRESHOLD_MONOTONE_MIN = 0.8  # test 分桶成龙率与分位序的 Spearman 达标线

# 进稳定性门的候选因子（L2 打分候选 + 备选 + 滞后温度变体）
GATE_FACTOR_KEYS = (
    "drawdown_from_126d_high_pct",
    "return_20d_pct",
    "position_126d",
    "prior_4_10d_up_days",
    "volume_ratio_5_60",
    "concept_max_return_20d",
    "turnover_ratio_3d_vs_prev7d",
    "float_market_cap",
    "prior_10d_amplitude_pct",
    "prior_return_5d_pct",
    "return_60d_pct",
    "market_first_board_count_d_lag1",
    "market_first_board_count_ma5",
    "market_sealed_count_d_lag1",
    "market_sealed_count_ma5",
)

# 全日口径温度（含未来信息，仅用于量化虚高幅度，绝不进白名单）
LOOKAHEAD_REFERENCE_KEYS = ("market_first_board_count_d", "market_sealed_count_d")

# 风控门角色（豁免双目标一致）：温度只用于高潮日停手/冷日加权，不做 D+1 加分
RISK_GATE_KEYS = (
    "market_first_board_count_d_lag1",
    "market_first_board_count_ma5",
    "market_sealed_count_d_lag1",
    "market_sealed_count_ma5",
)

# 共线性矩阵因子集（族识别）
COLLINEARITY_KEYS = (
    "drawdown_from_126d_high_pct",
    "return_20d_pct",
    "position_126d",
    "return_60d_pct",
    "return_126d_pct",
    "rebound_from_126d_low_pct",
    "market_first_board_count_d_lag1",
    "market_sealed_count_d_lag1",
    "concept_max_return_20d",
    "volume_ratio_5_60",
    "turnover_ratio_3d_vs_prev7d",
    "prior_4_10d_up_days",
    "float_market_cap",
)
CLAN_CORR_MIN = 0.7  # |rho| 超过即判同族

# 先验族定义（用于代表与权重上限建议；同族判定仍以相关矩阵为准）
STRENGTH_CLAN = (
    "drawdown_from_126d_high_pct",
    "return_20d_pct",
    "position_126d",
    "return_60d_pct",
    "return_126d_pct",
    "rebound_from_126d_low_pct",
)
TEMPERATURE_CLAN = (
    "market_first_board_count_d_lag1",
    "market_first_board_count_ma5",
    "market_sealed_count_d_lag1",
    "market_sealed_count_ma5",
)

LAGGED_TEMPERATURE_KEYS = (
    "market_first_board_count_d_lag1",
    "market_first_board_count_ma5",
    "market_sealed_count_d_lag1",
    "market_sealed_count_ma5",
)


# ── 滞后温度（盘前可知，无未来函数）──────────────────────────────────────


def attach_lagged_temperature(
    factor_samples: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """给每个样本挂 D-1 滞后/近 5 日均值口径的市场温度（返回新列表）。"""

    first_board_by_date: dict[str, int] = defaultdict(int)
    for sample in factor_samples:
        first_board_by_date[str(sample.get("trade_date") or "")] += 1
    sealed_by_date: dict[str, int] = defaultdict(int)
    for event in events:
        if _bool(event.get("is_sealed")):
            sealed_by_date[str(event.get("trade_date") or "")] += 1
    dates = sorted(set(first_board_by_date) | set(sealed_by_date))
    day_number = {value: index for index, value in enumerate(dates)}

    enriched: list[dict[str, object]] = []
    for sample in factor_samples:
        trade_date = str(sample.get("trade_date") or "")
        index = day_number.get(trade_date)
        row = dict(sample)
        lag1_first = lag1_sealed = ma5_first = ma5_sealed = None
        if index is not None and index >= 1:
            prev_date = dates[index - 1]
            lag1_first = first_board_by_date.get(prev_date, 0)
            lag1_sealed = sealed_by_date.get(prev_date, 0)
        if index is not None and index >= 5:
            window = dates[index - 5 : index]
            ma5_first = round(mean(first_board_by_date.get(one, 0) for one in window), 4)
            ma5_sealed = round(mean(sealed_by_date.get(one, 0) for one in window), 4)
        row["market_first_board_count_d_lag1"] = lag1_first
        row["market_sealed_count_d_lag1"] = lag1_sealed
        row["market_first_board_count_ma5"] = ma5_first
        row["market_sealed_count_ma5"] = ma5_sealed
        enriched.append(row)
    return enriched


# ── 月度切分 / holdout ─────────────────────────────────────────────────


def _month_of(sample: Mapping[str, object]) -> str:
    return str(sample.get("trade_date") or "")[:7]


def split_holdout_months(
    factor_samples: Sequence[Mapping[str, object]],
    *,
    test_months: int = HOLDOUT_TEST_MONTHS,
) -> tuple[list[str], list[str]]:
    """按月排序切 train/test（test = 最后 ``test_months`` 个月）。"""

    months = sorted({_month_of(sample) for sample in factor_samples if _month_of(sample)})
    if len(months) <= test_months:
        return months, []
    return months[:-test_months], months[-test_months:]


def monthly_factor_stability(
    factor_samples: Sequence[Mapping[str, object]],
    factor_key: str,
    *,
    min_samples: int = MIN_MONTH_SAMPLES,
    min_positives: int = MIN_MONTH_POSITIVES,
) -> dict[str, object]:
    """逐月 AUC/方向，与全样本方向的一致率。"""

    full_pos, full_neg = _label_values(factor_samples, factor_key, "is_leader")
    full_auc = _auc(full_pos, full_neg)
    full_direction = _auc_direction(full_auc)
    by_month: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for sample in factor_samples:
        by_month[_month_of(sample)].append(sample)
    months: list[dict[str, object]] = []
    agree = 0
    valid = 0
    for month in sorted(by_month):
        members = by_month[month]
        pos, neg = _label_values(members, factor_key, "is_leader")
        total = len(pos) + len(neg)
        if total < min_samples or len(pos) < min_positives:
            months.append(
                {"month": month, "total": total, "positive": len(pos), "auc": None, "direction": "skip"}
            )
            continue
        auc = _auc(pos, neg)
        direction = _auc_direction(auc)
        valid += 1
        if direction == full_direction:
            agree += 1
        months.append(
            {
                "month": month,
                "total": total,
                "positive": len(pos),
                "auc": round(auc, 4) if auc is not None else None,
                "direction": direction,
            }
        )
    return {
        "factor_key": factor_key,
        "full_auc": round(full_auc, 4) if full_auc is not None else None,
        "full_direction": full_direction,
        "valid_months": valid,
        "agree_months": agree,
        "monthly_agreement": round(agree / valid, 4) if valid else None,
        "months": months,
    }


def _label_values(
    samples: Sequence[Mapping[str, object]],
    factor_key: str,
    label_key: str,
) -> tuple[list[float], list[float]]:
    pos: list[float] = []
    neg: list[float] = []
    for sample in samples:
        value = _sample_float(sample.get(factor_key))
        if value is None:
            continue
        if label_key == "d1_win":
            d1 = _number(sample.get("d1_open_return_pct"))
            if d1 is None:
                continue
            (pos if d1 > 0 else neg).append(value)
        elif _bool(sample.get(label_key)):
            pos.append(value)
        else:
            neg.append(value)
    return pos, neg


# ── 阈值稳定性（train 分位定阈值 → test 分桶单调性）─────────────────────


def _percentile(sorted_values: Sequence[float], q: float) -> float | None:
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[index]


def threshold_stability(
    train_samples: Sequence[Mapping[str, object]],
    test_samples: Sequence[Mapping[str, object]],
    factor_key: str,
    *,
    buckets: int = 5,
) -> dict[str, object]:
    """train 期分位阈值 → test 期分桶成龙率 + 单调性 Spearman。"""

    train_values = sorted(
        value
        for value in (_sample_float(sample.get(factor_key)) for sample in train_samples)
        if value is not None
    )
    boundaries = [
        _percentile(train_values, index / buckets) for index in range(1, buckets)
    ]
    if any(boundary is None for boundary in boundaries):
        return {"factor_key": factor_key, "boundaries": [], "test_buckets": [], "spearman": None}
    bucket_members: list[list[Mapping[str, object]]] = [[] for _ in range(buckets)]
    for sample in test_samples:
        value = _sample_float(sample.get(factor_key))
        if value is None:
            continue
        bucket = sum(1 for boundary in boundaries if value > float(boundary))
        bucket_members[min(bucket, buckets - 1)].append(sample)
    rows: list[dict[str, object]] = []
    for index, members in enumerate(bucket_members):
        leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
        d1_returns = [
            value
            for value in (_number(sample.get("d1_open_return_pct")) for sample in members)
            if value is not None
        ]
        rows.append(
            {
                "bucket": index + 1,
                "total": len(members),
                "leader_rate": round(leaders / len(members), 4) if members else None,
                "d1_open_return_mean": round(mean(d1_returns), 4) if d1_returns else None,
            }
        )
    rates = [(index + 1, row["leader_rate"]) for index, row in enumerate(rows) if row["leader_rate"] is not None]
    spearman = _spearman_pairs([one for one, _ in rates], [rate for _, rate in rates])
    return {
        "factor_key": factor_key,
        "boundaries": [round(float(boundary), 4) for boundary in boundaries if boundary is not None],
        "test_buckets": rows,
        "spearman": round(spearman, 4) if spearman is not None else None,
    }


# ── 共线性（Spearman 秩相关，纯 Python）─────────────────────────────────


def _ranks(values: Sequence[float]) -> list[float]:
    """平均秩（ ties 取均值，1-based）。"""

    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor
        while end + 1 < len(order) and values[order[end + 1]] == values[order[cursor]]:
            end += 1
        average = (cursor + end) / 2 + 1
        for position in range(cursor, end + 1):
            ranks[order[position]] = average
        cursor = end + 1
    return ranks


def _spearman_pairs(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    rank_x = _ranks(list(xs))
    rank_y = _ranks(list(ys))
    mean_x = mean(rank_x)
    mean_y = mean(rank_y)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(rank_x, rank_y, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in rank_x)
    var_y = sum((y - mean_y) ** 2 for y in rank_y)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / (var_x**0.5 * var_y**0.5)


def collinearity_matrix(
    factor_samples: Sequence[Mapping[str, object]],
    factor_keys: Sequence[str],
) -> list[dict[str, object]]:
    """两两 Spearman 秩相关（|rho|>=CLAN_CORR_MIN 标记同族）。"""

    pairs: list[dict[str, object]] = []
    for left_index, left in enumerate(factor_keys):
        for right in factor_keys[left_index + 1 :]:
            xs: list[float] = []
            ys: list[float] = []
            for sample in factor_samples:
                left_value = _sample_float(sample.get(left))
                right_value = _sample_float(sample.get(right))
                if left_value is None or right_value is None:
                    continue
                xs.append(left_value)
                ys.append(right_value)
            rho = _spearman_pairs(xs, ys)
            if rho is None:
                continue
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "sample_count": len(xs),
                    "spearman": round(rho, 4),
                    "same_clan": abs(rho) >= CLAN_CORR_MIN,
                }
            )
    pairs.sort(key=lambda item: abs(item["spearman"]), reverse=True)
    return pairs


# ── 白名单裁决 ─────────────────────────────────────────────────────────


def evaluate_whitelist(
    gate_reports: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    """按确定性规则裁决白名单（风控门因子豁免双目标一致）。"""

    decisions: list[dict[str, object]] = []
    for factor_key, report in gate_reports.items():
        holdout = report.get("holdout") or {}
        monthly = report.get("monthly") or {}
        dual = report.get("dual_target") or {}
        reasons: list[str] = []
        if not holdout.get("direction_consistent"):
            reasons.append("holdout方向不一致")
        test_auc = holdout.get("test_auc")
        test_direction = holdout.get("test_direction")
        effect_ok = (
            test_auc is not None
            and test_direction in ("higher", "lower")
            and abs(float(test_auc) - 0.5) >= HOLDOUT_EFFECT_MIN
        )
        if not effect_ok:
            reasons.append(f"test AUC 未达标({_fmt(test_auc)})")
        agreement = monthly.get("monthly_agreement")
        if agreement is None or float(agreement) < MONTHLY_AGREEMENT_MIN:
            reasons.append(f"逐月一致性不足({_fmt(agreement)})")
        is_risk_gate = factor_key in RISK_GATE_KEYS
        if not is_risk_gate and not dual.get("direction_consistent"):
            reasons.append("双目标方向不一致")
        passed = not reasons
        decisions.append(
            {
                "factor_key": factor_key,
                "role": "risk_gate" if is_risk_gate else "scoring",
                "passed": passed,
                "direction": holdout.get("train_direction"),
                "test_auc": test_auc,
                "monthly_agreement": agreement,
                "dual_target_consistent": dual.get("direction_consistent"),
                "reject_reasons": reasons,
            }
        )
    decisions.sort(key=lambda item: (not item["passed"], item["factor_key"]))
    return decisions


def suggest_clan_weights(
    decisions: Sequence[Mapping[str, object]],
    collinearity: Sequence[Mapping[str, object]],
    holdout_by_key: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    """族代表与权重上限建议：同族只取 test 效应最强者为代表，族合计权重设上限。"""

    passed = {str(item.get("factor_key")) for item in decisions if item.get("passed")}
    clans: list[dict[str, object]] = []
    for clan_name, members in (
        ("strength", STRENGTH_CLAN),
        ("temperature", TEMPERATURE_CLAN),
    ):
        clan_passed = [key for key in members if key in passed]
        representative = max(
            clan_passed,
            key=lambda key: abs(
                float((holdout_by_key.get(key) or {}).get("test_auc") or 0.5) - 0.5
            ),
            default=None,
        )
        strong_pairs = [
            f"{item['left']}×{item['right']} rho={item['spearman']}"
            for item in collinearity
            if item.get("same_clan") and (item["left"] in members or item["right"] in members)
        ]
        clans.append(
            {
                "clan": clan_name,
                "members": list(members),
                "passed_members": clan_passed,
                "representative": representative,
                "weight_cap": 0.4 if clan_passed else 0.0,
                "single_factor_cap": 0.25,
                "strong_pairs": strong_pairs[:6],
            }
        )
    return clans


# ── 报告编排 ───────────────────────────────────────────────────────────


def build_stability_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    memberships: Sequence[Mapping[str, object]],
    sector_bars: Sequence[Mapping[str, object]],
    *,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
    board_gap_mode: str = DEFAULT_BOARD_GAP_MODE,
    test_months: int = HOLDOUT_TEST_MONTHS,
) -> dict[str, object]:
    """编排 Phase 0 稳定性门（纯函数，不连数据库）。"""

    _, factor_samples = build_factor_samples(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )
    factor_samples = attach_lagged_temperature(factor_samples, events)

    train_months, test_months_list = split_holdout_months(
        factor_samples, test_months=test_months
    )
    test_set = set(test_months_list)
    train_samples = [sample for sample in factor_samples if _month_of(sample) not in test_set]
    test_samples = [sample for sample in factor_samples if _month_of(sample) in test_set]

    gate_reports: dict[str, dict[str, object]] = {}
    all_keys = (*GATE_FACTOR_KEYS, *LOOKAHEAD_REFERENCE_KEYS)
    for factor_key in all_keys:
        monthly = monthly_factor_stability(factor_samples, factor_key)
        train_pos, train_neg = _label_values(train_samples, factor_key, "is_leader")
        test_pos, test_neg = _label_values(test_samples, factor_key, "is_leader")
        train_auc = _auc(train_pos, train_neg)
        test_auc = _auc(test_pos, test_neg)
        train_direction = _auc_direction(train_auc)
        test_direction = _auc_direction(test_auc)
        d1_train_pos, d1_train_neg = _label_values(factor_samples, factor_key, "d1_win")
        d1_auc = _auc(d1_train_pos, d1_train_neg)
        leader_auc_full = monthly.get("full_auc")
        dual_consistent = (
            leader_auc_full is not None
            and d1_auc is not None
            and (float(leader_auc_full) - 0.5) * (d1_auc - 0.5) > 0
        )
        threshold = threshold_stability(train_samples, test_samples, factor_key)
        gate_reports[factor_key] = {
            "monthly": monthly,
            "holdout": {
                "train_auc": round(train_auc, 4) if train_auc is not None else None,
                "test_auc": round(test_auc, 4) if test_auc is not None else None,
                "train_direction": train_direction,
                "test_direction": test_direction,
                "direction_consistent": train_direction == test_direction,
                "train_samples": len(train_pos) + len(train_neg),
                "test_samples": len(test_pos) + len(test_neg),
            },
            "dual_target": {
                "leader_auc_full": leader_auc_full,
                "d1_win_auc_full": round(d1_auc, 4) if d1_auc is not None else None,
                "direction_consistent": dual_consistent,
            },
            "threshold": threshold,
        }

    collinearity = collinearity_matrix(factor_samples, COLLINEARITY_KEYS)
    gate_only = {key: gate_reports[key] for key in GATE_FACTOR_KEYS}
    decisions = evaluate_whitelist(gate_only)
    holdout_by_key = {key: report["holdout"] for key, report in gate_only.items()}
    clans = suggest_clan_weights(decisions, collinearity, holdout_by_key)

    combos_train = evaluate_combos(train_samples)
    combos_test = evaluate_combos(test_samples)

    lookahead_compare = [
        {
            "factor_key": key,
            "full_auc": (gate_reports[key]["monthly"] or {}).get("full_auc"),
            "test_auc": gate_reports[key]["holdout"].get("test_auc"),
        }
        for key in LOOKAHEAD_REFERENCE_KEYS
    ]
    lagged_compare = [
        {
            "factor_key": key,
            "full_auc": (gate_reports[key]["monthly"] or {}).get("full_auc"),
            "test_auc": gate_reports[key]["holdout"].get("test_auc"),
        }
        for key in LAGGED_TEMPERATURE_KEYS
    ]

    positive = sum(1 for sample in factor_samples if _bool(sample.get("is_leader")))
    return {
        "status": "ok" if factor_samples else "insufficient_data",
        "mode": "leader_first_board_factor_stability_gate",
        "execution_valid": False,
        "study_version": STUDY_VERSION,
        "min_consecutive_boards": min_consecutive_boards,
        "board_gap_mode": board_gap_mode,
        "first_board_count": len(factor_samples),
        "label_balance": {
            "positive": positive,
            "negative": len(factor_samples) - positive,
            "positive_rate": round(positive / len(factor_samples), 4) if factor_samples else None,
        },
        "holdout_months": {"train": train_months, "test": test_months_list},
        "holdout_samples": {"train": len(train_samples), "test": len(test_samples)},
        "gate_rules": {
            "holdout_effect_min": HOLDOUT_EFFECT_MIN,
            "monthly_agreement_min": MONTHLY_AGREEMENT_MIN,
            "threshold_monotone_min": THRESHOLD_MONOTONE_MIN,
            "risk_gate_keys": list(RISK_GATE_KEYS),
        },
        "whitelist": decisions,
        "clans": clans,
        "factor_reports": gate_reports,
        "collinearity": collinearity,
        "temperature_compare": {"lookahead": lookahead_compare, "lagged": lagged_compare},
        "combos_holdout": {"train": combos_train, "test": combos_test},
        "notes": [
            "eventual_peak / d1_* 是未来标签，仅用于对照分组，绝不作为可交易因子。",
            "全日口径温度（market_*_count_d）含未来信息，只用于量化虚高，不进白名单。",
            "滞后温度 = D-1 全日首板/封板数（盘前可知），ma5 = 近 5 个交易日均值。",
            "白名单裁决为确定性规则：holdout 方向一致 + test |AUC-0.5|>=0.05 "
            "+ 逐月一致性>=0.7 + 双目标一致（风控门豁免）。",
            "阈值稳定性的 spearman 为 test 期分桶成龙率与分位序的秩相关，"
            "方向为 lower 的因子期望显著负相关。",
        ],
    }


def run_research(
    *,
    start: date,
    end: date,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
    board_gap_mode: str = DEFAULT_BOARD_GAP_MODE,
) -> dict[str, object]:
    """Load frozen dataset and return the factor stability gate report."""

    dataset = load_limit_up_dataset(start, end)
    events = dataset["events"]
    daily_bars = load_daily_bars_all(
        start - timedelta(days=DAILY_LOOKBACK_DAYS),
        end + timedelta(days=DAILY_FORWARD_DAYS),
    )
    calendar = sorted(
        {str(bar.get("trade_date") or "") for bar in daily_bars if bar.get("trade_date")}
    )
    memberships = load_sector_memberships_all()
    sector_bars = load_sector_daily_bars(start - timedelta(days=SECTOR_LOOKBACK_DAYS), end)
    report = build_stability_report(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )
    coverage = dict(dataset.get("coverage") or {})
    coverage["trade_days_in_window"] = len(calendar)
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["coverage"] = coverage
    report["input_fingerprint"] = hashlib.sha256(
        f"{STUDY_VERSION}|{len(events)}|{len(daily_bars)}|{report['first_board_count']}".encode()
    ).hexdigest()[:16]
    return report


# ── Markdown 渲染 ──────────────────────────────────────────────────────


def render_markdown(result: Mapping[str, object]) -> str:
    """Render the Phase 0 stability gate evidence."""

    balance = _mapping(result.get("label_balance"))
    holdout_months = _mapping(result.get("holdout_months"))
    rules = _mapping(result.get("gate_rules"))
    lines = [
        "# 潜龙首板因子时间稳定性门（Phase 0）",
        "",
        "## Boundary",
        "",
        f"- 状态：`{str(result.get('status') or 'unavailable')}`；研究版本 `{str(result.get('study_version') or '-')}`。",
        "- 本报告只读历史数据，不改任何实时链路；`execution_valid` 恒为 False。",
        f"- 连板阈值 `>= {_integer(result.get('min_consecutive_boards'))}` 板；切浪 `{str(result.get('board_gap_mode') or 'wave')}`。",
        "",
        "## Coverage / Holdout",
        "",
        f"- 结算范围：`{str(result.get('start') or '-')}` 至 `{str(result.get('end') or '-')}`。",
        f"- 首板样本：{_integer(result.get('first_board_count'))} 个；正样本率 {_ratio_pct(balance.get('positive_rate'))}。",
        f"- train 月：{', '.join(str(one) for one in holdout_months.get('train') or [])}",
        f"- test 月：{', '.join(str(one) for one in holdout_months.get('test') or [])}",
        "",
        "## 裁决规则",
        "",
        f"- holdout 方向一致 且 test |AUC-0.5| >= {_fmt(rules.get('holdout_effect_min'))}"
        f" 且逐月一致性 >= {_fmt(rules.get('monthly_agreement_min'))}"
        " 且双目标方向一致（风控门因子豁免）。",
        "",
        "## 白名单裁决",
        "",
        "| 因子 | 角色 | 方向 | test AUC | 逐月一致性 | 双目标一致 | 结论 | 淘汰原因 |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    for item in result.get("whitelist") or []:
        row = _mapping(item)
        lines.append(
            f"| {str(row.get('factor_key') or '-')} | {str(row.get('role') or '-')} | "
            f"{str(row.get('direction') or '-')} | {_fmt(row.get('test_auc'))} | "
            f"{_fmt(row.get('monthly_agreement'))} | "
            f"{'是' if row.get('dual_target_consistent') else '否'} | "
            f"{'✅ 入列' if row.get('passed') else '❌ 淘汰'} | "
            f"{'；'.join(str(one) for one in row.get('reject_reasons') or []) or '-'} |"
        )
    temperature = _mapping(result.get("temperature_compare"))
    lines.extend(
        [
            "",
            "## 温度口径对比（全日=含未来信息，仅量化虚高；滞后=可交易口径）",
            "",
            "| 口径 | 因子 | 全样本 AUC | test AUC |",
            "|---|---|---:|---:|",
        ]
    )
    for group, label in (("lookahead", "全日(前瞻)"), ("lagged", "滞后(可用)")):
        for item in temperature.get(group) or []:
            row = _mapping(item)
            lines.append(
                f"| {label} | {str(row.get('factor_key') or '-')} | "
                f"{_fmt(row.get('full_auc'))} | {_fmt(row.get('test_auc'))} |"
            )
    clans = result.get("clans") or []
    if clans:
        lines.extend(
            [
                "",
                "## 共线性族（代表与权重上限建议）",
                "",
                "| 族 | 入列成员 | 代表 | 族权重上限 | 单因子上限 | 强相关对 |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        for item in clans:
            row = _mapping(item)
            lines.append(
                f"| {str(row.get('clan') or '-')} | "
                f"{', '.join(str(one) for one in row.get('passed_members') or []) or '-'} | "
                f"{str(row.get('representative') or '-')} | "
                f"{_fmt(row.get('weight_cap'))} | {_fmt(row.get('single_factor_cap'))} | "
                f"{'; '.join(str(one) for one in row.get('strong_pairs') or []) or '-'} |"
            )
    reports = _mapping(result.get("factor_reports"))
    lines.extend(["", "## 因子明细（holdout / 逐月 / 阈值稳定性 / 双目标）", ""])
    for factor_key in (*GATE_FACTOR_KEYS, *LOOKAHEAD_REFERENCE_KEYS):
        report = _mapping(reports.get(factor_key))
        if not report:
            continue
        holdout = _mapping(report.get("holdout"))
        monthly = _mapping(report.get("monthly"))
        dual = _mapping(report.get("dual_target"))
        threshold = _mapping(report.get("threshold"))
        lines.extend(
            [
                f"### {factor_key}",
                "",
                f"- 全样本 AUC {_fmt(monthly.get('full_auc'))}（{str(monthly.get('full_direction') or '-') }）"
                f"｜train {_fmt(holdout.get('train_auc'))}（{str(holdout.get('train_direction') or '-') }）"
                f" → test {_fmt(holdout.get('test_auc'))}（{str(holdout.get('test_direction') or '-') }）"
                f"｜逐月一致性 {_fmt(monthly.get('monthly_agreement'))}"
                f"｜D+1 AUC {_fmt(dual.get('d1_win_auc_full'))}"
                f"｜阈值 spearman {_fmt(threshold.get('spearman'))}",
                "",
                "| 月份 | 样本 | 正样本 | AUC | 方向 |",
                "|---|---:|---:|---:|---|",
            ]
        )
        for month_row in monthly.get("months") or []:
            one = _mapping(month_row)
            lines.append(
                f"| {str(one.get('month') or '-')} | {_integer(one.get('total'))} | "
                f"{_integer(one.get('positive'))} | {_fmt(one.get('auc'))} | "
                f"{str(one.get('direction') or '-')} |"
            )
        buckets = threshold.get("test_buckets") or []
        if buckets:
            lines.extend(
                [
                    "",
                    f"train 分位阈值：{', '.join(_fmt(one) for one in threshold.get('boundaries') or [])}",
                    "",
                    "| test 桶 | 样本 | 成龙率 | D+1开盘收益 |",
                    "|---|---:|---:|---:|",
                ]
            )
            for bucket in buckets:
                one = _mapping(bucket)
                lines.append(
                    f"| Q{_integer(one.get('bucket'))} | {_integer(one.get('total'))} | "
                    f"{_ratio_pct(one.get('leader_rate'))} | {_pct_signed(one.get('d1_open_return_mean'))} |"
                )
        lines.append("")
    combos = _mapping(result.get("combos_holdout"))
    for period, label in (("train", "train"), ("test", "test")):
        rows = combos.get(period) or []
        if not rows:
            continue
        lines.extend(
            [
                "",
                f"## 组合 holdout（{label}）",
                "",
                "| 组合 | 样本 | 成龙率 | D+1开盘收益 | D+1胜率 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in rows:
            item = _mapping(row)
            lines.append(
                f"| {str(item.get('combo') or '-')} | {_integer(item.get('total'))} | "
                f"{_ratio_pct(item.get('leader_rate'))} | {_pct_signed(item.get('d1_open_return_mean'))} | "
                f"{_ratio_pct(item.get('d1_open_win_rate'))} |"
            )
    lines.extend(["", "## Evidence Boundary", ""])
    for note in result.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _pct_signed(value: object) -> str:
    number = _number(value)
    return f"{number:+.2f}%" if number is not None else "-"


def _ratio_pct(value: object) -> str:
    number = _number(value)
    return f"{number * 100:.2f}%" if number is not None else "-"


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Phase 0 stability gate and write evidence files."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--min-consecutive-boards", type=int, default=DEFAULT_MIN_CONSECUTIVE_BOARDS)
    parser.add_argument("--board-gap-mode", choices=("strict", "wave"), default=DEFAULT_BOARD_GAP_MODE)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    result = run_research(
        start=arguments.start,
        end=arguments.end,
        min_consecutive_boards=arguments.min_consecutive_boards,
        board_gap_mode=arguments.board_gap_mode,
    )
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
