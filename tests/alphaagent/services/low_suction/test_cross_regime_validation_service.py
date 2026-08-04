from __future__ import annotations

from alphaagent.server.services.low_suction import (
    cross_regime_validation_service as service,
)


def test_product_view_combines_final_candidate_and_natural_gates(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service,
        "load_causal_forward_report",
        lambda: {
            "diagnostic_policies": {
                "causal-leader-pullback-rotation-next-session-v1": {
                    "research_status": "accumulating_natural_forward",
                    "qualification": {
                        "sample_gates_passed": False,
                        "performance_gates_passed": False,
                        "all_gates_passed": False,
                    },
                    "verified_forward_metrics": None,
                },
                "causal-leader-pullback-three-phase-adaptive-v1": {
                    "research_status": "accumulating_natural_forward",
                    "qualification": {
                        "sample_gates_passed": False,
                        "performance_gates_passed": False,
                        "all_gates_passed": False,
                    },
                    "verified_forward_metrics": None,
                },
            }
        },
    )

    product = service.get_cross_regime_validation()

    assert product["research_status"] == "historical_evidence_retired"
    assert product["formal_strategy"] is False
    assert product["current_candidate"] is None
    assert product["adaptive_candidate"] is None
    assert product["natural_forward"]["verified_forward_metrics"] is None
    assert product["three_phase_candidate"] is None
    assert product["three_phase_natural_forward"][
        "verified_forward_metrics"
    ] is None
    assert product["artifact"] is None
    assert product["three_phase_artifact"] is None
