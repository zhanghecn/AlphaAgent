from __future__ import annotations

from datetime import date, datetime

from alphaagent.server.services.limit_up import preboard_decision_service as service
from alphaagent.server.services.limit_up.first_board_quality import PreboardPools
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    PreboardExecutionMode,
    PreboardPolicyThresholds,
)


DECISION_AT = datetime.fromisoformat("2026-07-21T10:05:00+08:00")


class _MinuteBuffer:
    def __init__(self) -> None:
        self.quality_rows: list[dict[str, object]] = []

    def ingest_quality_pool(self, _decision_at, rows) -> None:
        self.quality_rows = [dict(row) for row in rows]

    def completed_quality_pool_snapshots(self, _decision_at):
        return [
            {
                "captured_at": "2026-07-21T10:04:00+08:00",
                "candidates": self.quality_rows,
            },
            {
                "captured_at": "2026-07-21T10:05:00+08:00",
                "candidates": self.quality_rows,
            },
        ]

    def completed_bars(self, _symbol, _decision_at):
        return []

    def source_quality(self, _symbol, _decision_at):
        return "insufficient_live_prefix"


def test_live_service_scores_trace_capture_without_old_lanes(monkeypatch) -> None:
    candidate = {
        "vt_symbol": "600001.SSE",
        "name": "板前样本",
        "change_pct": 8.0,
        "last_price": 10.8,
        "limit_price": 11.0,
        "quality_gate_passed": True,
        "board_lane": "first_board",
    }
    calls: list[dict[str, object]] = []
    buffer = _MinuteBuffer()
    monkeypatch.setattr(service, "_live_adapter_rows", lambda _snapshot: [candidate])
    monkeypatch.setattr(
        service,
        "build_preboard_pools",
        lambda *_args, **_kwargs: PreboardPools(
            adapter_input_count=1,
            capture_pool=(candidate,),
            eligible_first_board_pool=(candidate,),
            quality_pool=(candidate,),
            rejection_counts={},
        ),
    )

    def project(row):
        calls.append(dict(row))
        return {
            "feature_contract_version": PREBOARD_DECISION_VERSION,
            "feature_status": "scoreable",
            "feature_fingerprint": "sha256:" + "a" * 64,
            "feature_values": {},
        }

    monkeypatch.setattr(service, "project_live_decision_features", project)
    monkeypatch.setattr(
        service,
        "evaluate_preboard_decisions",
        lambda rows, **_kwargs: [
            {
                **dict(row),
                "decision_state": "observe",
                "probability_status": "model_unavailable",
                "execution_mode": "research_only",
                "formal_strategy_changed": False,
            }
            for row in rows
        ],
    )

    result = service.score_live_preboard_snapshot(
        {
            "captured_at": DECISION_AT.isoformat(),
            "trace_capture_candidates": [candidate],
            "early_radar_recommendations": {"market_gate": {"passed": True}},
        },
        model_bundle=None,
        thresholds=None,
        execution_mode=PreboardExecutionMode.RESEARCH_ONLY,
        minute_buffer=buffer,
    )

    assert len(calls) == 1
    assert calls[0]["vt_symbol"] == "600001.SSE"
    assert calls[0]["quality_pool_snapshots"][-1]["candidates"] == [candidate]
    assert result["decision_version"] == PREBOARD_DECISION_VERSION
    assert result["pool_counts"] == {
        "adapter_input": 1,
        "capture": 1,
        "eligible": 1,
        "quality": 1,
    }
    assert [row["vt_symbol"] for row in result["feature_rows"]] == ["600001.SSE"]
    assert result["action_saved"] == 0
    assert result["formal_strategy_changed"] is False


def test_invalid_capture_time_fails_explicitly() -> None:
    try:
        service.score_live_preboard_snapshot(
            {"captured_at": "not-a-datetime"},
            model_bundle=None,
            thresholds=None,
            execution_mode=PreboardExecutionMode.RESEARCH_ONLY,
            minute_buffer=_MinuteBuffer(),
        )
    except ValueError as exc:
        assert str(exc) == "captured_at must be an ISO datetime"
    else:
        raise AssertionError("invalid captured_at was accepted")


def test_active_rejected_runtime_keeps_probabilities_research_only(
    monkeypatch,
) -> None:
    bundle = object()
    monkeypatch.setattr(
        service.preboard_decision_repository,
        "load_active_decision_runtime",
        lambda: {
            "model_bundle": bundle,
            "thresholds": None,
            "execution_mode": PreboardExecutionMode.RESEARCH_ONLY,
            "probability_qualification_status": "ready",
            "historical_promotion_status": "historical_rejected",
            "model_fingerprint": "sha256:" + "b" * 64,
            "feature_fingerprint": "sha256:" + "c" * 64,
        },
    )
    captured: dict[str, object] = {}

    def score(_snapshot, **kwargs):
        captured.update(kwargs)
        return {
            "status": "ready",
            "probability_status": "ready",
            "preboard_candidates": [
                {
                    "vt_symbol": "600001.SSE",
                    "decision_state": "observe",
                    "execution_mode": "research_only",
                    "touch_probability_3m": 0.71,
                }
            ],
            "action_saved": 0,
            "formal_strategy_changed": False,
        }

    monkeypatch.setattr(service, "score_live_preboard_snapshot", score)

    result = service.score_active_live_preboard_snapshot(
        {"captured_at": DECISION_AT.isoformat()},
        minute_buffer=_MinuteBuffer(),
    )

    assert captured["model_bundle"] is bundle
    assert captured["thresholds"] is None
    assert captured["execution_mode"] is PreboardExecutionMode.RESEARCH_ONLY
    assert captured["historical_promotion_status"] == "historical_rejected"
    assert result["probability_status"] == "ready"
    assert result["historical_promotion_status"] == "historical_rejected"
    assert result["preboard_candidates"][0]["touch_probability_3m"] == 0.71
    assert result["action_saved"] == 0
    assert result["formal_strategy_changed"] is False


def test_active_live_scoring_failure_never_emits_candidates_or_actions(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service,
        "score_active_live_preboard_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("store down")),
    )

    result = service.score_active_live_preboard_snapshot_safely(
        {"captured_at": DECISION_AT.isoformat()},
        minute_buffer=_MinuteBuffer(),
    )

    assert result["status"] == "error"
    assert result["preboard_candidates"] == []
    assert result["action_saved"] == 0
    assert result["formal_strategy_changed"] is False


def test_shadow_action_uses_saved_slots_and_persists_only_the_new_decision(
    monkeypatch,
) -> None:
    candidate = {
        "vt_symbol": "600001.SSE",
        "name": "板前样本",
        "change_pct": 8.0,
        "last_price": 10.8,
        "limit_price": 11.0,
        "quality_gate_passed": True,
        "board_lane": "first_board",
    }
    thresholds = PreboardPolicyThresholds(
        minimum_touch_probability_3m=0.6,
        minimum_eventual_touch_probability=0.7,
        calibrated_dates=(date(2026, 7, 20),),
        fingerprint="sha256:" + "b" * 64,
    )
    monkeypatch.setattr(service, "_live_adapter_rows", lambda _snapshot: [candidate])
    monkeypatch.setattr(
        service,
        "build_preboard_pools",
        lambda *_args, **_kwargs: PreboardPools(
            adapter_input_count=1,
            capture_pool=(candidate,),
            eligible_first_board_pool=(candidate,),
            quality_pool=(candidate,),
            rejection_counts={},
        ),
    )
    monkeypatch.setattr(
        service,
        "project_live_decision_features",
        lambda _row: {"feature_status": "scoreable"},
    )
    prior = [{"vt_symbol": "600009.SSE", "daily_slot": 1}]
    monkeypatch.setattr(
        service.preboard_decision_repository,
        "load_decision_actions",
        lambda **_kwargs: prior,
    )
    evaluation_calls: list[object] = []

    def evaluate(rows, **kwargs):
        evaluation_calls.append(kwargs["prior_actions"])
        return [
            {
                **dict(rows[0]),
                "decision_state": "actionable",
                "execution_mode": "shadow",
                "formal_strategy_changed": False,
            }
        ]

    monkeypatch.setattr(service, "evaluate_preboard_decisions", evaluate)
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(
        service.preboard_decision_repository,
        "save_decision_actions",
        lambda rows, **_kwargs: saved.extend(dict(row) for row in rows) or 1,
    )

    result = service.score_live_preboard_snapshot(
        {
            "captured_at": DECISION_AT.isoformat(),
            "trace_capture_candidates": [candidate],
            "early_radar_recommendations": {"market_gate": {"passed": True}},
        },
        model_bundle=object(),
        thresholds=thresholds,
        execution_mode=PreboardExecutionMode.SHADOW,
        minute_buffer=_MinuteBuffer(),
    )

    assert evaluation_calls == [prior]
    assert [row["vt_symbol"] for row in saved] == ["600001.SSE"]
    assert result["action_saved"] == 1
    assert result["formal_strategy_changed"] is False


def test_day_freeze_does_not_reconstruct_missing_intraday_decisions(
    monkeypatch,
) -> None:
    trade_date = date(2026, 7, 21)
    observation = {
        "frame_id": 10,
        "vt_symbol": "600001.SSE",
        "board_lane": "first_board",
        "capture_state": "near_limit",
        "formal_action": "pass",
        "change_pct": 8.0,
        "last_price": 10.8,
        "limit_price": 11.0,
    }
    saved: dict[str, object] = {}
    monkeypatch.setattr(
        service,
        "settle_decision_actions",
        lambda **_kwargs: {"action_count": 0, "stages_closed": 0},
    )
    monkeypatch.setattr(service.radar_observation_repository, "load_frames", lambda *_: [{}])
    monkeypatch.setattr(
        service.radar_observation_repository,
        "load_observations",
        lambda *_: [observation],
    )
    monkeypatch.setattr(
        service.preboard_decision_repository,
        "load_decision_feature_rows",
        lambda _dates: [],
    )
    monkeypatch.setattr(
        service,
        "_audit_label_scope",
        lambda *_args: {"frame_count": 1, "reason_codes": (), "metrics": {}},
    )
    monkeypatch.setattr(
        service.preboard_decision_repository,
        "label_decision_feature_rows",
        lambda *_args: 0,
    )

    def save_scope(_date, **kwargs):
        saved.update(kwargs)
        return {"status": "frozen"}

    monkeypatch.setattr(
        service.preboard_decision_repository,
        "save_decision_day_scope",
        save_scope,
    )

    result = service.freeze_and_settle(
        as_of=datetime.fromisoformat("2026-07-21T16:00:00+08:00"),
        trade_date=trade_date,
    )

    assert result["status"] == "incomplete_scope"
    assert result["reason_codes"] == ["missing_live_decision_rows"]
    assert saved["status"] == "incomplete"
    assert saved["feature_rows"] == []


def test_complete_day_labels_the_actual_saved_shared_payload(monkeypatch) -> None:
    trade_date = date(2026, 7, 21)
    feature_row = {
        "decision_version": PREBOARD_DECISION_VERSION,
        "frame_id": 10,
        "vt_symbol": "600001.SSE",
        "decision_at": datetime.fromisoformat("2026-07-21T10:05:00+08:00"),
        "feature_status": "scoreable",
        "_decision_payload_present": True,
    }
    observations = [
        {
            "frame_id": 11,
            "vt_symbol": "600001.SSE",
            "board_lane": "first_board",
            "captured_at": datetime.fromisoformat("2026-07-21T10:07:00+08:00"),
            "formal_action": "buy_now",
        }
    ]
    persisted: dict[str, object] = {}
    monkeypatch.setattr(
        service,
        "settle_decision_actions",
        lambda **_kwargs: {"action_count": 0, "stages_closed": 0},
    )
    monkeypatch.setattr(service.radar_observation_repository, "load_frames", lambda *_: [{}])
    monkeypatch.setattr(
        service.radar_observation_repository,
        "load_observations",
        lambda *_: observations,
    )
    monkeypatch.setattr(
        service.preboard_decision_repository,
        "load_decision_feature_rows",
        lambda _dates: [feature_row],
    )
    monkeypatch.setattr(
        service,
        "_audit_label_scope",
        lambda *_args: {"frame_count": 1, "reason_codes": (), "metrics": {}},
    )

    def label_rows(_date, labels):
        persisted["labels"] = labels
        return 1

    monkeypatch.setattr(
        service.preboard_decision_repository,
        "label_decision_feature_rows",
        label_rows,
    )
    monkeypatch.setattr(
        service.preboard_decision_repository,
        "save_decision_day_scope",
        lambda _date, **kwargs: persisted.update({"scope": kwargs})
        or {"status": "frozen"},
    )

    result = service.freeze_and_settle(
        as_of=datetime.fromisoformat("2026-07-21T16:00:00+08:00"),
        trade_date=trade_date,
    )

    assert result["status"] == "complete"
    assert persisted["labels"][(10, "600001.SSE")]["formal_touch_within_3m"] is True
    assert persisted["scope"]["feature_rows"][0]["label_status"] == "known"
    assert "_decision_payload_present" not in persisted["scope"]["feature_rows"][0]
