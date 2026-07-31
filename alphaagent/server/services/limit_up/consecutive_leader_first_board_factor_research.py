"""Read-only consecutive-leader first-board factor mining study.

找出历史中走出 ``>= min_consecutive_boards`` 连板的龙头，回看它们启动首板
（第 1 板）当天的可观测特征（封板时间、前序走势、封板质量、涨停基因、市值
流动性），与 1-2 板即夭折的普通首板做对照，提炼区分连板龙的规律因子。

研究脚本只读 PostgreSQL（``repository.load_limit_up_dataset``），只写
``memory/06_backtests`` 证据文件，绝不触碰实时表、API、portfolio 或
``actionable_recommendations``。``eventual_peak``（最终连板高度）是
**未来标签**，仅用于定义正负 label，不进入任何 D 日即时因子。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from statistics import mean, median

import numpy as np
from scipy.stats import mannwhitneyu

from alphaagent.server.services.limit_up.domain import normalize_limit_time
from alphaagent.server.services.limit_up.features import prior_stock_features
from alphaagent.server.services.limit_up.repository import load_limit_up_dataset
from alphaagent.server.services.limit_up.time_bucket_research import (
    classify_first_limit_time,
)

STUDY_VERSION = "consecutive-leader-first-board-factor-v1"
DEFAULT_MIN_CONSECUTIVE_BOARDS = 3


def extract_first_board_samples(
    events: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    *,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
) -> list[dict[str, object]]:
    """Identify first-board samples and label each by its segment's eventual peak.

    只用 ``is_sealed=True`` 的涨停事件，按 ``vt_symbol`` 分组、``trade_date``
    排序；以全市场交易日历 ``calendar`` 判断相邻性，``limit_times`` 严格递增
    （1,2,3,...）且交易日相邻才算同一段连板。每段取 ``limit_times==1`` 的首板，
    标注 ``eventual_peak``（该段最大连板数）与 ``is_leader``
    （``eventual_peak >= min_consecutive_boards``）。段内无首板（首板数据缺失）
    的整段跳过。
    """

    day_number = {value: index for index, value in enumerate(sorted(set(calendar)))}
    by_symbol: dict[str, list[Mapping[str, object]]] = {}
    for event in events:
        if not _bool(event.get("is_sealed")):
            continue
        trade_date = str(event.get("trade_date") or "")
        if trade_date not in day_number:
            continue  # 不在交易日历里的脏事件
        by_symbol.setdefault(str(event.get("vt_symbol") or ""), []).append(event)

    samples: list[dict[str, object]] = []
    for symbol in sorted(by_symbol):
        rows = sorted(by_symbol[symbol], key=lambda row: str(row.get("trade_date") or ""))
        for segment in _iter_board_segments(rows, day_number):
            first_board = next(
                (row for row in segment if _integer(row.get("limit_times")) == 1),
                None,
            )
            if first_board is None:
                continue
            peak = max(_integer(row.get("limit_times")) for row in segment)
            sample = dict(first_board)
            sample["eventual_peak"] = peak
            sample["is_leader"] = peak >= min_consecutive_boards
            sample["segment_length"] = len(segment)
            samples.append(sample)
    return samples


def _iter_board_segments(
    rows: Sequence[Mapping[str, object]],
    day_number: Mapping[str, int],
) -> list[list[Mapping[str, object]]]:
    """Split a symbol's sealed events into consecutive-board segments.

    仅当交易日历上真相邻（``day_number`` 差 1）且 ``limit_times`` 严格递增
    （前板 +1）才延续当前段，否则断开新开一段。返回有序的段列表。
    """

    segments: list[list[Mapping[str, object]]] = []
    current: list[Mapping[str, object]] = []
    for row in rows:
        trade_date = str(row.get("trade_date") or "")
        if current:
            previous = current[-1]
            previous_date = str(previous.get("trade_date") or "")
            adjacent = day_number[trade_date] == day_number[previous_date] + 1
            continuous = _integer(row.get("limit_times")) == _integer(
                previous.get("limit_times")
            ) + 1
            if adjacent and continuous:
                current.append(row)
                continue
            segments.append(current)
            current = [row]
        else:
            current = [row]
    if current:
        segments.append(current)
    return segments


def _bool(value: object) -> bool:
    return bool(value)


def _integer(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


# ── Task 2: first-board factor extraction ──────────────────────────────


def _locate_bar(
    ordered: Sequence[Mapping[str, object]], trade_date: str
) -> int | None:
    for index, row in enumerate(ordered):
        if str(row.get("trade_date") or "") == trade_date:
            return index
    return None


def _first_limit_hour(value: object) -> int | None:
    normalized = normalize_limit_time(value)
    if normalized is None:
        return None
    return int(normalized.split(":")[0])


def _is_early_seal(value: object) -> bool:
    """首板首次封板时间不晚于 10:00 视为早盘封板。"""

    normalized = normalize_limit_time(value)
    if normalized is None:
        return False
    return normalized <= "10:00:00"


_EMPTY_PRIOR_3D_SHAPE: dict[str, object] = {
    "prior_3d_cum_return_pct": None,
    "prior_3d_max_change_pct": None,
    "prior_3d_up_days": None,
    "prior_day_change_pct": None,
    "prior_day_body_pct": None,
    "prior_day_range_pct": None,
    "prior_day_close_position": None,
}


def _prior_3d_shape(
    bars: Sequence[Mapping[str, object]], trade_date: str
) -> dict[str, object]:
    """D-3..D-1 走势形状，只用首板 D 日之前的 bar（无 lookahead）。"""

    ordered = sorted(bars, key=lambda row: str(row.get("trade_date") or ""))
    index = _locate_bar(ordered, trade_date)
    if index is None or index < 1:
        return dict(_EMPTY_PRIOR_3D_SHAPE)
    window = list(ordered[max(0, index - 3): index])  # D-3..D-1
    if not window:
        return dict(_EMPTY_PRIOR_3D_SHAPE)
    changes = [
        value
        for value in (_number(row.get("change_pct")) for row in window)
        if value is not None
    ]
    base_close = _number(window[0].get("close_price"))
    last_close = _number(window[-1].get("close_price"))
    cum_return = (
        round((last_close / base_close - 1) * 100, 4)
        if base_close and last_close
        else None
    )
    day_before = ordered[index - 2] if index >= 2 else None
    prior_close = _number(day_before.get("close_price")) if day_before else None
    last = window[-1]
    return {
        "prior_3d_cum_return_pct": cum_return,
        "prior_3d_max_change_pct": round(max(changes), 4) if changes else None,
        "prior_3d_up_days": sum(1 for value in changes if value > 0),
        "prior_day_change_pct": changes[-1] if changes else None,
        "prior_day_body_pct": _body_pct(last, prior_close),
        "prior_day_range_pct": _range_pct(last, prior_close),
        "prior_day_close_position": _close_position(last),
    }


def _body_pct(bar: Mapping[str, object], prior_close: float | None) -> float | None:
    open_price = _number(bar.get("open_price"))
    close_price = _number(bar.get("close_price"))
    if None in (open_price, close_price) or not prior_close:
        return None
    return round(abs(close_price - open_price) / prior_close * 100, 4)


def _range_pct(bar: Mapping[str, object], prior_close: float | None) -> float | None:
    high = _number(bar.get("high_price"))
    low = _number(bar.get("low_price"))
    if None in (high, low) or not prior_close:
        return None
    return round((high - low) / prior_close * 100, 4)


def _close_position(bar: Mapping[str, object]) -> float | None:
    high = _number(bar.get("high_price"))
    low = _number(bar.get("low_price"))
    close_price = _number(bar.get("close_price"))
    if None in (high, low, close_price) or high <= low:
        return None
    return round((close_price - low) / (high - low), 4)


def _is_one_word_board(d_bar: Mapping[str, object] | None) -> bool:
    """一字板：开/收/高/低几乎相等（振幅与实体均 <0.1%）。"""

    if not d_bar:
        return False
    open_price = _number(d_bar.get("open_price"))
    close_price = _number(d_bar.get("close_price"))
    high = _number(d_bar.get("high_price"))
    low = _number(d_bar.get("low_price"))
    if None in (open_price, close_price, high, low) or high <= 0:
        return False
    return (high - low) / high < 0.001 and abs(open_price - close_price) / high < 0.001


def _seal_quality(
    sample: Mapping[str, object], d_bar: Mapping[str, object] | None
) -> dict[str, object]:
    open_times = _integer(sample.get("open_times"))
    seal_amount = _number(sample.get("seal_amount"))
    turnover = _number(sample.get("turnover"))
    seal_to_turnover = (
        round(seal_amount / turnover, 4) if seal_amount is not None and turnover else None
    )
    is_early = _is_early_seal(sample.get("first_limit_time"))
    return {
        "open_times": open_times,
        "seal_to_turnover_ratio": seal_to_turnover,
        "is_one_word_board": _is_one_word_board(d_bar),
        "is_clean_seal": open_times == 0 and is_early,
    }


_EMPTY_PRIOR_LIMITS: dict[str, object] = {
    "prior_limit_count_126": None,
    "prior_limit_count_20": None,
    "days_since_prior_limit": None,
}


def compute_prior_limit_counts(
    samples: Sequence[Mapping[str, object]],
    all_events: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    *,
    long_window: int = 126,
    short_window: int = 20,
) -> dict[tuple[str, str], dict[str, object]]:
    """每个首板样本在 D 日之前的历史涨停频率（用全量 events 自算，无 lookahead）。"""

    day_number = {value: index for index, value in enumerate(sorted(set(calendar)))}
    by_symbol: dict[str, list[int]] = {}
    for event in all_events:
        if not _bool(event.get("is_sealed")):
            continue
        trade_date = str(event.get("trade_date") or "")
        if trade_date in day_number:
            by_symbol.setdefault(str(event.get("vt_symbol") or ""), []).append(
                day_number[trade_date]
            )
    counts: dict[tuple[str, str], dict[str, object]] = {}
    for sample in samples:
        symbol = str(sample.get("vt_symbol") or "")
        trade_date = str(sample.get("trade_date") or "")
        if trade_date not in day_number:
            counts[(symbol, trade_date)] = dict(_EMPTY_PRIOR_LIMITS)
            continue
        current = day_number[trade_date]
        prior_nums = sorted(n for n in by_symbol.get(symbol, []) if n < current)
        counts[(symbol, trade_date)] = {
            "prior_limit_count_126": sum(
                1 for n in prior_nums if n >= current - long_window
            ),
            "prior_limit_count_20": sum(
                1 for n in prior_nums if n >= current - short_window
            ),
            "days_since_prior_limit": current - prior_nums[-1] if prior_nums else None,
        }
    return counts


def extract_factor_vector(
    sample: Mapping[str, object],
    *,
    symbol_bars: Sequence[Mapping[str, object]],
    d_bar: Mapping[str, object] | None,
    prior_limits: Mapping[str, object],
) -> dict[str, object]:
    """Combine all D-day-observable factors for one first-board sample.

    所有因子只用首板当天及之前可观测的数据；``is_leader`` / ``eventual_peak``
    仅供对照分组，不作为可交易因子。
    """

    trade_date = str(sample.get("trade_date") or "")
    bucket = classify_first_limit_time(sample.get("first_limit_time"))
    prior = prior_stock_features(symbol_bars, trade_date)
    shape = _prior_3d_shape(symbol_bars, trade_date)
    seal = _seal_quality(sample, d_bar)
    return {
        # ① 封板时间（盘中）
        "first_limit_time_bucket": bucket[0] if bucket else None,
        "first_limit_hour": _first_limit_hour(sample.get("first_limit_time")),
        "is_early_seal": _is_early_seal(sample.get("first_limit_time")),
        # ② 前序走势（前 5 日）
        "prior_return_5d_pct": prior["prior_return_5d_pct"],
        "prior_turnover_ratio_5d": prior["prior_turnover_ratio_5d"],
        "prior_change_pct": prior["prior_change_pct"],
        # ③ 前 3 天走势形状
        **shape,
        # ④ 封板质量
        **seal,
        # ⑤ 涨停基因（events 自算）
        "prior_limit_count_126": prior_limits.get("prior_limit_count_126"),
        "prior_limit_count_20": prior_limits.get("prior_limit_count_20"),
        "days_since_prior_limit": prior_limits.get("days_since_prior_limit"),
        # ⑥ 市值/流动性
        "float_market_cap": _number(sample.get("float_market_cap")),
        "turnover_rate": _number(sample.get("turnover_rate")),
        # label（仅供对照）
        "is_leader": sample.get("is_leader"),
        "eventual_peak": sample.get("eventual_peak"),
    }


# ── Task 3: factor comparison statistics ───────────────────────────────

COMPARE_DRAWS = 2000
COMPARE_SEED = 20260730


def _sample_float(value: object) -> float | None:
    """Coerce a factor value to float; bool -> 0.0/1.0; non-numeric -> None."""

    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_factor_groups(
    samples: Sequence[Mapping[str, object]], factor_key: str
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    positives: list[tuple[str, float]] = []
    negatives: list[tuple[str, float]] = []
    for sample in samples:
        value = _sample_float(sample.get(factor_key))
        if value is None:
            continue
        trade_date = str(sample.get("trade_date") or "")
        if _bool(sample.get("is_leader")):
            positives.append((trade_date, value))
        else:
            negatives.append((trade_date, value))
    return positives, negatives


def _auc(pos_values: Sequence[float], neg_values: Sequence[float]) -> float | None:
    if not pos_values or not neg_values:
        return None
    result = mannwhitneyu(pos_values, neg_values, alternative="greater")
    return float(result.statistic) / (len(pos_values) * len(neg_values))


def _auc_direction(auc: float | None) -> str:
    if auc is None:
        return "flat"
    if auc > 0.5:
        return "higher"
    if auc < 0.5:
        return "lower"
    return "flat"


def _quintile_positive_rates(
    samples: Sequence[Mapping[str, object]], factor_key: str, *, buckets: int = 5
) -> list[dict[str, object]]:
    valued = sorted(
        (
            (value, _bool(sample.get("is_leader")))
            for sample in samples
            if (value := _sample_float(sample.get(factor_key))) is not None
        ),
        key=lambda item: item[0],
    )
    total = len(valued)
    if total < buckets:
        return []
    rates: list[dict[str, object]] = []
    for index in range(buckets):
        chunk = valued[index * total // buckets : (index + 1) * total // buckets]
        if not chunk:
            continue
        positive = sum(1 for _, is_win in chunk if is_win)
        rates.append(
            {
                "quintile": index + 1,
                "total": len(chunk),
                "positive_count": positive,
                "positive_rate": round(positive / len(chunk), 4),
                "value_min": round(chunk[0][0], 4),
                "value_max": round(chunk[-1][0], 4),
            }
        )
    return rates


def _date_block_bootstrap_mean_delta(
    positives: Sequence[tuple[str, float]],
    negatives: Sequence[tuple[str, float]],
    *,
    draws: int,
    seed: int,
) -> dict[str, float | None]:
    """按 trade_date 整块重采样，返回正负因子均值差的 95% 置信区间。"""

    if not positives or not negatives:
        return {"mean_delta": None, "lower_95": None, "upper_95": None}
    pos_by_date: dict[str, list[float]] = defaultdict(list)
    for trade_date, value in positives:
        pos_by_date[trade_date].append(value)
    neg_by_date: dict[str, list[float]] = defaultdict(list)
    for trade_date, value in negatives:
        neg_by_date[trade_date].append(value)
    dates = sorted(set(pos_by_date) | set(neg_by_date))
    rng = np.random.default_rng(seed)
    deltas: list[float] = []
    for _ in range(draws):
        sampled = rng.choice(dates, size=len(dates), replace=True)
        pos_pool = [value for one in sampled for value in pos_by_date.get(one, ())]
        neg_pool = [value for one in sampled for value in neg_by_date.get(one, ())]
        if pos_pool and neg_pool:
            deltas.append(float(np.mean(pos_pool) - np.mean(neg_pool)))
    if not deltas:
        return {"mean_delta": None, "lower_95": None, "upper_95": None}
    return {
        "mean_delta": round(float(np.mean(deltas)), 4),
        "lower_95": round(float(np.quantile(deltas, 0.025)), 4),
        "upper_95": round(float(np.quantile(deltas, 0.975)), 4),
    }


def compare_numeric_factor(
    samples: Sequence[Mapping[str, object]],
    factor_key: str,
    *,
    draws: int = COMPARE_DRAWS,
    seed: int = COMPARE_SEED,
) -> dict[str, object]:
    """对照正/负样本在某个数值（或布尔）因子上的分布与区分度。"""

    positives, negatives = _split_factor_groups(samples, factor_key)
    pos_values = [value for _, value in positives]
    neg_values = [value for _, value in negatives]
    auc = _auc(pos_values, neg_values)
    bootstrap = _date_block_bootstrap_mean_delta(
        positives, negatives, draws=draws, seed=seed
    )
    return {
        "factor_key": factor_key,
        "sample_count": len(pos_values) + len(neg_values),
        "positive_count": len(pos_values),
        "negative_count": len(neg_values),
        "positive_mean": round(mean(pos_values), 4) if pos_values else None,
        "negative_mean": round(mean(neg_values), 4) if neg_values else None,
        "positive_median": round(median(pos_values), 4) if pos_values else None,
        "negative_median": round(median(neg_values), 4) if neg_values else None,
        "auc": round(auc, 4) if auc is not None else None,
        "effect_strength": round(abs(auc - 0.5) * 100, 2) if auc is not None else None,
        "direction": _auc_direction(auc),
        "mean_delta": bootstrap["mean_delta"],
        "mean_delta_lower_95": bootstrap["lower_95"],
        "mean_delta_upper_95": bootstrap["upper_95"],
        "quintile_positive_rates": _quintile_positive_rates(samples, factor_key),
    }


def compare_categorical_factor(
    samples: Sequence[Mapping[str, object]], factor_key: str
) -> dict[str, object]:
    """分类因子的各类正样本率（按正样本率降序）。"""

    totals: dict[str, int] = defaultdict(int)
    positives: dict[str, int] = defaultdict(int)
    for sample in samples:
        category = sample.get(factor_key)
        if category is None:
            continue
        key = str(category)
        totals[key] += 1
        if _bool(sample.get("is_leader")):
            positives[key] += 1
    categories: list[dict[str, object]] = []
    for key, total in totals.items():
        positive = positives.get(key, 0)
        categories.append(
            {
                "category": key,
                "total": total,
                "positive_count": positive,
                "positive_rate": round(positive / total, 4) if total else None,
            }
        )
    categories.sort(key=lambda item: item["positive_rate"] or 0.0, reverse=True)
    return {"factor_key": factor_key, "categories": categories}


def rank_factors(
    samples: Sequence[Mapping[str, object]],
    numeric_keys: Sequence[str],
    *,
    draws: int = COMPARE_DRAWS,
    seed: int = COMPARE_SEED,
) -> list[dict[str, object]]:
    """对所有数值因子计算区分度并按 effect_strength 降序排序。"""

    results = [
        compare_numeric_factor(samples, key, draws=draws, seed=seed)
        for key in numeric_keys
    ]
    results.sort(key=lambda item: item.get("effect_strength") or 0.0, reverse=True)
    return results


# ── Task 4: report orchestration, markdown, CLI ────────────────────────

NUMERIC_FACTOR_KEYS = (
    "first_limit_hour",
    "is_early_seal",
    "prior_return_5d_pct",
    "prior_turnover_ratio_5d",
    "prior_change_pct",
    "prior_3d_cum_return_pct",
    "prior_3d_max_change_pct",
    "prior_3d_up_days",
    "prior_day_change_pct",
    "prior_day_body_pct",
    "prior_day_range_pct",
    "prior_day_close_position",
    "open_times",
    "seal_to_turnover_ratio",
    "is_one_word_board",
    "is_clean_seal",
    "prior_limit_count_126",
    "prior_limit_count_20",
    "days_since_prior_limit",
    "float_market_cap",
    "turnover_rate",
)
CATEGORICAL_FACTOR_KEYS = ("first_limit_time_bucket",)

_RESEARCH_NOTES = (
    "eventual_peak（最终连板高度）是未来标签，仅用于定义正负 label，不进入任何 D 日即时因子。",
    "所有因子只用首板当天及之前可观测数据；封板时间取 provider 首次封板时间。",
    "样本仅覆盖 stock_events 现有区间（约 2025-06-27 起 13 个月），跨牛熊周期不足，结论适用于相近市场环境。",
    "涨停判定沿用 events 的 provider 标记（主板口径）；创业板/科创板 20% 幅度未单独处理。",
)


def build_factor_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    *,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
    draws: int = COMPARE_DRAWS,
    seed: int = COMPARE_SEED,
) -> dict[str, object]:
    """Orchestrate first-board factor mining into a non-actionable report.

    纯函数：不连数据库。``run_research`` 负责取数后调用本函数。
    """

    samples = extract_first_board_samples(
        events, calendar, min_consecutive_boards=min_consecutive_boards
    )
    prior_limits = compute_prior_limit_counts(samples, events, calendar)
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)

    factor_samples: list[dict[str, object]] = []
    for sample in samples:
        symbol = str(sample.get("vt_symbol") or "")
        trade_date = str(sample.get("trade_date") or "")
        symbol_bars = bars_by_symbol.get(symbol, [])
        d_bar = next(
            (bar for bar in symbol_bars if str(bar.get("trade_date") or "") == trade_date),
            None,
        )
        limits = prior_limits.get((symbol, trade_date), {})
        factors = extract_factor_vector(
            sample, symbol_bars=symbol_bars, d_bar=d_bar, prior_limits=limits
        )
        factors["vt_symbol"] = symbol
        factors["trade_date"] = trade_date
        factors["name"] = sample.get("name")
        factor_samples.append(factors)

    numeric_ranking = rank_factors(factor_samples, NUMERIC_FACTOR_KEYS, draws=draws, seed=seed)
    categorical_reports = {
        key: compare_categorical_factor(factor_samples, key)
        for key in CATEGORICAL_FACTOR_KEYS
    }
    positive = sum(1 for sample in factor_samples if _bool(sample.get("is_leader")))
    negative = len(factor_samples) - positive
    return {
        "status": "ok" if factor_samples else "insufficient_data",
        "mode": "leader_first_board_factor_lookahead_proxy",
        "execution_valid": False,
        "study_version": STUDY_VERSION,
        "min_consecutive_boards": min_consecutive_boards,
        "first_board_count": len(factor_samples),
        "label_balance": {
            "positive": positive,
            "negative": negative,
            "positive_rate": round(positive / len(factor_samples), 4)
            if factor_samples
            else None,
        },
        "numeric_factor_ranking": numeric_ranking,
        "categorical_factors": categorical_reports,
        "notes": list(_RESEARCH_NOTES),
    }


def run_research(
    *,
    start: date,
    end: date,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
) -> dict[str, object]:
    """Load frozen dataset and return a non-actionable first-board factor report."""

    dataset = load_limit_up_dataset(start, end)
    events = dataset["events"]
    daily_bars = dataset["daily_bars"]
    calendar = sorted(
        {str(bar.get("trade_date") or "") for bar in daily_bars if bar.get("trade_date")}
    )
    report = build_factor_report(
        events,
        daily_bars,
        calendar,
        min_consecutive_boards=min_consecutive_boards,
    )
    coverage = dict(dataset.get("coverage") or {})
    coverage["trade_days_in_window"] = len(calendar)
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["coverage"] = coverage
    report["input_fingerprint"] = _input_fingerprint(
        events, daily_bars, report["first_board_count"]
    )
    return report


def _input_fingerprint(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    first_board_count: int,
) -> str:
    payload = f"{STUDY_VERSION}|{len(events)}|{len(daily_bars)}|{first_board_count}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def render_markdown(result: Mapping[str, object]) -> str:
    """Render the read-only first-board factor mining evidence."""

    balance = _mapping(result.get("label_balance"))
    coverage = _mapping(result.get("coverage"))
    ranking = result.get("numeric_factor_ranking") or []
    lines = [
        "# Consecutive-Leader First-Board Factor Mining",
        "",
        "## Boundary",
        "",
        f"- 状态：`{str(result.get('status') or 'unavailable')}`；研究版本 `{str(result.get('study_version') or '-')}`。",
        "- 本报告只读 `stock_events`/`stock_daily_bars`，不修改 `limit-up-core-abc-v2`、C、实时推荐或账户。",
        "- `eventual_peak`（最终连板高度）是未来标签，仅用于定义正/负 label，绝不作为可交易因子。",
        "- 所有数值因子均使用首板当天及之前可观测的数据；封板时间取 provider 首次封板时间。",
        f"- 连板阈值 `>= {_integer(result.get('min_consecutive_boards'))}` 板；改阈值需重跑，结论不冒充普适规律。",
        "",
        "## Coverage",
        "",
        f"- 结算范围：`{str(result.get('start') or '-')}` 至 `{str(result.get('end') or '-')}`。",
        f"- 首板样本：{_integer(result.get('first_board_count'))} 个；窗口交易日：{_integer(coverage.get('trade_days_in_window'))} 日。",
        f"- 输入指纹：`{str(result.get('input_fingerprint') or '-')}`。",
        "",
        "## Sample Balance",
        "",
        f"- 正样本（连板 >= 阈值）：{_integer(balance.get('positive'))}；"
        f"负样本（1-2 板夭折）：{_integer(balance.get('negative'))}；"
        f"正样本率：{_ratio_pct(balance.get('positive_rate'))}。",
        "- 正负比悬殊时 AUC 仍有效；五分桶正样本率在小样本桶内波动大，需结合样本量解读。",
        "",
        "## Numeric Factor Ranking",
        "",
        "| 因子 | 正/负 | 正均值 | 负均值 | AUC | 效应强度 | 方向 | 均值差 | 95%下限 | 95%上限 |",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|",
    ]
    for item in ranking:
        lines.append(_numeric_factor_row(item))
    categorical = _mapping(result.get("categorical_factors")).get("first_limit_time_bucket")
    if categorical:
        lines.extend(
            [
                "",
                "## Categorical Factors — First-Limit-Time Bucket",
                "",
                "| 时段桶 | 样本 | 正样本 | 正样本率 |",
                "|---|---:|---:|---:|",
            ]
        )
        for category in _mapping(categorical).get("categories", []):
            row = _mapping(category)
            lines.append(
                f"| {str(row.get('category') or '-')} | {_integer(row.get('total'))} | "
                f"{_integer(row.get('positive_count'))} | {_ratio_pct(row.get('positive_rate'))} |"
            )
    lines.extend(["", "## Top Factors — Quintile Positive Rates", ""])
    for item in ranking[:5]:
        lines.extend(_quintile_section(item))
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- 本报告为只读因子挖掘证据，``execution_valid`` 恒为 False，不产出可执行信号，不改变任何正式门或实时推荐。",
            "- 高效应因子仅作研究线索；任何上线须经独立自然前向验证与用户审批。",
            "",
            "## Evidence Boundary",
            "",
            "- JSON 含全部因子明细与五分桶；Markdown 只显示排行与 Top5 因子，避免事后最高被误读为可交易规则。",
            "- 样本仅覆盖现有事件区间（约 13 个月），跨牛熊不足；结论不可外推为全周期普适规律。",
        ]
    )
    return "\n".join(lines) + "\n"


def _numeric_factor_row(item: Mapping[str, object]) -> str:
    return (
        f"| {str(item.get('factor_key') or '-')} | "
        f"{_integer(item.get('positive_count'))}/{_integer(item.get('negative_count'))} | "
        f"{_fmt(item.get('positive_mean'))} | {_fmt(item.get('negative_mean'))} | "
        f"{_fmt(item.get('auc'))} | {_fmt(item.get('effect_strength'))} | "
        f"{str(item.get('direction') or '-')} | "
        f"{_fmt(item.get('mean_delta'))} | {_fmt(item.get('mean_delta_lower_95'))} | "
        f"{_fmt(item.get('mean_delta_upper_95'))} |"
    )


def _quintile_section(item: Mapping[str, object]) -> list[str]:
    rates = item.get("quintile_positive_rates") or []
    if not rates:
        return []
    lines = [
        "",
        f"### {str(item.get('factor_key') or '-')} "
        f"(AUC={_fmt(item.get('auc'))}, 效应={_fmt(item.get('effect_strength'))}, "
        f"方向={str(item.get('direction') or '-')})",
        "",
        "| 分位 | 样本 | 正样本 | 正样本率 | 区间下限 | 区间上限 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for rate in rates:
        row = _mapping(rate)
        lines.append(
            f"| Q{_integer(row.get('quintile'))} | {_integer(row.get('total'))} | "
            f"{_integer(row.get('positive_count'))} | {_ratio_pct(row.get('positive_rate'))} | "
            f"{_fmt(row.get('value_min'))} | {_fmt(row.get('value_max'))} |"
        )
    return lines


def main(argv: Sequence[str] | None = None) -> None:
    """Run the read-only first-board factor study and write evidence files."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--min-consecutive-boards", type=int, default=DEFAULT_MIN_CONSECUTIVE_BOARDS)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    result = run_research(
        start=arguments.start,
        end=arguments.end,
        min_consecutive_boards=arguments.min_consecutive_boards,
    )
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _pct(value: object) -> str:
    number = _number(value)
    return f"{number:.2f}%" if number is not None else "-"


def _ratio_pct(value: object) -> str:
    """小数比例（0.0519）渲染为百分比（5.19%）。"""

    number = _number(value)
    return f"{number * 100:.2f}%" if number is not None else "-"


if __name__ == "__main__":
    main()
