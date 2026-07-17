"""Full-universe D-1 study for verified first strong explosions."""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from .event_recognition_falsification import chronological_event_blocks
from .prelaunch_universe import PRELAUNCH_FEATURES, build_prelaunch_feature_panel


FIRST_EXPLOSION_RETURN_PCT = 5.0
POSITIVE_LABEL_STATUS = "verified_active_main_rise_first_explosion"
NEGATIVE_LABEL_STATUS = "not_verified_by_available_event_evidence"
TREE_MAX_DEPTH = 2
TREE_MIN_SAMPLES_LEAF = 1_000
TREE_RANDOM_STATE = 0
MAX_RULE_COVERAGE = 0.10
MIN_DEVELOPMENT_ROWS = 1_000
MIN_DEVELOPMENT_POSITIVES = 30
MIN_DEVELOPMENT_DAYS = 30
MIN_DEVELOPMENT_RECALL = 0.05
MIN_DEVELOPMENT_PRECISION_LIFT = 2.0
MIN_VALIDATION_ROWS = 500
MIN_VALIDATION_POSITIVES = 15
MIN_VALIDATION_DAYS = 20
MIN_VALIDATION_RECALL = 0.025
MIN_VALIDATION_PRECISION_LIFT = 1.5
STUDY_EVIDENCE_LEVEL = "full_main_board_prelaunch_first_explosion_proxy"

FEATURE_IDENTITY_COLUMNS = (
    "event_id",
    "context_date",
    "entry_date",
    "feature_cutoff_date",
    "vt_symbol",
)
PROHIBITED_FEATURE_LABEL_COLUMNS = frozenset(
    {
        "verified_first_explosion",
        "verified_concept_count",
        "verified_concept_names",
        "d_return_pct",
        "label_status",
        "net_return_pct",
        "gross_return_pct",
        "double_cost_net_return_pct",
        "entry_price",
        "exit_price",
    }
)


@dataclass(frozen=True)
class PrelaunchCondition:
    feature: str
    operator: str
    threshold: float

    def __post_init__(self) -> None:
        if self.feature not in PRELAUNCH_FEATURES:
            raise ValueError(f"unsupported prelaunch feature: {self.feature}")
        if self.operator not in {"<=", ">"}:
            raise ValueError(f"unsupported prelaunch operator: {self.operator}")


@dataclass(frozen=True)
class PrelaunchRule:
    rule_id: str
    conditions: tuple[PrelaunchCondition, ...]


@dataclass(frozen=True)
class PrelaunchLeafAttempt:
    leaf_node: int
    rule: PrelaunchRule
    status: str
    rejection_reasons: tuple[str, ...]
    rows: int
    verified_positives: int
    source_days: int
    precision: float | None
    positive_recall: float | None
    precision_lift: float | None
    universe_coverage: float | None


@dataclass(frozen=True)
class PrelaunchDiscoveryResult:
    model: DecisionTreeClassifier
    selected_rule: PrelaunchRule | None
    attempts: tuple[PrelaunchLeafAttempt, ...]
    development_base_rate: float


def attach_verified_first_explosion_labels(
    features: pd.DataFrame,
    exact_relations: pd.DataFrame,
    cycle_states: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Attach post-D verified event labels after causal features are frozen."""

    _reject_feature_labels(features)
    _require_columns(
        features,
        (*FEATURE_IDENTITY_COLUMNS, *PRELAUNCH_FEATURES),
        "prelaunch feature input",
    )
    _require_columns(
        exact_relations,
        ("event_id", "source_date", "sector_id", "concept_name", "vt_symbol"),
        "exact event relation",
    )
    _require_columns(
        cycle_states,
        ("definition", "trade_date", "sector_id", "in_cycle", "cycle_id"),
        "cycle state",
    )
    _require_columns(stock_bars, ("vt_symbol", "trade_date", "close_price"), "stock bar")

    result = features.copy()
    for column in ("context_date", "entry_date", "feature_cutoff_date"):
        result[column] = pd.to_datetime(result[column], errors="raise").dt.date
    if result["event_id"].duplicated().any():
        raise ValueError("prelaunch feature event IDs must be unique")

    verified = _verified_relation_summary(exact_relations, cycle_states)
    returns = _daily_return_frame(stock_bars)
    result = result.merge(
        returns,
        on=["entry_date", "vt_symbol"],
        how="left",
        validate="many_to_one",
    ).merge(
        verified,
        on=["entry_date", "vt_symbol"],
        how="left",
        validate="many_to_one",
    )
    result["verified_concept_count"] = (
        pd.to_numeric(result["verified_concept_count"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    result["verified_concept_names"] = result["verified_concept_names"].fillna("")
    result["verified_cycle_ids"] = result["verified_cycle_ids"].fillna("")
    result["verified_first_explosion"] = (
        result["verified_concept_count"].gt(0)
        & pd.to_numeric(result["d_return_pct"], errors="coerce").ge(
            FIRST_EXPLOSION_RETURN_PCT
        )
    )
    result["label_status"] = np.where(
        result["verified_first_explosion"],
        POSITIVE_LABEL_STATUS,
        NEGATIVE_LABEL_STATUS,
    )
    return result.sort_values(["entry_date", "vt_symbol"], kind="stable").reset_index(
        drop=True
    )


def attach_prelaunch_context(
    labels: pd.DataFrame,
    timing_context: pd.DataFrame,
) -> pd.DataFrame:
    """Attach five blocks and D-1 market regime fields for attribution only."""

    _require_columns(labels, ("entry_date", "context_date"), "prelaunch label")
    _require_columns(
        timing_context,
        ("source_date", "active_direction", "danger_state", "market_phase"),
        "timing context",
    )
    result = labels.copy()
    result["entry_date"] = pd.to_datetime(result["entry_date"], errors="raise").dt.date
    result["context_date"] = pd.to_datetime(result["context_date"], errors="raise").dt.date
    blocks = chronological_event_blocks(
        tuple(sorted(result["entry_date"].unique())),
        block_count=5,
    ).rename(columns={"source_date": "entry_date"})
    timing = timing_context.loc[
        :,
        ["source_date", "active_direction", "danger_state", "market_phase"],
    ].copy()
    timing["source_date"] = pd.to_datetime(timing["source_date"], errors="raise").dt.date
    if timing["source_date"].duplicated().any():
        raise ValueError("timing context dates must be unique")
    timing = timing.rename(columns={"source_date": "timing_source_date"})
    result = result.merge(
        blocks,
        on="entry_date",
        how="left",
        validate="many_to_one",
    ).merge(
        timing,
        left_on="context_date",
        right_on="timing_source_date",
        how="left",
        validate="many_to_one",
    )
    for column in ("active_direction", "danger_state", "market_phase"):
        result[column] = result[column].fillna("UNKNOWN")
    result["market_regime"] = (
        result["active_direction"].astype(str)
        + "/"
        + result["danger_state"].astype(str)
    )
    return result.sort_values(["entry_date", "vt_symbol"], kind="stable").reset_index(
        drop=True
    )


def discover_prelaunch_rule(labels: pd.DataFrame) -> PrelaunchDiscoveryResult:
    """Fit on blocks 1-3 and freeze at most one eligible leaf."""

    _require_columns(
        labels,
        (
            "event_id",
            "entry_date",
            "block",
            "verified_first_explosion",
            *PRELAUNCH_FEATURES,
        ),
        "prelaunch discovery label",
    )
    development = labels.loc[labels["block"].isin((1, 2, 3))].copy()
    if development["event_id"].duplicated().any():
        raise ValueError("prelaunch discovery event IDs must be unique")
    feature_values = development.loc[:, list(PRELAUNCH_FEATURES)].apply(
        pd.to_numeric, errors="coerce"
    )
    if feature_values.isna().any().any() or not np.isfinite(
        feature_values.to_numpy()
    ).all():
        raise ValueError("prelaunch discovery features must be complete finite values")
    target = development["verified_first_explosion"].astype(bool)
    if target.nunique() != 2:
        raise ValueError("prelaunch discovery requires both label classes")
    if len(development) < TREE_MIN_SAMPLES_LEAF * 2:
        raise ValueError("prelaunch discovery sample is too small for the frozen tree")

    model = DecisionTreeClassifier(
        max_depth=TREE_MAX_DEPTH,
        min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
        class_weight="balanced",
        random_state=TREE_RANDOM_STATE,
    )
    model.fit(feature_values, target)
    leaf_nodes = model.apply(feature_values)
    leaf_rows = _build_leaf_rows(model, development, leaf_nodes)
    selected_leaf = _select_development_leaf(leaf_rows)
    selected_node = int(selected_leaf[0]) if selected_leaf is not None else None
    attempts = tuple(
        _leaf_attempt(
            leaf_node,
            rule,
            metrics,
            reasons,
            selected_node=selected_node,
        )
        for leaf_node, rule, metrics, reasons in leaf_rows
    )
    return PrelaunchDiscoveryResult(
        model=model,
        selected_rule=(selected_leaf[1] if selected_leaf is not None else None),
        attempts=attempts,
        development_base_rate=float(target.mean()),
    )


def apply_prelaunch_rule(
    labels: pd.DataFrame,
    rule: PrelaunchRule,
) -> pd.DataFrame:
    """Apply the frozen conjunction without reading trade outcomes."""

    _require_columns(labels, PRELAUNCH_FEATURES, "prelaunch rule feature")
    result = labels.copy()
    predicate = pd.Series(True, index=result.index, dtype=bool)
    for condition in rule.conditions:
        values = pd.to_numeric(result[condition.feature], errors="coerce")
        predicate &= (
            values.le(condition.threshold)
            if condition.operator == "<="
            else values.gt(condition.threshold)
        )
    result["prelaunch_rule_match"] = predicate.fillna(False).astype(bool)
    result["prelaunch_rule_id"] = rule.rule_id
    return result


def evaluate_prelaunch_rule(
    labels: pd.DataFrame,
    discovery: PrelaunchDiscoveryResult,
) -> dict[str, Any]:
    """Evaluate the selected leaf on blocks 4-5 and decide the trade gate."""

    if discovery.selected_rule is None:
        return {
            "overall_conclusion": "no_development_prelaunch_leaf",
            "trade_gate_passed": False,
            "failed_gates": ["no_selected_development_leaf"],
            "selected_rule": None,
            "validation_metrics": _label_metrics(
                labels.iloc[0:0], labels.iloc[0:0]
            ),
            "trade_outcomes_read": False,
        }
    validation = labels.loc[labels["block"].isin((4, 5))].copy()
    applied = apply_prelaunch_rule(validation, discovery.selected_rule)
    selected = applied.loc[applied["prelaunch_rule_match"]]
    metrics = _label_metrics(selected, validation)
    failed = _validation_rejection_reasons(metrics)
    return {
        "overall_conclusion": (
            "validated_prelaunch_label_edge"
            if not failed
            else "prelaunch_label_validation_failed"
        ),
        "trade_gate_passed": not failed,
        "failed_gates": failed,
        "selected_rule": _rule_payload(discovery.selected_rule),
        "validation_metrics": metrics,
        "trade_outcomes_read": False,
    }


def execute_prelaunch_trade_gate(
    labels: pd.DataFrame,
    discovery: PrelaunchDiscoveryResult,
    evaluation: Mapping[str, Any],
    stock_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> dict[str, Any]:
    """Read trade outcomes only after the label-validation gate passes."""

    if not bool(evaluation.get("trade_gate_passed")) or discovery.selected_rule is None:
        return {
            "status": "not_run_label_gate_failed",
            "trade_outcomes_read": False,
            "selected_rule_id": None,
            "trade_metrics": [],
        }
    applied = apply_prelaunch_rule(labels, discovery.selected_rule)
    matches = applied.loc[applied["prelaunch_rule_match"]].copy()
    normal, stressed = _execute_prelaunch_rule_hits(
        matches,
        stock_bars,
        trading_dates=trading_dates,
    )
    ledger = _build_trade_ledger(matches, normal, stressed)
    metrics = _build_trade_metrics(ledger)
    from .research_protocol import fingerprint_frame

    return {
        "status": "completed_reused_history_diagnostic",
        "trade_outcomes_read": True,
        "selected_rule_id": discovery.selected_rule.rule_id,
        "signals": int(len(matches)),
        "trade_metrics": _records(metrics),
        "trade_ledger_fingerprint": fingerprint_frame(
            ledger,
            identity_columns=("event_id",),
        ).as_dict(),
    }


def _execute_prelaunch_rule_hits(
    matches: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    from .stock_main_rise_audit import execute_stock_main_rise_hold

    events = matches.copy()
    events["evidence_level"] = "prelaunch_full_universe_proxy"
    return execute_stock_main_rise_hold(
        events,
        stock_bars,
        trading_dates=trading_dates,
    )


def _build_trade_ledger(
    matches: pd.DataFrame,
    normal: pd.DataFrame,
    stressed: pd.DataFrame,
) -> pd.DataFrame:
    required = ("event_id", "status", "net_return_pct")
    _require_columns(normal, required, "normal prelaunch outcome")
    _require_columns(stressed, required, "stressed prelaunch outcome")
    if normal["event_id"].duplicated().any() or stressed["event_id"].duplicated().any():
        raise ValueError("prelaunch outcome event IDs must be unique")
    identity_columns = [
        column
        for column in (
            "event_id",
            "entry_date",
            "block",
            "vt_symbol",
            "market_regime",
            "verified_first_explosion",
        )
        if column in matches
    ]
    normal_values = normal.loc[:, list(required)].rename(
        columns={"status": "normal_status"}
    )
    stressed_values = stressed.loc[:, list(required)].rename(
        columns={
            "status": "stressed_status",
            "net_return_pct": "double_cost_net_return_pct",
        }
    )
    return matches.loc[:, identity_columns].merge(
        normal_values,
        on="event_id",
        how="left",
        validate="one_to_one",
    ).merge(
        stressed_values,
        on="event_id",
        how="left",
        validate="one_to_one",
    )


def _build_trade_metrics(ledger: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for segment, blocks in _metric_segments():
        rows.append(
            {
                "segment": segment,
                **_summarize_trade_rows(ledger.loc[ledger["block"].isin(blocks)]),
            }
        )
    return pd.DataFrame(rows)


def _summarize_trade_rows(rows: pd.DataFrame) -> dict[str, Any]:
    closed = rows.loc[
        rows["normal_status"].eq("closed")
        & rows["stressed_status"].eq("closed")
    ].copy()
    normal = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
    stressed = pd.to_numeric(
        closed.loc[normal.index, "double_cost_net_return_pct"], errors="coerce"
    ).dropna()
    compound, drawdown = _daily_compounding(closed.loc[normal.index])
    return {
        "signals": int(len(rows)),
        "closed_trades": int(len(normal)),
        "source_days": int(
            pd.to_datetime(closed.loc[normal.index, "entry_date"]).dt.date.nunique()
        )
        if len(normal)
        else 0,
        "win_rate_pct": float(normal.gt(0).mean() * 100.0) if len(normal) else None,
        "mean_net_return_pct": float(normal.mean()) if len(normal) else None,
        "median_net_return_pct": float(normal.median()) if len(normal) else None,
        "profit_factor": _profit_factor(normal),
        "double_cost_mean_net_return_pct": (
            float(stressed.mean()) if len(stressed) else None
        ),
        "compound_return_pct": compound,
        "maximum_drawdown_pct": drawdown,
    }


def _daily_compounding(rows: pd.DataFrame) -> tuple[float | None, float | None]:
    if rows.empty:
        return None, None
    frame = rows.copy()
    frame["net_return_pct"] = pd.to_numeric(frame["net_return_pct"], errors="coerce")
    daily = frame.dropna(subset=["net_return_pct"]).groupby(
        "entry_date", sort=True
    )["net_return_pct"].mean()
    if daily.empty:
        return None, None
    equity = (1.0 + daily / 100.0).cumprod()
    drawdown = equity / equity.cummax().clip(lower=1.0) - 1.0
    return float((equity.iloc[-1] - 1.0) * 100.0), float(drawdown.min() * 100.0)


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values > 0].sum())
    losses = abs(float(values.loc[values < 0].sum()))
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _metric_segments() -> tuple[tuple[str, frozenset[int]], ...]:
    return (
        ("all", frozenset(range(1, 6))),
        ("development", frozenset({1, 2, 3})),
        ("validation", frozenset({4, 5})),
        *((f"block_{block}", frozenset({block})) for block in range(1, 6)),
    )


def build_prelaunch_first_explosion_report(
    labels: pd.DataFrame,
    discovery: PrelaunchDiscoveryResult,
    evaluation: Mapping[str, Any],
    trade: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build exhaustive label evidence with trade outcomes behind the gate."""

    label_metrics = _build_label_metrics(labels)
    attribution = _build_regime_attribution(labels, discovery.selected_rule)
    return {
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "study_track": "prelaunch_first_explosion_proxy",
        "overall_conclusion": str(evaluation["overall_conclusion"]),
        "formal_metrics": None,
        "formal_rule_selected": False,
        "strict_historical_top3_claim": False,
        "trade_outcomes_read": bool(trade.get("trade_outcomes_read")),
        "outer_holdout_price_values_read": False,
        "late_segment_is_unseen_validation": False,
        "frozen_contract": {
            "denominator": "all eligible main-board stock-days on observed event dates",
            "feature_cutoff": "D-1 completed daily bars",
            "prior_strong_guard": "no >=5% daily return in prior 10 sessions",
            "features": list(PRELAUNCH_FEATURES),
            "tree": {
                "max_depth": TREE_MAX_DEPTH,
                "min_samples_leaf": TREE_MIN_SAMPLES_LEAF,
                "class_weight": "balanced",
                "random_state": TREE_RANDOM_STATE,
            },
            "development_blocks": [1, 2, 3],
            "validation_blocks": [4, 5],
            "conditional_trade": "D official open to first sellable D+1 official close",
        },
        "coverage": _json_safe(dict(metadata.get("coverage", {}))),
        "label_metrics": _records(label_metrics),
        "leaf_attempts": [_attempt_payload(attempt) for attempt in discovery.attempts],
        "tree_depth": int(discovery.model.get_depth()),
        "tree_leaf_count": int(discovery.model.get_n_leaves()),
        "development_base_rate": discovery.development_base_rate,
        "selected_rule": _json_safe(evaluation.get("selected_rule")),
        "label_evaluation": _json_safe(dict(evaluation)),
        "market_regime_attribution": _records(attribution),
        "conditional_trade": _json_safe(dict(trade)),
        "input_fingerprints": _json_safe(
            dict(metadata.get("input_fingerprints", {}))
        ),
        "discovery_start": _json_safe(metadata.get("discovery_start")),
        "discovery_end": _json_safe(metadata.get("discovery_end")),
        "limitations": [
            "historical D-1 concept membership and strict security status are unavailable",
            "current stock names provide reconstructed ST and delisting exclusions only",
            "unverified rows are not proven true negatives because event evidence can be incomplete",
            "exact main-rise concept relations are post-D outcome labels and cannot generate D orders",
            "blocks 4-5 are reused history rather than an untouched outer holdout",
        ],
    }


def run_prelaunch_first_explosion_study() -> dict[str, Any]:
    """Run the full-universe prelaunch study inside the discovery boundary."""

    return build_prelaunch_first_explosion_report(
        *load_prelaunch_first_explosion_study_data()
    )


def load_prelaunch_first_explosion_study_data() -> tuple[
    pd.DataFrame,
    PrelaunchDiscoveryResult,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    """Load and evaluate discovery-only prelaunch evidence from PostgreSQL."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine, session_scope

    from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
    from .contracts import CONCEPT_SECTOR_TYPES
    from .event_recognition_falsification import (
        EXCLUDED_MANIFEST_CLASSES,
        _normalize_database_events,
        build_exact_reason_relations,
        load_timing_context,
    )
    from .repository import _stock_bars_query
    from .research_protocol import fingerprint_frame
    from .theme_reference_cohorts import classify_manifest_sector

    cycle_inputs = load_cycle_research_inputs()
    discovery_start = cycle_inputs.split.discovery_dates[0]
    discovery_end = cycle_inputs.split.discovery_dates[-1]
    cycle_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )

    with session_scope() as session:
        event_rows = session.execute(
            select(
                schema.stock_events.c.id,
                schema.stock_events.c.vt_symbol,
                schema.stock_events.c.event_date,
                schema.stock_events.c.raw,
            )
            .where(
                schema.stock_events.c.event_type == "limit_pool_zt",
                schema.stock_events.c.event_date <= discovery_end.strftime("%Y%m%d"),
            )
            .order_by(schema.stock_events.c.event_date, schema.stock_events.c.id)
        ).mappings().all()
        concept_rows = session.execute(
            select(schema.sectors.c.id, schema.sectors.c.name)
            .where(schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES))
            .order_by(schema.sectors.c.id)
        ).all()

    events = _normalize_database_events(event_rows, discovery_end=discovery_end)
    events = events.loc[
        pd.to_datetime(events["source_date"]).dt.date.between(
            discovery_start,
            discovery_end,
        )
    ].copy()
    if events.empty:
        raise ValueError("no reason-covered limit-pool dates in the discovery window")
    target_dates = tuple(sorted(events["source_date"].unique()))

    concepts = pd.DataFrame(concept_rows, columns=["sector_id", "concept_name"])
    concepts["manifest_class"] = concepts["sector_id"].map(
        classify_manifest_sector
    )
    concepts = concepts.loc[
        ~concepts["manifest_class"].isin(EXCLUDED_MANIFEST_CLASSES)
    ].copy()
    relations = build_exact_reason_relations(events, concepts)

    discovery_calendar = tuple(
        value for value in cycle_inputs.reliable_dates if value <= discovery_end
    )
    if not discovery_calendar:
        raise ValueError("no reliable trading dates inside the discovery boundary")
    first_position = bisect_left(discovery_calendar, target_dates[0])
    bar_start = discovery_calendar[max(0, first_position - 100)]
    stock_bars = pd.read_sql(
        _stock_bars_query(bar_start, discovery_end),
        get_engine(),
        parse_dates=["trade_date"],
    )
    if stock_bars.empty:
        raise ValueError("no main-board stock bars for prelaunch feature construction")
    stock_bar_dates = pd.to_datetime(stock_bars["trade_date"], errors="raise").dt.date
    if stock_bar_dates.max() > discovery_end:
        raise ValueError("stock bar query crossed the discovery boundary")

    features = build_prelaunch_feature_panel(
        stock_bars,
        target_dates=target_dates,
    )
    if features.empty:
        raise ValueError("no eligible full-universe prelaunch feature rows")
    labels = attach_verified_first_explosion_labels(
        features,
        relations,
        cycle_states,
        stock_bars,
    )
    timing_context = load_timing_context()
    timing_context = timing_context.loc[
        pd.to_datetime(timing_context["source_date"]).dt.date.le(discovery_end)
    ].copy()
    labels = attach_prelaunch_context(labels, timing_context)
    discovery = discover_prelaunch_rule(labels)
    evaluation = evaluate_prelaunch_rule(labels, discovery)
    trading_dates = tuple(
        value for value in discovery_calendar if bar_start <= value <= discovery_end
    )
    trade = execute_prelaunch_trade_gate(
        labels,
        discovery,
        evaluation,
        stock_bars,
        trading_dates=trading_dates,
    )

    coverage = {
        "target_dates": len(target_dates),
        "target_start": target_dates[0].isoformat(),
        "target_end": target_dates[-1].isoformat(),
        "event_rows_with_reason": int(len(events)),
        "exact_reason_relations": int(len(relations)),
        "matched_concepts": int(relations["sector_id"].nunique()),
        "stock_bar_rows": int(len(stock_bars)),
        "stock_bar_start": bar_start.isoformat(),
        "stock_bar_end": stock_bar_dates.max().isoformat(),
        "universe_rows": int(len(labels)),
        "universe_symbols": int(labels["vt_symbol"].nunique()),
        "eligible_universe_dates": int(labels["entry_date"].nunique()),
        "verified_positives": _positive_count(labels),
        "current_membership_rows_read": 0,
        "historical_security_state_rows_read": 0,
    }
    fingerprints = {
        "prelaunch_features": fingerprint_frame(
            features,
            identity_columns=("event_id",),
        ).as_dict(),
        "prelaunch_labels": fingerprint_frame(
            labels,
            identity_columns=("event_id",),
        ).as_dict(),
        "exact_reason_relations": fingerprint_frame(
            relations,
            identity_columns=("source_date", "sector_id", "vt_symbol"),
        ).as_dict(),
        "stock_bars": fingerprint_frame(
            stock_bars,
            identity_columns=("trade_date", "vt_symbol"),
        ).as_dict(),
    }
    trade_fingerprint = trade.get("trade_ledger_fingerprint")
    if trade_fingerprint is not None:
        fingerprints["conditional_trade_ledger"] = _json_safe(trade_fingerprint)
    metadata = {
        "coverage": coverage,
        "input_fingerprints": fingerprints,
        "discovery_start": discovery_start,
        "discovery_end": discovery_end,
    }
    return labels, discovery, evaluation, trade, metadata


def render_prelaunch_first_explosion_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_prelaunch_first_explosion_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    evaluation = report["label_evaluation"]
    trade_metrics = report["conditional_trade"].get("trade_metrics") or []
    all_trade = next(
        (row for row in trade_metrics if row.get("segment") == "all"),
        None,
    )
    lines = [
        "# AlphaAgent 启动前首次爆发研究",
        "",
        f"结论：`{report['overall_conclusion']}`  ",
        "轨道：全主板股票日的启动前代理研究，不是认可后回调  ",
        f"股票日/股票/核验正例：`{coverage.get('universe_rows', 0)}/"
        f"{coverage.get('universe_symbols', 0)}/{coverage.get('verified_positives', 0)}`  ",
        f"读取 D 开盘到 D+1 收盘收益：`{str(report['trade_outcomes_read']).lower()}`  ",
        "正式规则/正式绩效：`null/null`  ",
        (
            "交易诊断（全体命中）："
            f"`{_pct(all_trade.get('win_rate_pct'))}/"
            f"{_pct(all_trade.get('mean_net_return_pct'))}/"
            f"{_pct(all_trade.get('double_cost_mean_net_return_pct'))}`"
            "（胜率/普通成本均值/双倍成本均值）"
            if all_trade is not None
            else "交易诊断：标签门未通过，未读取收益"
        ),
        "",
        "## 数据覆盖",
        "",
        "| Item | Value |",
        "| --- | ---: |",
        f"| 目标事件日 | {coverage.get('target_dates', 0)} |",
        f"| 目标范围 | `{coverage.get('target_start')}..{coverage.get('target_end')}` |",
        f"| 有原因事件 | {coverage.get('event_rows_with_reason', 0)} |",
        f"| 精确概念关系 | {coverage.get('exact_reason_relations', 0)} |",
        f"| 主板日线 | {coverage.get('stock_bar_rows', 0)} |",
        f"| 日线范围 | `{coverage.get('stock_bar_start')}..{coverage.get('stock_bar_end')}` |",
        f"| 当前成员读取 | {coverage.get('current_membership_rows_read', 0)} |",
        f"| 历史证券状态读取 | {coverage.get('historical_security_state_rows_read', 0)} |",
        "",
        "## 标签基线",
        "",
        "| Segment | Rows | Positives | Days | Base rate |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report["label_metrics"]:
        lines.append(
            f"| `{row['segment']}` | {row['rows']} | {row['verified_positives']} | "
            f"{row['source_days']} | {_ratio(row['precision'])} |"
        )
    lines.extend(
        [
            "",
            "## 开发叶子账本",
            "",
            "| Leaf | Conditions | Status | Rows | Positives | Days | Precision | Recall | Lift | Coverage | Reasons |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["leaf_attempts"]:
        conditions = " AND ".join(
            f"{item['feature']} {item['operator']} {item['threshold']:.6f}"
            for item in row["rule"]["conditions"]
        ) or "all"
        lines.append(
            f"| {row['leaf_node']} | `{conditions}` | `{row['status']}` | "
            f"{row['rows']} | {row['verified_positives']} | {row['source_days']} | "
            f"{_ratio(row['precision'])} | {_ratio(row['positive_recall'])} | "
            f"{_number(row['precision_lift'])} | {_ratio(row['universe_coverage'])} | "
            f"`{','.join(row['rejection_reasons']) or '-'}` |"
        )
    validation = evaluation["validation_metrics"]
    lines.extend(
        [
            "",
            "## 后段标签验证",
            "",
            f"规则：`{_rule_text(report.get('selected_rule'))}`  ",
            f"信号/正例/日期：`{validation['rows']}/{validation['verified_positives']}/"
            f"{validation['source_days']}`  ",
            f"精度/召回/提升/覆盖：`{_ratio(validation['precision'])}/"
            f"{_ratio(validation['positive_recall'])}/{_number(validation['precision_lift'])}/"
            f"{_ratio(validation['universe_coverage'])}`  ",
            f"失败门：`{','.join(evaluation['failed_gates']) or '-'}`",
            "",
            "## 条件交易诊断",
            "",
            f"状态：`{report['conditional_trade']['status']}`",
        ]
    )
    if trade_metrics:
        lines.extend(
            [
                "",
                "| Segment | Closed | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in trade_metrics:
            lines.append(
                f"| `{row['segment']}` | {row['closed_trades']} | {row['source_days']} | "
                f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
                f"{_number(row['profit_factor'])} | "
                f"{_pct(row['double_cost_mean_net_return_pct'])} | "
                f"{_pct(row['compound_return_pct'])} | "
                f"{_pct(row['maximum_drawdown_pct'])} |"
            )
        lines.extend(
            [
                "",
                "复利和回撤按每个信号日全部闭合命中等权后逐日计算，只是复用历史的诊断曲线，不是现金账户或正式绩效。",
            ]
        )
    lines.extend(
        [
            "",
            "## 金银与危险状态归因",
            "",
            "| Segment | Regime | Universe | Base | Rule rows | Rule positives | Rule precision | Lift |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["market_regime_attribution"]:
        lines.append(
            f"| `{row['segment']}` | `{row['market_regime']}` | "
            f"{row['universe_rows']} | {_ratio(row['universe_base_rate'])} | "
            f"{row['rule_rows']} | {row['rule_positives']} | "
            f"{_ratio(row['rule_precision'])} | "
            f"{_number(row['rule_precision_lift'])} |"
        )
    lines.extend(
        [
            "",
            "## 输入指纹",
            "",
            "| Input | Rows | SHA256 |",
            "| --- | ---: | --- |",
        ]
    )
    for name, fingerprint in sorted(report["input_fingerprints"].items()):
        lines.append(
            f"| `{name}` | {fingerprint.get('rows', 0)} | "
            f"`{fingerprint.get('digest')}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "未核验行统一标记 `not_verified_by_available_event_evidence`，不代表已证明不会爆发。历史证券状态只使用当前名称重建，主升概念关系仅是 D 日后的结果标签，不能生成 D 日订单。",
            "",
        ]
    )
    return "\n".join(lines)


def _build_label_metrics(labels: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for segment, blocks in _metric_segments():
        cohort = labels.loc[labels["block"].isin(blocks)]
        rows.append({"segment": segment, **_label_metrics(cohort, cohort)})
    return pd.DataFrame(rows)


def _build_regime_attribution(
    labels: pd.DataFrame,
    rule: PrelaunchRule | None,
) -> pd.DataFrame:
    rows = []
    applied = apply_prelaunch_rule(labels, rule) if rule is not None else None
    for segment, blocks in (("development", {1, 2, 3}), ("validation", {4, 5})):
        universe = labels.loc[labels["block"].isin(blocks)]
        for regime, group in universe.groupby("market_regime", sort=True):
            baseline = _label_metrics(group, group)
            selected = (
                applied.loc[
                    applied["block"].isin(blocks)
                    & applied["market_regime"].eq(regime)
                    & applied["prelaunch_rule_match"]
                ]
                if applied is not None
                else group.iloc[0:0]
            )
            rule_metrics = _label_metrics(selected, group)
            rows.append(
                {
                    "segment": segment,
                    "market_regime": str(regime),
                    "universe_rows": baseline["rows"],
                    "universe_positives": baseline["verified_positives"],
                    "universe_base_rate": baseline["precision"],
                    "rule_rows": rule_metrics["rows"],
                    "rule_positives": rule_metrics["verified_positives"],
                    "rule_precision": rule_metrics["precision"],
                    "rule_precision_lift": rule_metrics["precision_lift"],
                }
            )
    return pd.DataFrame(rows)


def _build_leaf_rows(
    model: DecisionTreeClassifier,
    development: pd.DataFrame,
    leaf_nodes: np.ndarray,
) -> list[tuple[int, PrelaunchRule, dict[str, Any], list[str]]]:
    rows = []
    for leaf_node, conditions in _leaf_paths(model):
        selected = development.loc[leaf_nodes == leaf_node]
        metrics = _label_metrics(selected, development)
        rows.append(
            (
                leaf_node,
                PrelaunchRule(f"prelaunch_leaf_{leaf_node}", conditions),
                metrics,
                _development_rejection_reasons(metrics),
            )
        )
    return rows


def _select_development_leaf(
    rows: list[tuple[int, PrelaunchRule, dict[str, Any], list[str]]],
) -> tuple[int, PrelaunchRule, dict[str, Any], list[str]] | None:
    eligible = [row for row in rows if not row[3]]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda row: (
            -float(row[2]["precision_lift"]),
            -int(row[2]["verified_positives"]),
            float(row[2]["universe_coverage"]),
            int(row[0]),
        ),
    )


def _leaf_attempt(
    leaf_node: int,
    rule: PrelaunchRule,
    metrics: dict[str, Any],
    reasons: list[str],
    *,
    selected_node: int | None,
) -> PrelaunchLeafAttempt:
    selected = leaf_node == selected_node
    rejection_reasons = tuple(reasons)
    if not selected and not rejection_reasons and selected_node is not None:
        rejection_reasons = ("eligible_but_not_best_development_leaf",)
    return PrelaunchLeafAttempt(
        leaf_node=int(leaf_node),
        rule=rule,
        status="selected" if selected else "rejected",
        rejection_reasons=rejection_reasons,
        rows=int(metrics["rows"]),
        verified_positives=int(metrics["verified_positives"]),
        source_days=int(metrics["source_days"]),
        precision=_optional_float(metrics["precision"]),
        positive_recall=_optional_float(metrics["positive_recall"]),
        precision_lift=_optional_float(metrics["precision_lift"]),
        universe_coverage=_optional_float(metrics["universe_coverage"]),
    )


def _leaf_paths(
    model: DecisionTreeClassifier,
) -> list[tuple[int, tuple[PrelaunchCondition, ...]]]:
    tree = model.tree_
    paths: list[tuple[int, tuple[PrelaunchCondition, ...]]] = []

    def visit(node: int, conditions: tuple[PrelaunchCondition, ...]) -> None:
        left = int(tree.children_left[node])
        right = int(tree.children_right[node])
        if left == right:
            paths.append((node, conditions))
            return
        feature = PRELAUNCH_FEATURES[int(tree.feature[node])]
        threshold = float(tree.threshold[node])
        visit(left, (*conditions, PrelaunchCondition(feature, "<=", threshold)))
        visit(right, (*conditions, PrelaunchCondition(feature, ">", threshold)))

    visit(0, ())
    return sorted(paths, key=lambda item: item[0])


def _label_metrics(selected: pd.DataFrame, universe: pd.DataFrame) -> dict[str, Any]:
    selected_positive = _positive_count(selected)
    universe_positive = _positive_count(universe)
    precision = selected_positive / len(selected) if len(selected) else None
    base_rate = universe_positive / len(universe) if len(universe) else None
    return {
        "rows": int(len(selected)),
        "verified_positives": selected_positive,
        "source_days": (
            int(pd.to_datetime(selected["entry_date"]).dt.date.nunique())
            if len(selected) and "entry_date" in selected
            else 0
        ),
        "precision": precision,
        "positive_recall": (
            selected_positive / universe_positive if universe_positive else None
        ),
        "precision_lift": (
            precision / base_rate
            if precision is not None and base_rate is not None and base_rate > 0
            else None
        ),
        "universe_coverage": len(selected) / len(universe) if len(universe) else None,
        "universe_rows": int(len(universe)),
        "universe_positives": universe_positive,
        "universe_base_rate": base_rate,
    }


def _positive_count(frame: pd.DataFrame) -> int:
    if "verified_first_explosion" not in frame:
        return 0
    return int(frame["verified_first_explosion"].astype(bool).sum())


def _development_rejection_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons = []
    if int(metrics["rows"]) < MIN_DEVELOPMENT_ROWS:
        reasons.append("fewer_than_1000_rows")
    if int(metrics["verified_positives"]) < MIN_DEVELOPMENT_POSITIVES:
        reasons.append("fewer_than_30_verified_positives")
    if int(metrics["source_days"]) < MIN_DEVELOPMENT_DAYS:
        reasons.append("fewer_than_30_dates")
    if _below(metrics["positive_recall"], MIN_DEVELOPMENT_RECALL):
        reasons.append("positive_recall_below_5pct")
    if _below(metrics["precision_lift"], MIN_DEVELOPMENT_PRECISION_LIFT):
        reasons.append("precision_lift_below_2")
    if _above(metrics["universe_coverage"], MAX_RULE_COVERAGE):
        reasons.append("universe_coverage_above_10pct")
    return reasons


def _validation_rejection_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons = []
    if int(metrics["rows"]) < MIN_VALIDATION_ROWS:
        reasons.append("fewer_than_500_rows")
    if int(metrics["verified_positives"]) < MIN_VALIDATION_POSITIVES:
        reasons.append("fewer_than_15_verified_positives")
    if int(metrics["source_days"]) < MIN_VALIDATION_DAYS:
        reasons.append("fewer_than_20_dates")
    if _below(metrics["positive_recall"], MIN_VALIDATION_RECALL):
        reasons.append("positive_recall_below_2_5pct")
    if not _strictly_above(metrics["precision"], metrics["universe_base_rate"]):
        reasons.append("precision_not_above_validation_base")
    if _below(metrics["precision_lift"], MIN_VALIDATION_PRECISION_LIFT):
        reasons.append("precision_lift_below_1_5")
    if _above(metrics["universe_coverage"], MAX_RULE_COVERAGE):
        reasons.append("universe_coverage_above_10pct")
    return reasons


def _rule_payload(rule: PrelaunchRule) -> dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "conditions": [
            {
                "feature": condition.feature,
                "operator": condition.operator,
                "threshold": condition.threshold,
            }
            for condition in rule.conditions
        ],
    }


def _attempt_payload(attempt: PrelaunchLeafAttempt) -> dict[str, Any]:
    return _json_safe(asdict(attempt))


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_safe(row) for row in frame.to_dict("records")]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    try:
        return None if bool(pd.isna(value)) else value
    except (TypeError, ValueError):
        return value


def _rule_text(rule: Mapping[str, Any] | None) -> str:
    if not rule:
        return "null"
    conditions = rule.get("conditions") or []
    return " AND ".join(
        f"{item['feature']} {item['operator']} {float(item['threshold']):.6f}"
        for item in conditions
    ) or "all"


def _ratio(value: Any) -> str:
    number = _optional_float(value)
    return "-" if number is None else f"{number * 100.0:.4f}%"


def _pct(value: Any) -> str:
    number = _optional_float(value)
    return "-" if number is None else f"{number:.4f}%"


def _number(value: Any) -> str:
    number = _optional_float(value)
    return "-" if number is None else f"{number:.4f}"


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _below(value: Any, threshold: float) -> bool:
    number = _optional_float(value)
    return number is None or number < threshold


def _above(value: Any, threshold: float) -> bool:
    number = _optional_float(value)
    return number is not None and number > threshold


def _strictly_above(left: Any, right: Any) -> bool:
    left_number = _optional_float(left)
    right_number = _optional_float(right)
    return (
        left_number is not None
        and right_number is not None
        and left_number > right_number
    )


def _verified_relation_summary(
    relations: pd.DataFrame,
    cycle_states: pd.DataFrame,
) -> pd.DataFrame:
    relation_frame = relations.loc[
        :, ["event_id", "source_date", "sector_id", "concept_name", "vt_symbol"]
    ].copy()
    relation_frame["source_date"] = pd.to_datetime(
        relation_frame["source_date"], errors="raise"
    ).dt.date
    states = cycle_states.loc[
        cycle_states["definition"].eq("breakout_trend")
        & cycle_states["in_cycle"].astype(bool),
        ["trade_date", "sector_id", "cycle_id"],
    ].copy()
    states["trade_date"] = pd.to_datetime(states["trade_date"], errors="raise").dt.date
    if states.duplicated(["trade_date", "sector_id"]).any():
        raise ValueError("active cycle state identities must be unique")
    active = relation_frame.merge(
        states,
        left_on=["source_date", "sector_id"],
        right_on=["trade_date", "sector_id"],
        how="inner",
        validate="many_to_one",
    )
    if active.empty:
        return pd.DataFrame(
            columns=[
                "entry_date",
                "vt_symbol",
                "verified_concept_count",
                "verified_concept_names",
                "verified_cycle_ids",
            ]
        )
    return (
        active.groupby(["source_date", "vt_symbol"], sort=True, as_index=False)
        .agg(
            verified_concept_count=("sector_id", "nunique"),
            verified_concept_names=(
                "concept_name",
                lambda values: " | ".join(sorted(set(values.astype(str)))),
            ),
            verified_cycle_ids=(
                "cycle_id",
                lambda values: " | ".join(sorted(set(values.astype(str)))),
            ),
        )
        .rename(columns={"source_date": "entry_date"})
    )


def _daily_return_frame(stock_bars: pd.DataFrame) -> pd.DataFrame:
    bars = stock_bars.loc[:, ["vt_symbol", "trade_date", "close_price"]].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock bar identities must be unique")
    bars["close_price"] = pd.to_numeric(bars["close_price"], errors="coerce")
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    bars["d_return_pct"] = bars.groupby("vt_symbol", sort=False)[
        "close_price"
    ].pct_change(fill_method=None) * 100.0
    return bars.loc[:, ["vt_symbol", "trade_date", "d_return_pct"]].rename(
        columns={"trade_date": "entry_date"}
    )


def _reject_feature_labels(features: pd.DataFrame) -> None:
    prohibited = sorted(PROHIBITED_FEATURE_LABEL_COLUMNS & set(features))
    prohibited.extend(
        sorted(
            str(column)
            for column in features.columns
            if str(column).startswith(("future_", "outcome_", "exit_"))
        )
    )
    if prohibited:
        raise ValueError(f"feature input contains prohibited labels: {prohibited}")


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
