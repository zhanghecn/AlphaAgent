"""Immutable storage for causal pre-board transaction-flow features."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime

from sqlalchemy import delete, insert, select, tuple_

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope


FLOW_READY = "flow_ready"
PAIR_MANIFEST_VERSION = "limit-up-preboard-transaction-pairs-v1"


def save_transaction_pair_manifest(
    manifest: Mapping[str, object],
) -> dict[str, object]:
    """Freeze one exact shared-strategy stock-day manifest immutably."""

    values = _validated_pair_manifest(manifest)
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_transaction_pair_manifests
    identity = (
        table.c.manifest_version == values["manifest_version"],
        table.c.session_count == values["session_count"],
        table.c.start_date == values["start_date"],
        table.c.end_date == values["end_date"],
    )
    with session_scope() as session:
        existing = session.execute(
            select(table.c.input_fingerprint).where(*identity)
        ).mappings().first()
        if existing:
            status = (
                "already_frozen"
                if str(existing.get("input_fingerprint") or "")
                == values["input_fingerprint"]
                else "fingerprint_conflict"
            )
            return {
                "status": status,
                "manifest_written": 0,
                "input_fingerprint": values["input_fingerprint"],
                "shared_pair_count": values["shared_pair_count"],
            }
        session.execute(insert(table).values(**values))
    return {
        "status": "frozen",
        "manifest_written": 1,
        "input_fingerprint": values["input_fingerprint"],
        "shared_pair_count": values["shared_pair_count"],
    }


def load_latest_transaction_pair_manifest(
    *,
    manifest_version: str = PAIR_MANIFEST_VERSION,
    session_count: int,
) -> dict[str, object] | None:
    """Load the latest frozen range for one bounded research scope."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_transaction_pair_manifests
    with session_scope() as session:
        row = session.execute(
            select(table)
            .where(
                table.c.manifest_version == str(manifest_version),
                table.c.session_count == int(session_count),
            )
            .order_by(table.c.end_date.desc(), table.c.start_date.desc())
            .limit(1)
        ).mappings().first()
    return dict(row) if row is not None else None


def save_transaction_feature_capture(
    scope: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Freeze one complete stock-day or replace a previously invalid attempt."""

    scope_values = _validated_scope(scope, rows)
    feature_rows = [_validated_feature_row(row, scope_values) for row in rows]
    engine = get_engine()
    schema.ensure_schema_once(engine)
    scopes = schema.limit_up_transaction_feature_scopes
    features = schema.limit_up_transaction_features
    identity = (
        scopes.c.feature_version == scope_values["feature_version"],
        scopes.c.vt_symbol == scope_values["vt_symbol"],
        scopes.c.trade_date == scope_values["trade_date"],
    )
    with session_scope() as session:
        existing = session.execute(
            select(scopes.c.status, scopes.c.input_fingerprint).where(*identity)
        ).mappings().first()
        if existing and str(existing.get("status") or "") == FLOW_READY:
            status = (
                "already_frozen"
                if str(existing.get("input_fingerprint") or "")
                == scope_values["input_fingerprint"]
                else "fingerprint_conflict"
            )
            return {
                "status": status,
                "rows_written": 0,
                "scope_written": 0,
                "input_fingerprint": scope_values["input_fingerprint"],
            }
        if existing:
            feature_identity = (
                features.c.feature_version == scope_values["feature_version"],
                features.c.vt_symbol == scope_values["vt_symbol"],
                features.c.trade_date == scope_values["trade_date"],
            )
            session.execute(delete(features).where(*feature_identity))
            session.execute(delete(scopes).where(*identity))
        if feature_rows:
            session.execute(insert(features), feature_rows)
        session.execute(insert(scopes).values(**scope_values))
    return {
        "status": "frozen" if scope_values["status"] == FLOW_READY else "invalid",
        "rows_written": len(feature_rows),
        "scope_written": 1,
        "input_fingerprint": scope_values["input_fingerprint"],
    }


def load_transaction_feature_coverage(
    pairs: Sequence[tuple[str, date]],
    *,
    feature_version: str,
) -> dict[str, object]:
    """Load coverage for the exact requested stock-day identities."""

    normalized = _normalize_pairs(pairs)
    if not normalized:
        return build_transaction_feature_coverage((), ())
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_transaction_feature_scopes
    with session_scope() as session:
        rows = session.execute(
            select(table)
            .where(
                table.c.feature_version == str(feature_version),
                tuple_(table.c.vt_symbol, table.c.trade_date).in_(normalized),
            )
            .order_by(table.c.trade_date, table.c.vt_symbol)
        ).mappings().all()
    return build_transaction_feature_coverage(normalized, rows)


def load_transaction_features(
    pairs: Sequence[tuple[str, date]],
    *,
    feature_version: str,
) -> list[dict[str, object]]:
    """Load immutable feature rows for exact stock-day identities."""

    normalized = _normalize_pairs(pairs)
    if not normalized:
        return []
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.limit_up_transaction_features
    with session_scope() as session:
        rows = session.execute(
            select(table)
            .where(
                table.c.feature_version == str(feature_version),
                tuple_(table.c.vt_symbol, table.c.trade_date).in_(normalized),
            )
            .order_by(table.c.trade_date, table.c.vt_symbol, table.c.bar_time)
        ).mappings().all()
    return [dict(row) for row in rows]


def build_transaction_feature_coverage(
    pairs: Sequence[tuple[str, date]],
    scopes: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Summarize only exact requested pairs; unrelated scopes never count."""

    requested = _normalize_pairs(pairs)
    requested_set = set(requested)
    by_pair: dict[tuple[str, date], Mapping[str, object]] = {}
    for scope in scopes:
        pair = _scope_pair(scope)
        if pair not in requested_set:
            continue
        if pair in by_pair:
            raise ValueError(f"duplicate transaction feature scope: {pair}")
        by_pair[pair] = scope
    ready = {
        pair
        for pair, scope in by_pair.items()
        if str(scope.get("status") or "") == FLOW_READY
    }
    missing = [pair for pair in requested if pair not in by_pair]
    pending = [pair for pair in requested if pair not in ready]
    status_counts = Counter(
        str(by_pair[pair].get("status") or "unknown")
        for pair in requested
        if pair in by_pair
    )
    if missing:
        status_counts["missing"] += len(missing)
    return {
        "requested_pair_count": len(requested),
        "ready_pair_count": len(ready),
        "ready_pair_pct": (
            round(len(ready) / len(requested) * 100, 4) if requested else None
        ),
        "missing_pair_count": len(missing),
        "status_counts": dict(sorted(status_counts.items())),
        "missing_pairs": [
            {"vt_symbol": symbol, "trade_date": trade_date.isoformat()}
            for symbol, trade_date in missing
        ],
        "pending_pairs": [
            {"vt_symbol": symbol, "trade_date": trade_date.isoformat()}
            for symbol, trade_date in pending
        ],
    }


def _validated_scope(
    scope: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    required = {
        "feature_version",
        "vt_symbol",
        "trade_date",
        "status",
        "source",
        "input_fingerprint",
    }
    missing = sorted(required - set(scope))
    if missing:
        raise ValueError(f"missing transaction scope fields: {', '.join(missing)}")
    values = dict(scope)
    values["feature_version"] = _required_text(values["feature_version"], "feature_version")
    values["vt_symbol"] = _required_text(values["vt_symbol"], "vt_symbol")
    values["trade_date"] = _required_date(values["trade_date"], "trade_date")
    values["status"] = _required_text(values["status"], "status")
    values["source"] = _required_text(values["source"], "source")
    values["input_fingerprint"] = _required_fingerprint(values["input_fingerprint"])
    values["feature_row_count"] = int(values.get("feature_row_count") or 0)
    if values["feature_row_count"] != len(rows):
        raise ValueError("transaction scope feature_row_count does not match rows")
    if values["status"] == FLOW_READY and not rows:
        raise ValueError("flow_ready transaction scope requires feature rows")
    values.setdefault("source_host", {})
    values.setdefault("raw", {})
    return values


def _validated_pair_manifest(manifest: Mapping[str, object]) -> dict[str, object]:
    required = {
        "manifest_version",
        "session_count",
        "start_date",
        "end_date",
        "status",
        "strategy_filter_version",
        "feature_version",
        "input_fingerprint",
        "manifest_pair_count",
        "complete_minute_pair_count",
        "static_upper_bound_pair_count",
        "shared_pair_count",
        "shared_prefix_count",
        "pairs",
        "filter_audit",
        "feature_coverage",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"missing transaction pair manifest fields: {', '.join(missing)}")
    values = dict(manifest)
    values["manifest_version"] = _required_text(
        values["manifest_version"], "manifest_version"
    )
    values["strategy_filter_version"] = _required_text(
        values["strategy_filter_version"], "strategy_filter_version"
    )
    values["feature_version"] = _required_text(
        values["feature_version"], "feature_version"
    )
    values["status"] = _required_text(values["status"], "status")
    if values["status"] != "ready":
        raise ValueError("transaction pair manifest status must be ready")
    values["session_count"] = int(values["session_count"])
    if values["session_count"] < 1:
        raise ValueError("transaction pair manifest session_count must be positive")
    values["start_date"] = _required_date(values["start_date"], "start_date")
    values["end_date"] = _required_date(values["end_date"], "end_date")
    if values["start_date"] > values["end_date"]:
        raise ValueError("transaction pair manifest date range is reversed")
    values["input_fingerprint"] = _required_fingerprint(
        values["input_fingerprint"]
    )
    for field in (
        "manifest_pair_count",
        "complete_minute_pair_count",
        "static_upper_bound_pair_count",
        "shared_pair_count",
        "shared_prefix_count",
    ):
        values[field] = int(values[field])
        if values[field] < 0:
            raise ValueError(f"transaction pair manifest {field} must be nonnegative")
    pairs = _validated_manifest_pairs(
        values["pairs"],
        start_date=values["start_date"],
        end_date=values["end_date"],
    )
    if values["shared_pair_count"] != len(pairs):
        raise ValueError("transaction pair manifest shared_pair_count does not match pairs")
    values["pairs"] = pairs
    for field in ("filter_audit", "feature_coverage"):
        if not isinstance(values[field], Mapping):
            raise ValueError(f"transaction pair manifest {field} must be a mapping")
        values[field] = dict(values[field])
    return values


def _validated_manifest_pairs(
    value: object,
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("transaction pair manifest pairs must be a sequence")
    pairs: set[tuple[str, date]] = set()
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError("transaction pair manifest pair must be a mapping")
        symbol = _required_text(row.get("vt_symbol"), "vt_symbol")
        raw_date = row.get("trade_date")
        pair_date = (
            date.fromisoformat(str(raw_date)[:10])
            if not isinstance(raw_date, date)
            else _required_date(raw_date, "trade_date")
        )
        if pair_date < start_date or pair_date > end_date:
            raise ValueError("transaction pair manifest pair is outside its date range")
        pairs.add((symbol, pair_date))
    return [
        {"vt_symbol": symbol, "trade_date": trade_date.isoformat()}
        for symbol, trade_date in sorted(pairs, key=lambda pair: (pair[1], pair[0]))
    ]


def _validated_feature_row(
    row: Mapping[str, object],
    scope: Mapping[str, object],
) -> dict[str, object]:
    values = dict(row)
    for field in ("feature_version", "vt_symbol", "trade_date", "input_fingerprint"):
        if values.get(field) != scope.get(field):
            raise ValueError(f"transaction feature {field} differs from scope")
    if not isinstance(values.get("bar_time"), datetime):
        raise ValueError("transaction feature bar_time must be datetime")
    if not isinstance(values.get("values"), Mapping):
        raise ValueError("transaction feature values must be a mapping")
    values["source"] = _required_text(values.get("source"), "source")
    values["values"] = dict(values["values"])
    return values


def _normalize_pairs(
    pairs: Sequence[tuple[str, date]],
) -> list[tuple[str, date]]:
    normalized = {
        (_required_text(symbol, "vt_symbol"), _required_date(trade_date, "trade_date"))
        for symbol, trade_date in pairs
    }
    return sorted(normalized, key=lambda pair: (pair[1], pair[0]))


def _scope_pair(scope: Mapping[str, object]) -> tuple[str, date]:
    return (
        _required_text(scope.get("vt_symbol"), "vt_symbol"),
        _required_date(scope.get("trade_date"), "trade_date"),
    )


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _required_date(value: object, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError(f"{field} must be date")


def _required_fingerprint(value: object) -> str:
    text = _required_text(value, "input_fingerprint")
    if not text.startswith("sha256:") or len(text) != 71:
        raise ValueError("input_fingerprint must be a SHA-256 value")
    return text
