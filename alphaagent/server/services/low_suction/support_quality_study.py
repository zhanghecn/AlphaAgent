"""Sequential V6 study for main-rise quality on frozen support-day entries."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.research_runtime import require_research_runtime

from .causal_leader_pullback import MINIMUM_REQUIRED_SUPPORT
from .causal_leader_pullback_study import (
    build_causal_stock_features,
    build_concept_campaign_ledger,
    build_dynamic_leader_paths,
    build_named_case_audit,
    load_causal_leader_pullback_inputs,
    prepare_dynamic_leader_paths,
    simulate_four_slot_cash,
)
from .dynamic_concept_campaign import MEMBERSHIP_EVIDENCE_LEVEL
from .support_day_entry import (
    DEVELOPMENT_BLOCKS,
    DOUBLE_ROUND_TRIP_COST_PCT,
    ROUND_TRIP_COST_PCT,
    RULE_EXACT_HOLD,
    apply_pre_registered_rules,
    assign_common_time_blocks,
    build_support_day_events,
    execute_d1_close_trades,
    filter_common_rule_universe,
    reprice_d1_close_trades,
    summarize_d1_trades,
)
from .support_day_study import (
    ENVIRONMENT_COLUMNS,
    apply_frozen_environment_policy,
    freeze_development_environments,
)
from .support_quality import (
    MIN_PROFIT_FACTOR,
    MIN_WIN_RATE_PCT,
    QUALITY_FEATURES,
    QualityLeaf,
    apply_quality_leaf,
    describe_quality_tree,
    enrich_support_quality_events,
    evaluate_sequential_late_blocks,
    fit_development_quality_tree,
    freeze_development_quality_leaf,
    quality_leaf_from_dict,
)


STUDY_VERSION = "low-suction-support-quality-study-v1"
POLICY_VERSION = "causal-leader-support-quality-v6"
MIN_TOTAL_TRADES = 100
MIN_CASH_COMPOUND_PCT = 60.0
MIN_CASH_DRAWDOWN_PCT = -10.0
MIN_MATERIAL_ENVIRONMENT_TRADES = 30
MIN_MATERIAL_ENVIRONMENT_DAYS = 20


@dataclass(frozen=True)
class QualityValidation:
    environment_freeze: Mapping[str, Any]
    block_4: Mapping[str, Any]
    block_5: Mapping[str, Any] | None
    late_validation_passed: bool
    qualification: Mapping[str, Any]
    four_slot_cash: Mapping[str, Any]
    double_cost_four_slot_cash: Mapping[str, Any]
    material_environment_metrics: tuple[Mapping[str, Any], ...]
    visible_trades: pd.DataFrame


def evaluate_selected_quality_rule(
    selected_leaf_trades: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    coverage: Mapping[str, Any],
) -> QualityValidation:
    """Freeze one environment map and expose late blocks in sequence."""

    environment_freeze = freeze_development_environments(selected_leaf_trades)
    routed = apply_frozen_environment_policy(
        selected_leaf_trades,
        _mapping(environment_freeze.get("policy_by_environment")),
    )
    late = evaluate_sequential_late_blocks(routed)
    visible_blocks = set(DEVELOPMENT_BLOCKS) | {"block_4"}
    if bool(_mapping(late.get("block_4")).get("passed")):
        visible_blocks.add("block_5")
    visible = routed.loc[routed["time_block"].isin(visible_blocks)].copy()
    visible = _sort_trades(visible)

    if not bool(late["late_validation_passed"]):
        failed_block = "block_4" if late["block_5"] is None else "block_5"
        qualification = _unvalidated_qualification(
            failed_block,
            coverage=coverage,
        )
        return QualityValidation(
            environment_freeze=environment_freeze,
            block_4=_mapping(late["block_4"]),
            block_5=(
                _mapping(late["block_5"])
                if late["block_5"] is not None
                else None
            ),
            late_validation_passed=False,
            qualification=qualification,
            four_slot_cash={},
            double_cost_four_slot_cash={},
            material_environment_metrics=(),
            visible_trades=visible,
        )

    double_cost = reprice_d1_close_trades(
        routed,
        round_trip_cost_pct=DOUBLE_ROUND_TRIP_COST_PCT,
    )
    cash = simulate_four_slot_cash(routed, stock_bars)
    double_cost_cash = simulate_four_slot_cash(double_cost, stock_bars)
    environment_metrics = tuple(_material_environment_metrics(routed, stock_bars))
    qualification = _evaluate_final_quality_rule(
        routed,
        cash_result=cash,
        double_cost_cash_result=double_cost_cash,
        environment_metrics=environment_metrics,
        coverage=coverage,
    )
    return QualityValidation(
        environment_freeze=environment_freeze,
        block_4=_mapping(late["block_4"]),
        block_5=_mapping(late["block_5"]),
        late_validation_passed=True,
        qualification=qualification,
        four_slot_cash=cash,
        double_cost_four_slot_cash=double_cost_cash,
        material_environment_metrics=environment_metrics,
        visible_trades=_sort_trades(routed),
    )


def build_support_quality_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
    enriched_events: pd.DataFrame,
    executed_trades: pd.DataFrame,
    tree_description: Mapping[str, Any],
    leaf_freeze: Mapping[str, Any],
    validation: QualityValidation | None,
    named_case_audit: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a report that never serializes an unopened validation block."""

    selected_leaf = leaf_freeze.get("selected_leaf")
    if selected_leaf is None:
        qualification = _no_leaf_qualification(coverage)
        environment_freeze: Mapping[str, Any] = {}
        block_4 = None
        block_5 = None
        visible_trades = pd.DataFrame()
        cash: Mapping[str, Any] = {}
        double_cost_cash: Mapping[str, Any] = {}
        environment_metrics: Sequence[Mapping[str, Any]] = ()
    else:
        if validation is None:
            raise ValueError("selected quality leaf requires validation evidence")
        qualification = validation.qualification
        environment_freeze = validation.environment_freeze
        block_4 = validation.block_4
        block_5 = validation.block_5
        visible_trades = validation.visible_trades
        cash = validation.four_slot_cash
        double_cost_cash = validation.double_cost_four_slot_cash
        environment_metrics = validation.material_environment_metrics

    development = executed_trades.loc[
        executed_trades.get("time_block", pd.Series(dtype=str)).isin(
            DEVELOPMENT_BLOCKS
        )
    ].copy()
    report = {
        "study_version": STUDY_VERSION,
        "policy_version": POLICY_VERSION,
        "research_status": _research_status(selected_leaf, validation),
        "selected_leaf": selected_leaf,
        "formal_strategy": bool(qualification.get("formal_strategy", False)),
        "formal_metrics": qualification.get("formal_metrics"),
        "contract": {
            "base_rule": RULE_EXACT_HOLD,
            "entry": "completed exact MA5/MA10 support-test close",
            "exit": "next symbol trading-session official close",
            "quality_features": list(QUALITY_FEATURES),
            "selection_blocks": sorted(DEVELOPMENT_BLOCKS),
            "validation_order": ["block_4", "block_5"],
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "double_round_trip_cost_pct": DOUBLE_ROUND_TRIP_COST_PCT,
            "cash": "100000 CNY, four slots, one concurrent slot per concept",
        },
        "data_quality": {
            "membership_evidence": MEMBERSHIP_EVIDENCE_LEVEL,
            "strict_historical_membership": bool(
                int(coverage.get("strict_historical_membership_rows") or 0) > 0
            ),
            "preclose_execution_available": bool(
                int(coverage.get("preclose_execution_rows") or 0) > 0
            ),
            "entry_price_evidence": "same_close_research_proxy",
            "minutes_used": False,
            "fund_flow_used": False,
            "environment_used_by_tree": False,
        },
        "coverage": {
            **dict(coverage),
            "enriched_exact_support_events": int(len(enriched_events)),
            "complete_quality_events": int(
                enriched_events.get(
                    "quality_feature_complete", pd.Series(dtype=bool)
                ).fillna(False).astype(bool).sum()
            ),
            "executed_d1_trades": int(len(executed_trades)),
            "visible_selected_trades": int(len(visible_trades)),
        },
        "development_tree": dict(tree_description),
        "leaf_freeze": dict(leaf_freeze),
        "environment_freeze": dict(environment_freeze),
        "block_4": block_4,
        "block_5": block_5,
        "qualification": dict(qualification),
        "overall_metrics": qualification.get("overall_metrics"),
        "four_slot_cash": dict(cash),
        "double_cost_four_slot_cash": dict(double_cost_cash),
        "material_environment_metrics": [dict(row) for row in environment_metrics],
        "development_trade_ledger": _records(_sort_trades(development)),
        "selected_trade_ledger": _records(visible_trades),
        "named_case_audit": [dict(row) for row in named_case_audit],
        "fingerprints": dict(fingerprints),
        "boundaries": [
            "The V5 exact-support predicate, common calendar and D+1 close exit are unchanged.",
            "The tree and leaf nomination use blocks 1-3 only.",
            "Block 5 outcomes and trade rows stay absent unless block 4 passes.",
            "GOLD/SILVER and market phase cannot change the selected entry leaf.",
            "Named stocks are attribution only and cannot select a leaf.",
            "Current membership and the D close remain historical research proxies.",
        ],
        "reproduce": (
            "docker compose --profile research run --rm -T --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace "
            "-e PYTHONPATH=/workspace:/app/third_party/akshare "
            "alphaagent-research python -m "
            "alphaagent.server.services.low_suction.cli "
            "v6-support-quality-study --format json"
        ),
    }
    return _json_safe(report)


def run_support_quality_study() -> dict[str, Any]:
    """Run one database load and one pre-registered V6 replay."""

    from .research_protocol import fingerprint_frame

    require_research_runtime()
    inputs = load_causal_leader_pullback_inputs()
    stock_features = build_causal_stock_features(inputs.stock_bars)
    campaigns, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    leader_paths, rank_coverage = build_dynamic_leader_paths(
        campaign_paths,
        inputs.memberships,
        stock_features,
    )
    prepared = prepare_dynamic_leader_paths(
        leader_paths,
        inputs.market_timing,
        support_match_mode=MINIMUM_REQUIRED_SUPPORT,
    )
    raw_events = build_support_day_events(
        leader_paths,
        prepared.campaigns.daily_ledger,
        inputs.market_timing,
    )
    common_events = filter_common_rule_universe(raw_events)
    common_events = assign_common_time_blocks(
        common_events,
        event_dates=common_events["signal_date"],
    )
    exact_events = apply_pre_registered_rules(common_events)
    exact_events = exact_events.loc[
        exact_events["rule_id"].eq(RULE_EXACT_HOLD)
    ].reset_index(drop=True)
    enriched_events = enrich_support_quality_events(exact_events, leader_paths)
    executed_trades = execute_d1_close_trades(enriched_events, stock_features)

    discovery = fit_development_quality_tree(executed_trades)
    tree_description = describe_quality_tree(discovery)
    development_cash = _development_leaf_cash_results(
        executed_trades,
        discovery.leaves,
        stock_features,
    )
    leaf_freeze = freeze_development_quality_leaf(
        executed_trades,
        discovery,
        development_cash,
    )
    selected_leaf = leaf_freeze.get("selected_leaf")
    validation: QualityValidation | None = None
    selected_leaf_object: QualityLeaf | None = None
    if isinstance(selected_leaf, Mapping):
        selected_leaf_object = quality_leaf_from_dict(selected_leaf)
        leaf_trades = executed_trades.loc[
            apply_quality_leaf(executed_trades, selected_leaf_object)
        ].reset_index(drop=True)
        validation = evaluate_selected_quality_rule(
            leaf_trades,
            stock_features,
            coverage=inputs.coverage,
        )

    visible_trades = (
        validation.visible_trades if validation is not None else pd.DataFrame()
    )
    base_cases = build_named_case_audit(
        leader_paths,
        enriched_events,
        visible_trades,
        prepared.waves,
        prepared.campaigns.daily_ledger,
    )
    named_cases = _augment_named_cases(
        base_cases,
        enriched_events,
        selected_leaf_object,
        (
            _mapping(validation.environment_freeze.get("policy_by_environment"))
            if validation is not None
            else {}
        ),
        visible_trades,
    )

    coverage = {
        **dict(inputs.coverage),
        **dict(rank_coverage),
        "concept_campaigns": int(len(campaigns)),
        "leader_path_rows": int(len(leader_paths)),
        "raw_support_day_events": int(len(raw_events)),
        "common_support_day_events": int(len(common_events)),
        "exact_support_events": int(len(exact_events)),
        "preclose_execution_rows": 0,
    }
    fingerprints: dict[str, Mapping[str, Any]] = dict(inputs.fingerprints)
    _add_fingerprint(
        fingerprints,
        "v6_enriched_exact_support_events",
        enriched_events,
        ("signal_id",),
        fingerprint_frame,
    )
    identity_columns = [
        column
        for column in ("signal_id", "time_block", "entry_date", "exit_date")
        if column in executed_trades
    ]
    _add_fingerprint(
        fingerprints,
        "v6_d1_execution_identities",
        executed_trades.loc[:, identity_columns],
        ("signal_id",),
        fingerprint_frame,
    )
    development_trades = executed_trades.loc[
        executed_trades["time_block"].isin(DEVELOPMENT_BLOCKS)
    ]
    _add_fingerprint(
        fingerprints,
        "v6_development_d1_trades",
        development_trades,
        ("signal_id",),
        fingerprint_frame,
    )
    fingerprints["v6_development_tree"] = {
        "fingerprint": tree_description["model_fingerprint"],
        "development_rows": tree_description["development_rows"],
        "incomplete_feature_rows": tree_description["incomplete_feature_rows"],
    }
    _add_fingerprint(
        fingerprints,
        "v6_visible_selected_trades",
        visible_trades,
        ("signal_id",),
        fingerprint_frame,
    )
    return build_support_quality_report(
        coverage=coverage,
        fingerprints=fingerprints,
        enriched_events=enriched_events,
        executed_trades=executed_trades,
        tree_description=tree_description,
        leaf_freeze=leaf_freeze,
        validation=validation,
        named_case_audit=named_cases,
    )


def render_support_quality_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_support_quality_markdown(report: Mapping[str, Any]) -> str:
    tree = _mapping(report.get("development_tree"))
    freeze = _mapping(report.get("leaf_freeze"))
    qualification = _mapping(report.get("qualification"))
    lines = [
        "# AlphaAgent 主升龙头支撑质量低吸 V6",
        "",
        f"规则版本：`{report.get('policy_version')}`  ",
        f"研究状态：`{report.get('research_status')}`  ",
        f"开发期冻结叶：`{_leaf_label(report.get('selected_leaf'))}`  ",
        f"历史代理门：`{qualification.get('historical_proxy_gate_passed', False)}`  ",
        f"正式策略：`{str(report.get('formal_strategy', False)).lower()}`",
        "",
        "## 固定树合同",
        "",
        f"- 特征：`{', '.join(tree.get('features') or [])}`",
        f"- 完整开发样本：`{tree.get('development_rows', 0)}`",
        f"- 缺失特征样本：`{tree.get('incomplete_feature_rows', 0)}`",
        f"- 模型指纹：`{tree.get('model_fingerprint')}`",
        "",
        "## 开发叶子",
        "",
        "| 叶子 | 条件 | 成交 | 胜率 | 均值 | PF | 双成本均值 | 正向块 | 四仓复利 | 入围 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in freeze.get("leaf_metrics") or []:
        metric = _mapping(row)
        lines.append(
            "| {leaf} | {conditions} | {trades} | {win} | {mean} | {pf} | "
            "{double} | {blocks} | {cash} | {passed} |".format(
                leaf=metric.get("rule_id"),
                conditions=_condition_text(metric.get("conditions") or []),
                trades=metric.get("development_closed_trades", 0),
                win=_pct(metric.get("development_win_rate_pct")),
                mean=_pct(
                    metric.get("development_mean_net_return_pct"), signed=True
                ),
                pf=_number(metric.get("development_profit_factor")),
                double=_pct(
                    metric.get("development_double_cost_mean_pct"), signed=True
                ),
                blocks=metric.get("development_stable_blocks", 0),
                cash=_pct(
                    metric.get("development_cash_compound_pct"), signed=True
                ),
                passed=metric.get("nomination_passed", False),
            )
        )
    if not freeze.get("leaf_metrics"):
        lines.append("| - | - | 0 | - | - | - | - | 0 | - | False |")

    lines.extend(["", "## 冻结行情表", ""])
    environment = _mapping(report.get("environment_freeze"))
    policies = _mapping(environment.get("policy_by_environment"))
    if policies:
        lines.extend(f"- `{key}`：`{value}`" for key, value in policies.items())
    else:
        lines.append("- 未冻结：开发期没有合格质量叶。")

    lines.extend(["", "## 顺序样本外", ""])
    lines.append(_block_line("block 4", report.get("block_4")))
    lines.append(_block_line("block 5", report.get("block_5")))
    lines.extend(["", "## 最终四仓与资格", ""])
    overall = _mapping(report.get("overall_metrics"))
    cash = _mapping(report.get("four_slot_cash"))
    lines.extend(
        [
            f"- 成交：`{overall.get('closed_trades', 0)}`",
            f"- 胜率：`{_pct(overall.get('win_rate_pct'))}`",
            f"- 单笔均值：`{_pct(overall.get('mean_net_return_pct'), signed=True)}`",
            f"- PF：`{_number(overall.get('profit_factor'))}`",
            f"- 四仓复利：`{_pct(cash.get('compound_return_pct'), signed=True)}`",
            f"- 四仓最大回撤：`{_pct(cash.get('maximum_drawdown_pct'), signed=True)}`",
            f"- 合格物质行情：`{len(qualification.get('qualified_material_environments') or [])}`",
            f"- 失败门：`{', '.join(qualification.get('failed_gates') or []) or 'none'}`",
            f"- 正式阻断：`{', '.join(qualification.get('formal_blockers') or []) or 'none'}`",
        ]
    )

    lines.extend(["", "## 参考龙头", ""])
    for case in report.get("named_case_audit") or []:
        item = _mapping(case)
        counts = _mapping(item.get("quality_counts"))
        reasons = _mapping(item.get("exclusion_reasons"))
        lines.append(
            f"- {item.get('stock_name')} `{item.get('vt_symbol')}`："
            f"精确支撑 `{counts.get('exact_support_events', 0)}`，"
            f"质量叶匹配 `{counts.get('quality_leaf_matches', 0)}`，"
            f"可见成交 `{counts.get('visible_trades', 0)}`；"
            f"排除 `{json.dumps(reasons, ensure_ascii=False, sort_keys=True)}`。"
        )
    lines.extend(["", "## 研究边界", ""])
    lines.extend(f"- {value}" for value in report.get("boundaries") or [])
    lines.extend(
        ["", "## Reproduce", "", "```bash", str(report.get("reproduce") or ""), "```"]
    )
    return "\n".join(lines).rstrip() + "\n"


def _development_leaf_cash_results(
    trades: pd.DataFrame,
    leaves: Sequence[QualityLeaf],
    stock_bars: pd.DataFrame,
) -> dict[str, Mapping[str, Any]]:
    development = trades.loc[trades["time_block"].isin(DEVELOPMENT_BLOCKS)]
    return {
        leaf.rule_id: simulate_four_slot_cash(
            development.loc[apply_quality_leaf(development, leaf)],
            stock_bars,
        )
        for leaf in leaves
    }


def _evaluate_final_quality_rule(
    trades: pd.DataFrame,
    *,
    cash_result: Mapping[str, Any],
    double_cost_cash_result: Mapping[str, Any],
    environment_metrics: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    overall = summarize_d1_trades(trades)
    failed: list[str] = []
    if int(overall["closed_trades"]) < MIN_TOTAL_TRADES:
        failed.append("closed_trades<100")
    if float(overall["win_rate_pct"] or 0.0) <= MIN_WIN_RATE_PCT:
        failed.append("win_rate<=60pct")
    if float(overall["mean_net_return_pct"] or 0.0) <= 0.0:
        failed.append("mean_return<=0")
    if float(overall["profit_factor"] or 0.0) < MIN_PROFIT_FACTOR:
        failed.append("profit_factor<1.2")
    if float(cash_result.get("compound_return_pct") or 0.0) <= MIN_CASH_COMPOUND_PCT:
        failed.append("cash_compound<=60pct")
    drawdown = _finite_or_none(cash_result.get("maximum_drawdown_pct"))
    if drawdown is None or drawdown < MIN_CASH_DRAWDOWN_PCT:
        failed.append("cash_drawdown<-10pct")
    if float(double_cost_cash_result.get("compound_return_pct") or 0.0) <= 0.0:
        failed.append("double_cost_compound<=0")

    qualified_environments = [
        str(metric["environment_key"])
        for metric in environment_metrics
        if bool(metric.get("qualified_material_environment"))
    ]
    if len(qualified_environments) < 2:
        failed.append("qualified_material_environments<2")
    historical_passed = not failed
    blockers = _formal_blockers(
        coverage,
        required_preclose_rows=int(overall["closed_trades"]),
    )
    formal_strategy = historical_passed and not blockers
    return {
        "historical_proxy_gate_passed": historical_passed,
        "formal_strategy": formal_strategy,
        "formal_metrics": (
            {
                "d1": overall,
                "four_slot_cash": dict(cash_result),
                "material_environments": [dict(row) for row in environment_metrics],
            }
            if formal_strategy
            else None
        ),
        "overall_metrics": overall,
        "qualified_material_environments": qualified_environments,
        "failed_gates": failed,
        "formal_blockers": blockers,
    }


def _material_environment_metrics(
    trades: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> list[dict[str, Any]]:
    keyed = _with_environment_key(trades)
    rows: list[dict[str, Any]] = []
    for environment, group in keyed.groupby("environment_key", sort=True):
        summary = summarize_d1_trades(group)
        cash = simulate_four_slot_cash(group, stock_bars)
        trade_days = int(
            pd.to_datetime(group["entry_date"], errors="coerce")
            .dropna()
            .dt.normalize()
            .nunique()
        )
        drawdown = _finite_or_none(cash.get("maximum_drawdown_pct"))
        qualified = bool(
            int(summary["closed_trades"]) >= MIN_MATERIAL_ENVIRONMENT_TRADES
            and trade_days >= MIN_MATERIAL_ENVIRONMENT_DAYS
            and float(summary["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
            and float(cash.get("compound_return_pct") or 0.0) > 0.0
            and drawdown is not None
            and drawdown >= MIN_CASH_DRAWDOWN_PCT
        )
        rows.append(
            {
                "environment_key": str(environment),
                "trade_days": trade_days,
                **summary,
                "four_slot_cash": dict(cash),
                "qualified_material_environment": qualified,
            }
        )
    return rows


def _augment_named_cases(
    base_cases: Sequence[Mapping[str, Any]],
    events: pd.DataFrame,
    selected_leaf: QualityLeaf | None,
    environment_policy: Mapping[str, str],
    visible_trades: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows = []
    for case in base_cases:
        symbol = str(case.get("vt_symbol"))
        case_events = events.loc[
            events.get("vt_symbol", pd.Series(dtype=str)).astype(str).eq(symbol)
        ].copy()
        complete = case_events.get(
            "quality_feature_complete", pd.Series(False, index=case_events.index)
        ).fillna(False).astype(bool)
        leaf_matches = (
            apply_quality_leaf(case_events, selected_leaf)
            if selected_leaf is not None and not case_events.empty
            else pd.Series(False, index=case_events.index, dtype=bool)
        )
        matched = case_events.loc[leaf_matches].copy()
        if not matched.empty:
            matched = _with_environment_key(matched)
            traded_environment = matched["environment_key"].map(
                environment_policy
            ).eq("trade")
        else:
            traded_environment = pd.Series(False, index=matched.index, dtype=bool)
        visible_count = int(
            visible_trades.get("vt_symbol", pd.Series(dtype=str))
            .astype(str)
            .eq(symbol)
            .sum()
        )
        reasons: dict[str, int] = {}
        _record_reason(reasons, "incomplete_quality_features", int((~complete).sum()))
        if selected_leaf is None:
            _record_reason(reasons, "no_development_quality_leaf", int(complete.sum()))
        else:
            _record_reason(
                reasons,
                "quality_leaf_not_matched",
                int((complete & ~leaf_matches).sum()),
            )
            _record_reason(
                reasons,
                "environment_policy_cash",
                int((~traded_environment).sum()),
            )
            _record_reason(
                reasons,
                "validation_block_not_opened",
                int(traded_environment.sum()) - visible_count,
            )
        rows.append(
            {
                **dict(case),
                "quality_counts": {
                    "exact_support_events": int(len(case_events)),
                    "complete_quality_events": int(complete.sum()),
                    "quality_leaf_matches": int(leaf_matches.sum()),
                    "traded_environment_matches": int(traded_environment.sum()),
                    "visible_trades": visible_count,
                },
                "exclusion_reasons": reasons,
            }
        )
    return rows


def _no_leaf_qualification(coverage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "historical_proxy_gate_passed": False,
        "formal_strategy": False,
        "formal_metrics": None,
        "overall_metrics": None,
        "qualified_material_environments": [],
        "failed_gates": ["no_development_quality_leaf"],
        "formal_blockers": _formal_blockers(
            coverage,
            required_preclose_rows=1,
        ),
    }


def _unvalidated_qualification(
    failed_block: str,
    *,
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "historical_proxy_gate_passed": False,
        "formal_strategy": False,
        "formal_metrics": None,
        "overall_metrics": None,
        "qualified_material_environments": [],
        "failed_gates": [f"{failed_block}_failed"],
        "formal_blockers": _formal_blockers(
            coverage,
            required_preclose_rows=1,
        ),
    }


def _formal_blockers(
    coverage: Mapping[str, Any],
    *,
    required_preclose_rows: int,
) -> list[str]:
    blockers = []
    if int(coverage.get("strict_historical_membership_rows") or 0) <= 0:
        blockers.append("strict_historical_membership_missing")
    if int(coverage.get("preclose_execution_rows") or 0) < required_preclose_rows:
        blockers.append("executable_preclose_price_missing")
    return blockers


def _research_status(
    selected_leaf: object,
    validation: QualityValidation | None,
) -> str:
    if selected_leaf is None:
        return "no_development_quality_leaf"
    if validation is None:
        raise ValueError("selected quality leaf requires validation evidence")
    if not bool(validation.block_4.get("passed")):
        return "block_4_failed"
    if validation.block_5 is None or not bool(validation.block_5.get("passed")):
        return "block_5_failed"
    if bool(validation.qualification.get("historical_proxy_gate_passed")):
        return "historical_proxy_quality_rule_passed"
    return "historical_proxy_final_gates_failed"


def _with_environment_key(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["environment_key"] = result[list(ENVIRONMENT_COLUMNS)].astype(str).agg(
        "|".join,
        axis=1,
    )
    return result


def _sort_trades(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    columns = [
        column
        for column in ("entry_date", "dynamic_rank", "signal_id")
        if column in frame
    ]
    return frame.sort_values(columns, kind="stable").reset_index(drop=True)


def _add_fingerprint(
    target: dict[str, Mapping[str, Any]],
    name: str,
    frame: pd.DataFrame,
    identity: Sequence[str],
    fingerprint_frame: Any,
) -> None:
    if frame.empty or any(column not in frame for column in identity):
        return
    target[name] = fingerprint_frame(
        frame,
        identity_columns=tuple(identity),
    ).as_dict()


def _record_reason(target: dict[str, int], reason: str, count: int) -> None:
    if count > 0:
        target[reason] = count


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_safe(row) for row in frame.to_dict("records")]


def _leaf_label(value: object) -> str:
    if not isinstance(value, Mapping):
        return "none"
    return f"{value.get('rule_id')}: {_condition_text(value.get('conditions') or [])}"


def _condition_text(conditions: Sequence[Mapping[str, Any]]) -> str:
    return " & ".join(
        f"{condition.get('feature')} {condition.get('operator')} "
        f"{float(condition.get('threshold') or 0.0):.12g}"
        for condition in conditions
    ) or "all rows"


def _block_line(label: str, value: object) -> str:
    if not isinstance(value, Mapping):
        return f"- {label}：`未读取`"
    return (
        f"- {label}：成交 `{value.get('closed_trades', 0)}`，"
        f"胜率 `{_pct(value.get('win_rate_pct'))}`，"
        f"均值 `{_pct(value.get('mean_net_return_pct'), signed=True)}`，"
        f"PF `{_number(value.get('profit_factor'))}`，"
        f"通过 `{value.get('passed', False)}`"
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct(value: object, *, signed: bool = False) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "-"
    return f"{number:+.4f}%" if signed else f"{number:.4f}%"


def _number(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.4f}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is pd.NaT or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
