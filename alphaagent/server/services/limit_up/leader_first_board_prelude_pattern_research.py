"""首板前奏形态因子研究（小阳爬升/阴跌蓄势 + 量能共振）。

主人假说（2026-08-02）：成功首板（>=2 连板）的前奏有两类形态：

- **A 小阳爬升型**：首板前 2-3 个连续小阳线，每日收盘涨幅控制在 3% 以内
  （0 < change_pct <= 3），温和吸筹爬升。
- **B 阴跌蓄势型**（与 A 相反）：低位首板前连续 2-3 个小阴跌，每日收盘跌幅
  控制在 -3% 以内（-3 <= change_pct < 0），杀跌衰竭蓄势。
- **量能共振**：前奏期之前约 7 个交易日成交量一直平稳，前奏期（小阳/小阴
  那 2-3 天）突然出现量能变化；A/B 两型的量能变化方向预期有区别
  （A 温和放量 / B 缩量）——方向是**待证假说**，研究先做分型描述统计，
  不预设进判定条件。

研究流程（主人指定顺序）：

1. 收集 >=2 连板的首板票样本并去重——复用
   ``build_factor_samples(min_consecutive_boards=2, board_gap_mode="wave")``，
   与深度因子/稳定性研究同一管线（首板识别、wave 切浪、每浪只留首板）。
2. 核对形态命中率（描述性）：成功票里有多少符合 A/B 形态 vs 失败票。
3. 形态/量能特征的预测区分度（AUC + 五分位 + bootstrap CI）。
4. A/B 两型的量能方向差异（mannwhitneyu + P(shift>1)/P(<1)）。
5. 月度一致性（防过拟合：显式列 2026-06 vs 2026-07 方向是否翻转）+
   预登记组合 vs 全样本基线。

窗口口径（固定，不动态对齐，与既有因子同口径可比）：

- 前奏期 = D-3..D-1（与 ``_prior_3d_shape`` 同窗口）。
- 平稳窗口 = D-10..D-4（与 ``turnover_ratio_3d_vs_prev7d`` 分母同窗口）。
- ``prelude_vol_shift_ratio`` 与 ``turnover_ratio_3d_vs_prev7d`` 同口径
  （重复是有意的：盘前/回测单点调用自足），回归测试锁两键相等。

``_prelude_pattern_features`` 是共享纯函数：分钟/扫板回测器与盘前选股服务
直接 import 复用（DRY），全部特征 D-1 可观测、无未来函数。

只读研究脚本：不触碰实时表/API/持仓。``is_leader``/``eventual_peak``/``d1_*``
是未来标签，仅用于对照分组，绝不作为可交易因子。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median, pstdev

from scipy.stats import mannwhitneyu

from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    compare_categorical_factor,
    compare_numeric_factor,
)
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    DAILY_FORWARD_DAYS,
    DAILY_LOOKBACK_DAYS,
    SECTOR_LOOKBACK_DAYS,
    _bool,
    _categorical_outcomes,
    _number,
    _sample_float,
    build_factor_samples,
)
from alphaagent.server.services.limit_up.leader_first_board_factor_stability_research import (
    _month_of,
    collinearity_matrix,
    monthly_factor_stability,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_limit_up_dataset,
    load_sector_daily_bars,
    load_sector_memberships_all,
)

STUDY_VERSION = "leader-first-board-prelude-pattern-v1"

# 形态阈值（主人口径；敏感性档见 SENSITIVITY_MAX_CHANGE_PCTS）
PRELUDE_MAX_CHANGE_PCT = 3.0
PRELUDE_MIN_STREAK = 2
PRELUDE_WINDOW_DAYS = 3  # 前奏期 D-3..D-1
PRELUDE_CALM_WINDOW_DAYS = 7  # 平稳窗口 D-10..D-4
SENSITIVITY_MAX_CHANGE_PCTS = (2.0, 3.0, 4.0)

PRELUDE_NUMERIC_KEYS = (
    "prelude_small_yang_streak",
    "prelude_small_yin_streak",
    "prelude_vol_cv_7d",
    "prelude_vol_shift_ratio",
)

# 共线性对照：新键 vs 预计高相关的既有键
_COLLINEARITY_KEYS = (
    *PRELUDE_NUMERIC_KEYS,
    "return_20d_pct",
    "prior_3d_up_days",
    "prior_3d_cum_return_pct",
    "volume_ratio_5_60",
    "turnover_ratio_3d_vs_prev7d",
)

_RESEARCH_NOTES = (
    "形态阈值（±3%、连续>=2 天、3+7 窗口）来自主人先验，敏感性只做预声明的 2/3/4% 三档，不做网格搜索。",
    "量能阈值与方向条件均为 in-sample 描述统计；进生产硬条件前要求月度一致性 >=0.7 且 2026-06/07 不翻转。",
    "样本窗口 2025-06 起为单边牛+一次崩盘（2026-07），B 阴跌型样本天然偏小，结论带 n 与 CI，不达标即证据不足。",
    "is_leader/eventual_peak/d1_* 是未来标签，仅用于对照分组；全部形态/量能特征 D-1 收盘前可观测。",
    "prelude_vol_shift_ratio 与既有 turnover_ratio_3d_vs_prev7d 同口径（有意的冗余，测试锁相等）。",
)


# ── 共享纯函数：前奏形态 + 量能特征（回测器/盘前服务复用）──────────────────


def _prelude_pattern_features(
    bars_before: Sequence[Mapping[str, object]],
    *,
    max_change_pct: float = PRELUDE_MAX_CHANGE_PCT,
    min_streak: int = PRELUDE_MIN_STREAK,
) -> dict[str, object]:
    """首板前奏形态与量能特征（全部 D-1 可观测）。

    ``bars_before`` = D-1 及之前的日线（升序）。streak 从 D-1 向前数、
    最多数 ``PRELUDE_WINDOW_DAYS`` 天；change_pct==0 或缺失打断两型。
    """

    out: dict[str, object] = {
        "prelude_small_yang_streak": 0,
        "prelude_small_yin_streak": 0,
        "prelude_pattern": "none",
        "prelude_vol_cv_7d": None,
        "prelude_vol_shift_ratio": None,
    }
    window = list(bars_before[-PRELUDE_WINDOW_DAYS:])  # D-3..D-1
    changes = [_number(row.get("change_pct")) for row in window]
    yang_streak = 0
    for change in reversed(changes):  # D-1 → D-3
        if change is not None and 0 < change <= max_change_pct:
            yang_streak += 1
        else:
            break
    yin_streak = 0
    for change in reversed(changes):
        if change is not None and -max_change_pct <= change < 0:
            yin_streak += 1
        else:
            break
    out["prelude_small_yang_streak"] = yang_streak
    out["prelude_small_yin_streak"] = yin_streak
    if yang_streak >= min_streak:
        out["prelude_pattern"] = "small_yang"
    elif yin_streak >= min_streak:
        out["prelude_pattern"] = "small_yin"

    if len(bars_before) < PRELUDE_WINDOW_DAYS + PRELUDE_CALM_WINDOW_DAYS:
        return out
    calm = [
        value
        for value in (
            _number(row.get("turnover"))
            for row in bars_before[-(PRELUDE_WINDOW_DAYS + PRELUDE_CALM_WINDOW_DAYS) : -PRELUDE_WINDOW_DAYS]
        )
        if value is not None
    ]
    prelude = [
        value
        for value in (_number(row.get("turnover")) for row in bars_before[-PRELUDE_WINDOW_DAYS:])
        if value is not None
    ]
    if len(calm) >= 5 and mean(calm) > 0:
        out["prelude_vol_cv_7d"] = round(pstdev(calm) / mean(calm), 4)
    # 与 turnover_ratio_3d_vs_prev7d 同口径：两侧非空即算（测试锁相等）
    if calm and prelude and mean(calm) > 0:
        out["prelude_vol_shift_ratio"] = round(mean(prelude) / mean(calm), 4)
    return out


def attach_prelude_features(
    factor_samples: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    *,
    max_change_pct: float = PRELUDE_MAX_CHANGE_PCT,
) -> list[dict[str, object]]:
    """给 build_factor_samples 的因子样本追加前奏形态特征（后处理，不重写样本抽取）。"""

    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    dates_by_symbol: dict[str, list[str]] = {}
    for symbol, rows in bars_by_symbol.items():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
        dates_by_symbol[symbol] = [str(row.get("trade_date") or "") for row in rows]

    attached: list[dict[str, object]] = []
    for sample in factor_samples:
        symbol = str(sample.get("vt_symbol") or "")
        trade_date = str(sample.get("trade_date") or "")
        rows = bars_by_symbol.get(symbol, [])
        dates = dates_by_symbol.get(symbol, [])
        d_index = bisect_left(dates, trade_date)
        merged = dict(sample)
        merged.update(
            _prelude_pattern_features(rows[:d_index], max_change_pct=max_change_pct)
        )
        attached.append(merged)
    return attached


# ── 分析块 1：形态命中率（描述性，验证主人观察覆盖率）─────────────────────


def _pattern_hit_rates(
    samples: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """P(pattern | is_leader=True) vs P(pattern | False)，分型 A/B/any。"""

    leaders = [sample for sample in samples if _bool(sample.get("is_leader"))]
    non_leaders = [sample for sample in samples if not _bool(sample.get("is_leader"))]
    rows: list[dict[str, object]] = []
    for pattern in ("small_yang", "small_yin", "any"):
        row: dict[str, object] = {"pattern": pattern}
        for group_name, group in (("leader", leaders), ("non_leader", non_leaders)):
            if pattern == "any":
                hits = sum(
                    1
                    for sample in group
                    if sample.get("prelude_pattern") in ("small_yang", "small_yin")
                )
            else:
                hits = sum(1 for sample in group if sample.get("prelude_pattern") == pattern)
            row[f"{group_name}_total"] = len(group)
            row[f"{group_name}_hits"] = hits
            row[f"{group_name}_hit_rate"] = round(hits / len(group), 4) if group else None
        leader_rate = row.get("leader_hit_rate")
        non_leader_rate = row.get("non_leader_hit_rate")
        row["rate_ratio"] = (
            round(float(leader_rate) / float(non_leader_rate), 4)
            if leader_rate is not None and non_leader_rate
            else None
        )
        rows.append(row)
    return rows


# ── 分析块 3：A/B 量能方向差异（主人「还是有区别的」假说）──────────────────


def _volume_shift_by_pattern(
    samples: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """按形态分组的量能突变比分布 + A vs B 秩和检验 + × is_leader 交叉。"""

    def _stats(members: Sequence[Mapping[str, object]]) -> dict[str, object]:
        shifts = [
            value
            for value in (_sample_float(sample.get("prelude_vol_shift_ratio")) for sample in members)
            if value is not None
        ]
        return {
            "total": len(members),
            "valid": len(shifts),
            "shift_median": round(median(shifts), 4) if shifts else None,
            "shift_mean": round(mean(shifts), 4) if shifts else None,
            "prob_expand": round(sum(1 for value in shifts if value > 1.0) / len(shifts), 4)
            if shifts
            else None,
            "prob_shrink": round(sum(1 for value in shifts if value < 1.0) / len(shifts), 4)
            if shifts
            else None,
        }

    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for sample in samples:
        groups[str(sample.get("prelude_pattern") or "none")].append(sample)

    by_pattern: dict[str, object] = {}
    for pattern in ("small_yang", "small_yin", "none"):
        members = groups.get(pattern, [])
        by_pattern[pattern] = {
            **_stats(members),
            "leader": _stats([sample for sample in members if _bool(sample.get("is_leader"))]),
            "non_leader": _stats(
                [sample for sample in members if not _bool(sample.get("is_leader"))]
            ),
        }

    yang_shifts = [
        value
        for value in (
            _sample_float(sample.get("prelude_vol_shift_ratio"))
            for sample in groups.get("small_yang", [])
        )
        if value is not None
    ]
    yin_shifts = [
        value
        for value in (
            _sample_float(sample.get("prelude_vol_shift_ratio"))
            for sample in groups.get("small_yin", [])
        )
        if value is not None
    ]
    test: dict[str, object] = {"statistic": None, "p_value": None, "note": "样本不足"}
    if len(yang_shifts) >= 20 and len(yin_shifts) >= 20:
        result = mannwhitneyu(yang_shifts, yin_shifts, alternative="greater")
        test = {
            "statistic": round(float(result.statistic), 2),
            "p_value": round(float(result.pvalue), 6),
            "note": "H1: A 小阳组的 shift 大于 B 小阴组（A 放量 / B 缩量方向）",
        }
    return {"by_pattern": by_pattern, "yang_vs_yin_mannwhitney": test}


# ── 分析块 5：预登记组合 vs 全样本基线 ─────────────────────────────────────


def _prelude_combo_rows(
    samples: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """先验组合（非事后搜索）：形态、形态+量稳、形态+量稳+方向、形态+低位。"""

    cv_values = sorted(
        value
        for value in (_sample_float(sample.get("prelude_vol_cv_7d")) for sample in samples)
        if value is not None
    )
    cv_median = median(cv_values) if cv_values else None

    def _is_pattern(sample: Mapping[str, object], pattern: str) -> bool:
        if pattern == "any":
            return sample.get("prelude_pattern") in ("small_yang", "small_yin")
        return sample.get("prelude_pattern") == pattern

    def _calm(sample: Mapping[str, object]) -> bool:
        value = _sample_float(sample.get("prelude_vol_cv_7d"))
        return cv_median is not None and value is not None and value <= cv_median

    definitions: list[tuple[str, str, object]] = [
        (
            "prelude_any",
            "前奏形态任一（A 小阳或 B 小阴，连续>=2 天 ±3% 以内）",
            lambda s: _is_pattern(s, "any"),
        ),
        (
            "prelude_a_calm",
            "A 小阳 + 前 7 日量稳（cv <= 全样本中位数）",
            lambda s: _is_pattern(s, "small_yang") and _calm(s),
        ),
        (
            "prelude_b_calm",
            "B 小阴 + 前 7 日量稳（cv <= 全样本中位数）",
            lambda s: _is_pattern(s, "small_yin") and _calm(s),
        ),
        (
            "prelude_a_calm_expand",
            "A 小阳 + 量稳 + 前奏放量（shift>1，主人方向假说）",
            lambda s: _is_pattern(s, "small_yang")
            and _calm(s)
            and (_sample_float(s.get("prelude_vol_shift_ratio")) or 0.0) > 1.0,
        ),
        (
            "prelude_b_calm_shrink",
            "B 小阴 + 量稳 + 前奏缩量（shift<1，主人方向假说）",
            lambda s: _is_pattern(s, "small_yin")
            and _calm(s)
            and (_sample_float(s.get("prelude_vol_shift_ratio")) or 999.0) < 1.0,
        ),
        (
            "prelude_any_low_position",
            "任一形态 + 低位（return_20d_pct <= 10）",
            lambda s: _is_pattern(s, "any")
            and (_sample_float(s.get("return_20d_pct")) or 999.0) <= 10.0,
        ),
    ]

    def _stats(members: Sequence[Mapping[str, object]]) -> dict[str, object]:
        leaders = sum(1 for sample in members if _bool(sample.get("is_leader")))
        d1_returns = [
            value
            for value in (_number(sample.get("d1_open_return_pct")) for sample in members)
            if value is not None
        ]
        return {
            "total": len(members),
            "leader_count": leaders,
            "leader_rate": round(leaders / len(members), 4) if members else None,
            "d1_open_return_mean": round(mean(d1_returns), 4) if d1_returns else None,
            "d1_open_win_rate": round(
                sum(1 for value in d1_returns if value > 0) / len(d1_returns), 4
            )
            if d1_returns
            else None,
        }

    rows: list[dict[str, object]] = [
        {"combo": "__baseline__", "description": "全样本基线", **_stats(samples)}
    ]
    for name, description, predicate in definitions:
        members = [sample for sample in samples if predicate(sample)]
        rows.append({"combo": name, "description": description, **_stats(members)})
    for row in rows:
        row["cv_median_used"] = round(cv_median, 4) if cv_median is not None else None
    return rows


# ── 敏感性（预声明 2/3/4% 三档，不网格搜索）────────────────────────────────


def _sensitivity_rows(
    samples: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """max_change_pct 三档下的形态覆盖率与形态组 >=2 板率（对照全样本基线）。"""

    baseline_rate = (
        sum(1 for sample in samples if _bool(sample.get("is_leader"))) / len(samples)
        if samples
        else None
    )
    rows: list[dict[str, object]] = []
    for threshold in SENSITIVITY_MAX_CHANGE_PCTS:
        attached = attach_prelude_features(samples, daily_bars, max_change_pct=threshold)
        matched = [
            sample
            for sample in attached
            if sample.get("prelude_pattern") in ("small_yang", "small_yin")
        ]
        leaders = sum(1 for sample in matched if _bool(sample.get("is_leader")))
        rows.append(
            {
                "max_change_pct": threshold,
                "matched": len(matched),
                "coverage": round(len(matched) / len(samples), 4) if samples else None,
                "leader_count": leaders,
                "leader_rate": round(leaders / len(matched), 4) if matched else None,
                "baseline_leader_rate": round(baseline_rate, 4)
                if baseline_rate is not None
                else None,
            }
        )
    return rows


# ── 月度一致性补充：2026-06 vs 2026-07 方向显式对照（MA20 教训）─────────────


def _june_july_check(
    monthly_reports: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """从 monthly_factor_stability 结果里提取 6/7 月方向，标翻转。"""

    rows: list[dict[str, object]] = []
    for report in monthly_reports:
        months = {
            str(item.get("month")): item for item in (report.get("months") or [])
        }
        june = months.get("2026-06") or {}
        july = months.get("2026-07") or {}
        june_direction = str(june.get("direction") or "skip")
        july_direction = str(july.get("direction") or "skip")
        flipped = (
            june_direction not in ("skip", "flat")
            and july_direction not in ("skip", "flat")
            and june_direction != july_direction
        )
        rows.append(
            {
                "factor_key": report.get("factor_key"),
                "june_auc": june.get("auc"),
                "june_direction": june_direction,
                "july_auc": july.get("auc"),
                "july_direction": july_direction,
                "flipped": flipped,
            }
        )
    return rows


def _monthly_pattern_rates(
    samples: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """prelude_pattern 分类因子逐月 >=2 板率（categorical 的月度一致性）。"""

    by_month: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for sample in samples:
        by_month[_month_of(sample)].append(sample)
    rows: list[dict[str, object]] = []
    for month in sorted(by_month):
        members = by_month[month]
        row: dict[str, object] = {"month": month, "total": len(members)}
        for pattern in ("small_yang", "small_yin"):
            group = [sample for sample in members if sample.get("prelude_pattern") == pattern]
            leaders = sum(1 for sample in group if _bool(sample.get("is_leader")))
            row[f"{pattern}_total"] = len(group)
            row[f"{pattern}_leader_rate"] = (
                round(leaders / len(group), 4) if group else None
            )
        rows.append(row)
    return rows


# ── 报告编排 ──────────────────────────────────────────────────────────────


def build_prelude_pattern_report(
    events: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[str],
    memberships: Sequence[Mapping[str, object]],
    sector_bars: Sequence[Mapping[str, object]],
    *,
    min_consecutive_boards: int = 2,
    board_gap_mode: str = "wave",
) -> dict[str, object]:
    """编排前奏形态研究（纯函数，不连数据库）。"""

    _, factor_samples = build_factor_samples(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
        min_consecutive_boards=min_consecutive_boards,
        board_gap_mode=board_gap_mode,
    )
    samples = attach_prelude_features(factor_samples, daily_bars)

    numeric_reports = [
        compare_numeric_factor(samples, key) for key in PRELUDE_NUMERIC_KEYS
    ]
    monthly_reports = [
        monthly_factor_stability(samples, key) for key in PRELUDE_NUMERIC_KEYS
    ]

    positive = sum(1 for sample in samples if _bool(sample.get("is_leader")))
    return {
        "status": "ok" if samples else "insufficient_data",
        "study_version": STUDY_VERSION,
        "min_consecutive_boards": min_consecutive_boards,
        "board_gap_mode": board_gap_mode,
        "thresholds": {
            "max_change_pct": PRELUDE_MAX_CHANGE_PCT,
            "min_streak": PRELUDE_MIN_STREAK,
            "prelude_window_days": PRELUDE_WINDOW_DAYS,
            "calm_window_days": PRELUDE_CALM_WINDOW_DAYS,
        },
        "first_board_count": len(samples),
        "label_balance": {
            "positive": positive,
            "negative": len(samples) - positive,
            "positive_rate": round(positive / len(samples), 4) if samples else None,
        },
        "hit_rates": _pattern_hit_rates(samples),
        "numeric_factors": numeric_reports,
        "pattern_categorical": compare_categorical_factor(samples, "prelude_pattern"),
        "pattern_outcomes": _categorical_outcomes(samples, "prelude_pattern"),
        "volume_shift_by_pattern": _volume_shift_by_pattern(samples),
        "monthly_stability": monthly_reports,
        "june_july_check": _june_july_check(monthly_reports),
        "monthly_pattern_rates": _monthly_pattern_rates(samples),
        "combos": _prelude_combo_rows(samples),
        "sensitivity": _sensitivity_rows(samples, daily_bars),
        "collinearity": collinearity_matrix(samples, _COLLINEARITY_KEYS),
        "notes": list(_RESEARCH_NOTES),
    }


def run_research(*, start: date, end: date) -> dict[str, object]:
    """加载冻结数据集并返回前奏形态研究报告。"""

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
    report = build_prelude_pattern_report(
        events,
        daily_bars,
        calendar,
        memberships,
        sector_bars,
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


# ── Markdown 渲染 ─────────────────────────────────────────────────────────


def _fmt(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _pct(value: object) -> str:
    return f"{float(value) * 100:.2f}%" if value is not None else "-"


def render_markdown(result: Mapping[str, object]) -> str:
    """渲染前奏形态研究证据报告。"""

    balance = result.get("label_balance") or {}
    thresholds = result.get("thresholds") or {}
    lines = [
        "# 首板前奏形态因子研究（小阳爬升 / 阴跌蓄势 + 量能共振）",
        "",
        "## Boundary",
        "",
        f"- 状态：`{result.get('status') or 'unavailable'}`；研究版本 `{result.get('study_version') or '-'}`。",
        "- 只读 `stock_events`/`stock_daily_bars`/板块数据，不触碰任何实时链路。",
        "- `is_leader`/`eventual_peak`/`d1_*` 是未来标签，仅用于对照分组。",
        f"- 成功标签：连板 >= {result.get('min_consecutive_boards')} 板（{result.get('board_gap_mode')} 切浪，每浪只留首板）。",
        f"- 形态口径：连续 >= {thresholds.get('min_streak')} 天、每日涨/跌幅 <= {thresholds.get('max_change_pct')}%；"
        f"前奏窗口 D-3..D-1，平稳窗口 D-10..D-4。",
        "",
        "## Sample Balance",
        "",
        f"- 结算范围：`{result.get('start') or '-'}` 至 `{result.get('end') or '-'}`。",
        f"- 首板样本：{result.get('first_board_count')} 个；输入指纹 `{result.get('input_fingerprint') or '-'}`。",
        f"- 正样本（>=2 板）：{balance.get('positive')}；负样本：{balance.get('negative')}；"
        f"基线 >=2 板率：{_pct(balance.get('positive_rate'))}。",
        "",
        "## ① 形态命中率（主人观察覆盖率：成功票 vs 失败票）",
        "",
        "| 形态 | 成功票数 | 成功组命中率 | 失败票数 | 失败组命中率 | 命中比 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result.get("hit_rates") or []:
        lines.append(
            f"| {row.get('pattern')} | {row.get('leader_hits')}/{row.get('leader_total')} | "
            f"{_pct(row.get('leader_hit_rate'))} | {row.get('non_leader_hits')}/{row.get('non_leader_total')} | "
            f"{_pct(row.get('non_leader_hit_rate'))} | {_fmt(row.get('rate_ratio'))} |"
        )
    lines.extend(
        [
            "",
            "## ② 预测区分度（>=2 板标签 AUC + 五分位）",
            "",
            "| 因子 | 样本 | 正均值 | 负均值 | AUC | 方向 | 均值差 95%CI |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for item in result.get("numeric_factors") or []:
        ci = f"[{_fmt(item.get('mean_delta_lower_95'))}, {_fmt(item.get('mean_delta_upper_95'))}]"
        lines.append(
            f"| {item.get('factor_key')} | {item.get('sample_count')} | "
            f"{_fmt(item.get('positive_mean'))} | {_fmt(item.get('negative_mean'))} | "
            f"{_fmt(item.get('auc'))} | {item.get('direction')} | {ci} |"
        )
    outcomes = (result.get("pattern_outcomes") or {}).get("categories") or []
    if outcomes:
        lines.extend(
            [
                "",
                "### 形态分类结局（>=2 板率 + D+1 开盘收益）",
                "",
                "| 形态 | 样本 | >=2 板率 | D+1 开盘均收益 | D+1 胜率 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for item in outcomes:
            lines.append(
                f"| {item.get('category')} | {item.get('total')} | "
                f"{_pct(item.get('leader_rate'))} | {_fmt(item.get('d1_open_return_mean'))} | "
                f"{_pct(item.get('d1_open_win_rate'))} |"
            )
    volume = result.get("volume_shift_by_pattern") or {}
    by_pattern = volume.get("by_pattern") or {}
    if by_pattern:
        lines.extend(
            [
                "",
                "## ③ A/B 量能方向差异（主人「还是有区别的」假说）",
                "",
                "| 形态 | 组 | 样本 | shift 中位数 | P(放量>1) | P(缩量<1) |",
                "|---|---|---:|---:|---:|---:|",
            ]
        )
        for pattern in ("small_yang", "small_yin", "none"):
            stats = by_pattern.get(pattern) or {}
            for group_name, label in (("leader", "成功"), ("non_leader", "失败")):
                group = stats.get(group_name) or {}
                lines.append(
                    f"| {pattern} | {label} | {group.get('valid', 0)} | "
                    f"{_fmt(group.get('shift_median'))} | {_pct(group.get('prob_expand'))} | "
                    f"{_pct(group.get('prob_shrink'))} |"
                )
        test = volume.get("yang_vs_yin_mannwhitney") or {}
        lines.append(
            f"- A vs B 秩和检验：statistic={_fmt(test.get('statistic'))}，"
            f"p={_fmt(test.get('p_value'))}（{test.get('note') or '-'}）。"
        )
    lines.extend(
        [
            "",
            "## ④ 月度一致性（防过拟合：显式 2026-06 vs 2026-07 方向对照）",
            "",
            "| 因子 | 全样本 AUC | 月度一致率 | 6 月 AUC/方向 | 7 月 AUC/方向 | 翻转 |",
            "|---|---:|---:|---|---|---|",
        ]
    )
    monthly_by_key = {
        str(item.get("factor_key")): item for item in result.get("monthly_stability") or []
    }
    for check in result.get("june_july_check") or []:
        report = monthly_by_key.get(str(check.get("factor_key"))) or {}
        lines.append(
            f"| {check.get('factor_key')} | {_fmt(report.get('full_auc'))} | "
            f"{_fmt(report.get('monthly_agreement'))} | "
            f"{_fmt(check.get('june_auc'))}/{check.get('june_direction')} | "
            f"{_fmt(check.get('july_auc'))}/{check.get('july_direction')} | "
            f"{'⚠️ 翻转' if check.get('flipped') else '一致'} |"
        )
    combos = result.get("combos") or []
    if combos:
        lines.extend(
            [
                "",
                "## ⑤ 预登记组合 vs 基线（先验设定，非事后搜索）",
                "",
                "| 组合 | 说明 | 样本 | >=2 板数 | >=2 板率 | D+1 开盘均收益 | D+1 胜率 |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in combos:
            lines.append(
                f"| {row.get('combo')} | {row.get('description')} | {row.get('total')} | "
                f"{row.get('leader_count')} | {_pct(row.get('leader_rate'))} | "
                f"{_fmt(row.get('d1_open_return_mean'))} | {_pct(row.get('d1_open_win_rate'))} |"
            )
    sensitivity = result.get("sensitivity") or []
    if sensitivity:
        lines.extend(
            [
                "",
                "## 敏感性（预声明 2/3/4% 三档，不挑最优）",
                "",
                "| 单日幅度上限 | 形态命中数 | 覆盖率 | 形态组 >=2 板率 | 基线 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for row in sensitivity:
            lines.append(
                f"| ±{row.get('max_change_pct')}% | {row.get('matched')} | "
                f"{_pct(row.get('coverage'))} | {_pct(row.get('leader_rate'))} | "
                f"{_pct(row.get('baseline_leader_rate'))} |"
            )
    collinearity = result.get("collinearity") or []
    high_pairs = [pair for pair in collinearity if abs(pair.get("spearman") or 0.0) >= 0.7]
    if high_pairs:
        lines.extend(
            [
                "",
                "## 共线性（|rho|>=0.7 的因子对）",
                "",
                "| 左 | 右 | Spearman | 样本 |",
                "|---|---|---:|---:|",
            ]
        )
        for pair in high_pairs:
            lines.append(
                f"| {pair.get('left')} | {pair.get('right')} | "
                f"{_fmt(pair.get('spearman'))} | {pair.get('sample_count')} |"
            )
    lines.extend(["", "## Notes", ""])
    for note in result.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="首板前奏形态因子研究（小阳/阴跌+量能）")
    parser.add_argument("--start", required=True, help="样本窗口起点（ISO 日期）")
    parser.add_argument("--end", required=True, help="样本窗口终点（ISO 日期）")
    parser.add_argument("--json-output", required=True, help="JSON 证据输出路径")
    parser.add_argument("--markdown-output", required=True, help="Markdown 报告输出路径")
    arguments = parser.parse_args(argv)

    report = run_research(
        start=date.fromisoformat(arguments.start),
        end=date.fromisoformat(arguments.end),
    )
    json_path = Path(arguments.json_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    markdown_path = Path(arguments.markdown_output)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(
        f"prelude-pattern research: status={report['status']} "
        f"samples={report['first_board_count']} "
        f"positive_rate={(report.get('label_balance') or {}).get('positive_rate')}"
    )


if __name__ == "__main__":
    main()
