"""Outcome-neutral observation days for event-recognized leader spells."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
from .event_recognition_falsification import (
    PROHIBITED_OUTCOME_COLUMNS,
    load_event_falsification_inputs,
    load_timing_context,
)
from .research_protocol import default_protocol, fingerprint_frame, protocol_hash

OBSERVATION_OFFSETS = (1, 2, 3, 4, 5)
EVIDENCE_LEVEL = "event_recognition_neutral_day_falsification"
RANK_MODE = "event_recognition_proxy"

RECOGNITION_COLUMNS = (
    "event_id",
    "source_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "recognition_rank",
)
DAILY_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)
CYCLE_COLUMNS = (
    "trade_date",
    "sector_id",
    "definition",
    "in_cycle",
    "cycle_id",
    "relative_percentile",
)
TIMING_COLUMNS = (
    "source_date",
    "active_direction",
    "danger_state",
    "market_phase",
)


@dataclass(frozen=True)
class EventNeutralInputs:
    candidates: pd.DataFrame
    stock_bars: pd.DataFrame
    trading_dates: tuple[date, ...]
    discovery_start: date
    discovery_end: date
    coverage: dict[str, Any]
    input_fingerprints: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _BuildResult:
    candidates: pd.DataFrame
    diagnostics: dict[str, int]


def build_event_neutral_days(
    recognition_candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    cycle_states: pd.DataFrame,
    timing_context: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
    discovery_end: date,
) -> pd.DataFrame:
    """Build S+1..S+5 days using only information known before each open."""

    return _build_neutral_days(
        recognition_candidates,
        stock_bars,
        cycle_states,
        timing_context,
        trading_dates=trading_dates,
        discovery_end=discovery_end,
    ).candidates


def build_event_neutral_comparison_days(
    recognition_candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    cycle_states: pd.DataFrame,
    timing_context: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
    discovery_end: date,
) -> pd.DataFrame:
    """Build the same spell days while retaining a D-1 non-main-rise control."""

    return _build_neutral_days(
        recognition_candidates,
        stock_bars,
        cycle_states,
        timing_context,
        trading_dates=trading_dates,
        discovery_end=discovery_end,
        include_non_main_rise=True,
    ).candidates


def load_event_neutral_inputs() -> EventNeutralInputs:
    """Load immutable event-recognition proxy inputs inside V2 discovery."""

    return _load_event_neutral_inputs(include_non_main_rise=False)


def load_event_neutral_comparison_inputs() -> EventNeutralInputs:
    """Load the same discovery inputs with a point-in-time non-main-rise control."""

    return _load_event_neutral_inputs(include_non_main_rise=True)


def _load_event_neutral_inputs(
    *,
    include_non_main_rise: bool,
) -> EventNeutralInputs:

    event_inputs = load_event_falsification_inputs()
    cycle_inputs = load_cycle_research_inputs()
    if cycle_inputs.split.discovery_dates[-1] != event_inputs.discovery_end:
        raise ValueError("event and cycle discovery boundaries must match")
    cycle_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    timing = load_timing_context()
    timing = timing.loc[
        pd.to_datetime(timing["source_date"]).dt.date
        <= event_inputs.discovery_end
    ].copy()
    _assert_discovery_bound(
        event_inputs.stock_bars,
        column="trade_date",
        discovery_end=event_inputs.discovery_end,
        label="stock daily bars",
    )
    _assert_discovery_bound(
        cycle_states,
        column="trade_date",
        discovery_end=event_inputs.discovery_end,
        label="cycle states",
    )
    result = _build_neutral_days(
        event_inputs.candidates,
        event_inputs.stock_bars,
        cycle_states,
        timing,
        trading_dates=event_inputs.trading_dates,
        discovery_end=event_inputs.discovery_end,
        include_non_main_rise=include_non_main_rise,
    )
    candidates = result.candidates
    candidate_fingerprint = (
        "event_outcome_group_days"
        if include_non_main_rise
        else "event_neutral_days"
    )
    fingerprints = {
        **event_inputs.input_fingerprints,
        candidate_fingerprint: fingerprint_frame(
            candidates,
            identity_columns=("entry_date", "vt_symbol"),
        ).as_dict(),
        "breakout_cycle_states": fingerprint_frame(
            cycle_states.loc[cycle_states["definition"].eq("breakout_trend")],
            identity_columns=("trade_date", "sector_id"),
        ).as_dict(),
    }
    return EventNeutralInputs(
        candidates=candidates,
        stock_bars=event_inputs.stock_bars,
        trading_dates=event_inputs.trading_dates,
        discovery_start=event_inputs.discovery_start,
        discovery_end=event_inputs.discovery_end,
        coverage=_build_coverage(candidates, result.diagnostics),
        input_fingerprints=fingerprints,
    )


def run_event_neutral_candidate_audit() -> dict[str, Any]:
    inputs = load_event_neutral_inputs()
    protocol = default_protocol()
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": EVIDENCE_LEVEL,
        "overall_conclusion": (
            "event_neutral_candidates_available"
            if len(inputs.candidates) >= 100
            else "insufficient_event_neutral_candidates"
        ),
        "formal_metrics": None,
        "formal_rule_selected": False,
        "holdout_price_values_read": False,
        "minute_values_read": False,
        "outcome_values_computed": False,
        "current_membership_rows_read": 0,
        "date_split": {
            "discovery_start": inputs.discovery_start.isoformat(),
            "discovery_end": inputs.discovery_end.isoformat(),
            "observation_offsets": list(OBSERVATION_OFFSETS),
        },
        "frozen_contract": {
            "spell_identity": ["sector_id", "cycle_id", "vt_symbol"],
            "spell_event": "earliest recognition event",
            "eligibility": "previous reliable close retains exact breakout cycle",
            "same_day_concept_close_read": False,
            "stock_outcome_filter": None,
            "collision_order": [
                "context_relative_percentile_desc",
                "recognition_source_date_asc",
                "sector_id_asc",
            ],
            "timing_context": "previous reliable close",
        },
        "coverage": inputs.coverage,
        "input_fingerprints": inputs.input_fingerprints,
        "next_gate": "event_neutral_candidate_only_5m_manifest",
    }


def render_event_neutral_audit_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_event_neutral_audit_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    return "\n".join(
        [
            "# Low-suction Event-neutral Candidate Audit",
            "",
            f"- Conclusion: `{report['overall_conclusion']}`",
            "- Formal metrics: `null`",
            "- Holdout/minute/outcome values read: `false/false/false`",
            f"- Recognition candidates/spells: `{coverage['recognition_candidates']}/"
            f"{coverage['recognition_spells']}`",
            f"- Neutral candidate days: `{coverage['candidate_count']}`",
            f"- Symbols/dates: `{coverage['candidate_symbols']}/"
            f"{coverage['candidate_dates']}`",
            f"- Collision rows removed: `{coverage['cross_concept_collisions_removed']}`",
            "",
        ]
    )


def _build_neutral_days(
    recognition_candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    cycle_states: pd.DataFrame,
    timing_context: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
    discovery_end: date,
    include_non_main_rise: bool = False,
) -> _BuildResult:
    _reject_outcome_columns(recognition_candidates, cycle_states, timing_context)
    spells = _prepare_spells(recognition_candidates)
    bars = _prepare_daily_bars(stock_bars)
    states = _prepare_cycle_states(cycle_states)
    timing = _prepare_timing(timing_context)
    calendar = tuple(
        value
        for value in sorted(set(pd.to_datetime(trading_dates, errors="raise").date))
        if value <= discovery_end
    )
    diagnostics = Counter(
        input_recognition_candidates=len(recognition_candidates),
        recognition_spells=len(spells),
        potential_spell_days=len(spells) * len(OBSERVATION_OFFSETS),
    )
    if not calendar or spells.empty:
        return _BuildResult(_empty_candidates(), dict(diagnostics))

    positions = {value: index for index, value in enumerate(calendar)}
    bar_index = {
        (str(row.vt_symbol), row.trade_date): row
        for row in bars.itertuples(index=False)
    }
    state_index = {
        (str(row.sector_id), row.trade_date): row
        for row in states.itertuples(index=False)
    }
    timing_index = {
        row.source_date: row for row in timing.itertuples(index=False)
    }
    rows = []
    for spell in spells.to_dict("records"):
        source_position = positions.get(spell["source_date"])
        if source_position is None:
            diagnostics["rejected_source_outside_calendar"] += len(
                OBSERVATION_OFFSETS
            )
            continue
        for offset in OBSERVATION_OFFSETS:
            candidate = _build_spell_day(
                spell,
                offset=offset,
                source_position=source_position,
                calendar=calendar,
                bar_index=bar_index,
                state_index=state_index,
                timing_index=timing_index,
                include_non_main_rise=include_non_main_rise,
            )
            if candidate.row is None:
                diagnostics[candidate.rejection_reason or "rejected_unknown"] += 1
                continue
            rows.append(candidate.row)
    diagnostics["pre_collision_candidates"] = len(rows)
    candidates = pd.DataFrame(rows, columns=_empty_candidates().columns)
    candidates = _deduplicate_collisions(candidates)
    diagnostics["cross_concept_collisions_removed"] = len(rows) - len(candidates)
    diagnostics["candidate_count"] = len(candidates)
    if len(candidates):
        candidates["event_id"] = range(1, len(candidates) + 1)
    return _BuildResult(candidates, dict(diagnostics))


@dataclass(frozen=True)
class _CandidateRow:
    row: dict[str, Any] | None
    rejection_reason: str | None = None


def _build_spell_day(
    spell: dict[str, Any],
    *,
    offset: int,
    source_position: int,
    calendar: tuple[date, ...],
    bar_index: dict[tuple[str, date], Any],
    state_index: dict[tuple[str, date], Any],
    timing_index: dict[date, Any],
    include_non_main_rise: bool,
) -> _CandidateRow:
    observation_position = source_position + offset
    exit_position = observation_position + 1
    if exit_position >= len(calendar):
        return _CandidateRow(None, "rejected_discovery_boundary")
    observation_date = calendar[observation_position]
    context_date = calendar[observation_position - 1]
    state = state_index.get((str(spell["sector_id"]), context_date))
    main_rise = state is not None and str(state.cycle_id) == str(spell["cycle_id"])
    if not main_rise and not include_non_main_rise:
        return _CandidateRow(None, "rejected_previous_day_cycle_guard")
    support = bar_index.get((str(spell["vt_symbol"]), context_date))
    if support is None or pd.isna(support.close_price):
        return _CandidateRow(None, "rejected_missing_previous_day_support")
    timing = timing_index.get(context_date)
    leader_spell_id = ":".join(
        [
            str(spell["sector_id"]),
            str(spell["cycle_id"]),
            str(spell["vt_symbol"]),
        ]
    )
    return _CandidateRow(
        {
            "event_id": None,
            "recognition_event_id": spell["event_id"],
            "leader_spell_id": leader_spell_id,
            "recognition_source_date": spell["source_date"],
            "context_date": context_date,
            "source_date": observation_date,
            "entry_date": observation_date,
            "planned_exit_date": calendar[exit_position],
            "sector_id": str(spell["sector_id"]),
            "concept_name": str(spell["concept_name"]),
            "cycle_id": str(spell["cycle_id"]),
            "vt_symbol": str(spell["vt_symbol"]),
            "stock_name": str(spell.get("stock_name") or ""),
            "recognition_rank": int(spell["recognition_rank"]),
            "cycle_relative_percentile": (
                float(state.relative_percentile) if state is not None else float("nan")
            ),
            "spell_session_offset": int(offset),
            "signal_close": float(support.close_price),
            "previous_high": float(support.high_price),
            "ma5": float(support.ma5),
            "ma10": float(support.ma10),
            "active_direction": _timing_value(timing, "active_direction"),
            "danger_state": _timing_value(timing, "danger_state"),
            "market_phase": _timing_value(timing, "market_phase"),
            "main_rise": main_rise,
            "is_top3": True,
            "rank_mode": RANK_MODE,
            "evidence_level": EVIDENCE_LEVEL,
        }
    )


def _prepare_spells(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, RECOGNITION_COLUMNS, "recognition candidate")
    spells = frame.copy()
    spells["source_date"] = pd.to_datetime(
        spells["source_date"], errors="raise"
    ).dt.date
    if spells[list(RECOGNITION_COLUMNS)].isna().any().any():
        raise ValueError("recognition spell identity cannot be null")
    spells = spells.sort_values(
        ["source_date", "event_id", "sector_id", "vt_symbol"], kind="stable"
    )
    return spells.drop_duplicates(
        ["sector_id", "cycle_id", "vt_symbol"], keep="first"
    ).reset_index(drop=True)


def _prepare_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, DAILY_COLUMNS, "stock daily bar")
    bars = frame.loc[:, list(DAILY_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    for column in ("open_price", "high_price", "low_price", "close_price", "volume"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    grouped = bars.groupby("vt_symbol", sort=False)["close_price"]
    bars["ma5"] = grouped.transform(lambda values: values.rolling(5).mean())
    bars["ma10"] = grouped.transform(lambda values: values.rolling(10).mean())
    return bars.reset_index(drop=True)


def _prepare_cycle_states(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, CYCLE_COLUMNS, "cycle state")
    states = frame.copy()
    states["trade_date"] = pd.to_datetime(
        states["trade_date"], errors="raise"
    ).dt.date
    states = states.loc[
        states["definition"].eq("breakout_trend")
        & states["in_cycle"].astype(bool)
    ].copy()
    if states.duplicated(["trade_date", "sector_id"]).any():
        raise ValueError("active breakout cycle state identities must be unique")
    states["relative_percentile"] = pd.to_numeric(
        states["relative_percentile"], errors="coerce"
    )
    if states["relative_percentile"].isna().any():
        raise ValueError("active breakout cycle percentile must be numeric")
    return states


def _prepare_timing(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, TIMING_COLUMNS, "market timing")
    timing = frame.loc[:, list(TIMING_COLUMNS)].copy()
    timing["source_date"] = pd.to_datetime(
        timing["source_date"], errors="raise"
    ).dt.date
    if timing.duplicated(["source_date"]).any():
        raise ValueError("market timing dates must be unique")
    return timing


def _deduplicate_collisions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_candidates()
    ordered = frame.sort_values(
        [
            "vt_symbol",
            "entry_date",
            "main_rise",
            "cycle_relative_percentile",
            "recognition_source_date",
            "sector_id",
            "recognition_event_id",
        ],
        ascending=[True, True, False, False, True, True, True],
        kind="stable",
    )
    return (
        ordered.drop_duplicates(["vt_symbol", "entry_date"], keep="first")
        .sort_values(
            ["entry_date", "sector_id", "recognition_rank", "vt_symbol"],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def _build_coverage(
    candidates: pd.DataFrame,
    diagnostics: dict[str, int],
) -> dict[str, Any]:
    offsets = (
        candidates["spell_session_offset"].value_counts().sort_index()
        if not candidates.empty
        else pd.Series(dtype="int64")
    )
    regimes = (
        (
            candidates["active_direction"].astype(str)
            + "/"
            + candidates["danger_state"].astype(str)
        ).value_counts()
        if not candidates.empty
        else pd.Series(dtype="int64")
    )
    return {
        **diagnostics,
        "recognition_candidates": diagnostics.get(
            "input_recognition_candidates", 0
        ),
        "candidate_symbols": int(candidates["vt_symbol"].nunique()),
        "candidate_dates": int(candidates["entry_date"].nunique()),
        "candidate_cycles": int(candidates["cycle_id"].nunique()),
        "candidate_start": (
            min(candidates["entry_date"]).isoformat() if len(candidates) else None
        ),
        "candidate_end": (
            max(candidates["entry_date"]).isoformat() if len(candidates) else None
        ),
        "offset_counts": {
            str(int(key)): int(value) for key, value in offsets.items()
        },
        "regime_counts": {str(key): int(value) for key, value in regimes.items()},
        "same_day_cycle_values_read": 0,
        "stock_outcome_values_read": 0,
        "current_membership_rows_read": 0,
    }


def _assert_discovery_bound(
    frame: pd.DataFrame,
    *,
    column: str,
    discovery_end: date,
    label: str,
) -> None:
    if frame.empty:
        return
    maximum = pd.to_datetime(frame[column], errors="raise").dt.date.max()
    if maximum > discovery_end:
        raise ValueError(f"{label} crossed the V2 discovery boundary")


def _reject_outcome_columns(*frames: pd.DataFrame) -> None:
    prohibited = set().union(
        *(PROHIBITED_OUTCOME_COLUMNS & set(frame) for frame in frames)
    )
    if prohibited:
        raise ValueError(
            f"outcome columns are prohibited from neutral-day discovery: {sorted(prohibited)}"
        )


def _timing_value(row: Any | None, field: str) -> str:
    if row is None:
        return "UNKNOWN"
    value = getattr(row, field, None)
    return str(value) if value and not pd.isna(value) else "UNKNOWN"


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _empty_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "recognition_event_id",
            "leader_spell_id",
            "recognition_source_date",
            "context_date",
            "source_date",
            "entry_date",
            "planned_exit_date",
            "sector_id",
            "concept_name",
            "cycle_id",
            "vt_symbol",
            "stock_name",
            "recognition_rank",
            "cycle_relative_percentile",
            "spell_session_offset",
            "signal_close",
            "previous_high",
            "ma5",
            "ma10",
            "active_direction",
            "danger_state",
            "market_phase",
            "main_rise",
            "is_top3",
            "rank_mode",
            "evidence_level",
        ]
    )
