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

    assert product["formal_strategy"] is False
    assert product["current_candidate"]["full_history"]["closed_trades"] == 86
    assert product["current_candidate"]["cash"]["compound_return_pct"] > 60.0
    adaptive = product["adaptive_candidate"]
    assert adaptive["full_history"]["closed_trades"] == 81
    assert adaptive["cash"]["cash_win_rate_pct"] > 60.0
    assert adaptive["cash"]["compound_return_pct"] > 60.0
    assert adaptive["qualification"]["historical_numeric_gates_passed"] is False
    assert product["natural_forward"]["verified_forward_metrics"] is None
    three_phase = product["three_phase_candidate"]
    assert three_phase["full_history"]["closed_trades"] == 89
    assert three_phase["cash"]["compound_return_pct"] > 60.0
    assert three_phase["robustness"]["full_history"]["wilson_95_lower_pct"] > 60.0
    assert [row["id"] for row in three_phase["development_market_phases"]] == [
        "uptrend",
        "rotation",
        "warming",
    ]
    assert three_phase["development_market_phases"][0]["closed_trades"] == 5
    assert three_phase["validation_market_phases"][0]["closed_trades"] == 3
    assert product["three_phase_natural_forward"][
        "verified_forward_metrics"
    ] is None
    assert product["artifact"]["sha256"] == service.REPORT_SHA256
    assert product["three_phase_artifact"]["sha256"] == (
        service.THREE_PHASE_REPORT_SHA256
    )
