"""Immutable persistence and natural-date orchestration for causal low suction."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, insert, select, update

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff

from .baostock_security_source import FORWARD_SECURITY_SOURCE
from .causal_leader_pullback import (
    CONCEPT_ANCHOR_MODE,
    CONCEPT_EXIT_CONFIRM_SESSIONS,
    CONCEPT_EXIT_DRAWDOWN_PCT,
    ROTATION_NEXT_SESSION_POLICY_VERSION,
    THREE_PHASE_ADAPTIVE_POLICY_VERSION,
)
from .causal_leader_pullback_forward import (
    FEATURE_CUTOFF_TIME,
    FORWARD_CONTRACT_VERSION,
    FORWARD_EVIDENCE_LEVEL,
    FORWARD_IDENTITY_MODE,
    THREE_PHASE_QUALIFICATION_CONTRACT_VERSION,
    CausalForwardInputs,
    blocked_causal_forward_capture,
    build_causal_forward_capture,
    evaluate_causal_forward_outcomes,
)
from .causal_leader_pullback_study import (
    build_concept_campaign_ledger,
    simulate_four_slot_cash,
)
from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE
from .contracts import CONCEPT_SECTOR_TYPES
from .dynamic_concept_campaign import build_exploratory_campaigns
from .forward_leader_identity import FORWARD_LEADER_RANKING_VERSION
from .forward_ma5_pullback import ForwardMa5Capture
from .forward_membership import (
    FORWARD_MEMBERSHIP_SOURCE,
    TRADABLE_SCOPE_TYPE,
)
from .leader_identity import LeaderIdentityMode

SHANGHAI = ZoneInfo("Asia/Shanghai")
MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3_000
STOCK_HISTORY_BUFFER_DAYS = 120

CONCEPT_BAR_COLUMNS = (
    "sector_id",
    "concept_name",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "source",
)
STOCK_BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "change_pct",
    "source",
)


class CausalForwardLedgerImmutableError(RuntimeError):
    """Raised when immutable V2 capture or outcome evidence would change."""


@dataclass(frozen=True)
class ForwardMa5SaveResult:
    status: str
    rows_written: int
    scopes_written: int
    input_fingerprint: str


def save_causal_forward_capture(capture: ForwardMa5Capture) -> ForwardMa5SaveResult:
    """Persist one V2 scope while allowing only same-day blocked recovery."""

    _validate_capture(capture)
    engine = get_engine()
    schema.ensure_schema_once(engine)
    candidates = schema.low_suction_forward_ma5_candidates
    scopes = schema.low_suction_forward_ma5_scopes
    with session_scope() as session:
        existing = session.execute(
            select(
                scopes.c.identity_mode,
                scopes.c.complete,
                scopes.c.input_fingerprint,
            ).where(
                scopes.c.contract_version == FORWARD_CONTRACT_VERSION,
                scopes.c.signal_trade_date == capture.signal_trade_date,
            )
        ).mappings().all()
        decision = _existing_capture_decision(existing, capture)
        if decision is not None:
            return ForwardMa5SaveResult(
                status=decision,
                rows_written=0,
                scopes_written=0,
                input_fingerprint=capture.input_fingerprint,
            )

        _require_natural_write_time(capture)
        if existing:
            session.execute(
                delete(candidates).where(
                    candidates.c.contract_version == FORWARD_CONTRACT_VERSION,
                    candidates.c.signal_trade_date == capture.signal_trade_date,
                )
            )
            session.execute(
                delete(scopes).where(
                    scopes.c.contract_version == FORWARD_CONTRACT_VERSION,
                    scopes.c.signal_trade_date == capture.signal_trade_date,
                )
            )
        if capture.rows:
            session.execute(insert(candidates), [asdict(row) for row in capture.rows])
        session.execute(insert(scopes), [asdict(capture.scopes[0])])
    return ForwardMa5SaveResult(
        status="frozen" if capture.complete else "blocked",
        rows_written=len(capture.rows),
        scopes_written=1,
        input_fingerprint=capture.input_fingerprint,
    )


def save_causal_forward_outcomes(outcomes: pd.DataFrame) -> dict[str, int]:
    """Insert outcome states and advance only nonterminal V2 rows."""

    if outcomes.empty:
        return {"inserted": 0, "updated": 0, "terminal_preserved": 0}
    required = {
        "contract_version",
        "signal_trade_date",
        "identity_mode",
        "vt_symbol",
        "candidate_input_fingerprint",
        "terminal",
        "status",
    }
    _require_columns(outcomes, required, "causal forward outcome")
    if not outcomes["contract_version"].astype(str).eq(FORWARD_CONTRACT_VERSION).all():
        raise ValueError("causal forward outcome requires the V2 contract version")
    if not outcomes["identity_mode"].astype(str).eq(FORWARD_IDENTITY_MODE).all():
        raise ValueError("causal forward outcome requires the V2 identity mode")
    identities = outcomes.loc[
        :, ["contract_version", "signal_trade_date", "identity_mode", "vt_symbol"]
    ]
    if identities.duplicated().any():
        raise ValueError("causal forward outcome identity must be unique")

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.low_suction_forward_ma5_outcomes
    counts = {"inserted": 0, "updated": 0, "terminal_preserved": 0}
    with session_scope() as session:
        for raw in outcomes.to_dict("records"):
            values = _outcome_values(raw)
            identity = _outcome_identity_predicate(table, values)
            existing_rows = session.execute(select(table).where(identity)).mappings().all()
            if len(existing_rows) > 1:
                raise CausalForwardLedgerImmutableError(
                    "causal forward outcome identity is duplicated"
                )
            if not existing_rows:
                session.execute(insert(table).values(**values))
                counts["inserted"] += 1
                continue
            existing = existing_rows[0]
            if str(existing.get("candidate_input_fingerprint") or "") != str(
                values["candidate_input_fingerprint"]
            ):
                raise CausalForwardLedgerImmutableError(
                    "causal forward outcome candidate fingerprint changed"
                )
            if bool(existing.get("terminal")):
                merged_raw = _terminal_raw_with_d2_shadow(
                    existing.get("raw"), values.get("raw")
                )
                if merged_raw is not None:
                    session.execute(
                        update(table).where(identity).values(raw=merged_raw)
                    )
                    counts["updated"] += 1
                    continue
                counts["terminal_preserved"] += 1
                continue
            session.execute(update(table).where(identity).values(**values))
            counts["updated"] += 1
    return counts


def _terminal_raw_with_d2_shadow(
    existing_raw: object,
    evaluated_raw: object,
) -> dict[str, object] | None:
    """Enrich only the shadow field while preserving terminal trade facts."""

    if not isinstance(existing_raw, Mapping) or not isinstance(evaluated_raw, Mapping):
        return None
    incoming = evaluated_raw.get("d2_fast_limit_shadow")
    if not isinstance(incoming, Mapping):
        return None
    current = existing_raw.get("d2_fast_limit_shadow")
    if current == incoming:
        return None
    merged = dict(existing_raw)
    merged["d2_fast_limit_shadow"] = dict(incoming)
    return merged


def load_causal_forward_inputs(
    source_trade_date: date,
    signal_trade_date: date,
    *,
    attempted_at: datetime,
) -> CausalForwardInputs:
    """Load strict D-1 snapshots and D-close data for one natural session."""

    _require_aware(attempted_at, "attempted_at")
    if source_trade_date >= signal_trade_date:
        raise ValueError("source trade date must precede signal trade date")
    if attempted_at.astimezone(SHANGHAI).date() != signal_trade_date:
        raise ValueError("causal forward inputs require the natural signal date")

    return _load_causal_inputs(
        source_trade_date,
        signal_trade_date,
        data_known_at=attempted_at,
        capture_attempted_at=attempted_at,
    )


def load_causal_replay_inputs(
    source_trade_date: date,
    signal_trade_date: date,
    *,
    evaluated_at: datetime,
) -> CausalForwardInputs:
    """Load a non-persistable point-in-time replay with an explicit audit clock."""

    _require_aware(evaluated_at, "evaluated_at")
    if source_trade_date >= signal_trade_date:
        raise ValueError("source trade date must precede signal trade date")
    if evaluated_at.astimezone(SHANGHAI).date() < signal_trade_date:
        raise ValueError("causal replay cannot be evaluated before its signal date")
    feature_clock = datetime.combine(
        signal_trade_date,
        FEATURE_CUTOFF_TIME,
        tzinfo=SHANGHAI,
    )
    return _load_causal_inputs(
        source_trade_date,
        signal_trade_date,
        data_known_at=evaluated_at,
        capture_attempted_at=feature_clock,
    )


def _load_causal_inputs(
    source_trade_date: date,
    signal_trade_date: date,
    *,
    data_known_at: datetime,
    capture_attempted_at: datetime,
) -> CausalForwardInputs:
    """Load shared strict inputs for either natural capture or labeled replay."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    base = _snapshot_statements(source_trade_date, attempted_at=data_known_at)
    with session_scope() as session:
        membership_scope = session.execute(
            base["membership_scope"]
        ).mappings().one_or_none()
        security_scope = session.execute(
            base["security_scope"]
        ).mappings().one_or_none()
        membership_rows = session.execute(
            base["membership_rows"]
        ).mappings().all()
        security_rows = session.execute(base["security_rows"]).mappings().all()
        timing_rows = session.execute(base["market_timing_panel"]).mappings().all()

    _require_ready_scope(membership_scope, source_trade_date, "membership")
    _require_ready_scope(security_scope, source_trade_date, "security")
    memberships = pd.DataFrame(membership_rows)
    securities = pd.DataFrame(security_rows)
    sector_ids = tuple(sorted(set(memberships.get("sector_id", pd.Series(dtype=str)).astype(str))))
    concept_bars = pd.read_sql(
        _concept_bars_statement(sector_ids, end=signal_trade_date),
        engine,
        parse_dates=["trade_date"],
    )
    campaign_paths = _signal_campaign_paths(concept_bars, signal_trade_date)
    active_sector_ids = set(
        campaign_paths.get("sector_id", pd.Series(dtype=str)).astype(str)
    )
    memberships = memberships.loc[
        memberships.get("sector_id", pd.Series(dtype=str)).astype(str).isin(
            active_sector_ids
        )
    ].copy()
    active_symbols = tuple(
        sorted(set(memberships.get("vt_symbol", pd.Series(dtype=str)).astype(str)))
    )
    securities = securities.loc[
        securities.get("vt_symbol", pd.Series(dtype=str)).astype(str).isin(
            active_symbols
        )
    ].copy()
    stock_start = _stock_history_start(campaign_paths, signal_trade_date)
    stock_bars = pd.read_sql(
        _stock_bars_statement(active_symbols, start=stock_start, end=signal_trade_date),
        engine,
        parse_dates=["trade_date"],
    )
    return CausalForwardInputs(
        source_trade_date=source_trade_date,
        signal_trade_date=signal_trade_date,
        attempted_at=capture_attempted_at,
        membership_scope=dict(membership_scope or {}),
        security_scope=dict(security_scope or {}),
        campaign_paths=pd.DataFrame(campaign_paths),
        memberships=pd.DataFrame(memberships),
        securities=pd.DataFrame(securities),
        stock_bars=pd.DataFrame(stock_bars, columns=STOCK_BAR_COLUMNS),
        market_timing=_timing_frame(timing_rows, cutoff=signal_trade_date),
    )


def evaluate_causal_candidate_outcomes(
    candidates: pd.DataFrame,
    *,
    as_of_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate frozen candidate rows without persisting any result."""

    if candidates.empty:
        return pd.DataFrame(), pd.DataFrame(columns=STOCK_BAR_COLUMNS)
    required = {
        "sector_id",
        "vt_symbol",
        "spell_anchor_date",
        "raw",
    }
    _require_columns(candidates, required, "causal forward candidate evaluation")
    engine = get_engine()
    schema.ensure_schema_once(engine)
    sector_ids = tuple(sorted(set(candidates["sector_id"].astype(str))))
    concept_bars = pd.read_sql(
        _concept_bars_statement(sector_ids, end=as_of_date),
        engine,
        parse_dates=["trade_date"],
    )
    campaign_paths = _reconstruct_frozen_campaign_paths(candidates, concept_bars)

    symbols = tuple(sorted(set(candidates["vt_symbol"].astype(str))))
    anchor_dates = candidates["spell_anchor_date"].map(_as_date)
    stock_start = min(anchor_dates) - timedelta(days=STOCK_HISTORY_BUFFER_DAYS)
    stock_bars = pd.read_sql(
        _stock_bars_statement(symbols, start=stock_start, end=as_of_date),
        engine,
        parse_dates=["trade_date"],
    )
    with session_scope() as session:
        completed_dates = tuple(
            session.execute(
                _completed_dates_statement(as_of_date, start=stock_start)
            ).scalars()
        )
    outcomes = evaluate_causal_forward_outcomes(
        candidates,
        campaign_paths,
        stock_bars,
        completed_dates=completed_dates,
    )
    return outcomes, pd.DataFrame(stock_bars, columns=STOCK_BAR_COLUMNS)


def settle_causal_forward_outcomes(*, as_of_date: date) -> dict[str, int]:
    """Advance every main or pre-registered diagnostic signal through daily bars."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    candidates = schema.low_suction_forward_ma5_candidates
    with session_scope() as session:
        candidate_rows = session.execute(
            select(candidates)
            .where(
                candidates.c.contract_version == FORWARD_CONTRACT_VERSION,
                candidates.c.identity_mode == FORWARD_IDENTITY_MODE,
                candidates.c.signal_trade_date <= as_of_date,
            )
            .order_by(candidates.c.signal_trade_date, candidates.c.vt_symbol)
        ).mappings().all()
    candidate_rows = [
        row for row in candidate_rows if _candidate_requires_outcome(row)
    ]
    if not candidate_rows:
        return {
            "evaluated": 0,
            "inserted": 0,
            "updated": 0,
            "terminal_preserved": 0,
        }

    outcomes, _stock_bars = evaluate_causal_candidate_outcomes(
        pd.DataFrame(candidate_rows),
        as_of_date=as_of_date,
    )
    saved = save_causal_forward_outcomes(outcomes)
    return {"evaluated": int(len(outcomes)), **saved}


def _candidate_requires_outcome(candidate: Mapping[str, object]) -> bool:
    if bool(candidate.get("signal_eligible")):
        return True
    raw = candidate.get("raw")
    policies = raw.get("diagnostic_policies") if isinstance(raw, Mapping) else None
    if not isinstance(policies, Mapping):
        return False
    return any(
        isinstance(policy, Mapping) and bool(policy.get("signal_eligible"))
        for policy in policies.values()
    )


def advance_causal_forward(
    *,
    as_of_date: date,
    attempted_at: datetime,
) -> dict[str, object]:
    """Capture only today's natural D-close scope, then settle saved outcomes."""

    _require_aware(attempted_at, "attempted_at")
    local_attempt = attempted_at.astimezone(SHANGHAI)
    captures: list[dict[str, object]] = []
    blocking_reasons: list[str] = []

    if local_attempt.date() != as_of_date:
        blocking_reasons.append("historical_natural_capture_forbidden")
    else:
        pair = _natural_source_pair(as_of_date)
        if pair is None:
            blocking_reasons.append("strict_source_pair_unavailable")
        else:
            source_date, signal_date = pair
            capture = _capture_natural_pair(
                source_date,
                signal_date,
                attempted_at=attempted_at,
            )
            saved = save_causal_forward_capture(capture)
            captures.append(_capture_result(capture, saved))
            blocking_reasons.extend(
                str(scope.raw["blocking_reason"])
                for scope in capture.scopes
                if scope.raw.get("blocking_reason")
            )

    outcomes = settle_causal_forward_outcomes(as_of_date=as_of_date)
    return {
        "contract_version": FORWARD_CONTRACT_VERSION,
        "as_of_date": as_of_date.isoformat(),
        "captures": captures,
        "blocking_reasons": sorted(set(blocking_reasons)),
        "outcomes": outcomes,
        "recommendations_created": 0,
        "orders_created": 0,
        "formal_metrics": None,
    }


def load_causal_forward_report(
    *,
    as_of_date: date | None = None,
) -> dict[str, object]:
    """Return deterministic V2 coverage without promoting descriptive outcomes."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    cutoff = as_of_date or completed_daily_bar_cutoff()
    scopes = schema.low_suction_forward_ma5_scopes
    candidates = schema.low_suction_forward_ma5_candidates
    outcomes = schema.low_suction_forward_ma5_outcomes
    with session_scope() as session:
        scope_rows = session.execute(
            select(scopes)
            .where(
                scopes.c.contract_version == FORWARD_CONTRACT_VERSION,
                scopes.c.identity_mode == FORWARD_IDENTITY_MODE,
                scopes.c.signal_trade_date <= cutoff,
            )
            .order_by(scopes.c.signal_trade_date)
        ).mappings().all()
        candidate_rows = session.execute(
            select(candidates)
            .where(
                candidates.c.contract_version == FORWARD_CONTRACT_VERSION,
                candidates.c.identity_mode == FORWARD_IDENTITY_MODE,
                candidates.c.signal_trade_date <= cutoff,
            )
            .order_by(candidates.c.signal_trade_date, candidates.c.vt_symbol)
        ).mappings().all()
        outcome_rows = session.execute(
            select(outcomes)
            .where(
                outcomes.c.contract_version == FORWARD_CONTRACT_VERSION,
                outcomes.c.identity_mode == FORWARD_IDENTITY_MODE,
                outcomes.c.signal_trade_date <= cutoff,
            )
            .order_by(outcomes.c.signal_trade_date, outcomes.c.vt_symbol)
        ).mappings().all()
    candidate_frame = pd.DataFrame(candidate_rows)
    stock_bars = pd.DataFrame(columns=STOCK_BAR_COLUMNS)
    if not candidate_frame.empty:
        symbols = tuple(sorted(set(candidate_frame["vt_symbol"].astype(str))))
        start = min(candidate_frame["signal_trade_date"].map(_as_date))
        stock_bars = pd.read_sql(
            _stock_bars_statement(symbols, start=start, end=cutoff),
            engine,
            parse_dates=["trade_date"],
        )
    return build_causal_forward_report(
        pd.DataFrame(scope_rows),
        candidate_frame,
        pd.DataFrame(outcome_rows),
        as_of_date=cutoff,
        stock_bars=stock_bars,
    )


def list_causal_forward_ledger(
    *,
    page: int = 1,
    page_size: int = 20,
    signal_eligible: bool | None = None,
    terminal: bool | None = None,
) -> dict[str, object]:
    """Page immutable natural candidates together with their later outcomes."""

    if page < 1:
        raise ValueError("page must be positive")
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    engine = get_engine()
    schema.ensure_schema_once(engine)
    candidates = schema.low_suction_forward_ma5_candidates
    outcomes = schema.low_suction_forward_ma5_outcomes
    identity = (
        (candidates.c.contract_version == outcomes.c.contract_version)
        & (candidates.c.signal_trade_date == outcomes.c.signal_trade_date)
        & (candidates.c.identity_mode == outcomes.c.identity_mode)
        & (candidates.c.vt_symbol == outcomes.c.vt_symbol)
    )
    joined = candidates.outerjoin(outcomes, identity)
    predicates = [
        candidates.c.contract_version == FORWARD_CONTRACT_VERSION,
        candidates.c.identity_mode == FORWARD_IDENTITY_MODE,
    ]
    if signal_eligible is not None:
        predicates.append(candidates.c.signal_eligible.is_(signal_eligible))
    if terminal is not None:
        predicates.append(outcomes.c.terminal.is_(terminal))
    fields = (
        candidates.c.signal_trade_date,
        candidates.c.source_trade_date,
        candidates.c.vt_symbol,
        candidates.c.stock_name,
        candidates.c.sector_id,
        candidates.c.sector_name,
        candidates.c.rank,
        candidates.c.current_wave_number,
        candidates.c.confirmed_higher_highs,
        candidates.c.support_line,
        candidates.c.support_price,
        candidates.c.reference_peak_price,
        candidates.c.market_timing_direction,
        candidates.c.signal_eligible,
        candidates.c.decision_reason,
        candidates.c.known_at,
        candidates.c.evidence_level,
        candidates.c.input_fingerprint,
        outcomes.c.status.label("outcome_status"),
        outcomes.c.entry_date,
        outcomes.c.entry_price,
        outcomes.c.exit_date,
        outcomes.c.exit_price,
        outcomes.c.exit_reason,
        outcomes.c.net_return_pct,
        outcomes.c.terminal,
        outcomes.c.last_evaluated_trade_date,
    )
    count_statement = select(func.count()).select_from(joined).where(*predicates)
    rows_statement = (
        select(*fields)
        .select_from(joined)
        .where(*predicates)
        .order_by(candidates.c.signal_trade_date.desc(), candidates.c.vt_symbol.asc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    with session_scope() as session:
        total = int(session.execute(count_statement).scalar_one())
        rows = session.execute(rows_statement).mappings().all()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "contract_version": FORWARD_CONTRACT_VERSION,
        "qualification_contract_version": THREE_PHASE_QUALIFICATION_CONTRACT_VERSION,
        "historical_backfill_allowed": False,
    }


def load_d2_fast_limit_shadow_summary() -> dict[str, object]:
    """Summarize naturally settled D+2 shadow comparisons."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.low_suction_forward_ma5_outcomes
    with session_scope() as session:
        rows = session.execute(
            select(table.c.raw).where(
                table.c.contract_version == FORWARD_CONTRACT_VERSION,
                table.c.identity_mode == FORWARD_IDENTITY_MODE,
            )
        ).scalars().all()
    shadows = [
        raw.get("d2_fast_limit_shadow")
        for raw in rows
        if isinstance(raw, Mapping)
        and isinstance(raw.get("d2_fast_limit_shadow"), Mapping)
    ]
    triggered = [row for row in shadows if bool(row.get("triggered"))]
    settled = [row for row in triggered if row.get("status") == "settled"]
    deltas = [
        float(row["return_delta_pct_points"])
        for row in settled
        if row.get("return_delta_pct_points") is not None
    ]
    return {
        "version": "d2-fast-limit-shadow-v1",
        "trigger_rule": "d1_open_gain_gte_7_and_close_gain_gte_9_5",
        "target_samples": 20,
        "triggered": len(triggered),
        "settled": len(settled),
        "improved": sum(delta > 0 for delta in deltas),
        "mean_return_delta_pct_points": (
            round(sum(deltas) / len(deltas), 4) if deltas else None
        ),
        "eligible_for_review": len(settled) >= 20,
    }


def build_causal_forward_report(
    scopes: pd.DataFrame,
    candidates: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    as_of_date: date,
    stock_bars: pd.DataFrame | None = None,
) -> dict[str, object]:
    """Summarize one-mode natural evidence while keeping formal metrics null."""

    complete = _scope_dates(scopes, complete=True)
    blocked = _scope_dates(scopes, complete=False)
    signals = (
        candidates.loc[candidates["signal_eligible"].astype(bool)]
        if not candidates.empty and "signal_eligible" in candidates
        else pd.DataFrame()
    )
    closed = (
        outcomes.loc[outcomes["terminal"].astype(bool)]
        if not outcomes.empty and "terminal" in outcomes
        else pd.DataFrame()
    )
    net = (
        pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
        if not closed.empty and "net_return_pct" in closed
        else pd.Series(dtype=float)
    )
    funnel: Counter[str] = Counter()
    for raw in scopes.get("raw", pd.Series(dtype=object)):
        if not isinstance(raw, Mapping):
            continue
        values = raw.get("signal_funnel")
        if isinstance(values, Mapping):
            funnel.update({str(key): int(value) for key, value in values.items()})
    reasons = Counter(
        candidates.get("decision_reason", pd.Series(dtype=str)).dropna().astype(str)
    )
    blocking_reasons = sorted(
        {
            str(raw["blocking_reason"])
            for raw in scopes.get("raw", pd.Series(dtype=object))
            if isinstance(raw, Mapping) and raw.get("blocking_reason")
        }
    )
    diagnostic = _build_rotation_next_session_forward_diagnostic(
        candidates,
        closed,
        stock_bars=stock_bars,
    )
    three_phase_diagnostic = _build_three_phase_forward_diagnostic(
        candidates,
        closed,
        stock_bars=stock_bars,
    )
    return {
        "contract_version": FORWARD_CONTRACT_VERSION,
        "identity_mode": FORWARD_IDENTITY_MODE,
        "forward_sample": True,
        "research_status": (
            "blocked_by_strict_forward_inputs"
            if blocked and not complete
            else "accumulating_natural_forward"
        ),
        "as_of_date": as_of_date.isoformat(),
        "coverage": {
            "scope_rows": int(len(scopes)),
            "complete_signal_sessions": len(complete),
            "blocked_signal_sessions": len(blocked),
            "candidate_rows": int(len(candidates)),
            "signal_rows": int(len(signals)),
            "outcome_rows": int(len(outcomes)),
            "closed_outcomes": int(len(closed)),
        },
        "signal_funnel": dict(sorted(funnel.items())),
        "rejection_reason_counts": dict(sorted(reasons.items())),
        "blocking_reasons": blocking_reasons,
        "descriptive_closed_forward": {
            "closed": int(len(net)),
            "win_rate_pct": float(net.gt(0).mean() * 100.0) if not net.empty else None,
            "mean_net_return_pct": float(net.mean()) if not net.empty else None,
        },
        "diagnostic_policies": {
            ROTATION_NEXT_SESSION_POLICY_VERSION: diagnostic,
            THREE_PHASE_ADAPTIVE_POLICY_VERSION: three_phase_diagnostic,
        },
        "input_fingerprints": sorted(
            set(scopes.get("input_fingerprint", pd.Series(dtype=str)).dropna().astype(str))
        ),
        "formal_metrics": None,
        "boundaries": [
            "only captures written on their natural signal date are forward samples",
            "retrospective 2026-07-17/20 replay is excluded from this ledger",
            "no recommendation or order is created by this research contract",
        ],
    }


def _build_rotation_next_session_forward_diagnostic(
    candidates: pd.DataFrame,
    closed_outcomes: pd.DataFrame,
    *,
    stock_bars: pd.DataFrame | None,
) -> dict[str, object]:
    return _build_adaptive_forward_diagnostic(
        candidates,
        closed_outcomes,
        stock_bars=stock_bars,
        policy_version=ROTATION_NEXT_SESSION_POLICY_VERSION,
        minimum_closed=40,
        minimum_phase_closed={"rotation": 20, "warming": 20},
    )


def _build_three_phase_forward_diagnostic(
    candidates: pd.DataFrame,
    closed_outcomes: pd.DataFrame,
    *,
    stock_bars: pd.DataFrame | None,
) -> dict[str, object]:
    return _build_adaptive_forward_diagnostic(
        candidates,
        closed_outcomes,
        stock_bars=stock_bars,
        policy_version=THREE_PHASE_ADAPTIVE_POLICY_VERSION,
        minimum_closed=50,
        minimum_phase_closed={"uptrend": 10, "rotation": 20, "warming": 20},
        minimum_phase_wilson_95_lower_pct=60.0,
        qualification_contract_version=THREE_PHASE_QUALIFICATION_CONTRACT_VERSION,
    )


def _build_adaptive_forward_diagnostic(
    candidates: pd.DataFrame,
    closed_outcomes: pd.DataFrame,
    *,
    stock_bars: pd.DataFrame | None,
    policy_version: str,
    minimum_closed: int,
    minimum_phase_closed: Mapping[str, int],
    minimum_phase_wilson_95_lower_pct: float | None = None,
    qualification_contract_version: str | None = None,
) -> dict[str, object]:
    selected: list[dict[str, object]] = []
    for row in candidates.to_dict("records") if not candidates.empty else []:
        raw = row.get("raw")
        policies = raw.get("diagnostic_policies") if isinstance(raw, Mapping) else None
        policy = (
            policies.get(policy_version)
            if isinstance(policies, Mapping)
            else None
        )
        if not isinstance(policy, Mapping) or not bool(
            policy.get("signal_eligible")
        ):
            continue
        if qualification_contract_version is not None and str(
            policy.get("qualification_contract_version") or ""
        ) != qualification_contract_version:
            raise ValueError(
                "diagnostic candidate qualification contract version mismatch"
            )
        signal = raw.get("signal") if isinstance(raw, Mapping) else None
        if not isinstance(signal, Mapping):
            raise ValueError("diagnostic forward candidate is missing frozen signal")
        selected.append(
            {
                "signal_trade_date": _as_date(row["signal_trade_date"]),
                "vt_symbol": str(row["vt_symbol"]),
                "sector_id": str(row.get("sector_id") or ""),
                "rank": int(row.get("rank") or 0),
                "signal_id": str(signal.get("signal_id") or ""),
                "market_phase": str(signal.get("market_phase") or "UNKNOWN"),
            }
        )

    identity_to_phase = {
        (row["signal_trade_date"], row["vt_symbol"]): row["market_phase"]
        for row in selected
    }
    outcomes: list[dict[str, object]] = []
    for row in (
        closed_outcomes.to_dict("records")
        if not closed_outcomes.empty
        else []
    ):
        key = (_as_date(row["signal_trade_date"]), str(row["vt_symbol"]))
        phase = identity_to_phase.get(key)
        if phase is None:
            continue
        outcomes.append({**row, "market_phase": phase})

    phase_counts = Counter(str(row["market_phase"]) for row in selected)
    closed_phase_counts = Counter(str(row["market_phase"]) for row in outcomes)
    net = pd.to_numeric(
        pd.Series([row.get("net_return_pct") for row in outcomes], dtype=object),
        errors="coerce",
    ).dropna()
    phase_metrics = {
        phase: _natural_forward_return_metrics(
            [row for row in outcomes if row["market_phase"] == phase]
        )
        for phase in minimum_phase_closed
    }
    cash = _natural_forward_four_slot_cash(
        selected,
        outcomes,
        stock_bars,
        policy_version=policy_version,
    )
    required_phases = tuple(minimum_phase_closed)
    sample_failed_gates: list[str] = []
    performance_failed_gates: list[str] = []
    confidence_failed_gates: list[str] = []
    if len(outcomes) < minimum_closed:
        sample_failed_gates.append(f"closed_outcomes<{minimum_closed}")
    for phase in required_phases:
        minimum_phase = int(minimum_phase_closed[phase])
        if closed_phase_counts[phase] < minimum_phase:
            sample_failed_gates.append(f"closed_{phase}<{minimum_phase}")
        metrics = phase_metrics[phase]
        if metrics["win_rate_pct"] is None or metrics["win_rate_pct"] <= 60.0:
            performance_failed_gates.append(f"{phase}_win_rate<=60pct")
        if (
            metrics["mean_net_return_pct"] is None
            or metrics["mean_net_return_pct"] <= 0.0
        ):
            performance_failed_gates.append(f"{phase}_mean_return<=0")
        if minimum_phase_wilson_95_lower_pct is not None and (
            metrics["wilson_95_lower_pct"] is None
            or metrics["wilson_95_lower_pct"] <= minimum_phase_wilson_95_lower_pct
        ):
            confidence_failed_gates.append(
                f"{phase}_wilson_95_lower<={minimum_phase_wilson_95_lower_pct:g}pct"
            )
    if cash is None:
        performance_failed_gates.append("four_slot_cash_unavailable")
    else:
        if cash["cash_win_rate_pct"] is None or cash["cash_win_rate_pct"] <= 60.0:
            performance_failed_gates.append("four_slot_cash_win_rate<=60pct")
        if cash["compound_return_pct"] <= 60.0:
            performance_failed_gates.append("four_slot_cash_compound<=60pct")
        if cash["maximum_drawdown_pct"] < -10.0:
            performance_failed_gates.append("four_slot_cash_drawdown<-10pct")
    failed_gates = [
        *sample_failed_gates,
        *performance_failed_gates,
        *confidence_failed_gates,
    ]
    sample_passed = not sample_failed_gates
    performance_passed = not performance_failed_gates
    confidence_passed = not confidence_failed_gates
    all_passed = not failed_gates
    research_status = (
        "forward_qualified_candidate_for_review"
        if all_passed
        else "forward_performance_below_gate"
        if sample_passed
        else "accumulating_natural_forward"
    )
    verified_metrics = (
        {
            "policy_version": policy_version,
            "closed": int(len(net)),
            "win_rate_pct": (
                float(net.gt(0).mean() * 100.0) if not net.empty else None
            ),
            "mean_net_return_pct": (
                float(net.mean()) if not net.empty else None
            ),
            "market_phase_metrics": phase_metrics,
            "four_slot_cash": cash,
        }
        if all_passed
        else None
    )
    return {
        "registered_before_first_natural_scope": True,
        "qualification_contract_version": qualification_contract_version,
        "selection_origin": "pre_registered_posthoc_historical_diagnostic",
        "coverage": {
            "candidate_rows": len(selected),
            "closed_outcomes": len(outcomes),
            "candidate_market_phases": dict(sorted(phase_counts.items())),
            "closed_market_phases": dict(sorted(closed_phase_counts.items())),
        },
        "descriptive_closed_forward": {
            "closed": int(len(net)),
            "win_rate_pct": float(net.gt(0).mean() * 100.0) if not net.empty else None,
            "mean_net_return_pct": float(net.mean()) if not net.empty else None,
        },
        "market_phase_metrics": phase_metrics,
        "four_slot_cash": cash,
        "qualification": {
            "sample_gates_passed": sample_passed,
            "performance_gates_passed": performance_passed,
            "confidence_gates_passed": confidence_passed,
            "all_gates_passed": all_passed,
            "failed_gates": failed_gates,
        },
        "research_status": research_status,
        "verified_forward_metrics": verified_metrics,
        "recommendations_created": 0,
        "orders_created": 0,
        "formal_metrics": None,
    }


def _natural_forward_return_metrics(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    net = pd.to_numeric(
        pd.Series([row.get("net_return_pct") for row in rows], dtype=object),
        errors="coerce",
    ).dropna()
    closed = int(len(net))
    wins = int(net.gt(0).sum())
    return {
        "closed": closed,
        "win_rate_pct": float(net.gt(0).mean() * 100.0) if not net.empty else None,
        "mean_net_return_pct": float(net.mean()) if not net.empty else None,
        "wilson_95_lower_pct": _wilson_95_lower_pct(wins, closed),
    }


def _wilson_95_lower_pct(wins: int, trials: int) -> float | None:
    if trials <= 0:
        return None
    z = 1.959963984540054
    proportion = wins / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    half_width = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return float((center - half_width) * 100.0)


def _natural_forward_four_slot_cash(
    selected: Sequence[Mapping[str, object]],
    outcomes: Sequence[Mapping[str, object]],
    stock_bars: pd.DataFrame | None,
    *,
    policy_version: str = ROTATION_NEXT_SESSION_POLICY_VERSION,
) -> dict[str, Any] | None:
    if stock_bars is None:
        return None
    candidate_by_identity = {
        (row["signal_trade_date"], row["vt_symbol"]): row
        for row in selected
    }
    trades: list[dict[str, object]] = []
    for outcome in outcomes:
        key = (
            _as_date(outcome["signal_trade_date"]),
            str(outcome["vt_symbol"]),
        )
        candidate = candidate_by_identity[key]
        trades.append(
            {
                "variant": policy_version,
                "signal_id": str(candidate.get("signal_id") or ""),
                "sector_id": str(candidate.get("sector_id") or ""),
                "vt_symbol": key[1],
                "dynamic_rank": int(candidate.get("rank") or 0),
                "entry_date": outcome.get("entry_date"),
                "entry_price": outcome.get("entry_price"),
                "exit_date": outcome.get("exit_date"),
                "net_return_pct": outcome.get("net_return_pct"),
            }
        )
    return simulate_four_slot_cash(pd.DataFrame.from_records(trades), stock_bars)


def render_causal_forward_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_causal_forward_markdown(report: Mapping[str, Any]) -> str:
    coverage = report.get("coverage")
    coverage = coverage if isinstance(coverage, Mapping) else {}
    diagnostics = report.get("diagnostic_policies")
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    adaptive = diagnostics.get(ROTATION_NEXT_SESSION_POLICY_VERSION)
    adaptive = adaptive if isinstance(adaptive, Mapping) else {}
    adaptive_coverage = adaptive.get("coverage")
    adaptive_coverage = (
        adaptive_coverage if isinstance(adaptive_coverage, Mapping) else {}
    )
    adaptive_qualification = adaptive.get("qualification")
    adaptive_qualification = (
        adaptive_qualification
        if isinstance(adaptive_qualification, Mapping)
        else {}
    )
    adaptive_cash = adaptive.get("four_slot_cash")
    adaptive_cash = adaptive_cash if isinstance(adaptive_cash, Mapping) else {}
    lines = [
        "# AlphaAgent 跨行情龙头低吸自然前向账本",
        "",
        f"合同：`{report.get('contract_version')}`；身份："
        f"`{report.get('identity_mode')}`。",
        f"研究状态：`{report.get('research_status')}`；截至 "
        f"`{report.get('as_of_date')}`。",
        "正式胜率、收益和四仓复利：`null`。",
        "",
        "## Coverage",
        "",
        f"- 完整/阻断信号日：`{coverage.get('complete_signal_sessions', 0)}` / "
        f"`{coverage.get('blocked_signal_sessions', 0)}`。",
        f"- 候选/有效信号：`{coverage.get('candidate_rows', 0)}` / "
        f"`{coverage.get('signal_rows', 0)}`。",
        f"- 结果/闭合：`{coverage.get('outcome_rows', 0)}` / "
        f"`{coverage.get('closed_outcomes', 0)}`。",
        "",
        "## Rotation 次日确认诊断",
        "",
        f"- 预注册策略：`{ROTATION_NEXT_SESSION_POLICY_VERSION}`。",
        f"- 状态：`{adaptive.get('research_status')}`。",
        f"- 候选/闭合：`{adaptive_coverage.get('candidate_rows', 0)}` / "
        f"`{adaptive_coverage.get('closed_outcomes', 0)}`。",
        f"- 40/20 样本门：`{str(bool(adaptive_qualification.get('sample_gates_passed'))).lower()}`；"
        f"绩效门：`{str(bool(adaptive_qualification.get('performance_gates_passed'))).lower()}`；"
        f"全部门：`{str(bool(adaptive_qualification.get('all_gates_passed'))).lower()}`；"
        f"失败门：`{', '.join(str(item) for item in adaptive_qualification.get('failed_gates', [])) or 'none'}`。",
        f"- 四仓成交/胜率：`{adaptive_cash.get('closed_trades', 0)}` / "
        f"`{adaptive_cash.get('cash_win_rate_pct')}`；复利/回撤："
        f"`{adaptive_cash.get('compound_return_pct')}` / "
        f"`{adaptive_cash.get('maximum_drawdown_pct')}`。",
        "- 正式指标、推荐和订单：`null / 0 / 0`。",
        "",
        "## Boundary",
        "",
        "只统计在真实信号日盘后冻结的 V2 单身份样本。",
        "历史点时回放和旧三身份 MA5 影子均不进入本账本正式指标。",
        "",
    ]
    return "\n".join(lines)


def _capture_natural_pair(
    source_trade_date: date,
    signal_trade_date: date,
    *,
    attempted_at: datetime,
) -> ForwardMa5Capture:
    local_attempt = attempted_at.astimezone(SHANGHAI)
    if local_attempt.time().replace(tzinfo=None) < FEATURE_CUTOFF_TIME:
        return blocked_causal_forward_capture(
            source_trade_date=source_trade_date,
            signal_trade_date=signal_trade_date,
            attempted_at=attempted_at,
            reason="signal_close_not_complete",
        )
    try:
        inputs = load_causal_forward_inputs(
            source_trade_date,
            signal_trade_date,
            attempted_at=attempted_at,
        )
        return build_causal_forward_capture(inputs)
    except ValueError as exc:
        return blocked_causal_forward_capture(
            source_trade_date=source_trade_date,
            signal_trade_date=signal_trade_date,
            attempted_at=attempted_at,
            reason=f"strict_forward_inputs_incomplete:{exc}",
        )


def _capture_result(
    capture: ForwardMa5Capture,
    saved: ForwardMa5SaveResult,
) -> dict[str, object]:
    return {
        "source_trade_date": capture.source_trade_date.isoformat(),
        "signal_trade_date": capture.signal_trade_date.isoformat(),
        "complete": capture.complete,
        "status": saved.status,
        "rows_written": saved.rows_written,
        "scopes_written": saved.scopes_written,
        "candidate_rows": len(capture.rows),
        "signal_rows": sum(row.signal_eligible for row in capture.rows),
        "input_fingerprint": capture.input_fingerprint,
    }


def _natural_source_pair(signal_trade_date: date) -> tuple[date, date] | None:
    engine = get_engine()
    schema.ensure_schema_once(engine)
    scopes = schema.low_suction_forward_leader_rank_snapshot_scopes
    expected_modes = len(LeaderIdentityMode)
    with session_scope() as session:
        rows = session.execute(
            select(
                scopes.c.source_trade_date,
                scopes.c.target_trade_date,
                func.count(func.distinct(scopes.c.identity_mode)).label("mode_count"),
                func.bool_and(scopes.c.complete).label("all_complete"),
            )
            .where(
                scopes.c.ranking_version == FORWARD_LEADER_RANKING_VERSION,
                scopes.c.target_trade_date == signal_trade_date,
            )
            .group_by(scopes.c.source_trade_date, scopes.c.target_trade_date)
        ).mappings().all()
    valid = [
        row
        for row in rows
        if int(row.get("mode_count") or 0) == expected_modes
        and bool(row.get("all_complete"))
    ]
    if len(valid) > 1:
        raise CausalForwardLedgerImmutableError(
            "natural signal date has multiple complete source bindings"
        )
    if not valid:
        return None
    return valid[0]["source_trade_date"], valid[0]["target_trade_date"]


def _snapshot_statements(
    source_trade_date: date,
    *,
    attempted_at: datetime,
) -> dict[str, object]:
    membership_scopes = schema.low_suction_forward_membership_snapshot_scopes
    memberships = schema.low_suction_forward_membership_snapshots
    security_scopes = schema.low_suction_security_snapshot_scopes
    securities = schema.low_suction_security_snapshots
    return {
        "membership_scope": select(membership_scopes).where(
            membership_scopes.c.source_trade_date == source_trade_date,
            membership_scopes.c.scope_type == TRADABLE_SCOPE_TYPE,
            membership_scopes.c.source == FORWARD_MEMBERSHIP_SOURCE,
            membership_scopes.c.observed_at <= attempted_at,
        ),
        "membership_rows": select(memberships).where(
            memberships.c.source_trade_date == source_trade_date,
            memberships.c.source == FORWARD_MEMBERSHIP_SOURCE,
            memberships.c.observed_at <= attempted_at,
        ),
        "security_scope": select(security_scopes).where(
            security_scopes.c.source_trade_date == source_trade_date,
            security_scopes.c.source == FORWARD_SECURITY_SOURCE,
            security_scopes.c.observed_at <= attempted_at,
        ),
        "security_rows": select(securities).where(
            securities.c.source_trade_date == source_trade_date,
            securities.c.source == FORWARD_SECURITY_SOURCE,
            securities.c.observed_at <= attempted_at,
        ),
        "market_timing_panel": (
            select(
                schema.market_timing_panel.c.panel,
                schema.market_timing_panel.c.computed_at,
            )
            .where(schema.market_timing_panel.c.computed_at <= attempted_at)
            .order_by(schema.market_timing_panel.c.computed_at.desc())
            .limit(1)
        ),
    }


def _concept_bars_statement(sector_ids: Sequence[str], *, end: date):
    return (
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sectors.c.name.label("concept_name"),
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.open_price,
            schema.sector_daily_bars.c.high_price,
            schema.sector_daily_bars.c.low_price,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.volume,
            schema.sector_daily_bars.c.turnover,
            schema.sector_daily_bars.c.source,
        )
        .select_from(
            schema.sector_daily_bars.join(
                schema.sectors,
                schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
            )
        )
        .where(
            schema.sector_daily_bars.c.sector_id.in_(tuple(sector_ids)),
            schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
            schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
            schema.sector_daily_bars.c.trade_date <= end,
        )
        .order_by(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
        )
    )


def _stock_bars_statement(symbols: Sequence[str], *, start: date, end: date):
    return (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover,
            schema.stock_daily_bars.c.change_pct,
            schema.stock_daily_bars.c.source,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(tuple(symbols)),
            schema.stock_daily_bars.c.trade_date.between(start, end),
        )
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    )


def _completed_dates_statement(cutoff: date, *, start: date):
    return (
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date.between(start, cutoff))
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
            >= MIN_COMPLETE_DAILY_SYMBOL_COUNT
        )
        .order_by(schema.stock_daily_bars.c.trade_date)
    )


def _signal_campaign_paths(
    concept_bars: pd.DataFrame,
    signal_trade_date: date,
) -> pd.DataFrame:
    if concept_bars.empty:
        return _empty_campaign_paths()
    _campaigns, paths = build_concept_campaign_ledger(concept_bars)
    signal = pd.Timestamp(signal_trade_date)
    active_ids = set(
        paths.loc[
            paths["trade_date"].eq(signal) & paths["campaign_active"].astype(bool),
            "campaign_id",
        ].astype(str)
    )
    return paths.loc[paths["campaign_id"].astype(str).isin(active_ids)].copy()


def _reconstruct_frozen_campaign_paths(
    candidates: pd.DataFrame,
    concept_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Continue frozen campaign identities without rerunning anchor selection."""

    _require_columns(
        candidates,
        {"sector_id", "spell_anchor_date", "raw"},
        "causal forward campaign reconstruction",
    )
    _require_columns(
        concept_bars,
        {"sector_id", "concept_name", "trade_date", "close_price"},
        "causal forward concept bars",
    )
    bars = concept_bars.copy()
    bars["sector_id"] = bars["sector_id"].astype(str)
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("causal forward concept bar identities must be unique")

    specifications: dict[str, tuple[str, pd.Timestamp]] = {}
    for candidate in candidates.to_dict("records"):
        raw = candidate.get("raw") if isinstance(candidate.get("raw"), Mapping) else {}
        signal = raw.get("signal") if isinstance(raw, Mapping) else None
        if not isinstance(signal, Mapping) or not signal.get("campaign_id"):
            raise ValueError("causal forward candidate is missing its frozen campaign")
        campaign_id = str(signal["campaign_id"])
        specification = (
            str(candidate["sector_id"]),
            pd.Timestamp(candidate["spell_anchor_date"]).normalize(),
        )
        existing = specifications.get(campaign_id)
        if existing is not None and existing != specification:
            raise ValueError("frozen campaign identity has conflicting specifications")
        specifications[campaign_id] = specification

    trigger_column = f"anchor_{CONCEPT_ANCHOR_MODE}"
    rebuilt: list[pd.DataFrame] = []
    for campaign_id, (sector_id, anchor_date) in sorted(specifications.items()):
        campaign_bars = bars.loc[
            bars["sector_id"].eq(sector_id)
            & bars["trade_date"].ge(anchor_date)
        ].copy()
        if campaign_bars.empty or not campaign_bars["trade_date"].eq(anchor_date).any():
            raise ValueError(f"frozen campaign anchor bar is unavailable: {campaign_id}")
        campaign_bars[trigger_column] = campaign_bars["trade_date"].eq(anchor_date)
        campaigns, paths = build_exploratory_campaigns(
            campaign_bars,
            anchor_modes=(CONCEPT_ANCHOR_MODE,),
            exit_candidates=(
                (CONCEPT_EXIT_DRAWDOWN_PCT, CONCEPT_EXIT_CONFIRM_SESSIONS),
            ),
            retained_path_days=None,
        )
        matching_campaigns = campaigns.loc[
            campaigns["campaign_id"].astype(str).eq(campaign_id)
        ]
        matching_paths = paths.loc[
            paths["campaign_id"].astype(str).eq(campaign_id)
        ].copy()
        if len(matching_campaigns) != 1 or matching_paths.empty:
            raise ValueError(f"frozen campaign cannot be continued: {campaign_id}")
        right_censored = bool(matching_campaigns.iloc[0]["right_censored"])
        matching_paths["campaign_active"] = (
            ~matching_paths["is_endpoint"].astype(bool) | right_censored
        )
        matching_paths["feature_cutoff_date"] = matching_paths["trade_date"]
        rebuilt.append(matching_paths)
    return pd.concat(rebuilt, ignore_index=True).sort_values(
        ["campaign_id", "trade_date"],
        kind="stable",
    )


def _empty_campaign_paths() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "campaign_id",
            "sector_id",
            "concept_name",
            "anchor_date",
            "trade_date",
            "campaign_day",
            "cumulative_gain_pct",
            "campaign_active",
        ]
    )


def _stock_history_start(campaign_paths: pd.DataFrame, signal_trade_date: date) -> date:
    if campaign_paths.empty:
        return signal_trade_date - timedelta(days=STOCK_HISTORY_BUFFER_DAYS)
    anchor = pd.to_datetime(campaign_paths["anchor_date"], errors="raise").dt.date.min()
    return anchor - timedelta(days=STOCK_HISTORY_BUFFER_DAYS)


def _timing_frame(
    rows: Sequence[Mapping[str, Any]],
    *,
    cutoff: date,
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "source_date",
                "active_direction",
                "danger_state",
                "market_phase",
                "known_at",
            ]
        )
    latest = rows[0]
    panel = latest.get("panel") if isinstance(latest.get("panel"), Mapping) else {}
    records = []
    for item in panel.get("timing_series", ()) if isinstance(panel, Mapping) else ():
        if not isinstance(item, Mapping) or not item.get("date"):
            continue
        source_date = pd.Timestamp(item["date"]).date()
        if source_date > cutoff:
            continue
        records.append(
            {
                "source_date": source_date,
                "active_direction": str(item.get("active_direction") or "UNKNOWN"),
                "danger_state": str(item.get("danger_state") or "UNKNOWN"),
                "market_phase": str(
                    item.get("market_phase") or item.get("phase") or "UNKNOWN"
                ),
                "known_at": latest.get("computed_at"),
            }
        )
    return pd.DataFrame(
        records,
        columns=[
            "source_date",
            "active_direction",
            "danger_state",
            "market_phase",
            "known_at",
        ],
    )


def _require_ready_scope(
    scope: Mapping[str, Any] | None,
    source_trade_date: date,
    label: str,
) -> None:
    if not scope:
        raise ValueError(f"strict {label} scope is unavailable")
    if _as_date(scope.get("source_trade_date")) != source_trade_date:
        raise ValueError(f"strict {label} scope source date mismatch")
    if not bool(scope.get("complete")) or str(scope.get("evidence_level")) != "strict":
        raise ValueError(f"strict {label} scope is incomplete")


def _existing_capture_decision(
    existing: Sequence[Mapping[str, Any]],
    capture: ForwardMa5Capture,
) -> str | None:
    if not existing:
        return None
    if len(existing) != 1 or str(existing[0].get("identity_mode") or "") != FORWARD_IDENTITY_MODE:
        raise CausalForwardLedgerImmutableError(
            "existing causal forward scope set is not the single V2 identity"
        )
    existing_scope = existing[0]
    existing_fingerprint = str(existing_scope.get("input_fingerprint") or "")
    if bool(existing_scope.get("complete")):
        if not capture.complete:
            return "complete_preserved"
        if existing_fingerprint != capture.input_fingerprint:
            raise CausalForwardLedgerImmutableError(
                "complete causal forward fingerprint is immutable"
            )
        return "already_frozen"
    if not capture.complete and existing_fingerprint == capture.input_fingerprint:
        return "already_blocked"
    return None


def _validate_capture(capture: ForwardMa5Capture) -> None:
    if capture.contract_version != FORWARD_CONTRACT_VERSION:
        raise ValueError("causal forward repository requires the V2 contract version")
    if len(capture.scopes) != 1:
        raise ValueError("causal forward capture requires exactly one V2 scope")
    if not capture.input_fingerprint.startswith("sha256:"):
        raise ValueError("causal forward fingerprint must use sha256")
    if capture.source_trade_date >= capture.signal_trade_date:
        raise ValueError("causal forward source date must precede signal date")
    scope = capture.scopes[0]
    if scope.identity_mode != FORWARD_IDENTITY_MODE:
        raise ValueError("causal forward capture requires the V2 identity mode")
    if (
        scope.contract_version != capture.contract_version
        or scope.source_trade_date != capture.source_trade_date
        or scope.signal_trade_date != capture.signal_trade_date
        or scope.input_fingerprint != capture.input_fingerprint
        or scope.unique_candidate_count != len(capture.rows)
        or scope.signal_count != sum(row.signal_eligible for row in capture.rows)
    ):
        raise ValueError("causal forward scope does not match candidate rows")
    if scope.evidence_level != FORWARD_EVIDENCE_LEVEL:
        raise ValueError("causal forward scope evidence level mismatch")
    _validate_known_at(scope.known_at, capture.signal_trade_date, complete=scope.complete)
    if not capture.complete and capture.rows:
        raise ValueError("blocked causal forward capture cannot contain candidates")

    identities = [(row.signal_trade_date, row.identity_mode, row.vt_symbol) for row in capture.rows]
    if len(identities) != len(set(identities)):
        raise ValueError("causal forward candidate identity must be unique")
    for row in capture.rows:
        if (
            row.contract_version != capture.contract_version
            or row.source_trade_date != capture.source_trade_date
            or row.signal_trade_date != capture.signal_trade_date
            or row.identity_mode != FORWARD_IDENTITY_MODE
            or row.input_fingerprint != capture.input_fingerprint
            or row.feature_cutoff_date != capture.signal_trade_date
            or row.selected_mode_at_capture != FORWARD_IDENTITY_MODE
            or row.evidence_level != FORWARD_EVIDENCE_LEVEL
        ):
            raise ValueError("causal forward candidate identity mismatch")
        signal = row.raw.get("signal") if isinstance(row.raw, Mapping) else None
        if not isinstance(signal, Mapping) or not signal.get("campaign_id"):
            raise ValueError("causal forward candidate is missing its frozen campaign")
        _validate_known_at(row.known_at, capture.signal_trade_date, complete=True)


def _validate_known_at(value: datetime, signal_trade_date: date, *, complete: bool) -> None:
    _require_aware(value, "known_at")
    local = value.astimezone(SHANGHAI)
    if local.date() != signal_trade_date:
        raise ValueError("causal forward known_at must be on the signal date")
    if complete and local.time().replace(tzinfo=None) < FEATURE_CUTOFF_TIME:
        raise ValueError("complete causal forward scope requires the completed close")


def _require_natural_write_time(capture: ForwardMa5Capture) -> None:
    now = _shanghai_now()
    if now.date() != capture.signal_trade_date:
        raise ValueError("causal forward capture must be written on its natural signal date")
    if capture.complete and now.time().replace(tzinfo=None) < FEATURE_CUTOFF_TIME:
        raise ValueError("complete causal forward capture cannot be written before close")


def _shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def _outcome_values(raw: Mapping[str, Any]) -> dict[str, object]:
    columns = {
        column.name
        for column in schema.low_suction_forward_ma5_outcomes.columns
        if column.name not in {"created_at", "updated_at"}
    }
    values = {key: _sql_value(value) for key, value in raw.items() if key in columns}
    values.setdefault("raw", {})
    values.setdefault("entry_proxy", "same_completed_session_close_research_proxy")
    return values


def _outcome_identity_predicate(table, values: Mapping[str, object]):
    return (
        (table.c.contract_version == values["contract_version"])
        & (table.c.signal_trade_date == values["signal_trade_date"])
        & (table.c.identity_mode == values["identity_mode"])
        & (table.c.vt_symbol == values["vt_symbol"])
    )


def _scope_dates(scopes: pd.DataFrame, *, complete: bool) -> set[date]:
    if scopes.empty or not {"signal_trade_date", "complete"}.issubset(scopes.columns):
        return set()
    return set(
        scopes.loc[scopes["complete"].astype(bool).eq(complete), "signal_trade_date"].map(
            _as_date
        )
    )


def _sql_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (float, np.floating)) and not np.isfinite(float(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date() if value.tzinfo is None else value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _as_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.Timestamp(value).date()


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
