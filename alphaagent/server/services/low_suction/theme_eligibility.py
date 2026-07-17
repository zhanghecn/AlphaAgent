"""Point-in-time membership-dynamics features for concept eligibility."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import numpy as np
import pandas as pd

REQUIRED_MEMBERSHIP_COLUMNS = ("trade_date", "sector_id", "vt_symbol")
REQUIRED_SCOPE_COLUMNS = ("trade_date", "sector_id", "complete")


def build_theme_features(
    memberships: pd.DataFrame,
    scopes: pd.DataFrame,
    *,
    board_types: Mapping[str, str],
    cutoff: date,
    lookback_sessions: int = 20,
    min_complete_sessions: int = 20,
) -> pd.DataFrame:
    """Build one no-lookahead feature row per scoped board at a cutoff."""

    if lookback_sessions < 2:
        raise ValueError("lookback_sessions must be at least two")
    if not 1 <= min_complete_sessions <= lookback_sessions:
        raise ValueError("min_complete_sessions must fit inside lookback_sessions")
    members = _normalized_frame(memberships, REQUIRED_MEMBERSHIP_COLUMNS)
    scope_frame = _normalized_frame(scopes, REQUIRED_SCOPE_COLUMNS)
    cutoff_value = pd.Timestamp(cutoff).normalize()
    members = members.loc[members["trade_date"] <= cutoff_value].copy()
    scope_frame = scope_frame.loc[scope_frame["trade_date"] <= cutoff_value].copy()
    if members.duplicated(REQUIRED_MEMBERSHIP_COLUMNS).any():
        raise ValueError("daily membership rows must be unique")
    if scope_frame.duplicated(("trade_date", "sector_id")).any():
        raise ValueError("daily membership scope rows must be unique")
    scope_frame["complete"] = scope_frame["complete"].fillna(False).astype(bool)

    member_sets = {
        (str(sector_id), pd.Timestamp(trade_date).normalize()): set(
            group["vt_symbol"].astype(str)
        )
        for (sector_id, trade_date), group in members.groupby(
            ["sector_id", "trade_date"],
            sort=False,
        )
    }
    rows = [
        _sector_features(
            str(sector_id),
            group.tail(lookback_sessions),
            member_sets=member_sets,
            board_type=str(board_types.get(str(sector_id)) or "unknown"),
            cutoff=cutoff_value,
            min_complete_sessions=min_complete_sessions,
        )
        for sector_id, group in scope_frame.sort_values("trade_date").groupby(
            "sector_id",
            sort=True,
        )
    ]
    if not rows:
        return pd.DataFrame(columns=["sector_id"]).set_index("sector_id")
    return pd.DataFrame(rows).set_index("sector_id").sort_index()


def _sector_features(
    sector_id: str,
    scopes: pd.DataFrame,
    *,
    member_sets: Mapping[tuple[str, pd.Timestamp], set[str]],
    board_type: str,
    cutoff: pd.Timestamp,
    min_complete_sessions: int,
) -> dict[str, object]:
    complete_flags = scopes["complete"].tolist()
    dates = [pd.Timestamp(value).normalize() for value in scopes["trade_date"]]
    complete_sessions = sum(complete_flags)
    scope_coverage = round(complete_sessions / len(scopes), 4) if len(scopes) else 0.0
    sets = [member_sets.get((sector_id, trade_date), set()) for trade_date in dates]
    pair_metrics = [
        _set_pair_metrics(sets[index - 1], sets[index])
        for index in range(1, len(sets))
        if complete_flags[index - 1] and complete_flags[index]
    ]
    counts = [
        len(values)
        for values, complete in zip(sets, complete_flags, strict=True)
        if complete
    ]
    ready = complete_sessions >= min_complete_sessions
    status = "ready" if ready else "insufficient_history"
    if board_type != "概念板块":
        status = "non_concept"
    jaccards = [metric[0] for metric in pair_metrics]
    replacement_rates = [metric[1] for metric in pair_metrics]
    mean_count = float(np.mean(counts)) if counts else 0.0
    return {
        "sector_id": sector_id,
        "cutoff": cutoff,
        "board_type": board_type,
        "status": status,
        "observed_sessions": int(len(scopes)),
        "active_sessions": int(complete_sessions),
        "scope_coverage": scope_coverage,
        "median_jaccard": _median(jaccards),
        "p10_jaccard": _quantile(jaccards, 0.1),
        "median_replacement_rate": _median(replacement_rates),
        "median_member_count": _median(counts),
        "member_count_cv": (
            round(float(np.std(counts, ddof=0) / mean_count), 6)
            if counts and mean_count
            else 0.0
        ),
    }


def _set_pair_metrics(previous: set[str], current: set[str]) -> tuple[float, float]:
    union = previous | current
    if not union:
        return 1.0, 0.0
    return (
        round(len(previous & current) / len(union), 6),
        round(len(previous ^ current) / len(union), 6),
    )


def _normalized_frame(frame: pd.DataFrame, required: tuple[str, ...]) -> pd.DataFrame:
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"missing theme eligibility columns: {', '.join(missing)}")
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"],
        errors="raise",
    ).dt.normalize()
    return result


def _median(values: list[float] | list[int]) -> float | None:
    return round(float(np.median(values)), 6) if values else None


def _quantile(values: list[float], quantile: float) -> float | None:
    return round(float(np.quantile(values, quantile)), 6) if values else None
