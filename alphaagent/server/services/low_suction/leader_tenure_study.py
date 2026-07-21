"""Sequential V8 study for persistent causal leader identity."""

from __future__ import annotations

import gc
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from alphaagent.server.services.research_runtime import require_research_runtime

from .causal_leader_pullback import MINIMUM_REQUIRED_SUPPORT
from .causal_leader_pullback_study import (
    REFERENCE_SYMBOLS,
    build_causal_stock_features,
    build_concept_campaign_ledger,
    build_dynamic_leader_paths,
    load_causal_leader_pullback_inputs,
    prepare_dynamic_leader_paths,
    simulate_four_slot_cash,
)
from .dynamic_concept_campaign import MEMBERSHIP_EVIDENCE_LEVEL
from .leader_tenure_identity import (
    TENURE_GRACE_SESSIONS,
    build_causal_leader_tenures,
    select_primary_concept_events,
)
from .support_day_entry import (
    DEVELOPMENT_BLOCKS,
    DOUBLE_ROUND_TRIP_COST_PCT,
    ROUND_TRIP_COST_PCT,
    RULE_EXACT_HOLD,
    apply_pre_registered_rules,
    build_support_day_events,
    execute_d1_close_trades,
    filter_common_rule_universe,
    reprice_d1_close_trades,
    summarize_d1_trades,
)
from .support_day_study import (
    apply_frozen_environment_policy,
    freeze_development_environments,
)
from .support_quality import MIN_LATE_BLOCK_TRADES, MIN_PROFIT_FACTOR, MIN_WIN_RATE_PCT
from .support_reclaim_confirmation import (
    assign_frozen_time_blocks,
    build_support_reclaim_confirmations,
    freeze_common_block_boundaries,
    freeze_development_confirmation_rule,
)
from .support_reclaim_confirmation_study import (
    ConfirmationValidation,
    build_development_diagnostics,
    evaluate_selected_confirmation_rule,
)


STUDY_VERSION = "low-suction-causal-leader-tenure-study-v1"
POLICY_VERSION = "causal-leader-tenure-support-reclaim-v8"


TradeExecutor = Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame]
CashSimulator = Callable[[pd.DataFrame, pd.DataFrame], Mapping[str, Any]]


@dataclass(frozen=True)
class TenureConfirmationEvaluation:
    development_freeze: Mapping[str, Any]
    environment_freeze: Mapping[str, Any]
    block_4: Mapping[str, Any] | None
    block_5: Mapping[str, Any] | None
    qualification: Mapping[str, Any]
    development_trades: pd.DataFrame
    visible_trades: pd.DataFrame
    four_slot_cash: Mapping[str, Any]
    double_cost_four_slot_cash: Mapping[str, Any]
    final_validation: ConfirmationValidation | None


def evaluate_tenure_confirmations(
    confirmation_events: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    coverage: Mapping[str, Any],
    executor: TradeExecutor = execute_d1_close_trades,
    cash_simulator: CashSimulator = simulate_four_slot_cash,
) -> TenureConfirmationEvaluation:
    """Execute D+1 prices only after each chronological gate opens."""

    required = (
        "rule_id",
        "signal_id",
        "time_block",
        "active_direction",
        "danger_state",
        "market_phase",
    )
    _require_columns(confirmation_events, required, "V8 confirmation event")
    events = confirmation_events.copy()
    development_events = events.loc[
        events["time_block"].isin(DEVELOPMENT_BLOCKS)
    ].copy()
    development_trades = _execute_events(
        development_events,
        stock_bars,
        executor=executor,
    )
    development_double = reprice_d1_close_trades(
        development_trades,
        round_trip_cost_pct=DOUBLE_ROUND_TRIP_COST_PCT,
    )
    development_cash = cash_simulator(development_trades, stock_bars)
    development_freeze = freeze_development_confirmation_rule(
        development_trades,
        development_double,
        development_cash,
    )
    if development_freeze.get("selected_rule") is None:
        return TenureConfirmationEvaluation(
            development_freeze=development_freeze,
            environment_freeze={},
            block_4=None,
            block_5=None,
            qualification=_unvalidated_qualification(
                "no_development_tenure_rule", coverage
            ),
            development_trades=_sort_trades(development_trades),
            visible_trades=_sort_trades(development_trades),
            four_slot_cash={},
            double_cost_four_slot_cash={},
            final_validation=None,
        )

    environment_freeze = freeze_development_environments(development_trades)
    policy = _mapping(environment_freeze.get("policy_by_environment"))
    routed_development = apply_frozen_environment_policy(
        development_trades, policy
    )
    block_4_events = apply_frozen_environment_policy(
        events.loc[events["time_block"].eq("block_4")], policy
    )
    block_4_trades = _execute_events(
        block_4_events,
        stock_bars,
        executor=executor,
    )
    block_4 = _late_block_result(block_4_trades)
    visible = _concat_trades(routed_development, block_4_trades)
    if not bool(block_4["passed"]):
        return TenureConfirmationEvaluation(
            development_freeze=development_freeze,
            environment_freeze=environment_freeze,
            block_4=block_4,
            block_5=None,
            qualification=_unvalidated_qualification("block_4_failed", coverage),
            development_trades=_sort_trades(development_trades),
            visible_trades=visible,
            four_slot_cash={},
            double_cost_four_slot_cash={},
            final_validation=None,
        )

    block_5_events = apply_frozen_environment_policy(
        events.loc[events["time_block"].eq("block_5")], policy
    )
    block_5_trades = _execute_events(
        block_5_events,
        stock_bars,
        executor=executor,
    )
    block_5 = _late_block_result(block_5_trades)
    visible = _concat_trades(visible, block_5_trades)
    if not bool(block_5["passed"]):
        return TenureConfirmationEvaluation(
            development_freeze=development_freeze,
            environment_freeze=environment_freeze,
            block_4=block_4,
            block_5=block_5,
            qualification=_unvalidated_qualification("block_5_failed", coverage),
            development_trades=_sort_trades(development_trades),
            visible_trades=visible,
            four_slot_cash={},
            double_cost_four_slot_cash={},
            final_validation=None,
        )

    sequential_trades = _concat_trades(
        development_trades,
        block_4_trades,
        block_5_trades,
    )
    final_validation = evaluate_selected_confirmation_rule(
        sequential_trades,
        stock_bars,
        coverage=coverage,
    )
    return TenureConfirmationEvaluation(
        development_freeze=development_freeze,
        environment_freeze=final_validation.environment_freeze,
        block_4=final_validation.block_4,
        block_5=final_validation.block_5,
        qualification=final_validation.qualification,
        development_trades=_sort_trades(development_trades),
        visible_trades=final_validation.visible_trades,
        four_slot_cash=final_validation.four_slot_cash,
        double_cost_four_slot_cash=final_validation.double_cost_four_slot_cash,
        final_validation=final_validation,
    )


def build_identity_diagnostics(
    raw_paths: pd.DataFrame,
    tenure_paths: pd.DataFrame,
) -> dict[str, Any]:
    """Describe identity changes without reading a trade outcome."""

    _require_columns(raw_paths, ("dynamic_top3",), "raw leader path")
    required = (
        "vt_symbol",
        "trade_date",
        "leader_tenure_active",
        "current_dynamic_top3",
        "tenure_established_today",
        "tenure_expired_today",
        "tenure_end_reason",
        "active_tenure_concepts",
    )
    _require_columns(tenure_paths, required, "tenure leader path")
    grace = (
        tenure_paths["leader_tenure_active"].astype(bool)
        & ~tenure_paths["current_dynamic_top3"].astype(bool)
    )
    breadth = tenure_paths.drop_duplicates(["vt_symbol", "trade_date"])
    breadth_counts = {
        str(int(key)): int(count)
        for key, count in breadth["active_tenure_concepts"]
        .value_counts(sort=False)
        .sort_index()
        .items()
    }
    reasons = {
        str(key): int(count)
        for key, count in tenure_paths.loc[
            tenure_paths["tenure_expired_today"].astype(bool),
            "tenure_end_reason",
        ]
        .value_counts(sort=False)
        .sort_index()
        .items()
    }
    return {
        "raw_path_rows": int(len(raw_paths)),
        "tenure_path_rows": int(len(tenure_paths)),
        "raw_current_top3_rows": int(raw_paths["dynamic_top3"].astype(bool).sum()),
        "tenure_active_rows": int(
            tenure_paths["leader_tenure_active"].astype(bool).sum()
        ),
        "rank_grace_rows": int(grace.sum()),
        "tenures_established": int(
            tenure_paths["tenure_established_today"].astype(bool).sum()
        ),
        "tenures_expired": int(
            tenure_paths["tenure_expired_today"].astype(bool).sum()
        ),
        "tenure_end_reasons": reasons,
        "active_tenure_concept_breadth": breadth_counts,
    }


def build_named_tenure_case_audit(
    tenure_paths: pd.DataFrame,
    primary_anchors: pd.DataFrame,
    primary_confirmations: pd.DataFrame,
    visible_trades: pd.DataFrame,
) -> list[dict[str, Any]]:
    """List complete causal tenure intervals for the three requested stocks."""

    rows: list[dict[str, Any]] = []
    for symbol, name in REFERENCE_SYMBOLS.items():
        paths = tenure_paths.loc[tenure_paths["vt_symbol"].eq(symbol)].copy()
        active = paths.loc[paths["leader_tenure_active"].astype(bool)].copy()
        intervals = []
        for tenure_id, interval in active.groupby("leader_tenure_id", sort=True):
            current_top3 = interval["current_dynamic_top3"].astype(bool)
            intervals.append(
                {
                    "leader_tenure_id": str(tenure_id),
                    "campaign_id": str(interval["campaign_id"].iloc[0]),
                    "sector_id": str(interval["sector_id"].iloc[0]),
                    "concept_name": str(interval["concept_name"].iloc[0]),
                    "start_date": _date_text(interval["trade_date"].min()),
                    "end_date": _date_text(interval["trade_date"].max()),
                    "top3_dates": [
                        _date_text(value)
                        for value in interval.loc[current_top3, "trade_date"]
                    ],
                    "grace_dates": [
                        _date_text(value)
                        for value in interval.loc[~current_top3, "trade_date"]
                    ],
                    "best_rank": _optional_int(interval["tenure_best_rank"].min()),
                    "top3_days": int(interval["tenure_top3_days"].max()),
                }
            )
        anchors = _symbol_rows(primary_anchors, symbol)
        confirmations = _symbol_rows(primary_confirmations, symbol)
        trades = _symbol_rows(visible_trades, symbol)
        rows.append(
            {
                "vt_symbol": symbol,
                "stock_name": name,
                "tenure_intervals": intervals,
                "tenure_count": int(len(intervals)),
                "exact_support_dates": _dated_event_records(anchors),
                "confirmation_dates": _dated_event_records(confirmations),
                "visible_trade_rows": _records(trades),
                "cross_concept_anchors_removed": int(
                    pd.to_numeric(
                        anchors.get("duplicate_concept_count", pd.Series(dtype=float)),
                        errors="coerce",
                    )
                    .sub(1)
                    .clip(lower=0)
                    .fillna(0)
                    .sum()
                ),
                "cross_concept_confirmations_removed": int(
                    pd.to_numeric(
                        confirmations.get(
                            "duplicate_concept_count", pd.Series(dtype=float)
                        ),
                        errors="coerce",
                    )
                    .sub(1)
                    .clip(lower=0)
                    .fillna(0)
                    .sum()
                ),
            }
        )
    return _json_safe(rows)


def build_leader_tenure_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
    block_boundaries: Mapping[str, object],
    identity_diagnostics: Mapping[str, Any],
    event_counts: Mapping[str, Any],
    evaluation: TenureConfirmationEvaluation,
    named_case_audit: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build V8 evidence without serializing unopened late outcomes."""

    selected_rule = evaluation.development_freeze.get("selected_rule")
    research_status = _research_status(evaluation)
    report = {
        "study_version": STUDY_VERSION,
        "policy_version": POLICY_VERSION,
        "research_status": research_status,
        "formal_strategy": bool(evaluation.qualification.get("formal_strategy")),
        "formal_metrics": evaluation.qualification.get("formal_metrics"),
        "selected_rule": selected_rule,
        "contract": {
            "universe": "SSE/SZSE main board dynamic concept Top3 only",
            "identity_establishment": "valid completed-day dynamic Top3",
            "identity_grace_sessions": TENURE_GRACE_SESSIONS,
            "identity_exit": "campaign inactive, structure invalid, or fourth rank miss",
            "primary_concept_order": [
                "tenure_top3_days desc",
                "tenure_best_rank asc",
                "current_dynamic_top3 desc",
                "concept_gain_pct desc",
                "concept_excess_gain_pct desc",
                "turnover_expansion desc",
                "sector_id asc",
                "campaign_id asc",
            ],
            "first_wave_support": "ma5",
            "later_wave_support": "ma10",
            "confirmation": "unchanged V7 first weak-to-strong close",
            "entry": "confirmation_day_close",
            "exit": "next_symbol_session_close",
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "double_round_trip_cost_pct": DOUBLE_ROUND_TRIP_COST_PCT,
            "membership_evidence_level": MEMBERSHIP_EVIDENCE_LEVEL,
            "development_blocks": sorted(DEVELOPMENT_BLOCKS),
            "entry_execution_assumption": "same_close_research_proxy",
        },
        "block_boundaries": {
            key: _date_text(value) for key, value in block_boundaries.items()
        },
        "coverage": dict(coverage),
        "fingerprints": dict(fingerprints),
        "identity_diagnostics": dict(identity_diagnostics),
        "event_counts": dict(event_counts),
        "development_freeze": dict(evaluation.development_freeze),
        "development_diagnostics": build_development_diagnostics(
            evaluation.development_trades
        ),
        "environment_freeze": dict(evaluation.environment_freeze),
        "block_4": evaluation.block_4,
        "block_5": evaluation.block_5,
        "qualification": dict(evaluation.qualification),
        "overall_metrics": evaluation.qualification.get("overall_metrics"),
        "four_slot_cash": dict(evaluation.four_slot_cash),
        "double_cost_four_slot_cash": dict(
            evaluation.double_cost_four_slot_cash
        ),
        "development_trade_ledger": _records(evaluation.development_trades),
        "selected_trade_ledger": _records(evaluation.visible_trades),
        "named_case_audit": [dict(row) for row in named_case_audit],
        "boundaries": [
            "V8 changes only leader identity; campaign, support, confirmation and exit remain V7.",
            "Only blocks 1-3 D+1 prices are queried before development nomination.",
            "Block 4 prices are queried only after nomination; block 5 only after block 4 passes.",
            "One primary concept is selected per stock/date without an outcome feature.",
            "Current membership and the completed D close remain historical research proxies.",
        ],
        "reproduce": (
            "docker compose --profile research run --rm -T --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace "
            "-e PYTHONPATH=/workspace:/app/third_party/akshare "
            "alphaagent-research python -m "
            "alphaagent.server.services.low_suction.cli "
            "v8-leader-tenure-study --format json"
        ),
    }
    return _json_safe(report)


def run_leader_tenure_study() -> dict[str, Any]:
    """Run one capped V8 identity replay and strict sequential evaluation."""

    from .research_protocol import fingerprint_frame

    require_research_runtime()
    inputs = load_causal_leader_pullback_inputs()
    stock_features = build_causal_stock_features(inputs.stock_bars)
    campaigns, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    raw_paths, rank_coverage = build_dynamic_leader_paths(
        campaign_paths,
        inputs.memberships,
        stock_features,
    )

    raw_prepared = prepare_dynamic_leader_paths(
        raw_paths,
        inputs.market_timing,
        support_match_mode=MINIMUM_REQUIRED_SUPPORT,
    )
    raw_support = build_support_day_events(
        raw_paths,
        raw_prepared.campaigns.daily_ledger,
        inputs.market_timing,
    )
    common_calendar = filter_common_rule_universe(raw_support)
    block_boundaries = freeze_common_block_boundaries(
        common_calendar["signal_date"]
    )
    del raw_prepared
    gc.collect()

    tenure_paths = build_causal_leader_tenures(raw_paths)
    tenure_prepared = prepare_dynamic_leader_paths(
        tenure_paths,
        inputs.market_timing,
        support_match_mode=MINIMUM_REQUIRED_SUPPORT,
    )
    tenure_support = build_support_day_events(
        tenure_paths,
        tenure_prepared.campaigns.daily_ledger,
        inputs.market_timing,
    )
    tenure_common = filter_common_rule_universe(tenure_support)
    exact_support = apply_pre_registered_rules(tenure_common)
    exact_support = exact_support.loc[
        exact_support["rule_id"].eq(RULE_EXACT_HOLD)
    ].reset_index(drop=True)
    primary_anchors = select_primary_concept_events(
        exact_support,
        tenure_paths,
    )
    confirmations = build_support_reclaim_confirmations(
        primary_anchors,
        tenure_paths,
        tenure_prepared.campaigns.daily_ledger,
        inputs.market_timing,
    )
    confirmations = assign_frozen_time_blocks(confirmations, block_boundaries)
    primary_confirmations = select_primary_concept_events(
        confirmations,
        tenure_paths,
    )
    evaluation = evaluate_tenure_confirmations(
        primary_confirmations,
        stock_features,
        coverage=inputs.coverage,
    )

    identity_diagnostics = build_identity_diagnostics(raw_paths, tenure_paths)
    named_cases = build_named_tenure_case_audit(
        tenure_paths,
        primary_anchors,
        primary_confirmations,
        evaluation.visible_trades,
    )
    event_counts = {
        "unchanged_v5_common_calendar_events": int(len(common_calendar)),
        "tenure_common_support_events": int(len(tenure_common)),
        "exact_support_events_before_primary": int(len(exact_support)),
        "primary_exact_support_events": int(len(primary_anchors)),
        "confirmations_before_primary": int(len(confirmations)),
        "primary_confirmations": int(len(primary_confirmations)),
        "duplicate_exact_support_events_removed": int(
            len(exact_support) - len(primary_anchors)
        ),
        "duplicate_confirmations_removed": int(
            len(confirmations) - len(primary_confirmations)
        ),
    }
    coverage = {
        **dict(inputs.coverage),
        **dict(rank_coverage),
        "concept_campaigns": int(len(campaigns)),
        "raw_leader_path_rows": int(len(raw_paths)),
        "tenure_leader_path_rows": int(len(tenure_paths)),
        "state_machine_daily_rows": int(
            len(tenure_prepared.campaigns.daily_ledger)
        ),
        "development_tenure_trades": int(len(evaluation.development_trades)),
        "preclose_execution_rows": 0,
    }
    fingerprints: dict[str, Mapping[str, Any]] = dict(inputs.fingerprints)
    _add_fingerprint(
        fingerprints,
        "v8_raw_identity",
        raw_paths.loc[
            :,
            [
                "campaign_id",
                "vt_symbol",
                "trade_date",
                "dynamic_rank",
                "dynamic_top3",
                "campaign_active",
                "structure_intact",
                "feature_cutoff_date",
            ],
        ],
        ("campaign_id", "vt_symbol", "trade_date"),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v8_tenure_identity",
        tenure_paths.loc[
            :,
            [
                "campaign_id",
                "vt_symbol",
                "trade_date",
                "current_dynamic_rank",
                "current_dynamic_top3",
                "leader_tenure_active",
                "sessions_since_top3",
                "tenure_rank",
                "tenure_best_rank",
                "tenure_top3_days",
                "active_tenure_concepts",
                "feature_cutoff_date",
            ],
        ],
        ("campaign_id", "vt_symbol", "trade_date"),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v8_primary_exact_support",
        primary_anchors,
        ("signal_id",),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v8_primary_confirmations",
        primary_confirmations,
        ("signal_id",),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v8_development_execution",
        evaluation.development_trades,
        ("signal_id",),
        fingerprint_frame,
    )
    for block in ("block_4", "block_5"):
        opened = evaluation.visible_trades.loc[
            evaluation.visible_trades.get(
                "time_block", pd.Series(index=evaluation.visible_trades.index, dtype=str)
            ).eq(block)
        ]
        _add_fingerprint(
            fingerprints,
            f"v8_{block}_execution",
            opened,
            ("signal_id",),
            fingerprint_frame,
        )
    boundary_frame = pd.DataFrame(
        [
            {"time_block": block, "end_date": endpoint}
            for block, endpoint in block_boundaries.items()
        ]
    )
    _add_fingerprint(
        fingerprints,
        "v8_block_boundaries",
        boundary_frame,
        ("time_block",),
        fingerprint_frame,
    )
    return build_leader_tenure_report(
        coverage=coverage,
        fingerprints=fingerprints,
        block_boundaries=block_boundaries,
        identity_diagnostics=identity_diagnostics,
        event_counts=event_counts,
        evaluation=evaluation,
        named_case_audit=named_cases,
    )


def render_leader_tenure_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(report),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_leader_tenure_markdown(report: Mapping[str, Any]) -> str:
    development = _mapping(report.get("development_freeze"))
    metrics = _mapping(development.get("development_metrics"))
    identity = _mapping(report.get("identity_diagnostics"))
    events = _mapping(report.get("event_counts"))
    qualification = _mapping(report.get("qualification"))
    lines = [
        "# 低吸因果龙头任期 V8",
        "",
        f"- 研究状态：`{report.get('research_status')}`",
        f"- 正式策略：`{str(bool(report.get('formal_strategy'))).lower()}`",
        f"- 开发段入选规则：`{report.get('selected_rule') or 'null'}`",
        f"- 原始 Top3 行：`{identity.get('raw_current_top3_rows', 0)}`",
        f"- 任期有效行：`{identity.get('tenure_active_rows', 0)}`",
        f"- 排名宽限行：`{identity.get('rank_grace_rows', 0)}`",
        f"- 主概念精确支撑：`{events.get('primary_exact_support_events', 0)}`",
        f"- 主概念确认：`{events.get('primary_confirmations', 0)}`",
        "",
        "## 开发段",
        "",
        f"- 成交：`{metrics.get('closed_trades', 0)}`",
        f"- 胜率：`{_percent(metrics.get('win_rate_pct'))}`",
        f"- 平均净收益：`{_percent(metrics.get('mean_net_return_pct'))}`",
        f"- 利润因子：`{_number(metrics.get('profit_factor'))}`",
        f"- 四仓复利：`{_percent(development.get('development_cash_compound_pct'))}`",
        f"- block 4：`{_block_text(report.get('block_4'))}`",
        f"- block 5：`{_block_text(report.get('block_5'))}`",
        "",
        "## 资格",
        "",
        f"- 历史代理通过：`{str(bool(qualification.get('historical_proxy_gate_passed'))).lower()}`",
        f"- 失败门：`{', '.join(map(str, qualification.get('failed_gates', ()))) or '无'}`",
        "",
        "## 个股任期",
        "",
    ]
    for case in report.get("named_case_audit", ()):
        case_map = _mapping(case)
        lines.append(
            f"- {case_map.get('stock_name')} `{case_map.get('vt_symbol')}`："
            f"任期 `{case_map.get('tenure_count', 0)}`，"
            f"精确支撑 `{len(case_map.get('exact_support_dates', ()))}`，"
            f"确认 `{len(case_map.get('confirmation_dates', ()))}`"
        )
    lines.extend(["", "## 边界", ""])
    lines.extend(f"- {item}" for item in report.get("boundaries", ()))
    return "\n".join(lines).rstrip() + "\n"


def _execute_events(
    events: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    executor: TradeExecutor,
) -> pd.DataFrame:
    if not events.empty:
        return executor(events, stock_bars)
    empty = events.copy()
    for column, dtype in (
        ("entry_date", "datetime64[ns]"),
        ("entry_price", float),
        ("d1_date", "datetime64[ns]"),
        ("d1_close", float),
        ("d1_net_return_pct", float),
        ("exit_date", "datetime64[ns]"),
        ("exit_price", float),
        ("net_return_pct", float),
        ("round_trip_cost_pct", float),
    ):
        empty[column] = pd.Series(index=empty.index, dtype=dtype)
    return empty


def _late_block_result(trades: pd.DataFrame) -> dict[str, Any]:
    metrics = summarize_d1_trades(trades)
    passed = bool(
        int(metrics["closed_trades"]) >= MIN_LATE_BLOCK_TRADES
        and float(metrics["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
        and float(metrics["mean_net_return_pct"] or 0.0) > 0.0
        and float(metrics["profit_factor"] or 0.0) >= MIN_PROFIT_FACTOR
    )
    return {**metrics, "passed": passed}


def _unvalidated_qualification(
    failed_gate: str,
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    formal_blockers = []
    if int(coverage.get("strict_historical_membership_rows") or 0) <= 0:
        formal_blockers.append("strict_historical_membership_missing")
    if int(coverage.get("preclose_execution_rows") or 0) <= 0:
        formal_blockers.append("executable_preclose_price_missing")
    return {
        "historical_proxy_gate_passed": False,
        "formal_strategy": False,
        "formal_metrics": None,
        "overall_metrics": None,
        "qualified_material_environments": [],
        "failed_gates": [failed_gate],
        "formal_blockers": formal_blockers,
    }


def _research_status(evaluation: TenureConfirmationEvaluation) -> str:
    if evaluation.development_freeze.get("selected_rule") is None:
        return "no_development_tenure_rule"
    if evaluation.block_4 is not None and not bool(evaluation.block_4.get("passed")):
        return "block_4_failed"
    if evaluation.block_5 is not None and not bool(evaluation.block_5.get("passed")):
        return "block_5_failed"
    if evaluation.qualification.get("historical_proxy_gate_passed"):
        return "historical_proxy_gate_passed"
    return "historical_proxy_gate_failed"


def _concat_trades(*frames: pd.DataFrame) -> pd.DataFrame:
    available = [frame for frame in frames if not frame.empty]
    if not available:
        return frames[0].copy() if frames else pd.DataFrame()
    return _sort_trades(pd.concat(available, ignore_index=True, sort=False))


def _sort_trades(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    columns = [
        column
        for column in ("signal_date", "entry_date", "dynamic_rank", "signal_id")
        if column in frame
    ]
    return frame.sort_values(columns, kind="stable").reset_index(drop=True)


def _dated_event_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    fields = (
        "signal_date",
        "campaign_id",
        "sector_id",
        "concept_name",
        "wave_number",
        "required_support",
        "duplicate_concept_count",
    )
    return _records(frame.loc[:, [field for field in fields if field in frame]])


def _symbol_rows(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty or "vt_symbol" not in frame:
        return frame.iloc[0:0].copy()
    return frame.loc[frame["vt_symbol"].astype(str).eq(symbol)].copy()


def _add_fingerprint(
    target: dict[str, Mapping[str, Any]],
    name: str,
    frame: pd.DataFrame,
    identity: Sequence[str],
    fingerprint: Callable[..., Any],
) -> None:
    if frame.empty:
        return
    target[name] = fingerprint(frame, identity_columns=identity).as_dict()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return _json_safe(frame.to_dict("records"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NaT or value is pd.NA:
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _date_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).date().isoformat()


def _optional_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _percent(value: object) -> str:
    number = _finite_or_none(value)
    return "null" if number is None else f"{number:.4f}%"


def _number(value: object) -> str:
    number = _finite_or_none(value)
    return "null" if number is None else f"{number:.4f}"


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _block_text(value: object) -> str:
    if not isinstance(value, Mapping):
        return "未读取"
    return "通过" if bool(value.get("passed")) else "失败"


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")
