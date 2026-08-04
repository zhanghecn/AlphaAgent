"""Read-only status for retired low-suction swing research evidence."""

from __future__ import annotations

from typing import Any


def get_swing_research() -> dict[str, Any]:
    """Keep the legacy endpoint fail-closed after retiring local report archives."""

    return {
        "research_kind": "historical_swing_proxy",
        "research_status": "historical_evidence_retired",
        "formal_strategy": False,
        "formal_metrics": None,
        "historical_proxy_available": False,
        "boundaries": [
            "Historical swing artifacts were retired with the local memory archive.",
            "The retired proxy is not a product, recommendation, or trading contract.",
            "Current daily low-suction research remains exploratory only.",
        ],
    }
