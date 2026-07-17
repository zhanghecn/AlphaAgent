"""Point-in-time continuous 5-minute states for neutral event-spell days."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .event_recognition_5m_study import build_event_5m_state_panel

NEUTRAL_STATE_FEATURES = (
    "drawdown_from_session_high_pct",
    "distance_to_previous_close_pct",
    "distance_to_open_pct",
    "distance_to_vwap_pct",
    "distance_to_previous_high_pct",
    "distance_to_ma5_pct",
    "distance_to_ma10_pct",
    "return_1bar_pct",
    "return_3bar_pct",
    "volume_ratio_prior_3bars",
    "minutes_from_open",
    "cycle_relative_percentile",
    "spell_session_offset",
)

EXTRA_CANDIDATE_COLUMNS = (
    "leader_spell_id",
    "previous_high",
    "ma5",
    "ma10",
    "cycle_relative_percentile",
    "spell_session_offset",
    "main_rise",
    "is_top3",
    "rank_mode",
    "evidence_level",
)

PROHIBITED_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "mfe_pct",
        "mae_pct",
        "session_final_low",
        "session_final_high",
        "future_return_pct",
        "exit_price",
    }
)


def build_event_neutral_state_panel(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Build executable state rows using only bars through each timestamp."""

    _reject_future_or_outcome_columns(candidates, minute_bars)
    _require_columns(candidates, ("event_id", *EXTRA_CANDIDATE_COLUMNS), "candidate")
    if candidates.duplicated(["event_id"]).any():
        raise ValueError("neutral candidate event IDs must be unique")

    base = build_event_5m_state_panel(candidates, minute_bars)
    context = candidates.loc[:, ["event_id", *EXTRA_CANDIDATE_COLUMNS]].copy()
    panel = base.merge(
        context,
        on="event_id",
        how="left",
        validate="many_to_one",
    ).sort_values(["event_id", "bar_time"], kind="stable")
    for column in (
        "previous_high",
        "ma5",
        "ma10",
        "cycle_relative_percentile",
        "spell_session_offset",
    ):
        panel[column] = pd.to_numeric(panel[column], errors="coerce")

    group = panel.groupby("event_id", sort=False)
    panel["session_high"] = group["high_price"].cummax()
    panel["drawdown_from_session_high_pct"] = _distance_pct(
        panel["close_price"], panel["session_high"]
    )
    panel["distance_to_previous_close_pct"] = _distance_pct(
        panel["close_price"], panel["signal_close"]
    )
    panel["distance_to_open_pct"] = _distance_pct(
        panel["close_price"], panel["entry_day_open"]
    )
    panel["distance_to_vwap_pct"] = _distance_pct(
        panel["close_price"], panel["vwap"]
    )
    panel["distance_to_previous_high_pct"] = _distance_pct(
        panel["close_price"], panel["previous_high"]
    )
    panel["distance_to_ma5_pct"] = _distance_pct(
        panel["close_price"], panel["ma5"]
    )
    panel["distance_to_ma10_pct"] = _distance_pct(
        panel["close_price"], panel["ma10"]
    )
    panel["return_1bar_pct"] = group["close_price"].pct_change(
        1, fill_method=None
    ) * 100.0
    panel["return_3bar_pct"] = group["close_price"].pct_change(
        3, fill_method=None
    ) * 100.0
    prior_volume_mean = group["volume"].transform(
        lambda values: values.shift(1).rolling(3, min_periods=3).mean()
    )
    panel["volume_ratio_prior_3bars"] = panel["volume"] / prior_volume_mean.where(
        prior_volume_mean.gt(0)
    )
    panel["minutes_from_open"] = (group.cumcount() + 1) * 5
    panel["observed_at"] = panel["bar_time"]
    panel["observation_id"] = (
        panel["event_id"].astype(str)
        + ":"
        + panel["bar_time"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    )
    panel["independence_block_id"] = (
        panel["entry_date"].astype(str) + ":" + panel["cycle_id"].astype(str)
    )

    feature_values = panel.loc[:, list(NEUTRAL_STATE_FEATURES)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    minute_valid = (
        feature_values.notna().all(axis=1)
        & np.isfinite(feature_values.to_numpy(dtype=float)).all(axis=1)
        & panel["next_bar_time"].notna()
        & pd.to_numeric(panel["next_bar_open"], errors="coerce").gt(0)
        & pd.to_numeric(panel["volume"], errors="coerce").gt(0)
        & panel["main_rise"].astype(bool)
        & panel["is_top3"].astype(bool)
    )
    panel = panel.loc[minute_valid].copy()
    panel["minute_valid"] = True
    block_size = panel.groupby("independence_block_id", sort=False)[
        "observation_id"
    ].transform("size")
    panel["sample_weight"] = 1.0 / block_size
    return panel.sort_values(
        ["entry_date", "cycle_id", "event_id", "bar_time"],
        kind="stable",
    ).reset_index(drop=True)


def _distance_pct(values: pd.Series, reference: pd.Series) -> pd.Series:
    return (values / reference.where(reference.gt(0)) - 1.0) * 100.0


def _reject_future_or_outcome_columns(*frames: pd.DataFrame) -> None:
    prohibited = set().union(*(PROHIBITED_COLUMNS & set(frame) for frame in frames))
    prohibited.update(
        column
        for frame in frames
        for column in frame
        if str(column).startswith("future_")
    )
    if prohibited:
        raise ValueError(
            f"future or outcome columns are prohibited from state features: {sorted(prohibited)}"
        )


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
