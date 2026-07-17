"""Versioned exact-ID reference manifest for Eastmoney concept-board classes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

MANIFEST_VERSION = "low-suction-theme-manifest-seed-v1"


@dataclass(frozen=True)
class ThemeManifestRecord:
    sector_id: str
    observed_name: str
    board_class: str
    evidence_reason: str
    first_verified_date: date


def _record(
    sector_id: str,
    name: str,
    board_class: str,
    reason: str,
) -> ThemeManifestRecord:
    return ThemeManifestRecord(
        sector_id=sector_id,
        observed_name=name,
        board_class=board_class,
        evidence_reason=reason,
        first_verified_date=date(2026, 7, 13),
    )


REFERENCE_MANIFEST = {
    row.sector_id: row
    for row in (
        _record("BK1630", "昨日首板", "mechanical_event", "daily event membership"),
        _record("BK1645", "昨日打二板以上表现", "mechanical_event", "daily event membership"),
        _record("BK0817", "昨日触板", "mechanical_event", "daily event membership"),
        _record("BK1631", "昨日炸板", "mechanical_event", "daily event membership"),
        _record("BK0816", "昨日连板", "mechanical_event", "daily event membership"),
        _record("BK0815", "昨日涨停", "mechanical_event", "daily event membership"),
        _record("BK1050", "昨日涨停_含一字", "mechanical_event", "daily event membership"),
        _record("BK1051", "昨日连板_含一字", "mechanical_event", "daily event membership"),
        _record("BK1632", "昨日高换手", "mechanical_event", "daily event membership"),
        _record("BK1633", "昨日高振幅", "mechanical_event", "daily event membership"),
        _record("BK1714", "金融地产风格", "style_universe", "style universe"),
        _record("BK1682", "2026一季报扭亏", "report_event", "financial report screen"),
        _record("BK1681", "2026一季报预减", "report_event", "financial report screen"),
        _record("BK1680", "2026一季报预增", "report_event", "financial report screen"),
        _record("BK1679", "2025年报扭亏", "report_event", "financial report screen"),
        _record("BK1678", "2025年报预减", "report_event", "financial report screen"),
        _record("BK1677", "2025年报预增", "report_event", "financial report screen"),
        _record("BK1665", "大盘成长", "style_universe", "capitalization style"),
        _record("BK1663", "大盘股", "style_universe", "capitalization style"),
        _record("BK1662", "权重股", "style_universe", "capitalization style"),
        _record("BK0490", "军工", "narrative_theme", "persistent business narrative"),
        _record("BK0800", "人工智能", "narrative_theme", "persistent business narrative"),
        _record("BK0899", "CRO", "narrative_theme", "persistent business narrative"),
        _record("BK0963", "商业航天", "narrative_theme", "persistent business narrative"),
        _record("BK0968", "固态电池", "narrative_theme", "persistent business narrative"),
        _record("BK1090", "机器人概念", "narrative_theme", "persistent business narrative"),
        _record("BK1106", "创新药", "narrative_theme", "persistent business narrative"),
        _record("BK1134", "算力概念", "narrative_theme", "persistent business narrative"),
        _record("BK1166", "低空经济", "narrative_theme", "persistent business narrative"),
        _record("BK1184", "人形机器人", "narrative_theme", "persistent business narrative"),
    )
}


def classify_manifest_sector(
    sector_id: str,
    *,
    observed_name: str | None = None,
) -> str:
    del observed_name
    record = REFERENCE_MANIFEST.get(str(sector_id).strip().upper())
    return record.board_class if record else "unlabeled"


def validate_manifest_coverage(
    active_sector_ids: tuple[str, ...] | list[str],
    *,
    manifest: dict[str, ThemeManifestRecord] | None = None,
) -> dict[str, object]:
    selected = manifest or REFERENCE_MANIFEST
    active = {str(value).strip().upper() for value in active_sector_ids}
    known = set(selected)
    unclassified = sorted(active - known)
    return {
        "version": MANIFEST_VERSION,
        "complete": not unclassified,
        "active_sectors": len(active),
        "classified_sectors": len(active & known),
        "unclassified": unclassified,
        "inactive_manifest_records": sorted(known - active),
    }
