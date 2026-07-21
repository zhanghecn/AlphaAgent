from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from math import log
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.limit_up import radar_validation
from alphaagent.server.services.limit_up import preboard_point_trigger_study as study
from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CALIBRATION_DAY_COUNT,
    CONTRACT_VERSION,
    ELIGIBLE_AFTER,
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
    PointTriggerDayAudit,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_dataset import (
    point_trigger_input_fingerprint,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_model import (
    ACTION_FEATURE_FIELDS,
    ACTION_MODEL_PARAMETERS,
    ACTION_SCORE_FIELD,
    EVENT_MODEL_PARAMETERS,
    EVENT_SCORE_FIELD,
    IDENTITY_MODEL_PARAMETERS,
    IDENTITY_SCORE_FIELD,
    score_frozen_point_top1,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_study import (
    PointTriggerArchiveConflict,
    archive_point_trigger_forward_report,
    build_point_trigger_accounts,
    build_point_trigger_forward_report,
    freeze_point_trigger_cohorts,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_repository import (
    point_trigger_action_decision_fingerprint,
    point_trigger_day_cohort_fingerprint,
    point_trigger_model_record_fingerprint,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_settlement import (
    build_point_trigger_settlement_evidence,
    point_trigger_settlement_evidence_fingerprint,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
RUNTIME_FINGERPRINT = "sha256:" + "d" * 64
FIT_DATES = tuple(date(2026, 7, 21) + timedelta(days=index) for index in range(40))
CALIBRATION_DATES = tuple(
    FIT_DATES[-1] + timedelta(days=index + 1) for index in range(15)
)
MODEL_FROZEN_AT = datetime.combine(
    CALIBRATION_DATES[-1],
    time(21, 30),
    tzinfo=SHANGHAI,
)
VALIDATION_DATES = tuple(
    CALIBRATION_DATES[-1] + timedelta(days=index + 2) for index in range(60)
)


@lru_cache(maxsize=1)
def _test_model_artifact() -> dict[str, object]:
    import lightgbm as lgb
    import numpy as np

    event_matrix = np.asarray(
        [
            [0.0] * len(FRAME_FEATURE_FIELDS),
            [1.0] * len(FRAME_FEATURE_FIELDS),
        ]
    )
    event = lgb.train(
        {
            "objective": "binary",
            "verbosity": -1,
            "seed": 0,
            "num_leaves": 2,
            "min_data_in_leaf": 1,
        },
        lgb.Dataset(
            event_matrix,
            label=[0, 1],
            feature_name=list(FRAME_FEATURE_FIELDS),
        ),
        num_boost_round=1,
    )
    identity_fields = (*FRAME_FEATURE_FIELDS, *IDENTITY_FEATURE_FIELDS)
    identity_matrix = np.asarray(
        [
            [0.0] * len(identity_fields),
            [1.0] * len(identity_fields),
        ]
    )
    identity = lgb.train(
        {
            "objective": "lambdarank",
            "metric": "ndcg",
            "verbosity": -1,
            "seed": 0,
            "num_leaves": 2,
            "min_data_in_leaf": 1,
        },
        lgb.Dataset(
            identity_matrix,
            label=[1, 0],
            group=[2],
            feature_name=list(identity_fields),
        ),
        num_boost_round=1,
    )
    return {
        "format": "limit-up-preboard-point-trigger-artifact-v1",
        "event_booster_model_text": event.model_to_string(),
        "identity_booster_model_text": identity.model_to_string(),
        "action_scaler_mean_by_feature": {
            field: 0.0 for field in ACTION_FEATURE_FIELDS
        },
        "action_scaler_scale_by_feature": {
            field: 1.0 for field in ACTION_FEATURE_FIELDS
        },
        "action_coefficient_by_feature": {
            field: 0.0 for field in ACTION_FEATURE_FIELDS
        },
        "action_intercept": log(0.82 / 0.18),
    }


def _model(*, status: str = "active") -> dict[str, object]:
    model: dict[str, object] = {
        "model_fingerprint": "sha256:" + "a" * 64,
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "fit_trade_dates": list(FIT_DATES),
        "calibration_trade_dates": list(CALIBRATION_DATES),
        "validation_trade_dates": [],
        "event_model_params": EVENT_MODEL_PARAMETERS,
        "identity_model_params": IDENTITY_MODEL_PARAMETERS,
        "action_model_params": ACTION_MODEL_PARAMETERS,
        "frame_feature_fields": list(FRAME_FEATURE_FIELDS),
        "identity_feature_fields": list(IDENTITY_FEATURE_FIELDS),
        "action_feature_fields": list(ACTION_FEATURE_FIELDS),
        "training_input_fingerprint": "sha256:" + "b" * 64,
        "event_model_fingerprint": "sha256:event",
        "identity_model_fingerprint": "sha256:identity",
        "action_model_fingerprint": "sha256:action",
        "calibration_threshold": 0.70 if status == "active" else None,
        "calibration_metrics": {
            "status": "ready" if status == "active" else "rejected",
            "complete_day_count": CALIBRATION_DAY_COUNT,
        },
        "model_artifact": deepcopy(_test_model_artifact()),
        "frozen_at": MODEL_FROZEN_AT,
    }
    model["record_fingerprint"] = point_trigger_model_record_fingerprint(model)
    return model


def _scope(
    trade_date: date,
    index: int,
    *,
    eligible: bool = True,
    frozen_at: datetime | None = None,
    reachable_event_count: int = 1,
) -> dict[str, object]:
    formal_order = {
        "vt_symbol": f"{600000 + max(index, 1):06d}.SSE",
        "name": f"{600000 + max(index, 1):06d}.SSE",
        "lane": "first_board",
        "entry_date": trade_date.isoformat(),
        "signal_date": trade_date.isoformat(),
        "buy_time": "10:05:50",
        "entry_price": 11.0,
        "limit_price": 11.0,
        "rank_score": 100.0,
        "pool_rank": 1,
        "source_frame_id": max(index, 1),
        "source_captured_at": datetime.combine(
            trade_date,
            time(10, 5, 50),
            tzinfo=SHANGHAI,
        ).isoformat(),
        "source": "saved_live_formal_portfolio",
    }
    audit = PointTriggerDayAudit(
        contract_version=CONTRACT_VERSION,
        trade_date=trade_date,
        status="complete" if eligible else "incomplete",
        is_complete=eligible,
        eligible_for_model=eligible,
        reason_codes=() if eligible else ("test_incomplete",),
        frame_count=720,
        observation_count=20_000,
        metrics={
            "scan_interval_p90_seconds": 15.0,
            "formal_event_static_eligible_within_60s_count": (reachable_event_count),
            "reachable_formal_event_count": 1,
            "reachable_event_label_coverage_ratio": (
                1.0 / reachable_event_count if reachable_event_count else 1.0
            ),
        },
        capture_runtime_fingerprint=RUNTIME_FINGERPRINT,
        formal_baseline_order_projection_complete=True,
        formal_baseline_orders=(formal_order,),
    )
    rows = (
        [_feature_row(_action(trade_date, max(index, 1), winning=True))]
        if eligible
        else []
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "trade_date": trade_date,
        "status": "complete" if eligible else "incomplete",
        "is_complete": eligible,
        "eligible_for_model": eligible,
        "reason_codes": list(audit.reason_codes),
        "frame_count": audit.frame_count,
        "observation_count": audit.observation_count,
        "audit_metrics": dict(audit.metrics),
        "capture_runtime_fingerprint": RUNTIME_FINGERPRINT,
        "formal_baseline_order_projection_complete": True,
        "formal_baseline_order_count": 1,
        "formal_baseline_orders": [formal_order],
        "formal_baseline_orders_fingerprint": study._fingerprint([formal_order]),
        "input_fingerprint": (
            point_trigger_input_fingerprint(rows) if rows else "sha256:" + "0" * 64
        ),
        "feature_row_count": len(rows),
        "cohort_fingerprint": (
            point_trigger_day_cohort_fingerprint(audit, rows)
            if trade_date > ELIGIBLE_AFTER
            else "sha256:" + "0" * 64
        ),
        "frozen_at": frozen_at or MODEL_FROZEN_AT + timedelta(days=index + 1),
    }


def _validation_scopes(count: int = 60) -> list[dict[str, object]]:
    return [
        _scope(trade_date, index)
        for index, trade_date in enumerate(VALIDATION_DATES[:count], start=1)
    ]


def _action(
    trade_date: date,
    index: int,
    *,
    winning: bool,
    captured_second: int = 0,
) -> dict[str, object]:
    symbol = f"{600000 + index:06d}.SSE"
    captured_at = datetime.combine(
        trade_date,
        time(10, 5, captured_second),
        tzinfo=SHANGHAI,
    )
    fill_at = captured_at + timedelta(seconds=20)
    d1_close_price = 10.4 if winning else 10.0
    normal = radar_validation._execution_outcome(
        10.0,
        d1_close_price,
        limit_price=11.0,
        cost_multiplier=1.0,
    )
    stress = radar_validation._execution_outcome(
        10.0,
        d1_close_price,
        limit_price=11.0,
        cost_multiplier=2.0,
    )
    assert normal is not None and stress is not None
    action: dict[str, object] = {
        "model_fingerprint": _model()["model_fingerprint"],
        "contract_version": CONTRACT_VERSION,
        "trade_date": trade_date,
        "captured_at": captured_at,
        "daily_slot": 1,
        "frame_id": index,
        "vt_symbol": symbol,
        "quote_observed_at": captured_at,
        "last_price": 10.0,
        "action_probability": 0.82,
        "action_threshold": 0.70,
        "event_probability": 0.88,
        "identity_score": 1.25,
        "top1_margin": 0.30,
        "candidate_count": 1,
        "input_fingerprint": "sha256:" + f"{index:064x}"[-64:],
        "decision_payload": {
            "eligible_candidate_symbols": [symbol],
            "concurrent_formal_two_slot_symbols": [symbol],
            "concurrent_formal_two_slot_observed": True,
            "event_model_fingerprint": "sha256:event",
            "identity_model_fingerprint": "sha256:identity",
            "action_model_fingerprint": "sha256:action",
        },
        "actionable": False,
        "execution_effect": "none_research_only",
        "action_kind": "research_action",
        "fill_status": "filled",
        "fill_at": fill_at,
        "fill_price": 10.0,
        "fill_quote_observed_at": fill_at,
        "limit_price": 11.0,
        "formal_identity_status": "matched",
        "formal_identity_matched": True,
        "formal_event_at": captured_at + timedelta(seconds=50),
        "formal_identity_vt_symbol": symbol,
        "original_two_slot_symbols": [symbol],
        "original_two_slot_matched": True,
        "physical_touch_status": "touched",
        "physical_touch_at": captured_at + timedelta(seconds=50),
        "final_sealed": True,
        "d1_status": "closed",
        "d1_trade_date": trade_date + timedelta(days=1),
        "d1_close_price": d1_close_price,
        "gross_return_pct": round((d1_close_price / 10.0 - 1.0) * 100.0, 4),
        "net_return_pct": normal["net_return_pct"],
        "double_cost_net_return_pct": stress["net_return_pct"],
    }
    evidence = build_point_trigger_settlement_evidence(
        action,
        [
            {
                "id": index * 10 + offset,
                "trade_date": trade_date,
                "captured_at": captured_at + timedelta(seconds=seconds),
            }
            for offset, seconds in enumerate((20, 50, 60), start=1)
        ],
        [
            {
                "frame_id": index * 10 + 1,
                "captured_at": fill_at,
                "quote_observed_at": fill_at,
                "vt_symbol": symbol,
                "last_price": 10.0,
                "capture_state": "rising",
            },
            {
                "frame_id": index * 10 + 2,
                "captured_at": captured_at + timedelta(seconds=50),
                "quote_observed_at": captured_at + timedelta(seconds=50),
                "vt_symbol": symbol,
                "last_price": 11.0,
                "capture_state": "sealed",
            },
            {
                "frame_id": index * 10 + 3,
                "captured_at": captured_at + timedelta(seconds=60),
                "quote_observed_at": captured_at + timedelta(seconds=60),
                "vt_symbol": symbol,
                "last_price": 11.0,
                "capture_state": "sealed",
            },
        ],
    )
    action["settlement_evidence"] = evidence
    action["settlement_evidence_fingerprint"] = (
        point_trigger_settlement_evidence_fingerprint(evidence)
    )
    action["decision_fingerprint"] = point_trigger_action_decision_fingerprint(action)
    return action


def _feature_row(action: dict[str, object]) -> dict[str, object]:
    row: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "frame_id": action["frame_id"],
        "trade_date": action["trade_date"],
        "captured_at": action["captured_at"],
        "vt_symbol": action["vt_symbol"],
        "name": action["vt_symbol"],
        "last_price": action["last_price"],
        "limit_price": action["limit_price"],
        "quote_observed_at": action["quote_observed_at"],
        "action_frame_eligible": True,
        "action_previous_frame_gap_seconds": 15.0,
        "action_quote_coverage_ratio": 1.0,
        "action_market_timing_observed": True,
        "formal_two_slot_observed": True,
        "formal_two_slot_symbols": list(
            action["decision_payload"]["concurrent_formal_two_slot_symbols"]
        ),
        "frame_features": {field: 0.0 for field in FRAME_FEATURE_FIELDS},
        "identity_features": {field: 0.0 for field in IDENTITY_FEATURE_FIELDS},
        "formal_event_at": action["formal_event_at"],
        "formal_identity_vt_symbol": action["formal_identity_vt_symbol"],
        "formal_event_within_60s": True,
        "formal_identity_within_60s": True,
        "label_status": "known",
    }
    row["feature_fingerprint"] = point_trigger_input_fingerprint([row])
    return row


def _bars_for_actions(actions: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for action in actions:
        symbol = str(action["vt_symbol"])
        entry_date = action["trade_date"]
        d1_date = action["d1_trade_date"]
        close = float(action["d1_close_price"])
        rows.extend(
            [
                {
                    "vt_symbol": symbol,
                    "trade_date": entry_date,
                    "open_price": 10.0,
                    "high_price": 11.0,
                    "low_price": 10.0,
                    "close_price": 11.0,
                },
                {
                    "vt_symbol": symbol,
                    "trade_date": d1_date,
                    "open_price": close,
                    "high_price": close,
                    "low_price": close,
                    "close_price": close,
                },
            ]
        )
    return rows


def _formal_orders_for_actions(
    actions: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "vt_symbol": action["vt_symbol"],
            "name": action["vt_symbol"],
            "lane": "first_board",
            "entry_date": action["trade_date"],
            "signal_date": action["trade_date"],
            "result_date": action["d1_trade_date"],
            "buy_time": action["formal_event_at"].strftime("%H:%M:%S"),
            "entry_price": 10.0,
            "limit_price": 11.0,
            "rank_score": 100.0,
        }
        for action in actions
    ]


def _mature_inputs() -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    actions = [
        _action(trade_date, index, winning=index % 5 != 0)
        for index, trade_date in enumerate(VALIDATION_DATES, start=1)
    ]
    features = [_feature_row(action) for action in actions]
    scored_by_frame = {
        str(row["frame_id"]): row for row in score_frozen_point_top1(features, _model())
    }
    for action, feature in zip(actions, features, strict=True):
        scored = scored_by_frame[str(action["frame_id"])]
        action.update(
            {
                "event_probability": scored[EVENT_SCORE_FIELD],
                "identity_score": scored[IDENTITY_SCORE_FIELD],
                "action_probability": scored[ACTION_SCORE_FIELD],
                "top1_margin": scored["top1_margin"],
                "candidate_count": scored["candidate_count"],
                "input_fingerprint": point_trigger_input_fingerprint([feature]),
            }
        )
        action["decision_fingerprint"] = point_trigger_action_decision_fingerprint(
            action
        )
    return (
        actions,
        features,
        _formal_orders_for_actions(actions),
        _bars_for_actions(actions),
    )


def test_first_40_15_60_cohort_identity_cannot_drift_after_freeze() -> None:
    scopes = _validation_scopes()
    initial = freeze_point_trigger_cohorts(scopes, _model())
    backfilled_earlier = _scope(
        CALIBRATION_DATES[-1] + timedelta(days=1),
        10_000,
        frozen_at=MODEL_FROZEN_AT + timedelta(days=100),
    )
    changed_excluded = _scope(
        date(2026, 7, 20),
        20_000,
        eligible=False,
        frozen_at=MODEL_FROZEN_AT + timedelta(days=101),
    )
    sixty_first = _scope(
        VALIDATION_DATES[-1] + timedelta(days=1),
        30_000,
        frozen_at=MODEL_FROZEN_AT + timedelta(days=102),
    )

    repeated = freeze_point_trigger_cohorts(
        [changed_excluded, backfilled_earlier, sixty_first, *scopes],
        _model(),
    )

    assert initial["fit_trade_dates"] == list(FIT_DATES)
    assert initial["calibration_trade_dates"] == list(CALIBRATION_DATES)
    assert initial["validation_trade_dates"] == list(VALIDATION_DATES)
    assert initial["validation_cohort_id"] == repeated["validation_cohort_id"]
    assert repeated["validation_trade_dates"] == list(VALIDATION_DATES)


def test_mature_report_does_not_drift_after_sixty_first_scope() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    model_scopes = [
        _scope(trade_date, index)
        for index, trade_date in enumerate(
            [*FIT_DATES, *CALIBRATION_DATES],
            start=1,
        )
    ]
    validation_scopes = _validation_scopes()
    common = {
        "model": _model(),
        "actions": actions,
        "feature_rows": features,
        "formal_orders": formal_orders,
        "relay_orders": [],
        "daily_bars": bars,
        "trade_dates": [
            *VALIDATION_DATES,
            VALIDATION_DATES[-1] + timedelta(days=1),
        ],
    }
    initial = build_point_trigger_forward_report(
        scopes=[*model_scopes, *validation_scopes],
        **common,
    )
    sixty_first = _scope(
        VALIDATION_DATES[-1] + timedelta(days=2),
        30_000,
        frozen_at=MODEL_FROZEN_AT + timedelta(days=200),
    )
    repeated = build_point_trigger_forward_report(
        scopes=[*model_scopes, *validation_scopes, sixty_first],
        **common,
    )

    assert initial == repeated
    assert initial["phase"]["validation_available_day_count"] == 60
    assert initial["phase"]["eligible_complete_day_count"] == 115


def test_mature_report_uses_frozen_scope_formal_orders_by_default() -> None:
    actions, features, _formal_orders, bars = _mature_inputs()

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    assert report["status"] == "forward_reliable_candidate_for_live_review"
    assert report["validation_metrics"]["original_account_identity_match_count"] == 60


def test_frozen_formal_account_requires_the_next_session_official_bar() -> None:
    trade_date = VALIDATION_DATES[0]
    next_date = VALIDATION_DATES[1]
    formal_order = _scope(trade_date, 1)["formal_baseline_orders"][0]

    accounts = study.build_point_trigger_accounts(
        [],
        [],
        [
            {
                "vt_symbol": formal_order["vt_symbol"],
                "trade_date": trade_date,
                "open_price": 11.0,
                "high_price": 11.0,
                "low_price": 11.0,
                "close_price": 11.0,
            }
        ],
        [trade_date, next_date],
        formal_orders=[formal_order],
        validation_dates=[trade_date],
    )

    audit = accounts["original_formal_market_data_audit"]
    assert audit["complete"] is False
    assert audit["missing_early_bars"] == [
        {"vt_symbol": formal_order["vt_symbol"], "trade_date": next_date}
    ]


def test_formal_input_loader_discovers_next_reliable_session(monkeypatch) -> None:
    from alphaagent.server.services.limit_up import (
        history_repository,
        preboard_momentum_data,
    )

    trade_date = date(2026, 7, 21)
    next_date = date(2026, 7, 22)
    scope = _scope(trade_date, 1)
    formal_order = scope["formal_baseline_orders"][0]
    bar_calls: list[tuple[list[str], date, date]] = []

    monkeypatch.setattr(
        preboard_momentum_data,
        "load_reliable_trade_dates",
        lambda start, end: [trade_date, next_date],
    )
    monkeypatch.setattr(
        history_repository,
        "load_account_daily_bars",
        lambda symbols, start, end: (
            bar_calls.append((list(symbols), start, end))
            or [
                {
                    "vt_symbol": formal_order["vt_symbol"],
                    "trade_date": current,
                    "open_price": price,
                    "high_price": price,
                    "low_price": price,
                    "close_price": price,
                }
                for current, price in ((trade_date, 11.0), (next_date, 11.5))
            ]
        ),
    )

    formal, relays, bars, calendar = study._load_formal_account_inputs(
        [trade_date],
        [],
        [scope],
    )
    accounts = build_point_trigger_accounts(
        [],
        relays,
        bars,
        calendar,
        formal_orders=formal,
        validation_dates=[trade_date],
    )

    assert bar_calls == [([formal_order["vt_symbol"]], trade_date, next_date)]
    assert calendar == [trade_date, next_date]
    assert accounts["original_formal_market_data_audit"]["complete"] is True


def test_validation_scope_must_be_frozen_after_the_model() -> None:
    scopes = _validation_scopes()
    scopes[0]["frozen_at"] = MODEL_FROZEN_AT

    cohorts = freeze_point_trigger_cohorts(scopes, _model())

    assert cohorts["validation_complete_day_count"] == 59
    assert VALIDATION_DATES[0] not in cohorts["validation_trade_dates"]
    assert cohorts["validation_cohort_id"] is None


def test_duplicate_complete_scope_date_fails_closed() -> None:
    scopes = _validation_scopes()

    with pytest.raises(ValueError, match="duplicate complete scope date"):
        freeze_point_trigger_cohorts([scopes[0], *scopes], _model())


def test_shakedown_and_other_contract_scopes_never_enter_fit_cohort() -> None:
    shakedown = _scope(ELIGIBLE_AFTER, 1)
    other_contract = {
        **_scope(ELIGIBLE_AFTER + timedelta(days=1), 2),
        "contract_version": "other-contract",
    }
    valid = _scope(ELIGIBLE_AFTER + timedelta(days=2), 3)

    cohorts = freeze_point_trigger_cohorts(
        [shakedown, other_contract, valid],
        None,
    )

    assert cohorts["eligible_complete_day_count"] == 1
    assert cohorts["fit_trade_dates"] == [valid["trade_date"]]


def test_model_cohort_cannot_include_the_permanent_shakedown_day() -> None:
    model = _model()
    model["fit_trade_dates"] = [ELIGIBLE_AFTER, *FIT_DATES[1:]]

    with pytest.raises(ValueError, match="after eligible_after"):
        freeze_point_trigger_cohorts([], model)


def test_immature_validation_hides_every_performance_conclusion() -> None:
    actions, features, formal_orders, bars = _mature_inputs()

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(59),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=VALIDATION_DATES,
    )

    assert report["status"] == "forward_collecting"
    assert report["phase"]["validation_complete_day_count"] == 59
    assert report["validation_metrics"] is None
    assert report["accounts"] is None
    assert report["reliability_gates"] is None
    assert report["performance_visible"] is False


def test_changed_frozen_model_record_is_rejected_before_reporting() -> None:
    model = _model()
    model["calibration_threshold"] = 0.75

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=model,
    )

    assert report["status"] == "forward_rejected"
    assert report["performance_visible"] is False
    assert report["model_record_integrity_verified"] is False
    assert report["validation_metrics"] is None


def test_two_slot_accounts_preserve_arrival_order_and_reject_unknown_queue() -> None:
    trade_date = VALIDATION_DATES[0]
    first = _action(trade_date, 1, winning=True, captured_second=0)
    second = _action(trade_date, 2, winning=True, captured_second=10)
    queue_unknown = {
        **_action(trade_date, 3, winning=True, captured_second=20),
        "fill_status": "queue_unknown_without_l2",
        "fill_at": None,
        "fill_price": None,
        "d1_status": "not_filled",
        "d1_trade_date": None,
        "d1_close_price": None,
        "gross_return_pct": None,
        "net_return_pct": None,
        "double_cost_net_return_pct": None,
    }
    relay = {
        "vt_symbol": "600999.SSE",
        "name": "relay",
        "lane": "two_to_three",
        "entry_date": trade_date,
        "result_date": trade_date + timedelta(days=1),
        "buy_time": "10:00:00",
        "entry_price": 8.0,
        "limit_price": 8.8,
        "rank_score": 99.0,
    }
    bars = _bars_for_actions([first, second]) + [
        {
            "vt_symbol": "600999.SSE",
            "trade_date": trade_date,
            "open_price": 8.0,
            "high_price": 8.0,
            "low_price": 8.0,
            "close_price": 8.0,
        },
        {
            "vt_symbol": "600999.SSE",
            "trade_date": trade_date + timedelta(days=1),
            "open_price": 8.4,
            "high_price": 8.4,
            "low_price": 8.4,
            "close_price": 8.4,
        },
    ]

    accounts = build_point_trigger_accounts(
        [first, second, queue_unknown],
        [relay],
        bars,
        [trade_date, trade_date + timedelta(days=1)],
        formal_orders=[relay],
    )

    assert (
        accounts["early_first_board_normal"]["execution_summary"]["signal_count"] == 2
    )
    joint = accounts["joint_with_two_to_three_normal"]
    assert joint["execution_summary"]["signal_count"] == 3
    assert joint["execution_summary"]["filled_count"] == 2
    assert joint["execution_summary"]["skipped_reasons"] == {"position_limit": 1}
    assert {trade["lane"] for trade in joint["executed_trades"]} == {
        "first_board",
        "two_to_three",
    }
    assert (
        accounts["early_first_board_double_cost"]["execution_summary"]["total_fees"]
        > accounts["early_first_board_normal"]["execution_summary"]["total_fees"]
    )
    assert (
        accounts["original_formal_double_cost"]["execution_summary"]["total_fees"]
        > accounts["original_formal_normal"]["execution_summary"]["total_fees"]
    )
    rejection = accounts["queue_unknown_rejection"]
    assert rejection["queue_unknown_rejected_count"] == 1
    assert rejection["accepted_filled_action_count"] == 2
    assert rejection["account"]["execution_summary"]["signal_count"] == 2


def test_chronological_blocks_slice_one_continuous_account() -> None:
    first_block_date = VALIDATION_DATES[11]
    second_block_date = VALIDATION_DATES[12]
    first_block_actions = [
        _action(
            first_block_date,
            200 + offset,
            winning=True,
            captured_second=offset * 10,
        )
        for offset in range(2)
    ]
    second_block_actions = [
        _action(
            second_block_date,
            202 + offset,
            winning=False,
            captured_second=offset * 10,
        )
        for offset in range(2)
    ]
    actions = [*first_block_actions, *second_block_actions]

    accounts = build_point_trigger_accounts(
        actions,
        [],
        _bars_for_actions(actions),
        [*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
        validation_dates=VALIDATION_DATES,
    )

    account = accounts["early_first_board_normal"]
    blocks = accounts["early_first_board_chronological_blocks"]
    compounded = 1.0
    for block in blocks:
        compounded *= 1.0 + float(block["total_return_pct"]) / 100.0

    assert len(blocks) == 5
    assert blocks[0]["filled_count"] == 2
    assert blocks[1]["signal_count"] == 2
    assert blocks[1]["filled_count"] == 0
    assert blocks[1]["initial_equity"] == blocks[0]["final_equity"]
    assert blocks[-1]["final_equity"] == account["execution_summary"]["final_equity"]
    assert (compounded - 1.0) * 100.0 == pytest.approx(
        account["execution_summary"]["total_return_pct"],
        abs=0.0002,
    )


def test_joint_account_losses_fail_forward_reliability_gates() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    relays: list[dict[str, object]] = []
    for index, trade_date in enumerate(VALIDATION_DATES, start=1):
        symbol = f"{601000 + index:06d}.SSE"
        next_date = trade_date + timedelta(days=1)
        relays.append(
            {
                "vt_symbol": symbol,
                "name": symbol,
                "lane": "two_to_three",
                "entry_date": trade_date,
                "result_date": next_date,
                "buy_time": "09:30:00",
                "entry_price": 10.0,
                "limit_price": 11.0,
                "rank_score": 100.0,
            }
        )
        bars.extend(
            [
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": 10.0,
                    "high_price": 10.0,
                    "low_price": 10.0,
                    "close_price": 10.0,
                },
                {
                    "vt_symbol": symbol,
                    "trade_date": next_date,
                    "open_price": 9.01,
                    "high_price": 9.01,
                    "low_price": 9.01,
                    "close_price": 9.01,
                },
            ]
        )

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=relays,
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    metrics = report["validation_metrics"]
    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert metrics["early_account_total_return_pct"] > 0.0
    assert metrics["joint_account_total_return_pct"] < 0.0
    assert report["status"] == "forward_rejected"
    assert gates["positive_joint_two_slot_compound"]["passed"] is False
    assert gates["joint_two_slot_profit_factor"]["passed"] is False
    assert gates["joint_maximum_drawdown"]["passed"] is False


def test_joint_product_must_not_underperform_same_window_formal_baseline() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    for order in formal_orders:
        order["entry_price"] = 9.9

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    metrics = report["validation_metrics"]
    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert metrics["joint_account_total_return_pct"] > 0.0
    assert metrics["joint_vs_formal_win_rate_delta_pct"] < 0.0
    assert metrics["joint_vs_formal_total_return_delta_pct"] < 0.0
    assert metrics["joint_vs_formal_max_drawdown_delta_pct"] < 0.0
    assert metrics["joint_vs_formal_profit_factor_ratio"] is None
    assert metrics["joint_double_vs_formal_win_rate_delta_pct"] < 0.0
    assert metrics["joint_double_vs_formal_total_return_delta_pct"] < 0.0
    assert metrics["joint_double_vs_formal_max_drawdown_delta_pct"] < 0.0
    assert metrics["joint_double_vs_formal_profit_factor_ratio"] is None
    assert report["status"] == "forward_rejected"
    assert gates["joint_win_rate_vs_formal_baseline"]["passed"] is False
    assert gates["joint_compound_vs_formal_baseline"]["passed"] is False
    assert gates["joint_drawdown_vs_formal_baseline"]["passed"] is True
    assert gates["joint_profit_factor_vs_formal_baseline"]["passed"] is False
    assert gates["joint_double_win_rate_vs_formal_baseline"]["passed"] is False
    assert gates["joint_double_compound_vs_formal_baseline"]["passed"] is False
    assert gates["joint_double_drawdown_vs_formal_baseline"]["passed"] is True
    assert (
        gates["joint_double_profit_factor_vs_formal_baseline"]["passed"] is False
    )


def test_material_same_window_drawdown_degradation_fails_reliability() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )
    metrics = deepcopy(report["validation_metrics"])
    metrics["joint_vs_formal_max_drawdown_delta_pct"] = -1.0001
    metrics["joint_double_vs_formal_max_drawdown_delta_pct"] = -1.0001

    gates = {gate["name"]: gate for gate in study._reliability_gates(metrics)}

    assert gates["joint_drawdown_vs_formal_baseline"]["passed"] is False
    assert gates["joint_double_drawdown_vs_formal_baseline"]["passed"] is False


def test_all_forward_reliability_gates_can_pass_and_archive(
    monkeypatch,
    tmp_path,
) -> None:
    actions, features, formal_orders, bars = _mature_inputs()

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    assert report["status"] == "forward_reliable_candidate_for_live_review"
    assert (
        report["reliability_gate_version"]
        == "limit-up-preboard-point-trigger-reliability-v8"
    )
    assert report["performance_visible"] is True
    assert all(gate["passed"] is True for gate in report["reliability_gates"])
    assert report["validation_metrics"]["closed_action_count"] == 60
    assert report["validation_metrics"]["formal_identity_precision_pct"] == 100.0
    assert (
        report["validation_metrics"]["formal_identity_precision_wilson_lower_pct"]
        == 93.9828
    )
    assert (
        report["validation_metrics"]["original_account_identity_precision_pct"] == 100.0
    )
    assert report["validation_metrics"]["reachable_recall_pct"] == 100.0
    assert report["validation_metrics"]["expected_action_count"] == 60
    assert report["validation_metrics"]["complete_action_set_replay"] == 1
    assert report["validation_metrics"]["positive_block_count"] == 5
    assert report["validation_metrics"]["joint_vs_formal_win_rate_delta_pct"] == 0.0
    assert (
        report["validation_metrics"]["joint_vs_formal_total_return_delta_pct"]
        == 0.0
    )
    assert (
        report["validation_metrics"]["joint_vs_formal_max_drawdown_delta_pct"]
        == 0.0
    )
    assert (
        report["validation_metrics"]["joint_vs_formal_profit_factor_ratio"] == 1.0
    )
    assert (
        report["validation_metrics"]["joint_double_vs_formal_win_rate_delta_pct"]
        == 0.0
    )
    assert (
        report["validation_metrics"]["joint_double_vs_formal_total_return_delta_pct"]
        == 0.0
    )
    assert (
        report["validation_metrics"]["joint_double_vs_formal_max_drawdown_delta_pct"]
        == 0.0
    )
    assert (
        report["validation_metrics"][
            "joint_double_vs_formal_profit_factor_ratio"
        ]
        == 1.0
    )
    assert report["accounts"]["market_data_audit"]["complete"] is True
    authoritative = [report]
    monkeypatch.setattr(
        study,
        "load_point_trigger_forward_report",
        lambda: authoritative[0],
    )

    archived = archive_point_trigger_forward_report(report, tmp_path)

    json_path = tmp_path / "limit_up_preboard_point_trigger_v9_forward.json"
    markdown_path = tmp_path / "limit_up_preboard_point_trigger_v9_forward.md"
    assert archived["json_path"] == str(json_path)
    assert archived["markdown_path"] == str(markdown_path)
    assert (
        json.loads(json_path.read_text(encoding="utf-8"))["status"] == report["status"]
    )
    assert "forward_reliable_candidate_for_live_review" in markdown_path.read_text(
        encoding="utf-8"
    )
    assert archive_point_trigger_forward_report(report, tmp_path) == archived

    changed = deepcopy(report)
    changed["validation_metrics"]["average_net_return_pct"] = 9.9
    next(
        gate
        for gate in changed["reliability_gates"]
        if gate["name"] == "average_net_return"
    )["current"] = 9.9
    authoritative[0] = changed
    with pytest.raises(PointTriggerArchiveConflict):
        archive_point_trigger_forward_report(changed, tmp_path)


def test_archive_rejects_incomplete_or_forged_gate_set(monkeypatch, tmp_path) -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )
    report["reliability_gates"] = [
        {
            "name": "forged_gate",
            "current": 1,
            "requirement": "= 1",
            "passed": True,
        }
    ]
    monkeypatch.setattr(
        study,
        "load_point_trigger_forward_report",
        lambda: report,
    )

    with pytest.raises(ValueError, match="fully gated"):
        archive_point_trigger_forward_report(report, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_archive_rejects_duplicate_validation_dates(monkeypatch, tmp_path) -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )
    phase = report["phase"]
    phase["validation_trade_dates"][-1] = phase["validation_trade_dates"][-2]
    monkeypatch.setattr(
        study,
        "load_point_trigger_forward_report",
        lambda: report,
    )

    with pytest.raises(ValueError, match="60 unique chronological"):
        archive_point_trigger_forward_report(report, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_original_account_identity_comes_from_formal_cash_replay() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    rebuilt_orders = deepcopy(formal_orders)
    rebuilt_bars = deepcopy(bars)
    for index, (action, order) in enumerate(
        zip(actions, rebuilt_orders, strict=True),
        start=1,
    ):
        rebuilt_symbol = f"{601000 + index:06d}.SSE"
        order["vt_symbol"] = rebuilt_symbol
        order["name"] = rebuilt_symbol
        rebuilt_bars.extend(
            [
                {
                    "vt_symbol": rebuilt_symbol,
                    "trade_date": action["trade_date"],
                    "open_price": 10.0,
                    "high_price": 10.0,
                    "low_price": 10.0,
                    "close_price": 10.0,
                },
                {
                    "vt_symbol": rebuilt_symbol,
                    "trade_date": action["d1_trade_date"],
                    "open_price": 10.4,
                    "high_price": 10.4,
                    "low_price": 10.4,
                    "close_price": 10.4,
                },
            ]
        )

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=rebuilt_orders,
        relay_orders=[],
        daily_bars=rebuilt_bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    metrics = report["validation_metrics"]
    assert report["status"] == "forward_rejected"
    assert metrics["original_account_identity_coverage_count"] == 60
    assert metrics["original_account_identity_precision_pct"] == 0.0


def test_same_frame_portfolio_membership_cannot_override_formal_account_miss() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    missed_symbol = "603999.SSE"
    formal_orders[0] = {
        **formal_orders[0],
        "vt_symbol": missed_symbol,
        "name": missed_symbol,
    }
    bars.extend(
        [
            {
                "vt_symbol": missed_symbol,
                "trade_date": actions[0]["trade_date"],
                "open_price": 10.0,
                "high_price": 10.0,
                "low_price": 10.0,
                "close_price": 10.0,
            },
            {
                "vt_symbol": missed_symbol,
                "trade_date": actions[0]["d1_trade_date"],
                "open_price": 10.4,
                "high_price": 10.4,
                "low_price": 10.4,
                "close_price": 10.4,
            },
        ]
    )

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert report["status"] == "forward_reliable_candidate_for_live_review"
    assert metrics["original_account_identity_match_count"] == 59
    assert metrics["original_account_identity_precision_pct"] < 100.0
    assert gates["original_account_identity_precision"]["passed"] is True


def test_reachable_recall_uses_frozen_scope_funnel_denominator() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    scopes = _validation_scopes()
    scopes[0] = _scope(
        VALIDATION_DATES[0],
        1,
        reachable_event_count=2,
    )

    report = build_point_trigger_forward_report(
        scopes=scopes,
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert report["status"] == "forward_rejected"
    assert metrics["scope_reachable_formal_event_count"] == 61
    assert metrics["labeled_reachable_formal_event_count"] == 60
    assert metrics["reachable_recall_pct"] == pytest.approx(98.3607, abs=1e-4)
    assert gates["reachable_event_label_reconciliation"]["passed"] is False


def test_changed_action_decision_fingerprint_fails_integrity_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["action_probability"] = 0.99

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert report["status"] == "forward_rejected"
    assert metrics["action_decision_integrity_count"] == 59
    assert gates["action_decision_integrity"]["passed"] is False


def test_changed_stored_d1_return_fails_official_outcome_integrity_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["net_return_pct"] = 99.0

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert report["status"] == "forward_rejected"
    assert metrics["official_d1_outcome_integrity_count"] == 59
    assert gates["official_d1_outcome_integrity"]["passed"] is False


def test_self_consistent_forged_fill_fails_delayed_fill_integrity_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    action = actions[0]
    action["fill_price"] = 9.9
    close_price = float(action["d1_close_price"])
    normal = radar_validation._execution_outcome(
        9.9,
        close_price,
        limit_price=11.0,
        cost_multiplier=1.0,
    )
    stress = radar_validation._execution_outcome(
        9.9,
        close_price,
        limit_price=11.0,
        cost_multiplier=2.0,
    )
    assert normal is not None and stress is not None
    action["gross_return_pct"] = round((close_price / 9.9 - 1.0) * 100.0, 4)
    action["net_return_pct"] = normal["net_return_pct"]
    action["double_cost_net_return_pct"] = stress["net_return_pct"]

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert report["status"] == "forward_rejected"
    assert report["validation_metrics"]["delayed_fill_integrity_count"] == 59
    assert gates["delayed_fill_integrity"]["passed"] is False


def test_forged_formal_identity_fails_frozen_label_integrity_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["formal_identity_status"] = "missed"
    actions[0]["formal_identity_matched"] = False

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert report["status"] == "forward_rejected"
    assert report["validation_metrics"]["formal_identity_integrity_count"] == 59
    assert gates["formal_identity_integrity"]["passed"] is False


def test_forged_physical_touch_fails_evidence_replay_integrity_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["physical_touch_status"] = "not_touched"
    actions[0]["physical_touch_at"] = None
    actions[0]["final_sealed"] = False

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert report["status"] == "forward_rejected"
    assert report["validation_metrics"]["physical_touch_integrity_count"] == 59
    assert gates["physical_touch_integrity"]["passed"] is False


def test_changed_settlement_evidence_fails_immutable_evidence_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["settlement_evidence"]["symbol_observations"][0]["last_price"] = 9.9

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert report["status"] == "forward_rejected"
    assert report["validation_metrics"]["settlement_evidence_integrity_count"] == 59
    assert gates["settlement_evidence_integrity"]["passed"] is False


def test_stored_d1_date_must_be_the_next_official_market_session() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    action = actions[0]
    wrong_d1 = VALIDATION_DATES[2]
    action["d1_trade_date"] = wrong_d1
    bars.append(
        {
            "vt_symbol": action["vt_symbol"],
            "trade_date": wrong_d1,
            "open_price": action["d1_close_price"],
            "high_price": action["d1_close_price"],
            "low_price": action["d1_close_price"],
            "close_price": action["d1_close_price"],
        }
    )

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert report["status"] == "forward_rejected"
    assert gates["official_d1_outcome_integrity"]["passed"] is False


def test_pending_physical_touch_stage_fails_action_stage_completion_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["physical_touch_status"] = "pending"
    actions[0]["physical_touch_at"] = None
    actions[0]["final_sealed"] = None

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert report["status"] == "forward_rejected"
    assert metrics["settled_action_stage_count"] == 59
    assert gates["action_stage_completion"]["passed"] is False


def test_rehashed_wrong_action_score_fails_frozen_model_replay_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["action_probability"] = 0.99
    actions[0]["decision_fingerprint"] = point_trigger_action_decision_fingerprint(
        actions[0]
    )

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert metrics["action_decision_integrity_count"] == 60
    assert metrics["action_model_replay_integrity_count"] == 59
    assert gates["action_model_replay_integrity"]["passed"] is False
    assert report["status"] == "forward_rejected"


def test_missing_expected_action_fails_complete_action_set_replay_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions.pop(0)

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert report["status"] == "forward_rejected"
    assert metrics["expected_action_count"] == 60
    assert metrics["missing_expected_action_count"] == 1
    assert metrics["unexpected_action_count"] == 0
    assert metrics["complete_action_set_replay"] == 0
    assert gates["complete_action_set_replay"]["passed"] is False


def test_changed_validation_label_fails_scope_integrity_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    features[0]["formal_identity_within_60s"] = False

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert report["status"] == "forward_rejected"
    assert metrics["validation_scope_integrity_count"] == 59
    assert gates["validation_scope_integrity"]["passed"] is False


def test_three_valid_actions_on_one_day_fail_two_slot_selection_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    extras = [
        _action(
            VALIDATION_DATES[0],
            100 + offset,
            winning=True,
            captured_second=20 + offset * 10,
        )
        for offset in range(2)
    ]
    actions.extend(extras)
    bars.extend(_bars_for_actions(extras))

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert report["status"] == "forward_rejected"
    assert report["validation_metrics"]["action_selection_integrity"] == 0
    assert gates["action_selection_integrity"]["passed"] is False


def test_a_single_action_cannot_start_at_daily_slot_two() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["daily_slot"] = 2
    actions[0]["decision_fingerprint"] = point_trigger_action_decision_fingerprint(
        actions[0]
    )

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert report["status"] == "forward_rejected"
    assert report["validation_metrics"]["action_selection_integrity"] == 0
    assert gates["action_selection_integrity"]["passed"] is False


def test_seventy_percent_point_identity_precision_cannot_pass_reliability_gate() -> (
    None
):
    actions, features, formal_orders, bars = _mature_inputs()
    for action in actions[42:]:
        action["formal_identity_status"] = "missed"
        action["formal_identity_matched"] = False

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders[:42],
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert report["status"] == "forward_rejected"
    assert metrics["formal_identity_precision_pct"] == 70.0
    assert metrics["formal_identity_precision_wilson_lower_pct"] == 57.4913
    assert metrics["original_account_identity_precision_pct"] == 70.0
    assert metrics["original_account_identity_precision_wilson_lower_pct"] == 57.4913
    assert gates["formal_identity_precision"]["passed"] is True
    assert gates["formal_identity_precision_wilson_lower"]["passed"] is False
    assert gates["original_account_identity_precision"]["passed"] is True
    assert gates["original_account_identity_precision_wilson_lower"]["passed"] is False


def test_forward_rejected_report_cannot_be_archived(monkeypatch, tmp_path) -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    for action in actions[42:]:
        action["formal_identity_status"] = "missed"
        action["formal_identity_matched"] = False

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders[:42],
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    assert report["status"] == "forward_rejected"
    monkeypatch.setattr(
        study,
        "load_point_trigger_forward_report",
        lambda: report,
    )
    with pytest.raises(ValueError, match="reliable live-review candidate"):
        archive_point_trigger_forward_report(report, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_archive_rejects_report_not_matching_authoritative_ledgers(
    monkeypatch,
    tmp_path,
) -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )
    forged = deepcopy(report)
    forged["validation_metrics"]["average_net_return_pct"] = 9.9
    next(
        gate
        for gate in forged["reliability_gates"]
        if gate["name"] == "average_net_return"
    )["current"] = 9.9
    monkeypatch.setattr(
        study,
        "load_point_trigger_forward_report",
        lambda: report,
    )

    with pytest.raises(ValueError, match="authoritative ledger report"):
        archive_point_trigger_forward_report(forged, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_sixty_percent_point_d1_win_rate_cannot_pass_reliability_gate() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    for index, action in enumerate(actions):
        winning = index < 36
        close_price = 10.4 if winning else 10.0
        normal = radar_validation._execution_outcome(
            10.0,
            close_price,
            limit_price=11.0,
            cost_multiplier=1.0,
        )
        stress = radar_validation._execution_outcome(
            10.0,
            close_price,
            limit_price=11.0,
            cost_multiplier=2.0,
        )
        assert normal is not None and stress is not None
        action["d1_close_price"] = close_price
        action["gross_return_pct"] = round((close_price / 10.0 - 1.0) * 100.0, 4)
        action["net_return_pct"] = normal["net_return_pct"]
        action["double_cost_net_return_pct"] = stress["net_return_pct"]
    bars = _bars_for_actions(actions)

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    metrics = report["validation_metrics"]
    assert metrics["d1_win_rate_pct"] == 60.0
    assert metrics["d1_win_rate_wilson_lower_pct"] == 47.3661
    assert gates["d1_win_rate"]["passed"] is True
    assert gates["d1_win_rate_wilson_lower"]["passed"] is False


def test_any_null_hard_gate_rejects_the_mature_validation() -> None:
    actions, features, formal_orders, bars = _mature_inputs()
    actions[0]["double_cost_net_return_pct"] = None

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars,
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    assert report["status"] == "forward_rejected"
    assert gates["double_cost_return_coverage"]["current"] == 59
    assert gates["double_cost_return_coverage"]["passed"] is False


def test_missing_official_account_bar_cannot_be_hidden_by_derived_fallback() -> None:
    actions, features, formal_orders, bars = _mature_inputs()

    report = build_point_trigger_forward_report(
        scopes=_validation_scopes(),
        model=_model(),
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=[],
        daily_bars=bars[:-1],
        trade_dates=[*VALIDATION_DATES, VALIDATION_DATES[-1] + timedelta(days=1)],
    )

    gates = {gate["name"]: gate for gate in report["reliability_gates"]}
    audit = report["accounts"]["market_data_audit"]
    assert report["status"] == "forward_rejected"
    assert audit["complete"] is False
    assert audit["expected_early_bar_count"] == 120
    assert audit["supplied_early_bar_count"] == 119
    assert gates["early_account_market_data_coverage"]["passed"] is False
