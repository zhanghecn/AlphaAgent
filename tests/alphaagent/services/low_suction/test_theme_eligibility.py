from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from alphaagent.server.services.low_suction.theme_eligibility import (
    build_theme_features,
)
from alphaagent.server.services.low_suction.theme_reference_cohorts import (
    classify_manifest_sector,
    validate_manifest_coverage,
)


def _membership_frames() -> tuple[pd.DataFrame, pd.DataFrame, tuple[date, ...]]:
    dates = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(21))
    member_rows: list[dict[str, object]] = []
    scope_rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        sets = {
            "EVENT": {f"E{index:02d}A", f"E{index:02d}B"},
            "THEME": {"A", "B", "C"},
            "STYLE": {"D", "E"},
        }
        for sector_id, members in sets.items():
            scope_rows.append(
                {
                    "trade_date": trade_date,
                    "sector_id": sector_id,
                    "complete": True,
                }
            )
            member_rows.extend(
                {
                    "trade_date": trade_date,
                    "sector_id": sector_id,
                    "vt_symbol": member,
                }
                for member in members
            )
    return pd.DataFrame(member_rows), pd.DataFrame(scope_rows), dates


def test_jaccard_separates_rotating_event_but_not_stable_style() -> None:
    memberships, scopes, dates = _membership_frames()

    features = build_theme_features(
        memberships,
        scopes,
        board_types={
            "EVENT": "概念板块",
            "THEME": "概念板块",
            "STYLE": "概念板块",
        },
        cutoff=dates[-1],
    )

    assert features.loc["EVENT", "median_jaccard"] == 0.0
    assert features.loc["THEME", "median_jaccard"] == 1.0
    assert features.loc["STYLE", "median_jaccard"] == 1.0
    assert set(features["status"]) == {"ready"}


def test_future_membership_mutation_cannot_change_prior_cutoff() -> None:
    memberships, scopes, dates = _membership_frames()
    cutoff = dates[-2]
    original = build_theme_features(
        memberships,
        scopes,
        board_types={key: "概念板块" for key in ("EVENT", "THEME", "STYLE")},
        cutoff=cutoff,
    )
    mutated = pd.concat(
        [
            memberships,
            pd.DataFrame(
                [
                    {
                        "trade_date": dates[-1],
                        "sector_id": "THEME",
                        "vt_symbol": "FUTURE_ONLY",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    changed = build_theme_features(
        mutated,
        scopes,
        board_types={key: "概念板块" for key in ("EVENT", "THEME", "STYLE")},
        cutoff=cutoff,
    )

    assert changed.loc["THEME"].to_dict() == original.loc["THEME"].to_dict()


def test_missing_scope_is_not_treated_as_an_empty_member_set() -> None:
    memberships, scopes, dates = _membership_frames()
    scopes.loc[
        (scopes["sector_id"] == "THEME")
        & (scopes["trade_date"] == dates[-5]),
        "complete",
    ] = False

    features = build_theme_features(
        memberships,
        scopes,
        board_types={key: "概念板块" for key in ("EVENT", "THEME", "STYLE")},
        cutoff=dates[-1],
    )

    assert features.loc["THEME", "scope_coverage"] == 0.95
    assert features.loc["THEME", "status"] == "insufficient_history"


def test_manifest_classification_uses_exact_id_not_changed_name() -> None:
    assert classify_manifest_sector("BK1630", observed_name="完全不同的名字") == (
        "mechanical_event"
    )
    assert classify_manifest_sector("BK9999", observed_name="昨日首板") == "unlabeled"


def test_manifest_coverage_fails_closed_for_unclassified_active_boards() -> None:
    report = validate_manifest_coverage(("BK1630", "BK1184", "BK9999"))

    assert report["complete"] is False
    assert report["unclassified"] == ["BK9999"]
