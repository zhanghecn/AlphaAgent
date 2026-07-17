"""Outcome-isolated daily discovery events for three low-suction families."""

from __future__ import annotations

import pandas as pd

MAIN_RISE_CONFIRMED = "MAIN_RISE_CONFIRMED"
PROHIBITED_PREFIXES = ("future_", "outcome_", "mfe_", "mae_", "exit_")
REQUIRED_COLUMNS = (
    "sector_id",
    "concept_name",
    "trade_date",
    "cutoff",
    "vt_symbol",
    "rank",
    "is_top3",
    "state",
    "rise_cycle_id",
    "evidence_level",
    "open_price",
    "close_price",
    "previous_close",
    "ma5",
    "ma10",
    "volume_ratio_5d",
    "return_10d_pct",
    "prior_strong_day",
    "sessions_since_peak",
    "drawdown_from_peak_pct",
    "concept_strength_score",
    "leader_score",
)
EVENT_NUMERIC_COLUMNS = (
    "open_price",
    "close_price",
    "previous_close",
    "ma5",
    "ma10",
    "volume_ratio_5d",
    "return_10d_pct",
    "sessions_since_peak",
    "drawdown_from_peak_pct",
    "concept_strength_score",
    "leader_score",
)


def build_daily_discovery_events(features: pd.DataFrame) -> pd.DataFrame:
    """Build first-occurrence events using information available by D close."""

    _validate_features(features)
    if features.empty:
        return _empty_events()

    frame = features.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["cutoff"] = pd.to_datetime(frame["cutoff"], utc=True, errors="raise")
    frame = frame.loc[
        frame["is_top3"].fillna(False).astype(bool)
        & (frame["state"] == MAIN_RISE_CONFIRMED)
        & frame["rise_cycle_id"].notna()
    ].copy()
    if frame.empty:
        return _empty_events()

    frame = attach_daily_event_metrics(frame)
    frame["family_tags"] = frame.apply(classify_daily_family_tags, axis=1)
    candidates = frame.loc[frame["family_tags"].map(bool)].copy()
    if candidates.empty:
        return _empty_events()

    related_concepts = (
        candidates.groupby(["vt_symbol", "cutoff"], sort=False)["sector_id"]
        .agg(lambda values: tuple(sorted(set(map(str, values)))))
        .rename("related_concepts")
        .reset_index()
    )
    candidates = candidates.merge(
        related_concepts,
        on=["vt_symbol", "cutoff"],
        how="left",
        validate="many_to_one",
    )
    candidates = candidates.sort_values(
        [
            "vt_symbol",
            "cutoff",
            "concept_strength_score",
            "leader_score",
            "sector_id",
        ],
        ascending=[True, True, False, False, True],
        kind="stable",
    ).drop_duplicates(["vt_symbol", "cutoff"], keep="first")
    candidates = candidates.sort_values(
        ["vt_symbol", "rise_cycle_id", "cutoff", "sector_id"],
        kind="stable",
    ).drop_duplicates(["vt_symbol", "rise_cycle_id"], keep="first")
    candidates["event_id"] = candidates.apply(_event_id, axis=1)
    candidates["signal_at"] = candidates["cutoff"]
    candidates["observation_cutoff"] = "daily_close"
    candidates["earliest_entry"] = "next_session_open"
    return candidates.sort_values(
        ["trade_date", "vt_symbol", "sector_id"],
        kind="stable",
        ignore_index=True,
    )


def attach_daily_event_metrics(features: pd.DataFrame) -> pd.DataFrame:
    """Attach the same close-cutoff event metrics to product and control rows."""

    missing = [column for column in EVENT_NUMERIC_COLUMNS if column not in features]
    if missing:
        raise ValueError(f"missing daily event metric columns: {', '.join(missing)}")
    frame = features.copy()
    frame[list(EVENT_NUMERIC_COLUMNS)] = frame[list(EVENT_NUMERIC_COLUMNS)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    frame = frame.dropna(subset=list(EVENT_NUMERIC_COLUMNS))
    frame["day_return_pct"] = (
        frame["close_price"] / frame["previous_close"] - 1.0
    ) * 100.0
    frame["candle_return_pct"] = (
        frame["close_price"] / frame["open_price"] - 1.0
    ) * 100.0
    frame["distance_to_ma5_pct"] = (frame["close_price"] / frame["ma5"] - 1.0) * 100.0
    frame["distance_to_ma10_pct"] = (
        frame["close_price"] / frame["ma10"] - 1.0
    ) * 100.0
    return frame


def classify_daily_family_tags(row: pd.Series) -> tuple[str, ...]:
    tags: list[str] = []
    day_return = float(row["day_return_pct"])
    candle_return = float(row["candle_return_pct"])
    prior_return = float(row["return_10d_pct"])
    prior_strong = bool(row["prior_strong_day"])
    weak_open_repair = (
        float(row["open_price"]) < float(row["previous_close"])
        and float(row["close_price"]) > float(row["open_price"])
    )

    if prior_return > 0 and (day_return < 0 or candle_return < 0):
        tags.append("first_divergence")
    if prior_strong and (candle_return < 0 or weak_open_repair):
        tags.append("first_bearish_or_break_repair")

    sessions_since_peak = float(row["sessions_since_peak"])
    drawdown = float(row["drawdown_from_peak_pct"])
    second_wave = (
        2 <= sessions_since_peak <= 15
        and -15.0 <= drawdown < 0
        and float(row["close_price"]) >= float(row["ma10"])
        and float(row["volume_ratio_5d"]) <= 1.0
    )
    if second_wave:
        tags.append("second_wave_pullback")
    return tuple(sorted(tags))


def _event_id(row: pd.Series) -> str:
    trade_date = pd.Timestamp(row["trade_date"]).date().isoformat()
    taxonomy_version = str(row.get("theme_eligibility_version") or "").strip()
    taxonomy_identity = f":{taxonomy_version}" if taxonomy_version else ""
    return (
        f"low-suction-daily-v1{taxonomy_identity}:{trade_date}:{row['vt_symbol']}:"
        f"{row['sector_id']}:{row['rise_cycle_id']}"
    )


def _validate_features(features: pd.DataFrame) -> None:
    prohibited = [
        column
        for column in features.columns
        if str(column).lower().startswith(PROHIBITED_PREFIXES)
    ]
    if prohibited:
        raise ValueError(f"outcome columns are not allowed in event features: {prohibited}")
    missing = [column for column in REQUIRED_COLUMNS if column not in features]
    if missing:
        raise ValueError(f"missing required event columns: {', '.join(missing)}")


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            *REQUIRED_COLUMNS,
            "day_return_pct",
            "candle_return_pct",
            "distance_to_ma5_pct",
            "distance_to_ma10_pct",
            "family_tags",
            "related_concepts",
            "event_id",
            "signal_at",
            "observation_cutoff",
            "earliest_entry",
        ]
    )
