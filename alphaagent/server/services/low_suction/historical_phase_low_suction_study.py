"""Historical low-suction validation joined to causal stock-level phases."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .event_recognition_5m_study import FROZEN_RULES


JOIN_KEYS = ("vt_symbol", "entry_date")
PHASE_FEATURE_COLUMNS = (
    "phase",
    "phase_reason",
    "phase_feature_complete",
    "feature_cutoff_date",
    "volume_class",
    "relative_strength_state",
    "stock_close",
    "ma5",
    "ma10",
    "ma20",
    "stock_daily_return_pct",
    "stock_return_3d_pct",
    "stock_return_5d_pct",
    "volume_to_prior_5d_ratio",
    "stock_excess_concept_3d_pct",
    "stock_excess_concept_3d_change_pct",
    "stock_excess_market_3d_pct",
)
PROHIBITED_PHASE_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "double_cost_net_return_pct",
        "mfe_pct",
        "mae_pct",
        "exit_price",
        "exit_price_raw",
        "outcome_group",
    }
)
COHORT_DIMENSIONS = (
    "volume_class",
    "relative_strength_state",
    "leader_rank_group",
    "market_regime",
    "intraday_volume_class",
    "signal_time_bucket",
    "pullback_depth_bucket",
)
TRANSITION_ATTRIBUTION_DIMENSIONS = (
    "market_regime",
    "volume_class",
    "relative_strength_state",
    "leader_rank_group",
)
OUTCOME_COLUMNS = (
    "event_id",
    "normal_status",
    "net_return_pct",
    "double_cost_net_return_pct",
)
DEVELOPMENT_BLOCKS = frozenset({1, 2, 3})
VALIDATION_BLOCKS = frozenset({4, 5})
MIN_DEVELOPMENT_TRADES = 30
MIN_DEVELOPMENT_DAYS = 20
MIN_VALIDATION_TRADES = 20
MIN_VALIDATION_DAYS = 15
MIN_CANDIDATE_WIN_RATE_PCT = 55.0
HIGH_WIN_RATE_PCT = 60.0
ELIGIBLE_PHASES = frozenset(
    {
        "first_launch",
        "divergence_restart",
        "healthy_pullback",
        "trend_continuation",
    }
)
RISK_PHASES = frozenset(
    {
        "continuous_acceleration",
        "climax_risk",
        "decay",
        "unclassified",
    }
)
STUDY_EVIDENCE_LEVEL = "historical_event_top3_stock_phase_low_suction_validation"


def join_historical_phase_trades(
    outcome_trades: pd.DataFrame,
    phase_panel: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Attach D-1 stock phases without dropping unmatched executed trades."""

    _require_columns(outcome_trades, JOIN_KEYS, "outcome trade")
    _require_columns(
        phase_panel,
        (*JOIN_KEYS, *PHASE_FEATURE_COLUMNS),
        "stock phase",
    )
    _reject_phase_leakage(phase_panel)
    outcomes = _normalize_entry_dates(outcome_trades)
    phases = _normalize_entry_dates(phase_panel)
    if outcomes.duplicated(list(JOIN_KEYS)).any():
        raise ValueError("outcome trade identities must be unique")
    if phases.duplicated(list(JOIN_KEYS)).any():
        raise ValueError("phase identities must be unique")

    selected_phases = phases.loc[:, [*JOIN_KEYS, *PHASE_FEATURE_COLUMNS]]
    merged = outcomes.merge(
        selected_phases,
        on=list(JOIN_KEYS),
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    merged["phase_matched"] = merged.pop("_merge").eq("both")
    matched = int(merged["phase_matched"].sum())
    coverage = {
        "outcome_trades": int(len(merged)),
        "matched_phase_trades": matched,
        "unmatched_phase_trades": int(len(merged) - matched),
    }
    return merged, coverage


def classify_signal_time(value: Any) -> str:
    """Classify elapsed minutes at the completed signal bar."""

    minutes = _finite_float(value)
    if minutes is None or minutes < 0:
        return "missing"
    if minutes <= 30:
        return "opening_30"
    if minutes <= 120:
        return "morning_31_120"
    return "afternoon_121_plus"


def classify_pullback_depth(value: Any) -> str:
    """Classify the signal close distance below the previous close."""

    distance = _finite_float(value)
    if distance is None or distance > 0:
        return "missing"
    depth = abs(distance)
    if depth <= 1:
        return "shallow_0_1"
    if depth <= 3:
        return "moderate_1_3"
    return "deep_3_plus"


def build_phase_cohort_membership(merged_trades: pd.DataFrame) -> pd.DataFrame:
    """Freeze phase plus at most one causal condition for every matched trade."""

    required = (
        "event_id",
        "vt_symbol",
        "entry_date",
        "block",
        "phase_matched",
        "phase",
        "volume_class",
        "relative_strength_state",
        "leader_rank_group",
        "market_regime",
        "intraday_volume_class",
        "signal_minutes_from_open",
        "distance_to_previous_close_pct",
    )
    _require_columns(merged_trades, required, "merged phase trade")
    frame = _normalize_entry_dates(merged_trades)
    frame = frame.loc[frame["phase_matched"].astype(bool)].copy()
    frame["signal_time_bucket"] = frame["signal_minutes_from_open"].map(
        classify_signal_time
    )
    frame["pullback_depth_bucket"] = frame[
        "distance_to_previous_close_pct"
    ].map(classify_pullback_depth)
    identity_columns = [
        "event_id",
        "vt_symbol",
        "entry_date",
        "block",
        "phase",
    ]
    memberships = [
        _cohort_membership_rows(
            frame,
            identity_columns=identity_columns,
            dimension=None,
        )
    ]
    memberships.extend(
        _cohort_membership_rows(
            frame,
            identity_columns=identity_columns,
            dimension=dimension,
        )
        for dimension in COHORT_DIMENSIONS
    )
    result = pd.concat(memberships, ignore_index=True)
    if result.duplicated(["event_id", "table_id", "cohort_key"]).any():
        raise ValueError("phase cohort identities must be unique")
    return result.sort_values(
        ["entry_date", "event_id", "table_id", "cohort_key"],
        kind="stable",
    ).reset_index(drop=True)


def attach_phase_cohort_outcomes(
    membership: pd.DataFrame,
    outcome_trades: pd.DataFrame,
) -> pd.DataFrame:
    """Attach execution labels only after causal cohort identities are frozen."""

    _require_columns(
        membership,
        ("event_id", "table_id", "cohort_key"),
        "phase cohort membership",
    )
    _require_columns(outcome_trades, OUTCOME_COLUMNS, "outcome trade")
    outcomes = outcome_trades.loc[:, list(OUTCOME_COLUMNS)].copy()
    if outcomes["event_id"].duplicated().any():
        raise ValueError("outcome event IDs must be unique")
    result = membership.merge(
        outcomes,
        on="event_id",
        how="left",
        validate="many_to_one",
    )
    if result[list(OUTCOME_COLUMNS[1:])].isna().all(axis=1).any():
        raise ValueError("every phase cohort membership requires an outcome row")
    return result.sort_values(
        ["entry_date", "event_id", "table_id", "cohort_key"],
        kind="stable",
    ).reset_index(drop=True)


def build_phase_transition_cohort_trades(
    normal_outcomes: pd.DataFrame,
    stressed_outcomes: pd.DataFrame,
    phase_panel: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Join frozen recovery identities to phases before attaching outcomes."""

    identity_columns = (
        "transition_id",
        "rule",
        "vt_symbol",
        "entry_date",
        "recognition_rank",
        "active_direction",
        "danger_state",
    )
    _require_columns(
        normal_outcomes,
        (*identity_columns, "status", "net_return_pct"),
        "normal transition outcome",
    )
    _require_columns(
        stressed_outcomes,
        ("transition_id", "net_return_pct"),
        "stressed transition outcome",
    )
    _require_columns(
        phase_panel,
        (
            *JOIN_KEYS,
            "phase",
            "block",
            "volume_class",
            "relative_strength_state",
        ),
        "transition stock phase",
    )
    normal = _normalize_entry_dates(normal_outcomes)
    phases = _normalize_entry_dates(phase_panel)
    if normal["transition_id"].duplicated().any():
        raise ValueError("normal transition IDs must be unique")
    if stressed_outcomes["transition_id"].duplicated().any():
        raise ValueError("stressed transition IDs must be unique")
    if phases.duplicated(list(JOIN_KEYS)).any():
        raise ValueError("phase identities must be unique")
    invalid_rules = sorted(set(normal["rule"].astype(str)) - set(FROZEN_RULES))
    if invalid_rules:
        raise ValueError(f"unregistered transition rules: {invalid_rules}")

    identities = normal.loc[:, list(identity_columns)]
    joined = identities.merge(
        phases.loc[
            :,
            [
                *JOIN_KEYS,
                "phase",
                "block",
                "volume_class",
                "relative_strength_state",
            ],
        ],
        on=list(JOIN_KEYS),
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    matched_mask = joined["_merge"].eq("both")
    coverage = {
        "transition_outcomes": int(len(joined)),
        "transition_phase_matched": int(matched_mask.sum()),
        "transition_phase_unmatched": int((~matched_mask).sum()),
    }
    membership = joined.loc[matched_mask].drop(columns="_merge").copy()
    membership["event_id"] = membership["transition_id"].astype(str)
    membership["table_id"] = "phase_x_transition_rule"
    membership["cohort_key"] = (
        "phase="
        + membership["phase"].astype(str)
        + "|transition_rule="
        + membership["rule"].astype(str)
    )
    membership["condition_count"] = 2
    membership["market_regime"] = (
        membership["active_direction"].astype(str)
        + "/"
        + membership["danger_state"].astype(str)
    )
    membership["leader_rank_group"] = np.where(
        pd.to_numeric(membership["recognition_rank"], errors="raise").eq(1),
        "rank_1",
        "rank_2_3",
    )
    normal_labels = normal.loc[
        :, ["transition_id", "status", "net_return_pct"]
    ].rename(columns={"status": "normal_status"})
    stressed_labels = stressed_outcomes.loc[
        :, ["transition_id", "net_return_pct"]
    ].rename(columns={"net_return_pct": "double_cost_net_return_pct"})
    result = membership.merge(
        normal_labels,
        on="transition_id",
        validate="one_to_one",
    ).merge(
        stressed_labels,
        on="transition_id",
        validate="one_to_one",
    )
    columns = (
        "event_id",
        "vt_symbol",
        "entry_date",
        "block",
        "phase",
        "table_id",
        "cohort_key",
        "condition_count",
        "rule",
        "market_regime",
        "volume_class",
        "relative_strength_state",
        "leader_rank_group",
        "normal_status",
        "net_return_pct",
        "double_cost_net_return_pct",
    )
    return (
        result.loc[:, list(columns)]
        .sort_values(["entry_date", "event_id"], kind="stable")
        .reset_index(drop=True),
        coverage,
    )


def build_historical_phase_metrics(cohort_trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize frozen cohorts over all, development, validation, and blocks."""

    required = (
        "event_id",
        "entry_date",
        "block",
        "phase",
        "table_id",
        "cohort_key",
        "condition_count",
        *OUTCOME_COLUMNS[1:],
    )
    _require_columns(cohort_trades, required, "phase cohort trade")
    frame = _normalize_entry_dates(cohort_trades)
    rows = []
    grouped = frame.groupby(["table_id", "cohort_key"], sort=True)
    for (table_id, cohort_key), cohort in grouped:
        condition_count = int(cohort["condition_count"].iloc[0])
        for segment, blocks in _metric_segments():
            summary = _summarize_cohort_rows(
                cohort.loc[cohort["block"].isin(blocks)]
            )
            rows.append(
                {
                    "table_id": str(table_id),
                    "cohort_key": str(cohort_key),
                    "phase": str(cohort["phase"].iloc[0]),
                    "condition_count": condition_count,
                    "segment": segment,
                    **summary,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["table_id", "cohort_key", "segment"],
        kind="stable",
    ).reset_index(drop=True)


def evaluate_historical_phase_cohorts(metrics: pd.DataFrame) -> pd.DataFrame:
    """Require a development candidate to retain its edge in later blocks."""

    required = (
        "table_id",
        "cohort_key",
        "phase",
        "condition_count",
        "segment",
        "closed_trades",
        "source_days",
        "win_rate_pct",
        "mean_net_return_pct",
        "profit_factor",
        "double_cost_mean_net_return_pct",
    )
    _require_columns(metrics, required, "historical phase metric")
    rows = []
    grouped = metrics.groupby(["table_id", "cohort_key"], sort=True)
    for (table_id, cohort_key), cohort in grouped:
        by_segment = cohort.set_index("segment")
        development = by_segment.loc["development"]
        validation = by_segment.loc["validation"]
        development_candidate = _passes_candidate_gate(
            development,
            minimum_trades=MIN_DEVELOPMENT_TRADES,
            minimum_days=MIN_DEVELOPMENT_DAYS,
        ) and str(development["phase"]) in ELIGIBLE_PHASES
        validation_sample = _passes_sample_gate(
            validation,
            minimum_trades=MIN_VALIDATION_TRADES,
            minimum_days=MIN_VALIDATION_DAYS,
        )
        validation_positive = validation_sample and _passes_performance_gate(
            validation
        )
        high_win = (
            development_candidate
            and validation_positive
            and float(development["win_rate_pct"]) > HIGH_WIN_RATE_PCT
            and float(validation["win_rate_pct"]) > HIGH_WIN_RATE_PCT
        )
        if str(development["phase"]) not in ELIGIBLE_PHASES:
            status = "risk_phase_not_eligible"
        elif not development_candidate:
            status = "not_development_candidate"
        elif not validation_sample:
            status = "validation_insufficient"
        elif not validation_positive:
            status = "validation_failed"
        elif high_win:
            status = "high_win_confirmed"
        else:
            status = "positive_confirmed"
        rows.append(
            {
                "table_id": str(table_id),
                "cohort_key": str(cohort_key),
                "phase": str(development["phase"]),
                "condition_count": int(development["condition_count"]),
                "status": status,
                "development_closed_trades": int(development["closed_trades"]),
                "development_source_days": int(development["source_days"]),
                "development_win_rate_pct": development["win_rate_pct"],
                "development_mean_net_return_pct": development[
                    "mean_net_return_pct"
                ],
                "validation_closed_trades": int(validation["closed_trades"]),
                "validation_source_days": int(validation["source_days"]),
                "validation_win_rate_pct": validation["win_rate_pct"],
                "validation_mean_net_return_pct": validation[
                    "mean_net_return_pct"
                ],
                "validation_profit_factor": validation["profit_factor"],
                "validation_double_cost_mean_net_return_pct": validation[
                    "double_cost_mean_net_return_pct"
                ],
                "validation_compound_return_pct": validation[
                    "compound_return_pct"
                ],
                "validation_maximum_drawdown_pct": validation[
                    "maximum_drawdown_pct"
                ],
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["status", "table_id", "cohort_key"],
        kind="stable",
    ).reset_index(drop=True)


def load_historical_phase_low_suction_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Build the historical study from existing daily-phase and outcome ledgers."""

    from .daily_phase_study import load_daily_phase_study_data
    from .outcome_group_study import load_outcome_group_study_data

    phase_panel, _trades, _metrics, _attribution, _evaluation, phase_metadata = (
        load_daily_phase_study_data()
    )
    _candidates, _signals, outcome_trades, outcome_metadata = (
        load_outcome_group_study_data()
    )
    merged, join_coverage = join_historical_phase_trades(
        outcome_trades,
        phase_panel,
    )
    first_touch_membership = build_phase_cohort_membership(merged)
    first_touch_trades = attach_phase_cohort_outcomes(
        first_touch_membership,
        merged,
    )
    transition_trades, transition_coverage, transition_fingerprints = (
        load_historical_phase_transition_cohort_trades(phase_panel)
    )
    membership_columns = (
        "event_id",
        "vt_symbol",
        "entry_date",
        "block",
        "phase",
        "table_id",
        "cohort_key",
        "condition_count",
    )
    transition_membership = transition_trades.loc[
        :, list(membership_columns)
    ]
    membership = pd.concat(
        [first_touch_membership, transition_membership],
        ignore_index=True,
    )
    cohort_trades = pd.concat(
        [first_touch_trades, transition_trades],
        ignore_index=True,
    )
    metrics = build_historical_phase_metrics(cohort_trades)
    evaluation = evaluate_historical_phase_cohorts(metrics)
    coverage = {
        **join_coverage,
        "phase_panel_rows": int(len(phase_panel)),
        "matched_source_days": int(
            merged.loc[merged["phase_matched"], "entry_date"].nunique()
        ),
        "matched_stocks": int(
            merged.loc[merged["phase_matched"], "vt_symbol"].nunique()
        ),
        **transition_coverage,
        "first_touch_cohort_membership_rows": int(len(first_touch_membership)),
        "cohort_membership_rows": int(len(membership)),
        "cohort_metric_rows": int(len(metrics)),
    }
    metadata = {
        "coverage": coverage,
        "input_fingerprints": {
            "daily_phase": dict(phase_metadata.get("input_fingerprints", {})),
            "outcome_group": dict(outcome_metadata.get("input_fingerprints", {})),
            "phase_transitions": transition_fingerprints,
        },
    }
    return merged, membership, cohort_trades, metrics, evaluation, metadata


def load_historical_phase_transition_cohort_trades(
    phase_panel: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int], dict[str, Any]]:
    """Execute the four existing recovery rules on complete historical 5m days."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    from .event_neutral_days import load_event_neutral_comparison_inputs
    from .event_recognition_5m_study import (
        build_event_5m_state_panel,
        execute_event_5m_transitions,
        extract_frozen_transitions,
    )
    from .event_recognition_minutes import INTERVAL, REQUIRED_BARS
    from .outcome_group_minutes import load_outcome_group_5m_manifest
    from .research_protocol import fingerprint_frame

    inputs = load_event_neutral_comparison_inputs()
    candidates = inputs.candidates.copy()
    manifest = load_outcome_group_5m_manifest(candidates)
    if not manifest["status"].eq("complete").all():
        raise ValueError("phase transition minute manifest must be complete")
    symbols = tuple(sorted(candidates["vt_symbol"].astype(str).unique()))
    dates = tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique()))
    statement = (
        select(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
            schema.stock_minute_bars.c.interval,
            schema.stock_minute_bars.c.open_price,
            schema.stock_minute_bars.c.high_price,
            schema.stock_minute_bars.c.low_price,
            schema.stock_minute_bars.c.close_price,
            schema.stock_minute_bars.c.volume,
            schema.stock_minute_bars.c.turnover,
            schema.stock_minute_bars.c.source,
        )
        .where(
            schema.stock_minute_bars.c.vt_symbol.in_(symbols),
            schema.stock_minute_bars.c.trade_date.between(dates[0], dates[-1]),
            schema.stock_minute_bars.c.interval == INTERVAL,
        )
        .order_by(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
        )
    )
    loaded = pd.read_sql(statement, get_engine(), parse_dates=["bar_time"])
    minutes = _filter_candidate_minute_pairs(candidates, loaded)
    expected_rows = len(candidates) * REQUIRED_BARS
    if len(minutes) != expected_rows:
        raise ValueError("phase transition minute rows must be complete")
    state_panel = build_event_5m_state_panel(candidates, minutes)
    transitions = extract_frozen_transitions(state_panel)
    normal = execute_event_5m_transitions(
        transitions,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    stressed = execute_event_5m_transitions(
        transitions,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
        cost_multiplier=2.0,
    )
    cohort_trades, join_coverage = build_phase_transition_cohort_trades(
        normal,
        stressed,
        phase_panel,
    )
    coverage = {
        **join_coverage,
        "transition_candidate_days": int(len(candidates)),
        "transition_minute_rows": int(len(minutes)),
        "transition_signals": int(len(transitions)),
        "transition_closed_trades": int(normal["status"].eq("closed").sum()),
    }
    fingerprints = {
        "minutes": fingerprint_frame(
            minutes,
            identity_columns=("vt_symbol", "bar_time", "interval"),
        ).as_dict(),
        "transitions": fingerprint_frame(
            transitions,
            identity_columns=("transition_id",),
        ).as_dict(),
        "normal_outcomes": fingerprint_frame(
            normal,
            identity_columns=("transition_id",),
        ).as_dict(),
        "stressed_outcomes": fingerprint_frame(
            stressed,
            identity_columns=("transition_id",),
        ).as_dict(),
    }
    return cohort_trades, coverage, fingerprints


def run_historical_phase_low_suction_study() -> dict[str, Any]:
    """Run the immediate historical stock-phase low-suction validation."""

    return build_historical_phase_report(*load_historical_phase_low_suction_data())


def build_historical_phase_report(
    merged_trades: pd.DataFrame,
    membership: pd.DataFrame,
    cohort_trades: pd.DataFrame,
    metrics: pd.DataFrame,
    evaluation: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Render complete historical diagnostics without promoting a formal rule."""

    matched = merged_trades.loc[merged_trades["phase_matched"].astype(bool)].copy()
    overall = _summarize_cohort_rows(matched)
    phase_baselines = metrics.loc[
        metrics["table_id"].eq("phase")
        & metrics["segment"].isin(("all", "development", "validation"))
    ]
    development_candidates = evaluation.loc[
        ~evaluation["status"].isin(
            ("not_development_candidate", "risk_phase_not_eligible")
        )
    ]
    confirmed = evaluation.loc[
        evaluation["status"].isin(("positive_confirmed", "high_win_confirmed"))
    ]
    best_validation = _best_validation_cohorts(metrics)
    stable_positive = _stable_positive_expectation_cohorts(metrics)
    transition_attribution = _build_transition_attribution_metrics(cohort_trades)
    stable_keys = set(stable_positive["cohort_key"].astype(str))
    stable_transition_attribution = transition_attribution.loc[
        transition_attribution["cohort_key"].astype(str).isin(stable_keys)
    ]
    environment_evaluation = _evaluate_transition_environments(
        stable_positive,
        stable_transition_attribution,
    )
    if evaluation["status"].eq("high_win_confirmed").any():
        conclusion = "historical_high_win_cohort_found"
    elif not confirmed.empty:
        conclusion = "historical_positive_cohort_found"
    elif environment_evaluation.get("environment_positive_confirmed_cohorts", 0):
        conclusion = "environment_confirmed_positive_low_win_transition"
    elif not stable_positive.empty:
        conclusion = "time_split_positive_but_regime_confounded"
    else:
        conclusion = "no_time_split_stable_high_win_cohort"
    coverage = dict(metadata.get("coverage", {}))
    coverage.setdefault("cohort_membership_rows", int(len(membership)))
    coverage.setdefault("cohort_trade_rows", int(len(cohort_trades)))
    return {
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": conclusion,
        "formal_metrics": None,
        "formal_rule_selected": False,
        "strict_historical_top3_claim": False,
        "historical_validation_values_read": True,
        "outer_holdout_price_values_read": False,
        "late_segment_is_unseen_validation": False,
        "forward_ledger_rows_read": 0,
        "current_membership_rows_read": 0,
        "frozen_contract": {
            "identity": "historical_event_recognition_rank_1_3_proxy",
            "feature_cutoff": "D-1 official close plus completed 5m signal bar",
            "entry": "first 5m close at or below D-1 close; next 5m open",
            "exit": "D+1 official close with T+1 and costs",
            "development_blocks": sorted(DEVELOPMENT_BLOCKS),
            "validation_blocks": sorted(VALIDATION_BLOCKS),
            "eligible_phases": sorted(ELIGIBLE_PHASES),
            "risk_phases": sorted(RISK_PHASES),
            "cohort_dimensions": list(COHORT_DIMENSIONS),
            "transition_rules": list(FROZEN_RULES),
            "maximum_conditions": 2,
        },
        "coverage": coverage,
        "overall_metrics": overall,
        "first_touch_gate_summary": _cohort_gate_summary(
            metrics.loc[metrics["table_id"].ne("phase_x_transition_rule")],
            evaluation.loc[
                evaluation["table_id"].ne("phase_x_transition_rule")
            ],
        ),
        "cohort_gate_summary": _cohort_gate_summary(metrics, evaluation),
        "phase_baselines": _records(phase_baselines),
        "transition_rule_metrics": _records(
            metrics.loc[
                metrics["table_id"].eq("phase_x_transition_rule")
                & metrics["segment"].isin(("all", "development", "validation"))
            ]
        ),
        "winner_loser_profiles": _records(_winner_loser_profiles(matched)),
        "cohort_metrics": _records(metrics),
        "cohort_evaluation": _records(evaluation),
        "development_candidates": _records(development_candidates),
        "confirmed_cohorts": _records(confirmed),
        "stable_positive_expectation_cohorts": _records(stable_positive),
        "stable_transition_attribution": _records(
            stable_transition_attribution
        ),
        "transition_environment_evaluation": environment_evaluation,
        "best_validation_cohorts": _records(best_validation),
        "historical_best_available": (
            _records(best_validation.head(1))[0]
            if not best_validation.empty
            else None
        ),
        "input_fingerprints": dict(metadata.get("input_fingerprints", {})),
        "limitations": [
            "historical identity is event-recognition Rank1-3, not strict full-member concept Top3",
            "blocks 4-5 are chronological validation but were visible in earlier proxy reports",
            "daily equal-weight compounding is comparative and not a production cash ledger",
            "no fitted threshold, multi-condition search, forward ledger, or current membership is read",
        ],
    }


def render_historical_phase_json(report: Mapping[str, Any]) -> str:
    """Render deterministic machine-readable historical evidence."""

    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_historical_phase_markdown(report: Mapping[str, Any]) -> str:
    """Render the decision-bearing subset of the historical report."""

    coverage = report["coverage"]
    overall = report["overall_metrics"]
    lines = [
        "# AlphaAgent 历史个股主升低吸验证",
        "",
        f"结论：`{report['overall_conclusion']}`  ",
        "身份：历史事件 Top3 代理，不是严格历史全成员 Top3  ",
        "买卖：首次 5 分钟收盘不高于前收，下一根开盘买入，D+1 收盘卖出  ",
        f"交易/匹配/未匹配：`{coverage.get('outcome_trades', 0)}/"
        f"{coverage.get('matched_phase_trades', 0)}/"
        f"{coverage.get('unmatched_phase_trades', 0)}`  ",
        f"匹配样本胜率/均值/双倍成本均值：`{_pct(overall.get('win_rate_pct'))}/"
        f"{_pct(overall.get('mean_net_return_pct'))}/"
        f"{_pct(overall.get('double_cost_mean_net_return_pct'))}`",
        f"首次触价充分样本组/两段正期望/两段胜率>50%：`"
        f"{report['first_touch_gate_summary']['adequately_sampled_eligible_cohorts']}/"
        f"{report['first_touch_gate_summary']['stable_positive_expectation_cohorts']}/"
        f"{report['first_touch_gate_summary']['both_segments_win_above_50_cohorts']}`",
        f"加入承接确认后充分样本组/两段正期望/高胜率确认：`"
        f"{report['cohort_gate_summary']['adequately_sampled_eligible_cohorts']}/"
        f"{report['cohort_gate_summary']['stable_positive_expectation_cohorts']}/"
        f"{report['cohort_gate_summary']['high_win_confirmed_cohorts']}`",
        "",
        "## 个股阶段基线",
        "",
        "| Phase | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["phase_baselines"]:
        lines.append(
            f"| `{row['phase']}` | `{row['segment']}` | {row['closed_trades']} | "
            f"{row['source_days']} | {_pct(row['win_rate_pct'])} | "
            f"{_pct(row['mean_net_return_pct'])} | {_number(row['profit_factor'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} | "
            f"{_pct(row['compound_return_pct'])} | "
            f"{_pct(row['maximum_drawdown_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## 开发候选与验证",
            "",
            "| Cohort | Status | Dev trades/days | Dev win/mean | Val trades/days | Val win/mean | Val 2x mean | Val compound/drawdown |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    candidates = list(report["development_candidates"])
    if not candidates:
        lines.append("| - | `none` | - | - | - | - | - | - |")
    for row in candidates:
        lines.append(
            f"| `{row['cohort_key']}` | `{row['status']}` | "
            f"{row['development_closed_trades']}/{row['development_source_days']} | "
            f"{_pct(row['development_win_rate_pct'])}/{_pct(row['development_mean_net_return_pct'])} | "
            f"{row['validation_closed_trades']}/{row['validation_source_days']} | "
            f"{_pct(row['validation_win_rate_pct'])}/{_pct(row['validation_mean_net_return_pct'])} | "
            f"{_pct(row['validation_double_cost_mean_net_return_pct'])} | "
            f"{_pct(row['validation_compound_return_pct'])}/"
            f"{_pct(row['validation_maximum_drawdown_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## 时间分段正期望但非高胜率",
            "",
            "| Cohort | Dev trades/days | Dev win/mean/2x | Val trades/days | Val win/mean/2x | Val compound/drawdown |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    stable_positive = list(report["stable_positive_expectation_cohorts"])
    if not stable_positive:
        lines.append("| - | - | - | - | - | - |")
    for row in stable_positive:
        lines.append(
            f"| `{row['cohort_key']}` | "
            f"{int(row['closed_trades_development'])}/{int(row['source_days_development'])} | "
            f"{_pct(row['win_rate_pct_development'])}/"
            f"{_pct(row['mean_net_return_pct_development'])}/"
            f"{_pct(row['double_cost_mean_net_return_pct_development'])} | "
            f"{int(row['closed_trades_validation'])}/{int(row['source_days_validation'])} | "
            f"{_pct(row['win_rate_pct_validation'])}/"
            f"{_pct(row['mean_net_return_pct_validation'])}/"
            f"{_pct(row['double_cost_mean_net_return_pct_validation'])} | "
            f"{_pct(row['compound_return_pct_validation'])}/"
            f"{_pct(row['maximum_drawdown_pct_validation'])} |"
        )
    environment = report["transition_environment_evaluation"]
    lines.extend(
        [
            "",
            "## 金银环境复核",
            "",
            f"时间分段正期望候选：`{environment['time_split_positive_cohorts']}`；"
            f"同环境正期望确认：`{environment['environment_positive_confirmed_cohorts']}`；"
            f"环境混淆：`{environment['regime_confounded_cohorts']}`。",
            "",
        ]
    )
    lines.extend(
        [
            "",
            "## 正期望候选归因（不增加筛选条件）",
            "",
            "| Dimension | Value | Segment | Trades | Days | Win | Mean | 2x mean |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    attribution = list(report["stable_transition_attribution"])
    if not attribution:
        lines.append("| - | - | - | - | - | - | - | - |")
    for row in attribution:
        lines.append(
            f"| `{row['dimension']}` | `{row['value']}` | `{row['segment']}` | "
            f"{row['closed_trades']} | {row['source_days']} | "
            f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## 当前边界",
            "",
            "本报告立即验证历史规律，但不读取前向账本。只有开发与验证同时通过的组才会列入 confirmed；严格历史概念 Top3 仍因历史成员缺失而不作虚假声明。",
            "",
        ]
    )
    return "\n".join(lines)


def _best_validation_cohorts(metrics: pd.DataFrame) -> pd.DataFrame:
    validation = metrics.loc[
        metrics["segment"].eq("validation")
        & metrics["phase"].isin(ELIGIBLE_PHASES)
        & metrics["closed_trades"].ge(MIN_VALIDATION_TRADES)
        & metrics["source_days"].ge(MIN_VALIDATION_DAYS)
    ].copy()
    return validation.sort_values(
        [
            "win_rate_pct",
            "double_cost_mean_net_return_pct",
            "compound_return_pct",
            "closed_trades",
            "cohort_key",
        ],
        ascending=[False, False, False, False, True],
        kind="stable",
    ).head(20)


def _cohort_gate_summary(
    metrics: pd.DataFrame,
    evaluation: pd.DataFrame,
) -> dict[str, int]:
    adequate = _adequately_sampled_cohort_comparison(metrics)
    stable_positive = adequate.loc[
        _positive_expectation_mask(adequate, "development")
        & _positive_expectation_mask(adequate, "validation")
    ]
    both_win_above_50 = adequate.loc[
        adequate["win_rate_pct_development"].gt(50)
        & adequate["win_rate_pct_validation"].gt(50)
    ]
    return {
        "evaluated_cohorts": int(len(evaluation)),
        "adequately_sampled_eligible_cohorts": int(len(adequate)),
        "development_candidates": int(
            (
                ~evaluation["status"].isin(
                    ("not_development_candidate", "risk_phase_not_eligible")
                )
            ).sum()
        ),
        "stable_positive_expectation_cohorts": int(len(stable_positive)),
        "both_segments_win_above_50_cohorts": int(len(both_win_above_50)),
        "positive_confirmed_cohorts": int(
            evaluation["status"].eq("positive_confirmed").sum()
        ),
        "high_win_confirmed_cohorts": int(
            evaluation["status"].eq("high_win_confirmed").sum()
        ),
    }


def _stable_positive_expectation_cohorts(metrics: pd.DataFrame) -> pd.DataFrame:
    adequate = _adequately_sampled_cohort_comparison(metrics)
    stable = adequate.loc[
        _positive_expectation_mask(adequate, "development")
        & _positive_expectation_mask(adequate, "validation")
    ].copy()
    return stable.sort_values(
        [
            "compound_return_pct_validation",
            "double_cost_mean_net_return_pct_validation",
            "win_rate_pct_validation",
            "cohort_key",
        ],
        ascending=[False, False, False, True],
        kind="stable",
    )


def _adequately_sampled_cohort_comparison(metrics: pd.DataFrame) -> pd.DataFrame:
    selected = metrics.loc[
        metrics["segment"].isin(("development", "validation"))
    ]
    wide = selected.pivot(
        index=["table_id", "cohort_key", "phase", "condition_count"],
        columns="segment",
        values=[
            "closed_trades",
            "source_days",
            "win_rate_pct",
            "mean_net_return_pct",
            "profit_factor",
            "double_cost_mean_net_return_pct",
            "compound_return_pct",
            "maximum_drawdown_pct",
        ],
    )
    wide.columns = [
        f"{metric}_{segment}" for metric, segment in wide.columns
    ]
    wide = wide.reset_index()
    return wide.loc[
        wide["phase"].isin(ELIGIBLE_PHASES)
        & wide["closed_trades_development"].ge(MIN_DEVELOPMENT_TRADES)
        & wide["source_days_development"].ge(MIN_DEVELOPMENT_DAYS)
        & wide["closed_trades_validation"].ge(MIN_VALIDATION_TRADES)
        & wide["source_days_validation"].ge(MIN_VALIDATION_DAYS)
    ].copy()


def _positive_expectation_mask(frame: pd.DataFrame, segment: str) -> pd.Series:
    return (
        frame[f"mean_net_return_pct_{segment}"].gt(0)
        & frame[f"profit_factor_{segment}"].gt(1)
        & frame[f"double_cost_mean_net_return_pct_{segment}"].gt(0)
    )


def _winner_loser_profiles(matched: pd.DataFrame) -> pd.DataFrame:
    required = (
        "phase",
        "entry_date",
        "normal_status",
        "net_return_pct",
        "volume_to_prior_5d_ratio",
        "intraday_volume_ratio",
        "distance_to_previous_close_pct",
        "signal_minutes_from_open",
    )
    _require_columns(matched, required, "matched phase trade")
    closed = matched.loc[matched["normal_status"].eq("closed")].copy()
    returns = pd.to_numeric(closed["net_return_pct"], errors="coerce")
    closed["outcome_group"] = returns.map(
        lambda value: "winner" if value > 0 else "loser"
    )
    rows = []
    for (phase, outcome_group), group in closed.groupby(
        ["phase", "outcome_group"], sort=True
    ):
        rows.append(
            {
                "phase": str(phase),
                "outcome_group": str(outcome_group),
                "trades": int(len(group)),
                "source_days": int(group["entry_date"].nunique()),
                "median_daily_volume_ratio": _median_numeric(
                    group["volume_to_prior_5d_ratio"]
                ),
                "median_intraday_volume_ratio": _median_numeric(
                    group["intraday_volume_ratio"]
                ),
                "median_pullback_depth_pct": _median_numeric(
                    group["distance_to_previous_close_pct"]
                ),
                "median_signal_minutes_from_open": _median_numeric(
                    group["signal_minutes_from_open"]
                ),
            }
        )
    return pd.DataFrame(rows)


def _build_transition_attribution_metrics(
    cohort_trades: pd.DataFrame,
) -> pd.DataFrame:
    transitions = cohort_trades.loc[
        cohort_trades["table_id"].eq("phase_x_transition_rule")
    ].copy()
    if transitions.empty:
        return pd.DataFrame(
            columns=(
                "cohort_key",
                "dimension",
                "value",
                "segment",
                "closed_trades",
                "source_days",
                "win_rate_pct",
                "mean_net_return_pct",
                "double_cost_mean_net_return_pct",
            )
        )
    _require_columns(
        transitions,
        TRANSITION_ATTRIBUTION_DIMENSIONS,
        "transition attribution trade",
    )
    rows = []
    for dimension in TRANSITION_ATTRIBUTION_DIMENSIONS:
        grouped = transitions.groupby(
            ["cohort_key", dimension],
            sort=True,
            dropna=False,
        )
        for (cohort_key, value), group in grouped:
            for segment, blocks in _metric_segments()[:3]:
                summary = _summarize_cohort_rows(
                    group.loc[group["block"].isin(blocks)]
                )
                rows.append(
                    {
                        "cohort_key": str(cohort_key),
                        "dimension": dimension,
                        "value": str(value),
                        "segment": segment,
                        **summary,
                    }
                )
    return pd.DataFrame(rows).sort_values(
        ["cohort_key", "dimension", "value", "segment"],
        kind="stable",
    ).reset_index(drop=True)


def _evaluate_transition_environments(
    stable_positive: pd.DataFrame,
    attribution: pd.DataFrame,
) -> dict[str, Any]:
    evaluations = []
    for cohort_key in stable_positive.get(
        "cohort_key", pd.Series(dtype=object)
    ).astype(str):
        market = attribution.loc[
            attribution["cohort_key"].astype(str).eq(cohort_key)
            & attribution["dimension"].eq("market_regime")
            & attribution["segment"].isin(("development", "validation"))
        ]
        comparable = []
        positive = []
        high_win = []
        if not market.empty:
            wide = market.pivot(
                index="value",
                columns="segment",
                values=[
                    "closed_trades",
                    "source_days",
                    "win_rate_pct",
                    "mean_net_return_pct",
                    "profit_factor",
                    "double_cost_mean_net_return_pct",
                ],
            )
            for regime, row in wide.iterrows():
                if not _environment_sample_is_comparable(row):
                    continue
                comparable.append(str(regime))
                if _environment_expectation_is_positive(row):
                    positive.append(str(regime))
                    if (
                        float(row[("win_rate_pct", "development")])
                        > HIGH_WIN_RATE_PCT
                        and float(row[("win_rate_pct", "validation")])
                        > HIGH_WIN_RATE_PCT
                    ):
                        high_win.append(str(regime))
        status = (
            "environment_positive_confirmed"
            if positive
            else "regime_confounded"
        )
        evaluations.append(
            {
                "cohort_key": cohort_key,
                "status": status,
                "comparable_regimes": comparable,
                "positive_regimes": positive,
                "high_win_regimes": high_win,
            }
        )
    return {
        "time_split_positive_cohorts": int(len(stable_positive)),
        "environment_positive_confirmed_cohorts": sum(
            row["status"] == "environment_positive_confirmed"
            for row in evaluations
        ),
        "regime_confounded_cohorts": sum(
            row["status"] == "regime_confounded" for row in evaluations
        ),
        "cohorts": evaluations,
    }


def _environment_sample_is_comparable(row: pd.Series) -> bool:
    required = (
        ("closed_trades", "development", 10),
        ("source_days", "development", 5),
        ("closed_trades", "validation", 10),
        ("source_days", "validation", 5),
    )
    return all(
        (metric, segment) in row.index
        and pd.notna(row[(metric, segment)])
        and float(row[(metric, segment)]) >= minimum
        for metric, segment, minimum in required
    )


def _environment_expectation_is_positive(row: pd.Series) -> bool:
    for segment in ("development", "validation"):
        if not (
            float(row[("mean_net_return_pct", segment)]) > 0
            and float(row[("profit_factor", segment)]) > 1
            and float(row[("double_cost_mean_net_return_pct", segment)]) > 0
        ):
            return False
    return True


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (date, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    return value


def _median_numeric(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if not numeric.empty else None


def _pct(value: Any) -> str:
    number = _finite_float(value)
    return "-" if number is None else f"{number:.4f}%"


def _number(value: Any) -> str:
    number = _finite_float(value)
    return "-" if number is None else f"{number:.4f}"


def _cohort_membership_rows(
    frame: pd.DataFrame,
    *,
    identity_columns: list[str],
    dimension: str | None,
) -> pd.DataFrame:
    result = frame.loc[:, identity_columns].copy()
    phase_identity = "phase=" + result["phase"].fillna("missing").astype(str)
    if dimension is None:
        result["table_id"] = "phase"
        result["cohort_key"] = phase_identity
        result["condition_count"] = 1
        return result
    dimension_values = frame[dimension].fillna("missing").astype(str)
    result["table_id"] = f"phase_x_{dimension}"
    result["cohort_key"] = phase_identity + "|" + dimension + "=" + dimension_values
    result["condition_count"] = 2
    return result


def _filter_candidate_minute_pairs(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    pairs = candidates.loc[:, ["vt_symbol", "entry_date"]].copy()
    pairs["entry_date"] = pd.to_datetime(pairs["entry_date"], errors="raise").dt.date
    if pairs.duplicated(["vt_symbol", "entry_date"]).any():
        raise ValueError("transition candidate stock/date pairs must be unique")
    bars = minute_bars.copy()
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.date
    result = bars.merge(
        pairs,
        left_on=["vt_symbol", "trade_date"],
        right_on=["vt_symbol", "entry_date"],
        how="inner",
        validate="many_to_one",
    ).drop(columns="entry_date")
    return result.sort_values(
        ["vt_symbol", "trade_date", "bar_time"],
        kind="stable",
    ).reset_index(drop=True)


def _metric_segments() -> tuple[tuple[str, frozenset[int]], ...]:
    return (
        ("all", frozenset({1, 2, 3, 4, 5})),
        ("development", DEVELOPMENT_BLOCKS),
        ("validation", VALIDATION_BLOCKS),
        *((f"block_{block}", frozenset({block})) for block in range(1, 6)),
    )


def _summarize_cohort_rows(rows: pd.DataFrame) -> dict[str, Any]:
    closed = rows.loc[rows["normal_status"].eq("closed")].copy()
    returns = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
    stressed = pd.to_numeric(
        closed["double_cost_net_return_pct"], errors="coerce"
    ).dropna()
    compound, drawdown = _daily_compounding(closed)
    return {
        "signals": int(len(rows)),
        "closed_trades": int(len(returns)),
        "source_days": int(closed.loc[returns.index, "entry_date"].nunique()),
        "win_rate_pct": _win_rate(returns),
        "mean_net_return_pct": _mean(returns),
        "median_net_return_pct": _median(returns),
        "profit_factor": _profit_factor(returns),
        "double_cost_mean_net_return_pct": _mean(stressed),
        "compound_return_pct": compound,
        "maximum_drawdown_pct": drawdown,
    }


def _daily_compounding(rows: pd.DataFrame) -> tuple[float | None, float | None]:
    if rows.empty:
        return None, None
    frame = rows.copy()
    frame["net_return_pct"] = pd.to_numeric(
        frame["net_return_pct"], errors="coerce"
    )
    daily = frame.dropna(subset=["net_return_pct"]).groupby(
        "entry_date", sort=True
    )["net_return_pct"].mean()
    if daily.empty:
        return None, None
    equity = (1.0 + daily / 100.0).cumprod()
    running_peak = equity.cummax().clip(lower=1.0)
    drawdown = equity / running_peak - 1.0
    return float((equity.iloc[-1] - 1.0) * 100.0), float(drawdown.min() * 100.0)


def _passes_candidate_gate(
    metric: pd.Series,
    *,
    minimum_trades: int,
    minimum_days: int,
) -> bool:
    return _passes_sample_gate(
        metric,
        minimum_trades=minimum_trades,
        minimum_days=minimum_days,
    ) and _passes_performance_gate(metric)


def _passes_sample_gate(
    metric: pd.Series,
    *,
    minimum_trades: int,
    minimum_days: int,
) -> bool:
    return (
        int(metric["closed_trades"]) >= minimum_trades
        and int(metric["source_days"]) >= minimum_days
    )


def _passes_performance_gate(metric: pd.Series) -> bool:
    values = (
        metric["win_rate_pct"],
        metric["mean_net_return_pct"],
        metric["profit_factor"],
        metric["double_cost_mean_net_return_pct"],
    )
    if any(value is None or pd.isna(value) for value in values):
        return False
    return (
        float(metric["win_rate_pct"]) > MIN_CANDIDATE_WIN_RATE_PCT
        and float(metric["mean_net_return_pct"]) > 0
        and float(metric["profit_factor"]) > 1
        and float(metric["double_cost_mean_net_return_pct"]) > 0
    )


def _win_rate(values: pd.Series) -> float | None:
    return float(values.gt(0).mean() * 100.0) if not values.empty else None


def _mean(values: pd.Series) -> float | None:
    return float(values.mean()) if not values.empty else None


def _median(values: pd.Series) -> float | None:
    return float(values.median()) if not values.empty else None


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values.gt(0)].sum())
    losses = abs(float(values.loc[values.lt(0)].sum()))
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _normalize_entry_dates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["entry_date"] = pd.to_datetime(
        result["entry_date"], errors="raise"
    ).dt.date
    return result


def _reject_phase_leakage(frame: pd.DataFrame) -> None:
    columns = {str(column).lower() for column in frame.columns}
    prohibited = columns & PROHIBITED_PHASE_COLUMNS
    prohibited.update(
        column
        for column in columns
        if column.startswith("future_") or column.startswith("outcome_")
    )
    if prohibited:
        raise ValueError(
            f"stock phase contains future or outcome columns: {sorted(prohibited)}"
        )


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _require_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing required columns: {missing}")
