"""Strict point-in-time, return-independent Top3 identity research for V2."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .research_protocol import ProtocolSplit
from .universe import SecurityRecord, eligibility_reason

SHANGHAI = ZoneInfo("Asia/Shanghai")
OPEN_EVIDENCE_CUTOFF = time(9, 25)
IDENTITY_COLUMNS = ("trade_date", "sector_id", "vt_symbol")
RANK_FEATURE_COLUMNS = (
    "cycle_relative_return",
    "strong_day_count_cycle",
    "sessions_since_strong",
    "turnover_median_20d",
)
PROHIBITED_OUTCOME_COLUMNS = frozenset(
    {
        "net_return_pct",
        "net_log_return",
        "mfe_pct",
        "mae_pct",
        "entry_price",
        "exit_price",
    }
)
PROHIBITED_OUTCOME_PREFIXES = ("future_", "outcome_", "d1_", "d3_", "d5_")


class LeaderIdentityMode(StrEnum):
    CYCLE_RELATIVE_STRENGTH = "cycle_relative_strength"
    MARKET_RECOGNITION = "market_recognition_lexicographic"
    RECOGNITION_CONSENSUS = "recognition_consensus"


@dataclass(frozen=True)
class LeaderIdentitySelectionResult:
    status: str
    selected_mode: str | None
    fold_winners: tuple[str | None, ...]
    win_counts: tuple[tuple[str, int], ...]
    fold_metrics: pd.DataFrame
    discovery_metrics: pd.DataFrame


def rank_leader_identities(
    features: pd.DataFrame,
    *,
    mode: LeaderIdentityMode | str,
) -> pd.DataFrame:
    selected_mode = LeaderIdentityMode(mode)
    frame = _validated_features(features)
    frame["excluded_reason"] = (
        frame.apply(_security_exclusion_reason, axis=1)
        if not frame.empty
        else pd.Series(index=frame.index, dtype=object)
    )
    result = rank_prevalidated_leader_identities(
        frame,
        mode=selected_mode,
        session_column="trade_date",
    )
    return result.drop(
        columns=[
            "_cutoff_utc",
            "_feature_cutoff_utc",
            "_membership_known_at_utc",
            "_security_known_at_utc",
        ]
    )


def rank_prevalidated_leader_identities(
    features: pd.DataFrame,
    *,
    mode: LeaderIdentityMode | str,
    session_column: str,
) -> pd.DataFrame:
    """Rank a frame whose point-in-time source contract was validated upstream."""

    selected_mode = LeaderIdentityMode(mode)
    session_key = str(session_column).strip()
    required = {
        session_key,
        "sector_id",
        "vt_symbol",
        *RANK_FEATURE_COLUMNS,
        "capacity_passed",
        "excluded_reason",
    }
    missing = sorted(required - set(features))
    if missing:
        raise ValueError(
            "missing prevalidated leader columns: " + ", ".join(missing)
        )
    _reject_low_suction_outcomes(features)

    frame = features.copy()
    frame[session_key] = pd.to_datetime(
        frame[session_key],
        errors="raise",
    ).dt.date
    rank_identity = [session_key, "sector_id", "vt_symbol"]
    if frame.duplicated(rank_identity).any():
        raise ValueError("prevalidated leader identity must be unique")
    frame[list(RANK_FEATURE_COLUMNS)] = frame[list(RANK_FEATURE_COLUMNS)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    eligible = frame["excluded_reason"].isna()
    if frame.loc[eligible, list(RANK_FEATURE_COLUMNS)].isna().any().any():
        raise ValueError("eligible leader rank features must be complete numeric values")
    if frame.loc[eligible, "capacity_passed"].isna().any():
        raise ValueError("eligible leader capacity evidence must be complete")
    if frame.empty:
        return _empty_rank_result(frame, selected_mode)

    frame["rank_eligible"] = eligible
    eligible = frame.loc[frame["rank_eligible"]].copy()
    relative = _relative_strength_order(eligible, session_key)
    recognition = _market_recognition_order(eligible, session_key)

    frame = frame.merge(
        relative[rank_identity + ["relative_strength_rank"]],
        on=rank_identity,
        how="left",
        validate="one_to_one",
    ).merge(
        recognition[rank_identity + ["market_recognition_rank"]],
        on=rank_identity,
        how="left",
        validate="one_to_one",
    )
    selected = _selected_order(frame, selected_mode, session_key)
    selected["rank"] = (
        selected.groupby([session_key, "sector_id"], sort=False).cumcount() + 1
    )

    ranks = selected[rank_identity + ["rank"]]
    frame = frame.drop(columns=["rank_eligible"]).merge(
        ranks,
        on=rank_identity,
        how="left",
        validate="one_to_one",
    )
    if selected_mode == LeaderIdentityMode.RECOGNITION_CONSENSUS:
        outside_consensus = (
            frame["excluded_reason"].isna() & frame["rank"].isna()
        )
        frame.loc[outside_consensus, "excluded_reason"] = (
            "outside_recognition_consensus"
        )
    frame["rank_eligible"] = frame["rank"].notna()
    frame["rank"] = pd.array(frame["rank"], dtype="Int64")
    frame["is_top3"] = frame["rank"].le(3).fillna(False)
    frame["identity_mode"] = selected_mode.value
    return frame.sort_values(
        [session_key, "sector_id", "rank_eligible", "rank", "vt_symbol"],
        ascending=[True, True, False, True, True],
        na_position="last",
        kind="stable",
        ignore_index=True,
    )


def evaluate_leader_identity(
    ranks: pd.DataFrame,
    *,
    outcomes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    required = {
        "trade_date",
        "calendar_position",
        "sector_id",
        "vt_symbol",
        "identity_mode",
        "is_top3",
        "capacity_passed",
    }
    missing = sorted(required - set(ranks))
    if missing:
        raise ValueError(f"missing leader evaluation columns: {', '.join(missing)}")
    frame = ranks.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    top3 = frame.loc[frame["is_top3"]].copy()
    top3 = _add_next_day_retention(top3, frame)
    top3["sessions_to_next_strong_event"] = np.nan
    if outcomes is not None:
        _reject_low_suction_outcomes(outcomes)
        outcome_columns = [
            "trade_date",
            "sector_id",
            "vt_symbol",
            "sessions_to_next_strong_event",
        ]
        missing_outcomes = [column for column in outcome_columns if column not in outcomes]
        if missing_outcomes:
            raise ValueError(
                "missing leader outcome columns: " + ", ".join(missing_outcomes)
            )
        outcome_frame = outcomes[outcome_columns].copy()
        outcome_frame["trade_date"] = pd.to_datetime(
            outcome_frame["trade_date"],
            errors="raise",
        ).dt.date
        if outcome_frame.duplicated(list(IDENTITY_COLUMNS)).any():
            raise ValueError("leader outcome identity must be unique")
        top3 = top3.drop(columns=["sessions_to_next_strong_event"]).merge(
            outcome_frame,
            on=list(IDENTITY_COLUMNS),
            how="left",
            validate="many_to_one",
        )

    rows = []
    for identity_mode, group in top3.groupby("identity_mode", sort=True):
        lead = pd.to_numeric(
            group["sessions_to_next_strong_event"],
            errors="coerce",
        ).dropna()
        retention = pd.to_numeric(
            group["retained_top3_next_day"],
            errors="coerce",
        ).dropna()
        rows.append(
            {
                "identity_mode": str(identity_mode),
                "ranked_days": int(group["trade_date"].nunique()),
                "ranked_concept_days": int(
                    group[["trade_date", "sector_id"]].drop_duplicates().shape[0]
                ),
                "top3_observations": int(len(group)),
                "eligible_retention_observations": int(len(retention)),
                "next_day_top3_retention": (
                    float(retention.mean()) if not retention.empty else np.nan
                ),
                "strong_event_lead_sessions": (
                    float(lead.median()) if not lead.empty else np.nan
                ),
                "capacity_pass_rate": float(group["capacity_passed"].astype(bool).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("identity_mode", kind="stable").reset_index(drop=True)


def choose_stable_leader_identity(
    fold_winners: Sequence[str | LeaderIdentityMode | None],
    *,
    minimum_wins: int = 3,
) -> LeaderIdentityMode | None:
    if minimum_wins < 1:
        raise ValueError("minimum_wins must be positive")
    counts = Counter(str(winner) for winner in fold_winners if winner is not None)
    eligible = [mode for mode, count in counts.items() if count >= minimum_wins]
    if len(eligible) != 1:
        return None
    return LeaderIdentityMode(eligible[0])


def select_leader_identity(
    ranks: pd.DataFrame,
    outcomes: pd.DataFrame,
    split: ProtocolSplit,
) -> LeaderIdentitySelectionResult:
    rank_dates = set(pd.to_datetime(ranks["trade_date"]).dt.date)
    if rank_dates & set(split.holdout_dates):
        raise ValueError("locked holdout values must not be loaded during leader selection")

    fold_metrics = []
    fold_winners: list[str | None] = []
    for fold_number, fold in enumerate(split.rolling_folds, start=1):
        fold_dates = set(fold.validation_dates)
        metrics = evaluate_leader_identity(
            ranks.loc[pd.to_datetime(ranks["trade_date"]).dt.date.isin(fold_dates)],
            outcomes=outcomes.loc[
                pd.to_datetime(outcomes["trade_date"]).dt.date.isin(fold_dates)
            ],
        )
        winner = _winning_identity_mode(metrics)
        fold_winners.append(winner)
        fold_metrics.append(
            metrics.assign(
                fold=fold_number,
                fold_winner=metrics["identity_mode"].eq(winner),
            )
        )

    selected = choose_stable_leader_identity(fold_winners)
    counts = Counter(winner for winner in fold_winners if winner is not None)
    discovery_dates = set(split.discovery_dates)
    return LeaderIdentitySelectionResult(
        status=(
            "selected_top3_identity"
            if selected is not None
            else "no_stable_top3_identity"
        ),
        selected_mode=selected.value if selected is not None else None,
        fold_winners=tuple(fold_winners),
        win_counts=tuple(sorted((str(key), value) for key, value in counts.items())),
        fold_metrics=pd.concat(fold_metrics, ignore_index=True),
        discovery_metrics=evaluate_leader_identity(
            ranks.loc[pd.to_datetime(ranks["trade_date"]).dt.date.isin(discovery_dates)],
            outcomes=outcomes.loc[
                pd.to_datetime(outcomes["trade_date"]).dt.date.isin(discovery_dates)
            ],
        ),
    )


def _validated_features(features: pd.DataFrame) -> pd.DataFrame:
    required = {
        *IDENTITY_COLUMNS,
        *RANK_FEATURE_COLUMNS,
        "calendar_position",
        "symbol",
        "exchange",
        "cutoff",
        "feature_cutoff",
        "membership_known_at",
        "membership_source_trade_date",
        "membership_evidence_level",
        "membership_scope_complete",
        "security_known_at",
        "security_evidence_level",
        "name",
        "status",
        "listed_sessions",
        "suspended",
        "risk_warning",
        "delisted",
        "capacity_passed",
    }
    missing = sorted(required - set(features))
    if missing:
        raise ValueError(f"missing leader identity columns: {', '.join(missing)}")
    _reject_low_suction_outcomes(features)

    frame = features.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    if frame.duplicated(list(IDENTITY_COLUMNS)).any():
        raise ValueError("leader feature identity must be unique")
    for source, target in (
        ("cutoff", "_cutoff_utc"),
        ("feature_cutoff", "_feature_cutoff_utc"),
        ("membership_known_at", "_membership_known_at_utc"),
        ("security_known_at", "_security_known_at_utc"),
    ):
        frame[target] = frame[source].map(_aware_utc_timestamp)
    _validate_point_in_time_contract(frame)

    numeric_columns = [*RANK_FEATURE_COLUMNS, "calendar_position", "listed_sessions"]
    frame[numeric_columns] = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if frame[numeric_columns].isna().any().any():
        raise ValueError("leader rank features must be complete numeric values")
    return frame


def _validate_point_in_time_contract(frame: pd.DataFrame) -> None:
    local_cutoffs = frame["_cutoff_utc"].dt.tz_convert(SHANGHAI)
    if any(
        cutoff.date() != trade_date or cutoff.time() > OPEN_EVIDENCE_CUTOFF
        for cutoff, trade_date in zip(local_cutoffs, frame["trade_date"], strict=True)
    ):
        raise ValueError("leader cutoff must be no later than D 09:25")
    if (frame["_feature_cutoff_utc"] > frame["_cutoff_utc"]).any():
        raise ValueError("leader feature timestamp is after cutoff")
    if not frame["membership_evidence_level"].eq("strict").all():
        raise ValueError("strict membership evidence is required for V2 identity")
    if not frame["membership_scope_complete"].eq(True).all():
        raise ValueError("strict membership scope must be complete")
    if (frame["_membership_known_at_utc"] > frame["_cutoff_utc"]).any():
        raise ValueError("membership known_at is after D 09:25")
    source_dates = pd.to_datetime(
        frame["membership_source_trade_date"],
        errors="raise",
    ).dt.date
    if any(source >= trade for source, trade in zip(source_dates, frame["trade_date"], strict=True)):
        raise ValueError("membership source date must be before the ranked trade date")
    if not frame["security_evidence_level"].eq("strict").all():
        raise ValueError("strict security evidence is required for V2 identity")
    if (frame["_security_known_at_utc"] > frame["_cutoff_utc"]).any():
        raise ValueError("security known_at is after D 09:25")


def _security_exclusion_reason(row: pd.Series) -> str | None:
    return eligibility_reason(
        SecurityRecord(
            vt_symbol=str(row["vt_symbol"]),
            symbol=str(row["symbol"]),
            exchange=str(row["exchange"]),
            name=str(row["name"]),
            status=str(row["status"]),
            listed_sessions=int(row["listed_sessions"]),
            suspended=bool(row["suspended"]),
            risk_warning=bool(row["risk_warning"]),
            delisted=bool(row["delisted"]),
            evidence_level=str(row["security_evidence_level"]),
        ),
        row["trade_date"],
    )


def _relative_strength_order(
    frame: pd.DataFrame,
    session_column: str,
) -> pd.DataFrame:
    ordered = frame.sort_values(
        [
            session_column,
            "sector_id",
            "cycle_relative_return",
            "capacity_passed",
            "turnover_median_20d",
            "vt_symbol",
        ],
        ascending=[True, True, False, False, False, True],
        kind="stable",
    ).copy()
    ordered["relative_strength_rank"] = (
        ordered.groupby([session_column, "sector_id"], sort=False).cumcount() + 1
    )
    return ordered


def _market_recognition_order(
    frame: pd.DataFrame,
    session_column: str,
) -> pd.DataFrame:
    ordered = frame.sort_values(
        [
            session_column,
            "sector_id",
            "strong_day_count_cycle",
            "sessions_since_strong",
            "cycle_relative_return",
            "capacity_passed",
            "turnover_median_20d",
            "vt_symbol",
        ],
        ascending=[True, True, False, True, False, False, False, True],
        kind="stable",
    ).copy()
    ordered["market_recognition_rank"] = (
        ordered.groupby([session_column, "sector_id"], sort=False).cumcount() + 1
    )
    return ordered


def _selected_order(
    frame: pd.DataFrame,
    mode: LeaderIdentityMode,
    session_column: str,
) -> pd.DataFrame:
    eligible = frame.loc[frame["excluded_reason"].isna()].copy()
    if mode == LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH:
        return eligible.sort_values(
            [session_column, "sector_id", "relative_strength_rank"],
            kind="stable",
        )
    if mode == LeaderIdentityMode.MARKET_RECOGNITION:
        return eligible.sort_values(
            [session_column, "sector_id", "market_recognition_rank"],
            kind="stable",
        )
    consensus = eligible.loc[
        eligible["relative_strength_rank"].le(5)
        & eligible["market_recognition_rank"].le(5)
    ]
    return consensus.sort_values(
        [session_column, "sector_id", "market_recognition_rank"],
        kind="stable",
    )


def _add_next_day_retention(top3: pd.DataFrame, ranks: pd.DataFrame) -> pd.DataFrame:
    group_keys = ["identity_mode", "sector_id", "calendar_position"]
    availability = ranks[group_keys].drop_duplicates().copy()
    availability["calendar_position"] -= 1
    availability["next_group_available"] = True
    retained = top3[
        ["identity_mode", "sector_id", "calendar_position", "vt_symbol"]
    ].copy()
    retained["calendar_position"] -= 1
    retained["retained_top3_next_day"] = True
    result = top3.merge(
        availability,
        on=group_keys,
        how="left",
        validate="many_to_one",
    ).merge(
        retained,
        on=[*group_keys, "vt_symbol"],
        how="left",
        validate="one_to_one",
    )
    result["retained_top3_next_day"] = np.where(
        result["next_group_available"].eq(True),
        result["retained_top3_next_day"].eq(True),
        np.nan,
    )
    return result.drop(columns=["next_group_available"])


def _winning_identity_mode(metrics: pd.DataFrame) -> str | None:
    eligible = metrics.dropna(subset=["next_day_top3_retention"]).copy()
    if eligible.empty:
        return None
    ranked = eligible.sort_values(
        [
            "next_day_top3_retention",
            "strong_event_lead_sessions",
            "capacity_pass_rate",
            "identity_mode",
        ],
        ascending=[False, True, False, True],
        na_position="last",
        kind="stable",
    )
    return str(ranked.iloc[0]["identity_mode"])


def _reject_low_suction_outcomes(frame: pd.DataFrame) -> None:
    prohibited = [
        str(column)
        for column in frame.columns
        if str(column) in PROHIBITED_OUTCOME_COLUMNS
        or str(column).lower().startswith(PROHIBITED_OUTCOME_PREFIXES)
    ]
    if prohibited:
        raise ValueError(f"low-suction outcomes are not allowed: {sorted(prohibited)}")


def _aware_utc_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("leader evidence timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _empty_rank_result(
    frame: pd.DataFrame,
    mode: LeaderIdentityMode,
) -> pd.DataFrame:
    result = frame.copy()
    result["relative_strength_rank"] = pd.Series(dtype="Int64")
    result["market_recognition_rank"] = pd.Series(dtype="Int64")
    result["rank"] = pd.Series(dtype="Int64")
    result["is_top3"] = pd.Series(dtype=bool)
    result["rank_eligible"] = pd.Series(dtype=bool)
    result["excluded_reason"] = pd.Series(dtype=object)
    result["identity_mode"] = mode.value
    return result
