"""Evaluate the point-in-time quality fields used by the formal A+B contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pandas as pd

from alphaagent.server.services.limit_up.capital_mainline_contract import (
    validate_asof_fields,
)
from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    extract_formal_recommendations,
    monthly_summaries,
    performance_summary,
)
from alphaagent.server.services.limit_up.first_board_stock_gene_research import (
    attach_prior_stock_gene_evidence_to_orders,
)
from alphaagent.server.services.limit_up.scheduled_execution import (
    extract_scheduled_orders,
    filter_profitability_qualified_orders,
)
from alphaagent.server.services.limit_up.versions import CORE_ABC_STRATEGY_VERSION


STUDY_VERSION = "limit-up-quality-reconstruction-v1"
CORE_RULE_VERSION = "recognition-capacity-expansion-v1"
COVERAGE_RULE_VERSION = "recognition-2-to-6-v1"
NATURAL_FORWARD_START = date(2026, 7, 27)
MINIMUM_PRIOR_LIMIT_COUNT_126 = 2
MAXIMUM_PRIOR_LIMIT_COUNT_126 = 6
MINIMUM_PRIOR_INDUSTRY_TURNOVER_RATIO_5D = 1.0
QUALITY_FIELDS = (
    "prior_limit_count_126",
    "prior_industry_turnover_ratio_5d",
)
TIME_SLICES = (
    ("2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("2026_01_02", date(2026, 1, 1), date(2026, 2, 28)),
    ("2026_03_07", date(2026, 3, 1), date(2026, 7, 31)),
)


def build_quality_reconstruction_frame(
    days: Sequence[Mapping[str, object]],
    *,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Preserve the raw D-1 fields beside formal independent-slot returns."""

    formal = extract_formal_recommendations(days, start=start, end=end)
    if formal.empty:
        return formal
    orders = extract_scheduled_orders(days)
    enriched = attach_prior_stock_gene_evidence_to_orders(days, orders)
    qualified, _ = filter_profitability_qualified_orders(enriched)
    return attach_quality_fields(formal, qualified)


def attach_quality_fields(
    formal: pd.DataFrame,
    qualified_orders: Sequence[Mapping[str, object]],
) -> pd.DataFrame:
    """Join only signal-time quality evidence by formal order identity."""

    if formal.empty:
        return formal.copy()
    lookup: dict[tuple[date, str], Mapping[str, object]] = {}
    for order in qualified_orders:
        identity = _candidate_identity(order)
        if identity is not None:
            lookup.setdefault(identity, order)

    records: list[dict[str, object]] = []
    missing: list[str] = []
    for candidate in formal.to_dict("records"):
        identity = _candidate_identity(candidate)
        raw = lookup.get(identity) if identity is not None else None
        if raw is None:
            missing.append(f"{candidate.get('trade_date')}:{candidate.get('vt_symbol')}")
            continue
        records.append(
            {
                **candidate,
                **{field: raw.get(field) for field in QUALITY_FIELDS},
            }
        )
    if missing:
        preview = ", ".join(missing[:5])
        raise ValueError(f"formal quality evidence missing for {len(missing)} rows: {preview}")
    validate_asof_fields(QUALITY_FIELDS)
    return pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "signal_time", "pool_rank", "vt_symbol"]
    ).reset_index(drop=True)


def quality_rule_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Return the fixed ablation masks without consulting outcomes."""

    limit_count = pd.to_numeric(
        frame.get("prior_limit_count_126"), errors="coerce"
    )
    industry_turnover = pd.to_numeric(
        frame.get("prior_industry_turnover_ratio_5d"), errors="coerce"
    )
    recognition = limit_count.between(
        MINIMUM_PRIOR_LIMIT_COUNT_126,
        MAXIMUM_PRIOR_LIMIT_COUNT_126,
    )
    expansion = industry_turnover.ge(
        MINIMUM_PRIOR_INDUSTRY_TURNOVER_RATIO_5D
    )
    return {
        "formal_baseline": pd.Series(True, index=frame.index),
        "recognition_2_to_6": recognition,
        "industry_turnover_expansion": expansion,
        "recognition_and_industry_expansion": recognition & expansion,
    }


def select_quality_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the frozen reconstruction candidate without ranking or Top-N."""

    mask = quality_rule_masks(frame)["recognition_and_industry_expansion"]
    return frame.loc[mask.fillna(False)].copy().reset_index(drop=True)


def select_coverage_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the final full-coverage rule while retaining expansion as a tier."""

    mask = quality_rule_masks(frame)["recognition_2_to_6"]
    selected = frame.loc[mask.fillna(False)].copy()
    expansion = quality_rule_masks(selected)["industry_turnover_expansion"]
    selected["quality_priority_tier"] = expansion.map(
        {True: "A_industry_expanding", False: "B_recognition_only"}
    )
    return selected.reset_index(drop=True)


def evaluate_quality_reconstruction(frame: pd.DataFrame) -> dict[str, object]:
    """Evaluate the fixed masks on every formal recommendation."""

    if frame.empty:
        return {}
    baseline_count = int(
        pd.to_numeric(frame.get("return_pct"), errors="coerce").notna().sum()
    )
    factors: dict[str, object] = {}
    for name, mask in quality_rule_masks(frame).items():
        selected = frame.loc[mask.fillna(False)]
        factors[name] = {
            "full": performance_summary(selected, baseline_count=baseline_count),
            "time_slices": {
                label: performance_summary(
                    selected.loc[
                        pd.to_datetime(selected["trade_date"]).dt.date.between(
                            start,
                            end,
                        )
                    ],
                    baseline_count=baseline_count,
                )
                for label, start, end in TIME_SLICES
            },
            "monthly": monthly_summaries(selected),
            "lanes": {
                str(lane): performance_summary(rows, baseline_count=baseline_count)
                for lane, rows in selected.groupby("lane", sort=True)
            },
        }

    return {
        "study_version": STUDY_VERSION,
        "rule_version": CORE_RULE_VERSION,
        "factors": factors,
    }


def render_quality_reconstruction_report(
    frame: pd.DataFrame,
    evaluation: Mapping[str, object],
    *,
    start: date,
    end: date,
) -> str:
    """Render the replay, root cause boundary, and executable rule contract."""

    factors = _mapping(evaluation.get("factors"))
    core = _mapping(factors.get("recognition_and_industry_expansion"))
    core_full = _mapping(core.get("full"))
    coverage_rule = _mapping(factors.get("recognition_2_to_6"))
    coverage_full = _mapping(coverage_rule.get("full"))
    baseline_full = _mapping(_mapping(factors.get("formal_baseline")).get("full"))
    selected = select_quality_candidates(frame)
    coverage_selected = select_coverage_candidates(frame)
    tier_summaries = {
        str(tier): performance_summary(rows, baseline_count=len(frame))
        for tier, rows in coverage_selected.groupby("quality_priority_tier", sort=True)
    }
    formal_start = min(frame["trade_date"]) if not frame.empty else None
    formal_end = max(frame["trade_date"]) if not frame.empty else None
    lines = [
        "# AlphaAgent 打板质量重建与早期扩散底座",
        "",
        "## Current state",
        "",
        f"- 研究版本：`{STUDY_VERSION}`；正式合同：`{CORE_ABC_STRATEGY_VERSION}`；行情背景区间 `{start}..{end}`。",
        f"- 正式推荐实际覆盖 `{formal_start}..{formal_end}`，不是从行情背景起点持续出单；当前闭合母池 {int(baseline_full.get('closed_count') or 0)} 笔。",
        "- 财报补齐后的正确正式质量门保持不变；本研究只在其全量正式推荐之上增加两个 D-1 字段。",
        f"- 全量覆盖规则：`{MINIMUM_PRIOR_LIMIT_COUNT_126} <= prior_limit_count_126 <= {MAXIMUM_PRIOR_LIMIT_COUNT_126}`；行业量能只区分 A/B 优先级。",
        f"- A 级规则额外要求 `prior_industry_turnover_ratio_5d >= {MINIMUM_PRIOR_INDUSTRY_TURNOVER_RATIO_5D:.1f}`。",
        "- 股票名、概念名和本地财报覆盖身份都不进入规则；不读取分钟数据。",
        f"- 归档状态：该发现已进入 `{CORE_ABC_STRATEGY_VERSION}` 的 A+B 基座；全量覆盖历史为 {int(coverage_full.get('win_count') or 0)}/"
        f"{int(coverage_full.get('closed_count') or 0)}={_fmt(coverage_full.get('win_rate_pct'))}%；其中 A 级为 {int(core_full.get('win_count') or 0)}/"
        f"{int(core_full.get('closed_count') or 0)}={_fmt(core_full.get('win_rate_pct'))}%。当前状态为 `historical_pass_forward_not_passed`。",
        "",
        "## Root cause answer",
        "",
        "- 修复前财报覆盖不是随机缺失。旧同步优先覆盖持续高关注、高资金承载股票，本地有财报因而变成隐性粘性白名单。",
        "- 正确补齐后，新进入母池的股票缺少这种持续辨识度与板块资金承接，导致全量胜率下降；正确归母同比本身仍是正因子。",
        "- `2-6` 次半年涨停表达“已有市场记忆但尚未反复透支”；行业 D-1 成交额不低于前 5 日基准表达“资金开始向所属板块扩张”。",
        "- 这两个字段重建的是旧覆盖的经济含义，不恢复错误的缺财报拒绝，也不使用静态最高成交额追拥挤股。",
        "",
        "## Fixed ablation",
        "",
        "| 规则 | 闭合 | 胜/负 | 胜率 | 平均净收益 | 复利 | 最大回撤 | 硬亏率 | 保留率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "formal_baseline": "修复后正式全量",
        "recognition_2_to_6": "半年涨停 2-6 次",
        "industry_turnover_expansion": "D-1 行业成交额扩张",
        "recognition_and_industry_expansion": "两者交叉",
    }
    for name in labels:
        summary = _mapping(_mapping(factors.get(name)).get("full"))
        count = int(summary.get("closed_count") or 0)
        wins = int(summary.get("win_count") or 0)
        lines.append(
            f"| {labels[name]} | {count} | {wins}/{count - wins} | {_fmt(summary.get('win_rate_pct'))}% | "
            f"{_signed(summary.get('average_return_pct'))}% | {_signed(summary.get('daily_equal_weight_compounded_pct'))}% | "
            f"{_signed(summary.get('maximum_drawdown_pct'))}% | {_fmt(summary.get('hard_loss_rate_pct'))}% | "
            f"{_fmt(summary.get('retention_pct'))}% |"
        )

    lines.extend(
        [
            "",
            "## Priority tiers",
            "",
            "| 层级 | 闭合 | 胜/负 | 胜率 | 平均净收益 | 最大回撤 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for tier, label in (
        ("A_industry_expanding", "A：2-6次且行业量能扩张"),
        ("B_recognition_only", "B：2-6次但行业量能未扩张"),
    ):
        summary = _mapping(tier_summaries.get(tier))
        count = int(summary.get("closed_count") or 0)
        wins = int(summary.get("win_count") or 0)
        lines.append(
            f"| {label} | {count} | {wins}/{count - wins} | {_fmt(summary.get('win_rate_pct'))}% | "
            f"{_signed(summary.get('average_return_pct'))}% | {_signed(summary.get('maximum_drawdown_pct'))}% |"
        )

    lines.extend(
        [
            "",
            "## Time stability",
            "",
            "| 规则 | 分段 | 闭合 | 胜/负 | 胜率 | 平均净收益 | 最大回撤 | 硬亏率 |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rule, rule_label in ((coverage_rule, "全量2-6"), (core, "A级")):
        for label, _, _ in TIME_SLICES:
            summary = _mapping(_mapping(rule.get("time_slices")).get(label))
            count = int(summary.get("closed_count") or 0)
            wins = int(summary.get("win_count") or 0)
            lines.append(
                f"| {rule_label} | {label} | {count} | {wins}/{count - wins} | {_fmt(summary.get('win_rate_pct'))}% | "
                f"{_signed(summary.get('average_return_pct'))}% | {_signed(summary.get('maximum_drawdown_pct'))}% | "
                f"{_fmt(summary.get('hard_loss_rate_pct'))}% |"
            )

    lines.extend(
        [
            "",
            "## Monthly and lane audit",
            "",
            "| 分组 | 闭合 | 胜/负 | 胜率 | 平均净收益 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for month, summary_value in _mapping(coverage_rule.get("monthly")).items():
        summary = _mapping(summary_value)
        count = int(summary.get("closed_count") or 0)
        wins = int(summary.get("win_count") or 0)
        lines.append(
            f"| 月份 {month} | {count} | {wins}/{count - wins} | {_fmt(summary.get('win_rate_pct'))}% | "
            f"{_signed(summary.get('average_return_pct'))}% |"
        )
    for lane, summary_value in _mapping(coverage_rule.get("lanes")).items():
        summary = _mapping(summary_value)
        count = int(summary.get("closed_count") or 0)
        wins = int(summary.get("win_count") or 0)
        lines.append(
            f"| lane {lane} | {count} | {wins}/{count - wins} | {_fmt(summary.get('win_rate_pct'))}% | "
            f"{_signed(summary.get('average_return_pct'))}% |"
        )

    lines.extend(
        [
            "",
            "## A-tier selected replay ledger",
            "",
            "| 日期 | 股票 | lane | 半年涨停 | 行业量能/5日 | D+1净收益 |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for row in selected.to_dict("records"):
        lines.append(
            f"| {row.get('trade_date')} | {row.get('name')} `{row.get('vt_symbol')}` | {row.get('lane')} | "
            f"{int(_number(row.get('prior_limit_count_126')) or 0)} | "
            f"{_fmt(row.get('prior_industry_turnover_ratio_5d'))} | "
            f"{_signed(row.get('return_pct'))}% |"
        )

    lines.extend(
        [
            "",
            "## Executable contract",
            "",
            "1. 先执行当前正式合同的正确财报、正式低位结构、封板和同股历史盈利门，保留全部合格推荐，不做两仓 Top-N 评价。",
            "2. 全量交易集合再要求过去 126 个交易日涨停次数为 2-6 次，排除没有辨识度和已经反复透支的两端。",
            "3. 信号日前一交易日所属行业总成交额不低于更早 5 日均值时标记 A 级，否则为 B 级；A/B 都属于全量规则，不能只报 A 级胜率。",
            "4. 动态概念扩散只负责排序和进场时机：同概念梯队刚开始扩散且尚未进入分歧、退潮时优先；它不能绕过前两道质量门或新增交易。",
            "5. 历史收益仍按涨停价买入、D+1 收盘卖出及正式费用合同评价；实时退出可另外观察热度一致与分歧，但不得反写本研究标签。",
            "",
            "## Promotion boundary",
            "",
            f"- `{COVERAGE_RULE_VERSION}` 从 `{NATURAL_FORWARD_START}` 起冻结自然前向，至少 30 笔闭合且覆盖至少 3 个月。",
            "- 晋级要求全部闭合推荐胜率 `>=60%`，同时报告均值、复利、回撤、硬亏和市场阶段；两仓结果不参与。",
            f"- `{CORE_ABC_STRATEGY_VERSION}` 的 A+B 基座已完成历史/实时同源接入。",
        ]
    )
    return "\n".join(lines) + "\n"


def _candidate_identity(
    candidate: Mapping[str, object],
) -> tuple[date, str] | None:
    trade_date = _as_date(
        candidate.get("trade_date")
        or candidate.get("signal_date")
        or candidate.get("entry_date")
    )
    symbol = str(candidate.get("vt_symbol") or "").upper()
    return (trade_date, symbol) if trade_date is not None and symbol else None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and pd.notna(number) else None


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _signed(value: object) -> str:
    number = _number(value)
    return f"{number:+.4f}" if number is not None else "-"
