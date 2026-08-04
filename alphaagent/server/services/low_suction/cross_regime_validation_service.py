"""Read-only cross-regime status without retired historical report archives."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .causal_leader_pullback import (
    ROTATION_NEXT_SESSION_POLICY_VERSION,
    THREE_PHASE_ADAPTIVE_POLICY_VERSION,
)
from .causal_leader_pullback_forward_repository import load_causal_forward_report


REPORT_VERSION = "cross-regime-validation-product-v1"


def get_cross_regime_validation() -> dict[str, Any]:
    """Expose current natural-forward status without resurrecting old metrics."""

    forward = load_causal_forward_report()
    diagnostics = forward.get("diagnostic_policies")
    if not isinstance(diagnostics, Mapping):
        raise ValueError("causal forward report diagnostic_policies must be an object")
    return {
        "report_version": REPORT_VERSION,
        "research_status": "historical_evidence_retired",
        "formal_strategy": False,
        "current_candidate": None,
        "adaptive_candidate": None,
        "three_phase_candidate": None,
        "natural_forward": diagnostics.get(ROTATION_NEXT_SESSION_POLICY_VERSION),
        "three_phase_natural_forward": diagnostics.get(
            THREE_PHASE_ADAPTIVE_POLICY_VERSION
        ),
        "artifact": None,
        "three_phase_artifact": None,
        "boundaries": [
            "Historical cross-regime artifacts were retired with the local memory archive.",
            "Only natural-forward diagnostic status is retained here.",
            "No historical metric forms a strategy, recommendation, or trading contract.",
        ],
    }
