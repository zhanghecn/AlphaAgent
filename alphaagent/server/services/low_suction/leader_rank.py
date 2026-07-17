"""Fixed-weight point-in-time Top3 ranking within each concept."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

RANK_BLOCK_WEIGHTS = {
    "relative_strength_score": 0.2,
    "active_gene_score": 0.2,
    "resilience_score": 0.2,
    "liquidity_score": 0.2,
    "concept_leadership_score": 0.2,
}

BLOCK_FACTORS = {
    "relative_strength_score": (
        ("relative_strength_5d", 1.0),
        ("relative_strength_10d", 1.0),
        ("relative_strength_20d", 1.0),
    ),
    "active_gene_score": (
        ("limit_up_count_20d", 1.0),
        ("strong_day_count_20d", 1.0),
        ("sessions_since_strong", -1.0),
    ),
    "resilience_score": (
        ("max_drawdown_20d_pct", 1.0),
        ("divergence_relative_return", 1.0),
        ("ma10_hold_ratio", 1.0),
    ),
    "liquidity_score": (
        ("turnover_median_20d", 1.0),
        ("turnover_nonzero_ratio", 1.0),
    ),
    "concept_leadership_score": (
        ("concept_correlation_20d", 1.0),
        ("launch_lead_sessions", 1.0),
        ("intraday_lead_ratio", 1.0),
    ),
}

IDENTITY_COLUMNS = ("sector_id", "cutoff", "feature_cutoff", "vt_symbol", "turnover")
PROHIBITED_PREFIXES = ("future_", "outcome_", "mfe_", "mae_", "exit_")
ALLOWED_MEMBERSHIP_MODES = ("strict", "current_proxy", "membership_proxy")


def rank_concept_leaders(
    features: pd.DataFrame,
    *,
    membership_mode: str,
) -> pd.DataFrame:
    """Rank complete rows inside each concept/cutoff without using future fields."""

    _validate_inputs(features, membership_mode)
    if features.empty:
        return _empty_result(features)

    frame = features.copy()
    frame["_cutoff_utc"] = pd.to_datetime(frame["cutoff"], utc=True, errors="raise")
    frame["_feature_cutoff_utc"] = pd.to_datetime(
        frame["feature_cutoff"],
        utc=True,
        errors="raise",
    )
    if (frame["_feature_cutoff_utc"] > frame["_cutoff_utc"]).any():
        raise ValueError("feature timestamp is after cutoff")

    result = _rank_all_groups(frame, membership_mode)
    result = result.drop(columns=["_cutoff_utc", "_feature_cutoff_utc"])
    return result.sort_values(
        ["cutoff", "sector_id", "rank", "vt_symbol"],
        kind="stable",
        na_position="last",
        ignore_index=True,
    )


def _rank_all_groups(frame: pd.DataFrame, membership_mode: str) -> pd.DataFrame:
    ranked = frame.copy()
    numeric_columns = _factor_columns()
    ranked[numeric_columns] = ranked[numeric_columns].apply(
        pd.to_numeric,
        errors="coerce",
    )
    complete = ranked[numeric_columns].notna().all(axis=1)
    ranked["excluded_reason"] = np.where(complete, None, "incomplete_rank_features")

    valid = ranked.loc[complete].copy()
    group_keys = ["sector_id", "_cutoff_utc"]
    for block_name, factors in BLOCK_FACTORS.items():
        percentiles = [
            (valid[column] * direction).groupby(
                [valid[key] for key in group_keys],
                sort=False,
            ).rank(method="average", pct=True, ascending=True)
            for column, direction in factors
        ]
        valid[block_name] = pd.concat(percentiles, axis=1).mean(axis=1)
    valid["leader_score"] = sum(
        valid[block_name] * weight
        for block_name, weight in RANK_BLOCK_WEIGHTS.items()
    )
    valid = valid.sort_values(
        [*group_keys, "leader_score", "turnover", "vt_symbol"],
        ascending=[True, True, False, False, True],
        kind="stable",
    )
    valid["rank"] = valid.groupby(group_keys, sort=False).cumcount() + 1
    valid["is_top3"] = valid["rank"] <= 3

    invalid = ranked.loc[~complete].copy()
    for column in (*RANK_BLOCK_WEIGHTS, "leader_score", "rank"):
        invalid[column] = np.nan
    invalid["is_top3"] = False

    result = pd.concat([valid, invalid], ignore_index=True)
    result["membership_mode"] = membership_mode
    result["evidence_level"] = (
        "strict" if membership_mode == "strict" else "membership_proxy"
    )
    return result


def _factor_columns() -> list[str]:
    return [column for factors in BLOCK_FACTORS.values() for column, _ in factors]


def _validate_inputs(features: pd.DataFrame, membership_mode: str) -> None:
    if membership_mode not in ALLOWED_MEMBERSHIP_MODES:
        raise ValueError(f"unsupported membership mode: {membership_mode}")
    prohibited = [
        column
        for column in features.columns
        if str(column).lower().startswith(PROHIBITED_PREFIXES)
    ]
    if prohibited:
        raise ValueError(f"outcome columns are not allowed in ranking: {prohibited}")

    required: Sequence[str] = (*IDENTITY_COLUMNS, *_factor_columns())
    missing = [column for column in required if column not in features]
    if missing:
        raise ValueError(f"missing required rank columns: {', '.join(missing)}")


def _empty_result(features: pd.DataFrame) -> pd.DataFrame:
    result = features.copy()
    for column in (
        *RANK_BLOCK_WEIGHTS,
        "leader_score",
        "rank",
        "is_top3",
        "excluded_reason",
        "membership_mode",
        "evidence_level",
    ):
        result[column] = pd.Series(dtype=object)
    return result
