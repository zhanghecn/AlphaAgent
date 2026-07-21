from __future__ import annotations

import inspect
from datetime import date

from alphaagent.server.services.limit_up import preboard_event_risk_study as study
from alphaagent.server.services.limit_up import preboard_transaction_trigger_study as v4


def test_v7_entrypoint_injects_event_builder_without_changing_v4_defaults(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def evaluate(**kwargs):
        captured.update(kwargs)
        return {"status": "sentinel"}

    monkeypatch.setattr(v4, "_evaluate_preboard_transaction_trigger", evaluate)

    result = study.evaluate_preboard_event_risk(session_count=89)

    assert result == {
        "status": "sentinel",
        "report_title": "首板事件竞争风险 v7 研究",
    }
    assert captured == {
        "session_count": 89,
        "study_version": study.STUDY_VERSION,
        "coverage_contract": v4.EXPLICIT_NO_ACTION_V5_COVERAGE,
        "candidate_key": "v7",
        "candidate_analysis_builder": study.build_event_risk_analysis,
        "candidate_confirmation_minutes": 1,
        "candidate_action_model_key": "event_policy",
        "candidate_label": "v7事件竞争风险",
        "historical_validation_kind": "viewed_development_counterexample",
    }


def test_shared_transaction_runner_accepts_v7_candidate_key(monkeypatch) -> None:
    monkeypatch.setattr(
        v4.preboard_transaction_data,
        "resolve_shared_transaction_pairs",
        lambda **kwargs: ([], {"status": "empty"}),
    )

    report = v4._evaluate_preboard_transaction_trigger(
        session_count=89,
        study_version=study.STUDY_VERSION,
        coverage_contract=v4.EXPLICIT_NO_ACTION_V5_COVERAGE,
        candidate_key="v7",
    )

    assert report["status"] == "blocked_by_pair_manifest"


def test_event_features_are_frozen_before_future_targets_are_attached(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        study,
        "enrich_same_minute_competition",
        lambda rows: [dict(row) for row in rows],
    )

    def enrich(rows):
        calls.append("features")
        assert all(study.TOUCH_TARGET_FIELD not in row for row in rows)
        return [{**dict(row), "event_feature_cutoff": row["signal_time"]} for row in rows]

    def attach(rows, formal_orders):
        calls.append("targets")
        assert all("event_feature_cutoff" in row for row in rows)
        return [{**dict(row), study.TOUCH_TARGET_FIELD: True} for row in rows]

    monkeypatch.setattr(study, "enrich_event_risk_features", enrich)
    monkeypatch.setattr(study, "attach_competing_risk_targets", attach)

    rows = study.build_event_feature_rows(
        [{"vt_symbol": "600001.SSE", "signal_time": "10:00:00"}],
        (),
    )

    assert calls == ["features", "targets"]
    assert rows[0][study.TOUCH_TARGET_FIELD] is True


def test_oracle_is_structurally_excluded_from_v7_acceptance_contract() -> None:
    parameters = inspect.signature(study.build_event_acceptance_report).parameters

    assert "oracle" not in parameters
    assert "oracle_ceiling" not in parameters


def test_event_order_preserves_entry_contract_and_event_evidence() -> None:
    order = study._event_order(
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
            study.EVENT_MARKET_SCORE_FIELD: 0.8,
            study.EVENT_RANK_SCORE_FIELD: 1.25,
            "event_active_candidate_count": 3,
            "event_feature_version": study.EVENT_FEATURE_VERSION,
            "event_feature_cutoff": "2026-07-16T10:00:00",
            "rank_score": 75.0,
        },
        conservative_entry=False,
    )

    assert order is not None
    assert order["algorithm"] == "formal_touch_event_risk_v7"
    assert order["confirmation_minutes"] == 1
    assert order[study.EVENT_MARKET_SCORE_FIELD] == 0.8
    assert order[study.EVENT_RANK_SCORE_FIELD] == 1.25
    assert order["event_active_candidate_count"] == 3
    assert order["event_feature_version"] == study.EVENT_FEATURE_VERSION
    assert order["event_feature_cutoff"] == "2026-07-16T10:00:00"


def test_event_phase_accounts_keeps_v7_first_board_bucket(monkeypatch) -> None:
    relay = {"lane": "two_to_three", "algorithm": "relay"}
    early = {"lane": "first_board", "algorithm": "formal_touch_event_risk_v7"}
    monkeypatch.setattr(study.legacy, "_orders_on_dates", lambda rows, dates: list(rows))
    monkeypatch.setattr(
        study.legacy,
        "_account_metrics",
        lambda rows, bars, trade_dates, **kwargs: {"order_count": len(rows)},
    )

    accounts = study._event_phase_accounts(
        formal_orders=(relay,),
        action_orders=(relay, early),
        conservative_orders=(relay, early),
        bars=(),
        trade_dates=(),
        allowed_dates={date(2026, 7, 16)},
    )

    assert accounts["early_first_board_only"]["order_count"] == 1
    assert accounts["joint_action"]["order_count"] == 2


def test_v7_renderer_states_that_historical_context_snapshots_are_excluded() -> None:
    markdown = study.render_preboard_event_risk_markdown(
        {
            "study_version": study.STUDY_VERSION,
            "status": "ready_historical_rejected",
            "decision": "historical_rejected_no_live_promotion",
            "candidate_key": "v7",
            "candidate_label": "v7事件竞争风险",
            "report_title": "首板事件竞争风险 v7 研究",
            "transaction_coverage": {},
            "v3": {},
            "v7": {
                "models": {},
                "threshold_selection": {
                    "status": "calibration_precision_gate_failed",
                    "threshold": None,
                    "minimum_selection_count": 10,
                    "minimum_precision": 0.7,
                    "metrics_by_threshold": [
                        {
                            "threshold": 0.25,
                            "selection_count": 10,
                            "touch_true_positive_count": 4,
                            "touch_precision": 0.4,
                            "reachable_recall": 0.2,
                        }
                    ],
                },
                "phases": {
                    "validation": {
                        "accounts": {
                            "early_first_board_only": {
                                "trade_count": 0,
                                "total_return_pct": 0.0,
                            },
                            "joint_action": {
                                "trade_count": 3,
                                "total_return_pct": 9.27,
                            },
                        }
                    }
                },
                "ranking_quality": {},
            },
            "acceptance": {"passed": False, "checks": {}},
            "point_in_time_context_coverage": {
                "concept_snapshot_trade_days": 4,
                "sector_fund_flow_snapshot_trade_days": 6,
                "radar_observation_trade_days": 2,
                "historical_model_input": False,
            },
        }
    )

    assert markdown.startswith("# 首板事件竞争风险 v7 研究")
    assert "不得进入 v7 历史模型" in markdown
    assert "概念快照 4 日" in markdown
    assert "`4/10=40.00%`" in markdown
    assert "来自未改动二进三" in markdown
