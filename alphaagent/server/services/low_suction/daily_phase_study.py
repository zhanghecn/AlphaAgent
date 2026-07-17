"""Causal daily lifecycle study for event-recognized leader spells."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .event_recognition_falsification import chronological_event_blocks
from .research_protocol import default_protocol, fingerprint_frame, protocol_hash
from .stock_main_rise_audit import execute_stock_main_rise_hold


PHASES = (
    "first_launch",
    "divergence_restart",
    "continuous_acceleration",
    "climax_risk",
    "healthy_pullback",
    "trend_continuation",
    "decay",
    "unclassified",
)
PHASE_PRECEDENCE = (
    "incomplete_history",
    "decay",
    "climax_risk",
    "continuous_acceleration",
    "divergence_restart",
    "first_launch",
    "healthy_pullback",
    "trend_continuation",
    "unclassified",
)
ELIGIBLE_PHASES = frozenset(
    {
        "first_launch",
        "divergence_restart",
        "continuous_acceleration",
        "healthy_pullback",
        "trend_continuation",
    }
)
STUDY_OFFSETS = (1, 2, 3, 4)
MIN_PHASE_TRADES = 30
MIN_PHASE_DAYS = 20
MAX_PROFIT_CONCENTRATION_PCT = 20.0
MIN_POSITIVE_BLOCKS = 4
STUDY_EVIDENCE_LEVEL = "event_recognition_daily_phase_hold_study"

CANDIDATE_COLUMNS = (
    "leader_spell_id",
    "recognition_source_date",
    "context_date",
    "entry_date",
    "planned_exit_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "stock_name",
    "recognition_rank",
    "cycle_relative_percentile",
    "spell_session_offset",
    "active_direction",
    "danger_state",
    "market_phase",
    "main_rise",
    "rank_mode",
)
STOCK_BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)
CONCEPT_BAR_COLUMNS = ("sector_id", "trade_date", "close_price")
MARKET_COLUMNS = ("trade_date", "market_daily_return")
PROHIBITED_FEATURE_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "double_cost_net_return_pct",
        "mfe_pct",
        "mae_pct",
        "exit_price",
        "exit_price_raw",
        "outcome_group",
        "future_5d_close_return_pct",
    }
)
PHASE_FEATURE_COLUMNS = (
    "stock_close",
    "stock_daily_return_pct",
    "ma5",
    "ma10",
    "ma20",
    "stock_return_3d_pct",
    "stock_return_5d_pct",
    "volume_to_prior_5d_ratio",
    "current_near_limit_up",
    "previous_near_limit_up",
    "consecutive_near_limit_up_days",
    "prior_near_limit_up_days_5d",
    "prior_near_limit_up_days_10d",
)


def build_daily_phase_panel(
    candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach D-1 causal features and one mutually exclusive leader phase."""

    _reject_feature_leakage(candidates, stock_bars, concept_bars, market_returns)
    _require_columns(candidates, CANDIDATE_COLUMNS, "leader-spell day")
    calendar = _prepare_calendar(trading_dates)
    selected = _prepare_candidates(candidates)
    if selected.empty:
        return _empty_phase_panel()

    stock_features = _build_stock_feature_panel(stock_bars, calendar)
    concept_features = _build_concept_feature_panel(concept_bars, calendar)
    market_features = _build_market_feature_panel(market_returns, calendar)

    result = selected.merge(
        stock_features,
        left_on=["vt_symbol", "context_date"],
        right_on=["vt_symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    ).drop(columns=["trade_date"])
    result = result.merge(
        concept_features,
        left_on=["sector_id", "context_date"],
        right_on=["sector_id", "trade_date"],
        how="left",
        validate="many_to_one",
    ).drop(columns=["trade_date"])
    result = result.merge(
        market_features,
        left_on="context_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    ).drop(columns=["trade_date"])

    result["stock_excess_concept_3d_pct"] = (
        result["stock_return_3d_pct"] - result["concept_return_3d_pct"]
    )
    prior_excess = (
        result["stock_return_3d_prior_pct"]
        - result["concept_return_3d_prior_pct"]
    )
    result["stock_excess_concept_3d_change_pct"] = (
        result["stock_excess_concept_3d_pct"] - prior_excess
    )
    result["stock_excess_market_3d_pct"] = (
        result["stock_return_3d_pct"] - result["market_return_3d_pct"]
    )
    numeric_phase_features = result.loc[
        :,
        [
            column
            for column in PHASE_FEATURE_COLUMNS
            if column not in {"current_near_limit_up", "previous_near_limit_up"}
        ],
    ].apply(pd.to_numeric, errors="coerce")
    result["phase_feature_complete"] = (
        numeric_phase_features.notna().all(axis=1)
        & np.isfinite(numeric_phase_features.to_numpy(dtype=float)).all(axis=1)
        & result["current_near_limit_up"].notna()
        & result["previous_near_limit_up"].notna()
    )
    classified = result.apply(classify_daily_phase, axis=1, result_type="expand")
    classified.columns = ["phase", "phase_reason"]
    result[["phase", "phase_reason"]] = classified
    result["volume_class"] = result["volume_to_prior_5d_ratio"].map(
        classify_volume_ratio
    )
    result["relative_strength_state"] = [
        classify_relative_strength(excess, change)
        for excess, change in zip(
            result["stock_excess_concept_3d_pct"],
            result["stock_excess_concept_3d_change_pct"],
            strict=True,
        )
    ]
    result["market_regime"] = (
        result["active_direction"].fillna("UNKNOWN").astype(str)
        + "/"
        + result["danger_state"].fillna("UNKNOWN").astype(str)
    )
    result["feature_cutoff_date"] = result["context_date"]
    result["event_id"] = (
        result["leader_spell_id"].astype(str)
        + ":"
        + result["context_date"].dt.strftime("%Y-%m-%d")
    )
    result["evidence_level"] = STUDY_EVIDENCE_LEVEL
    if result["event_id"].duplicated().any():
        raise ValueError("daily phase event IDs must be unique")
    if result.duplicated(["vt_symbol", "entry_date"]).any():
        raise ValueError("daily phase stock/entry rows must be unique")
    if not result["phase"].isin(PHASES).all():
        raise ValueError("daily phase classification must be exhaustive")
    return result.sort_values(
        ["entry_date", "sector_id", "recognition_rank", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)


def classify_daily_phase(values: Mapping[str, Any]) -> tuple[str, str]:
    """Apply the frozen mutually exclusive daily lifecycle contract."""

    if not bool(values.get("phase_feature_complete")):
        return "unclassified", "incomplete_causal_history"
    if not bool(values.get("main_rise")):
        return "decay", "exact_concept_cycle_ended"

    close = float(values["stock_close"])
    ma5 = float(values["ma5"])
    ma10 = float(values["ma10"])
    ma20 = float(values["ma20"])
    if close < ma10:
        return "decay", "close_below_ma10"
    if ma5 <= ma10:
        return "decay", "ma5_not_above_ma10"

    current_strong = bool(values["current_near_limit_up"])
    consecutive = int(values["consecutive_near_limit_up_days"])
    prior_10 = float(values["prior_near_limit_up_days_10d"])
    if current_strong and consecutive >= 3:
        return "climax_risk", "three_or_more_consecutive_strong_days"
    if current_strong and consecutive == 2:
        return "continuous_acceleration", "two_consecutive_strong_days"
    if current_strong and not bool(values["previous_near_limit_up"]) and prior_10 > 0:
        return "divergence_restart", "strong_day_after_prior_divergence"
    if current_strong and prior_10 == 0:
        return "first_launch", "first_strong_day_in_10_sessions"

    if (
        not current_strong
        and float(values["stock_daily_return_pct"]) <= 0
        and close >= ma5
        and float(values["prior_near_limit_up_days_5d"]) > 0
        and float(values["volume_to_prior_5d_ratio"]) < 1.0
    ):
        return "healthy_pullback", "nonpositive_above_ma5_after_strong_day_on_lower_volume"
    if close >= ma5 and ma5 > ma10 > ma20:
        return "trend_continuation", "ordered_stock_trend_without_strong_day"
    return "unclassified", "main_rise_observation_outside_frozen_phases"


def classify_volume_ratio(value: Any) -> str:
    """Map prior-five-session volume ratio to the frozen taxonomy."""

    ratio = _finite_float(value)
    if ratio is None or ratio < 0:
        return "missing"
    if ratio < 0.8:
        return "contraction"
    if ratio < 1.5:
        return "normal"
    if ratio < 2.5:
        return "expansion"
    return "explosion"


def classify_relative_strength(excess: Any, change: Any) -> str:
    """Classify stock-minus-concept three-day strength without fitted thresholds."""

    excess_value = _finite_float(excess)
    change_value = _finite_float(change)
    if excess_value is None or change_value is None:
        return "missing"
    if excess_value > 0 and change_value > 0:
        return "improving_positive"
    if excess_value > 0:
        return "positive_not_improving"
    return "non_positive"


def execute_daily_phase_holds(
    phase_panel: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Execute D-open/D+1-close outcomes under normal and double costs."""

    _require_columns(
        phase_panel,
        ("event_id", "vt_symbol", "context_date", "evidence_level"),
        "daily phase panel",
    )
    if phase_panel["event_id"].duplicated().any():
        raise ValueError("daily phase event IDs must be unique before execution")
    normal, stressed = execute_stock_main_rise_hold(
        phase_panel,
        daily_bars,
        trading_dates=trading_dates,
    )
    if set(normal["event_id"]) != set(stressed["event_id"]):
        raise ValueError("normal and double-cost phase identities must match")
    return normal, stressed


def build_daily_phase_trade_ledger(
    phase_panel: pd.DataFrame,
    normal_outcomes: pd.DataFrame,
    stressed_outcomes: pd.DataFrame,
) -> pd.DataFrame:
    """Join phase evidence and both execution surfaces without dropping failures."""

    _require_columns(phase_panel, ("event_id", "phase"), "daily phase panel")
    outcome_columns = (
        "event_id",
        "status",
        "reason",
        "entry_date",
        "exit_date",
        "entry_price_raw",
        "entry_price",
        "exit_price_raw",
        "exit_price",
        "volume",
        "buy_fee",
        "sell_fee",
        "total_fees",
        "gross_return_pct",
        "net_return_pct",
    )
    _require_columns(normal_outcomes, outcome_columns, "normal phase outcome")
    _require_columns(stressed_outcomes, outcome_columns, "stressed phase outcome")
    if normal_outcomes["event_id"].duplicated().any() or stressed_outcomes[
        "event_id"
    ].duplicated().any():
        raise ValueError("phase outcome event IDs must be unique")

    normal = normal_outcomes.loc[:, list(outcome_columns)].rename(
        columns={
            "status": "normal_status",
            "reason": "normal_reason",
            "entry_date": "actual_entry_date",
            "exit_date": "actual_exit_date",
        }
    )
    stressed = stressed_outcomes.loc[
        :,
        ["event_id", "status", "reason", "net_return_pct", "total_fees"],
    ].rename(
        columns={
            "status": "stressed_status",
            "reason": "stressed_reason",
            "net_return_pct": "double_cost_net_return_pct",
            "total_fees": "double_cost_total_fees",
        }
    )
    result = phase_panel.merge(
        normal,
        on="event_id",
        how="left",
        validate="one_to_one",
    ).merge(
        stressed,
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    return result.sort_values(["entry_date", "event_id"], kind="stable").reset_index(
        drop=True
    )


def classify_phase_baseline(metrics: Mapping[str, Any]) -> str:
    """Apply strict sample, expectation, cost and win-rate gates."""

    if (
        int(metrics.get("closed_trades") or 0) < MIN_PHASE_TRADES
        or int(metrics.get("source_days") or 0) < MIN_PHASE_DAYS
    ):
        return "insufficient_sample"
    win_rate = _finite_float(metrics.get("win_rate_pct"))
    mean_return = _finite_float(metrics.get("mean_net_return_pct"))
    profit_factor = _finite_float(
        metrics.get("profit_factor"), allow_infinite=True
    )
    stressed_mean = _finite_float(metrics.get("double_cost_mean_net_return_pct"))
    positive = (
        win_rate is not None
        and win_rate > 50.0
        and mean_return is not None
        and mean_return > 0
        and profit_factor is not None
        and profit_factor > 1
        and stressed_mean is not None
        and stressed_mean > 0
    )
    if positive and win_rate > 60.0:
        return "high_win_candidate"
    if positive:
        return "positive_candidate"
    return "not_positive_candidate"


def build_daily_phase_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize every observed phase over all, early/late and block segments."""

    _require_metric_trade_columns(trades)
    frame = trades.copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"], errors="raise").dt.normalize()
    phases = [phase for phase in PHASES if phase in set(frame["phase"].astype(str))]
    rows = []
    for phase in phases:
        phase_rows = frame.loc[frame["phase"].eq(phase)]
        for segment, blocks in _metric_segments():
            summary = _summarize_trade_rows(
                phase_rows.loc[phase_rows["block"].isin(blocks)]
            )
            rows.append(
                {
                    "phase": phase,
                    "segment": segment,
                    **summary,
                    "baseline_label": classify_phase_baseline(summary),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["phase", "segment"], kind="stable"
    ).reset_index(drop=True)


def build_daily_phase_attribution_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize phase x volume, relative-strength and market-regime cohorts."""

    _require_metric_trade_columns(trades)
    _require_columns(
        trades,
        ("volume_class", "relative_strength_state", "market_regime"),
        "phase attribution trade",
    )
    frame = trades.copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"], errors="raise").dt.normalize()
    rows = []
    for dimension in ("volume_class", "relative_strength_state", "market_regime"):
        grouped = frame.groupby(["phase", dimension], sort=True, dropna=False)
        for (phase, value), cohort in grouped:
            for segment, blocks in _metric_segments()[:3]:
                summary = _summarize_trade_rows(cohort.loc[cohort["block"].isin(blocks)])
                rows.append(
                    {
                        "phase": str(phase),
                        "dimension": dimension,
                        "cohort": str(value),
                        "segment": segment,
                        **summary,
                        "baseline_label": classify_phase_baseline(summary),
                    }
                )
    return pd.DataFrame(rows).sort_values(
        ["dimension", "phase", "cohort", "segment"], kind="stable"
    ).reset_index(drop=True)


def evaluate_daily_phase_candidates(metrics: pd.DataFrame) -> pd.DataFrame:
    """Evaluate early/late stability without promoting a production rule."""

    required = (
        "phase",
        "segment",
        "mean_net_return_pct",
        "profit_factor",
        "baseline_label",
        "maximum_stock_positive_profit_share_pct",
        "maximum_concept_positive_profit_share_pct",
        "maximum_month_positive_profit_share_pct",
    )
    _require_columns(metrics, required, "daily phase metric")
    rows = []
    for phase, group in metrics.groupby("phase", sort=True):
        by_segment = group.set_index("segment")
        early_label = _segment_value(by_segment, "early_1_3", "baseline_label")
        late_label = _segment_value(by_segment, "late_4_5", "baseline_label")
        all_row = by_segment.loc["all"] if "all" in by_segment.index else None
        concentration_ok = all_row is not None and all(
            _at_or_below(
                all_row[field],
                MAX_PROFIT_CONCENTRATION_PCT,
            )
            for field in (
                "maximum_stock_positive_profit_share_pct",
                "maximum_concept_positive_profit_share_pct",
                "maximum_month_positive_profit_share_pct",
            )
        )
        positive_blocks = 0
        for block in range(1, 6):
            segment = f"block_{block}"
            if segment not in by_segment.index:
                continue
            row = by_segment.loc[segment]
            mean_return = _finite_float(row["mean_net_return_pct"])
            profit_factor = _finite_float(row["profit_factor"], allow_infinite=True)
            if mean_return is not None and mean_return > 0 and profit_factor is not None and profit_factor > 1:
                positive_blocks += 1
        eligible = str(phase) in ELIGIBLE_PHASES
        both_high = early_label == "high_win_candidate" and late_label == "high_win_candidate"
        positive_labels = {"positive_candidate", "high_win_candidate"}
        both_positive = early_label in positive_labels and late_label in positive_labels
        stability_checks = positive_blocks >= MIN_POSITIVE_BLOCKS and concentration_ok
        rows.append(
            {
                "phase": str(phase),
                "eligible_for_minute_research": eligible,
                "early_label": early_label,
                "late_label": late_label,
                "positive_blocks": positive_blocks,
                "profit_concentration_ok": concentration_ok,
                "stable_positive_candidate": bool(
                    eligible and both_positive and stability_checks
                ),
                "stable_high_win_candidate": bool(
                    eligible and both_high and stability_checks
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("phase", kind="stable").reset_index(drop=True)


def build_daily_phase_report(
    phase_panel: pd.DataFrame,
    trades: pd.DataFrame,
    phase_metrics: pd.DataFrame,
    attribution_metrics: pd.DataFrame,
    candidate_evaluation: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a bounded report with complete individual phase trades."""

    _require_columns(phase_panel, ("event_id", "phase", "vt_symbol"), "phase panel")
    _require_columns(trades, ("event_id", "phase", "vt_symbol"), "phase trade")
    _require_columns(
        candidate_evaluation,
        ("phase", "stable_positive_candidate", "stable_high_win_candidate"),
        "phase candidate evaluation",
    )
    high_candidates = sorted(
        candidate_evaluation.loc[
            candidate_evaluation["stable_high_win_candidate"].astype(bool), "phase"
        ].astype(str)
    )
    positive_candidates = sorted(
        candidate_evaluation.loc[
            candidate_evaluation["stable_positive_candidate"].astype(bool), "phase"
        ].astype(str)
    )
    if high_candidates:
        conclusion = "stable_high_win_phase_candidate_found"
    elif positive_candidates:
        conclusion = "positive_phase_only"
    else:
        conclusion = "no_stable_daily_phase_edge"

    closed = trades.loc[
        trades.get("normal_status", pd.Series(index=trades.index, dtype=object)).eq("closed")
    ].copy()
    if "net_return_pct" in closed:
        closed["net_return_pct"] = pd.to_numeric(closed["net_return_pct"], errors="coerce")
        best = closed.sort_values(
            ["net_return_pct", "entry_date", "event_id"],
            ascending=[False, True, True],
            kind="stable",
        ).head(20)
        worst = closed.sort_values(
            ["net_return_pct", "entry_date", "event_id"],
            ascending=[True, True, True],
            kind="stable",
        ).head(20)
    else:
        best = closed.head(0)
        worst = closed.head(0)
    prevalence = phase_panel["phase"].value_counts(dropna=False).sort_index()
    coverage = dict(metadata.get("coverage", {}))
    coverage.setdefault("phase_observations", int(len(phase_panel)))
    coverage.setdefault("phase_trades", int(len(trades)))
    coverage.setdefault("unique_stocks", int(phase_panel["vt_symbol"].nunique()))
    coverage.setdefault(
        "phase_counts", {str(key): int(value) for key, value in prevalence.items()}
    )
    protocol = default_protocol()
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": conclusion,
        "formal_metrics": None,
        "cash_compounding": None,
        "formal_rule_selected": False,
        "strict_top3_claim": False,
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "minute_rows_read": 0,
        "old_low_suction_trade_rows_read": 0,
        "limit_up_strategy_rows_read": 0,
        "late_segment_is_unseen_validation": False,
        "minute_research_phase_candidates": high_candidates,
        "stable_positive_phase_candidates": positive_candidates,
        "frozen_contract": {
            "context_offsets": list(STUDY_OFFSETS),
            "feature_cutoff": "D-1 official close",
            "entry": "D official open with cash costs and tradability checks",
            "exit": "D+1 official close with T+1 and tradability checks",
            "strong_day_return_threshold_pct": 9.5,
            "phase_precedence": list(PHASE_PRECEDENCE),
            "early_segment_blocks": [1, 2, 3],
            "late_segment_blocks": [4, 5],
            "late_segment_reused": True,
            "strict_historical_top3": False,
        },
        "coverage": coverage,
        "input_fingerprints": dict(metadata.get("input_fingerprints", {})),
        "phase_metrics": _records(phase_metrics),
        "candidate_evaluation": _records(candidate_evaluation),
        "attribution_metrics": _records(attribution_metrics),
        "individual_phase_trades": _records(trades),
        "best_20_trades": _records(best),
        "worst_20_trades": _records(worst),
        "limitations": [
            "event-recognition ranks are not strict historical concept Top3 ranks",
            "historical point-in-time ST and delisting status remains unavailable",
            "all five diagnostic blocks were visible in earlier proxy studies",
            "volume, relative strength and gold/silver tables are attribution only",
            "no minute entry, portfolio compounding or production rule is selected",
        ],
    }


def load_daily_phase_study_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Load discovery inputs once and build the complete daily phase evidence."""

    from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
    from .event_neutral_days import build_event_neutral_comparison_days
    from .event_recognition_falsification import (
        load_event_falsification_inputs,
        load_timing_context,
    )

    event_inputs = load_event_falsification_inputs()
    cycle_inputs = load_cycle_research_inputs()
    if cycle_inputs.split.discovery_dates[-1] != event_inputs.discovery_end:
        raise ValueError("event and cycle discovery boundaries must match")
    cycle_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    timing = load_timing_context()
    timing = timing.loc[
        pd.to_datetime(timing["source_date"], errors="raise").dt.date
        <= event_inputs.discovery_end
    ].copy()
    comparison_days = build_event_neutral_comparison_days(
        event_inputs.candidates,
        event_inputs.stock_bars,
        cycle_states,
        timing,
        trading_dates=event_inputs.trading_dates,
        discovery_end=event_inputs.discovery_end,
    )
    panel = build_daily_phase_panel(
        comparison_days,
        event_inputs.stock_bars,
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
        trading_dates=event_inputs.trading_dates,
    )
    entry_dates = tuple(sorted(pd.to_datetime(panel["entry_date"]).dt.date.unique()))
    blocks = chronological_event_blocks(entry_dates, block_count=5).rename(
        columns={"source_date": "entry_date"}
    )
    blocks["entry_date"] = pd.to_datetime(blocks["entry_date"]).dt.normalize()
    panel = panel.merge(blocks, on="entry_date", how="left", validate="many_to_one")
    normal, stressed = execute_daily_phase_holds(
        panel,
        event_inputs.stock_bars,
        trading_dates=event_inputs.trading_dates,
    )
    trades = build_daily_phase_trade_ledger(panel, normal, stressed)
    metrics = build_daily_phase_metrics(trades)
    attribution = build_daily_phase_attribution_metrics(trades)
    evaluation = evaluate_daily_phase_candidates(metrics)

    normal_status = normal["status"].value_counts(dropna=False).sort_index()
    coverage = {
        **dict(event_inputs.coverage),
        "comparison_day_candidates": int(len(comparison_days)),
        "phase_observations": int(len(panel)),
        "phase_trades": int(len(trades)),
        "phase_dates": int(panel["entry_date"].nunique()),
        "phase_spells": int(panel["leader_spell_id"].nunique()),
        "unique_stocks": int(panel["vt_symbol"].nunique()),
        "unique_concepts": int(panel["sector_id"].nunique()),
        "offset_counts": {
            str(int(key)): int(value)
            for key, value in panel["spell_session_offset"].value_counts().sort_index().items()
        },
        "phase_counts": {
            str(key): int(value)
            for key, value in panel["phase"].value_counts().sort_index().items()
        },
        "normal_status_counts": {
            str(key): int(value) for key, value in normal_status.items()
        },
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "minute_rows_read": 0,
        "old_low_suction_trade_rows_read": 0,
        "limit_up_strategy_rows_read": 0,
    }
    cycle_fingerprints = {
        name: value.as_dict() for name, value in cycle_inputs.component_fingerprints
    }
    fingerprints = {
        **dict(event_inputs.input_fingerprints),
        **cycle_fingerprints,
        "daily_phase_comparison_days": fingerprint_frame(
            comparison_days,
            identity_columns=("entry_date", "vt_symbol"),
        ).as_dict(),
        "daily_phase_panel": fingerprint_frame(
            panel,
            identity_columns=("event_id",),
        ).as_dict(),
        "daily_phase_hold_normal": fingerprint_frame(
            normal,
            identity_columns=("event_id",),
        ).as_dict(),
        "daily_phase_hold_stressed": fingerprint_frame(
            stressed,
            identity_columns=("event_id",),
        ).as_dict(),
        "daily_phase_trade_ledger": fingerprint_frame(
            trades,
            identity_columns=("event_id",),
        ).as_dict(),
    }
    metadata = {
        "coverage": coverage,
        "input_fingerprints": fingerprints,
        "discovery_start": event_inputs.discovery_start,
        "discovery_end": event_inputs.discovery_end,
    }
    return panel, trades, metrics, attribution, evaluation, metadata


def run_daily_phase_study() -> dict[str, Any]:
    panel, trades, metrics, attribution, evaluation, metadata = (
        load_daily_phase_study_data()
    )
    return build_daily_phase_report(
        panel,
        trades,
        metrics,
        attribution,
        evaluation,
        metadata,
    )


def render_daily_phase_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_daily_phase_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# Low-suction Daily Leader Phase Hold Study",
        "",
        f"- Conclusion: `{report['overall_conclusion']}`",
        "- Evidence: event-recognition proxy, not strict historical Top3",
        "- Entry/exit: D open / D+1 official close",
        "- Late blocks are reused diagnostics, not untouched validation",
        f"- Observations/trades/stocks/concepts: `{coverage.get('phase_observations', 0)}/"
        f"{coverage.get('phase_trades', 0)}/{coverage.get('unique_stocks', 0)}/"
        f"{coverage.get('unique_concepts', 0)}`",
        "",
        "## Phase Baselines",
        "",
        "| Phase | Segment | Closed | Days | Win | Mean | PF | 2x mean | Label |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["phase_metrics"]:
        if row.get("segment") not in {"all", "early_1_3", "late_4_5"}:
            continue
        lines.append(
            f"| `{row.get('phase')}` | `{row.get('segment')}` | "
            f"{row.get('closed_trades')} | {row.get('source_days')} | "
            f"{_pct(row.get('win_rate_pct'))} | {_pct(row.get('mean_net_return_pct'))} | "
            f"{_number(row.get('profit_factor'))} | "
            f"{_pct(row.get('double_cost_mean_net_return_pct'))} | "
            f"`{row.get('baseline_label')}` |"
        )
    lines.extend(
        [
            "",
            "## Candidate Evaluation",
            "",
            "| Phase | Eligible | Early | Late | Positive blocks | Concentration | Stable high-win |",
            "| --- | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in report["candidate_evaluation"]:
        lines.append(
            f"| `{row.get('phase')}` | `{str(row.get('eligible_for_minute_research')).lower()}` | "
            f"`{row.get('early_label')}` | `{row.get('late_label')}` | "
            f"{row.get('positive_blocks')} | "
            f"`{str(row.get('profit_concentration_ok')).lower()}` | "
            f"`{str(row.get('stable_high_win_candidate')).lower()}` |"
        )
    lines.extend(
        [
            "",
            "## Attribution Diagnostics",
            "",
            "These rows are complete descriptive partitions, not selected entry filters.",
            "",
            "| Phase | Dimension | Cohort | Closed | Days | Win | Mean | PF | 2x mean | Label |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["attribution_metrics"]:
        if row.get("segment") != "all":
            continue
        lines.append(
            f"| `{row.get('phase')}` | `{row.get('dimension')}` | "
            f"`{row.get('cohort')}` | {row.get('closed_trades')} | "
            f"{row.get('source_days')} | {_pct(row.get('win_rate_pct'))} | "
            f"{_pct(row.get('mean_net_return_pct'))} | "
            f"{_number(row.get('profit_factor'))} | "
            f"{_pct(row.get('double_cost_mean_net_return_pct'))} | "
            f"`{row.get('baseline_label')}` |"
        )
    lines.extend(
        [
            "",
            "## Best Individual Trades",
            "",
            "| Context | Stock | Concept | Phase | Entry | Exit | Net | 2x net | Regime |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["best_20_trades"]:
        lines.append(_trade_markdown_row(row))
    lines.extend(
        [
            "",
            "## Worst Individual Trades",
            "",
            "| Context | Stock | Concept | Phase | Entry | Exit | Net | 2x net | Regime |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["worst_20_trades"]:
        lines.append(_trade_markdown_row(row))
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This report freezes daily lifecycle phases and a passive hold baseline only.",
            "Volume, relative strength and market regimes remain attribution fields. Strict",
            "historical Top3, minute entry, cash compounding, outer holdout and production",
            "selection remain closed.",
            "",
        ]
    )
    return "\n".join(lines)


def _prepare_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    frame = candidates.loc[:, list(CANDIDATE_COLUMNS)].copy()
    for column in (
        "recognition_source_date",
        "context_date",
        "entry_date",
        "planned_exit_date",
    ):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    frame["spell_session_offset"] = pd.to_numeric(
        frame["spell_session_offset"], errors="raise"
    ).astype(int)
    frame = frame.loc[
        frame["spell_session_offset"].isin(STUDY_OFFSETS)
        & frame["vt_symbol"].map(_is_main_board_symbol)
    ].copy()
    if frame.duplicated(["vt_symbol", "entry_date"]).any():
        raise ValueError("leader-spell days must be collision-free by stock/entry date")
    return frame.sort_values(
        ["entry_date", "sector_id", "recognition_rank", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def _is_main_board_symbol(vt_symbol: Any) -> bool:
    value = str(vt_symbol)
    if "." not in value:
        return False
    code, exchange = value.split(".", 1)
    if len(code) != 6 or not code.isdigit():
        return False
    if exchange == "SSE":
        return code.startswith(("600", "601", "603", "605"))
    if exchange == "SZSE":
        return code.startswith(("000", "001", "002", "003"))
    return False


def _prepare_calendar(trading_dates: Sequence[date]) -> pd.DatetimeIndex:
    calendar = pd.DatetimeIndex(
        pd.to_datetime(list(trading_dates), errors="raise")
    ).normalize()
    calendar = calendar.drop_duplicates().sort_values()
    if calendar.empty:
        raise ValueError("trading dates must not be empty")
    return calendar


def _build_stock_feature_panel(
    stock_bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    _require_columns(stock_bars, STOCK_BAR_COLUMNS, "stock daily bar")
    bars = stock_bars.loc[:, list(STOCK_BAR_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    rows = [
        _build_symbol_features(str(symbol), group, calendar)
        for symbol, group in bars.groupby("vt_symbol", sort=True)
    ]
    return pd.concat(rows, ignore_index=True) if rows else _empty_stock_features()


def _build_symbol_features(
    vt_symbol: str,
    group: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    frame = group.set_index("trade_date").reindex(calendar)
    frame.index.name = "trade_date"
    frame["vt_symbol"] = vt_symbol
    for column in ("open_price", "high_price", "low_price", "close_price", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    close = frame["close_price"]
    volume = frame["volume"]
    daily_return = close.pct_change(fill_method=None) * 100.0
    near_limit = daily_return.ge(9.5) & daily_return.notna()
    frame["stock_close"] = close
    frame["stock_daily_return_pct"] = daily_return
    for sessions in (5, 10, 20):
        frame[f"ma{sessions}"] = close.rolling(sessions, min_periods=sessions).mean()
    frame["stock_return_3d_pct"] = close.pct_change(3, fill_method=None) * 100.0
    frame["stock_return_3d_prior_pct"] = frame["stock_return_3d_pct"].shift(1)
    frame["stock_return_5d_pct"] = close.pct_change(5, fill_method=None) * 100.0
    prior_volume = volume.shift(1).rolling(5, min_periods=5).mean()
    frame["volume_to_prior_5d_ratio"] = volume / prior_volume.where(prior_volume.gt(0))
    frame["current_near_limit_up"] = near_limit.astype("boolean")
    frame["previous_near_limit_up"] = near_limit.shift(1).astype("boolean")
    frame["prior_near_limit_up_days_5d"] = (
        near_limit.shift(1).rolling(5, min_periods=5).sum()
    )
    frame["prior_near_limit_up_days_10d"] = (
        near_limit.shift(1).rolling(10, min_periods=10).sum()
    )
    frame["consecutive_near_limit_up_days"] = _consecutive_true_counts(near_limit)
    return frame.reset_index().loc[:, list(_empty_stock_features().columns)]


def _build_concept_feature_panel(
    concept_bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    _require_columns(concept_bars, CONCEPT_BAR_COLUMNS, "concept daily bar")
    bars = concept_bars.loc[:, list(CONCEPT_BAR_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    if bars.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept daily bar identities must be unique")
    rows = []
    for sector_id, group in bars.groupby("sector_id", sort=True):
        frame = group.set_index("trade_date").reindex(calendar)
        frame.index.name = "trade_date"
        close = pd.to_numeric(frame["close_price"], errors="coerce")
        return_3d = close.pct_change(3, fill_method=None) * 100.0
        frame["sector_id"] = str(sector_id)
        frame["concept_return_3d_pct"] = return_3d
        frame["concept_return_3d_prior_pct"] = return_3d.shift(1)
        frame["concept_return_5d_pct"] = close.pct_change(5, fill_method=None) * 100.0
        rows.append(
            frame.reset_index().loc[
                :,
                [
                    "sector_id",
                    "trade_date",
                    "concept_return_3d_pct",
                    "concept_return_3d_prior_pct",
                    "concept_return_5d_pct",
                ],
            ]
        )
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=[
            "sector_id",
            "trade_date",
            "concept_return_3d_pct",
            "concept_return_3d_prior_pct",
            "concept_return_5d_pct",
        ]
    )


def _build_market_feature_panel(
    market_returns: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    _require_columns(market_returns, MARKET_COLUMNS, "market return")
    frame = market_returns.loc[:, list(MARKET_COLUMNS)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    if frame["trade_date"].duplicated().any():
        raise ValueError("market return dates must be unique")
    frame = frame.set_index("trade_date").reindex(calendar)
    frame.index.name = "trade_date"
    daily = pd.to_numeric(frame["market_daily_return"], errors="coerce")
    level = (1.0 + daily).cumprod()
    frame["market_return_3d_pct"] = level.pct_change(3, fill_method=None) * 100.0
    frame["market_return_5d_pct"] = level.pct_change(5, fill_method=None) * 100.0
    return frame.reset_index().loc[
        :, ["trade_date", "market_return_3d_pct", "market_return_5d_pct"]
    ]


def _consecutive_true_counts(values: pd.Series) -> pd.Series:
    count = 0
    result = []
    for value in values.fillna(False).astype(bool):
        count = count + 1 if value else 0
        result.append(count)
    return pd.Series(result, index=values.index, dtype="int64")


def _metric_segments() -> tuple[tuple[str, tuple[int, ...]], ...]:
    return (
        ("all", (1, 2, 3, 4, 5)),
        ("early_1_3", (1, 2, 3)),
        ("late_4_5", (4, 5)),
        ("block_1", (1,)),
        ("block_2", (2,)),
        ("block_3", (3,)),
        ("block_4", (4,)),
        ("block_5", (5,)),
    )


def _summarize_trade_rows(frame: pd.DataFrame) -> dict[str, Any]:
    closed = frame.loc[
        frame["normal_status"].eq("closed")
        & frame["stressed_status"].eq("closed")
    ].copy()
    normal = pd.to_numeric(closed["net_return_pct"], errors="coerce")
    stressed = pd.to_numeric(closed["double_cost_net_return_pct"], errors="coerce")
    valid = normal.notna() & stressed.notna()
    closed = closed.loc[valid].copy()
    normal = normal.loc[valid]
    stressed = stressed.loc[valid]
    return {
        "observations": int(len(frame)),
        "closed_trades": int(len(normal)),
        "source_days": int(pd.to_datetime(closed["entry_date"]).dt.date.nunique()),
        "leader_spells": int(closed["leader_spell_id"].nunique()),
        "stocks": int(closed["vt_symbol"].nunique()),
        "concepts": int(closed["sector_id"].nunique()),
        "win_rate_pct": _win_rate(normal),
        "mean_net_return_pct": _mean(normal),
        "median_net_return_pct": _median(normal),
        "profit_factor": _profit_factor(normal),
        "tail_5pct": _quantile(normal, 0.05),
        "double_cost_win_rate_pct": _win_rate(stressed),
        "double_cost_mean_net_return_pct": _mean(stressed),
        "positive_profit_pct": float(normal.loc[normal.gt(0)].sum()),
        "maximum_stock_positive_profit_share_pct": _maximum_positive_profit_share(
            closed, normal, closed["vt_symbol"]
        ),
        "maximum_concept_positive_profit_share_pct": _maximum_positive_profit_share(
            closed, normal, closed["sector_id"]
        ),
        "maximum_month_positive_profit_share_pct": _maximum_positive_profit_share(
            closed,
            normal,
            pd.to_datetime(closed["entry_date"]).dt.to_period("M"),
        ),
    }


def _maximum_positive_profit_share(
    closed: pd.DataFrame,
    returns: pd.Series,
    groups: pd.Series,
) -> float | None:
    positive = returns.gt(0)
    total = float(returns.loc[positive].sum())
    if total <= 0:
        return None
    values = pd.DataFrame(
        {
            "group": groups.loc[positive].astype(str).to_numpy(),
            "return": returns.loc[positive].to_numpy(),
        },
        index=closed.index[positive],
    )
    return float(values.groupby("group", sort=False)["return"].sum().max() / total * 100.0)


def _segment_value(frame: pd.DataFrame, segment: str, column: str) -> Any:
    if segment not in frame.index:
        return None
    value = frame.loc[segment, column]
    if isinstance(value, pd.Series):
        raise ValueError("phase metric segments must be unique")
    return value


def _at_or_below(value: Any, threshold: float) -> bool:
    numeric = _finite_float(value)
    return numeric is not None and numeric <= threshold


def _require_metric_trade_columns(trades: pd.DataFrame) -> None:
    _require_columns(
        trades,
        (
            "event_id",
            "leader_spell_id",
            "phase",
            "entry_date",
            "vt_symbol",
            "sector_id",
            "block",
            "normal_status",
            "stressed_status",
            "net_return_pct",
            "double_cost_net_return_pct",
        ),
        "daily phase trade",
    )


def _empty_stock_features() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "vt_symbol",
            "trade_date",
            "stock_close",
            "stock_daily_return_pct",
            "ma5",
            "ma10",
            "ma20",
            "stock_return_3d_pct",
            "stock_return_3d_prior_pct",
            "stock_return_5d_pct",
            "volume_to_prior_5d_ratio",
            "current_near_limit_up",
            "previous_near_limit_up",
            "consecutive_near_limit_up_days",
            "prior_near_limit_up_days_5d",
            "prior_near_limit_up_days_10d",
        ]
    )


def _empty_phase_panel() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            *CANDIDATE_COLUMNS,
            *PHASE_FEATURE_COLUMNS,
            "phase_feature_complete",
            "phase",
            "phase_reason",
            "volume_class",
            "relative_strength_state",
            "market_regime",
            "feature_cutoff_date",
            "event_id",
            "evidence_level",
        ]
    )


def _reject_feature_leakage(*frames: pd.DataFrame) -> None:
    prohibited = set().union(
        *(PROHIBITED_FEATURE_COLUMNS & set(frame) for frame in frames)
    )
    prohibited.update(
        column
        for frame in frames
        for column in frame
        if str(column).startswith(("future_", "outcome_"))
    )
    if prohibited:
        raise ValueError(
            f"future or outcome columns are prohibited from daily phase features: {sorted(prohibited)}"
        )


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values.gt(0)].sum())
    losses = abs(float(values.loc[values.lt(0)].sum()))
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _win_rate(values: pd.Series) -> float | None:
    return float(values.gt(0).mean() * 100.0) if len(values) else None


def _mean(values: pd.Series) -> float | None:
    return float(values.mean()) if len(values) else None


def _median(values: pd.Series) -> float | None:
    return float(values.median()) if len(values) else None


def _quantile(values: pd.Series, quantile: float) -> float | None:
    return float(values.quantile(quantile)) if len(values) else None


def _finite_float(value: Any, *, allow_infinite: bool = False) -> float | None:
    if value is None or value is pd.NA:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or (math.isinf(result) and not allow_infinite):
        return None
    return result


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
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
        return pd.Timestamp(value).date().isoformat()
    return value


def _trade_markdown_row(row: Mapping[str, Any]) -> str:
    return (
        f"| {row.get('context_date')} | {row.get('stock_name')} "
        f"({row.get('vt_symbol')}) | {row.get('concept_name')} | "
        f"`{row.get('phase')}` | {_number(row.get('entry_price_raw'))} | "
        f"{_number(row.get('exit_price_raw'))} | {_pct(row.get('net_return_pct'))} | "
        f"{_pct(row.get('double_cost_net_return_pct'))} | "
        f"`{row.get('market_regime')}` |"
    )


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _number(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _require_columns(frame: pd.DataFrame, columns: Sequence[str], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
