"""Frozen support-day entry study over dynamic concept leaders."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .causal_leader_pullback import (
    MINIMUM_REQUIRED_SUPPORT,
    execute_close_trades,
    summarize_trade_metrics,
)
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
    LATE_BLOCKS,
    ROUND_TRIP_COST_PCT,
    RULE_IDS,
    apply_pre_registered_rules,
    assign_common_time_blocks,
    build_support_day_events,
    execute_d1_close_trades,
    filter_common_rule_universe,
    freeze_development_rule,
    reprice_d1_close_trades,
    summarize_d1_trades,
)


STUDY_VERSION = "low-suction-support-day-study-v1"
POLICY_VERSION = "causal-leader-support-day-v5"
ENVIRONMENT_COLUMNS = ("active_direction", "danger_state", "market_phase")
MIN_ENVIRONMENT_TRADES = 30
MIN_TOTAL_TRADES = 100
MIN_WIN_RATE_PCT = 60.0
MIN_PROFIT_FACTOR = 1.2
MIN_CASH_COMPOUND_PCT = 60.0
MIN_CASH_DRAWDOWN_PCT = -10.0
DEVELOPMENT_FEATURE_SETS = (
    ("wave_group",),
    ("support_geometry",),
    ("volume_class",),
    ("close_location_group",),
    ("signal_return_group",),
    ("dynamic_rank_group",),
    ("active_direction",),
    ("danger_state",),
    ("market_phase",),
    ("signal_return_group", "dynamic_rank_group"),
    ("signal_return_group", "wave_group"),
    ("signal_return_group", "volume_class"),
    ("signal_return_group", "close_location_group"),
    ("signal_return_group", "active_direction"),
    ("signal_return_group", "market_phase"),
    ("wave_group", "support_geometry", "volume_class"),
    ("wave_group", "dynamic_rank_group", "signal_return_group"),
    ("dynamic_rank_group", "volume_class", "signal_return_group"),
    ("active_direction", "market_phase", "signal_return_group"),
)
DEVELOPMENT_LEDGER_COLUMNS = (
    "rule_id",
    "signal_id",
    "campaign_id",
    "sector_id",
    "concept_name",
    "vt_symbol",
    "stock_name",
    "signal_date",
    "entry_date",
    "exit_date",
    "time_block",
    "entry_price",
    "d1_close",
    "net_return_pct",
    "wave_number",
    "wave_group",
    "required_support",
    "support_geometry",
    "peak_drawdown_low_pct",
    "low_to_required_pct",
    "close_to_required_pct",
    "exact_depth_match",
    "required_line_near",
    "required_support_held",
    "ma5_ma10_band_test",
    "ma5_reclaimed",
    "bullish_reversal",
    "volume_ratio_prior5",
    "volume_class",
    "close_location",
    "close_location_group",
    "daily_return_pct",
    "signal_return_group",
    "dynamic_rank",
    "dynamic_rank_group",
    "active_direction",
    "danger_state",
    "market_phase",
)


def freeze_development_environments(trades: pd.DataFrame) -> dict[str, Any]:
    """Freeze trade/cash environments using blocks 1-3 only."""

    required = (*ENVIRONMENT_COLUMNS, "time_block", "exit_date", "net_return_pct")
    _require_columns(trades, required, "environment trade")
    development = _with_environment_key(trades).loc[
        trades["time_block"].isin(DEVELOPMENT_BLOCKS)
    ]
    policies: dict[str, str] = {}
    metrics: list[dict[str, Any]] = []
    for environment, group in development.groupby("environment_key", sort=True):
        summary = summarize_d1_trades(group)
        positive_blocks = sum(
            _positive_block(group.loc[group["time_block"].eq(block)])
            for block in sorted(DEVELOPMENT_BLOCKS)
        )
        trade = bool(
            summary["closed_trades"] >= MIN_ENVIRONMENT_TRADES
            and float(summary["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
            and float(summary["compound_return_pct"] or 0.0) > 0.0
            and positive_blocks >= 2
        )
        policies[str(environment)] = "trade" if trade else "cash"
        metrics.append(
            {
                "environment_key": str(environment),
                **summary,
                "positive_development_blocks": int(positive_blocks),
                "policy": policies[str(environment)],
            }
        )
    return {
        "development_blocks": sorted(DEVELOPMENT_BLOCKS),
        "policy_by_environment": policies,
        "development_metrics": metrics,
    }


def apply_frozen_environment_policy(
    frame: pd.DataFrame,
    policy_by_environment: Mapping[str, str],
) -> pd.DataFrame:
    """Apply a frozen map; environments absent from development remain cash."""

    _require_columns(frame, ENVIRONMENT_COLUMNS, "environment policy frame")
    routed = _with_environment_key(frame)
    routed["environment_policy"] = (
        routed["environment_key"].map(policy_by_environment).fillna("cash")
    )
    return routed.loc[routed["environment_policy"].eq("trade")].reset_index(
        drop=True
    )


def evaluate_frozen_rule(
    trades: pd.DataFrame,
    *,
    cash_result: Mapping[str, Any],
    double_cost_cash_result: Mapping[str, Any],
    strict_membership_rows: int,
    preclose_execution_rows: int,
) -> dict[str, Any]:
    """Evaluate the unchanged rule and environment map on all five blocks."""

    required = (*ENVIRONMENT_COLUMNS, "time_block", "exit_date", "net_return_pct")
    _require_columns(trades, required, "frozen rule trade")
    routed = _with_environment_key(trades)
    overall = summarize_d1_trades(routed)
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
    if (drawdown if drawdown is not None else -100.0) < MIN_CASH_DRAWDOWN_PCT:
        failed.append("cash_drawdown<-10pct")

    late_metrics = _group_metrics(routed, "time_block", groups=sorted(LATE_BLOCKS))
    for metric in late_metrics:
        block = str(metric["group"])
        if (
            int(metric["closed_trades"]) == 0
            or float(metric["win_rate_pct"] or 0.0) <= MIN_WIN_RATE_PCT
            or float(metric["mean_net_return_pct"] or 0.0) <= 0.0
        ):
            failed.append(f"{block}_failed")

    environment_metrics = _group_metrics(routed, "environment_key")
    qualified_environments = [
        str(metric["group"])
        for metric in environment_metrics
        if int(metric["closed_trades"]) >= MIN_ENVIRONMENT_TRADES
        and float(metric["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
        and float(metric["compound_return_pct"] or 0.0) > 0.0
    ]
    if len(qualified_environments) < 2:
        failed.append("qualified_material_environments<2")
    if float(double_cost_cash_result.get("compound_return_pct") or 0.0) <= 0.0:
        failed.append("double_cost_compound<=0")

    historical_passed = not failed
    formal_blockers: list[str] = []
    if strict_membership_rows <= 0:
        formal_blockers.append("strict_historical_membership_missing")
    if preclose_execution_rows < int(overall["closed_trades"]):
        formal_blockers.append("executable_preclose_price_missing")
    formal_strategy = historical_passed and not formal_blockers
    return {
        "historical_proxy_gate_passed": historical_passed,
        "formal_strategy": formal_strategy,
        "formal_metrics": (
            {"d1": overall, "four_slot_cash": dict(cash_result)}
            if formal_strategy
            else None
        ),
        "overall_metrics": overall,
        "late_block_metrics": late_metrics,
        "environment_metrics": environment_metrics,
        "qualified_material_environments": qualified_environments,
        "failed_gates": failed,
        "formal_blockers": formal_blockers,
    }


def build_support_day_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
    events: pd.DataFrame,
    rule_events: pd.DataFrame,
    all_d1_trades: pd.DataFrame,
    rule_freeze: Mapping[str, Any],
    environment_freeze: Mapping[str, Any],
    selected_d1_trades: pd.DataFrame,
    selected_double_cost_trades: pd.DataFrame,
    cash_result: Mapping[str, Any],
    double_cost_cash_result: Mapping[str, Any],
    structural_trades: pd.DataFrame,
    named_case_audit: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the V5 evidence product without exposing unselected late outcomes."""

    selected_rule = rule_freeze.get("selected_rule")
    if selected_rule is None:
        qualification = _no_nominee_qualification()
        late_evaluation = None
        attribution: list[dict[str, Any]] = []
    else:
        qualification = evaluate_frozen_rule(
            selected_d1_trades,
            cash_result=cash_result,
            double_cost_cash_result=double_cost_cash_result,
            strict_membership_rows=int(
                coverage.get("strict_historical_membership_rows") or 0
            ),
            preclose_execution_rows=int(coverage.get("preclose_execution_rows") or 0),
        )
        late_evaluation = {
            "rule_id": selected_rule,
            "blocks": qualification["late_block_metrics"],
        }
        attribution = build_winner_loser_attribution(selected_d1_trades)

    rule_attempt_counts = {
        rule_id: int(
            rule_events.get("rule_id", pd.Series(dtype=str)).astype(str).eq(rule_id).sum()
        )
        for rule_id in RULE_IDS
    }
    report = {
        "study_version": STUDY_VERSION,
        "policy_version": POLICY_VERSION,
        "research_status": (
            "no_development_rule_nominated"
            if selected_rule is None
            else "historical_proxy_support_day_rule_frozen"
        ),
        "selected_rule": selected_rule,
        "formal_strategy": bool(qualification.get("formal_strategy", False)),
        "formal_metrics": qualification.get("formal_metrics"),
        "contract": {
            "universe": "eligible SSE/SZSE main board, no ST, dynamic concept Top3",
            "main_rise": "causal dynamic concept campaign and stock wave state machine",
            "entry": "support-test D completed close; daily_return_pct < 9.5",
            "exit_primary": "next symbol trading-session official close",
            "exit_secondary": "D+1 loss stop; otherwise higher high or structural exit",
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "double_round_trip_cost_pct": DOUBLE_ROUND_TRIP_COST_PCT,
            "selection_blocks": sorted(DEVELOPMENT_BLOCKS),
            "late_evaluation_blocks": sorted(LATE_BLOCKS),
        },
        "data_quality": {
            "membership_evidence": MEMBERSHIP_EVIDENCE_LEVEL,
            "strict_historical_membership": bool(
                int(coverage.get("strict_historical_membership_rows") or 0) > 0
            ),
            "preclose_execution_available": bool(
                int(coverage.get("preclose_execution_rows") or 0) > 0
            ),
            "minutes_used": False,
            "fund_flow_used": False,
            "entry_day_outcome_used_by_predicate": False,
        },
        "coverage": {
            **dict(coverage),
            "support_day_events": int(len(events)),
            "rule_attempts": rule_attempt_counts,
            "all_rule_d1_trades": int(len(all_d1_trades)),
            "selected_d1_trades": int(len(selected_d1_trades)),
            "selected_structural_trades": int(len(structural_trades)),
        },
        "rule_freeze": dict(rule_freeze),
        "environment_freeze": dict(environment_freeze),
        "qualification": qualification,
        "late_evaluation": late_evaluation,
        "selected_d1_metrics": summarize_d1_trades(selected_d1_trades),
        "selected_double_cost_metrics": summarize_d1_trades(
            selected_double_cost_trades
        ),
        "four_slot_cash": dict(cash_result),
        "double_cost_four_slot_cash": dict(double_cost_cash_result),
        "structural_hold_metrics": summarize_trade_metrics(structural_trades),
        "development_diagnostics": build_development_diagnostics(all_d1_trades),
        "development_trade_ledger": _development_trade_records(all_d1_trades),
        "winner_loser_attribution": attribution,
        "named_case_audit": [dict(row) for row in named_case_audit],
        "selected_d1_trade_ledger": _records(selected_d1_trades),
        "selected_structural_trade_ledger": _records(structural_trades),
        "fingerprints": dict(fingerprints),
        "boundaries": [
            "Only blocks 1-3 can nominate the rule and freeze the environment map.",
            "Blocks 4-5 are evaluated once for the frozen rule and never create new filters.",
            "Winner/loser and named-stock comparisons are attribution only.",
            "Current concept membership replay retains survivorship bias.",
            "The D close is a research price proxy until a pre-close executable price exists.",
        ],
        "reproduce": (
            "docker compose --profile research run --rm -T --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace "
            "-e PYTHONPATH=/workspace:/app/third_party/akshare "
            "alphaagent-research python -m alphaagent.server.services.low_suction.cli "
            "v5-support-day-study --format json"
        ),
    }
    return _json_safe(report)


def run_support_day_study() -> dict[str, Any]:
    """Run one immutable database load and one frozen V5 replay."""

    from .research_protocol import fingerprint_frame

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
    events = filter_common_rule_universe(raw_events)
    events = assign_common_time_blocks(events, event_dates=events["signal_date"])
    rule_events = apply_pre_registered_rules(events)
    all_d1_trades = execute_d1_close_trades(rule_events, stock_features)
    all_double_cost_trades = reprice_d1_close_trades(
        all_d1_trades,
        round_trip_cost_pct=DOUBLE_ROUND_TRIP_COST_PCT,
    )
    development_cash = {
        rule_id: simulate_four_slot_cash(
            all_d1_trades.loc[
                all_d1_trades.get("rule_id", pd.Series(dtype=str)).eq(rule_id)
                & all_d1_trades.get("time_block", pd.Series(dtype=str)).isin(
                    DEVELOPMENT_BLOCKS
                )
            ],
            stock_features,
        )
        for rule_id in RULE_IDS
    }
    rule_freeze = freeze_development_rule(
        all_d1_trades,
        all_double_cost_trades,
        development_cash,
    )

    selected_rule = rule_freeze["selected_rule"]
    environment_freeze: dict[str, Any] = {}
    selected_d1 = pd.DataFrame()
    selected_double = pd.DataFrame()
    structural_signals = pd.DataFrame()
    structural_trades = pd.DataFrame()
    cash_result: Mapping[str, Any] = {}
    double_cost_cash_result: Mapping[str, Any] = {}
    named_case_audit = build_named_case_audit(
        leader_paths,
        raw_events,
        pd.DataFrame(),
        prepared.waves,
        prepared.campaigns.daily_ledger,
    )
    if selected_rule is not None:
        selected_attempts = all_d1_trades.loc[
            all_d1_trades["rule_id"].eq(selected_rule)
        ]
        environment_freeze = freeze_development_environments(selected_attempts)
        selected_events = rule_events.loc[rule_events["rule_id"].eq(selected_rule)]
        routed_events = apply_frozen_environment_policy(
            selected_events,
            environment_freeze["policy_by_environment"],
        )
        selected_d1 = execute_d1_close_trades(routed_events, stock_features)
        selected_double = reprice_d1_close_trades(
            selected_d1,
            round_trip_cost_pct=DOUBLE_ROUND_TRIP_COST_PCT,
        )
        cash_result = simulate_four_slot_cash(selected_d1, stock_features)
        double_cost_cash_result = simulate_four_slot_cash(
            selected_double, stock_features
        )
        structural_signals = _as_structural_signals(routed_events)
        structural_trades = execute_close_trades(structural_signals, leader_paths)
        structural_trades = _attach_structural_context(
            structural_trades, structural_signals
        )
    coverage = {
        **dict(inputs.coverage),
        **dict(rank_coverage),
        "concept_campaigns": int(len(campaigns)),
        "leader_path_rows": int(len(leader_paths)),
        "state_machine_daily_rows": int(len(prepared.campaigns.daily_ledger)),
        "raw_support_day_events": int(len(raw_events)),
        "common_rule_universe_events": int(len(events)),
        "preclose_execution_rows": 0,
    }
    fingerprints: dict[str, Mapping[str, Any]] = dict(inputs.fingerprints)
    _add_fingerprint(
        fingerprints,
        "v5_raw_support_day_events",
        raw_events,
        ("signal_id",),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v5_support_day_events",
        events,
        ("signal_id",),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v5_rule_events",
        rule_events,
        ("rule_id", "signal_id"),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v5_all_d1_trades",
        all_d1_trades,
        ("rule_id", "signal_id"),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v5_selected_d1_trades",
        selected_d1,
        ("rule_id", "signal_id"),
        fingerprint_frame,
    )
    return build_support_day_report(
        coverage=coverage,
        fingerprints=fingerprints,
        events=events,
        rule_events=rule_events,
        all_d1_trades=all_d1_trades,
        rule_freeze=rule_freeze,
        environment_freeze=environment_freeze,
        selected_d1_trades=selected_d1,
        selected_double_cost_trades=selected_double,
        cash_result=cash_result,
        double_cost_cash_result=double_cost_cash_result,
        structural_trades=structural_trades,
        named_case_audit=named_case_audit,
    )


def build_winner_loser_attribution(trades: pd.DataFrame) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    frame = _with_attribution_groups(trades)
    features = (
        "wave_group",
        "support_geometry",
        "volume_class",
        "close_location_group",
        "signal_return_group",
        "dynamic_rank_group",
        "active_direction",
        "market_phase",
        "symbol_group",
        "concept_group",
        "calendar_year",
        "time_block",
    )
    rows: list[dict[str, Any]] = []
    for feature in features:
        for group, values in frame.groupby(feature, dropna=False, sort=True):
            complete = values.loc[
                values["exit_date"].notna() & values["net_return_pct"].notna()
            ]
            rows.append(
                {
                    "feature": feature,
                    "group": str(group),
                    **summarize_d1_trades(complete),
                    "losing_trades": int(
                        pd.to_numeric(
                            complete.get("net_return_pct", pd.Series(dtype=float)),
                            errors="coerce",
                        ).le(0.0).sum()
                    ),
                }
            )
    return rows


def build_development_diagnostics(trades: pd.DataFrame) -> dict[str, Any]:
    """Describe winners and losers using development blocks only."""

    if trades.empty:
        return _json_safe(
            {
                "blocks": sorted(DEVELOPMENT_BLOCKS),
                "rule_metrics": [],
                "feature_metrics": [],
                "high_win_groups": [],
                "low_win_groups": [],
                "warning": (
                    "development attribution only; groups are not executable rules"
                ),
            }
        )
    _require_columns(
        trades,
        ("rule_id", "time_block", "exit_date", "net_return_pct"),
        "development diagnostic trade",
    )
    development = trades.loc[trades["time_block"].isin(DEVELOPMENT_BLOCKS)].copy()
    frame = _with_attribution_groups(development)
    feature_metrics = _development_feature_metrics(frame)
    high_win_groups = sorted(
        (
            row
            for row in feature_metrics
            if int(row["closed_trades"]) >= MIN_ENVIRONMENT_TRADES
            and float(row["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
            and float(row["mean_net_return_pct"] or 0.0) > 0.0
            and float(row["profit_factor"] or 0.0) >= MIN_PROFIT_FACTOR
            and int(row["positive_development_blocks"]) >= 2
        ),
        key=lambda row: (
            -int(row["positive_development_blocks"]),
            -float(row["win_rate_pct"] or 0.0),
            -float(row["mean_net_return_pct"] or 0.0),
            -int(row["closed_trades"]),
            str(row["rule_id"]),
            str(row["feature"]),
            str(row["group"]),
        ),
    )
    low_win_groups = sorted(
        (
            row
            for row in feature_metrics
            if int(row["closed_trades"]) >= MIN_ENVIRONMENT_TRADES
            and float(row["win_rate_pct"] or 0.0) < 40.0
            and float(row["mean_net_return_pct"] or 0.0) < 0.0
            and row["profit_factor"] is not None
            and float(row["profit_factor"]) <= 0.8
            and int(row["negative_development_blocks"]) >= 2
        ),
        key=lambda row: (
            -int(row["negative_development_blocks"]),
            float(row["win_rate_pct"] or 0.0),
            float(row["mean_net_return_pct"] or 0.0),
            -int(row["closed_trades"]),
            str(row["rule_id"]),
            str(row["feature"]),
            str(row["group"]),
        ),
    )
    rule_metrics = [
        {
            "rule_id": str(rule_id),
            **summarize_d1_trades(values),
        }
        for rule_id, values in development.groupby("rule_id", sort=True)
    ]
    return _json_safe(
        {
            "blocks": sorted(DEVELOPMENT_BLOCKS),
            "rule_metrics": rule_metrics,
            "feature_metrics": feature_metrics,
            "high_win_groups": high_win_groups,
            "low_win_groups": low_win_groups,
            "warning": "development attribution only; groups are not executable rules",
        }
    )


def _development_feature_metrics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule_id, rule_rows in frame.groupby("rule_id", sort=True):
        for feature_set in DEVELOPMENT_FEATURE_SETS:
            if any(feature not in rule_rows for feature in feature_set):
                continue
            group_key: str | list[str] = (
                feature_set[0] if len(feature_set) == 1 else list(feature_set)
            )
            for raw_group, values in rule_rows.groupby(
                group_key,
                dropna=False,
                sort=True,
            ):
                group_values = raw_group if isinstance(raw_group, tuple) else (raw_group,)
                block_metrics = _group_metrics(
                    values,
                    "time_block",
                    groups=sorted(DEVELOPMENT_BLOCKS),
                )
                rows.append(
                    {
                        "rule_id": str(rule_id),
                        "feature": "+".join(feature_set),
                        "features": list(feature_set),
                        "group": "|".join(str(value) for value in group_values),
                        **summarize_d1_trades(values),
                        "positive_development_blocks": sum(
                            _is_positive_development_metric(metric)
                            for metric in block_metrics
                        ),
                        "negative_development_blocks": sum(
                            _is_negative_development_metric(metric)
                            for metric in block_metrics
                        ),
                        "block_metrics": block_metrics,
                    }
                )
    return rows


def _is_positive_development_metric(metric: Mapping[str, Any]) -> bool:
    return bool(
        int(metric.get("closed_trades") or 0) > 0
        and float(metric.get("win_rate_pct") or 0.0) > MIN_WIN_RATE_PCT
        and float(metric.get("mean_net_return_pct") or 0.0) > 0.0
    )


def _is_negative_development_metric(metric: Mapping[str, Any]) -> bool:
    return bool(
        int(metric.get("closed_trades") or 0) > 0
        and float(metric.get("win_rate_pct") or 0.0) < 40.0
        and float(metric.get("mean_net_return_pct") or 0.0) < 0.0
    )


def _development_trade_records(trades: pd.DataFrame) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    _require_columns(trades, ("time_block",), "development trade ledger")
    development = trades.loc[trades["time_block"].isin(DEVELOPMENT_BLOCKS)].copy()
    if development.empty:
        return []
    development = _with_attribution_groups(development)
    columns = [column for column in DEVELOPMENT_LEDGER_COLUMNS if column in development]
    sort_columns = [
        column
        for column in ("entry_date", "rule_id", "signal_id")
        if column in development
    ]
    if sort_columns:
        development = development.sort_values(sort_columns, kind="stable")
    return _records(development.loc[:, columns])


def render_support_day_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"


def render_support_day_markdown(report: Mapping[str, Any]) -> str:
    qualification = _mapping(report.get("qualification"))
    lines = [
        "# AlphaAgent 主升龙头支撑日低吸 V5",
        "",
        f"规则版本：`{report.get('policy_version')}`  ",
        f"开发期冻结规则：`{report.get('selected_rule') or 'none'}`  ",
        f"历史代理门：`{qualification.get('historical_proxy_gate_passed', False)}`  ",
        f"正式策略：`{str(report.get('formal_strategy', False)).lower()}`",
        "",
        "## 开发期规则冻结",
        "",
        "| 规则 | D1 成交 | 胜率 | 均值 | PF | 稳定块 | 四仓复利 | 入围 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    freeze = _mapping(report.get("rule_freeze"))
    for row in freeze.get("candidate_metrics") or []:
        metric = _mapping(row)
        lines.append(
            "| {rule} | {trades} | {win} | {mean} | {pf} | {blocks} | {cash} | {passed} |".format(
                rule=metric.get("rule_id"),
                trades=metric.get("development_closed_trades", 0),
                win=_pct(metric.get("development_win_rate_pct")),
                mean=_pct(metric.get("development_mean_net_return_pct"), signed=True),
                pf=_number(metric.get("development_profit_factor")),
                blocks=metric.get("development_stable_blocks", 0),
                cash=_pct(metric.get("development_cash_compound_pct"), signed=True),
                passed=metric.get("nomination_passed", False),
            )
        )
    diagnostics = _mapping(report.get("development_diagnostics"))
    lines.extend(
        [
            "",
            "## 开发期高胜率分组",
            "",
            "| 规则 | 特征 | 分组 | 成交 | 胜率 | 均值 | PF | 正向块 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    high_groups = list(diagnostics.get("high_win_groups") or [])
    for row in high_groups[:20]:
        metric = _mapping(row)
        lines.append(
            "| {rule} | {feature} | {group} | {trades} | {win} | {mean} | {pf} | {blocks} |".format(
                rule=metric.get("rule_id"),
                feature=metric.get("feature"),
                group=metric.get("group"),
                trades=metric.get("closed_trades", 0),
                win=_pct(metric.get("win_rate_pct")),
                mean=_pct(metric.get("mean_net_return_pct"), signed=True),
                pf=_number(metric.get("profit_factor")),
                blocks=metric.get("positive_development_blocks", 0),
            )
        )
    if not high_groups:
        lines.append("| - | - | 无满足稳定性门的分组 | 0 | - | - | - | 0 |")
    lines.extend(
        [
            "",
            "## 开发期低胜率分组",
            "",
            "| 规则 | 特征 | 分组 | 成交 | 胜率 | 均值 | PF | 负向块 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    low_groups = list(diagnostics.get("low_win_groups") or [])
    for row in low_groups[:20]:
        metric = _mapping(row)
        lines.append(
            "| {rule} | {feature} | {group} | {trades} | {win} | {mean} | {pf} | {blocks} |".format(
                rule=metric.get("rule_id"),
                feature=metric.get("feature"),
                group=metric.get("group"),
                trades=metric.get("closed_trades", 0),
                win=_pct(metric.get("win_rate_pct")),
                mean=_pct(metric.get("mean_net_return_pct"), signed=True),
                pf=_number(metric.get("profit_factor")),
                blocks=metric.get("negative_development_blocks", 0),
            )
        )
    if not low_groups:
        lines.append("| - | - | 无满足稳定性门的分组 | 0 | - | - | - | 0 |")
    lines.extend(["", "## 冻结行情策略", ""])
    environment = _mapping(report.get("environment_freeze"))
    lines.extend(
        f"- `{key}`：`{policy}`"
        for key, policy in _mapping(environment.get("policy_by_environment")).items()
    )
    lines.extend(["", "## 最终 D+1 与四仓", ""])
    metrics = _mapping(report.get("selected_d1_metrics"))
    cash = _mapping(report.get("four_slot_cash"))
    lines.extend(
        [
            f"- 成交：`{metrics.get('closed_trades', 0)}`",
            f"- 胜率：`{_pct(metrics.get('win_rate_pct'))}`",
            f"- 单笔均值：`{_pct(metrics.get('mean_net_return_pct'), signed=True)}`",
            f"- PF：`{_number(metrics.get('profit_factor'))}`",
            f"- 四仓复利：`{_pct(cash.get('compound_return_pct'), signed=True)}`",
            f"- 四仓最大回撤：`{_pct(cash.get('maximum_drawdown_pct'), signed=True)}`",
        ]
    )
    lines.extend(["", "## 资格结论", ""])
    lines.append(
        f"- 失败门：`{', '.join(qualification.get('failed_gates') or []) or 'none'}`"
    )
    lines.append(
        f"- 正式阻断：`{', '.join(qualification.get('formal_blockers') or []) or 'none'}`"
    )
    lines.extend(["", "## 参考龙头", ""])
    for case in report.get("named_case_audit") or []:
        item = _mapping(case)
        lines.append(
            f"- {item.get('stock_name')} `{item.get('vt_symbol')}`："
            f"campaign `{item.get('campaigns', 0)}`，波次 `{item.get('waves', 0)}`，"
            f"信号 `{item.get('signals', 0)}`，成交 `{item.get('executed_trades', 0)}`。"
        )
    lines.extend(["", "## 研究边界", ""])
    lines.extend(f"- {value}" for value in report.get("boundaries") or [])
    lines.extend(
        ["", "## Reproduce", "", "```bash", str(report.get("reproduce") or ""), "```"]
    )
    return "\n".join(lines).rstrip() + "\n"


def _as_structural_signals(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    signals = events.copy()
    signals["signal_close"] = signals["close_price"]
    signals["support_line"] = signals["deepest_tested_support"].fillna(
        signals["required_support"]
    )
    signals["support_depth"] = signals["deepest_tested_depth"].clip(lower=1)
    signals["reference_peak_price"] = signals["record_high_price"]
    return signals


def _attach_structural_context(
    trades: pd.DataFrame, signals: pd.DataFrame
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    columns = [
        column
        for column in (
            "signal_id",
            "rule_id",
            "stock_name",
            "concept_name",
            "active_direction",
            "danger_state",
            "market_phase",
            "time_block",
        )
        if column in signals
    ]
    context = signals.loc[:, columns].drop_duplicates("signal_id")
    duplicates = [column for column in columns if column in trades and column != "signal_id"]
    return trades.drop(columns=duplicates).merge(
        context, on="signal_id", how="left", validate="many_to_one", sort=False
    )


def _with_environment_key(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["environment_key"] = result[list(ENVIRONMENT_COLUMNS)].astype(str).agg(
        "|".join, axis=1
    )
    return result


def _positive_block(trades: pd.DataFrame) -> bool:
    metric = summarize_d1_trades(trades)
    return bool(
        metric["closed_trades"] > 0
        and float(metric["compound_return_pct"] or 0.0) > 0.0
    )


def _group_metrics(
    frame: pd.DataFrame,
    column: str,
    *,
    groups: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    requested = list(groups) if groups is not None else None
    if frame.empty:
        return [
            {"group": group, **summarize_d1_trades(pd.DataFrame())}
            for group in (requested or [])
        ]
    observed = {
        str(group): summarize_d1_trades(values)
        for group, values in frame.groupby(column, dropna=False, sort=True)
    }
    keys = requested if requested is not None else sorted(observed)
    return [
        {"group": key, **observed.get(key, summarize_d1_trades(pd.DataFrame()))}
        for key in keys
    ]


def _with_attribution_groups(trades: pd.DataFrame) -> pd.DataFrame:
    frame = trades.copy()
    if "wave_number" in frame:
        frame["wave_group"] = "wave_" + frame["wave_number"].astype(
            "Int64"
        ).astype(str)
    if "required_support" in frame:
        band = frame.get(
            "ma5_ma10_band_test", pd.Series(False, index=frame.index)
        ).astype(bool)
        frame["support_geometry"] = np.where(
            band,
            "ma5_ma10_band_reclaim",
            frame["required_support"].astype(str) + "_exact",
        )
    if "volume_ratio_prior5" in frame:
        volume = pd.to_numeric(frame["volume_ratio_prior5"], errors="coerce")
        frame["volume_class"] = pd.cut(
            volume,
            bins=[-np.inf, 0.8, 1.5, np.inf],
            labels=["contraction", "normal", "expansion"],
            right=False,
        ).astype(str)
    if "close_location" in frame:
        close_location = pd.to_numeric(frame["close_location"], errors="coerce")
        frame["close_location_group"] = pd.cut(
            close_location,
            bins=[-np.inf, 0.5, 0.75, np.inf],
            labels=["below_half", "middle", "upper_quarter"],
            right=False,
        ).astype(str)
    if "daily_return_pct" in frame:
        signal_return = pd.to_numeric(frame["daily_return_pct"], errors="coerce")
        frame["signal_return_group"] = pd.cut(
            signal_return,
            bins=[-np.inf, 0.0, 3.0, 6.0, 9.5],
            labels=["negative", "0_to_3", "3_to_6", "6_to_9_5"],
            right=False,
        ).astype(str)
    if "dynamic_rank" in frame:
        frame["dynamic_rank_group"] = "rank_" + frame["dynamic_rank"].astype(
            "Int64"
        ).astype(str)
    if "vt_symbol" in frame:
        frame["symbol_group"] = frame["vt_symbol"].astype(str) + " " + frame.get(
            "stock_name", pd.Series(index=frame.index, dtype=str)
        ).fillna("").astype(str)
    if "sector_id" in frame:
        frame["concept_group"] = frame["sector_id"].astype(str) + " " + frame.get(
            "concept_name", pd.Series(index=frame.index, dtype=str)
        ).fillna("").astype(str)
    if "entry_date" in frame:
        frame["calendar_year"] = pd.to_datetime(
            frame["entry_date"], errors="coerce"
        ).dt.year.astype("Int64").astype(str)
    return frame


def _no_nominee_qualification() -> dict[str, Any]:
    return {
        "historical_proxy_gate_passed": False,
        "formal_strategy": False,
        "formal_metrics": None,
        "overall_metrics": summarize_d1_trades(pd.DataFrame()),
        "late_block_metrics": [],
        "environment_metrics": [],
        "qualified_material_environments": [],
        "failed_gates": ["no_development_rule_nominated"],
        "formal_blockers": [
            "strict_historical_membership_missing",
            "executable_preclose_price_missing",
        ],
    }


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
        frame, identity_columns=tuple(identity)
    ).as_dict()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_safe(row) for row in frame.to_dict("records")]


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


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
