from __future__ import annotations

from datetime import date, datetime

import pytest

from alphaagent.server.services.limit_up.preboard_transaction_disposition import (
    CAUSAL_NO_ACTION,
    DATA_MISSING,
    SCOREABLE,
    build_causal_no_action_attribution,
    build_disposition_coverage_checks,
    classify_transaction_prefixes,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
    TRANSACTION_FEATURE_VERSION,
)


def test_classification_is_mutually_exclusive_and_complete() -> None:
    prefixes = [
        _prefix("600001.SSE", "2026-07-16", "10:00"),
        _prefix("600001.SSE", "2026-07-16", "10:01"),
        _prefix("600002.SSE", "2026-07-16", "10:00"),
    ]
    features = [_feature("600001.SSE", "2026-07-16", "10:00")]

    rows, audit = classify_transaction_prefixes(
        prefixes,
        features,
        ready_pairs={("600001.SSE", date(2026, 7, 16))},
    )

    assert [row["transaction_disposition"] for row in rows] == [
        SCOREABLE,
        CAUSAL_NO_ACTION,
        DATA_MISSING,
    ]
    assert rows[0]["transaction_features"] is not None
    assert rows[1]["transaction_features"] is None
    assert rows[2]["transaction_features"] is None
    assert audit["scoreable_prefix_count"] == 1
    assert audit["causal_no_action_prefix_count"] == 1
    assert audit["data_missing_prefix_count"] == 1
    assert audit["disposition_coverage_pct"] == 100.0


def test_invalid_feature_values_fail_closed_instead_of_becoming_no_action() -> None:
    feature = _feature("600001.SSE", "2026-07-16", "10:00")
    feature["values"][TRANSACTION_FEATURE_NAMES[0]] = float("nan")

    rows, audit = classify_transaction_prefixes(
        [_prefix("600001.SSE", "2026-07-16", "10:00")],
        [feature],
        ready_pairs={("600001.SSE", date(2026, 7, 16))},
    )

    assert rows[0]["transaction_disposition"] == DATA_MISSING
    assert rows[0]["transaction_disposition_reason"] == "invalid_feature_values"
    assert audit["causal_no_action_prefix_count"] == 0
    assert audit["data_missing_prefix_count"] == 1


def test_duplicate_feature_or_prefix_minutes_are_rejected() -> None:
    prefix = _prefix("600001.SSE", "2026-07-16", "10:00")
    feature = _feature("600001.SSE", "2026-07-16", "10:00")
    ready = {("600001.SSE", date(2026, 7, 16))}

    with pytest.raises(ValueError, match="duplicate transaction feature minute"):
        classify_transaction_prefixes([prefix], [feature, feature], ready_pairs=ready)
    with pytest.raises(ValueError, match="duplicate transaction prefix minute"):
        classify_transaction_prefixes([prefix, prefix], [feature], ready_pairs=ready)


@pytest.mark.parametrize(
    ("scoreable_pct", "expected"),
    [(94.9999, False), (95.0, True), (100.0, True)],
)
def test_coverage_gate_freezes_the_95_percent_boundary(
    scoreable_pct: float,
    expected: bool,
) -> None:
    report = build_disposition_coverage_checks(
        {
            "disposition_coverage_pct": 100.0,
            "data_missing_prefix_count": 0,
            "scoreable_prefix_pct": scoreable_pct,
        }
    )

    assert report["passed"] is expected
    assert report["checks"]["minimum_95pct_scoreable_prefixes"] is expected


def test_coverage_gate_rejects_missing_data_or_incomplete_disposition() -> None:
    missing = build_disposition_coverage_checks(
        {
            "disposition_coverage_pct": 100.0,
            "data_missing_prefix_count": 1,
            "scoreable_prefix_pct": 99.0,
        }
    )
    incomplete = build_disposition_coverage_checks(
        {
            "disposition_coverage_pct": 99.9,
            "data_missing_prefix_count": 0,
            "scoreable_prefix_pct": 99.0,
        }
    )

    assert missing["passed"] is False
    assert incomplete["passed"] is False


def test_no_action_attribution_is_read_only_and_validation_scoped() -> None:
    rows = [
        {
            **_prefix("600001.SSE", "2026-07-15", "10:00"),
            "transaction_disposition": CAUSAL_NO_ACTION,
        },
        {
            **_prefix("600001.SSE", "2026-07-16", "10:00"),
            "transaction_disposition": CAUSAL_NO_ACTION,
        },
        {
            **_prefix("600001.SSE", "2026-07-16", "10:01"),
            "transaction_disposition": CAUSAL_NO_ACTION,
        },
        {
            **_prefix("600002.SSE", "2026-07-16", "10:00"),
            "transaction_disposition": SCOREABLE,
        },
    ]

    report = build_causal_no_action_attribution(
        rows,
        validation_dates={date(2026, 7, 16)},
        formal_identity_pairs={("600001.SSE", date(2026, 7, 16))},
        original_account_pairs={("600001.SSE", date(2026, 7, 16))},
    )

    assert report["minute_count"] == 3
    assert report["pair_count"] == 2
    assert report["validation_minute_count"] == 2
    assert report["validation_pair_count"] == 1
    assert report["validation_formal_identity_intersection_count"] == 1
    assert report["validation_original_account_intersection_count"] == 1


def _prefix(symbol: str, signal_date: str, signal_time: str) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "signal_time": signal_time,
        "signal_at": f"{signal_date}T{signal_time}:00",
    }


def _feature(symbol: str, trade_date: str, bar_time: str) -> dict[str, object]:
    parsed_date = date.fromisoformat(trade_date)
    return {
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "vt_symbol": symbol,
        "trade_date": parsed_date,
        "bar_time": datetime.combine(
            parsed_date,
            datetime.strptime(bar_time, "%H:%M").time(),
        ),
        "input_fingerprint": "sha256:" + "a" * 64,
        "values": {
            name: float(index + 1) / 100.0
            for index, name in enumerate(TRANSACTION_FEATURE_NAMES)
        },
    }
