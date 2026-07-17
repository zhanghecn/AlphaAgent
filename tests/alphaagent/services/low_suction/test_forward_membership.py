from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.low_suction.forward_membership import (
    ForwardMembershipCaptureError,
    build_forward_membership_capture,
)
from alphaagent.server.services.low_suction.theme_reference_cohorts import (
    MANIFEST_VERSION,
    REFERENCE_MANIFEST,
    ThemeManifestRecord,
)

SOURCE_DATE = date(2026, 7, 16)
OBSERVED_AT = datetime(2026, 7, 16, 19, 8, tzinfo=ZoneInfo("Asia/Shanghai"))


def _sector(
    sector_id: str,
    *,
    name: str | None = None,
    sector_type: str = "theme",
) -> dict[str, object]:
    return {
        "id": sector_id,
        "name": name or sector_id,
        "type": sector_type,
    }


def _members(
    sector_id: str,
    *,
    vt_symbol: str = "600000.SSE",
) -> list[dict[str, object]]:
    return [
        {
            "vt_symbol": vt_symbol,
            "symbol": vt_symbol.split(".", maxsplit=1)[0],
            "name": f"{sector_id}-member",
            "source": "eastmoney.push2.board",
            "raw": {"sector_id": sector_id},
        }
    ]


def test_report_failures_allow_tradable_scope_by_exact_id_only() -> None:
    sectors = [
        _sector("BK1677"),
        _sector("BK1678"),
        _sector("BK1679"),
        _sector("BK9000"),
        _sector("BK1000", sector_type="industry"),
    ]

    capture = build_forward_membership_capture(
        sectors=sectors,
        members_by_sector={"BK9000": _members("BK9000")},
        failed_sector_ids=("BK1677", "BK1678", "BK1679", "BK1000"),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )

    assert capture.catalog_scope.complete is False
    assert capture.catalog_scope.expected_sector_count == 4
    assert capture.catalog_scope.returned_sector_count == 1
    assert capture.tradable_scope.complete is True
    assert capture.tradable_scope.expected_sector_count == 1
    assert capture.tradable_scope.returned_sector_count == 1
    assert [
        row["sector_id"]
        for row in capture.tradable_scope.raw["excluded_sectors"]
    ] == ["BK1677", "BK1678", "BK1679"]
    assert {
        row["manifest_class"]
        for row in capture.tradable_scope.raw["excluded_sectors"]
    } == {"report_event"}
    assert capture.tradable_scope.raw["manifest_version"] == MANIFEST_VERSION
    assert [record.sector_id for record in capture.records] == ["BK9000"]
    assert capture.records[0].manifest_class == "unlabeled"


def test_name_does_not_exclude_an_unlabelled_id() -> None:
    capture = build_forward_membership_capture(
        sectors=[_sector("BK9999", name="2025年报预增")],
        members_by_sector={},
        failed_sector_ids=("BK9999",),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )

    assert capture.tradable_scope.complete is False
    assert capture.tradable_scope.raw["missing_sector_ids"] == ["BK9999"]
    assert capture.tradable_scope.raw["excluded_sectors"] == []
    assert capture.records == ()


@pytest.mark.parametrize("sector_id", ["BK0963", "BK9999"])
def test_narrative_or_unlabelled_failure_closes_tradable_scope(
    sector_id: str,
) -> None:
    capture = build_forward_membership_capture(
        sectors=[_sector(sector_id)],
        members_by_sector={},
        failed_sector_ids=(sector_id,),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )

    assert capture.tradable_scope.complete is False
    assert capture.tradable_scope.evidence_level == "rejected_partial_response"
    assert capture.records == ()


def test_all_non_tradable_manifest_classes_are_exactly_excluded() -> None:
    sectors = [
        _sector("BK1630", name="renamed mechanical"),
        _sector("BK1714", name="renamed style"),
        _sector("BK1677", name="renamed report"),
        _sector("BK9000"),
    ]
    capture = build_forward_membership_capture(
        sectors=sectors,
        members_by_sector={"BK9000": _members("BK9000")},
        failed_sector_ids=("BK1630", "BK1714", "BK1677"),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )

    excluded = {
        row["sector_id"]: row["manifest_class"]
        for row in capture.tradable_scope.raw["excluded_sectors"]
    }
    assert excluded == {
        "BK1630": "mechanical_event",
        "BK1677": "report_event",
        "BK1714": "style_universe",
    }


def test_exact_ambiguous_manifest_record_is_excluded() -> None:
    manifest = {
        **REFERENCE_MANIFEST,
        "BK9998": ThemeManifestRecord(
            sector_id="BK9998",
            observed_name="待定板块",
            board_class="ambiguous",
            evidence_reason="identity is not settled",
            first_verified_date=SOURCE_DATE,
        ),
    }

    capture = build_forward_membership_capture(
        sectors=[_sector("BK9998"), _sector("BK9000")],
        members_by_sector={"BK9000": _members("BK9000")},
        failed_sector_ids=("BK9998",),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
        manifest=manifest,
    )

    assert capture.tradable_scope.complete is True
    assert capture.tradable_scope.raw["excluded_sectors"][0][
        "manifest_class"
    ] == "ambiguous"


def test_duplicate_catalog_or_member_identity_is_rejected() -> None:
    with pytest.raises(ForwardMembershipCaptureError, match="duplicate sector ID"):
        build_forward_membership_capture(
            sectors=[_sector("BK9000"), _sector("bk9000")],
            members_by_sector={"BK9000": _members("BK9000")},
            failed_sector_ids=(),
            source_trade_date=SOURCE_DATE,
            observed_at=OBSERVED_AT,
        )

    duplicate_members = [*_members("BK9000"), *_members("BK9000")]
    with pytest.raises(ForwardMembershipCaptureError, match="duplicate member"):
        build_forward_membership_capture(
            sectors=[_sector("BK9000")],
            members_by_sector={"BK9000": duplicate_members},
            failed_sector_ids=(),
            source_trade_date=SOURCE_DATE,
            observed_at=OBSERVED_AT,
        )


@pytest.mark.parametrize(
    "observed_at",
    [
        datetime(2026, 7, 16, 14, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
        datetime(2026, 7, 17, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        datetime(2026, 7, 16, 19, 0),
    ],
)
def test_capture_requires_same_day_post_close_observation(
    observed_at: datetime,
) -> None:
    with pytest.raises(ForwardMembershipCaptureError, match="post-close|timezone"):
        build_forward_membership_capture(
            sectors=[_sector("BK9000")],
            members_by_sector={"BK9000": _members("BK9000")},
            failed_sector_ids=(),
            source_trade_date=SOURCE_DATE,
            observed_at=observed_at,
        )


def test_capture_rows_are_immutable_values() -> None:
    capture = build_forward_membership_capture(
        sectors=[_sector("BK9000")],
        members_by_sector={"BK9000": _members("BK9000")},
        failed_sector_ids=(),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )

    changed = replace(capture.records[0], sector_name="changed")
    assert capture.records[0].sector_name == "BK9000"
    assert changed.sector_name == "changed"
