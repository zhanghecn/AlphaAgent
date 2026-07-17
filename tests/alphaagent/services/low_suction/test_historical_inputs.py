from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.low_suction.historical_inputs import (
    HistoricalInputValidationError,
    HistoricalMembershipBatch,
    HistoricalMembershipRecord,
    HistoricalSecurityBatch,
    HistoricalSecurityRecord,
    import_historical_memberships,
    import_historical_securities,
    membership_is_valid_at_open,
    security_is_valid_at_open,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _known_at(day: int, hour: int = 9, minute: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=SHANGHAI)


def _membership(
    *,
    sector_id: str = "885001.THI",
    vt_symbol: str = "600001.SSE",
    known_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "sector_id": sector_id,
        "sector_name": "机器人",
        "vt_symbol": vt_symbol,
        "in_date": date(2026, 7, 1),
        "out_date": date(2026, 7, 20),
        "known_at": known_at or _known_at(1),
        "evidence_level": "strict",
        "source": "strict_fixture",
        "source_record_id": f"member:{sector_id}:{vt_symbol}",
    }


def _membership_scope(
    *,
    sector_id: str = "885001.THI",
    expected_member_count: int = 1,
    returned_member_count: int = 1,
    pagination_complete: bool = True,
    known_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "trade_date": date(2026, 7, 1),
        "source_trade_date": date(2026, 6, 30),
        "sector_id": sector_id,
        "expected_member_count": expected_member_count,
        "returned_member_count": returned_member_count,
        "pagination_complete": pagination_complete,
        "known_at": known_at or _known_at(1),
        "evidence_level": "strict",
        "source": "strict_fixture",
        "source_request_id": f"scope:2026-07-01:{sector_id}",
    }


def _security(
    *,
    vt_symbol: str = "600001.SSE",
    name: str = "示例股份",
    status: str = "LISTED",
    risk_warning: bool = False,
    delisted_on: date | None = None,
    evidence_level: str = "strict",
    known_at: datetime | None = None,
    valid_from: date = date(2026, 7, 1),
    valid_to: date = date(2026, 7, 2),
) -> dict[str, object]:
    symbol, exchange = vt_symbol.split(".")
    return {
        "vt_symbol": vt_symbol,
        "symbol": symbol,
        "exchange": exchange,
        "name": name,
        "status": status,
        "board": "main",
        "listed_on": date(2018, 1, 2),
        "delisted_on": delisted_on,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "suspended": False,
        "risk_warning": risk_warning,
        "known_at": known_at or _known_at(1),
        "evidence_level": evidence_level,
        "source": "strict_fixture" if evidence_level == "strict" else "baostock",
        "source_record_id": f"security:{vt_symbol}:{valid_from}:{status}",
    }


def test_membership_interval_is_left_closed_and_known_before_open() -> None:
    record = HistoricalMembershipRecord.from_mapping(_membership())

    assert membership_is_valid_at_open(record, date(2026, 7, 1)) is True
    assert membership_is_valid_at_open(record, date(2026, 7, 19)) is True
    assert membership_is_valid_at_open(record, date(2026, 7, 20)) is False

    late = HistoricalMembershipRecord.from_mapping(
        _membership(known_at=_known_at(1, 9, 26))
    )
    assert membership_is_valid_at_open(late, date(2026, 7, 1)) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("in_date", None), ("out_date", None), ("known_at", datetime(2026, 7, 1, 9))],
)
def test_membership_rejects_incomplete_or_naive_interval_fields(
    field: str,
    value: object,
) -> None:
    row = _membership()
    row[field] = value

    with pytest.raises(HistoricalInputValidationError):
        HistoricalMembershipRecord.from_mapping(row)


def test_provider_documented_unavailable_intervals_never_become_strict() -> None:
    with pytest.raises(
        HistoricalInputValidationError,
        match="interval semantics are unavailable",
    ):
        import_historical_memberships(
            membership_rows=[_membership()],
            membership_scope_rows=[_membership_scope()],
            required_pairs=[(date(2026, 7, 1), "885001.THI")],
            membership_interval_semantics_available=False,
            dry_run=True,
        )


def test_membership_batch_rejects_mixed_evidence_levels() -> None:
    reconstructed = _membership(vt_symbol="600002.SSE")
    reconstructed["evidence_level"] = "reconstructed"

    with pytest.raises(HistoricalInputValidationError, match="evidence levels"):
        import_historical_memberships(
            membership_rows=[_membership(), reconstructed],
            membership_scope_rows=[
                _membership_scope(expected_member_count=2, returned_member_count=2)
            ],
            required_pairs=[(date(2026, 7, 1), "885001.THI")],
            dry_run=True,
        )


def test_truncated_membership_response_never_calls_writer() -> None:
    writes: list[HistoricalMembershipBatch] = []

    report = import_historical_memberships(
        membership_rows=[_membership()],
        membership_scope_rows=[
            _membership_scope(expected_member_count=3, returned_member_count=1)
        ],
        required_pairs=[(date(2026, 7, 1), "885001.THI")],
        writer=writes.append,
        dry_run=False,
    )

    assert report.status == "rejected_partial_response"
    assert report.scope_coverage_pct == 0.0
    assert report.incomplete_scope_pairs == ("2026-07-01:885001.THI",)
    assert writes == []


def test_membership_manifest_must_match_distinct_active_symbols() -> None:
    writes: list[HistoricalMembershipBatch] = []

    report = import_historical_memberships(
        membership_rows=[
            _membership(),
            _membership(vt_symbol="600002.SSE"),
        ],
        membership_scope_rows=[
            _membership_scope(expected_member_count=2, returned_member_count=2)
        ],
        required_pairs=[(date(2026, 7, 1), "885001.THI")],
        writer=writes.append,
        dry_run=False,
    )

    assert report.status == "replaced"
    assert report.scope_coverage_pct == 100.0
    assert len(writes) == 1
    assert len(writes[0].records) == 2
    assert len(writes[0].scopes) == 1


def test_late_membership_scope_is_rejected_even_when_rows_exist() -> None:
    report = import_historical_memberships(
        membership_rows=[_membership()],
        membership_scope_rows=[
            _membership_scope(known_at=_known_at(1, 9, 26))
        ],
        required_pairs=[(date(2026, 7, 1), "885001.THI")],
        dry_run=True,
    )

    assert report.status == "rejected_partial_response"
    assert report.incomplete_scope_pairs == ("2026-07-01:885001.THI",)


def test_security_validity_requires_strict_point_in_time_evidence() -> None:
    strict = HistoricalSecurityRecord.from_mapping(_security())
    reconstructed = HistoricalSecurityRecord.from_mapping(
        _security(evidence_level="reconstructed")
    )
    late = HistoricalSecurityRecord.from_mapping(
        _security(known_at=_known_at(1, 9, 26))
    )

    assert security_is_valid_at_open(strict, date(2026, 7, 1)) is True
    assert security_is_valid_at_open(strict, date(2026, 7, 2)) is False
    assert security_is_valid_at_open(reconstructed, date(2026, 7, 1)) is False
    assert security_is_valid_at_open(late, date(2026, 7, 1)) is False


def test_security_rejects_unknown_evidence_level() -> None:
    with pytest.raises(HistoricalInputValidationError, match="evidence_level"):
        HistoricalSecurityRecord.from_mapping(_security(evidence_level="claimed"))


def test_explicit_security_pairs_do_not_create_cartesian_requirements() -> None:
    report = import_historical_securities(
        security_rows=[_security()],
        required_pairs=[(date(2026, 7, 1), "600001.SSE")],
        dry_run=True,
    )

    assert report.status == "ready_for_atomic_replace"
    assert report.required_pairs == 1
    assert report.scope_coverage_pct == 100.0
    assert report.strict_scope_coverage_pct == 100.0


def test_reconstructed_security_can_be_stored_but_never_becomes_strict() -> None:
    writes: list[HistoricalSecurityBatch] = []

    report = import_historical_securities(
        security_rows=[_security(evidence_level="reconstructed")],
        required_pairs=[(date(2026, 7, 1), "600001.SSE")],
        writer=writes.append,
        dry_run=False,
    )

    assert report.status == "replaced"
    assert report.evidence_level == "reconstructed"
    assert report.scope_coverage_pct == 100.0
    assert report.strict_scope_coverage_pct == 0.0
    assert report.non_strict_security_pairs == ("2026-07-01:600001.SSE",)
    assert len(writes) == 1
    assert writes[0].evidence_level == "reconstructed"


def test_late_strict_security_response_never_calls_writer() -> None:
    writes: list[HistoricalSecurityBatch] = []

    report = import_historical_securities(
        security_rows=[_security(known_at=_known_at(1, 9, 26))],
        required_pairs=[(date(2026, 7, 1), "600001.SSE")],
        writer=writes.append,
        dry_run=False,
    )

    assert report.status == "rejected_non_point_in_time"
    assert report.strict_scope_coverage_pct == 0.0
    assert writes == []


def test_security_import_retains_historical_st_and_delisted_records() -> None:
    st = _security(name="*ST示例", status="ST", risk_warning=True)
    delisted = _security(
        vt_symbol="600002.SSE",
        name="退市示例",
        status="DELISTED",
        delisted_on=date(2026, 7, 1),
    )

    report = import_historical_securities(
        security_rows=[st, delisted],
        required_pairs=[
            (date(2026, 7, 1), "600001.SSE"),
            (date(2026, 7, 1), "600002.SSE"),
        ],
        dry_run=True,
    )

    assert report.status == "ready_for_atomic_replace"
    assert report.security_rows == 2
    assert report.risk_warning_rows == 1
    assert report.delisted_rows == 1


def test_partial_security_scope_never_calls_writer() -> None:
    writes: list[HistoricalSecurityBatch] = []

    report = import_historical_securities(
        security_rows=[_security()],
        required_pairs=[
            (date(2026, 7, 1), "600001.SSE"),
            (date(2026, 7, 1), "600002.SSE"),
        ],
        writer=writes.append,
        dry_run=False,
    )

    assert report.status == "rejected_partial_response"
    assert report.scope_coverage_pct == 50.0
    assert report.missing_security_pairs == ("2026-07-01:600002.SSE",)
    assert writes == []


def test_overlapping_security_rows_are_ambiguous_and_rejected() -> None:
    first = _security()
    second = _security(valid_from=date(2026, 6, 30))
    second["source_record_id"] = "security:600001.SSE:overlap"

    report = import_historical_securities(
        security_rows=[first, second],
        required_pairs=[(date(2026, 7, 1), "600001.SSE")],
        dry_run=True,
    )

    assert report.status == "rejected_partial_response"
    assert report.ambiguous_security_pairs == ("2026-07-01:600001.SSE",)


def test_security_dry_run_reports_counts_without_writing() -> None:
    writes: list[HistoricalSecurityBatch] = []

    report = import_historical_securities(
        security_rows=[_security()],
        required_pairs=[(date(2026, 7, 1), "600001.SSE")],
        writer=writes.append,
        dry_run=True,
    )

    assert report.status == "ready_for_atomic_replace"
    assert report.written is False
    assert writes == []
