"""Causal main-rise quality discovery for frozen V5 support-day events."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from .support_day_entry import (
    DEVELOPMENT_BLOCKS,
    PROHIBITED_OUTCOME_TOKENS,
    summarize_d1_trades,
)


QUALITY_FEATURES = (
    "campaign_day",
    "concept_gain_pct",
    "leg_gain_pct",
    "strong_days_since_ignition",
    "turnover_expansion",
    "volume_ratio_prior5",
    "dynamic_rank",
    "wave_number",
    "peak_gap_pct",
    "peak_drawdown_low_pct",
    "close_location",
    "daily_return_pct",
)
TREE_MAX_DEPTH = 2
TREE_MIN_SAMPLES_LEAF = 100
TREE_RANDOM_STATE = 0
MIN_DEVELOPMENT_TRADES = 100
MIN_WIN_RATE_PCT = 60.0
MIN_PROFIT_FACTOR = 1.2
MIN_LATE_BLOCK_TRADES = 30
DOUBLE_COST_INCREMENT_PCT = 0.2


@dataclass(frozen=True)
class QualityCondition:
    feature: str
    operator: str
    threshold: float

    def __post_init__(self) -> None:
        if self.feature not in QUALITY_FEATURES:
            raise ValueError(f"unsupported support quality feature: {self.feature}")
        if self.operator not in {"<=", ">"}:
            raise ValueError(f"unsupported support quality operator: {self.operator}")


@dataclass(frozen=True)
class QualityLeaf:
    rule_id: str
    leaf_node: int
    conditions: tuple[QualityCondition, ...]


@dataclass(frozen=True)
class QualityTreeDiscovery:
    model: DecisionTreeClassifier
    leaves: tuple[QualityLeaf, ...]
    development_rows: int
    incomplete_feature_rows: int
    model_fingerprint: str


def enrich_support_quality_events(
    events: pd.DataFrame,
    leader_paths: pd.DataFrame,
) -> pd.DataFrame:
    """Attach same-day campaign quality without reading any outcome column."""

    _reject_outcome_columns(events)
    _reject_outcome_columns(leader_paths)
    event_identity = ("campaign_id", "vt_symbol", "signal_date")
    path_identity = ("campaign_id", "vt_symbol", "trade_date")
    _require_columns(
        events,
        (
            *event_identity,
            "feature_cutoff_date",
            "close_price",
            "record_high_price",
            "peak_drawdown_low_pct",
            "close_location",
            "daily_return_pct",
            "volume_ratio_prior5",
            "dynamic_rank",
            "wave_number",
        ),
        "support quality event",
    )
    path_features = (
        "campaign_day",
        "concept_gain_pct",
        "leg_gain_pct",
        "strong_days_since_ignition",
        "turnover_expansion",
    )
    _require_columns(
        leader_paths,
        (*path_identity, "feature_cutoff_date", *path_features),
        "support quality leader path",
    )
    event_frame = events.copy()
    path_frame = leader_paths.loc[
        :, [*path_identity, "feature_cutoff_date", *path_features]
    ].copy()
    event_frame["signal_date"] = _dates(event_frame["signal_date"])
    event_frame["feature_cutoff_date"] = _dates(
        event_frame["feature_cutoff_date"]
    )
    path_frame["trade_date"] = _dates(path_frame["trade_date"])
    path_frame["feature_cutoff_date"] = _dates(path_frame["feature_cutoff_date"])
    if event_frame.duplicated(list(event_identity)).any():
        raise ValueError("support quality event identities must be unique")
    if path_frame.duplicated(list(path_identity)).any():
        raise ValueError("support quality leader path identities must be unique")
    if not event_frame["feature_cutoff_date"].eq(event_frame["signal_date"]).all():
        raise ValueError("support quality event cutoff must equal signal date")
    if not path_frame["feature_cutoff_date"].eq(path_frame["trade_date"]).all():
        raise ValueError("support quality path cutoff must equal trade date")

    path_frame = path_frame.rename(
        columns={
            "trade_date": "signal_date",
            "feature_cutoff_date": "quality_feature_cutoff_date",
        }
    )
    enriched = event_frame.merge(
        path_frame,
        on=list(event_identity),
        how="left",
        validate="one_to_one",
        sort=False,
    )
    enriched["peak_gap_pct"] = (
        pd.to_numeric(enriched["close_price"], errors="coerce")
        / pd.to_numeric(enriched["record_high_price"], errors="coerce")
        - 1.0
    ) * 100.0
    numeric = enriched.loc[:, list(QUALITY_FEATURES)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    enriched.loc[:, list(QUALITY_FEATURES)] = numeric
    enriched["quality_feature_complete"] = np.isfinite(
        numeric.to_numpy(dtype=float)
    ).all(axis=1)
    return enriched


def fit_development_quality_tree(trades: pd.DataFrame) -> QualityTreeDiscovery:
    """Fit the one frozen depth-2 tree using development trades only."""

    _require_columns(
        trades,
        (
            "signal_id",
            "signal_date",
            "time_block",
            "exit_date",
            "net_return_pct",
            *QUALITY_FEATURES,
        ),
        "support quality trade",
    )
    development = trades.loc[
        trades["time_block"].isin(DEVELOPMENT_BLOCKS)
        & trades["exit_date"].notna()
        & trades["net_return_pct"].notna()
    ].copy()
    development["signal_date"] = _dates(development["signal_date"])
    development = development.sort_values(
        ["signal_date", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)
    features = development.loc[:, list(QUALITY_FEATURES)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    complete = np.isfinite(features.to_numpy(dtype=float)).all(axis=1)
    incomplete_rows = int((~complete).sum())
    development = development.loc[complete].reset_index(drop=True)
    features = features.loc[complete].reset_index(drop=True)
    if len(development) < TREE_MIN_SAMPLES_LEAF * 2:
        raise ValueError("support quality development sample is too small")
    target = pd.to_numeric(
        development["net_return_pct"], errors="raise"
    ).gt(0.0)
    if target.nunique() != 2:
        raise ValueError("support quality development requires wins and losses")
    model = DecisionTreeClassifier(
        max_depth=TREE_MAX_DEPTH,
        min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
        random_state=TREE_RANDOM_STATE,
    )
    model.fit(features, target)
    leaves = tuple(
        QualityLeaf(
            rule_id=f"support_quality_leaf_{leaf_node}",
            leaf_node=leaf_node,
            conditions=conditions,
        )
        for leaf_node, conditions in _leaf_paths(model)
    )
    fingerprint = _tree_fingerprint(leaves)
    return QualityTreeDiscovery(
        model=model,
        leaves=leaves,
        development_rows=int(len(development)),
        incomplete_feature_rows=incomplete_rows,
        model_fingerprint=fingerprint,
    )


def describe_quality_tree(discovery: QualityTreeDiscovery) -> dict[str, Any]:
    return {
        "tree_contract": {
            "max_depth": TREE_MAX_DEPTH,
            "min_samples_leaf": TREE_MIN_SAMPLES_LEAF,
            "random_state": TREE_RANDOM_STATE,
        },
        "features": list(QUALITY_FEATURES),
        "development_rows": discovery.development_rows,
        "incomplete_feature_rows": discovery.incomplete_feature_rows,
        "leaves": [_leaf_dict(leaf) for leaf in discovery.leaves],
        "model_fingerprint": discovery.model_fingerprint,
    }


def apply_quality_leaf(frame: pd.DataFrame, leaf: QualityLeaf) -> pd.Series:
    _require_columns(
        frame,
        tuple(condition.feature for condition in leaf.conditions),
        "support quality leaf",
    )
    selected = pd.Series(True, index=frame.index, dtype=bool)
    for condition in leaf.conditions:
        values = pd.to_numeric(frame[condition.feature], errors="coerce")
        selected &= (
            values.le(condition.threshold)
            if condition.operator == "<="
            else values.gt(condition.threshold)
        )
    return selected.fillna(False).astype(bool)


def freeze_development_quality_leaf(
    trades: pd.DataFrame,
    discovery: QualityTreeDiscovery,
    cash_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Select at most one explicit leaf without touching late-block rows."""

    development = trades.loc[
        trades["time_block"].isin(DEVELOPMENT_BLOCKS)
    ].copy()
    attempts = []
    for leaf in discovery.leaves:
        selected = development.loc[apply_quality_leaf(development, leaf)]
        metrics = summarize_d1_trades(selected)
        returns = pd.to_numeric(
            selected.loc[selected["exit_date"].notna(), "net_return_pct"],
            errors="coerce",
        ).dropna()
        double_cost_mean = (
            float((returns - DOUBLE_COST_INCREMENT_PCT).mean())
            if len(returns)
            else None
        )
        stable_blocks = sum(
            _positive_block(
                selected.loc[selected["time_block"].eq(block)]
            )
            for block in sorted(DEVELOPMENT_BLOCKS)
        )
        cash_compound = _finite_or_none(
            cash_results.get(leaf.rule_id, {}).get("compound_return_pct")
        )
        passed = bool(
            int(metrics["closed_trades"]) >= MIN_DEVELOPMENT_TRADES
            and float(metrics["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
            and float(metrics["mean_net_return_pct"] or 0.0) > 0.0
            and float(metrics["profit_factor"] or 0.0) >= MIN_PROFIT_FACTOR
            and float(double_cost_mean or 0.0) > 0.0
            and stable_blocks >= 2
            and cash_compound is not None
        )
        attempts.append(
            {
                **_leaf_dict(leaf),
                "development_closed_trades": metrics["closed_trades"],
                "development_win_rate_pct": metrics["win_rate_pct"],
                "development_mean_net_return_pct": metrics[
                    "mean_net_return_pct"
                ],
                "development_profit_factor": metrics["profit_factor"],
                "development_double_cost_mean_pct": double_cost_mean,
                "development_stable_blocks": stable_blocks,
                "development_cash_compound_pct": cash_compound,
                "nomination_passed": passed,
            }
        )
    eligible = [attempt for attempt in attempts if attempt["nomination_passed"]]
    selected = (
        sorted(
            eligible,
            key=lambda row: (
                -float(row["development_cash_compound_pct"]),
                -float(row["development_profit_factor"]),
                _condition_text(row["conditions"]),
            ),
        )[0]
        if eligible
        else None
    )
    return {
        "selected_leaf": (
            {
                key: selected[key]
                for key in ("rule_id", "leaf_node", "conditions")
            }
            if selected is not None
            else None
        ),
        "leaf_metrics": attempts,
    }


def evaluate_sequential_late_blocks(trades: pd.DataFrame) -> dict[str, Any]:
    """Evaluate block 5 only after the unchanged rule passes block 4."""

    _require_columns(
        trades,
        ("time_block", "exit_date", "net_return_pct"),
        "support quality validation trade",
    )
    block_4 = _late_block_result(trades.loc[trades["time_block"].eq("block_4")])
    if not block_4["passed"]:
        return {
            "block_4": block_4,
            "block_5": None,
            "late_validation_passed": False,
        }
    block_5 = _late_block_result(trades.loc[trades["time_block"].eq("block_5")])
    return {
        "block_4": block_4,
        "block_5": block_5,
        "late_validation_passed": bool(block_5["passed"]),
    }


def quality_leaf_from_dict(value: Mapping[str, Any]) -> QualityLeaf:
    return QualityLeaf(
        rule_id=str(value["rule_id"]),
        leaf_node=int(value["leaf_node"]),
        conditions=tuple(
            QualityCondition(
                feature=str(condition["feature"]),
                operator=str(condition["operator"]),
                threshold=float(condition["threshold"]),
            )
            for condition in value.get("conditions", ())
        ),
    )


def _leaf_paths(
    model: DecisionTreeClassifier,
) -> list[tuple[int, tuple[QualityCondition, ...]]]:
    tree = model.tree_
    feature_names = [str(value) for value in model.feature_names_in_]
    paths: list[tuple[int, tuple[QualityCondition, ...]]] = []

    def visit(node: int, conditions: tuple[QualityCondition, ...]) -> None:
        left = int(tree.children_left[node])
        right = int(tree.children_right[node])
        if left == right:
            paths.append((node, conditions))
            return
        feature = feature_names[int(tree.feature[node])]
        threshold = float(tree.threshold[node])
        visit(left, (*conditions, QualityCondition(feature, "<=", threshold)))
        visit(right, (*conditions, QualityCondition(feature, ">", threshold)))

    visit(0, ())
    return sorted(paths, key=lambda item: item[0])


def _tree_fingerprint(leaves: Sequence[QualityLeaf]) -> str:
    payload = {
        "features": QUALITY_FEATURES,
        "max_depth": TREE_MAX_DEPTH,
        "min_samples_leaf": TREE_MIN_SAMPLES_LEAF,
        "random_state": TREE_RANDOM_STATE,
        "leaves": [_leaf_dict(leaf) for leaf in leaves],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _leaf_dict(leaf: QualityLeaf) -> dict[str, Any]:
    return {
        "rule_id": leaf.rule_id,
        "leaf_node": leaf.leaf_node,
        "conditions": [
            {
                "feature": condition.feature,
                "operator": condition.operator,
                "threshold": condition.threshold,
            }
            for condition in leaf.conditions
        ],
    }


def _late_block_result(trades: pd.DataFrame) -> dict[str, Any]:
    metrics = summarize_d1_trades(trades)
    passed = bool(
        int(metrics["closed_trades"]) >= MIN_LATE_BLOCK_TRADES
        and float(metrics["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
        and float(metrics["mean_net_return_pct"] or 0.0) > 0.0
        and float(metrics["profit_factor"] or 0.0) >= MIN_PROFIT_FACTOR
    )
    return {**metrics, "passed": passed}


def _positive_block(trades: pd.DataFrame) -> bool:
    metrics = summarize_d1_trades(trades)
    return bool(
        int(metrics["closed_trades"]) > 0
        and float(metrics["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
        and float(metrics["mean_net_return_pct"] or 0.0) > 0.0
    )


def _condition_text(conditions: Sequence[Mapping[str, Any]]) -> str:
    return " & ".join(
        f"{condition['feature']} {condition['operator']} "
        f"{float(condition['threshold']):.12g}"
        for condition in conditions
    )


def _reject_outcome_columns(frame: pd.DataFrame) -> None:
    prohibited = sorted(
        str(column)
        for column in frame
        if any(
            token in str(column).lower()
            for token in PROHIBITED_OUTCOME_TOKENS
        )
    )
    if prohibited:
        raise ValueError(f"outcome columns are prohibited: {prohibited}")


def _dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="raise").dt.normalize()


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
