from __future__ import annotations

import inspect
from datetime import date

from alphaagent.server.services.limit_up import preboard_transaction_touch_study as study
from alphaagent.server.services.limit_up import preboard_transaction_trigger_study as v4


def test_v6_entrypoint_injects_touch_builder_without_changing_v4_defaults(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def evaluate(**kwargs):
        captured.update(kwargs)
        return {"status": "sentinel"}

    monkeypatch.setattr(v4, "_evaluate_preboard_transaction_trigger", evaluate)

    result = study.evaluate_preboard_transaction_touch(session_count=89)

    assert result == {"status": "sentinel"}
    assert captured == {
        "session_count": 89,
        "study_version": study.STUDY_VERSION,
        "coverage_contract": v4.EXPLICIT_NO_ACTION_V5_COVERAGE,
        "candidate_key": "v6",
        "candidate_analysis_builder": study.build_transaction_touch_analysis,
        "candidate_confirmation_minutes": 1,
        "candidate_action_model_key": "action_touch_3m",
        "candidate_label": "v6触板时序模型",
        "historical_validation_kind": "viewed_development_counterexample",
    }


def test_v6_entrypoint_renames_incremental_attribution_and_adds_live_limit(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        v4,
        "_evaluate_preboard_transaction_trigger",
        lambda **kwargs: {
            "candidate_key": "v6",
            "incremental_attribution": {
                "v4_signal_pair_count": 3,
                "categories": {"v4_new_false_positive": {"pair_count": 2}},
            },
            "limitations": [],
        },
    )

    report = study.evaluate_preboard_transaction_touch(session_count=89)

    assert report["incremental_attribution"]["v6_signal_pair_count"] == 3
    assert "v6_new_false_positive" in report["incremental_attribution"]["categories"]
    assert "当前实时推荐链路尚未接入" in report["limitations"][-1]


def test_oracle_is_structurally_excluded_from_acceptance_contract() -> None:
    parameters = inspect.signature(study.build_touch_acceptance_report).parameters

    assert "oracle" not in parameters
    assert "oracle_ceiling" not in parameters


def test_touch_order_preserves_entry_contract_but_uses_one_minute_confirmation() -> None:
    order = study._touch_order(
        {
            "vt_symbol": "600001.SSE",
            "signal_date": "2026-07-16",
            "signal_time": "10:00:00",
            "signal_at": "2026-07-16T10:00:00",
            "entry_time": "10:01:00",
            "entry_price": 9.8,
            "signal_price": 9.7,
            "limit_price": 10.0,
            "fillable": True,
            "result_date": "2026-07-17",
            "result_close": 10.2,
            "transaction_touch_3m_probability": 0.8,
            "rank_score": 75.0,
        },
        conservative_entry=False,
    )

    assert order is not None
    assert order["algorithm"] == "formal_touch_3m_timing_v6"
    assert order["confirmation_minutes"] == 1
    assert order["transaction_touch_3m_probability"] == 0.8


def test_touch_score_alias_supports_replay_and_attribution() -> None:
    row = study._alias_touch_score(
        {"transaction_touch_3m_probability": 0.73}
    )

    assert row[study.JOINT_ACTION_SCORE_FIELD] == 0.73
    assert row[study.LEGACY_ACTION_SCORE_FIELD] == 0.73


def test_touch_identity_reachability_uses_one_scoreable_minute(monkeypatch) -> None:
    monkeypatch.setattr(study.legacy, "_identity_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        study,
        "transaction_trigger_feature_vector",
        lambda row: [1.0] if row.get("scoreable") is True else None,
    )
    rows = [
        {
            "vt_symbol": "600001.SSE",
            "signal_date": "2026-07-16",
            study.IDENTITY_TARGET_FIELD: True,
            "formal_touch_within_3m": True,
            "scoreable": True,
        },
        {
            "vt_symbol": "600002.SSE",
            "signal_date": "2026-07-16",
            study.IDENTITY_TARGET_FIELD: True,
            "formal_touch_within_3m": True,
            "scoreable": False,
        },
    ]

    report = study._touch_identity_report(
        rows,
        (),
        (rows[0],),
        allowed_dates={date(2026, 7, 16)},
    )

    assert report["reachable_formal_pair_count"] == 1
    assert report["reachable_horizon_pair_count"] == 1
    assert report["reachable_formal_recall_pct"] == 100.0
    assert report["reachable_confirmation_minutes"] == 1


def test_touch_phase_accounts_keeps_v6_early_first_board_bucket(monkeypatch) -> None:
    relay = {"lane": "two_to_three", "algorithm": "relay"}
    early = {"lane": "first_board", "algorithm": "formal_touch_3m_timing_v6"}
    monkeypatch.setattr(study.legacy, "_orders_on_dates", lambda rows, dates: list(rows))
    monkeypatch.setattr(
        study.legacy,
        "_account_metrics",
        lambda rows, bars, trade_dates, **kwargs: {"order_count": len(rows)},
    )

    accounts = study._touch_phase_accounts(
        formal_orders=(relay,),
        action_orders=(relay, early),
        conservative_orders=(relay, early),
        bars=(),
        trade_dates=(),
        allowed_dates={date(2026, 7, 16)},
    )

    assert accounts["early_first_board_only"]["order_count"] == 1
    assert accounts["joint_action"]["order_count"] == 2


def test_v6_renderer_marks_oracle_as_non_acceptance_evidence() -> None:
    markdown = study.render_preboard_transaction_touch_markdown(
        {
            "study_version": study.STUDY_VERSION,
            "status": "ready_historical_rejected",
            "decision": "historical_rejected_no_live_promotion",
            "candidate_key": "v6",
            "candidate_label": "v6逐笔模型",
            "report_title": "首板逐笔触板时序 v6 研究",
            "transaction_coverage": {},
            "v3": {},
            "v6": {
                "oracle_ceiling": {
                    "original_account_pair_count": 21,
                    "reachable_prefix_pair_count": 16,
                    "matched_original_pair_count": 15,
                    "reachable_original_recall_pct": 76.1905,
                }
            },
            "acceptance": {"passed": False, "checks": {}},
        }
    )

    assert markdown.startswith("# 首板逐笔触板时序 v6 研究")
    assert "仅作可达上界，不进入模型、阈值或验收" in markdown
    assert "\n\n## Same-account validation" in markdown
    assert "\n\n## Decision" in markdown
