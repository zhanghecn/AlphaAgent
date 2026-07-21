"""Frozen three-state eligibility for transaction-flow pre-board research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from math import isfinite

from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
    TRANSACTION_FEATURE_VERSION,
)


SCOREABLE = "scoreable"
CAUSAL_NO_ACTION = "causal_no_action"
DATA_MISSING = "data_missing"
MINIMUM_SCOREABLE_PREFIX_PCT = 95.0


def classify_transaction_prefixes(
    prefix_rows: Sequence[Mapping[str, object]],
    feature_rows: Sequence[Mapping[str, object]],
    *,
    ready_pairs: set[tuple[str, date]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Assign exactly one causal data disposition to every prefix."""

    normalized_ready = {
        (str(symbol), _as_date(trade_date))
        for symbol, trade_date in ready_pairs
    }
    feature_index: dict[tuple[str, date, str], dict[str, object]] = {}
    for raw in feature_rows:
        row = dict(raw)
        key = _feature_key(row)
        if key in feature_index:
            raise ValueError(f"duplicate transaction feature minute: {key}")
        feature_index[key] = row

    seen_prefixes: set[tuple[str, date, str]] = set()
    counts = {SCOREABLE: 0, CAUSAL_NO_ACTION: 0, DATA_MISSING: 0}
    details: list[dict[str, object]] = []
    joined: list[dict[str, object]] = []
    for raw in prefix_rows:
        row = dict(raw)
        key = _prefix_key(row)
        if key is None:
            disposition = DATA_MISSING
            reason = "invalid_prefix_identity"
            matched = None
        else:
            if key in seen_prefixes:
                raise ValueError(f"duplicate transaction prefix minute: {key}")
            seen_prefixes.add(key)
            matched = feature_index.get(key)
            values = _feature_values(matched)
            if key[:2] not in normalized_ready:
                disposition = DATA_MISSING
                reason = "scope_not_flow_ready"
            elif matched is None:
                disposition = CAUSAL_NO_ACTION
                reason = "frozen_feature_formula_unscoreable"
            elif values is None:
                disposition = DATA_MISSING
                reason = "invalid_feature_values"
            else:
                disposition = SCOREABLE
                reason = "ready"
        values = _feature_values(matched)
        counts[disposition] += 1
        if disposition != SCOREABLE:
            details.append(
                {
                    "vt_symbol": key[0] if key is not None else str(row.get("vt_symbol") or ""),
                    "signal_date": key[1].isoformat() if key is not None else str(row.get("signal_date") or "")[:10],
                    "signal_time": key[2] if key is not None else str(row.get("signal_time") or "")[:5],
                    "disposition": disposition,
                    "reason": reason,
                }
            )
        joined.append(
            {
                **row,
                "transaction_disposition": disposition,
                "transaction_disposition_reason": reason,
                "transaction_features": values if disposition == SCOREABLE else None,
                "transaction_feature_version": (
                    matched.get("feature_version") if matched is not None else TRANSACTION_FEATURE_VERSION
                ),
                "transaction_input_fingerprint": (
                    matched.get("input_fingerprint") if matched is not None else None
                ),
            }
        )

    prefix_count = len(prefix_rows)
    disposed = sum(counts.values())
    audit = {
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "prefix_count": prefix_count,
        "scoreable_prefix_count": counts[SCOREABLE],
        "causal_no_action_prefix_count": counts[CAUSAL_NO_ACTION],
        "data_missing_prefix_count": counts[DATA_MISSING],
        "disposition_count": disposed,
        "disposition_coverage_pct": _percentage(disposed, prefix_count),
        "scoreable_prefix_pct": _percentage(counts[SCOREABLE], prefix_count),
        "causal_no_action_prefix_pct": _percentage(
            counts[CAUSAL_NO_ACTION], prefix_count
        ),
        "disposition_details": details,
        "transaction_feature_count": len(feature_index),
    }
    return joined, audit


def build_disposition_coverage_checks(
    audit: Mapping[str, object],
    *,
    minimum_scoreable_prefix_pct: float = MINIMUM_SCOREABLE_PREFIX_PCT,
) -> dict[str, object]:
    """Apply the frozen v5 data gate without inspecting outcomes."""

    minimum = float(minimum_scoreable_prefix_pct)
    if not isfinite(minimum) or not 0.0 <= minimum <= 100.0:
        raise ValueError("minimum_scoreable_prefix_pct must be between 0 and 100")
    checks = {
        "transaction_disposition_coverage_100pct": (
            _number(audit.get("disposition_coverage_pct")) == 100.0
        ),
        "transaction_data_missing_zero": (
            int(audit.get("data_missing_prefix_count") or 0) == 0
        ),
        "minimum_95pct_scoreable_prefixes": (
            (_number(audit.get("scoreable_prefix_pct")) or -1.0) >= minimum
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "minimum_scoreable_prefix_pct": minimum,
    }


def build_causal_no_action_attribution(
    rows: Sequence[Mapping[str, object]],
    *,
    validation_dates: set[date],
    formal_identity_pairs: set[tuple[str, date]],
    original_account_pairs: set[tuple[str, date]],
) -> dict[str, object]:
    """Describe frozen no-action states without feeding them back to the model."""

    no_action_rows = [
        row
        for row in rows
        if str(row.get("transaction_disposition") or "") == CAUSAL_NO_ACTION
    ]
    validation_rows = [
        row
        for row in no_action_rows
        if (parsed := _optional_date(row.get("signal_date"))) in validation_dates
    ]
    all_pairs = {_row_pair(row) for row in no_action_rows}
    validation_pairs = {_row_pair(row) for row in validation_rows}
    normalized_formal = {
        (str(symbol), _as_date(trade_date))
        for symbol, trade_date in formal_identity_pairs
    }
    normalized_original = {
        (str(symbol), _as_date(trade_date))
        for symbol, trade_date in original_account_pairs
    }
    return {
        "minute_count": len(no_action_rows),
        "pair_count": len(all_pairs),
        "validation_minute_count": len(validation_rows),
        "validation_pair_count": len(validation_pairs),
        "validation_formal_identity_intersection_count": len(
            validation_pairs & normalized_formal
        ),
        "validation_original_account_intersection_count": len(
            validation_pairs & normalized_original
        ),
        "validation_pairs": [
            {"vt_symbol": symbol, "trade_date": trade_date.isoformat()}
            for symbol, trade_date in sorted(
                validation_pairs,
                key=lambda pair: (pair[1], pair[0]),
            )
        ],
    }


def _feature_values(row: Mapping[str, object] | None) -> dict[str, object] | None:
    if row is None:
        return None
    raw = row.get("values")
    values = dict(raw) if isinstance(raw, Mapping) else {}
    if not all(_number(values.get(name)) is not None for name in TRANSACTION_FEATURE_NAMES):
        return None
    return values


def _feature_key(row: Mapping[str, object]) -> tuple[str, date, str]:
    symbol = str(row.get("vt_symbol") or "").strip()
    trade_date = _as_date(row.get("trade_date"))
    bar_time = _as_datetime(row.get("bar_time"))
    if not symbol or bar_time is None:
        raise ValueError("transaction feature identity is invalid")
    return symbol, trade_date, bar_time.strftime("%H:%M")


def _prefix_key(row: Mapping[str, object]) -> tuple[str, date, str] | None:
    symbol = str(row.get("vt_symbol") or "").strip()
    try:
        signal_date = _as_date(row.get("signal_date"))
    except ValueError:
        return None
    signal_time = str(row.get("signal_time") or "")[:5]
    try:
        datetime.strptime(signal_time, "%H:%M")
    except ValueError:
        return None
    return (symbol, signal_date, signal_time) if symbol else None


def _row_pair(row: Mapping[str, object]) -> tuple[str, date]:
    return str(row.get("vt_symbol") or ""), _as_date(row.get("signal_date"))


def _optional_date(value: object) -> date | None:
    try:
        return _as_date(value)
    except ValueError:
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid trade date: {value}") from exc


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 4) if denominator else None
