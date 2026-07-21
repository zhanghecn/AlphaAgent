"""Individual warming attribution for the frozen cross-regime proxy."""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from alphaagent.server.services.research_runtime import require_research_runtime

from .causal_leader_pullback import (
    GOLD_STRONG_RECLAIM_RETURN_PCT,
    ROTATION_NEXT_SESSION_POLICY_VERSION,
)
from .cross_regime_validation import (
    DEVELOPMENT_BLOCKS,
    VALIDATION_BLOCKS,
    build_sequential_regime_audit,
)


STUDY_VERSION = "cross-regime-warming-failure-study-v5"
SOURCE_POLICY_VERSION = "causal-leader-pullback-cross-regime-v3"
CANDIDATE_POLICY_VERSION = (
    "causal-leader-pullback-warming-support-relevance-v1"
)
ADAPTIVE_DIAGNOSTIC_POLICY_VERSION = ROTATION_NEXT_SESSION_POLICY_VERSION
VARIANT = "cross_regime_support_reclaim_confirmation"
WARMING_PHASE = "warming"
ROTATION_PHASE = "rotation"
CANDIDATE_CAUSAL_CATEGORY_FEATURES = (
    "market_phase",
    "dynamic_rank",
    "wave_number",
    "support_line",
    "support_test_session_gap",
)
CANDIDATE_NUMERIC_FEATURES = (
    "signal_daily_return_pct",
    "volume_ratio_prior5",
    "peak_gap_pct",
    "low_support_gap_pct",
    "close_support_gap_pct",
    "turnover_expansion",
    "close_location",
    "sessions_since_ignition",
    "signal_ma5_gap_pct",
    "signal_ma10_gap_pct",
    "signal_ma20_gap_pct",
    "support_day_daily_return_pct",
    "support_day_volume_ratio_prior5",
    "support_day_close_location",
    "campaign_day",
    "concept_gain_pct",
)
PROHIBITED_OUTCOME_FIELDS = frozenset(
    {
        "d1_close",
        "d1_date",
        "d1_net_return_pct",
        "exit_date",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "mae_pct",
        "mfe_pct",
        "net_return_pct",
        "outcome",
        "outcome_group",
    }
)


@dataclass(frozen=True)
class DailyContext:
    """Bounded exact daily context for the selected frozen trade identities."""

    stock_bars: pd.DataFrame
    stock_features: pd.DataFrame
    campaign_paths: pd.DataFrame
    market_timing: pd.DataFrame
    coverage: dict[str, Any]


def build_trade_feature_ledger(
    source: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Join frozen cross-regime trades to their causal D-close signals."""

    _validate_source_contract(source)
    signals = _required_rows(source, "candidate_signal_ledger")
    trades = _required_rows(source, "trade_ledger")
    signal_by_id = _index_signals(signals)
    rows: list[dict[str, Any]] = []
    seen_trades: set[str] = set()
    for trade in trades:
        if str(trade.get("variant") or "") != VARIANT:
            continue
        signal_id = _required_text(trade, "signal_id", "trade")
        if signal_id in seen_trades:
            raise ValueError("selected trade identities must be unique")
        seen_trades.add(signal_id)
        signal = signal_by_id.get(signal_id)
        if signal is None:
            raise ValueError(f"trade signal is missing: {signal_id}")
        rows.append(_joined_ledger_row(trade, signal))
    if not rows:
        raise ValueError("cross-regime selected trades are empty")
    return sorted(rows, key=lambda row: (row["entry_date"], row["signal_id"]))


def select_support_relevance_candidate(
    feature_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep rotation and require warming lows to hold a still-relevant support."""

    selected: list[dict[str, Any]] = []
    for raw in feature_rows:
        prohibited = sorted(PROHIBITED_OUTCOME_FIELDS.intersection(raw))
        if prohibited:
            raise ValueError(
                f"prohibited outcome fields in candidate selection: {prohibited}"
            )
        row = dict(raw)
        phase = _required_text(row, "market_phase", "candidate feature")
        if phase == ROTATION_PHASE:
            selected.append(row)
            continue
        if phase != WARMING_PHASE:
            continue
        gap = _required_number(row, "low_support_gap_pct", "candidate feature")
        if 0.0 <= gap <= GOLD_STRONG_RECLAIM_RETURN_PCT:
            selected.append(row)
    return selected


def select_rotation_timeliness_candidate(
    feature_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Require next-session confirmation in rotation after support relevance."""

    selected: list[dict[str, Any]] = []
    for row in select_support_relevance_candidate(feature_rows):
        if (
            _required_text(row, "market_phase", "candidate feature")
            == ROTATION_PHASE
            and _required_integer(
                row,
                "support_test_session_gap",
                "candidate feature",
            )
            != 1
        ):
            continue
        selected.append(row)
    return selected


def build_warming_failure_report(
    source: Mapping[str, Any],
    *,
    bootstrap_draws: int = 10_000,
    enriched_ledger: Sequence[Mapping[str, Any]] | None = None,
    cash_metrics: Mapping[str, Any] | None = None,
    adaptive_cash_metrics: Mapping[str, Any] | None = None,
    context_coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build descriptive attribution plus one explicitly reused-history candidate."""

    ledger = (
        [dict(row) for row in enriched_ledger]
        if enriched_ledger is not None
        else build_trade_feature_ledger(source)
    )
    _validate_enriched_identity(source, ledger)
    causal_rows = [dict(row["causal_features"]) for row in ledger]
    selected_features = select_support_relevance_candidate(causal_rows)
    selected_ids = {str(row["signal_id"]) for row in selected_features}
    candidate_ledger = [row for row in ledger if row["signal_id"] in selected_ids]
    candidate_trades = [
        dict(trade)
        for trade in _required_rows(source, "trade_ledger")
        if str(trade.get("variant") or "") == VARIANT
        and str(trade.get("signal_id") or "") in selected_ids
    ]
    audit = build_sequential_regime_audit(
        candidate_trades,
        _required_rows(source, "candidate_signal_ledger"),
        bootstrap_draws=bootstrap_draws,
    )
    adaptive_features = select_rotation_timeliness_candidate(causal_rows)
    adaptive_ids = {str(row["signal_id"]) for row in adaptive_features}
    adaptive_ledger = [
        row for row in ledger if row["signal_id"] in adaptive_ids
    ]
    adaptive_trades = [
        dict(trade)
        for trade in _required_rows(source, "trade_ledger")
        if str(trade.get("variant") or "") == VARIANT
        and str(trade.get("signal_id") or "") in adaptive_ids
    ]
    adaptive_audit = build_sequential_regime_audit(
        adaptive_trades,
        _required_rows(source, "candidate_signal_ledger"),
        bootstrap_draws=bootstrap_draws,
    )
    validation_warming = [
        row
        for row in ledger
        if row["market_phase"] == WARMING_PHASE
        and row["time_block"] in VALIDATION_BLOCKS
    ]
    phase_metrics = _group_metrics(candidate_ledger, "market_phase")
    cash = dict(cash_metrics) if cash_metrics is not None else None
    candidate_qualification = _candidate_qualification(
        candidate_ledger,
        phase_metrics,
        audit,
        cash,
    )
    adaptive_cash = (
        dict(adaptive_cash_metrics)
        if adaptive_cash_metrics is not None
        else None
    )
    adaptive_phase_metrics = _group_metrics(adaptive_ledger, "market_phase")
    adaptive_qualification = _candidate_qualification(
        adaptive_ledger,
        adaptive_phase_metrics,
        adaptive_audit,
        adaptive_cash,
    )
    adaptive_blockers = [
        "posthoc_rule_requires_new_natural_forward_contract",
        "reused_validation_not_fresh_holdout",
        "strict_historical_membership_missing",
        "same_close_execution_is_research_proxy",
    ]
    if not adaptive_qualification["historical_numeric_gates_passed"]:
        adaptive_blockers.append("historical_numeric_gates_failed")
    formal_blockers = [
        "reused_validation_not_fresh_holdout",
        "strict_historical_membership_missing",
        "same_close_execution_is_research_proxy",
    ]
    if cash is None:
        formal_blockers.append("four_slot_cash_not_attached")
    if not candidate_qualification["historical_numeric_gates_passed"]:
        formal_blockers.append("historical_numeric_gates_failed")
    return {
        "study_version": STUDY_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "research_status": "warming_failure_attributed_candidate_reused_history",
        "formal_strategy": False,
        "causal_enrichment": dict(context_coverage or {}),
        "baseline": {
            "full_history": _return_metrics(ledger),
            "development": _return_metrics(_rows_in_blocks(ledger, DEVELOPMENT_BLOCKS)),
            "validation": _return_metrics(_rows_in_blocks(ledger, VALIDATION_BLOCKS)),
            "development_market_phases": _group_metrics(
                _rows_in_blocks(ledger, DEVELOPMENT_BLOCKS), "market_phase"
            ),
            "validation_market_phases": _group_metrics(
                _rows_in_blocks(ledger, VALIDATION_BLOCKS), "market_phase"
            ),
        },
        "attribution": {
            "profiled_trade_count": len(ledger),
            "warming": _warming_split_metrics(ledger),
            "feature_profiles": _warming_feature_profiles(ledger),
            "validation_clusters": {
                field: _group_metrics(validation_warming, field)
                for field in (
                    "entry_date",
                    "entry_month",
                    "vt_symbol",
                    "concept_name",
                    "campaign_id",
                )
            },
        },
        "individual_cases": {
            "validation_warming": [_case_row(row) for row in validation_warming],
            "development_warming_winners": _representative_cases(
                ledger,
                blocks=DEVELOPMENT_BLOCKS,
                outcome_group="winner",
            ),
            "development_warming_losses": _representative_cases(
                ledger,
                blocks=DEVELOPMENT_BLOCKS,
                outcome_group="loser",
            ),
        },
        "candidate": {
            "policy_version": CANDIDATE_POLICY_VERSION,
            "formal_strategy": False,
            "rule": {
                "rotation": "unchanged_v3_strong_reclaim",
                "warming": (
                    "0 <= confirmation_low/support-1 <= existing_8pct_"
                    "strong_reclaim_threshold"
                ),
                "threshold_searched": False,
            },
            "selected_signal_ids": sorted(selected_ids),
            "attribution": _candidate_attribution(candidate_ledger),
            "full_history": _return_metrics(candidate_ledger),
            "full_history_market_phases": phase_metrics,
            "sequential_audit": audit,
            "cash": cash,
            "qualification": candidate_qualification,
            "formal_blockers": formal_blockers,
        },
        "adaptive_diagnostic": {
            "policy_version": ADAPTIVE_DIAGNOSTIC_POLICY_VERSION,
            "selection_origin": "posthoc_after_category_stability_attribution",
            "formal_strategy": False,
            "rule": {
                "rotation": "support_test_session_gap == 1",
                "warming": "unchanged_support_relevance_candidate",
                "threshold_searched": False,
            },
            "selected_signal_ids": sorted(adaptive_ids),
            "excluded_signal_ids": sorted(selected_ids - adaptive_ids),
            "full_history": _return_metrics(adaptive_ledger),
            "development": _return_metrics(
                _rows_in_blocks(adaptive_ledger, DEVELOPMENT_BLOCKS)
            ),
            "validation": _return_metrics(
                _rows_in_blocks(adaptive_ledger, VALIDATION_BLOCKS)
            ),
            "development_market_phases": _group_metrics(
                _rows_in_blocks(adaptive_ledger, DEVELOPMENT_BLOCKS),
                "market_phase",
            ),
            "validation_market_phases": _group_metrics(
                _rows_in_blocks(adaptive_ledger, VALIDATION_BLOCKS),
                "market_phase",
            ),
            "sequential_audit": adaptive_audit,
            "cash": adaptive_cash,
            "qualification": adaptive_qualification,
            "formal_blockers": adaptive_blockers,
        },
        "boundaries": [
            "The frozen V3 source report is read-only and its trade identities are unchanged.",
            "Candidate selection receives causal feature mappings with outcome fields prohibited.",
            "Blocks 4-5 were previously inspected and are rejection evidence, not a fresh holdout.",
            "No API, paper strategy, or formal metrics are changed by this report.",
        ],
    }


def run_warming_failure_study(
    source: Mapping[str, Any],
    *,
    daily_context: DailyContext | None = None,
    bootstrap_draws: int = 10_000,
    source_path: str | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Load bounded causal context, replay cash, and build the detailed study."""

    ledger = build_trade_feature_ledger(source)
    if daily_context is None:
        require_research_runtime()
        context = load_selected_daily_context(ledger)
    else:
        context = daily_context
    enriched = enrich_trade_feature_ledger(
        ledger,
        stock_features=context.stock_features,
        campaign_paths=context.campaign_paths,
        market_timing=context.market_timing,
    )
    causal_rows = [dict(row["causal_features"]) for row in enriched]
    selected_ids = {
        str(row["signal_id"])
        for row in select_support_relevance_candidate(causal_rows)
    }
    candidate_trades = pd.DataFrame.from_records(
        [
            dict(row)
            for row in _required_rows(source, "trade_ledger")
            if str(row.get("variant") or "") == VARIANT
            and str(row.get("signal_id") or "") in selected_ids
        ]
    )
    if candidate_trades.empty:
        raise ValueError("support-relevance candidate produced no trades")
    from .causal_leader_pullback_study import simulate_four_slot_cash

    cash = simulate_four_slot_cash(candidate_trades, context.stock_bars)
    adaptive_ids = {
        str(row["signal_id"])
        for row in select_rotation_timeliness_candidate(causal_rows)
    }
    adaptive_trades = pd.DataFrame.from_records(
        [
            dict(row)
            for row in _required_rows(source, "trade_ledger")
            if str(row.get("variant") or "") == VARIANT
            and str(row.get("signal_id") or "") in adaptive_ids
        ]
    )
    if adaptive_trades.empty:
        raise ValueError("rotation-timeliness candidate produced no trades")
    adaptive_cash = simulate_four_slot_cash(adaptive_trades, context.stock_bars)
    report = build_warming_failure_report(
        source,
        bootstrap_draws=bootstrap_draws,
        enriched_ledger=enriched,
        cash_metrics=cash,
        adaptive_cash_metrics=adaptive_cash,
        context_coverage=context.coverage,
    )
    report["source_artifact"] = {
        "path": source_path,
        "sha256": source_sha256,
    }
    return report


def load_selected_daily_context(
    ledger: Sequence[Mapping[str, Any]],
) -> DailyContext:
    """Read only symbols and concepts referenced by the frozen selected ledger."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    from .causal_leader_pullback_study import (
        CONCEPT_SOURCE,
        build_causal_stock_features,
        build_concept_campaign_ledger,
    )
    from .contracts import CONCEPT_SECTOR_TYPES
    from .dynamic_concept_campaign_study import filter_exploratory_concept_universe
    from .event_recognition_falsification import load_timing_context

    symbols = tuple(sorted({str(row["vt_symbol"]) for row in ledger}))
    sector_ids = tuple(
        sorted(
            {
                str(row["causal_features"]["sector_id"])
                for row in ledger
            }
        )
    )
    if not symbols or not sector_ids:
        raise ValueError("selected context requires symbols and sector IDs")
    maximum_date = max(
        date.fromisoformat(
            str(row["outcome"].get("exit_date") or row["entry_date"])[:10]
        )
        for row in ledger
    )
    engine = get_engine()
    stock = schema.stock_daily_bars
    stock_statement = (
        select(
            stock.c.vt_symbol,
            stock.c.trade_date,
            stock.c.open_price,
            stock.c.high_price,
            stock.c.low_price,
            stock.c.close_price,
            stock.c.volume,
            stock.c.turnover,
            stock.c.source,
        )
        .where(
            stock.c.vt_symbol.in_(symbols),
            stock.c.trade_date <= maximum_date,
        )
        .order_by(stock.c.vt_symbol, stock.c.trade_date)
    )
    stock_bars = pd.read_sql(stock_statement, engine, parse_dates=["trade_date"])
    if stock_bars.empty:
        raise ValueError("selected stock daily context is empty")
    stock_features = build_causal_stock_features(stock_bars)

    sector_bar = schema.sector_daily_bars
    sector = schema.sectors
    concept_statement = (
        select(
            sector_bar.c.sector_id,
            sector.c.name.label("concept_name"),
            sector_bar.c.trade_date,
            sector_bar.c.open_price,
            sector_bar.c.high_price,
            sector_bar.c.low_price,
            sector_bar.c.close_price,
            sector_bar.c.volume,
            sector_bar.c.turnover,
            sector_bar.c.source,
        )
        .select_from(sector_bar.join(sector, sector_bar.c.sector_id == sector.c.id))
        .where(
            sector_bar.c.sector_id.in_(sector_ids),
            sector.c.type.in_(CONCEPT_SECTOR_TYPES),
            sector_bar.c.source == CONCEPT_SOURCE,
        )
        .order_by(sector_bar.c.sector_id, sector_bar.c.trade_date)
    )
    raw_concepts = pd.read_sql(
        concept_statement,
        engine,
        parse_dates=["trade_date"],
    )
    concept_bars, universe_audit = filter_exploratory_concept_universe(raw_concepts)
    _, campaign_paths = build_concept_campaign_ledger(concept_bars)
    market_timing = load_timing_context()
    return DailyContext(
        stock_bars=stock_bars,
        stock_features=stock_features,
        campaign_paths=campaign_paths,
        market_timing=market_timing,
        coverage={
            "selected_symbols": len(symbols),
            "selected_concepts": len(sector_ids),
            "stock_bar_rows": len(stock_bars),
            "stock_feature_rows": len(stock_features),
            "concept_bar_rows": len(concept_bars),
            "campaign_path_rows": len(campaign_paths),
            "market_timing_rows": len(market_timing),
            **universe_audit,
        },
    )


def render_warming_failure_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_warming_failure_markdown(report: Mapping[str, Any]) -> str:
    baseline = _required_mapping(report, "baseline")
    candidate = _required_mapping(report, "candidate")
    adaptive = _required_mapping(report, "adaptive_diagnostic")
    qualification = _required_mapping(candidate, "qualification")
    audit = _required_mapping(candidate, "sequential_audit")
    validation = _required_mapping(audit, "validation")
    cash = candidate.get("cash")
    cash_map = cash if isinstance(cash, Mapping) else {}
    adaptive_cash = adaptive.get("cash")
    adaptive_cash_map = (
        adaptive_cash if isinstance(adaptive_cash, Mapping) else {}
    )
    candidate_attribution = _required_mapping(candidate, "attribution")
    comparisons = candidate_attribution.get("numeric_feature_comparisons", [])
    category_splits = candidate_attribution.get(
        "causal_category_split_metrics", {}
    )
    cases = candidate_attribution.get("individual_cases", [])
    lines = [
        "# 低吸 warming 失败归因与支撑相关性研究",
        "",
        f"- 研究状态：`{report.get('research_status')}`",
        "- 正式策略：`false`",
        f"- 原 V3 全历史：{_metric_text(_required_mapping(baseline, 'full_history'))}",
        f"- 候选全历史：{_metric_text(_required_mapping(candidate, 'full_history'))}",
        f"- 候选顺序验证：{_metric_text(validation)}",
        (
            f"- 四仓现金：`{int(cash_map.get('closed_trades') or 0)}` 笔，"
            f"胜率 `{_pct(cash_map.get('cash_win_rate_pct'))}`，"
            f"复利 `{_pct(cash_map.get('compound_return_pct'))}`，"
            f"回撤 `{_pct(cash_map.get('maximum_drawdown_pct'))}`"
        ),
        f"- 历史数字门：`{str(bool(qualification.get('historical_numeric_gates_passed'))).lower()}`",
        "",
        "## 候选规则",
        "",
        "rotation 保持 V3；warming 要求确认日最低价没有跌破支撑，且最多高于支撑 8%。",
        "8% 复用既有强收复阈值，没有在 blocks 4-5 搜索新数字。",
        "",
        "## 最终候选赢家/输家特征",
        "",
        "以下仅描述最终候选，不增加规则阈值。",
        "",
        "| 特征 | 开发赢家中位数 | 开发输家中位数 | 验证赢家中位数 | 验证输家中位数 | 跨段方向一致 |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for raw in comparisons if isinstance(comparisons, Sequence) else []:
        if not isinstance(raw, Mapping):
            continue
        development = raw.get("development")
        validation = raw.get("validation")
        development_map = development if isinstance(development, Mapping) else {}
        validation_map = validation if isinstance(validation, Mapping) else {}
        lines.append(
            "| `{feature}` | {development_winner} | {development_loser} | "
            "{validation_winner} | {validation_loser} | `{stable}` |".format(
                feature=raw.get("feature"),
                development_winner=_median_text(development_map.get("winner")),
                development_loser=_median_text(development_map.get("loser")),
                validation_winner=_median_text(validation_map.get("winner")),
                validation_loser=_median_text(validation_map.get("loser")),
                stable=str(bool(raw.get("median_direction_consistent"))).lower(),
            )
        )
    lines.extend(
        [
            "",
            "## 分类特征跨段审计",
            "",
            "通过仅表示两个历史分段的胜率均大于 60% 且平均收益为正，不构成新规则。",
            "",
            "| 特征 | 分组 | 开发笔数/胜率/均值 | 验证笔数/胜率/均值 | 两段描述通过 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if isinstance(category_splits, Mapping):
        for feature, raw_groups in category_splits.items():
            if not isinstance(raw_groups, Sequence):
                continue
            for raw in raw_groups:
                if not isinstance(raw, Mapping):
                    continue
                development = raw.get("development")
                validation = raw.get("validation")
                lines.append(
                    "| `{feature}` | `{group}` | {development} | {validation} | `{passed}` |".format(
                        feature=feature,
                        group=raw.get("id"),
                        development=_compact_split_metric(development),
                        validation=_compact_split_metric(validation),
                        passed=str(
                            bool(raw.get("both_splits_descriptive_pass"))
                        ).lower(),
                    )
                )
    lines.extend(
        [
            "",
            "## 最终候选逐笔",
        "",
        "| 信号 | 日期 | 股票 | 概念 | 波次 | 排名 | 支撑 | 最低价距支撑 | 收益 | 结果 |",
        "| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- |",
        ]
    )
    for raw in cases if isinstance(cases, Sequence) else []:
        if not isinstance(raw, Mapping):
            continue
        lines.append(
            "| `{signal_id}` | {entry_date} | {stock_name} `{vt_symbol}` | {concept_name} | {wave_number} | "
            "{dynamic_rank} | {support_line} | {gap} | {result} | {outcome_group} |".format(
                **raw,
                gap=_pct(raw.get("low_support_gap_pct")),
                result=_pct(raw.get("net_return_pct")),
            )
        )
    lines.extend(
        [
            "",
            "## Rotation 时效自适应诊断",
            "",
            "该候选来自本报告的事后失败归因，只能用于预注册下一版前向合同。",
            "- 规则：rotation 只接受支撑测试后下一交易日确认；warming 不变。",
            f"- 全历史：{_metric_text(_required_mapping(adaptive, 'full_history'))}",
            f"- 开发段：{_metric_text(_required_mapping(adaptive, 'development'))}",
            f"- 复用验证：{_metric_text(_required_mapping(adaptive, 'validation'))}",
            (
                f"- 四仓现金：`{int(adaptive_cash_map.get('closed_trades') or 0)}` 笔，"
                f"胜率 `{_pct(adaptive_cash_map.get('cash_win_rate_pct'))}`，"
                f"复利 `{_pct(adaptive_cash_map.get('compound_return_pct'))}`，"
                f"回撤 `{_pct(adaptive_cash_map.get('maximum_drawdown_pct'))}`"
            ),
            (
                "- 历史资格门：`{status}`；失败门：`{failed}`。".format(
                    status=str(
                        _required_mapping(adaptive, "qualification").get(
                            "status"
                        )
                    ),
                    failed=", ".join(
                        str(item)
                        for item in _required_mapping(
                            adaptive,
                            "qualification",
                        ).get("failed_gates", [])
                    )
                    or "none",
                )
            ),
            "- 正式策略：`false`；现有 V2 自然前向合同保持不变。",
            "",
            "## 未解除边界",
            "",
            *[f"- {item}" for item in report.get("boundaries", [])],
            "",
            "## 失败门",
            "",
            *[
                f"- `{gate}`"
                for gate in qualification.get("failed_gates", [])
            ],
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def archive_warming_failure_report(
    report: Mapping[str, Any],
    output_path: Path,
) -> dict[str, str]:
    json_path = output_path.resolve()
    markdown_path = json_path.with_suffix(".md")
    _write_immutable(json_path, render_warming_failure_json(report))
    _write_immutable(markdown_path, render_warming_failure_markdown(report))
    return {"json": str(json_path), "markdown": str(markdown_path)}


def _median_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return "null"
    return _number_text(value.get("median"))


def _compact_split_metric(value: object) -> str:
    if not isinstance(value, Mapping):
        return "0 / null / null"
    return "{} / {} / {}".format(
        int(value.get("closed_trades") or 0),
        _pct(value.get("win_rate_pct")),
        _pct(value.get("mean_net_return_pct")),
    )


def enrich_trade_feature_ledger(
    ledger: Sequence[Mapping[str, Any]],
    *,
    stock_features: pd.DataFrame,
    campaign_paths: pd.DataFrame,
    market_timing: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Attach exact daily context without nearest-date or future fallback."""

    stock_lookup = _frame_lookup(
        stock_features,
        identity=("vt_symbol", "trade_date"),
        label="stock feature",
    )
    campaign_lookup = _frame_lookup(
        campaign_paths,
        identity=("campaign_id", "trade_date"),
        label="campaign path",
    )
    timing_dates, timing_phases = _timing_history(market_timing)
    enriched: list[dict[str, Any]] = []
    for raw in ledger:
        row = dict(raw)
        features = dict(row["causal_features"])
        signal_key = (str(row["vt_symbol"]), str(row["entry_date"]))
        support_key = (
            str(row["vt_symbol"]),
            str(features["support_test_date"]),
        )
        campaign_key = (str(row["campaign_id"]), str(row["entry_date"]))
        signal_bar = stock_lookup.get(signal_key)
        support_bar = stock_lookup.get(support_key)
        campaign = campaign_lookup.get(campaign_key)
        if signal_bar is not None:
            _validate_context_cutoff(signal_bar, row["entry_date"], "stock feature")
        if support_bar is not None:
            _validate_context_cutoff(
                support_bar,
                features["support_test_date"],
                "support stock feature",
            )
        if campaign is not None:
            _validate_context_cutoff(campaign, row["entry_date"], "campaign path")
        previous_phase = _previous_phase(
            row["entry_date"], timing_dates, timing_phases
        )
        features.update(
            {
                "turnover_expansion": _context_number(
                    signal_bar, "turnover_expansion"
                ),
                "close_location": _context_number(signal_bar, "close_location"),
                "sessions_since_ignition": _context_integer(
                    signal_bar, "sessions_since_ignition"
                ),
                "signal_ma5_gap_pct": _price_gap(
                    signal_bar, "close_price", "ma5"
                ),
                "signal_ma10_gap_pct": _price_gap(
                    signal_bar, "close_price", "ma10"
                ),
                "signal_ma20_gap_pct": _price_gap(
                    signal_bar, "close_price", "ma20"
                ),
                "visible_high20_gap_pct": _price_gap(
                    signal_bar, "close_price", "prior_high20"
                ),
                "support_day_daily_return_pct": _context_number(
                    support_bar, "daily_return_pct"
                ),
                "support_day_volume_ratio_prior5": _context_number(
                    support_bar, "volume_ratio_prior5"
                ),
                "support_day_close_location": _context_number(
                    support_bar, "close_location"
                ),
                "campaign_day": _context_integer(campaign, "campaign_day"),
                "concept_gain_pct": _context_number(
                    campaign, "cumulative_gain_pct"
                ),
                "previous_market_phase": previous_phase,
                "market_phase_transition": (
                    f"{previous_phase}_to_{row['market_phase']}"
                    if previous_phase is not None
                    else None
                ),
                "exact_stock_context": signal_bar is not None,
                "exact_support_context": support_bar is not None,
                "exact_campaign_context": campaign is not None,
            }
        )
        row["causal_features"] = features
        enriched.append(row)
    return enriched


def _validate_source_contract(source: Mapping[str, Any]) -> None:
    if str(source.get("policy_version") or "") != SOURCE_POLICY_VERSION:
        raise ValueError("source policy version is not the frozen V3 contract")
    if source.get("formal_strategy") is not False:
        raise ValueError("source must remain a non-formal research proxy")


def _validate_enriched_identity(
    source: Mapping[str, Any],
    ledger: Sequence[Mapping[str, Any]],
) -> None:
    expected = sorted(
        str(row.get("signal_id") or "")
        for row in _required_rows(source, "trade_ledger")
        if str(row.get("variant") or "") == VARIANT
    )
    actual = sorted(str(row.get("signal_id") or "") for row in ledger)
    if actual != expected or len(actual) != len(set(actual)):
        raise ValueError("enriched ledger identities must equal frozen selected trades")
    for row in ledger:
        features = row.get("causal_features")
        outcome = row.get("outcome")
        if not isinstance(features, Mapping) or not isinstance(outcome, Mapping):
            raise ValueError("enriched ledger must preserve causal and outcome mappings")


def _candidate_qualification(
    rows: Sequence[Mapping[str, Any]],
    phase_metrics: Sequence[Mapping[str, Any]],
    audit: Mapping[str, Any],
    cash: Mapping[str, Any] | None,
) -> dict[str, Any]:
    failed: list[str] = []
    overall = _return_metrics(rows)
    if _number_or_zero(overall.get("win_rate_pct")) <= 60.0:
        failed.append("full_history_win_rate<=60pct")
    phase_by_id = {str(row["id"]): row for row in phase_metrics}
    for phase in (ROTATION_PHASE, WARMING_PHASE):
        metrics = phase_by_id.get(phase, {})
        if int(metrics.get("closed_trades") or 0) < 30:
            failed.append(f"full_history_phase_trades<30:{phase}")
        if _number_or_zero(metrics.get("win_rate_pct")) <= 60.0:
            failed.append(f"full_history_phase_win_rate<=60pct:{phase}")
        if _number_or_zero(metrics.get("mean_net_return_pct")) <= 0.0:
            failed.append(f"full_history_phase_mean_return<=0:{phase}")
        if _number_or_zero(metrics.get("profit_factor")) < 1.2:
            failed.append(f"full_history_phase_profit_factor<1.2:{phase}")
        if _number_or_zero(metrics.get("signal_compound_return_pct")) <= 0.0:
            failed.append(f"full_history_phase_compound<=0:{phase}")
    sequential = audit.get("qualification")
    if not isinstance(sequential, Mapping) or not sequential.get(
        "sequential_cross_regime_passed"
    ):
        failed.append("sequential_cross_regime_failed")
    if cash is None:
        failed.append("four_slot_cash_missing")
    else:
        if int(cash.get("closed_trades") or 0) <= 0:
            failed.append("four_slot_cash_closed_trades<=0")
        if _number_or_zero(cash.get("compound_return_pct")) <= 60.0:
            failed.append("four_slot_cash_compound<=60pct")
        if _number_or_zero(cash.get("maximum_drawdown_pct"), missing=-100.0) < -10.0:
            failed.append("four_slot_cash_drawdown<-10pct")
    return {
        "historical_numeric_gates_passed": not failed,
        "status": (
            "historical_reused_validation_candidate"
            if not failed
            else "historical_candidate_rejected"
        ),
        "failed_gates": failed,
    }


def _frame_lookup(
    frame: pd.DataFrame,
    *,
    identity: tuple[str, str],
    label: str,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if frame.empty:
        return {}
    missing = [column for column in identity if column not in frame]
    if missing:
        raise ValueError(f"{label} is missing identity columns: {missing}")
    normalized = frame.copy()
    normalized[identity[0]] = normalized[identity[0]].astype(str)
    normalized[identity[1]] = pd.to_datetime(
        normalized[identity[1]], errors="raise"
    ).dt.strftime("%Y-%m-%d")
    if normalized.duplicated(list(identity)).any():
        raise ValueError(f"{label} identities must be unique")
    return {
        (str(row[identity[0]]), str(row[identity[1]])): row
        for row in normalized.to_dict("records")
    }


def _timing_history(
    market_timing: pd.DataFrame,
) -> tuple[list[str], list[str]]:
    if market_timing.empty:
        return [], []
    missing = [
        column
        for column in ("source_date", "market_phase")
        if column not in market_timing
    ]
    if missing:
        raise ValueError(f"market timing is missing columns: {missing}")
    timing = market_timing.loc[:, ["source_date", "market_phase"]].copy()
    timing["source_date"] = pd.to_datetime(
        timing["source_date"], errors="raise"
    ).dt.strftime("%Y-%m-%d")
    if timing["source_date"].duplicated().any():
        raise ValueError("market timing dates must be unique")
    timing = timing.sort_values("source_date", kind="stable")
    return timing["source_date"].tolist(), timing["market_phase"].astype(str).tolist()


def _previous_phase(
    trade_date: str,
    timing_dates: Sequence[str],
    timing_phases: Sequence[str],
) -> str | None:
    position = bisect_left(timing_dates, trade_date) - 1
    return timing_phases[position] if position >= 0 else None


def _validate_context_cutoff(
    row: Mapping[str, Any],
    expected_date: object,
    label: str,
) -> None:
    cutoff = row.get("feature_cutoff_date")
    if cutoff is None or (isinstance(cutoff, float) and math.isnan(cutoff)):
        return
    if str(cutoff)[:10] != str(expected_date)[:10]:
        raise ValueError(f"{label} cutoff does not match its exact date")


def _context_number(
    row: Mapping[str, Any] | None,
    field: str,
) -> float | None:
    return _optional_number(row.get(field)) if row is not None else None


def _context_integer(
    row: Mapping[str, Any] | None,
    field: str,
) -> int | None:
    return _optional_integer(row.get(field)) if row is not None else None


def _price_gap(
    row: Mapping[str, Any] | None,
    price_field: str,
    reference_field: str,
) -> float | None:
    price = _context_number(row, price_field)
    reference = _context_number(row, reference_field)
    if price is None or reference is None or reference <= 0.0:
        return None
    return (price / reference - 1.0) * 100.0


def _index_signals(
    signals: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for signal in signals:
        signal_id = _required_text(signal, "signal_id", "signal")
        if signal_id in indexed:
            raise ValueError("signal identities must be unique")
        indexed[signal_id] = signal
    return indexed


def _joined_ledger_row(
    trade: Mapping[str, Any],
    signal: Mapping[str, Any],
) -> dict[str, Any]:
    signal_id = _required_text(trade, "signal_id", "trade")
    entry_date = _required_date_text(trade, "entry_date", "trade")
    signal_date = _required_date_text(signal, "signal_date", "signal")
    cutoff_date = _required_date_text(signal, "feature_cutoff_date", "signal")
    if entry_date != signal_date or cutoff_date != entry_date:
        raise ValueError("feature cutoff must equal entry date")
    _require_matching_identity(trade, signal, "campaign_id")
    _require_matching_identity(trade, signal, "sector_id")
    _require_matching_identity(trade, signal, "vt_symbol")
    support_price = _positive_number(signal, "support_price", "signal")
    signal_low = _positive_number(signal, "signal_low", "signal")
    signal_close = _positive_number(signal, "signal_close", "signal")
    reference_peak = _positive_number(signal, "reference_peak_price", "signal")
    net_return = _required_number(trade, "net_return_pct", "trade")
    time_block = _required_text(trade, "time_block", "trade")
    if time_block not in {*DEVELOPMENT_BLOCKS, *VALIDATION_BLOCKS}:
        raise ValueError(f"unexpected time block: {time_block}")
    market_phase = _required_text(trade, "market_phase", "trade")
    causal_features = {
        "signal_id": signal_id,
        "feature_cutoff_date": cutoff_date,
        "campaign_id": _required_text(signal, "campaign_id", "signal"),
        "sector_id": _required_text(signal, "sector_id", "signal"),
        "concept_name": _required_text(signal, "concept_name", "signal"),
        "vt_symbol": _required_text(signal, "vt_symbol", "signal"),
        "stock_name": _required_text(signal, "stock_name", "signal"),
        "market_phase": market_phase,
        "active_direction": str(signal.get("active_direction") or "UNKNOWN"),
        "danger_state": str(signal.get("danger_state") or "UNKNOWN"),
        "dynamic_rank": _required_integer(signal, "dynamic_rank", "signal"),
        "stock_leg_number": _required_integer(
            signal, "stock_leg_number", "signal"
        ),
        "wave_number": _required_integer(signal, "wave_number", "signal"),
        "required_support": _required_text(signal, "required_support", "signal"),
        "support_line": _required_text(signal, "support_line", "signal"),
        "support_depth": _required_integer(signal, "support_depth", "signal"),
        "support_test_date": _required_date_text(
            signal, "support_test_date", "signal"
        ),
        "support_test_session_gap": _required_integer(
            signal, "support_test_session_gap", "signal"
        ),
        "support_price": support_price,
        "signal_close": signal_close,
        "signal_low": signal_low,
        "signal_daily_return_pct": _required_number(
            signal, "signal_daily_return_pct", "signal"
        ),
        "volume_ratio_prior5": _optional_number(signal.get("volume_ratio_prior5")),
        "reference_peak_price": reference_peak,
        "peak_gap_pct": (signal_close / reference_peak - 1.0) * 100.0,
        "low_support_gap_pct": (signal_low / support_price - 1.0) * 100.0,
        "close_support_gap_pct": (signal_close / support_price - 1.0) * 100.0,
    }
    return {
        "signal_id": signal_id,
        "entry_date": entry_date,
        "entry_month": entry_date[:7],
        "time_block": time_block,
        "market_phase": market_phase,
        "campaign_id": causal_features["campaign_id"],
        "concept_name": causal_features["concept_name"],
        "vt_symbol": causal_features["vt_symbol"],
        "stock_name": causal_features["stock_name"],
        "causal_features": causal_features,
        "outcome_group": "winner" if net_return > 0.0 else "loser",
        "outcome": {
            "net_return_pct": net_return,
            "d1_net_return_pct": _optional_number(trade.get("d1_net_return_pct")),
            "exit_date": str(trade.get("exit_date") or "") or None,
            "exit_reason": str(trade.get("exit_reason") or "") or None,
            "holding_sessions": _optional_integer(trade.get("holding_sessions")),
            "mfe_pct": _optional_number(trade.get("mfe_pct")),
            "mae_pct": _optional_number(trade.get("mae_pct")),
        },
    }


def _require_matching_identity(
    trade: Mapping[str, Any],
    signal: Mapping[str, Any],
    field: str,
) -> None:
    if _required_text(trade, field, "trade") != _required_text(
        signal, field, "signal"
    ):
        raise ValueError(f"trade and signal {field} do not match")


def _warming_split_metrics(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    warming = [row for row in rows if row["market_phase"] == WARMING_PHASE]
    return {
        "development": _return_metrics(_rows_in_blocks(warming, DEVELOPMENT_BLOCKS)),
        "validation": _return_metrics(_rows_in_blocks(warming, VALIDATION_BLOCKS)),
    }


def _warming_feature_profiles(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    warming = [row for row in rows if row["market_phase"] == WARMING_PHASE]
    profile_rows: list[dict[str, Any]] = []
    for split, blocks in (
        ("development", DEVELOPMENT_BLOCKS),
        ("validation", VALIDATION_BLOCKS),
    ):
        selected = _rows_in_blocks(warming, blocks)
        for feature in (
            "dynamic_rank",
            "wave_number",
            "support_line",
            "support_test_session_gap",
            "signal_return_band",
            "volume_band",
            "peak_gap_band",
            "low_support_gap_band",
            "close_support_gap_band",
        ):
            groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
            for row in selected:
                groups[_feature_group(row["causal_features"], feature)].append(row)
            for group in sorted(groups):
                profile_rows.append(
                    {
                        "split": split,
                        "feature": feature,
                        "group": group,
                        **_return_metrics(groups[group]),
                    }
                )
    return profile_rows


def _candidate_attribution(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "scope": "final_selected_candidate_only",
        "threshold_search": False,
        "selection_effect": "none_descriptive_only",
        "profiled_trade_count": len(rows),
        "outcome_groups": _group_metrics(rows, "outcome_group"),
        "market_phases": _group_metrics(rows, "market_phase"),
        "time_blocks": _group_metrics(rows, "time_block"),
        "causal_category_metrics": {
            feature: _causal_group_metrics(rows, feature)
            for feature in CANDIDATE_CAUSAL_CATEGORY_FEATURES
        },
        "causal_category_split_metrics": {
            feature: _causal_split_group_metrics(rows, feature)
            for feature in CANDIDATE_CAUSAL_CATEGORY_FEATURES
        },
        "numeric_feature_comparisons": [
            _numeric_feature_comparison(rows, feature)
            for feature in CANDIDATE_NUMERIC_FEATURES
        ],
        "individual_cases": [_case_row(row) for row in rows],
    }


def _causal_group_metrics(
    rows: Sequence[Mapping[str, Any]],
    feature: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        features = _required_mapping(row, "causal_features")
        groups[str(features.get(feature) or "UNKNOWN")].append(row)
    return [
        {"id": identifier, **_return_metrics(groups[identifier])}
        for identifier in sorted(groups)
    ]


def _causal_split_group_metrics(
    rows: Sequence[Mapping[str, Any]],
    feature: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        features = _required_mapping(row, "causal_features")
        groups[str(features.get(feature) or "UNKNOWN")].append(row)

    result: list[dict[str, Any]] = []
    for identifier in sorted(groups):
        development = _return_metrics(
            _rows_in_blocks(groups[identifier], DEVELOPMENT_BLOCKS)
        )
        validation = _return_metrics(
            _rows_in_blocks(groups[identifier], VALIDATION_BLOCKS)
        )
        both_present = all(
            int(metrics.get("closed_trades") or 0) > 0
            for metrics in (development, validation)
        )
        both_win = both_present and all(
            _number_or_zero(metrics.get("win_rate_pct")) > 60.0
            for metrics in (development, validation)
        )
        both_mean = both_present and all(
            _number_or_zero(metrics.get("mean_net_return_pct")) > 0.0
            for metrics in (development, validation)
        )
        result.append(
            {
                "id": identifier,
                "development": development,
                "validation": validation,
                "both_splits_present": both_present,
                "both_splits_win_rate_gt_60pct": both_win,
                "both_splits_mean_return_gt_0": both_mean,
                "both_splits_descriptive_pass": both_win and both_mean,
            }
        )
    return result


def _numeric_feature_comparison(
    rows: Sequence[Mapping[str, Any]],
    feature: str,
) -> dict[str, Any]:
    split_comparisons: dict[str, dict[str, Any]] = {}
    directions: list[str] = []
    for split, blocks in (
        ("development", DEVELOPMENT_BLOCKS),
        ("validation", VALIDATION_BLOCKS),
    ):
        split_rows = _rows_in_blocks(rows, blocks)
        winner = _numeric_feature_summary(split_rows, feature, "winner")
        loser = _numeric_feature_summary(split_rows, feature, "loser")
        direction = _median_direction(winner, loser)
        split_comparisons[split] = {
            "winner": winner,
            "loser": loser,
            "winner_minus_loser_median": _median_difference(winner, loser),
            "median_direction": direction,
        }
        directions.append(direction)
    comparable = {"winner_higher", "winner_lower", "equal"}
    return {
        "feature": feature,
        **split_comparisons,
        "median_direction_consistent": (
            len(directions) == 2
            and directions[0] in comparable
            and directions[0] == directions[1]
        ),
    }


def _numeric_feature_summary(
    rows: Sequence[Mapping[str, Any]],
    feature: str,
    outcome_group: str,
) -> dict[str, Any]:
    selected = [row for row in rows if row["outcome_group"] == outcome_group]
    values = [
        value
        for row in selected
        if (value := _optional_number(row["causal_features"].get(feature))) is not None
    ]
    return {
        "trades": len(selected),
        "available_values": len(values),
        "mean": sum(values) / len(values) if values else None,
        "median": median(values) if values else None,
    }


def _median_difference(
    winner: Mapping[str, Any],
    loser: Mapping[str, Any],
) -> float | None:
    winner_median = _optional_number(winner.get("median"))
    loser_median = _optional_number(loser.get("median"))
    if winner_median is None or loser_median is None:
        return None
    return winner_median - loser_median


def _median_direction(
    winner: Mapping[str, Any],
    loser: Mapping[str, Any],
) -> str:
    difference = _median_difference(winner, loser)
    if difference is None:
        return "not_comparable"
    if math.isclose(difference, 0.0, abs_tol=1e-12):
        return "equal"
    return "winner_higher" if difference > 0.0 else "winner_lower"


def _feature_group(features: Mapping[str, Any], feature: str) -> str:
    if feature in {
        "dynamic_rank",
        "wave_number",
        "support_line",
        "support_test_session_gap",
    }:
        return str(features.get(feature))
    if feature == "signal_return_band":
        return _band(
            features.get("signal_daily_return_pct"),
            ((9.5, "8_to_9_5"), (10.0, "9_5_to_10")),
            "above_10",
        )
    if feature == "volume_band":
        return _band(
            features.get("volume_ratio_prior5"),
            ((1.0, "below_1"), (1.5, "1_to_1_5")),
            "at_least_1_5",
        )
    if feature == "peak_gap_band":
        return _band(
            features.get("peak_gap_pct"),
            ((-3.0, "at_most_minus_3"), (-1.0, "minus_3_to_minus_1")),
            "above_minus_1",
        )
    if feature == "low_support_gap_band":
        return _band(
            features.get("low_support_gap_pct"),
            ((0.0, "below_support"), (1.0, "support_to_plus_1"), (8.0, "plus_1_to_plus_8")),
            "above_plus_8",
        )
    if feature == "close_support_gap_band":
        return _band(
            features.get("close_support_gap_pct"),
            ((10.0, "below_10"),),
            "at_least_10",
        )
    raise ValueError(f"unknown feature profile: {feature}")


def _band(
    value: object,
    thresholds: Sequence[tuple[float, str]],
    final_label: str,
) -> str:
    number = _optional_number(value)
    if number is None:
        return "missing"
    for upper, label in thresholds:
        if number < upper:
            return label
    return final_label


def _group_metrics(
    rows: Sequence[Mapping[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or "UNKNOWN")].append(row)
    return [
        {"id": identifier, **_return_metrics(groups[identifier])}
        for identifier in sorted(groups)
    ]


def _return_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row["outcome"]["net_return_pct"]) for row in rows]
    if not returns:
        return {
            "closed_trades": 0,
            "winning_trades": 0,
            "win_rate_pct": None,
            "mean_net_return_pct": None,
            "profit_factor": None,
            "signal_compound_return_pct": None,
        }
    wins = [value for value in returns if value > 0.0]
    losses = [value for value in returns if value < 0.0]
    return {
        "closed_trades": len(returns),
        "winning_trades": len(wins),
        "win_rate_pct": len(wins) / len(returns) * 100.0,
        "mean_net_return_pct": sum(returns) / len(returns),
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "signal_compound_return_pct": (
            math.prod(1.0 + value / 100.0 for value in returns) - 1.0
        )
        * 100.0,
    }


def _case_row(row: Mapping[str, Any]) -> dict[str, Any]:
    features = row["causal_features"]
    outcome = row["outcome"]
    return {
        "signal_id": row["signal_id"],
        "entry_date": row["entry_date"],
        "time_block": row["time_block"],
        "vt_symbol": row["vt_symbol"],
        "stock_name": row["stock_name"],
        "campaign_id": row["campaign_id"],
        "concept_name": row["concept_name"],
        "wave_number": features["wave_number"],
        "dynamic_rank": features["dynamic_rank"],
        "support_line": features["support_line"],
        "support_test_date": features["support_test_date"],
        "support_test_session_gap": features["support_test_session_gap"],
        "signal_daily_return_pct": features["signal_daily_return_pct"],
        "volume_ratio_prior5": features["volume_ratio_prior5"],
        "peak_gap_pct": features["peak_gap_pct"],
        "low_support_gap_pct": features["low_support_gap_pct"],
        "close_support_gap_pct": features["close_support_gap_pct"],
        "turnover_expansion": features.get("turnover_expansion"),
        "close_location": features.get("close_location"),
        "sessions_since_ignition": features.get("sessions_since_ignition"),
        "signal_ma5_gap_pct": features.get("signal_ma5_gap_pct"),
        "signal_ma10_gap_pct": features.get("signal_ma10_gap_pct"),
        "signal_ma20_gap_pct": features.get("signal_ma20_gap_pct"),
        "campaign_day": features.get("campaign_day"),
        "concept_gain_pct": features.get("concept_gain_pct"),
        "previous_market_phase": features.get("previous_market_phase"),
        "market_phase_transition": features.get("market_phase_transition"),
        "outcome_group": row["outcome_group"],
        "net_return_pct": outcome["net_return_pct"],
        "d1_net_return_pct": outcome["d1_net_return_pct"],
        "exit_date": outcome["exit_date"],
        "exit_reason": outcome["exit_reason"],
    }


def _representative_cases(
    rows: Sequence[Mapping[str, Any]],
    *,
    blocks: Sequence[str],
    outcome_group: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in _rows_in_blocks(rows, blocks)
        if row["market_phase"] == WARMING_PHASE
        and row["outcome_group"] == outcome_group
    ]
    selected.sort(
        key=lambda row: (
            float(row["outcome"]["net_return_pct"]),
            row["entry_date"],
            row["signal_id"],
        ),
        reverse=outcome_group == "winner",
    )
    return [_case_row(row) for row in selected[:limit]]


def _rows_in_blocks(
    rows: Sequence[Mapping[str, Any]],
    blocks: Sequence[str],
) -> list[Mapping[str, Any]]:
    allowed = set(blocks)
    return [row for row in rows if row["time_block"] in allowed]


def _required_rows(
    source: Mapping[str, Any],
    field: str,
) -> list[Mapping[str, Any]]:
    value = source.get(field)
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise ValueError(f"{field} must be a list of mappings")
    return value


def _required_text(row: Mapping[str, Any], field: str, label: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ValueError(f"{label} {field} is required")
    return value


def _required_date_text(row: Mapping[str, Any], field: str, label: str) -> str:
    value = _required_text(row, field, label)
    if len(value) < 10:
        raise ValueError(f"{label} {field} must contain an ISO date")
    return value[:10]


def _required_number(row: Mapping[str, Any], field: str, label: str) -> float:
    value = _optional_number(row.get(field))
    if value is None:
        raise ValueError(f"{label} {field} must be finite")
    return value


def _positive_number(row: Mapping[str, Any], field: str, label: str) -> float:
    value = _required_number(row, field, label)
    if value <= 0.0:
        raise ValueError(f"{label} {field} must be positive")
    return value


def _required_integer(row: Mapping[str, Any], field: str, label: str) -> int:
    value = _optional_integer(row.get(field))
    if value is None:
        raise ValueError(f"{label} {field} must be an integer")
    return value


def _optional_integer(value: object) -> int | None:
    number = _optional_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number_or_zero(value: object, *, missing: float = 0.0) -> float:
    number = _optional_number(value)
    return number if number is not None else missing


def _required_mapping(
    row: Mapping[str, Any],
    field: str,
) -> Mapping[str, Any]:
    value = row.get(field)
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _metric_text(metrics: Mapping[str, Any]) -> str:
    return (
        f"`{int(metrics.get('closed_trades') or 0)}` 笔，"
        f"胜率 `{_pct(metrics.get('win_rate_pct'))}`，"
        f"均值 `{_pct(metrics.get('mean_net_return_pct'))}`，"
        f"PF `{_number_text(metrics.get('profit_factor'))}`"
    )


def _pct(value: object) -> str:
    number = _optional_number(value)
    return "null" if number is None else f"{number:+.4f}%"


def _number_text(value: object) -> str:
    number = _optional_number(value)
    return "null" if number is None else f"{number:.4f}"


def _write_immutable(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") == contents:
            return
        raise ValueError(f"artifact already exists with different contents: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(contents, encoding="utf-8")
    temporary.replace(path)
