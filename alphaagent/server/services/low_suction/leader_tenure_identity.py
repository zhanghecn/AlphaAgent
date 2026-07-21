"""Causal persistent leader identity for low-suction campaign research."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


TENURE_GRACE_SESSIONS = 3
PROHIBITED_IDENTITY_TOKENS = (
    "d1_",
    "future_",
    "gross_return",
    "net_return",
    "outcome",
    "realized_",
    "exit_date",
    "exit_price",
    "mfe",
    "mae",
    "profit",
)
TENURE_IDENTITY_COLUMNS = ("campaign_id", "vt_symbol", "trade_date")
PRIMARY_EVENT_ORDER = (
    "tenure_top3_days",
    "tenure_best_rank",
    "current_dynamic_top3",
    "concept_gain_pct",
    "concept_excess_gain_pct",
    "turnover_expansion",
    "sector_id",
    "campaign_id",
)


def build_causal_leader_tenures(paths: pd.DataFrame) -> pd.DataFrame:
    """Extend a valid Top3 identity through one fixed three-session grace."""

    _reject_outcome_columns(paths, "leader tenure path")
    required = (
        *TENURE_IDENTITY_COLUMNS,
        "sector_id",
        "concept_name",
        "stock_name",
        "dynamic_rank",
        "dynamic_top3",
        "campaign_active",
        "structure_intact",
        "concept_gain_pct",
        "concept_excess_gain_pct",
        "turnover_expansion",
        "feature_cutoff_date",
    )
    _require_columns(paths, required, "leader tenure path")
    frame = paths.copy()
    frame["campaign_id"] = frame["campaign_id"].astype(str)
    frame["sector_id"] = frame["sector_id"].astype(str)
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    for column in ("trade_date", "feature_cutoff_date"):
        frame[column] = _dates(frame[column])
    if frame.duplicated(list(TENURE_IDENTITY_COLUMNS)).any():
        raise ValueError("leader tenure path identities must be unique")
    if not frame["feature_cutoff_date"].eq(frame["trade_date"]).all():
        raise ValueError("leader tenure cutoff must equal its completed trade date")

    frame = frame.sort_values(
        ["campaign_id", "vt_symbol", "trade_date"], kind="stable"
    ).reset_index(drop=True)
    frame["current_dynamic_rank"] = pd.to_numeric(
        frame["dynamic_rank"], errors="coerce"
    ).astype("Int64")
    frame["current_dynamic_top3"] = (
        frame["dynamic_top3"].fillna(False).astype(bool)
    )
    frame["campaign_active"] = frame["campaign_active"].fillna(False).astype(bool)
    frame["structure_intact"] = frame["structure_intact"].fillna(False).astype(bool)

    valid = frame["campaign_active"] & frame["structure_intact"]
    current_top3 = (
        valid
        & frame["current_dynamic_top3"]
        & frame["current_dynamic_rank"].between(1, 3).fillna(False)
    )
    identity_keys = [frame["campaign_id"], frame["vt_symbol"]]
    invalid_epoch = (~valid).astype(int).groupby(identity_keys, sort=False).cumsum()
    epoch_keys = [frame["campaign_id"], frame["vt_symbol"], invalid_epoch]
    epoch_position = frame.groupby(
        ["campaign_id", "vt_symbol", invalid_epoch], sort=False
    ).cumcount()
    last_top3_position = epoch_position.where(current_top3).groupby(
        epoch_keys, sort=False
    ).ffill()
    sessions_since_top3 = epoch_position - last_top3_position
    tenure_rank = frame["current_dynamic_rank"].where(current_top3).groupby(
        epoch_keys, sort=False
    ).ffill()
    tenure_best_rank = frame["current_dynamic_rank"].where(current_top3).groupby(
        epoch_keys, sort=False
    ).cummin()
    tenure_best_rank = tenure_best_rank.groupby(epoch_keys, sort=False).ffill()
    tenure_top3_days = current_top3.astype(int).groupby(
        epoch_keys, sort=False
    ).cumsum()
    active = (
        valid
        & last_top3_position.notna()
        & sessions_since_top3.le(TENURE_GRACE_SESSIONS)
    )

    frame["sessions_since_top3"] = sessions_since_top3.astype("Int64")
    frame["tenure_rank"] = tenure_rank.astype("Int64")
    frame["tenure_best_rank"] = tenure_best_rank.astype("Int64")
    frame["tenure_top3_days"] = tenure_top3_days.astype(int)
    frame["leader_tenure_active"] = active.astype(bool)
    previous_active = active.groupby(identity_keys, sort=False).shift(
        1, fill_value=False
    )
    frame["tenure_established_today"] = active & ~previous_active
    frame["tenure_expired_today"] = ~active & previous_active
    frame["tenure_end_reason"] = _tenure_end_reasons(
        frame,
        frame["tenure_expired_today"],
        sessions_since_top3,
    )
    start_date = frame["trade_date"].where(frame["tenure_established_today"])
    start_date = start_date.groupby(identity_keys, sort=False).ffill().where(active)
    frame["leader_tenure_id"] = (
        frame["campaign_id"]
        + ":"
        + frame["vt_symbol"]
        + ":"
        + start_date.dt.strftime("%Y-%m-%d").fillna("")
    ).where(active)

    breadth_keys = [frame["vt_symbol"], frame["trade_date"]]
    frame["active_tenure_concepts"] = active.astype(int).groupby(
        breadth_keys, sort=False
    ).transform("sum")
    frame["current_top3_concepts"] = current_top3.astype(int).groupby(
        breadth_keys, sort=False
    ).transform("sum")
    frame["maximum_top3_days"] = frame["tenure_top3_days"].groupby(
        breadth_keys, sort=False
    ).transform("max")

    frame["dynamic_rank"] = frame["current_dynamic_rank"].where(
        ~active, frame["tenure_rank"]
    ).astype("Int64")
    frame["dynamic_top3"] = active.astype(bool)
    return frame


def select_primary_concept_events(
    events: pd.DataFrame,
    tenure_paths: pd.DataFrame,
    *,
    date_column: str = "signal_date",
) -> pd.DataFrame:
    """Retain one causally strongest concept for each stock/event date."""

    _reject_outcome_columns(events, "primary concept event")
    _reject_outcome_columns(tenure_paths, "primary concept tenure path")
    event_required = (
        "signal_id",
        "campaign_id",
        "sector_id",
        "vt_symbol",
        date_column,
    )
    evidence_columns = (
        "campaign_id",
        "sector_id",
        "vt_symbol",
        "trade_date",
        "leader_tenure_id",
        "leader_tenure_active",
        "sessions_since_top3",
        "tenure_rank",
        "tenure_best_rank",
        "tenure_top3_days",
        "current_dynamic_rank",
        "current_dynamic_top3",
        "active_tenure_concepts",
        "current_top3_concepts",
        "maximum_top3_days",
        "concept_gain_pct",
        "concept_excess_gain_pct",
        "turnover_expansion",
    )
    _require_columns(events, event_required, "primary concept event")
    _require_columns(
        tenure_paths, evidence_columns, "primary concept tenure path"
    )
    if events.empty:
        return events.copy()

    event_frame = events.copy()
    event_frame[date_column] = _dates(event_frame[date_column])
    event_frame["campaign_id"] = event_frame["campaign_id"].astype(str)
    event_frame["sector_id"] = event_frame["sector_id"].astype(str)
    event_frame["vt_symbol"] = event_frame["vt_symbol"].astype(str)
    evidence = tenure_paths.loc[:, list(evidence_columns)].copy()
    evidence["trade_date"] = _dates(evidence["trade_date"])
    evidence = evidence.rename(columns={"trade_date": date_column})
    join_keys = ["campaign_id", "sector_id", "vt_symbol", date_column]
    if evidence.duplicated(join_keys).any():
        raise ValueError("primary concept tenure identities must be unique")

    added_columns = [column for column in evidence if column not in join_keys]
    event_frame = event_frame.drop(
        columns=[column for column in added_columns if column in event_frame],
        errors="ignore",
    )
    joined = event_frame.merge(
        evidence,
        on=join_keys,
        how="left",
        validate="many_to_one",
        sort=False,
    )
    if joined["leader_tenure_active"].isna().any():
        raise ValueError("primary concept event is missing tenure evidence")
    if not joined["leader_tenure_active"].astype(bool).all():
        raise ValueError("primary concept event requires an active leader tenure")

    duplicate_keys = ["vt_symbol", date_column]
    joined["duplicate_concept_count"] = joined.groupby(
        duplicate_keys, sort=False
    )["sector_id"].transform("nunique")
    joined["primary_concept_selected"] = True
    ordered = joined.sort_values(
        [*duplicate_keys, *PRIMARY_EVENT_ORDER, "signal_id"],
        ascending=[
            True,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
            True,
            True,
        ],
        na_position="last",
        kind="stable",
    )
    selected = ordered.drop_duplicates(duplicate_keys, keep="first")
    return selected.sort_values(
        [date_column, "vt_symbol", "signal_id"], kind="stable"
    ).reset_index(drop=True)


def _tenure_end_reasons(
    frame: pd.DataFrame,
    expired: pd.Series,
    sessions_since_top3: pd.Series,
) -> pd.Series:
    reasons = np.select(
        (
            expired & ~frame["campaign_active"],
            expired & ~frame["structure_intact"],
            expired & sessions_since_top3.gt(TENURE_GRACE_SESSIONS),
        ),
        ("campaign_active", "structure_intact", "rank_grace_expired"),
        default=None,
    )
    return pd.Series(reasons, index=frame.index, dtype=object)


def _reject_outcome_columns(frame: pd.DataFrame, label: str) -> None:
    prohibited = sorted(
        str(column)
        for column in frame
        if any(
            token in str(column).lower()
            for token in PROHIBITED_IDENTITY_TOKENS
        )
    )
    if prohibited:
        raise ValueError(f"{label} outcome columns are prohibited: {prohibited}")


def _dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="raise").dt.normalize()


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")
