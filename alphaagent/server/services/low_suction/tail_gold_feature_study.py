"""Fixed D-1 GOLD cohort for the leader tail low-suction feature study."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from .tail_feature_study import (
    build_tail_feature_report,
    load_tail_feature_study_data,
)


GOLD_ACTIVE_DIRECTION = "GOLD"

_GOLD_CONCLUSIONS = {
    "no_stable_tail_feature_group": "no_stable_gold_tail_feature_group",
    "tail_feature_stable_positive_group_found_in_reused_history": (
        "gold_tail_feature_stable_positive_group_found_in_reused_history"
    ),
    "tail_feature_high_win_group_found_in_reused_history": (
        "gold_tail_feature_high_win_group_found_in_reused_history"
    ),
}


def build_gold_tail_feature_report(
    features: pd.DataFrame,
    ledger: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a report only after proving every feature/trade row is D-1 GOLD."""

    _assert_gold_only(features, ledger)
    report = build_tail_feature_report(features, ledger, metadata)
    report["study_track"] = "tail_low_suction_gold_feature_discovery"
    report["overall_conclusion"] = _GOLD_CONCLUSIONS.get(
        str(report["overall_conclusion"]),
        str(report["overall_conclusion"]),
    )
    report["cohort_contract"] = {
        "active_direction": GOLD_ACTIVE_DIRECTION,
        "filter_before_minute_outcomes": True,
        "known_at": "D-1 close",
        "parent_direction_counts_read": True,
        "silver_candidate_feature_or_trade_rows": 0,
    }
    report["limitations"] = [
        *report.get("limitations", []),
        "GOLD keeps the original chronological blocks and is not re-split after filtering",
        "parent GOLD/SILVER candidate counts measure coverage only; SILVER features and trades are excluded",
    ]
    block_rows = report.get("coverage", {}).get("block_feature_rows", {})
    if int(block_rows.get("block_5", 0)) == 0:
        report["limitations"].append(
            "GOLD validation contains original block4 only; original block5 has zero GOLD candidates"
        )
    return report


def run_gold_tail_feature_study() -> dict[str, Any]:
    return build_gold_tail_feature_report(
        *load_tail_feature_study_data(active_direction=GOLD_ACTIVE_DIRECTION)
    )


def _assert_gold_only(features: pd.DataFrame, ledger: pd.DataFrame) -> None:
    for label, frame in (("feature", features), ("trade", ledger)):
        missing = [
            column
            for column in ("event_id", "active_direction")
            if column not in frame
        ]
        if missing:
            raise ValueError(
                f"missing GOLD-only {label} columns: {', '.join(missing)}"
            )
        if frame.empty:
            raise ValueError(f"GOLD-only {label} rows cannot be empty")
        directions = set(frame["active_direction"].astype(str).unique())
        if directions != {GOLD_ACTIVE_DIRECTION}:
            raise ValueError(
                f"GOLD-only {label} rows contain directions: {sorted(directions)}"
            )
    if set(features["event_id"]) != set(ledger["event_id"]):
        raise ValueError("GOLD-only feature and trade event IDs must match")
