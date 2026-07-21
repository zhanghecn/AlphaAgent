"""Causal transaction-flow features for pre-board trigger research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from hashlib import sha256
import json
from math import isfinite
from statistics import mean

from alphaagent.server.services.data_providers.tdx_transaction_history import (
    aggregate_transaction_close_minutes,
    validate_transaction_day,
)


TRANSACTION_FEATURE_VERSION = "limit-up-preboard-transaction-flow-v1"
TRANSACTION_FEATURE_NAMES = (
    "tx_trade_count_acceleration_1m_5m",
    "tx_max_print_turnover_share_1m",
    "tx_large_print_turnover_share_1m",
    "tx_large_print_turnover_share_3m",
    "tx_direction_01_imbalance_1m",
    "tx_direction_01_imbalance_3m",
    "tx_price_move_turnover_imbalance_1m",
    "tx_price_move_turnover_imbalance_3m",
    "tx_path_efficiency_1m",
)
_MORNING_START = time(10, 0)
_MORNING_END = time(11, 30)
_AFTERNOON_START = time(13, 1)
_AFTERNOON_END = time(14, 30)


def build_transaction_feature_rows(
    aligned_minutes: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Build the frozen nine-feature vector from completed close-labeled minutes."""

    ordered = sorted(
        (dict(row) for row in aligned_minutes),
        key=lambda row: _datetime(row.get("bar_time")) or datetime.max,
    )
    result: list[dict[str, object]] = []
    for index, row in enumerate(ordered):
        bar_time = _datetime(row.get("bar_time"))
        if bar_time is None or not _eligible_bar_time(bar_time.time()) or index < 5:
            continue
        prior_five = ordered[index - 5 : index]
        recent_three = ordered[max(0, index - 2) : index + 1]
        prior_counts = [_positive(item.get("trade_count")) for item in prior_five]
        current_count = _positive(row.get("trade_count"))
        current_turnover = _positive(row.get("turnover"))
        prior_mean = (
            mean(value for value in prior_counts if value is not None)
            if all(value is not None for value in prior_counts)
            else None
        )
        recent_turnover = _sum_positive(recent_three, "turnover")
        direction_0_1m = _nonnegative(row.get("direction_0_turnover"))
        direction_1_1m = _nonnegative(row.get("direction_1_turnover"))
        direction_0_3m = _sum_nonnegative(recent_three, "direction_0_turnover")
        direction_1_3m = _sum_nonnegative(recent_three, "direction_1_turnover")
        price_up_1m = _nonnegative(row.get("price_up_turnover"))
        price_down_1m = _nonnegative(row.get("price_down_turnover"))
        price_up_3m = _sum_nonnegative(recent_three, "price_up_turnover")
        price_down_3m = _sum_nonnegative(recent_three, "price_down_turnover")
        absolute_path = _positive(row.get("absolute_price_path"))
        signed_path = _number(row.get("signed_price_path"))
        values = {
            "tx_trade_count_acceleration_1m_5m": _bounded_ratio(
                current_count,
                prior_mean,
                lower=0.0,
                upper=10.0,
            ),
            "tx_max_print_turnover_share_1m": _bounded_ratio(
                _nonnegative(row.get("max_print_turnover")),
                current_turnover,
                lower=0.0,
                upper=1.0,
            ),
            "tx_large_print_turnover_share_1m": _bounded_ratio(
                _nonnegative(row.get("large_print_turnover")),
                current_turnover,
                lower=0.0,
                upper=1.0,
            ),
            "tx_large_print_turnover_share_3m": _bounded_ratio(
                _sum_nonnegative(recent_three, "large_print_turnover"),
                recent_turnover,
                lower=0.0,
                upper=1.0,
            ),
            "tx_direction_01_imbalance_1m": _imbalance(
                direction_0_1m,
                direction_1_1m,
            ),
            "tx_direction_01_imbalance_3m": _imbalance(
                direction_0_3m,
                direction_1_3m,
            ),
            "tx_price_move_turnover_imbalance_1m": _imbalance(
                price_up_1m,
                price_down_1m,
            ),
            "tx_price_move_turnover_imbalance_3m": _imbalance(
                price_up_3m,
                price_down_3m,
            ),
            "tx_path_efficiency_1m": _bounded_ratio(
                signed_path,
                absolute_path,
                lower=-1.0,
                upper=1.0,
            ),
        }
        if any(value is None for value in values.values()):
            continue
        result.append(
            {
                "trade_date": bar_time.date(),
                "bar_time": bar_time,
                "feature_version": TRANSACTION_FEATURE_VERSION,
                "values": {
                    name: round(float(values[name]), 8)
                    for name in TRANSACTION_FEATURE_NAMES
                },
                "source": str(row.get("source") or "tdx.history_transaction"),
            }
        )
    return result


def build_transaction_feature_capture(
    vt_symbol: str,
    trade_date: date,
    fetched: Mapping[str, object],
    daily_bar: Mapping[str, object],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Build one immutable scope and its causal feature rows."""

    raw_rows = fetched.get("rows")
    transaction_rows = (
        [dict(row) for row in raw_rows if isinstance(row, Mapping)]
        if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, (str, bytes))
        else []
    )
    pagination_complete = fetched.get("pagination_complete") is True
    quality = validate_transaction_day(
        transaction_rows,
        daily_bar,
        pagination_complete=pagination_complete,
    )
    aligned = aggregate_transaction_close_minutes(transaction_rows)
    features = build_transaction_feature_rows(aligned)
    fingerprint = transaction_input_fingerprint(
        vt_symbol,
        trade_date,
        transaction_rows,
        daily_bar,
    )
    feature_rows = [
        {
            **row,
            "feature_version": TRANSACTION_FEATURE_VERSION,
            "vt_symbol": vt_symbol,
            "trade_date": trade_date,
            "input_fingerprint": fingerprint,
        }
        for row in features
    ]
    quality_reasons = list(quality.get("reasons") or [])
    scope_status = str(quality.get("status") or "invalid")
    if scope_status == "flow_ready" and not feature_rows:
        scope_status = "invalid"
        quality_reasons.append("no_scoreable_feature_rows")
    scope = {
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "status": scope_status,
        "source": str(fetched.get("source") or "tdx.history_transaction"),
        "source_host": dict(fetched.get("host") or {}),
        "page_count": int(fetched.get("page_count") or 0),
        "raw_row_count": int(fetched.get("raw_row_count") or 0),
        "trade_row_count": len(transaction_rows),
        "pagination_complete": pagination_complete,
        "first_time": quality.get("first_time"),
        "last_time": quality.get("last_time"),
        "volume_matches": quality.get("volume_matches") is True,
        "observed_volume": quality.get("observed_volume"),
        "expected_volume": quality.get("expected_volume"),
        "volume_difference": quality.get("volume_difference"),
        "close_difference": quality.get("close_difference"),
        "high_difference": quality.get("high_difference"),
        "low_difference": quality.get("low_difference"),
        "price_audit_status": quality.get("price_audit_status"),
        "input_fingerprint": fingerprint,
        "feature_row_count": len(feature_rows),
        "raw": {
            "quality_reasons": quality_reasons,
            "aligned_minute_count": len(aligned),
            "feature_names": list(TRANSACTION_FEATURE_NAMES),
        },
    }
    return scope, feature_rows


def transaction_input_fingerprint(
    vt_symbol: str,
    trade_date: date,
    rows: Sequence[Mapping[str, object]],
    daily_bar: Mapping[str, object],
) -> str:
    """Hash only model inputs, excluding mutable host/fetch metadata."""

    payload = {
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "vt_symbol": str(vt_symbol),
        "trade_date": trade_date.isoformat(),
        "daily_bar": {
            field: _canonical_number(daily_bar.get(field))
            for field in ("volume", "high_price", "low_price", "close_price")
        },
        "transactions": [
            [
                int(row.get("sequence") or 0),
                str(row.get("time") or ""),
                _canonical_number(row.get("price")),
                _canonical_number(row.get("volume")),
                int(row.get("direction_code") or 0),
            ]
            for row in sorted(rows, key=lambda item: int(item.get("sequence") or 0))
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _eligible_bar_time(value: time) -> bool:
    return _MORNING_START <= value <= _MORNING_END or _AFTERNOON_START <= value <= _AFTERNOON_END


def _sum_positive(rows: Sequence[Mapping[str, object]], field: str) -> float | None:
    values = [_positive(row.get(field)) for row in rows]
    return sum(value for value in values if value is not None) if all(value is not None for value in values) else None


def _sum_nonnegative(rows: Sequence[Mapping[str, object]], field: str) -> float | None:
    values = [_nonnegative(row.get(field)) for row in rows]
    return sum(value for value in values if value is not None) if all(value is not None for value in values) else None


def _imbalance(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or left + right <= 0:
        return None
    return min(max((left - right) / (left + right), -1.0), 1.0)


def _bounded_ratio(
    numerator: float | None,
    denominator: float | None,
    *,
    lower: float,
    upper: float,
) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return min(max(numerator / denominator, lower), upper)


def _canonical_number(value: object) -> float | None:
    number = _number(value)
    return 0.0 if number == 0.0 else number


def _positive(value: object) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _nonnegative(value: object) -> float | None:
    number = _number(value)
    return number if number is not None and number >= 0 else None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _datetime(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None
