"""Evidence payload and Markdown report for membership-proxy discovery."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import pandas as pd

from .daily_discovery import RESEARCH_VERSION


def build_proxy_evidence(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
    stressed_outcomes: pd.DataFrame,
    *,
    coverage: Mapping[str, Any],
    minimum_validation_trades: int = 30,
) -> dict[str, Any]:
    """Build validation-selected evidence without creating formal metrics."""

    if minimum_validation_trades <= 0:
        raise ValueError("minimum_validation_trades must be positive")
    event_frame = events.copy()
    event_frame["trade_date"] = pd.to_datetime(
        event_frame["trade_date"], errors="raise"
    ).dt.normalize()
    normal = _merge_event_metadata(event_frame, outcomes)
    stressed = _merge_event_metadata(event_frame, stressed_outcomes)
    product_normal = normal.loc[normal["cohort"] == "main_rise_top3"].copy()
    product_stressed = stressed.loc[stressed["cohort"] == "main_rise_top3"].copy()

    exit_metrics = _group_metrics(
        _with_all_split(product_normal),
        ("time_split", "exit_key"),
    )
    cohort_metrics = _group_metrics(
        _with_all_split(normal),
        ("cohort", "time_split", "exit_key"),
    )
    market_timing_metrics = _group_metrics(
        _with_all_split(product_normal),
        ("active_direction", "danger_state", "time_split", "exit_key"),
    )
    family_normal = _explode_families(product_normal)
    family_stressed = _explode_families(product_stressed)
    family_metrics = _group_metrics(
        _with_all_split(family_normal),
        ("family", "time_split", "exit_key"),
    )
    stressed_family_metrics = _group_metrics(
        _with_all_split(family_stressed),
        ("family", "time_split", "exit_key"),
    )
    priorities = _strict_retest_priorities(
        family_metrics,
        stressed_family_metrics,
        family_normal,
        minimum_validation_trades=minimum_validation_trades,
    )

    return {
        "research_version": RESEARCH_VERSION,
        "status": "archived_membership_proxy",
        "selectable_for_v2": False,
        "superseded_by": "low-suction-research-v2",
        "formal_metrics": None,
        "qualification": "blocked_by_data_quality",
        "coverage": dict(coverage),
        "counts": {
            "events": int(event_frame["event_id"].nunique()),
            "events_by_cohort": _value_counts(event_frame["cohort"]),
            "closed_outcomes": int((outcomes["status"] == "closed").sum()),
            "rejected_outcomes": int((outcomes["status"] == "rejected").sum()),
            "unclosed_outcomes": int((outcomes["status"] == "unclosed").sum()),
            "rejection_reasons": _value_counts(
                outcomes.loc[outcomes["status"] != "closed", "reason"]
            ),
        },
        "time_splits": _time_split_ranges(event_frame),
        "product_exit_metrics": exit_metrics,
        "cohort_metrics": cohort_metrics,
        "market_timing_metrics": market_timing_metrics,
        "product_family_metrics": family_metrics,
        "strict_retest_priorities": priorities,
        "method_limits": [
            "current concept members are backfilled across history",
            "historical ST/listing/delist status is unavailable",
            "daily proxy observes D close and enters D+1 open",
            "entry+1/3/5 close exits are not the strict intraday D+1 exits",
            "concept correlation is neutral in the proxy leader block",
            "formal compounding and maximum drawdown remain null",
        ],
    }


def render_proxy_json(evidence: Mapping[str, Any]) -> str:
    return json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_proxy_markdown(evidence: Mapping[str, Any]) -> str:
    """Render concise proxy evidence with explicit non-qualification language."""

    coverage = _mapping(evidence.get("coverage"))
    counts = _mapping(evidence.get("counts"))
    lines = [
        "# AlphaAgent 主升龙头低吸代理探索",
        "",
        f"研究版本：`{evidence.get('research_version') or '-'}`  ",
        f"结论：`{evidence.get('qualification') or 'blocked_by_data_quality'}`  ",
        f"证据层级：`{evidence.get('status') or 'archived_membership_proxy'}`",
        "",
        "本报告使用当前概念成员回填历史，只能发现待严格复测的假设，不能作为正式胜率或复利，",
        "不构成投资建议。正式胜率、复利、最大回撤和策略资格均为 `null`。",
        "",
        "## Data Window",
        "",
        f"- 完整概念信号日：`{coverage.get('signal_trade_days', 0)}` 天，"
        f"`{coverage.get('signal_start') or '-'}..{coverage.get('signal_end') or '-'}`。",
        f"- 概念：`{coverage.get('concepts', 0)}`；当前成员代理："
        f"`{coverage.get('membership_rows', 0):,}` 条。",
        f"- 当前主板非 ST 代理股票：`{coverage.get('stock_symbols', 0):,}` 只；"
        f"股票日线：`{coverage.get('stock_rows', 0):,}` 行。",
        f"- 事件：`{counts.get('events', 0):,}`；闭合退出："
        f"`{counts.get('closed_outcomes', 0):,}`。",
        "",
        "## Time Splits",
        "",
        "| Split | Dates | Range |",
        "| --- | ---: | --- |",
    ]
    for split in evidence.get("time_splits") or []:
        lines.append(
            f"| `{split.get('time_split')}` | {split.get('trade_days', 0)} | "
            f"{split.get('start') or '-'}..{split.get('end') or '-'} |"
        )

    lines.extend(
        [
            "",
            "## Product Cohort Fixed Exits",
            "",
            "以下仅为 `main_rise_top3 / membership_proxy` 探索结果。",
            "",
            "| Exit | Closed | Win rate | Mean | Median | Profit factor |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for metric in _metrics_for_split(
        evidence.get("product_exit_metrics") or [],
        "all",
    ):
        lines.append(_metric_row(metric, key="exit_key"))

    lines.extend(
        [
            "",
            "## Falsification Cohorts",
            "",
            "| Cohort | Exit | Closed | Win rate | Mean | Profit factor |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    cohort_metrics = [
        item
        for item in evidence.get("cohort_metrics") or []
        if item.get("time_split") == "all"
    ]
    for metric in cohort_metrics:
        lines.append(
            f"| `{metric.get('cohort')}` | `{metric.get('exit_key')}` | "
            f"{metric.get('closed', 0)} | {_pct(metric.get('win_rate_pct'))} | "
            f"{_pct(metric.get('mean_return_pct'))} | {_profit_factor(metric)} |"
        )

    lines.extend(
        [
            "",
            "## Three Event Families",
            "",
            "同一事件可同时属于多个家族，因此下表家族样本不能相加。",
            "",
            "| Family | Exit | Closed | Win rate | Mean | Profit factor |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    family_metrics = [
        item
        for item in evidence.get("product_family_metrics") or []
        if item.get("time_split") == "all"
    ]
    for metric in family_metrics:
        lines.append(
            f"| `{metric.get('family')}` | `{metric.get('exit_key')}` | "
            f"{metric.get('closed', 0)} | {_pct(metric.get('win_rate_pct'))} | "
            f"{_pct(metric.get('mean_return_pct'))} | {_profit_factor(metric)} |"
        )

    lines.extend(
        [
            "",
            "## Gold And Silver Fingers",
            "",
            "金手指、银手指和危险状态只做分层，不作为入场开关。",
            "",
            "| Active state | Risk | Exit | Closed | Win rate | Mean | Profit factor |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    timing_metrics = [
        item
        for item in evidence.get("market_timing_metrics") or []
        if item.get("time_split") == "all"
    ]
    for metric in timing_metrics:
        lines.append(
            f"| `{metric.get('active_direction')}` | `{metric.get('danger_state')}` | "
            f"`{metric.get('exit_key')}` | {metric.get('closed', 0)} | "
            f"{_pct(metric.get('win_rate_pct'))} | {_pct(metric.get('mean_return_pct'))} | "
            f"{_profit_factor(metric)} |"
        )

    lines.extend(
        [
            "",
            "## Strict Retest Priorities",
            "",
            "优先级只由验证段产生；留出段和双倍成本只用于随后检查，不反向选择。",
            "",
            "| Family | Exit | Validation n/win/mean/PF | Holdout n/win/mean/PF | Double-cost holdout n/win/mean/PF | Stock/concept/month concentration |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ]
    )
    priorities = evidence.get("strict_retest_priorities") or []
    if priorities:
        for item in priorities:
            validation = _mapping(item.get("validation"))
            holdout = _mapping(item.get("holdout"))
            stressed = _mapping(item.get("double_cost_holdout"))
            concentration = _mapping(item.get("holdout_concentration"))
            lines.append(
                f"| `{item.get('family')}` | `{item.get('exit_key')}` | "
                f"{_compact_metric(validation)} | {_compact_metric(holdout)} | "
                f"{_compact_metric(stressed)} | "
                f"{_pct(concentration.get('top_stock_abs_share_pct'))} / "
                f"{_pct(concentration.get('top_concept_abs_share_pct'))} / "
                f"{_pct(concentration.get('top_month_abs_share_pct'))} |"
            )
    else:
        lines.append("| 无 | - | - | - | - | - |")

    lines.extend(["", "## Execution Gaps", ""])
    reasons = _mapping(counts.get("rejection_reasons"))
    if reasons:
        lines.extend(f"- `{reason}`：{count}" for reason, count in sorted(reasons.items()))
    else:
        lines.append("- 无")

    lines.extend(["", "## Limits", ""])
    lines.extend(f"- {limit}" for limit in evidence.get("method_limits") or [])
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "本轮只保留上表组合为严格数据复测优先级，不选择生产规则。只有补齐三年点时成员、",
            "历史证券状态和候选分钟路径，并通过至少 300 笔锁定留出交易、10% 回撤及双倍成本",
            "门禁后，才可能产生 `qualified_research_rule`。",
            "",
            "## Reproduce",
            "",
            "```bash",
            "docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli proxy-discovery --format markdown",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _merge_event_metadata(events: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    metadata_columns = [
        "event_id",
        "vt_symbol",
        "trade_date",
        "sector_id",
        "family_tags",
        "cohort",
        "time_split",
    ]
    missing = [column for column in metadata_columns if column not in events]
    if missing:
        raise ValueError(f"missing proxy event columns: {', '.join(missing)}")
    metadata = events[metadata_columns].copy()
    for column in ("active_direction", "danger_state"):
        metadata[column] = events[column] if column in events else "UNKNOWN"
    return outcomes.merge(
        metadata,
        on="event_id",
        how="left",
        suffixes=("", "_event"),
        validate="many_to_one",
    )


def _explode_families(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.explode("family_tags").rename(columns={"family_tags": "family"})


def _with_all_split(frame: pd.DataFrame) -> pd.DataFrame:
    aggregate = frame.copy()
    aggregate["time_split"] = "all"
    return pd.concat([frame, aggregate], ignore_index=True)


def _group_metrics(
    frame: pd.DataFrame,
    group_columns: Sequence[str],
) -> list[dict[str, Any]]:
    records = []
    for keys, group in frame.groupby(list(group_columns), dropna=False, sort=True):
        key_values = keys if isinstance(keys, tuple) else (keys,)
        record = dict(zip(group_columns, key_values, strict=True))
        record.update(_performance(group))
        records.append(record)
    return records


def _performance(frame: pd.DataFrame) -> dict[str, Any]:
    closed = frame.loc[frame["status"] == "closed", "net_return_pct"].dropna().astype(float)
    positive = float(closed.loc[closed > 0].sum())
    negative = float(abs(closed.loc[closed < 0].sum()))
    return {
        "events": int(frame["event_id"].nunique()),
        "closed": int(len(closed)),
        "win_rate_pct": _round((closed > 0).mean() * 100.0) if len(closed) else None,
        "mean_return_pct": _round(closed.mean()) if len(closed) else None,
        "median_return_pct": _round(closed.median()) if len(closed) else None,
        "profit_factor": _round(positive / negative) if negative > 0 else None,
    }


def _strict_retest_priorities(
    family_metrics: Sequence[Mapping[str, Any]],
    stressed_metrics: Sequence[Mapping[str, Any]],
    family_outcomes: pd.DataFrame,
    *,
    minimum_validation_trades: int,
) -> list[dict[str, Any]]:
    validation = [
        metric
        for metric in family_metrics
        if metric.get("time_split") == "validation"
        and int(metric.get("closed") or 0) >= minimum_validation_trades
        and float(metric.get("mean_return_pct") or 0) > 0
        and _profit_factor_passes(metric)
    ]
    validation.sort(
        key=lambda item: (
            -float(item.get("mean_return_pct") or 0),
            -float(item.get("profit_factor") or 0),
            -int(item.get("closed") or 0),
            str(item.get("family")),
            str(item.get("exit_key")),
        )
    )
    priorities = []
    for selected in validation[:5]:
        family = str(selected["family"])
        exit_key = str(selected["exit_key"])
        priorities.append(
            {
                "family": family,
                "exit_key": exit_key,
                "validation": dict(selected),
                "holdout": _find_metric(
                    family_metrics,
                    family=family,
                    exit_key=exit_key,
                    time_split="holdout",
                ),
                "double_cost_holdout": _find_metric(
                    stressed_metrics,
                    family=family,
                    exit_key=exit_key,
                    time_split="holdout",
                ),
                "holdout_concentration": _concentration(
                    family_outcomes,
                    family=family,
                    exit_key=exit_key,
                ),
            }
        )
    return priorities


def _profit_factor_passes(metric: Mapping[str, Any]) -> bool:
    profit_factor = metric.get("profit_factor")
    if profit_factor is not None:
        return float(profit_factor) > 1.0
    return float(metric.get("win_rate_pct") or 0) == 100.0


def _find_metric(
    metrics: Sequence[Mapping[str, Any]],
    **expected: str,
) -> dict[str, Any]:
    for metric in metrics:
        if all(str(metric.get(key)) == value for key, value in expected.items()):
            return dict(metric)
    return {
        **expected,
        "events": 0,
        "closed": 0,
        "win_rate_pct": None,
        "mean_return_pct": None,
        "median_return_pct": None,
        "profit_factor": None,
    }


def _concentration(
    family_outcomes: pd.DataFrame,
    *,
    family: str,
    exit_key: str,
) -> dict[str, Any]:
    rows = family_outcomes.loc[
        (family_outcomes["family"] == family)
        & (family_outcomes["exit_key"] == exit_key)
        & (family_outcomes["time_split"] == "holdout")
        & (family_outcomes["status"] == "closed")
    ].copy()
    if rows.empty:
        return {
            "top_stock_abs_share_pct": None,
            "top_concept_abs_share_pct": None,
            "top_month_abs_share_pct": None,
        }
    rows["month"] = pd.to_datetime(rows["trade_date"]).dt.to_period("M").astype(str)
    total_absolute = float(rows["net_return_pct"].abs().sum())
    if total_absolute <= 0:
        return {
            "top_stock_abs_share_pct": None,
            "top_concept_abs_share_pct": None,
            "top_month_abs_share_pct": None,
        }
    return {
        "top_stock_abs_share_pct": _top_absolute_share(rows, "vt_symbol", total_absolute),
        "top_concept_abs_share_pct": _top_absolute_share(rows, "sector_id", total_absolute),
        "top_month_abs_share_pct": _top_absolute_share(rows, "month", total_absolute),
    }


def _top_absolute_share(frame: pd.DataFrame, column: str, total_absolute: float) -> float:
    grouped = frame.groupby(column)["net_return_pct"].apply(lambda values: values.abs().sum())
    return _round(float(grouped.max()) / total_absolute * 100.0)


def _time_split_ranges(events: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for split, group in events.groupby("time_split", sort=True):
        rows.append(
            {
                "time_split": str(split),
                "trade_days": int(group["trade_date"].nunique()),
                "start": group["trade_date"].min().date().isoformat(),
                "end": group["trade_date"].max().date().isoformat(),
            }
        )
    order = {"development": 0, "validation": 1, "holdout": 2}
    return sorted(rows, key=lambda item: order.get(item["time_split"], 99))


def _value_counts(values: Iterable[Any]) -> dict[str, int]:
    counts = Counter(str(value) for value in values if pd.notna(value))
    return dict(sorted(counts.items()))


def _metrics_for_split(metrics: Sequence[Mapping[str, Any]], split: str):
    return [item for item in metrics if item.get("time_split") == split]


def _metric_row(metric: Mapping[str, Any], *, key: str) -> str:
    return (
        f"| `{metric.get(key)}` | {metric.get('closed', 0)} | "
        f"{_pct(metric.get('win_rate_pct'))} | {_pct(metric.get('mean_return_pct'))} | "
        f"{_pct(metric.get('median_return_pct'))} | {_profit_factor(metric)} |"
    )


def _compact_metric(metric: Mapping[str, Any]) -> str:
    return (
        f"{metric.get('closed', 0)} / {_pct(metric.get('win_rate_pct'))} / "
        f"{_pct(metric.get('mean_return_pct'))} / {_profit_factor(metric)}"
    )


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _profit_factor(metric: Mapping[str, Any]) -> str:
    value = metric.get("profit_factor")
    if value is not None:
        return f"{float(value):.4f}"
    return "∞" if int(metric.get("closed") or 0) > 0 else "-"


def _round(value: Any) -> float:
    return round(float(value), 4)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
