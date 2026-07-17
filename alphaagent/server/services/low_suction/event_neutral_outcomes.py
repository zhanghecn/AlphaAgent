"""Isolated D+1 execution labels for neutral event-spell states."""

from __future__ import annotations

from datetime import date

import pandas as pd

from .event_recognition_5m_study import execute_event_5m_transitions

OUTCOME_EVIDENCE_LEVEL = "event_recognition_neutral_state_d1_falsification"

PANEL_COLUMNS = (
    "observation_id",
    "event_id",
    "source_date",
    "entry_date",
    "planned_exit_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "recognition_rank",
    "signal_close",
    "active_direction",
    "danger_state",
    "market_phase",
    "observed_at",
    "next_bar_time",
    "next_bar_open",
    "close_price",
    "vwap",
)


def label_event_neutral_outcomes(
    panel: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
    cost_multiplier: float = 1.0,
) -> pd.DataFrame:
    """Fill every state at the next 5m open and exit at D+1 sellable close."""

    _require_columns(panel, PANEL_COLUMNS, "state panel")
    if panel.duplicated(["observation_id"]).any():
        raise ValueError("state observation IDs must be unique")
    transitions = _build_transitions(panel)
    outcomes = execute_event_5m_transitions(
        transitions,
        daily_bars,
        trading_dates=trading_dates,
        cost_multiplier=cost_multiplier,
    )
    outcomes["observation_id"] = outcomes["transition_id"]
    return outcomes.sort_values("observation_id", kind="stable").reset_index(drop=True)


def _build_transitions(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in panel.to_dict("records"):
        rows.append(
            {
                "transition_id": str(row["observation_id"]),
                "event_id": int(row["event_id"]),
                "rule": "neutral_state_observation",
                "source_date": row["source_date"],
                "entry_date": row["entry_date"],
                "planned_exit_date": row["planned_exit_date"],
                "sector_id": str(row["sector_id"]),
                "concept_name": str(row["concept_name"]),
                "cycle_id": str(row["cycle_id"]),
                "vt_symbol": str(row["vt_symbol"]),
                "recognition_rank": int(row["recognition_rank"]),
                "previous_close": float(row["signal_close"]),
                "active_direction": str(row["active_direction"]),
                "danger_state": str(row["danger_state"]),
                "market_phase": str(row["market_phase"]),
                "signal_time": pd.Timestamp(row["observed_at"]).to_pydatetime(),
                "entry_time": pd.Timestamp(row["next_bar_time"]).to_pydatetime(),
                "entry_price_raw": float(row["next_bar_open"]),
                "signal_close": float(row["close_price"]),
                "signal_vwap": float(row["vwap"]),
                "evidence_level": OUTCOME_EVIDENCE_LEVEL,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "transition_id",
            "event_id",
            "rule",
            "source_date",
            "entry_date",
            "planned_exit_date",
            "sector_id",
            "concept_name",
            "cycle_id",
            "vt_symbol",
            "recognition_rank",
            "previous_close",
            "active_direction",
            "danger_state",
            "market_phase",
            "signal_time",
            "entry_time",
            "entry_price_raw",
            "signal_close",
            "signal_vwap",
            "evidence_level",
        ],
    )


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
