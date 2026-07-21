"""Strict forward ledger for the frozen causal leader-pullback rule."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .causal_leader_pullback import (
    ALGORITHM_VERSION,
    ROUND_TRIP_COST_PCT,
    ROTATION_NEXT_SESSION_POLICY_VERSION,
    THREE_PHASE_ADAPTIVE_POLICY_VERSION,
    WARMING_SUPPORT_RELEVANCE_POLICY_VERSION,
    execute_close_trades,
    explain_warming_support_relevance_signal,
    select_cross_regime_support_reclaim_signals,
    select_gold_strong_reclaim_signals,
    select_rotation_next_session_signals,
    select_three_phase_adaptive_signals,
    select_warming_support_relevance_signals,
)
from .causal_leader_pullback_study import (
    CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
    GOLD_STRONG_RECLAIM_VARIANT,
    STOCK_PATH_FEATURE_COLUMNS,
    build_causal_stock_features,
    build_dynamic_leader_paths,
    replay_dynamic_leader_paths,
)
from .forward_ma5_pullback import (
    ForwardMa5CandidateRow,
    ForwardMa5Capture,
    ForwardMa5Scope,
)
from .research_protocol import fingerprint_frame
from .stock_wave_pullbacks import classify_volume_ratio
from .universe import SecurityRecord, eligibility_reason

SHANGHAI = ZoneInfo("Asia/Shanghai")
FORWARD_CONTRACT_VERSION = "causal-leader-pullback-cross-regime-forward-v2"
FORWARD_IDENTITY_MODE = "causal_campaign_rank_v2"
FORWARD_EVIDENCE_LEVEL = "strict_forward_close_proxy"
THREE_PHASE_QUALIFICATION_CONTRACT_VERSION = (
    "three-phase-natural-qualification-wilson-v1"
)
FEATURE_CUTOFF_TIME = time(15, 0)


@dataclass(frozen=True)
class CausalForwardInputs:
    source_trade_date: date
    signal_trade_date: date
    attempted_at: datetime
    membership_scope: Mapping[str, Any]
    security_scope: Mapping[str, Any]
    campaign_paths: pd.DataFrame
    memberships: pd.DataFrame
    securities: pd.DataFrame
    stock_bars: pd.DataFrame
    market_timing: pd.DataFrame


def build_causal_forward_capture(inputs: CausalForwardInputs) -> ForwardMa5Capture:
    """Freeze one D-close candidate set without reading any later bar."""

    prepared = _prepare_inputs(inputs)
    fingerprint = _input_fingerprint(prepared)
    if prepared.campaign_paths.empty:
        return _empty_capture(prepared, fingerprint, status="frozen_no_active_campaign")

    eligible_members = _eligible_memberships(prepared)
    if eligible_members.empty:
        return _empty_capture(prepared, fingerprint, status="frozen_no_eligible_members")

    stock_features = build_causal_stock_features(prepared.stock_bars)
    leader_paths, _ = build_dynamic_leader_paths(
        prepared.campaign_paths,
        eligible_members,
        stock_features,
    )
    replay = replay_dynamic_leader_paths(leader_paths, prepared.market_timing)
    signal_date = pd.Timestamp(prepared.signal_trade_date)
    signals = replay.signals.loc[
        pd.to_datetime(replay.signals.get("signal_date"), errors="coerce")
        .dt.normalize()
        .eq(signal_date)
    ].copy()
    gold = select_gold_strong_reclaim_signals(signals)
    v3 = select_cross_regime_support_reclaim_signals(signals)
    support_relevance = select_warming_support_relevance_signals(signals)
    rotation_next_session = select_rotation_next_session_signals(signals)
    three_phase_adaptive = select_three_phase_adaptive_signals(signals)
    eligible_ids = set(
        support_relevance.get("signal_id", pd.Series(dtype=str)).astype(str)
    )
    diagnostic_ids = set(
        rotation_next_session.get("signal_id", pd.Series(dtype=str)).astype(str)
    )
    three_phase_diagnostic_ids = set(
        three_phase_adaptive.get("signal_id", pd.Series(dtype=str)).astype(str)
    )
    selected = _deduplicate_signal_concepts(signals, eligible_ids)

    path_lookup = leader_paths.set_index(
        ["campaign_id", "vt_symbol", "trade_date"],
        drop=False,
    ).sort_index()
    feature_lookup = stock_features.set_index(["vt_symbol", "trade_date"]).sort_index()
    rows = tuple(
        _candidate_row(
            prepared,
            signal,
            path_lookup=path_lookup,
            feature_lookup=feature_lookup,
            eligible_ids=eligible_ids,
            diagnostic_ids=diagnostic_ids,
            three_phase_diagnostic_ids=three_phase_diagnostic_ids,
            fingerprint=fingerprint,
        )
        for signal in selected.to_dict("records")
    )
    signal_day_paths = leader_paths.loc[
        pd.to_datetime(leader_paths.get("trade_date"), errors="coerce")
        .dt.normalize()
        .eq(signal_date)
    ]
    confirmation_counts = Counter(
        replay.daily_ledger.loc[
            pd.to_datetime(replay.daily_ledger.get("trade_date"), errors="coerce")
            .dt.normalize()
            .eq(signal_date),
            "confirmation_status",
        ].astype(str)
    )
    decision_reason_counts = Counter(
        explain_warming_support_relevance_signal(signal)
        for signal in selected.to_dict("records")
    )
    scope = ForwardMa5Scope(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=prepared.source_trade_date,
        signal_trade_date=prepared.signal_trade_date,
        identity_mode=FORWARD_IDENTITY_MODE,
        known_at=prepared.attempted_at,
        complete=True,
        status="frozen",
        prior_top3_count=int(
            signal_day_paths.get("dynamic_top3", pd.Series(dtype=bool))
            .fillna(False)
            .astype(bool)
            .sum()
        ),
        unique_candidate_count=len(rows),
        active_concept_count=int(
            prepared.campaign_paths.loc[
                pd.to_datetime(
                    prepared.campaign_paths["trade_date"], errors="raise"
                )
                .dt.date.eq(prepared.signal_trade_date)
                & prepared.campaign_paths["campaign_active"].astype(bool),
                "sector_id",
            ].nunique()
        ),
        signal_count=sum(row.signal_eligible for row in rows),
        selected_mode_at_capture=FORWARD_IDENTITY_MODE,
        input_fingerprint=fingerprint,
        evidence_level=FORWARD_EVIDENCE_LEVEL,
        raw={
            "algorithm_version": ALGORITHM_VERSION,
            "policy_version": WARMING_SUPPORT_RELEVANCE_POLICY_VERSION,
            "market_policy": (
                "GOLD/NORMAL rotation=strong reclaim; warming=unbroken relevant "
                "support; all other states=cash"
            ),
            "signal_funnel": {
                "base_confirmation": int(len(signals)),
                "gold_strong_reclaim": int(len(gold)),
                "v3_cross_regime_support_reclaim": int(len(v3)),
                "warming_support_relevance": int(len(support_relevance)),
                "rotation_next_session_diagnostic": int(
                    len(rotation_next_session)
                ),
                "three_phase_adaptive_diagnostic": int(
                    len(three_phase_adaptive)
                ),
            },
            "decision_reason_counts": dict(sorted(decision_reason_counts.items())),
            "confirmation_status_counts": dict(sorted(confirmation_counts.items())),
            "same_close_execution": "research_proxy",
            "diagnostic_policies": {
                ROTATION_NEXT_SESSION_POLICY_VERSION: {
                    "registered_before_first_natural_scope": True,
                    "recommendations_created": 0,
                    "orders_created": 0,
                },
                THREE_PHASE_ADAPTIVE_POLICY_VERSION: {
                    "registered_before_first_natural_scope": True,
                    "qualification_contract_version": THREE_PHASE_QUALIFICATION_CONTRACT_VERSION,
                    "recommendations_created": 0,
                    "orders_created": 0,
                },
            },
            "formal_metrics": None,
        },
    )
    return ForwardMa5Capture(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=prepared.source_trade_date,
        signal_trade_date=prepared.signal_trade_date,
        input_fingerprint=fingerprint,
        rows=rows,
        scopes=(scope,),
    )


def blocked_causal_forward_capture(
    *,
    source_trade_date: date,
    signal_trade_date: date,
    attempted_at: datetime,
    reason: str,
) -> ForwardMa5Capture:
    """Persist an explicitly incomplete scope that may be retried later."""

    payload = {
        "contract_version": FORWARD_CONTRACT_VERSION,
        "source_trade_date": source_trade_date.isoformat(),
        "signal_trade_date": signal_trade_date.isoformat(),
        "reason": str(reason),
    }
    fingerprint = "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    scope = ForwardMa5Scope(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=source_trade_date,
        signal_trade_date=signal_trade_date,
        identity_mode=FORWARD_IDENTITY_MODE,
        known_at=attempted_at,
        complete=False,
        status="blocked",
        prior_top3_count=0,
        unique_candidate_count=0,
        active_concept_count=0,
        signal_count=0,
        selected_mode_at_capture=FORWARD_IDENTITY_MODE,
        input_fingerprint=fingerprint,
        evidence_level=FORWARD_EVIDENCE_LEVEL,
        raw={"blocking_reason": str(reason), "formal_metrics": None},
    )
    return ForwardMa5Capture(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=source_trade_date,
        signal_trade_date=signal_trade_date,
        input_fingerprint=fingerprint,
        rows=(),
        scopes=(scope,),
    )


def evaluate_causal_forward_outcomes(
    candidates: pd.DataFrame,
    campaign_paths: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    completed_dates: Sequence[date],
) -> pd.DataFrame:
    """Advance frozen eligible candidates with the same D-close exit algorithm."""

    required = {
        "contract_version",
        "source_trade_date",
        "signal_trade_date",
        "identity_mode",
        "vt_symbol",
        "signal_eligible",
        "input_fingerprint",
        "raw",
    }
    _require_columns(candidates, required, "causal forward candidate")
    eligible = candidates.loc[
        candidates["contract_version"].eq(FORWARD_CONTRACT_VERSION)
        & candidates["identity_mode"].eq(FORWARD_IDENTITY_MODE)
        & candidates["signal_eligible"].astype(bool)
    ].copy()
    if eligible.empty:
        return pd.DataFrame(columns=_outcome_columns())

    features = build_causal_stock_features(stock_bars)
    path_frame = campaign_paths.copy()
    path_frame["trade_date"] = pd.to_datetime(
        path_frame["trade_date"], errors="raise"
    ).dt.normalize()
    completed = tuple(sorted(set(completed_dates)))
    last_evaluated = max(completed) if completed else None
    rows: list[dict[str, object]] = []
    for candidate in eligible.sort_values(
        ["signal_trade_date", "vt_symbol"], kind="stable"
    ).to_dict("records"):
        raw = candidate.get("raw") if isinstance(candidate.get("raw"), Mapping) else {}
        signal = raw.get("signal") if isinstance(raw, Mapping) else None
        if not isinstance(signal, Mapping):
            raise ValueError("causal forward candidate is missing its frozen signal")
        campaign_id = str(signal["campaign_id"])
        vt_symbol = str(candidate["vt_symbol"])
        concept_path = path_frame.loc[path_frame["campaign_id"].astype(str).eq(campaign_id)]
        stock_path = features.loc[features["vt_symbol"].astype(str).eq(vt_symbol)]
        replay_path = concept_path.merge(
            stock_path.loc[:, ["trade_date", *STOCK_PATH_FEATURE_COLUMNS]],
            on="trade_date",
            how="inner",
            validate="one_to_one",
        )
        replay_path["vt_symbol"] = vt_symbol
        replay_path["stock_name"] = str(candidate.get("stock_name") or "")
        replay_path["dynamic_rank"] = int(signal["dynamic_rank"])
        replay_path["dynamic_top3"] = True
        replay_path["feature_cutoff_date"] = replay_path["trade_date"]
        trade = execute_close_trades(pd.DataFrame([dict(signal)]), replay_path).iloc[0]
        entry_price = float(trade["entry_price"])
        exit_date = _optional_date(trade.get("exit_date"))
        d1_date = _optional_date(trade.get("d1_date"))
        observation_end = pd.Timestamp(exit_date or last_evaluated) if (
            exit_date is not None or last_evaluated is not None
        ) else None
        observed = replay_path.loc[
            replay_path["trade_date"].ge(pd.Timestamp(signal["signal_date"]))
            & (
                replay_path["trade_date"].le(observation_end)
                if observation_end is not None
                else True
            )
        ]
        mae = (
            (float(observed["low_price"].min()) / entry_price - 1.0) * 100.0
            if not observed.empty
            else None
        )
        mfe = (
            (float(observed["high_price"].max()) / entry_price - 1.0) * 100.0
            if not observed.empty
            else None
        )
        net_return = _finite_or_none(trade.get("net_return_pct"))
        d2_shadow = _d2_fast_limit_shadow(
            signal,
            replay_path,
            entry_price=entry_price,
            original_net_return_pct=net_return,
        )
        rows.append(
            {
                "contract_version": FORWARD_CONTRACT_VERSION,
                "source_trade_date": _as_date(candidate["source_trade_date"]),
                "signal_trade_date": _as_date(candidate["signal_trade_date"]),
                "identity_mode": FORWARD_IDENTITY_MODE,
                "vt_symbol": vt_symbol,
                "candidate_input_fingerprint": str(candidate["input_fingerprint"]),
                "status": (
                    "closed"
                    if exit_date is not None
                    else "awaiting_d1"
                    if d1_date is None
                    else "open"
                ),
                "entry_date": _as_date(candidate["signal_trade_date"]),
                "entry_price": entry_price,
                "entry_proxy": "same_completed_session_close_research_proxy",
                "exit_date": exit_date,
                "exit_price": _finite_or_none(trade.get("exit_price")),
                "exit_reason": (
                    str(trade["exit_reason"]) if exit_date is not None else None
                ),
                "gross_return_pct": (
                    net_return + ROUND_TRIP_COST_PCT
                    if net_return is not None
                    else None
                ),
                "net_return_pct": net_return,
                "mae_pct": mae,
                "mfe_pct": mfe,
                "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
                "right_censored": False,
                "terminal": exit_date is not None,
                "last_evaluated_trade_date": last_evaluated,
                "raw": {
                    "algorithm_version": ALGORITHM_VERSION,
                    "signal_id": str(signal["signal_id"]),
                    "d1_date": d1_date.isoformat() if d1_date else None,
                    "d1_close": _finite_or_none(trade.get("d1_close")),
                    "d1_net_return_pct": _finite_or_none(
                        trade.get("d1_net_return_pct")
                    ),
                    "holding_sessions": _optional_int(
                        trade.get("holding_sessions")
                    ),
                    "d2_fast_limit_shadow": d2_shadow,
                },
            }
        )
    return pd.DataFrame.from_records(rows, columns=_outcome_columns())


def _d2_fast_limit_shadow(
    signal: Mapping[str, object],
    replay_path: pd.DataFrame,
    *,
    entry_price: float,
    original_net_return_pct: float | None,
) -> dict[str, object]:
    """Evaluate the frozen D+1 high-open limit-up hold-to-D+2 shadow."""

    signal_date = pd.Timestamp(signal["signal_date"]).normalize()
    later = replay_path.loc[replay_path["trade_date"].gt(signal_date)].sort_values(
        "trade_date", kind="stable"
    )
    if later.empty:
        return {"version": "d2-fast-limit-shadow-v1", "status": "awaiting_d1"}
    d1 = later.iloc[0]
    open_gain_pct = (float(d1["open_price"]) / entry_price - 1.0) * 100.0
    close_gain_pct = (float(d1["close_price"]) / entry_price - 1.0) * 100.0
    triggered = open_gain_pct >= 7.0 and close_gain_pct >= 9.5
    result: dict[str, object] = {
        "version": "d2-fast-limit-shadow-v1",
        "status": "awaiting_d2" if triggered else "not_triggered",
        "triggered": triggered,
        "d1_date": pd.Timestamp(d1["trade_date"]).date().isoformat(),
        "d1_open_gain_pct": round(open_gain_pct, 4),
        "d1_close_gain_pct": round(close_gain_pct, 4),
        "original_net_return_pct": original_net_return_pct,
    }
    if not triggered or len(later) < 2:
        return result
    d2 = later.iloc[1]
    d2_net_return_pct = (
        (float(d2["close_price"]) / entry_price - 1.0) * 100.0
        - ROUND_TRIP_COST_PCT
    )
    result.update(
        {
            "status": "settled",
            "d2_date": pd.Timestamp(d2["trade_date"]).date().isoformat(),
            "d2_close": round(float(d2["close_price"]), 4),
            "d2_net_return_pct": round(d2_net_return_pct, 4),
            "return_delta_pct_points": (
                round(d2_net_return_pct - original_net_return_pct, 4)
                if original_net_return_pct is not None
                else None
            ),
        }
    )
    return result


def _prepare_inputs(inputs: CausalForwardInputs) -> CausalForwardInputs:
    if inputs.attempted_at.tzinfo is None or inputs.attempted_at.utcoffset() is None:
        raise ValueError("attempted_at must be timezone-aware")
    if inputs.source_trade_date >= inputs.signal_trade_date:
        raise ValueError("source trade date must precede signal trade date")
    local_attempt = inputs.attempted_at.astimezone(SHANGHAI)
    if (
        local_attempt.date() != inputs.signal_trade_date
        or local_attempt.time().replace(tzinfo=None) < FEATURE_CUTOFF_TIME
    ):
        raise ValueError("causal forward capture must run after the signal close")
    _validate_scope(inputs.membership_scope, inputs.source_trade_date, "membership")
    _validate_scope(inputs.security_scope, inputs.source_trade_date, "security")

    paths = inputs.campaign_paths.copy()
    memberships = inputs.memberships.copy()
    securities = inputs.securities.copy()
    bars = inputs.stock_bars.copy()
    timing = inputs.market_timing.copy()
    _require_columns(
        paths,
        {
            "campaign_id",
            "sector_id",
            "concept_name",
            "anchor_date",
            "trade_date",
            "campaign_day",
            "cumulative_gain_pct",
            "campaign_active",
        },
        "causal campaign path",
    )
    _require_columns(
        memberships,
        {"source_trade_date", "sector_id", "vt_symbol", "evidence_level"},
        "strict forward membership",
    )
    _require_columns(
        securities,
        {
            "source_trade_date",
            "vt_symbol",
            "symbol",
            "exchange",
            "name",
            "status",
            "listed_on",
            "delisted_on",
            "suspended",
            "risk_warning",
            "evidence_level",
        },
        "strict forward security",
    )
    _require_columns(
        bars,
        {
            "vt_symbol",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "turnover",
        },
        "causal forward stock bar",
    )
    _require_columns(
        timing,
        {"source_date", "active_direction", "danger_state", "market_phase"},
        "causal forward market timing",
    )
    paths["trade_date"] = pd.to_datetime(paths["trade_date"], errors="raise").dt.normalize()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    timing["source_date"] = pd.to_datetime(
        timing["source_date"], errors="raise"
    ).dt.normalize()
    if paths["trade_date"].dt.date.gt(inputs.signal_trade_date).any():
        raise ValueError("campaign paths contain future dates")
    if bars["trade_date"].dt.date.gt(inputs.signal_trade_date).any():
        raise ValueError("stock bars contain future dates")
    if timing["source_date"].dt.date.gt(inputs.signal_trade_date).any():
        raise ValueError("market timing contains future dates")
    if not memberships["source_trade_date"].map(_as_date).eq(inputs.source_trade_date).all():
        raise ValueError("membership rows do not match the source date")
    if not securities["source_trade_date"].map(_as_date).eq(inputs.source_trade_date).all():
        raise ValueError("security rows do not match the source date")
    if not memberships["evidence_level"].astype(str).eq("strict").all():
        raise ValueError("strict forward memberships are required")
    if not securities["evidence_level"].astype(str).eq("strict").all():
        raise ValueError("strict forward securities are required")
    if memberships.duplicated(["sector_id", "vt_symbol"]).any():
        raise ValueError("membership identities must be unique")
    if securities.duplicated(["vt_symbol"]).any():
        raise ValueError("security identities must be unique")
    return CausalForwardInputs(
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        attempted_at=inputs.attempted_at,
        membership_scope=dict(inputs.membership_scope),
        security_scope=dict(inputs.security_scope),
        campaign_paths=paths,
        memberships=memberships,
        securities=securities,
        stock_bars=bars,
        market_timing=timing,
    )


def _validate_scope(scope: Mapping[str, Any], source_date: date, label: str) -> None:
    if _as_date(scope.get("source_trade_date")) != source_date:
        raise ValueError(f"{label} scope source date mismatch")
    if not bool(scope.get("complete")) or str(scope.get("evidence_level")) != "strict":
        raise ValueError(f"{label} scope is not strict and complete")


def _eligible_memberships(inputs: CausalForwardInputs) -> pd.DataFrame:
    securities = inputs.securities.copy()
    calendar = pd.DatetimeIndex(inputs.stock_bars["trade_date"].unique()).sort_values()
    reasons: dict[str, str | None] = {}
    for row in securities.to_dict("records"):
        listed_on = _as_date(row["listed_on"])
        listed_sessions = int(
            ((calendar.date >= listed_on) & (calendar.date <= inputs.source_trade_date)).sum()
        )
        delisted_on = _optional_date(row.get("delisted_on"))
        reasons[str(row["vt_symbol"])] = eligibility_reason(
            SecurityRecord(
                vt_symbol=str(row["vt_symbol"]),
                symbol=str(row["symbol"]),
                exchange=str(row["exchange"]),
                name=str(row["name"]),
                status=str(row["status"]),
                listed_sessions=listed_sessions,
                suspended=bool(row["suspended"]),
                risk_warning=bool(row["risk_warning"]),
                delisted=bool(delisted_on and delisted_on <= inputs.source_trade_date),
                evidence_level=str(row["evidence_level"]),
            ),
            inputs.source_trade_date,
        )
    names = securities.set_index("vt_symbol")["name"].astype(str)
    result = inputs.memberships.copy()
    result["stock_name"] = result["vt_symbol"].map(names).fillna("")
    result["exclusion_reason"] = [
        reasons.get(str(vt_symbol), "security_snapshot_missing")
        for vt_symbol in result["vt_symbol"]
    ]
    return result.loc[
        result["exclusion_reason"].isna(),
        ["sector_id", "vt_symbol", "stock_name"],
    ].reset_index(drop=True)


def _deduplicate_signal_concepts(
    signals: pd.DataFrame,
    eligible_ids: set[str],
) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    result = signals.copy()
    result["_eligible_order"] = ~result["signal_id"].astype(str).isin(
        eligible_ids
    )
    return (
        result.sort_values(
            ["_eligible_order", "dynamic_rank", "signal_id"], kind="stable"
        )
        .drop_duplicates(["vt_symbol"], keep="first")
        .drop(columns="_eligible_order")
        .reset_index(drop=True)
    )


def _candidate_row(
    inputs: CausalForwardInputs,
    signal: Mapping[str, Any],
    *,
    path_lookup: pd.DataFrame,
    feature_lookup: pd.DataFrame,
    eligible_ids: set[str],
    diagnostic_ids: set[str],
    three_phase_diagnostic_ids: set[str],
    fingerprint: str,
) -> ForwardMa5CandidateRow:
    signal_date = pd.Timestamp(inputs.signal_trade_date)
    key = (str(signal["campaign_id"]), str(signal["vt_symbol"]), signal_date)
    path_row = path_lookup.loc[key]
    feature_row = feature_lookup.loc[(str(signal["vt_symbol"]), signal_date)]
    campaign_path = path_lookup.loc[
        (str(signal["campaign_id"]), str(signal["vt_symbol"]))
    ]
    volume_ratio = _finite_or_none(signal.get("volume_ratio_prior5"))
    base_close = _finite_or_none(path_row.get("leader_leg_base_close"))
    reference_peak = float(signal["reference_peak_price"])
    raw_signal = _json_safe(dict(signal))
    eligible = str(signal["signal_id"]) in eligible_ids
    diagnostic_eligible = str(signal["signal_id"]) in diagnostic_ids
    three_phase_diagnostic_eligible = (
        str(signal["signal_id"]) in three_phase_diagnostic_ids
    )
    decision_reason = explain_warming_support_relevance_signal(signal)
    timing_known_at = _timing_known_at(inputs.market_timing, inputs.attempted_at)
    return ForwardMa5CandidateRow(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        identity_mode=FORWARD_IDENTITY_MODE,
        vt_symbol=str(signal["vt_symbol"]),
        stock_name=str(signal["stock_name"]),
        sector_id=str(signal["sector_id"]),
        sector_name=str(signal["concept_name"]),
        rank=int(signal["dynamic_rank"]),
        known_at=inputs.attempted_at,
        feature_cutoff_date=inputs.signal_trade_date,
        spell_anchor_date=pd.Timestamp(path_row["anchor_date"]).date(),
        spell_age_sessions=int(path_row["campaign_day"]) + 1,
        observation_limit_sessions=0,
        current_wave_number=int(signal["wave_number"]),
        confirmed_higher_highs=max(int(signal["wave_number"]) - 1, 0),
        wave_start_date=(
            pd.Timestamp(path_row.get("leader_ignition_date")).date()
            if pd.notna(path_row.get("leader_ignition_date"))
            else pd.Timestamp(path_row["anchor_date"]).date()
        ),
        reference_peak_date=pd.Timestamp(signal["reference_peak_date"]).date(),
        reference_peak_price=reference_peak,
        pullback_confirmation_date=inputs.signal_trade_date,
        support_line=str(signal["support_line"]),
        support_price=float(signal["support_price"]),
        line_distance_low_pct=(
            float(signal["signal_low"]) / float(signal["support_price"]) - 1.0
        )
        * 100.0,
        line_distance_close_pct=(
            float(signal["signal_close"]) / float(signal["support_price"]) - 1.0
        )
        * 100.0,
        signal_close_not_below_previous=bool(
            float(signal["signal_close"]) >= float(feature_row["previous_close"])
        ),
        stock_structure_intact=bool(path_row["structure_intact"]),
        concept_main_rise_intact=bool(path_row["campaign_active"]),
        impulse_gain_pct=(
            (reference_peak / base_close - 1.0) * 100.0
            if base_close is not None and base_close > 0
            else 0.0
        ),
        strong_days_ge_9_5pct=int(path_row["strong_days_since_ignition"]),
        max_volume_ratio_prior5=_finite_or_none(
            pd.to_numeric(
                campaign_path["volume_ratio_prior5"], errors="coerce"
            ).max()
        ),
        xuguang_climax_candidate=False,
        volume_ratio_prior5=volume_ratio,
        volume_class_prior5=classify_volume_ratio(volume_ratio),
        stock_main_net_inflow=None,
        stock_main_net_inflow_ratio=None,
        stock_fund_flow_source=None,
        stock_fund_flow_known_at=None,
        sector_main_net_inflow=None,
        sector_main_net_inflow_ratio=None,
        sector_fund_flow_source=None,
        sector_fund_flow_known_at=None,
        market_timing_direction=str(signal["active_direction"]),
        market_timing_danger_state=str(signal["danger_state"]),
        market_timing_known_at=timing_known_at,
        signal_eligible=eligible,
        decision_reason=decision_reason,
        selected_mode_at_capture=FORWARD_IDENTITY_MODE,
        input_fingerprint=fingerprint,
        evidence_level=FORWARD_EVIDENCE_LEVEL,
        raw={
            "algorithm_version": ALGORITHM_VERSION,
            "policy_version": WARMING_SUPPORT_RELEVANCE_POLICY_VERSION,
            "variant": WARMING_SUPPORT_RELEVANCE_POLICY_VERSION,
            "legacy_variants": {
                "gold": GOLD_STRONG_RECLAIM_VARIANT,
                "v3_cross_regime": CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
            },
            "signal": raw_signal,
            "diagnostic_policies": {
                ROTATION_NEXT_SESSION_POLICY_VERSION: {
                    "signal_eligible": diagnostic_eligible,
                    "registered_before_first_natural_scope": True,
                },
                THREE_PHASE_ADAPTIVE_POLICY_VERSION: {
                    "signal_eligible": three_phase_diagnostic_eligible,
                    "registered_before_first_natural_scope": True,
                    "qualification_contract_version": THREE_PHASE_QUALIFICATION_CONTRACT_VERSION,
                },
            },
            "same_close_execution": "research_proxy",
            "minutes_used": False,
            "fund_flow_used": False,
        },
    )


def _empty_capture(
    inputs: CausalForwardInputs,
    fingerprint: str,
    *,
    status: str,
) -> ForwardMa5Capture:
    scope = ForwardMa5Scope(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        identity_mode=FORWARD_IDENTITY_MODE,
        known_at=inputs.attempted_at,
        complete=True,
        status=status,
        prior_top3_count=0,
        unique_candidate_count=0,
        active_concept_count=0,
        signal_count=0,
        selected_mode_at_capture=FORWARD_IDENTITY_MODE,
        input_fingerprint=fingerprint,
        evidence_level=FORWARD_EVIDENCE_LEVEL,
        raw={
            "algorithm_version": ALGORITHM_VERSION,
            "policy_version": WARMING_SUPPORT_RELEVANCE_POLICY_VERSION,
            "diagnostic_policies": {
                ROTATION_NEXT_SESSION_POLICY_VERSION: {
                    "registered_before_first_natural_scope": True,
                    "recommendations_created": 0,
                    "orders_created": 0,
                },
                THREE_PHASE_ADAPTIVE_POLICY_VERSION: {
                    "registered_before_first_natural_scope": True,
                    "qualification_contract_version": THREE_PHASE_QUALIFICATION_CONTRACT_VERSION,
                    "recommendations_created": 0,
                    "orders_created": 0,
                },
            },
            "formal_metrics": None,
        },
    )
    return ForwardMa5Capture(
        contract_version=FORWARD_CONTRACT_VERSION,
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        input_fingerprint=fingerprint,
        rows=(),
        scopes=(scope,),
    )


def _input_fingerprint(inputs: CausalForwardInputs) -> str:
    frames = {
        "campaign_paths": (
            inputs.campaign_paths,
            ("campaign_id", "trade_date"),
        ),
        "memberships": (
            inputs.memberships,
            ("sector_id", "vt_symbol"),
        ),
        "securities": (inputs.securities, ("vt_symbol",)),
        "stock_bars": (inputs.stock_bars, ("vt_symbol", "trade_date")),
        "market_timing": (inputs.market_timing, ("source_date",)),
    }
    components = {
        name: fingerprint_frame(frame, identity_columns=identity).digest
        for name, (frame, identity) in frames.items()
    }
    payload = {
        "contract_version": FORWARD_CONTRACT_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "policy_version": WARMING_SUPPORT_RELEVANCE_POLICY_VERSION,
        "source_trade_date": inputs.source_trade_date.isoformat(),
        "signal_trade_date": inputs.signal_trade_date.isoformat(),
        "components": components,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _timing_known_at(frame: pd.DataFrame, fallback: datetime) -> datetime:
    if "known_at" not in frame or frame["known_at"].isna().all():
        return fallback
    known = pd.to_datetime(frame["known_at"], errors="coerce", utc=True).dropna()
    return known.max().to_pydatetime() if not known.empty else fallback


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
        "raw",
    ]


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if pd.isna(value):
        return None
    return value


def _as_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.Timestamp(value).date()


def _optional_date(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None
    return _as_date(value)


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
