"""Auditable event-reason to concept-index relations."""

from __future__ import annotations

import re

import pandas as pd


EVENT_COLUMNS = (
    "event_id",
    "source_date",
    "vt_symbol",
    "stock_name",
    "reason",
)
CONCEPT_COLUMNS = ("sector_id", "concept_name")
RELATION_COLUMNS = (
    "event_id",
    "source_date",
    "vt_symbol",
    "stock_name",
    "reason",
    "reason_token",
    "sector_id",
    "concept_name",
    "relation_method",
)
_TRAILING_SUFFIX = re.compile(r"(?:概念|龙头|板块)$")


def normalize_reason_name(value: object) -> str:
    """Normalize spacing/case and one explicit descriptive suffix."""

    compact = re.sub(r"\s+", "", str(value or "")).casefold()
    return _TRAILING_SUFFIX.sub("", compact, count=1)


def build_normalized_reason_relations(
    events: pd.DataFrame,
    concepts: pd.DataFrame,
) -> pd.DataFrame:
    """Map reason tokens by exact or suffix-normalized name equality."""

    _require_columns(events, EVENT_COLUMNS, "event")
    _require_columns(concepts, CONCEPT_COLUMNS, "concept")
    concept_frame = concepts.loc[:, list(CONCEPT_COLUMNS)].copy()
    concept_frame["sector_id"] = concept_frame["sector_id"].astype(str).str.strip()
    concept_frame["concept_name"] = concept_frame["concept_name"].astype(str).str.strip()
    if concept_frame[["sector_id", "concept_name"]].eq("").any(axis=None):
        raise ValueError("concept identity must not be empty")
    if concept_frame["sector_id"].duplicated().any():
        raise ValueError("concept sector IDs must be unique")
    if concept_frame["concept_name"].duplicated().any():
        raise ValueError("concept names must be unique")
    concept_frame["exact_key"] = concept_frame["concept_name"].str.casefold()
    concept_frame["normalized_key"] = concept_frame["concept_name"].map(
        normalize_reason_name
    )
    if concept_frame["normalized_key"].eq("").any():
        raise ValueError("normalized concept name must not be empty")
    if concept_frame["normalized_key"].duplicated().any():
        raise ValueError("ambiguous normalized concept name")

    frame = events.loc[:, list(EVENT_COLUMNS)].copy()
    if frame.empty:
        return pd.DataFrame(columns=list(RELATION_COLUMNS))
    frame["source_date"] = pd.to_datetime(
        frame["source_date"], errors="raise"
    ).dt.normalize()
    for column in ("vt_symbol", "stock_name", "reason"):
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    if frame[["vt_symbol", "reason"]].eq("").any(axis=None):
        raise ValueError("event symbol and reason must not be empty")
    frame["reason_token"] = frame["reason"].str.split("+", regex=False)
    frame = frame.explode("reason_token", ignore_index=True)
    frame["reason_token"] = frame["reason_token"].fillna("").astype(str).str.strip()
    frame = frame.loc[frame["reason_token"].ne("")].copy()
    frame["exact_key"] = frame["reason_token"].str.casefold()
    frame["normalized_key"] = frame["reason_token"].map(normalize_reason_name)

    exact = frame.merge(
        concept_frame,
        on="exact_key",
        how="inner",
        validate="many_to_one",
        suffixes=("", "_concept"),
    ).assign(relation_method="exact", relation_priority=0)
    normalized = frame.merge(
        concept_frame,
        on="normalized_key",
        how="inner",
        validate="many_to_one",
        suffixes=("", "_concept"),
    )
    normalized = normalized.loc[
        normalized["exact_key"] != normalized["exact_key_concept"]
    ].assign(relation_method="normalized_suffix_exact", relation_priority=1)
    result = pd.concat([exact, normalized], ignore_index=True)
    if result.empty:
        return pd.DataFrame(columns=list(RELATION_COLUMNS))
    result = result.sort_values(
        [
            "source_date",
            "sector_id",
            "vt_symbol",
            "relation_priority",
            "event_id",
            "reason_token",
        ],
        kind="stable",
    ).drop_duplicates(["source_date", "sector_id", "vt_symbol"], keep="first")
    return result.loc[:, list(RELATION_COLUMNS)].reset_index(drop=True)


def _require_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
