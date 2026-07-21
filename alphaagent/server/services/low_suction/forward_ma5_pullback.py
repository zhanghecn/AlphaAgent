"""Causal forward shadow for the first wave-three MA5 stabilization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from .cross_leader_wave_study import classify_xuguang_climax
from .forward_leader_identity import FORWARD_LEADER_RANKING_VERSION
from .leader_identity import LeaderIdentityMode
from .leader_waves import build_leader_wave_ledger
from .stock_wave_pullbacks import build_stock_wave_features, classify_volume_ratio

FORWARD_MA5_CONTRACT_VERSION = "low-suction-forward-ma5-shadow-v1"
FORWARD_MA5_EVIDENCE_LEVEL = "strict_forward_shadow"
MINIMUM_PULLBACK_PCT = 5.0
APPROACH_TOLERANCE_PCT = 2.0
MAX_SPELL_OBSERVATION_SESSIONS = 40
ROUND_TRIP_COST_PCT = 0.2
SUPPORT_DEPTH = {"ma5": 1, "ma10": 2, "ma20": 3}
PROHIBITED_PREFIXES = (
    "entry_",
    "exit_",
    "future_",
    "mae_",
    "mfe_",
    "outcome_",
)


@dataclass(frozen=True)
class ForwardMa5Inputs:
    source_trade_date: date
    signal_trade_date: date
    attempted_at: datetime
    prior_scopes: pd.DataFrame
    signal_scopes: pd.DataFrame
    rank_history: pd.DataFrame
    stock_bars: pd.DataFrame
    stock_fund_flows: pd.DataFrame
    sector_fund_flow_snapshots: pd.DataFrame
    market_timing_rows: pd.DataFrame
    completed_dates: tuple[date, ...]
    selected_mode: str | None


@dataclass(frozen=True)
class ForwardMa5CandidateRow:
    contract_version: str
    source_trade_date: date
    signal_trade_date: date
    identity_mode: str
    vt_symbol: str
    stock_name: str
    sector_id: str
    sector_name: str
    rank: int
    known_at: datetime
    feature_cutoff_date: date
    spell_anchor_date: date
    spell_age_sessions: int
    observation_limit_sessions: int
    current_wave_number: int
    confirmed_higher_highs: int
    wave_start_date: date
    reference_peak_date: date
    reference_peak_price: float
    pullback_confirmation_date: date | None
    support_line: str | None
    support_price: float | None
    line_distance_low_pct: float | None
    line_distance_close_pct: float | None
    signal_close_not_below_previous: bool
    stock_structure_intact: bool
    concept_main_rise_intact: bool
    impulse_gain_pct: float
    strong_days_ge_9_5pct: int
    max_volume_ratio_prior5: float | None
    xuguang_climax_candidate: bool
    volume_ratio_prior5: float | None
    volume_class_prior5: str
    stock_main_net_inflow: float | None
    stock_main_net_inflow_ratio: float | None
    stock_fund_flow_source: str | None
    stock_fund_flow_known_at: datetime | None
    sector_main_net_inflow: float | None
    sector_main_net_inflow_ratio: float | None
    sector_fund_flow_source: str | None
    sector_fund_flow_known_at: datetime | None
    market_timing_direction: str | None
    market_timing_danger_state: str | None
    market_timing_known_at: datetime | None
    signal_eligible: bool
    decision_reason: str
    selected_mode_at_capture: str | None
    input_fingerprint: str
    evidence_level: str
    raw: dict[str, object]


@dataclass(frozen=True)
class ForwardMa5Scope:
    contract_version: str
    source_trade_date: date
    signal_trade_date: date
    identity_mode: str
    known_at: datetime
    complete: bool
    status: str
    prior_top3_count: int
    unique_candidate_count: int
    active_concept_count: int
    signal_count: int
    selected_mode_at_capture: str | None
    input_fingerprint: str
    evidence_level: str
    raw: dict[str, object]


@dataclass(frozen=True)
class ForwardMa5Capture:
    contract_version: str
    source_trade_date: date
    signal_trade_date: date
    input_fingerprint: str
    rows: tuple[ForwardMa5CandidateRow, ...]
    scopes: tuple[ForwardMa5Scope, ...]

    @property
    def complete(self) -> bool:
        return bool(self.scopes) and all(scope.complete for scope in self.scopes)


@dataclass(frozen=True)
class _Stabilization:
    signal_date: date
    confirmation_date: date
    support_line: str
    support_price: float
    line_distance_low_pct: float
    line_distance_close_pct: float
    close_not_below_previous: bool


def build_forward_ma5_capture(inputs: ForwardMa5Inputs) -> ForwardMa5Capture:
    """Build one strict D-close shadow capture without reading later outcomes."""

    _require_aware(inputs.attempted_at, "attempted_at")
    if inputs.source_trade_date >= inputs.signal_trade_date:
        raise ValueError("source trade date must precede signal trade date")
    _reject_future_or_outcome_columns(
        inputs.prior_scopes,
        inputs.signal_scopes,
        inputs.rank_history,
        inputs.stock_bars,
        inputs.stock_fund_flows,
        inputs.sector_fund_flow_snapshots,
        inputs.market_timing_rows,
    )
    prepared = _prepare_inputs(inputs)
    fingerprint = _fingerprint_inputs(prepared)
    blocking_reason = _scope_blocking_reason(prepared)
    if blocking_reason is not None:
        return _blocked_capture(prepared, fingerprint, blocking_reason)

    rows: list[ForwardMa5CandidateRow] = []
    scopes: list[ForwardMa5Scope] = []
    active_by_mode = _active_concepts_by_mode(prepared.rank_history, inputs.signal_trade_date)
    candidates = _signal_candidates(prepared.rank_history, inputs)
    stock_features = _stock_features_by_symbol(prepared.stock_bars)
    for mode in LeaderIdentityMode:
        mode_candidates = candidates.loc[candidates["identity_mode"].eq(mode.value)]
        mode_rows: list[ForwardMa5CandidateRow] = []
        for candidate in mode_candidates.to_dict("records"):
            symbol = str(candidate["vt_symbol"])
            features = stock_features.get(symbol)
            if features is None:
                mode_rows.append(
                    _unavailable_candidate_row(
                        inputs,
                        candidate,
                        fingerprint=fingerprint,
                        reason="stock_daily_bars_unavailable",
                    )
                )
                continue
            feature_dates = set(
                pd.to_datetime(features["trade_date"], errors="raise").dt.date
            )
            spell_anchor = _spell_anchor_date(prepared, candidate)
            if inputs.signal_trade_date not in feature_dates:
                mode_rows.append(
                    _unavailable_candidate_row(
                        inputs,
                        candidate,
                        fingerprint=fingerprint,
                        reason="signal_stock_bar_unavailable",
                    )
                )
                continue
            if spell_anchor not in feature_dates:
                mode_rows.append(
                    _unavailable_candidate_row(
                        inputs,
                        candidate,
                        fingerprint=fingerprint,
                        reason="spell_anchor_stock_bar_unavailable",
                    )
                )
                continue
            mode_rows.append(
                _candidate_row(
                    prepared,
                    candidate,
                    features,
                    active_concepts=active_by_mode.get(mode.value, set()),
                    fingerprint=fingerprint,
                )
            )
        rows.extend(mode_rows)
        scopes.append(
            ForwardMa5Scope(
                contract_version=FORWARD_MA5_CONTRACT_VERSION,
                source_trade_date=inputs.source_trade_date,
                signal_trade_date=inputs.signal_trade_date,
                identity_mode=mode.value,
                known_at=inputs.attempted_at,
                complete=True,
                status="frozen",
                prior_top3_count=int(len(mode_candidates)),
                unique_candidate_count=int(len(mode_rows)),
                active_concept_count=len(active_by_mode.get(mode.value, set())),
                signal_count=sum(row.signal_eligible for row in mode_rows),
                selected_mode_at_capture=inputs.selected_mode,
                input_fingerprint=fingerprint,
                evidence_level=FORWARD_MA5_EVIDENCE_LEVEL,
                raw={"diagnostics_are_not_signal_inputs": True},
            )
        )
    return ForwardMa5Capture(
        contract_version=FORWARD_MA5_CONTRACT_VERSION,
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        input_fingerprint=fingerprint,
        rows=tuple(rows),
        scopes=tuple(scopes),
    )


def evaluate_forward_ma5_outcomes(
    candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    completed_dates: Sequence[date],
) -> pd.DataFrame:
    """Advance eligible candidates using only completed official daily bars."""

    required = {
        "contract_version",
        "source_trade_date",
        "signal_trade_date",
        "identity_mode",
        "vt_symbol",
        "spell_anchor_date",
        "reference_peak_price",
        "signal_eligible",
        "input_fingerprint",
    }
    _require_columns(candidates, required, "forward MA5 candidate")
    bars = _prepare_stock_bars(stock_bars, cutoff=None)
    calendar = tuple(sorted(set(completed_dates)))
    calendar_positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    rows: list[dict[str, object]] = []
    eligible = candidates.loc[candidates["signal_eligible"].astype(bool)].copy()
    for candidate in eligible.sort_values(
        ["signal_trade_date", "identity_mode", "vt_symbol"], kind="stable"
    ).to_dict("records"):
        symbol_bars = bars.loc[bars["vt_symbol"].eq(str(candidate["vt_symbol"]))]
        features = build_stock_wave_features(symbol_bars.drop(columns="vt_symbol"))
        rows.append(
            _evaluate_candidate_outcome(
                candidate,
                features,
                calendar=calendar,
                calendar_positions=calendar_positions,
            )
        )
    return pd.DataFrame.from_records(rows, columns=_outcome_columns())


def _prepare_inputs(inputs: ForwardMa5Inputs) -> ForwardMa5Inputs:
    cutoff = inputs.signal_trade_date
    rank_history = inputs.rank_history.copy()
    if not rank_history.empty:
        _require_columns(
            rank_history,
            {
                "source_trade_date",
                "target_trade_date",
                "ranking_version",
                "identity_mode",
                "sector_id",
                "sector_name",
                "vt_symbol",
                "rank",
                "is_top3",
                "input_fingerprint",
                "raw",
            },
            "forward rank history",
        )
        rank_history["source_trade_date"] = pd.to_datetime(
            rank_history["source_trade_date"], errors="raise"
        ).dt.date
        rank_history["target_trade_date"] = pd.to_datetime(
            rank_history["target_trade_date"], errors="coerce"
        ).dt.date
        rank_history = rank_history.loc[
            rank_history["source_trade_date"].le(cutoff)
            & (
                rank_history["target_trade_date"].isna()
                | rank_history["target_trade_date"].le(cutoff)
            )
        ].copy()
    return replace_inputs(
        inputs,
        prior_scopes=_prepare_scope_frame(inputs.prior_scopes),
        signal_scopes=_prepare_scope_frame(inputs.signal_scopes),
        rank_history=rank_history,
        stock_bars=_prepare_stock_bars(inputs.stock_bars, cutoff=cutoff),
        stock_fund_flows=_prepare_diagnostic_dates(inputs.stock_fund_flows, cutoff),
        sector_fund_flow_snapshots=_prepare_diagnostic_dates(
            inputs.sector_fund_flow_snapshots,
            cutoff,
        ),
        market_timing_rows=_prepare_diagnostic_dates(inputs.market_timing_rows, cutoff),
        completed_dates=tuple(
            day for day in sorted(set(inputs.completed_dates)) if day <= cutoff
        ),
    )


def replace_inputs(inputs: ForwardMa5Inputs, **changes: object) -> ForwardMa5Inputs:
    values = {field: getattr(inputs, field) for field in inputs.__dataclass_fields__}
    values.update(changes)
    return ForwardMa5Inputs(**values)


def _prepare_scope_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        return result
    for column in ("source_trade_date", "target_trade_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.date
    return result


def _prepare_diagnostic_dates(frame: pd.DataFrame, cutoff: date) -> pd.DataFrame:
    result = frame.copy()
    if result.empty or "trade_date" not in result:
        return result
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    return result.loc[result["trade_date"].le(cutoff)].copy()


def _prepare_stock_bars(frame: pd.DataFrame, cutoff: date | None) -> pd.DataFrame:
    required = {
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    }
    _require_columns(frame, required, "stock daily bar")
    result = frame.copy()
    result["vt_symbol"] = result["vt_symbol"].astype(str)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    if cutoff is not None:
        result = result.loc[result["trade_date"].le(cutoff)].copy()
    if result.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identity must be unique")
    return result.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(drop=True)


def _scope_blocking_reason(inputs: ForwardMa5Inputs) -> str | None:
    expected_modes = {mode.value for mode in LeaderIdentityMode}
    required = {
        "source_trade_date",
        "ranking_version",
        "identity_mode",
        "complete",
        "input_fingerprint",
    }
    for frame, label in (
        (inputs.prior_scopes, "prior"),
        (inputs.signal_scopes, "signal"),
    ):
        if frame.empty or not required.issubset(frame.columns):
            return f"{label}_top3_scopes_missing"
        modes = set(frame["identity_mode"].astype(str))
        if modes != expected_modes or len(frame) != len(expected_modes):
            return f"{label}_top3_scopes_not_complete"
        if not frame["complete"].astype(bool).all():
            return f"{label}_top3_scopes_not_complete"
        if not frame["ranking_version"].eq(FORWARD_LEADER_RANKING_VERSION).all():
            return f"{label}_top3_ranking_version_mismatch"
    if not inputs.prior_scopes["source_trade_date"].eq(inputs.source_trade_date).all():
        return "prior_top3_source_date_mismatch"
    if not inputs.prior_scopes["target_trade_date"].eq(inputs.signal_trade_date).all():
        return "prior_top3_target_date_mismatch"
    if not inputs.signal_scopes["source_trade_date"].eq(inputs.signal_trade_date).all():
        return "signal_top3_source_date_mismatch"
    if inputs.signal_trade_date not in set(inputs.completed_dates):
        return "signal_completed_session_missing"
    return None


def _blocked_capture(
    inputs: ForwardMa5Inputs,
    fingerprint: str,
    reason: str,
) -> ForwardMa5Capture:
    scopes = tuple(
        ForwardMa5Scope(
            contract_version=FORWARD_MA5_CONTRACT_VERSION,
            source_trade_date=inputs.source_trade_date,
            signal_trade_date=inputs.signal_trade_date,
            identity_mode=mode.value,
            known_at=inputs.attempted_at,
            complete=False,
            status="blocked",
            prior_top3_count=0,
            unique_candidate_count=0,
            active_concept_count=0,
            signal_count=0,
            selected_mode_at_capture=inputs.selected_mode,
            input_fingerprint=fingerprint,
            evidence_level=FORWARD_MA5_EVIDENCE_LEVEL,
            raw={"blocking_reason": reason},
        )
        for mode in LeaderIdentityMode
    )
    return ForwardMa5Capture(
        contract_version=FORWARD_MA5_CONTRACT_VERSION,
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        input_fingerprint=fingerprint,
        rows=(),
        scopes=scopes,
    )


def _active_concepts_by_mode(
    rank_history: pd.DataFrame,
    signal_date: date,
) -> dict[str, set[str]]:
    current = rank_history.loc[rank_history["source_trade_date"].eq(signal_date)]
    return {
        mode.value: set(
            current.loc[current["identity_mode"].eq(mode.value), "sector_id"].astype(str)
        )
        for mode in LeaderIdentityMode
    }


def _signal_candidates(
    rank_history: pd.DataFrame,
    inputs: ForwardMa5Inputs,
) -> pd.DataFrame:
    candidates = rank_history.loc[
        rank_history["source_trade_date"].eq(inputs.source_trade_date)
        & rank_history["target_trade_date"].eq(inputs.signal_trade_date)
        & rank_history["ranking_version"].eq(FORWARD_LEADER_RANKING_VERSION)
        & rank_history["is_top3"].astype(bool)
    ].copy()
    if candidates.empty:
        return candidates
    candidates["rank"] = pd.to_numeric(candidates["rank"], errors="raise").astype(int)
    candidates["duplicate_concept_count"] = candidates.groupby(
        ["identity_mode", "vt_symbol"], sort=False
    )["sector_id"].transform("nunique")
    return (
        candidates.sort_values(
            ["identity_mode", "vt_symbol", "rank", "sector_id"], kind="stable"
        )
        .drop_duplicates(["identity_mode", "vt_symbol"], keep="first")
        .reset_index(drop=True)
    )


def _stock_features_by_symbol(stock_bars: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        symbol: build_stock_wave_features(group.drop(columns="vt_symbol"))
        for symbol, group in stock_bars.groupby("vt_symbol", sort=False)
    }


def _candidate_row(
    inputs: ForwardMa5Inputs,
    candidate: Mapping[str, Any],
    features: pd.DataFrame,
    *,
    active_concepts: set[str],
    fingerprint: str,
) -> ForwardMa5CandidateRow:
    signal_date = inputs.signal_trade_date
    spell_anchor = _spell_anchor_date(inputs, candidate)
    calendar_positions = {
        trade_date: index for index, trade_date in enumerate(inputs.completed_dates)
    }
    spell_age = calendar_positions[signal_date] - calendar_positions[spell_anchor] + 1
    observed = features.loc[
        pd.to_datetime(features["trade_date"]).dt.date.le(signal_date)
    ].copy()
    ledger = build_leader_wave_ledger(
        observed,
        anchor_date=spell_anchor,
        observation_end=signal_date,
        minimum_pullback_pct=MINIMUM_PULLBACK_PCT,
    )
    current = ledger.iloc[-1]
    wave_number = int(current["wave_number"])
    confirmed_highs = wave_number - 1
    wave_start = pd.Timestamp(current["wave_start_date"]).date()
    peak_date = pd.Timestamp(current["peak_date"]).date()
    peak_price = float(current["peak_price"])
    stabilization = _first_stabilization(observed, wave_start)
    structure_intact = _stock_structure_intact(
        observed,
        peak_date=peak_date,
        signal_date=signal_date,
    )
    concept_intact = str(candidate["sector_id"]) in active_concepts
    impulse = observed.loc[
        pd.to_datetime(observed["trade_date"]).dt.date.between(wave_start, peak_date)
    ]
    start_close = float(impulse.iloc[0]["close_price"])
    impulse_gain = (peak_price / start_close - 1.0) * 100.0
    strong_days = int(impulse["daily_return_pct"].ge(9.5).sum())
    max_volume = _finite_or_none(impulse["volume_ratio_prior5"].max())
    climax = classify_xuguang_climax(impulse_gain, strong_days, max_volume)
    decision_reason = _decision_reason(
        spell_age=spell_age,
        wave_number=wave_number,
        stabilization=stabilization,
        signal_date=signal_date,
        structure_intact=structure_intact,
        concept_intact=concept_intact,
        climax=climax,
    )
    stock_flow = _latest_stock_flow(inputs, str(candidate["vt_symbol"]))
    sector_flow = _latest_sector_flow(inputs, str(candidate["sector_id"]))
    timing = _latest_timing(inputs)
    signal_bar = observed.loc[
        pd.to_datetime(observed["trade_date"]).dt.date.eq(signal_date)
    ].iloc[0]
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), Mapping) else {}
    return ForwardMa5CandidateRow(
        contract_version=FORWARD_MA5_CONTRACT_VERSION,
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=signal_date,
        identity_mode=str(candidate["identity_mode"]),
        vt_symbol=str(candidate["vt_symbol"]),
        stock_name=str(raw.get("stock_name") or ""),
        sector_id=str(candidate["sector_id"]),
        sector_name=str(candidate.get("sector_name") or candidate["sector_id"]),
        rank=int(candidate["rank"]),
        known_at=inputs.attempted_at,
        feature_cutoff_date=signal_date,
        spell_anchor_date=spell_anchor,
        spell_age_sessions=spell_age,
        observation_limit_sessions=MAX_SPELL_OBSERVATION_SESSIONS,
        current_wave_number=wave_number,
        confirmed_higher_highs=confirmed_highs,
        wave_start_date=wave_start,
        reference_peak_date=peak_date,
        reference_peak_price=peak_price,
        pullback_confirmation_date=(
            stabilization.confirmation_date if stabilization is not None else None
        ),
        support_line=(stabilization.support_line if stabilization is not None else None),
        support_price=(stabilization.support_price if stabilization is not None else None),
        line_distance_low_pct=(
            stabilization.line_distance_low_pct if stabilization is not None else None
        ),
        line_distance_close_pct=(
            stabilization.line_distance_close_pct if stabilization is not None else None
        ),
        signal_close_not_below_previous=(
            stabilization.close_not_below_previous
            if stabilization is not None
            else False
        ),
        stock_structure_intact=structure_intact,
        concept_main_rise_intact=concept_intact,
        impulse_gain_pct=impulse_gain,
        strong_days_ge_9_5pct=strong_days,
        max_volume_ratio_prior5=max_volume,
        xuguang_climax_candidate=climax,
        volume_ratio_prior5=_finite_or_none(signal_bar["volume_ratio_prior5"]),
        volume_class_prior5=classify_volume_ratio(signal_bar["volume_ratio_prior5"]),
        stock_main_net_inflow=_record_number(stock_flow, "main_net_inflow"),
        stock_main_net_inflow_ratio=_record_number(
            stock_flow, "main_net_inflow_ratio"
        ),
        stock_fund_flow_source=_record_text(stock_flow, "source"),
        stock_fund_flow_known_at=_record_datetime(stock_flow, "updated_at"),
        sector_main_net_inflow=_record_number(sector_flow, "main_net_inflow"),
        sector_main_net_inflow_ratio=_record_number(
            sector_flow, "main_net_inflow_ratio"
        ),
        sector_fund_flow_source=_record_text(sector_flow, "source"),
        sector_fund_flow_known_at=_record_datetime(sector_flow, "captured_at"),
        market_timing_direction=_record_text(timing, "active_direction"),
        market_timing_danger_state=_record_text(timing, "danger_state"),
        market_timing_known_at=_record_datetime(timing, "known_at"),
        signal_eligible=decision_reason == "eligible_forward_ma5_shadow",
        decision_reason=decision_reason,
        selected_mode_at_capture=inputs.selected_mode,
        input_fingerprint=fingerprint,
        evidence_level=FORWARD_MA5_EVIDENCE_LEVEL,
        raw={
            "duplicate_concept_count": int(candidate.get("duplicate_concept_count") or 1),
            "diagnostics_are_not_signal_inputs": True,
        },
    )


def _unavailable_candidate_row(
    inputs: ForwardMa5Inputs,
    candidate: Mapping[str, Any],
    *,
    fingerprint: str,
    reason: str,
) -> ForwardMa5CandidateRow:
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), Mapping) else {}
    return ForwardMa5CandidateRow(
        contract_version=FORWARD_MA5_CONTRACT_VERSION,
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        identity_mode=str(candidate["identity_mode"]),
        vt_symbol=str(candidate["vt_symbol"]),
        stock_name=str(raw.get("stock_name") or ""),
        sector_id=str(candidate["sector_id"]),
        sector_name=str(candidate.get("sector_name") or candidate["sector_id"]),
        rank=int(candidate["rank"]),
        known_at=inputs.attempted_at,
        feature_cutoff_date=inputs.signal_trade_date,
        spell_anchor_date=inputs.signal_trade_date,
        spell_age_sessions=1,
        observation_limit_sessions=MAX_SPELL_OBSERVATION_SESSIONS,
        current_wave_number=1,
        confirmed_higher_highs=0,
        wave_start_date=inputs.signal_trade_date,
        reference_peak_date=inputs.signal_trade_date,
        reference_peak_price=0.0,
        pullback_confirmation_date=None,
        support_line=None,
        support_price=None,
        line_distance_low_pct=None,
        line_distance_close_pct=None,
        signal_close_not_below_previous=False,
        stock_structure_intact=False,
        concept_main_rise_intact=False,
        impulse_gain_pct=0.0,
        strong_days_ge_9_5pct=0,
        max_volume_ratio_prior5=None,
        xuguang_climax_candidate=False,
        volume_ratio_prior5=None,
        volume_class_prior5="unavailable",
        stock_main_net_inflow=None,
        stock_main_net_inflow_ratio=None,
        stock_fund_flow_source=None,
        stock_fund_flow_known_at=None,
        sector_main_net_inflow=None,
        sector_main_net_inflow_ratio=None,
        sector_fund_flow_source=None,
        sector_fund_flow_known_at=None,
        market_timing_direction=None,
        market_timing_danger_state=None,
        market_timing_known_at=None,
        signal_eligible=False,
        decision_reason=reason,
        selected_mode_at_capture=inputs.selected_mode,
        input_fingerprint=fingerprint,
        evidence_level=FORWARD_MA5_EVIDENCE_LEVEL,
        raw={"diagnostics_are_not_signal_inputs": True},
    )


def _spell_anchor_date(
    inputs: ForwardMa5Inputs,
    candidate: Mapping[str, Any],
) -> date:
    history = inputs.rank_history.loc[
        inputs.rank_history["identity_mode"].eq(str(candidate["identity_mode"]))
        & inputs.rank_history["sector_id"].eq(str(candidate["sector_id"]))
        & inputs.rank_history["vt_symbol"].eq(str(candidate["vt_symbol"]))
        & inputs.rank_history["is_top3"].astype(bool)
        & inputs.rank_history["target_trade_date"].notna()
        & inputs.rank_history["target_trade_date"].le(inputs.signal_trade_date)
    ]
    observed = set(history["target_trade_date"])
    calendar = list(inputs.completed_dates)
    position = calendar.index(inputs.signal_trade_date)
    anchor = inputs.signal_trade_date
    while position >= 0 and calendar[position] in observed:
        anchor = calendar[position]
        position -= 1
    return anchor


def _first_stabilization(
    features: pd.DataFrame,
    wave_start: date,
) -> _Stabilization | None:
    frame = features.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    window = frame.loc[frame["trade_date"].ge(wave_start)].reset_index(drop=True)
    if len(window) < 2:
        return None
    peak = float(window.iloc[0]["high_price"])
    peak_date = wave_start
    confirmation: date | None = None
    deepest: str | None = None
    for position in range(1, len(window)):
        bar = window.iloc[position]
        trade_date = bar["trade_date"]
        high = float(bar["high_price"])
        low = float(bar["low_price"])
        if confirmation is None:
            if high > peak:
                peak = high
                peak_date = trade_date
            if trade_date > peak_date and low <= peak * (1.0 - MINIMUM_PULLBACK_PCT / 100.0):
                confirmation = trade_date
            else:
                continue
        elif high > peak:
            return None

        approached = [
            line
            for line in SUPPORT_DEPTH
            if (support := _finite_or_none(bar[line])) is not None
            and low <= support * (1.0 + APPROACH_TOLERANCE_PCT / 100.0)
        ]
        if approached:
            deepest_today = max(approached, key=SUPPORT_DEPTH.__getitem__)
            if deepest is None or SUPPORT_DEPTH[deepest_today] > SUPPORT_DEPTH[deepest]:
                deepest = deepest_today
        if deepest is None:
            continue
        support_price = _finite_or_none(bar[deepest])
        previous_close = float(window.iloc[position - 1]["close_price"])
        close = float(bar["close_price"])
        if support_price is not None and close >= support_price and close >= previous_close:
            return _Stabilization(
                signal_date=trade_date,
                confirmation_date=confirmation,
                support_line=deepest,
                support_price=support_price,
                line_distance_low_pct=(low / support_price - 1.0) * 100.0,
                line_distance_close_pct=(close / support_price - 1.0) * 100.0,
                close_not_below_previous=True,
            )
    return None


def _stock_structure_intact(
    features: pd.DataFrame,
    *,
    peak_date: date,
    signal_date: date,
) -> bool:
    dates = pd.to_datetime(features["trade_date"], errors="raise").dt.date
    path = features.loc[dates.gt(peak_date) & dates.le(signal_date)].copy()
    if path.empty:
        return True
    below_ma10 = path["close_price"].lt(path["ma10"]).fillna(False)
    broken = path["close_price"].lt(path["ma20"]).fillna(False) | (
        below_ma10
        & below_ma10.shift(1, fill_value=False)
        & path["ma5"].le(path["ma10"]).fillna(False)
    )
    return not bool(broken.any())


def _decision_reason(
    *,
    spell_age: int,
    wave_number: int,
    stabilization: _Stabilization | None,
    signal_date: date,
    structure_intact: bool,
    concept_intact: bool,
    climax: bool,
) -> str:
    if spell_age - 1 > MAX_SPELL_OBSERVATION_SESSIONS:
        return "leader_spell_observation_window_expired"
    if wave_number < 3:
        return "fewer_than_two_confirmed_higher_highs"
    if wave_number > 3:
        return "later_than_first_post_confirmation_pullback"
    if stabilization is None:
        return "wave_three_stabilization_not_observed"
    if stabilization.signal_date < signal_date:
        return "first_wave_three_stabilization_already_passed"
    if stabilization.signal_date > signal_date:
        return "wave_three_stabilization_not_observed"
    if stabilization.support_line != "ma5":
        return "first_stabilized_support_not_ma5"
    if not structure_intact:
        return "stock_structure_broken"
    if not concept_intact:
        return "concept_main_rise_not_intact_on_signal_date"
    if climax:
        return "xuguang_climax_combination"
    return "eligible_forward_ma5_shadow"


def _latest_stock_flow(
    inputs: ForwardMa5Inputs,
    vt_symbol: str,
) -> Mapping[str, Any] | None:
    frame = inputs.stock_fund_flows
    if frame.empty or not {"vt_symbol", "trade_date"}.issubset(frame.columns):
        return None
    matches = frame.loc[
        frame["vt_symbol"].astype(str).eq(vt_symbol)
        & frame["trade_date"].eq(inputs.signal_trade_date)
    ].copy()
    return _latest_known_record(matches, "updated_at", inputs.attempted_at)


def _latest_sector_flow(
    inputs: ForwardMa5Inputs,
    sector_id: str,
) -> Mapping[str, Any] | None:
    frame = inputs.sector_fund_flow_snapshots
    if frame.empty or not {"sector_id", "trade_date"}.issubset(frame.columns):
        return None
    matches = frame.loc[
        frame["sector_id"].astype(str).eq(sector_id)
        & frame["trade_date"].eq(inputs.signal_trade_date)
    ].copy()
    if "is_stale" in matches:
        matches = matches.loc[~matches["is_stale"].fillna(True).astype(bool)]
    return _latest_known_record(matches, "captured_at", inputs.attempted_at)


def _latest_timing(inputs: ForwardMa5Inputs) -> Mapping[str, Any] | None:
    frame = inputs.market_timing_rows
    if frame.empty or "trade_date" not in frame:
        return None
    matches = frame.loc[frame["trade_date"].eq(inputs.signal_trade_date)].copy()
    return _latest_known_record(matches, "known_at", inputs.attempted_at)


def _latest_known_record(
    frame: pd.DataFrame,
    known_column: str,
    attempted_at: datetime,
) -> Mapping[str, Any] | None:
    if frame.empty or known_column not in frame:
        return None
    known = pd.to_datetime(frame[known_column], errors="coerce", utc=True)
    cutoff = pd.Timestamp(attempted_at).tz_convert("UTC")
    eligible = frame.loc[known.le(cutoff)].copy()
    if eligible.empty:
        return None
    eligible["_known_order"] = known.loc[eligible.index]
    return eligible.sort_values("_known_order", kind="stable").iloc[-1].to_dict()


def _evaluate_candidate_outcome(
    candidate: Mapping[str, Any],
    features: pd.DataFrame,
    *,
    calendar: Sequence[date],
    calendar_positions: Mapping[date, int],
) -> dict[str, object]:
    signal_date = _as_date(candidate["signal_trade_date"])
    anchor_date = _as_date(candidate["spell_anchor_date"])
    peak = float(candidate["reference_peak_price"])
    frame = features.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    completed = frame.loc[frame["trade_date"].isin(calendar)].copy()
    after_signal = completed.loc[completed["trade_date"].gt(signal_date)].reset_index(drop=True)
    base = _outcome_identity(candidate)
    last_evaluated = max(calendar) if calendar else None
    if after_signal.empty:
        return {
            **base,
            "status": "awaiting_entry",
            "entry_date": None,
            "entry_price": None,
            "entry_proxy": "next_completed_session_open",
            "exit_date": None,
            "exit_price": None,
            "exit_reason": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "mae_pct": None,
            "mfe_pct": None,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "right_censored": False,
            "terminal": False,
            "last_evaluated_trade_date": last_evaluated,
        }
    entry = after_signal.iloc[0]
    entry_date = entry["trade_date"]
    entry_price = float(entry["open_price"])
    if entry_price >= peak:
        return {
            **base,
            "status": "opportunity_gone_at_entry",
            "entry_date": entry_date,
            "entry_price": entry_price,
            "entry_proxy": "next_completed_session_open",
            "exit_date": None,
            "exit_price": None,
            "exit_reason": "entry_open_at_or_above_reference_peak",
            "gross_return_pct": None,
            "net_return_pct": None,
            "mae_pct": None,
            "mfe_pct": None,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "right_censored": False,
            "terminal": True,
            "last_evaluated_trade_date": last_evaluated,
        }

    anchor_position = calendar_positions.get(anchor_date)
    boundary_position = (
        anchor_position + MAX_SPELL_OBSERVATION_SESSIONS
        if anchor_position is not None
        else None
    )
    boundary = (
        calendar[boundary_position]
        if boundary_position is not None and boundary_position < len(calendar)
        else None
    )
    evaluation_end = boundary or last_evaluated
    path = completed.loc[
        completed["trade_date"].ge(signal_date)
        & completed["trade_date"].le(evaluation_end)
    ].reset_index(drop=True)
    entry_path = path.loc[path["trade_date"].ge(entry_date)]
    target = entry_path.loc[entry_path["high_price"].gt(peak)]
    below_ma20 = path["close_price"].lt(path["ma20"]).fillna(False)
    second_below = below_ma20 & below_ma20.shift(1, fill_value=False)
    defense = path.loc[path["trade_date"].ge(entry_date) & second_below]
    target_row = target.iloc[0] if not target.empty else None
    defense_row = defense.iloc[0] if not defense.empty else None
    exit_row, exit_reason = _first_exit(target_row, defense_row)
    metric_end = exit_row["trade_date"] if exit_row is not None else evaluation_end
    metric_path = entry_path.loc[entry_path["trade_date"].le(metric_end)]
    mae = (float(metric_path["low_price"].min()) / entry_price - 1.0) * 100.0
    mfe = (float(metric_path["high_price"].max()) / entry_price - 1.0) * 100.0
    if exit_row is not None:
        exit_price = float(exit_row["close_price"])
        gross = (exit_price / entry_price - 1.0) * 100.0
        return {
            **base,
            "status": "closed",
            "entry_date": entry_date,
            "entry_price": entry_price,
            "entry_proxy": "next_completed_session_open",
            "exit_date": exit_row["trade_date"],
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "gross_return_pct": gross,
            "net_return_pct": gross - ROUND_TRIP_COST_PCT,
            "mae_pct": mae,
            "mfe_pct": mfe,
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "right_censored": False,
            "terminal": True,
            "last_evaluated_trade_date": last_evaluated,
        }
    censored = boundary is not None and last_evaluated is not None and last_evaluated >= boundary
    return {
        **base,
        "status": "right_censored" if censored else "open",
        "entry_date": entry_date,
        "entry_price": entry_price,
        "entry_proxy": "next_completed_session_open",
        "exit_date": None,
        "exit_price": None,
        "exit_reason": None,
        "gross_return_pct": None,
        "net_return_pct": None,
        "mae_pct": mae,
        "mfe_pct": mfe,
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        "right_censored": censored,
        "terminal": censored,
        "last_evaluated_trade_date": last_evaluated,
    }


def _first_exit(
    target: pd.Series | None,
    defense: pd.Series | None,
) -> tuple[pd.Series | None, str | None]:
    if target is None and defense is None:
        return None, None
    if defense is None:
        return target, "reference_peak_rebroken"
    if target is None:
        return defense, "second_consecutive_close_below_ma20"
    if target["trade_date"] <= defense["trade_date"]:
        return target, "reference_peak_rebroken"
    return defense, "second_consecutive_close_below_ma20"


def _outcome_identity(candidate: Mapping[str, Any]) -> dict[str, object]:
    return {
        "contract_version": str(candidate["contract_version"]),
        "source_trade_date": _as_date(candidate["source_trade_date"]),
        "signal_trade_date": _as_date(candidate["signal_trade_date"]),
        "identity_mode": str(candidate["identity_mode"]),
        "vt_symbol": str(candidate["vt_symbol"]),
        "candidate_input_fingerprint": str(candidate["input_fingerprint"]),
    }


def _outcome_columns() -> list[str]:
    return [
        "contract_version",
        "source_trade_date",
        "signal_trade_date",
        "identity_mode",
        "vt_symbol",
        "candidate_input_fingerprint",
        "status",
        "entry_date",
        "entry_price",
        "entry_proxy",
        "exit_date",
        "exit_price",
        "exit_reason",
        "gross_return_pct",
        "net_return_pct",
        "mae_pct",
        "mfe_pct",
        "round_trip_cost_pct",
        "right_censored",
        "terminal",
        "last_evaluated_trade_date",
    ]


def _fingerprint_inputs(inputs: ForwardMa5Inputs) -> str:
    payload = {
        "contract_version": FORWARD_MA5_CONTRACT_VERSION,
        "source_trade_date": inputs.source_trade_date.isoformat(),
        "signal_trade_date": inputs.signal_trade_date.isoformat(),
        "selected_mode": inputs.selected_mode,
        "completed_dates": [day.isoformat() for day in inputs.completed_dates],
        "frames": {
            "prior_scopes": _frame_records(inputs.prior_scopes),
            "signal_scopes": _frame_records(inputs.signal_scopes),
            "rank_history": _frame_records(inputs.rank_history),
            "stock_bars": _frame_records(inputs.stock_bars),
            "stock_fund_flows": _frame_records(inputs.stock_fund_flows),
            "sector_fund_flow_snapshots": _frame_records(
                inputs.sector_fund_flow_snapshots
            ),
            "market_timing_rows": _frame_records(inputs.market_timing_rows),
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _frame_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    result = frame.copy()
    result = result.reindex(sorted(result.columns), axis=1)
    sortable = [
        column
        for column in result.columns
        if not result[column].map(lambda value: isinstance(value, (dict, list))).any()
    ]
    if sortable:
        result = result.sort_values(sortable, kind="stable", na_position="last")
    return json.loads(result.to_json(orient="records", date_format="iso", date_unit="us"))


def _reject_future_or_outcome_columns(*frames: pd.DataFrame) -> None:
    prohibited = sorted(
        {
            str(column)
            for frame in frames
            for column in frame.columns
            if str(column).lower().startswith(PROHIBITED_PREFIXES)
        }
    )
    if prohibited:
        raise ValueError("future or outcome columns are prohibited: " + ", ".join(prohibited))


def _record_number(record: Mapping[str, Any] | None, key: str) -> float | None:
    return _finite_or_none(record.get(key)) if record is not None else None


def _record_text(record: Mapping[str, Any] | None, key: str) -> str | None:
    if record is None or record.get(key) is None or pd.isna(record.get(key)):
        return None
    return str(record[key])


def _record_datetime(
    record: Mapping[str, Any] | None,
    key: str,
) -> datetime | None:
    if record is None or record.get(key) is None or pd.isna(record.get(key)):
        return None
    value = pd.Timestamp(record[key])
    if value.tzinfo is None:
        raise ValueError(f"{key} must be timezone-aware")
    return value.to_pydatetime()


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
