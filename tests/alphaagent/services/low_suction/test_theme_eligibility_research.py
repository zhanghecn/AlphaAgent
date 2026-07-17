from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from alphaagent.server.services.low_suction.theme_eligibility_research import (
    run_theme_eligibility_research,
)
from alphaagent.server.services.low_suction.theme_reference_cohorts import (
    ThemeManifestRecord,
)


def _manifest() -> dict[str, ThemeManifestRecord]:
    return {
        "THEME": ThemeManifestRecord(
            sector_id="THEME",
            observed_name="真实题材",
            board_class="narrative_theme",
            evidence_reason="fixture",
            first_verified_date=date(2025, 1, 1),
        ),
        "EVENT": ThemeManifestRecord(
            sector_id="EVENT",
            observed_name="事件板块",
            board_class="mechanical_event",
            evidence_reason="fixture",
            first_verified_date=date(2025, 1, 1),
        ),
        "STYLE": ThemeManifestRecord(
            sector_id="STYLE",
            observed_name="风格板块",
            board_class="style_universe",
            evidence_reason="fixture",
            first_verified_date=date(2025, 1, 1),
        ),
    }


def _panel(*, theme_jaccard: float = 0.8) -> pd.DataFrame:
    rows = []
    for index in range(10):
        cutoff = date(2025, 1, 1) + timedelta(days=index)
        for sector_id, jaccard in (
            ("THEME", theme_jaccard),
            ("EVENT", 0.05),
            ("STYLE", 1.0),
        ):
            rows.append(
                {
                    "cutoff": cutoff,
                    "sector_id": sector_id,
                    "status": "ready",
                    "median_jaccard": jaccard,
                    "scope_coverage": 1.0,
                }
            )
    return pd.DataFrame(rows)


def test_rule_is_selected_on_development_then_validated_without_returns() -> None:
    report = run_theme_eligibility_research(
        _panel(),
        manifest=_manifest(),
        strict_membership_ready=True,
    )

    assert report["status"] == "qualified_taxonomy"
    assert report["formal_metrics"] is None
    assert report["rule"]["median_jaccard_floor"] == 0.3
    assert report["rule"]["scope_coverage_floor"] == 0.9
    assert report["development"]["narrative_theme_retention_rate"] == 100.0
    assert report["validation"]["mechanical_or_style_false_eligibility_rate"] == 0.0
    assert report["holdout_rows"] == 6


def test_holdout_mutation_does_not_change_selected_rule() -> None:
    baseline = _panel()
    original = run_theme_eligibility_research(
        baseline,
        manifest=_manifest(),
        strict_membership_ready=True,
    )
    mutated = baseline.copy()
    holdout_dates = sorted(mutated["cutoff"].unique())[-2:]
    mutated.loc[mutated["cutoff"].isin(holdout_dates), "median_jaccard"] = 0.0
    changed = run_theme_eligibility_research(
        mutated,
        manifest=_manifest(),
        strict_membership_ready=True,
    )

    assert changed["rule"] == original["rule"]


def test_no_failing_threshold_is_promoted() -> None:
    report = run_theme_eligibility_research(
        _panel(theme_jaccard=0.1),
        manifest=_manifest(),
        strict_membership_ready=True,
    )

    assert report["status"] == "no_qualified_taxonomy"
    assert report["rule"] is None


def test_missing_strict_membership_blocks_before_manifest_or_thresholds() -> None:
    report = run_theme_eligibility_research(
        pd.DataFrame(),
        manifest={},
        strict_membership_ready=False,
    )

    assert report == {
        "status": "blocked_by_historical_membership",
        "qualified": False,
        "formal_metrics": None,
        "rule": None,
    }
