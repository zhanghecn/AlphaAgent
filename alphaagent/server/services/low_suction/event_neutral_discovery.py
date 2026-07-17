"""Train-only response surfaces and bounded neutral-state rule discovery."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor

from .event_neutral_days import load_event_neutral_inputs
from .event_neutral_minutes import INTERVAL, load_event_neutral_5m_manifest
from .event_neutral_outcomes import label_event_neutral_outcomes
from .event_neutral_panel import NEUTRAL_STATE_FEATURES
from .event_neutral_panel import build_event_neutral_state_panel
from .event_recognition_falsification import chronological_event_blocks
from .research_protocol import default_protocol, fingerprint_frame, protocol_hash

BIN_LABELS = ("q00_q20", "q20_q40", "q40_q60", "q60_q80", "above_q80")
NEUTRAL_SURFACES = (
    ("drawdown_from_session_high_pct", "cycle_relative_percentile"),
    ("distance_to_vwap_pct", "volume_ratio_prior_3bars"),
    ("minutes_from_open", "distance_to_previous_close_pct"),
    ("return_3bar_pct", "drawdown_from_session_high_pct"),
)

TREE_MAX_DEPTH = 2
TREE_MIN_SAMPLES_LEAF = 100
TREE_RANDOM_STATE = 0
MIN_DEVELOPMENT_BLOCKS = 100
MAX_CANDIDATES = 5
STUDY_EVIDENCE_LEVEL = "event_recognition_neutral_state_falsification"


@dataclass(frozen=True)
class FittedResponseBins:
    edges: dict[str, tuple[float, ...]]


@dataclass(frozen=True)
class RuleCondition:
    feature: str
    operator: str
    threshold: float

    def __post_init__(self) -> None:
        if self.feature not in NEUTRAL_STATE_FEATURES:
            raise ValueError(f"unsupported neutral-state feature: {self.feature}")
        if self.operator not in {"<=", ">"}:
            raise ValueError(f"unsupported rule operator: {self.operator}")


@dataclass(frozen=True)
class CandidateRule:
    rule_id: str
    conditions: tuple[RuleCondition, ...]


@dataclass(frozen=True)
class LeafAttempt:
    rule_id: str
    leaf_node: int
    conditions: tuple[RuleCondition, ...]
    status: str
    reason: str | None
    tree_state_rows: int
    independent_blocks: int
    signals: int
    closed_trades: int
    win_rate_pct: float | None
    mean_net_return_pct: float | None
    profit_factor: float | None
    double_cost_mean_net_return_pct: float | None


@dataclass(frozen=True)
class DiscoveryResult:
    model: DecisionTreeRegressor
    candidates: tuple[CandidateRule, ...]
    attempts: tuple[LeafAttempt, ...]


def fit_response_bins(development: pd.DataFrame) -> FittedResponseBins:
    features = sorted({feature for surface in NEUTRAL_SURFACES for feature in surface})
    _require_columns(development, tuple(features), "development feature")
    if development.empty:
        raise ValueError("development rows are required to fit response bins")
    edges = {}
    for feature in features:
        values = pd.to_numeric(development[feature], errors="coerce").dropna()
        if values.empty:
            raise ValueError(f"development feature has no numeric values: {feature}")
        edges[feature] = tuple(
            float(value) for value in values.quantile([0.2, 0.4, 0.6, 0.8])
        )
    return FittedResponseBins(edges=edges)


def apply_response_bins(
    frame: pd.DataFrame,
    fitted: FittedResponseBins,
) -> pd.DataFrame:
    result = frame.copy()
    _require_columns(result, tuple(sorted(fitted.edges)), "response feature")
    for feature, edges in fitted.edges.items():
        values = pd.to_numeric(result[feature], errors="coerce").to_numpy(dtype=float)
        codes = np.full(len(values), -1, dtype=np.int64)
        valid = np.isfinite(values)
        codes[valid] = np.searchsorted(
            np.asarray(edges, dtype=float),
            values[valid],
            side="right",
        ).clip(0, len(BIN_LABELS) - 1)
        result[f"{feature}_bin"] = pd.Categorical.from_codes(
            codes,
            categories=BIN_LABELS,
            ordered=True,
        )
    return result


def build_response_surfaces(
    frame: pd.DataFrame,
    fitted: FittedResponseBins,
    *,
    segment: str,
) -> pd.DataFrame:
    required = (
        "observation_id",
        "event_id",
        "independence_block_id",
        "net_return_pct",
        "double_cost_net_return_pct",
    )
    _require_columns(frame, required, "response row")
    binned = apply_response_bins(frame, fitted)
    records = []
    for x_feature, y_feature in NEUTRAL_SURFACES:
        x_bin = f"{x_feature}_bin"
        y_bin = f"{y_feature}_bin"
        surface_id = f"{x_feature}__{y_feature}"
        for (x_label, y_label), states in binned.groupby(
            [x_bin, y_bin],
            observed=True,
            sort=True,
        ):
            candidate_episodes = (
                states.sort_values(["event_id", "observation_id"], kind="stable")
                .drop_duplicates(["event_id", x_bin, y_bin], keep="first")
            )
            normal_values = pd.to_numeric(
                candidate_episodes["net_return_pct"], errors="coerce"
            )
            stressed_values = pd.to_numeric(
                candidate_episodes["double_cost_net_return_pct"], errors="coerce"
            )
            closed_mask = normal_values.notna() & stressed_values.notna()
            episodes = candidate_episodes.loc[closed_mask]
            normal = normal_values.loc[closed_mask]
            stressed = stressed_values.loc[closed_mask]
            records.append(
                {
                    "segment": str(segment),
                    "surface_id": surface_id,
                    "x_feature": x_feature,
                    "y_feature": y_feature,
                    "x_bin": str(x_label),
                    "y_bin": str(y_label),
                    "raw_states": int(len(states)),
                    "candidate_episodes": int(len(candidate_episodes)),
                    "episodes": int(len(episodes)),
                    "independent_blocks": int(
                        episodes["independence_block_id"].nunique()
                    ),
                    "win_rate_pct": _win_rate(normal),
                    "mean_net_return_pct": _mean(normal),
                    "median_net_return_pct": _median(normal),
                    "profit_factor": _profit_factor(normal),
                    "tail_5pct": _quantile(normal, 0.05),
                    "double_cost_win_rate_pct": _win_rate(stressed),
                    "double_cost_mean_net_return_pct": _mean(stressed),
                    "minimum_block_coverage_met": bool(
                        episodes["independence_block_id"].nunique() >= 30
                    ),
                }
            )
    return pd.DataFrame(records).sort_values(
        ["segment", "surface_id", "x_bin", "y_bin"],
        kind="stable",
    ).reset_index(drop=True)


def materialize_rule_transitions(
    panel: pd.DataFrame,
    rule: CandidateRule,
) -> pd.DataFrame:
    _require_columns(
        panel,
        ("event_id", "bar_time", "observation_id", *NEUTRAL_STATE_FEATURES),
        "state panel",
    )
    frame = panel.sort_values(["event_id", "bar_time"], kind="stable").copy()
    predicate = pd.Series(True, index=frame.index, dtype=bool)
    for condition in rule.conditions:
        values = pd.to_numeric(frame[condition.feature], errors="coerce")
        if condition.operator == "<=":
            predicate &= values.le(condition.threshold)
        else:
            predicate &= values.gt(condition.threshold)
    prior = predicate.groupby(frame["event_id"], sort=False).shift(1)
    signals = frame.loc[predicate & prior.eq(False)].copy()
    signals["rule_id"] = rule.rule_id
    return (
        signals.sort_values(["event_id", "bar_time"], kind="stable")
        .drop_duplicates(["event_id"], keep="first")
        .reset_index(drop=True)
    )


def discover_candidate_rules(
    development_panel: pd.DataFrame,
    normal_outcomes: pd.DataFrame,
    stressed_outcomes: pd.DataFrame,
) -> DiscoveryResult:
    _require_columns(
        development_panel,
        (
            "observation_id",
            "event_id",
            "bar_time",
            "independence_block_id",
            "sample_weight",
            *NEUTRAL_STATE_FEATURES,
        ),
        "development panel",
    )
    joined = _join_outcomes(
        development_panel,
        normal_outcomes,
        stressed_outcomes,
    )
    training = joined.loc[
        joined["normal_status"].eq("closed")
        & pd.to_numeric(joined["net_return_pct"], errors="coerce").notna()
    ].copy()
    if len(training) < TREE_MIN_SAMPLES_LEAF * 2:
        raise ValueError("insufficient closed states for the frozen discovery tree")
    features = list(NEUTRAL_STATE_FEATURES)
    feature_values = training.loc[:, features].apply(pd.to_numeric, errors="coerce")
    if feature_values.isna().any().any():
        raise ValueError("discovery tree features must be numeric and complete")
    target = np.log1p(
        pd.to_numeric(training["net_return_pct"], errors="raise").to_numpy()
        / 100.0
    )
    model = DecisionTreeRegressor(
        max_depth=TREE_MAX_DEPTH,
        min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
        random_state=TREE_RANDOM_STATE,
    )
    model.fit(
        feature_values,
        target,
        sample_weight=pd.to_numeric(training["sample_weight"], errors="raise"),
    )

    leaf_nodes = model.apply(feature_values)
    attempts = []
    for leaf_node, conditions in _leaf_paths(model, features):
        rule = CandidateRule(
            rule_id=f"neutral_leaf_{leaf_node}",
            conditions=conditions,
        )
        signals = materialize_rule_transitions(development_panel, rule)
        metrics = _summarize_signals(signals, joined)
        reasons = _development_rejection_reasons(metrics)
        attempts.append(
            LeafAttempt(
                rule_id=rule.rule_id,
                leaf_node=leaf_node,
                conditions=conditions,
                status="rejected" if reasons else "accepted",
                reason=",".join(reasons) if reasons else None,
                tree_state_rows=int((leaf_nodes == leaf_node).sum()),
                independent_blocks=int(metrics["independent_blocks"]),
                signals=int(metrics["signals"]),
                closed_trades=int(metrics["closed_trades"]),
                win_rate_pct=metrics["win_rate_pct"],
                mean_net_return_pct=metrics["mean_net_return_pct"],
                profit_factor=metrics["profit_factor"],
                double_cost_mean_net_return_pct=metrics[
                    "double_cost_mean_net_return_pct"
                ],
            )
        )
    accepted = sorted(
        (attempt for attempt in attempts if attempt.status == "accepted"),
        key=lambda attempt: (
            -(attempt.mean_net_return_pct or -math.inf),
            attempt.rule_id,
        ),
    )[:MAX_CANDIDATES]
    candidates = tuple(
        CandidateRule(attempt.rule_id, attempt.conditions) for attempt in accepted
    )
    return DiscoveryResult(
        model=model,
        candidates=candidates,
        attempts=tuple(sorted(attempts, key=lambda attempt: attempt.leaf_node)),
    )


def candidate_rule_payload(rule: CandidateRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "conditions": [asdict(condition) for condition in rule.conditions],
    }


def leaf_attempt_payload(attempt: LeafAttempt) -> dict[str, Any]:
    payload = {
        key: _json_value(value) for key, value in asdict(attempt).items()
    }
    payload["conditions"] = [asdict(condition) for condition in attempt.conditions]
    return payload


def _join_outcomes(
    panel: pd.DataFrame,
    normal: pd.DataFrame,
    stressed: pd.DataFrame,
) -> pd.DataFrame:
    required = ("observation_id", "status", "net_return_pct")
    _require_columns(normal, required, "normal outcome")
    _require_columns(stressed, required, "stressed outcome")
    if normal.duplicated(["observation_id"]).any() or stressed.duplicated(
        ["observation_id"]
    ).any():
        raise ValueError("outcome observation IDs must be unique")
    normal_values = normal.loc[:, list(required)].rename(
        columns={"status": "normal_status"}
    )
    stressed_values = stressed.loc[:, list(required)].rename(
        columns={
            "status": "stressed_status",
            "net_return_pct": "double_cost_net_return_pct",
        }
    )
    return panel.merge(
        normal_values,
        on="observation_id",
        how="left",
        validate="one_to_one",
    ).merge(
        stressed_values,
        on="observation_id",
        how="left",
        validate="one_to_one",
    )


def _leaf_paths(
    model: DecisionTreeRegressor,
    features: list[str],
) -> list[tuple[int, tuple[RuleCondition, ...]]]:
    tree = model.tree_
    paths: list[tuple[int, tuple[RuleCondition, ...]]] = []

    def visit(node: int, conditions: tuple[RuleCondition, ...]) -> None:
        left = int(tree.children_left[node])
        right = int(tree.children_right[node])
        if left == right:
            paths.append((node, conditions))
            return
        feature = features[int(tree.feature[node])]
        threshold = float(tree.threshold[node])
        visit(left, (*conditions, RuleCondition(feature, "<=", threshold)))
        visit(right, (*conditions, RuleCondition(feature, ">", threshold)))

    visit(0, ())
    return sorted(paths, key=lambda item: item[0])


def _summarize_signals(
    signals: pd.DataFrame,
    joined: pd.DataFrame,
) -> dict[str, Any]:
    if signals.empty:
        return {
            "signals": 0,
            "independent_blocks": 0,
            "closed_trades": 0,
            "win_rate_pct": None,
            "mean_net_return_pct": None,
            "profit_factor": None,
            "double_cost_mean_net_return_pct": None,
        }
    values = signals.loc[
        :,
        ["observation_id", "independence_block_id"],
    ].merge(
        joined.loc[
            :,
            [
                "observation_id",
                "normal_status",
                "stressed_status",
                "net_return_pct",
                "double_cost_net_return_pct",
            ],
        ],
        on="observation_id",
        how="left",
        validate="one_to_one",
    )
    closed = values.loc[
        values["normal_status"].eq("closed")
        & values["stressed_status"].eq("closed")
    ]
    normal = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
    stressed = pd.to_numeric(
        closed["double_cost_net_return_pct"], errors="coerce"
    ).dropna()
    return {
        "signals": int(len(signals)),
        "independent_blocks": int(signals["independence_block_id"].nunique()),
        "closed_trades": int(len(normal)),
        "win_rate_pct": _win_rate(normal),
        "mean_net_return_pct": _mean(normal),
        "profit_factor": _profit_factor(normal),
        "double_cost_mean_net_return_pct": _mean(stressed),
    }


def _development_rejection_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons = []
    if int(metrics["independent_blocks"]) < MIN_DEVELOPMENT_BLOCKS:
        reasons.append("fewer_than_100_independent_blocks")
    if (metrics["mean_net_return_pct"] or -math.inf) <= 0:
        reasons.append("non_positive_mean")
    if (metrics["profit_factor"] or -math.inf) <= 1:
        reasons.append("profit_factor_not_above_one")
    if (metrics["double_cost_mean_net_return_pct"] or -math.inf) <= 0:
        reasons.append("non_positive_double_cost_mean")
    return reasons


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values > 0].sum())
    losses = abs(float(values.loc[values < 0].sum()))
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


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def load_event_neutral_state_study_data(
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load exact candidate states and the single frozen D+1 label."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    inputs = load_event_neutral_inputs()
    candidates = inputs.candidates
    manifest = load_event_neutral_5m_manifest(candidates)
    incomplete = manifest.loc[manifest["status"].ne("complete")]
    if not incomplete.empty:
        raise ValueError("event-neutral 5m manifest must be complete before discovery")
    if candidates.empty:
        raise ValueError("event-neutral candidates are required for state discovery")

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
    loaded_bars = pd.read_sql(statement, get_engine(), parse_dates=["bar_time"])
    minute_bars = _filter_candidate_pairs(candidates, loaded_bars)
    panel = build_event_neutral_state_panel(candidates, minute_bars)
    panel = _assign_chronological_blocks(panel)
    normal = label_event_neutral_outcomes(
        panel,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    stressed = label_event_neutral_outcomes(
        panel,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
        cost_multiplier=2.0,
    )
    expected_minutes = len(candidates) * 48
    if len(minute_bars) != expected_minutes:
        raise ValueError("candidate minute rows must equal candidate days times 48")
    expected_states = len(candidates) * 44
    if len(panel) != expected_states:
        raise ValueError("candidate state rows must equal candidate days times 44")

    fingerprints = {
        **inputs.input_fingerprints,
        "event_neutral_minutes": fingerprint_frame(
            minute_bars,
            identity_columns=("vt_symbol", "bar_time", "interval"),
        ).as_dict(),
        "event_neutral_states": fingerprint_frame(
            panel.loc[
                :,
                [
                    "observation_id",
                    "event_id",
                    "entry_date",
                    "bar_time",
                    "independence_block_id",
                    "block",
                    *NEUTRAL_STATE_FEATURES,
                ],
            ],
            identity_columns=("observation_id",),
        ).as_dict(),
        "event_neutral_normal_outcomes": fingerprint_frame(
            normal.loc[
                :,
                ["observation_id", "status", "reason", "net_return_pct"],
            ],
            identity_columns=("observation_id",),
        ).as_dict(),
        "event_neutral_stressed_outcomes": fingerprint_frame(
            stressed.loc[
                :,
                ["observation_id", "status", "reason", "net_return_pct"],
            ],
            identity_columns=("observation_id",),
        ).as_dict(),
    }
    coverage = {
        **inputs.coverage,
        "manifest_pairs": int(len(manifest)),
        "complete_pairs": int(manifest["status"].eq("complete").sum()),
        "minute_rows": int(len(minute_bars)),
        "raw_states": int(len(minute_bars)),
        "executable_state_rows": int(len(panel)),
        "excluded_initial_history_rows": int(len(candidates) * 3),
        "excluded_no_next_bar_rows": int(len(candidates)),
        "normal_outcome_status_counts": _value_counts(normal["status"]),
        "normal_outcome_reason_counts": _value_counts(
            normal["reason"].fillna("none")
        ),
        "stressed_outcome_status_counts": _value_counts(stressed["status"]),
        "stressed_outcome_reason_counts": _value_counts(
            stressed["reason"].fillna("none")
        ),
        "block_candidate_days": {
            str(int(block)): int(count)
            for block, count in panel.groupby("block", sort=True)["event_id"]
            .nunique()
            .items()
        },
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
    }
    return panel, normal, stressed, {
        "coverage": coverage,
        "fingerprints": fingerprints,
        "discovery_start": inputs.discovery_start,
        "discovery_end": inputs.discovery_end,
    }


def run_event_neutral_state_study() -> dict[str, Any]:
    panel, normal, stressed, metadata = load_event_neutral_state_study_data()
    development_panel = panel.loc[panel["block"].le(3)].copy()
    validation_panel = panel.loc[panel["block"].ge(4)].copy()
    joined = _join_outcomes(panel, normal, stressed)
    development_joined = joined.loc[joined["block"].le(3)].copy()
    validation_joined = joined.loc[joined["block"].ge(4)].copy()
    fitted = fit_response_bins(development_joined)
    surfaces = pd.concat(
        [
            build_response_surfaces(
                development_joined,
                fitted,
                segment="development_blocks_1_3",
            ),
            build_response_surfaces(
                validation_joined,
                fitted,
                segment="validation_blocks_4_5",
            ),
        ],
        ignore_index=True,
    )
    discovery = discover_candidate_rules(
        development_panel,
        normal,
        stressed,
    )
    rule_metrics, block_metrics, regime_metrics = _evaluate_validation_candidates(
        validation_panel,
        normal,
        stressed,
        discovery.candidates,
    )
    return build_event_neutral_state_report(
        coverage=metadata["coverage"],
        fingerprints=metadata["fingerprints"],
        discovery_start=metadata["discovery_start"],
        discovery_end=metadata["discovery_end"],
        fitted=fitted,
        discovery=discovery,
        surfaces=surfaces,
        rule_metrics=rule_metrics,
        block_metrics=block_metrics,
        regime_metrics=regime_metrics,
    )


def build_event_neutral_state_report(
    *,
    coverage: dict[str, Any],
    fingerprints: dict[str, Any],
    discovery_start: date,
    discovery_end: date,
    fitted: FittedResponseBins,
    discovery: DiscoveryResult,
    surfaces: pd.DataFrame,
    rule_metrics: pd.DataFrame,
    block_metrics: pd.DataFrame,
    regime_metrics: pd.DataFrame,
) -> dict[str, Any]:
    qualified = (
        rule_metrics.loc[rule_metrics["qualified_for_strict_retest"]]
        if not rule_metrics.empty
        else pd.DataFrame()
    )
    direction = (
        rule_metrics.loc[rule_metrics["validation_base_gate"]]
        if not rule_metrics.empty
        else pd.DataFrame()
    )
    if not qualified.empty:
        conclusion = "worth_strict_top3_retest"
    elif not direction.empty:
        conclusion = "event_neutral_direction_only"
    else:
        conclusion = "no_event_neutral_state_edge"
    protocol = default_protocol()
    high_win_cells = surfaces.loc[
        surfaces["segment"].eq("validation_blocks_4_5")
        & surfaces["minimum_block_coverage_met"]
        & pd.to_numeric(surfaces["win_rate_pct"], errors="coerce").gt(60)
        & pd.to_numeric(surfaces["mean_net_return_pct"], errors="coerce").gt(0)
        & pd.to_numeric(
            surfaces["double_cost_mean_net_return_pct"], errors="coerce"
        ).gt(0)
    ].copy()
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": conclusion,
        "formal_metrics": None,
        "formal_rule_selected": False,
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "strict_top3_identity_used": False,
        "date_split": {
            "discovery_start": discovery_start.isoformat(),
            "discovery_end": discovery_end.isoformat(),
            "development_blocks": [1, 2, 3],
            "validation_blocks": [4, 5],
            "outer_holdout": "locked",
        },
        "frozen_contract": {
            "observation_offsets": [1, 2, 3, 4, 5],
            "eligibility": "previous-day exact breakout cycle",
            "state_features": list(NEUTRAL_STATE_FEATURES),
            "response_surfaces": [list(surface) for surface in NEUTRAL_SURFACES],
            "response_quantiles": [0.2, 0.4, 0.6, 0.8],
            "tree_max_depth": TREE_MAX_DEPTH,
            "tree_min_samples_leaf": TREE_MIN_SAMPLES_LEAF,
            "tree_random_state": TREE_RANDOM_STATE,
            "entry": "first false-to-true close, next 5m open",
            "discovery_exit": "D+1 first sellable close",
            "cost_multipliers": [1.0, 2.0],
        },
        "coverage": coverage,
        "fitted_response_edges": {
            feature: list(edges) for feature, edges in sorted(fitted.edges.items())
        },
        "tree": {
            "depth": int(discovery.model.get_depth()),
            "leaves": int(discovery.model.get_n_leaves()),
            "accepted_candidates": len(discovery.candidates),
            "attempts": [leaf_attempt_payload(item) for item in discovery.attempts],
        },
        "candidate_rules": [
            candidate_rule_payload(rule) for rule in discovery.candidates
        ],
        "response_cells": _records(surfaces),
        "non_qualifying_high_win_cell_count": int(len(high_win_cells)),
        "non_qualifying_high_win_cells": _records(high_win_cells),
        "validation_rule_metrics": _records(rule_metrics),
        "validation_block_metrics": _records(block_metrics),
        "validation_regime_metrics": _records(regime_metrics),
        "qualifying_rules": (
            sorted(qualified["rule_id"].astype(str).tolist())
            if not qualified.empty
            else []
        ),
        "input_fingerprints": fingerprints,
        "limitations": [
            "event reasons are an incomplete proxy rather than historical membership Top3",
            "TDX 5m bars cannot reproduce one-minute or tick queue behavior",
            "historical security status remains reconstructed",
            "concept intraday relative-strength features are unavailable in this proxy",
            "formal exits, cash portfolio, drawdown and outer holdout remain locked",
        ],
    }


def render_event_neutral_state_json(report: dict[str, Any]) -> str:
    return json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_event_neutral_state_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# Low-suction Event-neutral State Discovery",
        "",
        f"- Conclusion: `{report['overall_conclusion']}`",
        "- Formal metrics: `null`",
        "- Holdout values read: `false`",
        f"- Candidate/complete days: `{coverage.get('candidate_count', 0)}/"
        f"{coverage.get('complete_pairs', 0)}`",
        f"- Minute/executable states: `{coverage.get('minute_rows', 0)}/"
        f"{coverage.get('executable_state_rows', 0)}`",
        f"- Tree depth/leaves/accepted: `{report['tree']['depth']}/"
        f"{report['tree']['leaves']}/{report['tree']['accepted_candidates']}`",
        "",
        "## Development Leaves",
        "",
        "| Rule | Conditions | Blocks | Signals | Closed | Win | Mean | PF | Double mean | Status | Reason |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for attempt in report["tree"]["attempts"]:
        lines.append(
            f"| `{attempt['rule_id']}` | {_conditions(attempt['conditions'])} | "
            f"{attempt['independent_blocks']} | {attempt['signals']} | "
            f"{attempt['closed_trades']} | {_pct(attempt['win_rate_pct'])} | "
            f"{_pct(attempt['mean_net_return_pct'])} | "
            f"{_number(attempt['profit_factor'])} | "
            f"{_pct(attempt['double_cost_mean_net_return_pct'])} | "
            f"{attempt['status']} | {attempt['reason'] or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Validation Rules",
            "",
            "| Rule | Signals | Closed | Win | Mean | PF | Double mean | Positive blocks | Retest |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["validation_rule_metrics"]:
        lines.append(
            f"| `{row['rule_id']}` | {row['signals']} | {row['closed_trades']} | "
            f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
            f"{_number(row['profit_factor'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} | "
            f"{row['positive_validation_blocks']}/2 | "
            f"{'yes' if row['qualified_for_strict_retest'] else 'no'} |"
        )
    top_cells = sorted(
        (
            cell
            for cell in report["response_cells"]
            if cell["segment"] == "validation_blocks_4_5"
            and cell["minimum_block_coverage_met"]
        ),
        key=lambda cell: (-(cell["mean_net_return_pct"] or -math.inf), cell["surface_id"]),
    )[:12]
    lines.extend(
        [
            "",
            "## Top Validation Response Cells",
            "",
            "| Surface | X bin | Y bin | Episodes | Blocks | Win | Mean | PF | Double mean |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for cell in top_cells:
        lines.append(
            f"| `{cell['surface_id']}` | `{cell['x_bin']}` | `{cell['y_bin']}` | "
            f"{cell['episodes']} | {cell['independent_blocks']} | "
            f"{_pct(cell['win_rate_pct'])} | {_pct(cell['mean_net_return_pct'])} | "
            f"{_number(cell['profit_factor'])} | "
            f"{_pct(cell['double_cost_mean_net_return_pct'])} |"
        )
    lines.extend(
        [
            "",
            "该结果只用于淘汰或提名严格历史 Top3 复测方向，不是正式策略绩效。",
            "",
        ]
    )
    return "\n".join(lines)


def _filter_candidate_pairs(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    pairs = candidates.loc[:, ["vt_symbol", "entry_date"]].copy()
    pairs["trade_date"] = pd.to_datetime(pairs.pop("entry_date")).dt.date
    pairs = pairs.drop_duplicates(["vt_symbol", "trade_date"])
    bars = minute_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    return bars.merge(
        pairs,
        on=["vt_symbol", "trade_date"],
        how="inner",
        validate="many_to_one",
    ).sort_values(["vt_symbol", "bar_time"], kind="stable")


def _assign_chronological_blocks(panel: pd.DataFrame) -> pd.DataFrame:
    dates = tuple(sorted(pd.to_datetime(panel["entry_date"]).dt.date.unique()))
    blocks = chronological_event_blocks(dates, block_count=5).rename(
        columns={"source_date": "entry_date"}
    )
    frame = panel.copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"]).dt.date
    return frame.merge(
        blocks,
        on="entry_date",
        how="left",
        validate="many_to_one",
    )


def _evaluate_validation_candidates(
    panel: pd.DataFrame,
    normal: pd.DataFrame,
    stressed: pd.DataFrame,
    candidates: tuple[CandidateRule, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not candidates:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    joined = _join_outcomes(panel, normal, stressed)
    rule_rows = []
    block_rows = []
    regime_rows = []
    for rule in candidates:
        signals = materialize_rule_transitions(panel, rule)
        rows = signals.loc[:, ["observation_id"]].merge(
            joined,
            on="observation_id",
            how="left",
            validate="one_to_one",
        )
        closed = rows.loc[
            rows["normal_status"].eq("closed")
            & rows["stressed_status"].eq("closed")
        ].copy()
        normal_returns = pd.to_numeric(
            closed["net_return_pct"], errors="coerce"
        ).dropna()
        stressed_returns = pd.to_numeric(
            closed["double_cost_net_return_pct"], errors="coerce"
        ).dropna()
        rule_block_rows = []
        for block in (4, 5):
            block_frame = closed.loc[closed["block"].eq(block)]
            returns = pd.to_numeric(
                block_frame["net_return_pct"], errors="coerce"
            ).dropna()
            profit_factor = _profit_factor(returns)
            positive = bool(
                len(returns)
                and float(returns.mean()) > 0
                and profit_factor is not None
                and profit_factor > 1
            )
            item = {
                "rule_id": rule.rule_id,
                "block": block,
                "closed_trades": int(len(returns)),
                "win_rate_pct": _win_rate(returns),
                "mean_net_return_pct": _mean(returns),
                "profit_factor": profit_factor,
                "positive_block": positive,
            }
            block_rows.append(item)
            rule_block_rows.append(item)
        positive_blocks = sum(item["positive_block"] for item in rule_block_rows)
        mean_return = _mean(normal_returns)
        profit_factor = _profit_factor(normal_returns)
        double_mean = _mean(stressed_returns)
        base_gate = bool(
            len(normal_returns) >= 100
            and mean_return is not None
            and mean_return > 0
            and profit_factor is not None
            and profit_factor > 1
            and double_mean is not None
            and double_mean > 0
            and positive_blocks == 2
        )
        win_rate = _win_rate(normal_returns)
        qualified = bool(base_gate and win_rate is not None and win_rate > 60)
        rule_rows.append(
            {
                "rule_id": rule.rule_id,
                "signals": int(len(signals)),
                "independent_blocks": int(
                    signals["independence_block_id"].nunique()
                ),
                "closed_trades": int(len(normal_returns)),
                "win_rate_pct": win_rate,
                "mean_net_return_pct": mean_return,
                "median_net_return_pct": _median(normal_returns),
                "profit_factor": profit_factor,
                "tail_5pct": _quantile(normal_returns, 0.05),
                "double_cost_mean_net_return_pct": double_mean,
                "positive_validation_blocks": int(positive_blocks),
                "maximum_symbol_trade_share": _maximum_share(
                    closed["vt_symbol"]
                ),
                "maximum_cycle_trade_share": _maximum_share(closed["cycle_id"]),
                "validation_base_gate": base_gate,
                "qualified_for_strict_retest": qualified,
            }
        )
        rows["regime_key"] = (
            rows["active_direction"].astype(str)
            + "/"
            + rows["danger_state"].astype(str)
        )
        for regime, regime_frame in rows.groupby("regime_key", sort=True):
            regime_closed = regime_frame.loc[
                regime_frame["normal_status"].eq("closed")
                & regime_frame["stressed_status"].eq("closed")
            ]
            returns = pd.to_numeric(
                regime_closed["net_return_pct"], errors="coerce"
            ).dropna()
            double_returns = pd.to_numeric(
                regime_closed["double_cost_net_return_pct"], errors="coerce"
            ).dropna()
            regime_rows.append(
                {
                    "rule_id": rule.rule_id,
                    "regime_key": str(regime),
                    "source_days": int(regime_frame["entry_date"].nunique()),
                    "closed_trades": int(len(returns)),
                    "win_rate_pct": _win_rate(returns),
                    "mean_net_return_pct": _mean(returns),
                    "profit_factor": _profit_factor(returns),
                    "double_cost_mean_net_return_pct": _mean(double_returns),
                }
            )
    return pd.DataFrame(rule_rows), pd.DataFrame(block_rows), pd.DataFrame(regime_rows)


def _maximum_share(values: pd.Series) -> float | None:
    if values.empty:
        return None
    return float(values.value_counts(dropna=False).max() / len(values))


def _value_counts(values: pd.Series) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in values.value_counts(dropna=False).sort_index().items()
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {key: _json_value(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (date, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    return value


def _conditions(conditions: list[dict[str, Any]]) -> str:
    if not conditions:
        return "all"
    return " and ".join(
        f"{item['feature']} {item['operator']} {float(item['threshold']):.6f}"
        for item in conditions
    )


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _number(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"
