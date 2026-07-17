"""Stable JSON and Markdown rendering for low-suction audit evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import STRICT_MIN_CALENDAR_DAYS

BLOCKING_GAP_LABELS = {
    "stock_daily_history": "三年可靠股票日线",
    "concept_index_history": "三年完整概念指数",
    "historical_concept_membership": "历史概念成员",
    "historical_security_status": "历史证券状态",
    "candidate_minute_paths": "候选分钟路径",
}
SUPPORTING_DATASETS = (
    ("stock_minutes_1m", "1 分钟线", "候选定向覆盖，非全市场连续"),
    ("dragon_tiger", "龙虎榜", "近端分层，不证明自然人身份"),
    ("stock_auction", "竞价", "仅前向近端"),
    ("stock_fund_flow", "个股资金流", "仅近端特征"),
    ("sector_fund_flow", "板块资金流", "仅近端特征"),
    ("live_concept_strength", "盘中概念强度", "仅前向点时证据"),
)


def render_audit_json(report: Mapping[str, Any]) -> str:
    """Render deterministic machine-readable evidence."""

    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_audit_markdown(report: Mapping[str, Any]) -> str:
    """Render the data-quality decision without inventing performance metrics."""

    coverage = _mapping(report.get("coverage"))
    inventory = _mapping(report.get("inventory"))
    blocking_gaps = [str(value) for value in report.get("blocking_gaps") or []]
    lines = [
        "# AlphaAgent 低吸研究数据质量审计",
        "",
        f"数据截止日：{report.get('as_of_date') or '-'}  ",
        f"研究版本：`{report.get('research_version') or '-'}`  ",
        f"结论：`{report.get('status') or 'blocked_by_data_quality'}`  ",
        f"证据层级：`{report.get('evidence_level') or 'invalid'}`",
        "",
        "正式胜率、复利、利润因子和回撤：`null`。当前输入未通过严格历史研究门禁，",
        "任何代理样本只能用于发现假设，不能用于选择生产规则或承诺未来收益。",
        "",
        "## Blocking Gaps",
        "",
    ]
    lines.extend(
        f"- `{gap}`：{BLOCKING_GAP_LABELS.get(gap, gap)}" for gap in blocking_gaps
    )
    if not blocking_gaps:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## Core Coverage",
            "",
            "| Input | Mode | Rows | Entities | Trade days | Range | Coverage |",
            "| --- | --- | ---: | ---: | ---: | --- | ---: |",
            _dataset_row("股票日线", coverage.get("stock_daily")),
            _dataset_row("概念指数", coverage.get("concept_daily")),
            _dataset_row("概念成员", coverage.get("concept_membership")),
            _dataset_row("证券状态", coverage.get("security_status")),
            _dataset_row("金银手指", coverage.get("market_timing")),
        ]
    )
    stock_coverage = _mapping(coverage.get("stock_daily"))
    stock_inventory = _mapping(inventory.get("stock_daily"))
    calendar_span_days = int(stock_coverage.get("calendar_span_days") or 0)
    if calendar_span_days:
        lines.extend(
            [
                "",
                f"股票日线可靠窗口为 `{int(stock_coverage.get('trade_days') or 0):,}` 个交易日、"
                f"`{calendar_span_days:,}` 个自然日；严格三年门槛至少需要 "
                f"`{STRICT_MIN_CALENDAR_DAYS:,}` 个自然日。",
            ]
        )
    raw_stock_days = int(stock_inventory.get("raw_trade_days") or 0)
    if raw_stock_days:
        minimum_symbols = int(stock_inventory.get("minimum_daily_symbols") or 0)
        threshold = (
            f"每日至少 `{minimum_symbols:,}` 只股票"
            if minimum_symbols
            else "可靠横截面"
        )
        lines.append(
            f"原始日线共有 `{raw_stock_days:,}` 个日期；只有满足{threshold}的日期计入可靠窗口。"
        )

    lines.extend(["", "## Concept Evidence", ""])
    concept_inventory = _mapping(inventory.get("concept_daily"))
    membership_inventory = _mapping(inventory.get("concept_membership"))
    expected_start = int(
        concept_inventory.get("minimum_expected_active_concepts") or 0
    )
    expected_end = int(
        concept_inventory.get("maximum_expected_active_concepts") or 0
    )
    minimum_active = int(concept_inventory.get("minimum_active_concepts") or 0)
    minimum_pct = float(concept_inventory.get("minimum_cross_section_pct") or 0.0)
    lines.extend(
        [
            f"- 当前题材概念：`{concept_inventory.get('concept_count', 0)}` 个。",
            f"- 官方概念指数：`{concept_inventory.get('canonical_source') or '-'}`；"
            f"已建指数 `{concept_inventory.get('indexed_concept_count', 0)}` 个。",
            f"- 原始概念指数日期：`{concept_inventory.get('raw_trade_days', 0)}` 天，"
            f"范围 `{_range_text(concept_inventory, prefix='raw_')}`。",
            f"- 动态有效概念分母：`{expected_start}..{expected_end}`；"
            f"每日至少 `{minimum_active}` 个且覆盖不低于 `{minimum_pct:.1f}%`。",
            f"- 达到动态横截面门槛：`{concept_inventory.get('complete_trade_days', 0)}` 天，"
            f"范围 `{_range_text(concept_inventory, prefix='complete_')}`。",
            f"- 原始成员快照：`{membership_inventory.get('raw_snapshot_trade_days', 0)}` 天。",
            f"- 按盘后快照只能次日使用后：`{membership_inventory.get('effective_trade_days', 0)}` 天。",
            "- 当前成员不能回填历史；盘后 D 日快照不能解释 D 日盘中。",
            "",
            "## Supporting Coverage",
            "",
            "| Input | Rows | Entities | Trade days | Range | Research use |",
            "| --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    supporting = _mapping(coverage.get("supporting"))
    supporting_rows = [
        _supporting_row(label, supporting.get(key), research_use)
        for key, label, research_use in SUPPORTING_DATASETS
        if key in supporting
    ]
    lines.extend(supporting_rows or ["| 无 | 0 | 0 | 0 | - | - |"])
    lines.extend(
        [
            "",
            "## Market-Timing Labels",
            "",
        ]
    )
    timing_inventory = _mapping(inventory.get("market_timing"))
    state_counts = _mapping(timing_inventory.get("state_counts"))
    lines.extend(
        f"- `{state}`：{count} 天" for state, count in sorted(state_counts.items())
    )
    if not state_counts:
        lines.append("- 无可用标签")
    lines.extend(
        [
            "",
            "金银手指覆盖可用于代理样本分层，但不能弥补概念成员、历史证券状态和",
            "候选分钟路径缺口，也不能预设它必然提高低吸收益。",
        ]
    )

    lines.extend(["", "## Source Findings", ""])
    limitations = _mapping(report.get("source_limitations"))
    for source_name, raw_item in sorted(limitations.items()):
        item = _mapping(raw_item)
        url = item.get("url")
        suffix = f"（{url}）" if url else ""
        lines.append(
            f"- `{source_name}`：`{item.get('status') or 'unknown'}`；"
            f"{item.get('reason') or '-'}{suffix}"
        )

    lines.extend(
        [
            "",
            "## Current Decision",
            "",
            *_current_decision_lines(blocking_gaps),
            "",
            "## Reproduce",
            "",
            "```bash",
            "docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli audit --format json",
            "docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli audit --format markdown",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _current_decision_lines(blocking_gaps: list[str]) -> tuple[str, ...]:
    if not blocking_gaps:
        return (
            "严格历史输入门禁已通过；本审计只确认数据可用性，正式胜率与复利仍需由锁定研究生成。",
        )

    lines = ["当前不能计算或发布正式低吸胜率与复利。"]
    daily_history_gaps = {"stock_daily_history", "concept_index_history"}
    if not daily_history_gaps.intersection(blocking_gaps):
        lines.append("股票和概念指数的三年日线门槛都已通过。")
    if "historical_concept_membership" in blocking_gaps:
        lines.append(
            "当前 `membership_proxy` 日线探索只用于缩小待验证的事件家族。"
        )
    unresolved = "、".join(
        BLOCKING_GAP_LABELS.get(gap, gap) for gap in blocking_gaps
    )
    lines.append(f"当前仍需补齐{unresolved}后重新验证。")
    return tuple(lines)


def validated_output_path(
    output: str | Path,
    *,
    evidence_dir: Path | None = None,
) -> Path:
    """Resolve an audit output strictly inside the maintained evidence folder."""

    repository_root = Path(__file__).resolve().parents[4]
    allowed_root = (evidence_dir or repository_root / "memory" / "06_backtests").resolve()
    candidate = Path(output)
    if not candidate.is_absolute():
        candidate = repository_root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("output must stay inside memory/06_backtests") from exc
    return resolved


def _dataset_row(label: str, raw_coverage: Any) -> str:
    coverage = _mapping(raw_coverage)
    return (
        f"| {label} | `{coverage.get('mode') or 'unavailable'}` | "
        f"{int(coverage.get('rows') or 0):,} | {int(coverage.get('entities') or 0):,} | "
        f"{int(coverage.get('trade_days') or 0):,} | {_range_text(coverage)} | "
        f"{float(coverage.get('coverage_pct') or 0):.4f}% |"
    )


def _supporting_row(label: str, raw_coverage: Any, research_use: str) -> str:
    coverage = _mapping(raw_coverage)
    return (
        f"| {label} | {int(coverage.get('rows') or 0):,} | "
        f"{int(coverage.get('entities') or 0):,} | "
        f"{int(coverage.get('trade_days') or 0):,} | "
        f"{_range_text(coverage)} | {research_use} |"
    )


def _range_text(values: Mapping[str, Any], *, prefix: str = "") -> str:
    start = values.get(f"{prefix}start") or "-"
    end = values.get(f"{prefix}end") or "-"
    if start == "-" and end == "-":
        return "-"
    return f"{start}..{end}"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
