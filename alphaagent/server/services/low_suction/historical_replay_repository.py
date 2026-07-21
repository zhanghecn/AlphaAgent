"""Immutable query ledger for database-derived low-suction replays."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import and_, func, insert, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope


ALLOWED_EVIDENCE_LEVELS = {
    "exploratory_survivorship_proxy",
    "strict_point_in_time",
}
ALLOWED_MEMBERSHIP_MODES = {
    "current_membership_replayed_backward",
    "point_in_time_snapshot",
}
ALLOWED_MARKET_PHASES = {"uptrend", "rotation", "warming"}
REQUIRED_TRADE_COLUMNS = {
    "signal_id",
    "campaign_id",
    "sector_id",
    "concept_name",
    "vt_symbol",
    "stock_name",
    "market_phase",
    "time_block",
    "dynamic_rank",
    "wave_number",
    "support_line",
    "support_price",
    "support_test_date",
    "signal_date",
    "entry_price",
    "d1_date",
    "d1_close",
    "d1_net_return_pct",
    "exit_date",
    "exit_price",
    "exit_reason",
    "holding_sessions",
    "net_return_pct",
}


class HistoricalReplayImmutableError(RuntimeError):
    """Raised when an existing replay identity would be rewritten."""


def save_replay_run(
    run: Mapping[str, object], trades: pd.DataFrame
) -> dict[str, int | str]:
    """Insert one replay once and accept only content-identical retries."""

    values, rows = _validated_payload(run, trades)
    engine = get_engine()
    schema.ensure_schema_once(engine)
    runs = schema.low_suction_historical_replay_runs
    ledger = schema.low_suction_historical_replay_trades
    with session_scope() as session:
        existing = session.execute(
            select(runs).where(runs.c.run_id == values["run_id"])
        ).mappings().all()
        if existing:
            if len(existing) != 1:
                raise HistoricalReplayImmutableError("replay run identity is duplicated")
            stored = existing[0]
            immutable = (
                "policy_version",
                "qualification_contract_version",
                "evidence_level",
                "membership_mode",
                "input_fingerprint",
                "trade_fingerprint",
                "regression_artifact_sha256",
                "trade_count",
            )
            if any(stored.get(key) != values.get(key) for key in immutable):
                raise HistoricalReplayImmutableError(
                    "existing replay content differs from immutable retry"
                )
            return {"status": "already_saved", "runs_written": 0, "trades_written": 0}

        session.execute(insert(runs).values(**values))
        if rows:
            session.execute(insert(ledger), rows)
    return {
        "status": "saved",
        "runs_written": 1,
        "trades_written": len(rows),
    }


def load_latest_replay_run(
    *, evidence_level: str | None = None
) -> dict[str, object] | None:
    """Return the latest run, optionally constrained to an evidence grade."""

    if evidence_level is not None and evidence_level not in ALLOWED_EVIDENCE_LEVELS:
        raise ValueError("unsupported evidence_level")
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.low_suction_historical_replay_runs
    statement = select(table)
    if evidence_level is not None:
        statement = statement.where(table.c.evidence_level == evidence_level)
    statement = statement.order_by(table.c.built_at.desc(), table.c.run_id.desc()).limit(1)
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return dict(rows[0]) if rows else None


def list_replay_trades(
    *,
    run_id: str,
    page: int = 1,
    page_size: int = 20,
    market_phase: str | None = None,
    outcome: str | None = None,
    vt_symbol: str | None = None,
    sector_id: str | None = None,
) -> dict[str, object]:
    """Return deterministic paginated replay rows and total count."""

    if page < 1:
        raise ValueError("page must be positive")
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if market_phase is not None and market_phase not in ALLOWED_MARKET_PHASES:
        raise ValueError("unsupported market_phase")
    if outcome is not None and outcome not in {"winner", "loser"}:
        raise ValueError("unsupported outcome")

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.low_suction_historical_replay_trades
    predicates = [table.c.run_id == run_id]
    if market_phase is not None:
        predicates.append(table.c.market_phase == market_phase)
    if outcome == "winner":
        predicates.append(table.c.net_return_pct > 0)
    elif outcome == "loser":
        predicates.append(table.c.net_return_pct <= 0)
    if vt_symbol:
        predicates.append(table.c.vt_symbol == vt_symbol.strip())
    if sector_id:
        predicates.append(table.c.sector_id == sector_id.strip())

    where = and_(*predicates)
    count_statement = select(func.count()).select_from(table).where(where)
    rows_statement = (
        select(table)
        .where(where)
        .order_by(table.c.signal_date.desc(), table.c.signal_id.asc())
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
    }


def get_replay_trade(*, run_id: str, signal_id: str) -> dict[str, object] | None:
    """Return one trade together with its causal raw evidence."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.low_suction_historical_replay_trades
    statement = select(table).where(
        table.c.run_id == run_id,
        table.c.signal_id == signal_id,
    )
    with session_scope() as session:
        rows = session.execute(statement).mappings().all()
    return dict(rows[0]) if rows else None


def _validated_payload(
    run: Mapping[str, object], trades: pd.DataFrame
) -> tuple[dict[str, object], list[dict[str, object]]]:
    missing = REQUIRED_TRADE_COLUMNS.difference(trades.columns)
    if missing:
        raise ValueError(f"historical replay trades missing columns: {sorted(missing)}")
    evidence_level = str(run.get("evidence_level") or "")
    membership_mode = str(run.get("membership_mode") or "")
    if evidence_level not in ALLOWED_EVIDENCE_LEVELS:
        raise ValueError("unsupported evidence_level")
    if membership_mode not in ALLOWED_MEMBERSHIP_MODES:
        raise ValueError("unsupported membership_mode")
    if evidence_level == "strict_point_in_time" and membership_mode != "point_in_time_snapshot":
        raise ValueError("strict evidence requires point-in-time membership")
    if trades["signal_id"].astype(str).duplicated().any():
        raise ValueError("signal_id must be unique within a replay")
    invalid_phases = set(trades["market_phase"].astype(str)).difference(ALLOWED_MARKET_PHASES)
    if invalid_phases:
        raise ValueError(f"unsupported market phases: {sorted(invalid_phases)}")

    run_id = str(run.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required")
    rows = []
    for raw in trades.to_dict("records"):
        row = {key: _json_safe(raw[key]) for key in REQUIRED_TRADE_COLUMNS}
        row["run_id"] = run_id
        row["signal_id"] = str(row["signal_id"])
        row["raw"] = _json_safe(raw.get("raw", raw))
        rows.append(row)
    rows.sort(key=lambda row: str(row["signal_id"]))
    trade_fingerprint = _fingerprint(rows)
    supplied_fingerprint = str(run.get("trade_fingerprint") or "")
    if supplied_fingerprint and supplied_fingerprint != trade_fingerprint:
        raise ValueError("supplied trade_fingerprint does not match replay rows")
    if int(run.get("trade_count", len(rows))) != len(rows):
        raise ValueError("trade_count does not match replay rows")

    values = {
        "run_id": run_id,
        "policy_version": str(run.get("policy_version") or ""),
        "qualification_contract_version": str(
            run.get("qualification_contract_version") or ""
        ),
        "evidence_level": evidence_level,
        "membership_mode": membership_mode,
        "input_fingerprint": str(run.get("input_fingerprint") or ""),
        "trade_fingerprint": trade_fingerprint,
        "regression_artifact_sha256": run.get("regression_artifact_sha256"),
        "trade_count": len(rows),
        "metrics": _json_safe(run.get("metrics") or {}),
        "built_at": run.get("built_at") or datetime.now().astimezone(),
        "raw": _json_safe(run.get("raw") or {}),
    }
    required_run_values = (
        "policy_version",
        "qualification_contract_version",
        "input_fingerprint",
    )
    if any(not values[key] for key in required_run_values):
        raise ValueError("policy, qualification and input fingerprints are required")
    return values, rows


def _fingerprint(rows: list[dict[str, object]]) -> str:
    payload = json.dumps(
        _json_safe(rows), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_safe(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value
