from __future__ import annotations

from alphaagent.server.services.limit_up import (
    preboard_transaction_disposition_study as study,
)
from alphaagent.server.services.limit_up import preboard_transaction_trigger_study as v4
from alphaagent.server.services.limit_up.preboard_transaction_trigger_model import (
    transaction_trigger_feature_vector,
)


def test_v5_entrypoint_selects_only_the_explicit_no_action_contract(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def evaluate(**kwargs):
        captured.update(kwargs)
        return {"status": "sentinel"}

    monkeypatch.setattr(v4, "_evaluate_preboard_transaction_trigger", evaluate)

    result = study.evaluate_preboard_transaction_disposition(session_count=89)

    assert result == {"status": "sentinel"}
    assert captured == {
        "session_count": 89,
        "study_version": study.STUDY_VERSION,
        "coverage_contract": v4.EXPLICIT_NO_ACTION_V5_COVERAGE,
        "candidate_key": "v5",
    }


def test_v5_renderer_uses_distinct_version_and_candidate_label() -> None:
    markdown = study.render_preboard_transaction_disposition_markdown(
        {
            "study_version": study.STUDY_VERSION,
            "status": "ready_historical_rejected",
            "decision": "historical_rejected_no_live_promotion",
            "candidate_key": "v5",
            "candidate_label": "v5逐笔模型",
            "report_title": "首板逐笔三态触发 v5 研究",
            "transaction_coverage": {},
            "v3": {},
            "v5": {},
            "acceptance": {"passed": False, "checks": {}},
            "causal_no_action_attribution": {
                "minute_count": 17,
                "pair_count": 14,
                "validation_minute_count": 8,
                "validation_pair_count": 6,
                "validation_formal_identity_intersection_count": 1,
                "validation_original_account_intersection_count": 0,
            },
        }
    )

    assert markdown.startswith("# 首板逐笔三态触发 v5 研究")
    assert "| v5逐笔模型 |" in markdown
    assert "全样本 17 个分钟、14 个股票日" in markdown


def test_causal_no_action_row_cannot_enter_the_frozen_model() -> None:
    row = {
        "transaction_disposition": "causal_no_action",
        "transaction_features": None,
    }

    assert transaction_trigger_feature_vector(row) is None


def test_v5_acceptance_uses_disposition_gate_instead_of_v4_100pct_scoreable() -> None:
    validation = {
        "identity": {
            "selection_count": 30,
            "formal_identity_precision_pct": 80.0,
            "reachable_formal_recall_pct": 40.0,
        },
        "account_identity": {"precision_pct": 80.0},
        "accounts": {
            "formal_touch": {"win_rate": 70.0},
            "joint_action": {
                "total_return_pct": 10.0,
                "max_drawdown_pct": -5.0,
                "win_rate": 70.0,
                "profit_factor": 1.5,
            },
            "joint_action_double_cost": {"total_return_pct": 8.0},
        },
    }
    blocks = [
        {
            "accounts": {
                "joint_action": {"trade_count": 2, "total_return_pct": 1.0}
            }
        }
        for _ in range(3)
    ] + [
        {
            "accounts": {
                "joint_action": {"trade_count": 2, "total_return_pct": -1.0}
            }
        }
        for _ in range(2)
    ]
    ready_model = type("Model", (), {"status": "ready"})()
    ready_threshold = type("Threshold", (), {"status": "ready"})()

    report = v4.build_transaction_acceptance_report(
        validation,
        validation_blocks=blocks,
        models=(ready_model, ready_model),
        threshold=ready_threshold,
        baseline_parity={"passed": True},
        v3_reference_parity={"passed": True},
        transaction_coverage={
            "scope_ready_pair_pct": 100.0,
            "disposition_coverage_pct": 100.0,
            "data_missing_prefix_count": 0,
            "scoreable_prefix_pct": 99.9255,
        },
        coverage_contract=v4.EXPLICIT_NO_ACTION_V5_COVERAGE,
    )

    assert report["passed"] is True
    assert "transaction_prefix_coverage_100pct" not in report["checks"]
    assert report["checks"]["minimum_95pct_scoreable_prefixes"] is True
