"""Read-only morning-window (09:30-11:00) leader-probability scoring study.

v2 of consecutive-leader first-board research. 聚焦 9:30-11:00 封板的首板，用
封板前可观测的日线级因子（D-1 收盘可知）建透明分位校准评分，按月 + 时间
holdout 防过拟合，产出可排序的龙头概率。研究只读 PostgreSQL
（``repository.load_limit_up_dataset``），只写 ``memory/06_backtests`` 证据文件，
绝不触碰实时表、API、portfolio 或 ``actionable_recommendations``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    compare_categorical_factor,
    compare_numeric_factor,
    compute_prior_limit_counts,
    extract_factor_vector,
    extract_first_board_samples,
)
from alphaagent.server.services.limit_up.repository import load_limit_up_dataset

STUDY_VERSION = "morning-window-leader-probability-v1"
DEFAULT_MIN_CONSECUTIVE_BOARDS = 3
DEFAULT_TRAIN_MONTHS = 10
DEFAULT_MIN_EFFECT = 5.0
DEFAULT_SCORE_AUC_LOCK = 0.58
WINDOW_START = "09:30:00"
WINDOW_END = "11:00:00"


def filter_morning_window(
    samples: Sequence[Mapping[str, object]],
    *,
    start: str = WINDOW_START,
    end: str = WINDOW_END,
) -> list[Mapping[str, object]]:
    """只保留首次封板时间落在 ``[start, end]`` 的样本（含边界）。"""

    result: list[Mapping[str, object]] = []
    for sample in samples:
        value = sample.get("first_limit_time")
        if value is None:
            continue
        text = str(value)
        if start <= text <= end:
            result.append(sample)
    return result


def group_by_month(
    samples: Sequence[Mapping[str, object]]
) -> dict[str, list[Mapping[str, object]]]:
    """按 ``trade_date`` 的 ``YYYY-MM`` 前缀分组。"""

    by_month: dict[str, list[Mapping[str, object]]] = {}
    for sample in samples:
        year_month = str(sample.get("trade_date") or "")[:7]
        if not year_month:
            continue
        by_month.setdefault(year_month, []).append(sample)
    return by_month


def time_holdout_split(
    samples: Sequence[Mapping[str, object]], *, train_months: int = DEFAULT_TRAIN_MONTHS
) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]]]:
    """按月份时间序切分：最早 ``train_months`` 个月为 train，其余为 test。

    保证无未来泄漏——train 月份严格早于 test 月份，test 所有日期晚于 train。
    """

    if train_months <= 0:
        return [], list(samples)
    by_month = group_by_month(samples)
    sorted_months = sorted(by_month.keys())
    train_month_set = set(sorted_months[:train_months])
    train: list[Mapping[str, object]] = []
    test: list[Mapping[str, object]] = []
    for sample in samples:
        year_month = str(sample.get("trade_date") or "")[:7]
        (train if year_month in train_month_set else test).append(sample)
    return train, test


# ── Task 2: transparent probability scoring ────────────────────────────


def build_calibration(
    train_samples: Sequence[Mapping[str, object]],
    factor_keys: Sequence[str],
    *,
    min_effect: float = DEFAULT_MIN_EFFECT,
    buckets: int = 5,
    draws: int = 2000,
    seed: int = 20260730,
) -> dict[str, object]:
    """在 train 集上为每个 effect≥min_effect 的因子建五分位→正样本率校准表。

    权重 = 各因子 effect_strength 归一化（effect 越大权重越高）。
    """

    factors: dict[str, dict[str, object]] = {}
    for factor in factor_keys:
        stats = compare_numeric_factor(train_samples, factor, draws=draws, seed=seed)
        effect = stats.get("effect_strength")
        if effect is None or effect < min_effect:
            continue
        quintiles = stats.get("quintile_positive_rates") or []
        if len(quintiles) != buckets:
            continue
        bounds = [
            (quintile.get("value_min"), quintile.get("value_max"))
            for quintile in quintiles
        ]
        factors[factor] = {
            "effect_strength": effect,
            "auc": stats.get("auc"),
            "direction": stats.get("direction"),
            "bounds": bounds,
            "quintile_rates": [quintile.get("positive_rate") for quintile in quintiles],
        }
    total_effect = sum(spec["effect_strength"] for spec in factors.values())
    for spec in factors.values():
        spec["weight"] = spec["effect_strength"] / total_effect if total_effect > 0 else 0.0
    return {"factors": factors, "buckets": buckets}


def score_leader_probability(
    sample: Mapping[str, object], calibration: Mapping[str, object]
) -> float | None:
    """查样本各入选因子所在分位的正样本率，按权重加权平均得龙头概率。"""

    factors = calibration.get("factors", {})
    if not factors:
        return None
    buckets = int(calibration.get("buckets", 5))
    weighted_sum = 0.0
    weight_sum = 0.0
    for factor, spec in factors.items():
        value = _to_float(sample.get(factor))
        if value is None:
            continue
        quintile = _quintile_of(value, spec.get("bounds", []), buckets)
        if quintile is None:
            continue
        rate = spec["quintile_rates"][quintile - 1]
        weight = float(spec.get("weight", 0.0))
        weighted_sum += (rate or 0.0) * weight
        weight_sum += weight
    if weight_sum <= 0:
        return None
    return round(weighted_sum / weight_sum, 6)


def _quintile_of(
    value: float, bounds: Sequence[object], buckets: int
) -> int | None:
    for index, pair in enumerate(bounds):
        lo = _to_float(pair[0]) if isinstance(pair, Sequence) else _to_float(pair)
        hi = _to_float(pair[1]) if isinstance(pair, Sequence) else None
        if lo is None or hi is None:
            continue
        if lo <= value <= hi:
            return index + 1
    if bounds:
        first_lo = _to_float(bounds[0][0]) if isinstance(bounds[0], Sequence) else None
        last_hi = _to_float(bounds[-1][1]) if isinstance(bounds[-1], Sequence) else None
        if first_lo is not None and value < first_lo:
            return 1
        if last_hi is not None and value > last_hi:
            return buckets
    return None


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: object) -> bool:
    return bool(value)


# ── Task 3: holdout evaluation & monthly stability ─────────────────────


def evaluate_score(
    test_samples: Sequence[Mapping[str, object]],
    calibration: Mapping[str, object],
    *,
    auc_lock: float = DEFAULT_SCORE_AUC_LOCK,
    draws: int = 2000,
    seed: int = 20260730,
) -> dict[str, object]:
    """在 holdout 上评估龙头概率评分的区分度，判定是否锁定。"""

    scored: list[dict[str, object]] = []
    for sample in test_samples:
        score = score_leader_probability(sample, calibration)
        if score is None:
            continue
        enriched = dict(sample)
        enriched["leader_probability"] = score
        scored.append(enriched)
    if not scored:
        return {
            "sample_count": 0,
            "positive_count": 0,
            "auc": None,
            "baseline_rate": None,
            "top20_positive_rate": None,
            "bottom20_positive_rate": None,
            "lift": None,
            "locked": False,
        }
    stats = compare_numeric_factor(scored, "leader_probability", draws=draws, seed=seed)
    positive = sum(1 for sample in scored if _bool(sample.get("is_leader")))
    baseline = positive / len(scored)
    quintiles = stats.get("quintile_positive_rates") or []
    top20 = quintiles[-1].get("positive_rate") if quintiles else None
    bottom20 = quintiles[0].get("positive_rate") if quintiles else None
    auc = stats.get("auc")
    lift = (top20 / baseline) if (top20 is not None and baseline) else None
    locked = bool(
        auc is not None
        and auc >= auc_lock
        and top20 is not None
        and bottom20 is not None
        and top20 > baseline
        and top20 > bottom20
    )
    return {
        "sample_count": len(scored),
        "positive_count": positive,
        "auc": auc,
        "baseline_rate": round(baseline, 4),
        "top20_positive_rate": top20,
        "bottom20_positive_rate": bottom20,
        "lift": round(lift, 4) if lift is not None else None,
        "locked": locked,
    }


def monthly_factor_stability(
    samples_by_month: Mapping[str, Sequence[Mapping[str, object]]],
    factor_keys: Sequence[str],
    *,
    draws: int = 2000,
    seed: int = 20260730,
) -> dict[str, dict[str, object]]:
    """每个因子按月算 AUC/方向；方向跨月翻转则标 ``unstable``。"""

    result: dict[str, dict[str, object]] = {}
    for factor in factor_keys:
        monthly: dict[str, object] = {}
        directions: list[str] = []
        for year_month, samples in samples_by_month.items():
            stats = compare_numeric_factor(samples, factor, draws=draws, seed=seed)
            direction = stats.get("direction")
            monthly[year_month] = {
                "auc": stats.get("auc"),
                "direction": direction,
                "effect_strength": stats.get("effect_strength"),
                "sample_count": stats.get("sample_count"),
            }
            if direction in ("higher", "lower"):
                directions.append(str(direction))
        distinct = sorted(set(directions))
        result[factor] = {
            "monthly": monthly,
            "directions": distinct,
            "unstable": len(distinct) > 1,
        }
    return result


# ── Task 4: report orchestration, markdown, CLI ────────────────────────

# A 组：封板前可观测（D-1 收盘可知），进龙头概率评分
GROUP_A_FACTORS = (
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
    "prior_limit_count_126",
    "prior_limit_count_20",
    "days_since_prior_limit",
    "float_market_cap",
    "turnover_rate",
)
# B 组：封板时刻质量（封板瞬间可知），仅诊断不进封板前评分
GROUP_B_NUMERIC = (
    "first_limit_hour",
    "is_early_seal",
    "open_times",
    "seal_to_turnover_ratio",
    "is_one_word_board",
    "is_clean_seal",
)
GROUP_B_CATEGORICAL = ("first_limit_time_bucket",)

_RESEARCH_NOTES = (
    "龙头概率 = 入选 A 因子（封板前可观测）五分位正样本率的 effect 加权平均；透明可解释，非黑盒 ML。",
    "eventual_peak 仅作 label；评分只用 D-1 收盘可观测的日线级因子，无未来函数。",
    "样本仅 13 个月 events，holdout 只有约 4 个月，统计功效有限；locked 因子须后续自然前向积累验证。",
    "封板前因子是日线级（D-1 可知），非封板当天早盘实时；实盘需 D-1 预筛 + D 日盘中确认两步。",
    "9:30-11:00 窗口已排除竞价秒板（买不到）和尾盘板；B 组封板时刻质量因子仅诊断不进评分。",
)


def build_probability_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    *,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
    train_months: int = DEFAULT_TRAIN_MONTHS,
    min_effect: float = DEFAULT_MIN_EFFECT,
    draws: int = 2000,
    seed: int = 20260730,
) -> dict[str, object]:
    """编排：首板提取 → 9:30-11:00 过滤 → 时间切分 → train 校准 → test 验证 → 月度稳定性。"""

    all_samples = extract_first_board_samples(
        events, calendar, min_consecutive_boards=min_consecutive_boards
    )
    prior_limits = compute_prior_limit_counts(all_samples, events, calendar)
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)

    factor_samples: list[dict[str, object]] = []
    for sample in all_samples:
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
        factors["first_limit_time"] = sample.get("first_limit_time")  # 供 9:30-11:00 窗口过滤
        factor_samples.append(factors)

    window_samples = filter_morning_window(factor_samples)
    train, test = time_holdout_split(window_samples, train_months=train_months)
    calibration = build_calibration(
        train, GROUP_A_FACTORS, min_effect=min_effect, draws=draws, seed=seed
    )
    holdout = evaluate_score(test, calibration, draws=draws, seed=seed)
    stability = monthly_factor_stability(
        group_by_month(window_samples), GROUP_A_FACTORS, draws=draws, seed=seed
    )
    locked = [
        factor
        for factor in calibration.get("factors", {})
        if holdout.get("locked")
        and not stability.get(factor, {}).get("unstable", True)
    ]

    group_b_summary: dict[str, object] = {}
    for key in GROUP_B_NUMERIC:
        group_b_summary[key] = compare_numeric_factor(
            window_samples, key, draws=draws, seed=seed
        )
    for key in GROUP_B_CATEGORICAL:
        group_b_summary[key] = compare_categorical_factor(window_samples, key)

    positive = sum(1 for sample in window_samples if _bool(sample.get("is_leader")))
    return {
        "status": "ok" if window_samples else "insufficient_data",
        "mode": "morning_window_leader_probability_lookahead_proxy",
        "execution_valid": False,
        "study_version": STUDY_VERSION,
        "min_consecutive_boards": min_consecutive_boards,
        "train_months": train_months,
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "coverage": {
            "first_board_total": len(all_samples),
            "morning_window_count": len(window_samples),
            "train_count": len(train),
            "test_count": len(test),
        },
        "sample_balance": {
            "positive": positive,
            "negative": len(window_samples) - positive,
            "positive_rate": round(positive / len(window_samples), 4)
            if window_samples
            else None,
        },
        "calibration": calibration,
        "holdout_eval": holdout,
        "monthly_stability": stability,
        "locked_factors": locked,
        "group_b_factor_summary": group_b_summary,
        "notes": list(_RESEARCH_NOTES),
    }


def run_research(
    *,
    start: date,
    end: date,
    min_consecutive_boards: int = DEFAULT_MIN_CONSECUTIVE_BOARDS,
    train_months: int = DEFAULT_TRAIN_MONTHS,
) -> dict[str, object]:
    """Load frozen dataset and return a non-actionable morning-window probability report."""

    dataset = load_limit_up_dataset(start, end)
    events = dataset["events"]
    daily_bars = dataset["daily_bars"]
    calendar = sorted(
        {str(bar.get("trade_date") or "") for bar in daily_bars if bar.get("trade_date")}
    )
    report = build_probability_report(
        events,
        daily_bars,
        calendar,
        min_consecutive_boards=min_consecutive_boards,
        train_months=train_months,
    )
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["coverage"]["trade_days_in_window"] = len(calendar)
    report["input_fingerprint"] = _input_fingerprint(
        events, daily_bars, report["coverage"]["morning_window_count"]
    )
    return report


def _input_fingerprint(events, daily_bars, morning_count) -> str:
    payload = f"{STUDY_VERSION}|{len(events)}|{len(daily_bars)}|{morning_count}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def render_markdown(result: Mapping[str, object]) -> str:
    """Render the read-only morning-window leader-probability evidence."""

    coverage = _mapping(result.get("coverage"))
    balance = _mapping(result.get("sample_balance"))
    holdout = _mapping(result.get("holdout_eval"))
    calibration = _mapping(result.get("calibration"))
    factors = calibration.get("factors", {})
    locked = result.get("locked_factors") or []
    stability = result.get("monthly_stability") or {}
    lines = [
        "# Morning-Window (09:30-11:00) Leader-Probability Scoring",
        "",
        "## Boundary",
        "",
        f"- 状态：`{str(result.get('status') or 'unavailable')}`；研究版本 `{str(result.get('study_version') or '-')}`。",
        "- 本报告只读 `stock_events`/`stock_daily_bars`，不修改 `limit-up-core-abc-v2`、C、实时推荐或账户。",
        "- 龙头概率 = 入选 A 因子五分位正样本率的 effect 加权平均；透明可解释，非黑盒模型。",
        "- `eventual_peak` 仅作 label；评分只用 D-1 收盘可观测因子，无未来函数。",
        f"- 窗口 `{str(result.get('window', {}).get('start'))}`~`{str(result.get('window', {}).get('end'))}`；"
        f"连板阈值 `>= {_integer(result.get('min_consecutive_boards'))}`；train 前 `{_integer(result.get('train_months'))}` 个月。",
        "",
        "## Coverage",
        "",
        f"- 结算范围：`{str(result.get('start') or '-')}` 至 `{str(result.get('end') or '-')}`。",
        f"- 全部首板：{_integer(coverage.get('first_board_total'))}；9:30-11:00 窗口：{_integer(coverage.get('morning_window_count'))}；"
        f"train：{_integer(coverage.get('train_count'))}；test：{_integer(coverage.get('test_count'))}。",
        f"- 输入指纹：`{str(result.get('input_fingerprint') or '-')}`。",
        "",
        "## Sample Balance",
        "",
        f"- 正样本（连板 >= 阈值）：{_integer(balance.get('positive'))}；"
        f"负样本：{_integer(balance.get('negative'))}；"
        f"正样本率：{_ratio_pct(balance.get('positive_rate'))}。",
        "",
        "## Train Selected Factors (A 组，封板前可观测)",
        "",
        "| 因子 | AUC | 效应强度 | 方向 | 权重 |",
        "|---|---:|---:|---|---:|",
    ]
    for factor, spec in factors.items():
        spec = _mapping(spec)
        lines.append(
            f"| {factor} | {_fmt(spec.get('auc'))} | {_fmt(spec.get('effect_strength'))} | "
            f"{str(spec.get('direction') or '-')} | {_ratio_pct(spec.get('weight'))} |"
        )
    if not factors:
        lines.append("| （无因子达到 train effect 门槛） | - | - | - | - |")
    lines.extend(
        [
            "",
            "## Holdout Validation",
            "",
            f"- test 样本：{_integer(holdout.get('sample_count'))}；正样本：{_integer(holdout.get('positive_count'))}。",
            f"- 评分 AUC：`{_fmt(holdout.get('auc'))}`；基线正样本率：`{_ratio_pct(holdout.get('baseline_rate'))}`。",
            f"- top20% 正样本率：`{_ratio_pct(holdout.get('top20_positive_rate'))}`；"
            f"bottom20%：`{_ratio_pct(holdout.get('bottom20_positive_rate'))}`；lift：`{_fmt(holdout.get('lift'))}`。",
            f"- **锁定状态**：`{'LOCKED' if holdout.get('locked') else 'NOT_LOCKED'}`。",
            f"- **locked 因子**（train 入选 + test 锁定 + 月度稳定）：{', '.join(locked) if locked else '（无）'}。",
            "",
            "## Monthly Stability",
            "",
            "| 因子 | 方向集合 | 是否翻转(unstable) |",
            "|---|---|---|",
        ]
    )
    for factor, spec in stability.items():
        spec = _mapping(spec)
        directions = spec.get("directions") or []
        lines.append(
            f"| {factor} | {','.join(directions) or '-'} | "
            f"{'是' if spec.get('unstable') else '否'} |"
        )
    lines.extend(
        [
            "",
            "## Probability Score Formula",
            "",
            "- 对新首板样本：查每个 locked A 因子所在五分位的正样本率，按 train effect 权重加权平均 = 龙头概率。",
            "- 排序：按龙头概率降序即每日推荐顺序。",
            "- 注意：评分为「封板首板中成龙头的概率」；实盘还需前置「会不会封板」的候选筛选。",
            "",
            "## Group-B Quality Factors (封板时刻质量，仅诊断)",
            "",
        ]
    )
    for key, summary in (result.get("group_b_factor_summary") or {}).items():
        summary = _mapping(summary)
        if "categories" in summary:
            lines.append(f"- `{key}`（分类）：")
            for category in summary.get("categories", []):
                category = _mapping(category)
                lines.append(
                    f"  - {category.get('category')}: 样本 {_integer(category.get('total'))}，"
                    f"正样本率 {_ratio_pct(category.get('positive_rate'))}"
                )
        else:
            lines.append(
                f"- `{key}`: AUC `{_fmt(summary.get('auc'))}`，"
                f"效应 `{_fmt(summary.get('effect_strength'))}`，"
                f"方向 {str(summary.get('direction') or '-')}"
            )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- 本报告为只读概率评分证据，``execution_valid`` 恒为 False，不产出可执行信号，不改变正式门或实时推荐。",
            "- locked 因子仅作研究线索；任何上线须经独立自然前向验证与用户审批。",
            "",
            "## Evidence Boundary",
            "",
            "- JSON 含校准表、holdout 明细与月度明细；Markdown 只显示汇总，避免事后最高被误读为可交易规则。",
            "- 样本仅 13 个月、holdout 约 4 个月，统计功效有限；结论不可外推为全周期普适规律。",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    """Run the read-only morning-window probability study and write evidence files."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--min-consecutive-boards", type=int, default=DEFAULT_MIN_CONSECUTIVE_BOARDS)
    parser.add_argument("--train-months", type=int, default=DEFAULT_TRAIN_MONTHS)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    result = run_research(
        start=arguments.start,
        end=arguments.end,
        min_consecutive_boards=arguments.min_consecutive_boards,
        train_months=arguments.train_months,
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
    number = _to_float(value)
    return f"{number:.4f}" if number is not None else "-"


def _ratio_pct(value: object) -> str:
    number = _to_float(value)
    return f"{number * 100:.2f}%" if number is not None else "-"


def _integer(value: object) -> int:
    number = _to_float(value)
    return int(number) if number is not None else 0


if __name__ == "__main__":
    main()
