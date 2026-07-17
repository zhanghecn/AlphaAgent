"""Discovery-only first-divergence candidates for low-suction research."""

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

DIVERGENCE_HORIZON_SESSIONS = 5
EVIDENCE_LEVEL = "event_recognition_first_divergence_falsification"

RECOGNITION_COLUMNS = (
    "event_id",
    "source_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "recognition_rank",
)
DAILY_COLUMNS = ("vt_symbol", "trade_date", "close_price", "volume")
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
class FirstDivergenceInputs:
    candidates: pd.DataFrame
    stock_bars: pd.DataFrame
    trading_dates: tuple[date, ...]
    discovery_start: date
    discovery_end: date
    coverage: dict[str, Any]
    input_fingerprints: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _CandidateBuildResult:
    candidates: pd.DataFrame
    diagnostics: dict[str, int]


def build_first_divergence_candidates(
    recognition_candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    cycle_states: pd.DataFrame,
    timing_context: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
    discovery_end: date,
) -> pd.DataFrame:
    """Select the first negative close after each recognition leader spell."""

    return _build_candidates(
        recognition_candidates,
        stock_bars,
        cycle_states,
        timing_context,
        trading_dates=trading_dates,
        discovery_end=discovery_end,
    ).candidates


def load_first_divergence_inputs() -> FirstDivergenceInputs:
    """Load only V2 discovery values and construct immutable candidates."""

    event_inputs = load_event_falsification_inputs()
    cycle_inputs = load_cycle_research_inputs()
    cycle_discovery_end = cycle_inputs.split.discovery_dates[-1]
    if cycle_discovery_end != event_inputs.discovery_end:
        raise ValueError("event and cycle discovery boundaries must match")

    cycle_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    timing_context = load_timing_context()
    timing_context = timing_context.loc[
        pd.to_datetime(timing_context["source_date"]).dt.date
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

    result = _build_candidates(
        event_inputs.candidates,
        event_inputs.stock_bars,
        cycle_states,
        timing_context,
        trading_dates=event_inputs.trading_dates,
        discovery_end=event_inputs.discovery_end,
    )
    candidates = result.candidates
    fingerprints = {
        **event_inputs.input_fingerprints,
        "first_divergence_candidates": fingerprint_frame(
            candidates,
            identity_columns=("divergence_date", "vt_symbol"),
        ).as_dict(),
        "breakout_cycle_states": fingerprint_frame(
            cycle_states.loc[cycle_states["definition"].eq("breakout_trend")],
            identity_columns=("trade_date", "sector_id"),
        ).as_dict(),
    }
    coverage = _build_coverage(candidates, result.diagnostics)
    return FirstDivergenceInputs(
        candidates=candidates,
        stock_bars=event_inputs.stock_bars,
        trading_dates=event_inputs.trading_dates,
        discovery_start=event_inputs.discovery_start,
        discovery_end=event_inputs.discovery_end,
        coverage=coverage,
        input_fingerprints=fingerprints,
    )


def run_first_divergence_candidate_audit() -> dict[str, Any]:
    """Return candidate coverage without loading minute bars or outcomes."""

    inputs = load_first_divergence_inputs()
    protocol = default_protocol()
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": EVIDENCE_LEVEL,
        "overall_conclusion": (
            "first_divergence_candidates_available"
            if len(inputs.candidates)
            else "no_first_divergence_candidates"
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
            "divergence_horizon_sessions": DIVERGENCE_HORIZON_SESSIONS,
        },
        "frozen_contract": {
            "spell_identity": ["sector_id", "cycle_id", "vt_symbol"],
            "spell_event": "earliest recognition source event",
            "divergence": "first close below previous close in S+1 through S+5",
            "cycle_guard": "same breakout_trend cycle_id on divergence date",
            "observation": "next reliable session after divergence",
            "planned_exit": "next reliable session after observation",
            "collision_order": [
                "divergence_relative_percentile_desc",
                "recognition_source_date_asc",
                "sector_id_asc",
            ],
            "timing_context": "divergence-date close",
        },
        "coverage": inputs.coverage,
        "input_fingerprints": inputs.input_fingerprints,
        "next_gate": "candidate_only_5m_manifest",
    }


def render_first_divergence_audit_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_first_divergence_audit_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    return "\n".join(
        [
            "# Low-suction First-divergence Candidate Audit",
            "",
            f"- Conclusion: `{report['overall_conclusion']}`",
            "- Formal metrics: `null`",
            "- Holdout/minute/outcome values read: `false/false/false`",
            f"- Recognition candidates/spells: `{coverage['recognition_candidates']}/"
            f"{coverage['recognition_spells']}`",
            f"- First-divergence candidates: `{coverage['candidate_count']}`",
            f"- Symbols/dates: `{coverage['candidate_symbols']}/"
            f"{coverage['candidate_dates']}`",
            f"- Collision rows removed: `{coverage['cross_concept_collisions_removed']}`",
            "",
        ]
    )


def _build_candidates(
    recognition_candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    cycle_states: pd.DataFrame,
    timing_context: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
    discovery_end: date,
) -> _CandidateBuildResult:
    _reject_outcome_columns(recognition_candidates, cycle_states, timing_context)
    spells = _prepare_spells(recognition_candidates)
    bars = _prepare_daily_bars(stock_bars)
    states = _prepare_cycle_states(cycle_states)
    timing = _prepare_timing_context(timing_context)
    calendar = tuple(
        value
        for value in sorted(set(pd.to_datetime(trading_dates, errors="raise").date))
        if value <= discovery_end
    )
    diagnostics = Counter(
        input_recognition_candidates=len(recognition_candidates),
        recognition_spells=len(spells),
    )
    if not calendar or spells.empty:
        return _CandidateBuildResult(_empty_candidates(), dict(diagnostics))

    calendar_positions = {value: index for index, value in enumerate(calendar)}
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
        row = _build_spell_candidate(
            spell,
            calendar=calendar,
            calendar_positions=calendar_positions,
            bar_index=bar_index,
            state_index=state_index,
            timing_index=timing_index,
        )
        if row.candidate is None:
            diagnostics[row.rejection_reason or "rejected_unknown"] += 1
            continue
        rows.append(row.candidate)
    diagnostics["pre_collision_candidates"] = len(rows)
    candidates = pd.DataFrame(rows, columns=_empty_candidates().columns)
    candidates = _deduplicate_cross_concept_collisions(candidates)
    diagnostics["cross_concept_collisions_removed"] = len(rows) - len(candidates)
    diagnostics["candidate_count"] = len(candidates)
    return _CandidateBuildResult(candidates, dict(diagnostics))


@dataclass(frozen=True)
class _SpellCandidate:
    candidate: dict[str, Any] | None
    rejection_reason: str | None = None


def _build_spell_candidate(
    spell: dict[str, Any],
    *,
    calendar: tuple[date, ...],
    calendar_positions: dict[date, int],
    bar_index: dict[tuple[str, date], Any],
    state_index: dict[tuple[str, date], Any],
    timing_index: dict[date, Any],
) -> _SpellCandidate:
    recognition_date = spell["source_date"]
    source_position = calendar_positions.get(recognition_date)
    if source_position is None:
        return _SpellCandidate(None, "rejected_source_outside_calendar")

    search_dates = calendar[
        source_position + 1 : source_position + 1 + DIVERGENCE_HORIZON_SESSIONS
    ]
    symbol = str(spell["vt_symbol"])
    for session_offset, divergence_date in enumerate(search_dates, start=1):
        bar = bar_index.get((symbol, divergence_date))
        if not _is_negative_close(bar):
            continue
        state = state_index.get((str(spell["sector_id"]), divergence_date))
        if state is None or str(state.cycle_id) != str(spell["cycle_id"]):
            return _SpellCandidate(None, "rejected_cycle_guard")
        observation_position = calendar_positions[divergence_date] + 1
        exit_position = observation_position + 1
        if exit_position >= len(calendar):
            return _SpellCandidate(None, "rejected_discovery_boundary")
        timing = timing_index.get(divergence_date)
        previous_close = float(bar.previous_close)
        close_price = float(bar.close_price)
        return _SpellCandidate(
            {
                "event_id": spell["event_id"],
                "recognition_source_date": recognition_date,
                "source_date": divergence_date,
                "divergence_date": divergence_date,
                "entry_date": calendar[observation_position],
                "planned_exit_date": calendar[exit_position],
                "sector_id": str(spell["sector_id"]),
                "concept_name": str(spell["concept_name"]),
                "cycle_id": str(spell["cycle_id"]),
                "vt_symbol": symbol,
                "stock_name": str(spell.get("stock_name") or ""),
                "recognition_rank": int(spell["recognition_rank"]),
                "relative_percentile": float(state.relative_percentile),
                "signal_close": close_price,
                "divergence_previous_close": previous_close,
                "divergence_return_pct": (close_price / previous_close - 1.0) * 100.0,
                "divergence_session_offset": session_offset,
                "active_direction": _timing_value(timing, "active_direction"),
                "danger_state": _timing_value(timing, "danger_state"),
                "market_phase": _timing_value(timing, "market_phase"),
                "evidence_level": EVIDENCE_LEVEL,
            }
        )
    return _SpellCandidate(None, "rejected_no_negative_close")


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
    for column in ("close_price", "volume"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    bars["previous_close"] = bars.groupby("vt_symbol", sort=False)[
        "close_price"
    ].shift(1)
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


def _prepare_timing_context(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, TIMING_COLUMNS, "market timing")
    timing = frame.loc[:, list(TIMING_COLUMNS)].copy()
    timing["source_date"] = pd.to_datetime(
        timing["source_date"], errors="raise"
    ).dt.date
    if timing.duplicated(["source_date"]).any():
        raise ValueError("market timing dates must be unique")
    return timing


def _is_negative_close(bar: Any | None) -> bool:
    if bar is None or pd.isna(bar.close_price) or pd.isna(bar.previous_close):
        return False
    if pd.isna(bar.volume) or float(bar.volume) <= 0:
        return False
    return float(bar.close_price) < float(bar.previous_close)


def _deduplicate_cross_concept_collisions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return _empty_candidates()
    ordered = frame.sort_values(
        [
            "vt_symbol",
            "entry_date",
            "relative_percentile",
            "recognition_source_date",
            "sector_id",
            "event_id",
        ],
        ascending=[True, True, False, True, True, True],
        kind="stable",
    )
    return (
        ordered.drop_duplicates(["vt_symbol", "entry_date"], keep="first")
        .sort_values(
            ["source_date", "sector_id", "recognition_rank", "vt_symbol"],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def _build_coverage(
    candidates: pd.DataFrame,
    diagnostics: dict[str, int],
) -> dict[str, Any]:
    offsets = (
        candidates["divergence_session_offset"].value_counts().sort_index()
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
        "candidate_dates": int(candidates["source_date"].nunique()),
        "candidate_start": (
            min(candidates["source_date"]).isoformat() if len(candidates) else None
        ),
        "candidate_end": (
            max(candidates["source_date"]).isoformat() if len(candidates) else None
        ),
        "divergence_offset_counts": {
            str(int(key)): int(value) for key, value in offsets.items()
        },
        "regime_counts": {str(key): int(value) for key, value in regimes.items()},
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
    prohibited = set().union(*(PROHIBITED_OUTCOME_COLUMNS & set(frame) for frame in frames))
    if prohibited:
        raise ValueError(
            f"outcome columns are prohibited from candidate discovery: {sorted(prohibited)}"
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
            "recognition_source_date",
            "source_date",
            "divergence_date",
            "entry_date",
            "planned_exit_date",
            "sector_id",
            "concept_name",
            "cycle_id",
            "vt_symbol",
            "stock_name",
            "recognition_rank",
            "relative_percentile",
            "signal_close",
            "divergence_previous_close",
            "divergence_return_pct",
            "divergence_session_offset",
            "active_direction",
            "danger_state",
            "market_phase",
            "evidence_level",
        ]
    )
