"""Frozen forward acceptance report for the point-trigger v9 study."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from hashlib import sha256
import json
from math import isfinite, sqrt
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import (
    cash_backtest,
    radar_validation,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CALIBRATION_DAY_COUNT,
    CONTRACT_VERSION,
    ELIGIBLE_AFTER,
    FIT_DAY_COUNT,
    VALIDATION_DAY_COUNT,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_dataset import (
    point_trigger_input_fingerprint,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_model import (
    ACTION_SCORE_FIELD,
    EVENT_SCORE_FIELD,
    IDENTITY_SCORE_FIELD,
    score_frozen_point_top1,
    select_point_actions,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_repository import (
    load_point_trigger_actions,
    load_point_trigger_day_scopes,
    load_point_trigger_feature_rows,
    load_point_trigger_models,
    point_trigger_action_decision_fingerprint,
    point_trigger_day_record_is_intact,
    point_trigger_model_record_fingerprint,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_settlement import (
    point_trigger_settlement_evidence_fingerprint,
    replay_delayed_fill_outcome,
    replay_formal_identity_outcome,
    replay_physical_touch_outcome,
    settlement_evidence_matches_action,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
KNOWN_FORMAL_IDENTITY_STATUSES = frozenset({"matched", "missed", "no_event"})
ARCHIVE_BASENAME = "limit_up_preboard_point_trigger_v9_forward"
RELIABILITY_GATE_VERSION = "limit-up-preboard-point-trigger-reliability-v8"
WILSON_95_Z = 1.959963984540054
MAXIMUM_BASELINE_DRAWDOWN_DEGRADATION_PCT = 1.0
MINIMUM_BASELINE_PROFIT_FACTOR_RATIO = 0.95


class PointTriggerArchiveConflict(RuntimeError):
    """Raised when a frozen report path already contains different evidence."""


def freeze_point_trigger_cohorts(
    scopes: Sequence[Mapping[str, object]],
    model: Mapping[str, object] | None,
) -> dict[str, object]:
    """Resolve immutable fit/calibration dates and the first 60 forward scopes."""

    eligible: list[dict[str, object]] = []
    for scope in scopes:
        trade_date = _as_date(scope.get("trade_date"))
        if (
            scope.get("contract_version") == CONTRACT_VERSION
            and scope.get("is_complete") is True
            and scope.get("eligible_for_model") is True
            and trade_date is not None
            and trade_date > ELIGIBLE_AFTER
        ):
            eligible.append(dict(scope))
    eligible_dates = [_as_date(scope.get("trade_date")) for scope in eligible]
    if len(eligible_dates) != len(set(eligible_dates)):
        raise ValueError("point-trigger has a duplicate complete scope date")
    eligible.sort(key=lambda scope: _as_date(scope.get("trade_date")) or date.max)
    model_row = dict(model) if isinstance(model, Mapping) else None
    if model_row is None:
        fit_dates = tuple(
            _as_date(scope.get("trade_date")) for scope in eligible[:FIT_DAY_COUNT]
        )
        calibration_dates = tuple(
            _as_date(scope.get("trade_date"))
            for scope in eligible[FIT_DAY_COUNT : FIT_DAY_COUNT + CALIBRATION_DAY_COUNT]
        )
        typed_fit = tuple(value for value in fit_dates if value is not None)
        typed_calibration = tuple(
            value for value in calibration_dates if value is not None
        )
        return {
            "fit_trade_dates": list(typed_fit),
            "calibration_trade_dates": list(typed_calibration),
            "validation_trade_dates": [],
            "fit_cohort_id": _fingerprint(
                {"contract_version": CONTRACT_VERSION, "fit": typed_fit}
            ),
            "calibration_cohort_id": (
                _fingerprint(
                    {
                        "contract_version": CONTRACT_VERSION,
                        "fit": typed_fit,
                        "calibration": typed_calibration,
                    }
                )
                if len(typed_calibration) == CALIBRATION_DAY_COUNT
                else None
            ),
            "validation_cohort_id": None,
            "validation_collection_fingerprint": None,
            "validation_complete_day_count": 0,
            "validation_available_day_count": 0,
            "validation_remaining_day_count": VALIDATION_DAY_COUNT,
            "eligible_complete_day_count": len(eligible),
        }

    if model_row.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("point-trigger model contract does not match the study")
    fit_dates = _required_date_tuple(
        model_row.get("fit_trade_dates"),
        "fit_trade_dates",
    )
    calibration_dates = _required_date_tuple(
        model_row.get("calibration_trade_dates"),
        "calibration_trade_dates",
    )
    if (
        len(fit_dates) != FIT_DAY_COUNT
        or len(calibration_dates) != CALIBRATION_DAY_COUNT
    ):
        raise ValueError(
            "point-trigger model does not contain the frozen 40/15 cohorts"
        )
    if (
        len(set((*fit_dates, *calibration_dates)))
        != FIT_DAY_COUNT + CALIBRATION_DAY_COUNT
    ):
        raise ValueError("point-trigger model cohort dates must be unique")
    if any(value <= ELIGIBLE_AFTER for value in (*fit_dates, *calibration_dates)):
        raise ValueError(
            "point-trigger model cohort dates must be after eligible_after"
        )
    if fit_dates != tuple(sorted(fit_dates)) or calibration_dates != tuple(
        sorted(calibration_dates)
    ):
        raise ValueError("point-trigger model cohort dates must be chronological")
    if fit_dates[-1] >= calibration_dates[0]:
        raise ValueError("point-trigger calibration dates must follow fit dates")
    model_frozen_at = _as_datetime(model_row.get("frozen_at"))
    calibration_close = datetime.combine(
        calibration_dates[-1],
        time(15, 0),
        tzinfo=SHANGHAI,
    )
    if model_frozen_at is None or model_frozen_at < calibration_close:
        raise ValueError(
            "point-trigger model must freeze after the calibration cohort closes"
        )

    calibration_end = max(calibration_dates)
    model_dates = set((*fit_dates, *calibration_dates))
    validation_scopes = [
        scope
        for scope in eligible
        if (scope_date := _as_date(scope.get("trade_date"))) is not None
        and (scope_frozen_at := _as_datetime(scope.get("frozen_at"))) is not None
        and scope_date > calibration_end
        and scope_date not in model_dates
        and scope_frozen_at > model_frozen_at
        and scope_frozen_at
        >= datetime.combine(scope_date, time(15, 0), tzinfo=SHANGHAI)
    ]
    validation_scopes.sort(key=_scope_freeze_sort_key)
    selected_scopes = validation_scopes[:VALIDATION_DAY_COUNT]
    selected_dates = tuple(
        value
        for scope in selected_scopes
        if (value := _as_date(scope.get("trade_date"))) is not None
    )
    validation_payload = {
        "contract_version": CONTRACT_VERSION,
        "model_fingerprint": model_row.get("model_fingerprint"),
        "scopes": [
            {
                "trade_date": _as_date(scope.get("trade_date")),
                "cohort_fingerprint": scope.get("cohort_fingerprint"),
                "frozen_at": _as_datetime(scope.get("frozen_at")),
            }
            for scope in selected_scopes
        ],
    }
    collection_fingerprint = _fingerprint(validation_payload)
    validation_cohort_id = (
        collection_fingerprint if len(selected_dates) == VALIDATION_DAY_COUNT else None
    )
    return {
        "fit_trade_dates": list(fit_dates),
        "calibration_trade_dates": list(calibration_dates),
        "validation_trade_dates": list(selected_dates),
        "fit_cohort_id": _fingerprint(
            {
                "contract_version": CONTRACT_VERSION,
                "model_fingerprint": model_row.get("model_fingerprint"),
                "fit": fit_dates,
            }
        ),
        "calibration_cohort_id": _fingerprint(
            {
                "contract_version": CONTRACT_VERSION,
                "model_fingerprint": model_row.get("model_fingerprint"),
                "fit": fit_dates,
                "calibration": calibration_dates,
            }
        ),
        "validation_cohort_id": validation_cohort_id,
        "validation_collection_fingerprint": collection_fingerprint,
        "validation_complete_day_count": len(selected_dates),
        "validation_available_day_count": len(selected_dates),
        "validation_remaining_day_count": max(
            VALIDATION_DAY_COUNT - len(selected_dates),
            0,
        ),
        "eligible_complete_day_count": min(
            len(eligible),
            FIT_DAY_COUNT + CALIBRATION_DAY_COUNT + VALIDATION_DAY_COUNT,
        ),
    }


def build_point_trigger_forward_report(
    *,
    scopes: Sequence[Mapping[str, object]],
    model: Mapping[str, object] | None,
    actions: Sequence[Mapping[str, object]] = (),
    feature_rows: Sequence[Mapping[str, object]] = (),
    formal_orders: Sequence[Mapping[str, object]] | None = None,
    relay_orders: Sequence[Mapping[str, object]] | None = None,
    daily_bars: Sequence[Mapping[str, object]] = (),
    trade_dates: Sequence[date | str] = (),
) -> dict[str, object]:
    """Build the only report allowed to declare a live-review candidate."""

    model_row = dict(model) if isinstance(model, Mapping) else None
    cohorts = freeze_point_trigger_cohorts(scopes, model_row)
    phase = {
        **cohorts,
        "fit_complete_day_count": len(cohorts["fit_trade_dates"]),
        "calibration_complete_day_count": len(cohorts["calibration_trade_dates"]),
    }
    base = {
        "contract_version": CONTRACT_VERSION,
        "reliability_gate_version": RELIABILITY_GATE_VERSION,
        "model_fingerprint": (
            model_row.get("model_fingerprint") if model_row is not None else None
        ),
        "model_status": model_row.get("status") if model_row is not None else None,
        "phase": phase,
        "production_effect": "none_research_only",
        "formal_strategy_changed": False,
        "model_record_integrity_verified": (
            _has_intact_model_record(model_row) if model_row is not None else False
        ),
    }
    if model_row is None:
        status = (
            "collecting_fit"
            if len(cohorts["fit_trade_dates"]) < FIT_DAY_COUNT
            else "collecting_calibration"
        )
        return _hidden_report(base, status, "frozen model is not available")
    if base["model_record_integrity_verified"] is not True:
        return _hidden_report(
            base,
            "forward_rejected",
            "frozen model record fingerprint is invalid",
        )
    if model_row.get("status") != "active":
        return _hidden_report(
            base,
            "forward_rejected",
            "calibration did not freeze an active threshold",
        )
    if cohorts["validation_complete_day_count"] < VALIDATION_DAY_COUNT:
        return _hidden_report(
            base,
            "forward_collecting",
            "60 complete forward validation days are not frozen",
        )

    validation_dates = {
        value
        for raw in cohorts["validation_trade_dates"]
        if (value := _as_date(raw)) is not None
    }
    model_fingerprint = str(model_row.get("model_fingerprint") or "")
    selected_actions = [
        dict(action)
        for action in actions
        if _as_date(action.get("trade_date")) in validation_dates
        and str(action.get("model_fingerprint") or "") == model_fingerprint
        and action.get("contract_version") == CONTRACT_VERSION
    ]
    selected_features = [
        dict(row)
        for row in feature_rows
        if _as_date(row.get("trade_date")) in validation_dates
        and row.get("contract_version") == CONTRACT_VERSION
    ]
    selected_scopes = [
        dict(scope)
        for scope in scopes
        if _as_date(scope.get("trade_date")) in validation_dates
        and scope.get("contract_version") == CONTRACT_VERSION
    ]
    selected_formal_orders = (
        _frozen_scope_formal_orders(selected_scopes)
        if formal_orders is None
        else [
            dict(order)
            for order in formal_orders
            if _as_date(order.get("entry_date") or order.get("signal_date"))
            in validation_dates
        ]
    )
    selected_relays = (
        [
            dict(order)
            for order in selected_formal_orders
            if str(order.get("lane") or order.get("board_lane") or "") == "two_to_three"
        ]
        if relay_orders is None
        else [
            dict(order)
            for order in relay_orders
            if _as_date(order.get("entry_date") or order.get("signal_date"))
            in validation_dates
        ]
    )
    accounts = build_point_trigger_accounts(
        selected_actions,
        selected_relays,
        daily_bars,
        trade_dates,
        formal_orders=selected_formal_orders,
        validation_dates=sorted(validation_dates),
    )
    accounts["action_settlement_audit"] = _action_settlement_integrity_audit(
        selected_actions,
        selected_features,
        daily_bars,
    )
    metrics = _validation_metrics(
        selected_actions,
        selected_features,
        selected_scopes,
        accounts,
        sorted(validation_dates),
        model_row,
    )
    gates = _reliability_gates(metrics)
    passed = bool(gates) and all(gate["passed"] is True for gate in gates)
    status = (
        "forward_reliable_candidate_for_live_review" if passed else "forward_rejected"
    )
    return {
        **base,
        "status": status,
        "message": (
            "all frozen forward gates passed; production review is still required"
            if passed
            else "one or more frozen forward gates failed"
        ),
        "performance_visible": True,
        "validation_metrics": metrics,
        "accounts": accounts,
        "reliability_gates": gates,
    }


def build_point_trigger_accounts(
    actions: Sequence[Mapping[str, object]],
    relay_orders: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date | str],
    *,
    formal_orders: Sequence[Mapping[str, object]] = (),
    validation_dates: Sequence[date | str] = (),
) -> dict[str, object]:
    """Replay early first boards alone and beside unchanged two-to-three orders."""

    action_rows = [dict(action) for action in actions]
    early_signals = [
        signal
        for action in action_rows
        if (signal := _action_signal(action)) is not None
    ]
    relays = [
        dict(order)
        for order in relay_orders
        if str(order.get("lane") or order.get("board_lane") or "") == "two_to_three"
    ]
    formal = [
        dict(order)
        for order in formal_orders
        if str(order.get("lane") or order.get("board_lane") or "")
        in scheduled_execution.PRODUCT_EXECUTION_LANES
    ]
    calendar = _account_calendar(trade_dates)
    official_outcome_audit = _official_action_outcome_audit(
        action_rows,
        daily_bars,
        calendar,
    )
    early_signals = _bind_next_close_dates(early_signals, calendar)
    relays = _bind_next_close_dates(relays, calendar)
    formal = _bind_next_close_dates(formal, calendar)
    bars = _official_account_bars(daily_bars)
    market_data_audit = _account_market_data_audit(early_signals, daily_bars)
    formal_market_data_audit = _account_market_data_audit(formal, daily_bars)
    normal_config = _account_config(cost_multiplier=1.0)
    double_config = _account_config(cost_multiplier=2.0)
    early_normal = cash_backtest.simulate_limit_up_account(
        early_signals,
        bars,
        calendar,
        scheduled_execution.EXIT_MODE,
        normal_config,
    )
    early_double = cash_backtest.simulate_limit_up_account(
        early_signals,
        bars,
        calendar,
        scheduled_execution.EXIT_MODE,
        double_config,
    )
    market_data_audit["normal_account_closed"] = not bool(
        early_normal.get("open_positions")
    )
    market_data_audit["double_cost_account_closed"] = not bool(
        early_double.get("open_positions")
    )
    market_data_audit["complete"] = bool(
        market_data_audit.get("complete")
        and market_data_audit["normal_account_closed"]
        and market_data_audit["double_cost_account_closed"]
    )
    joint_signals = [*early_signals, *relays]
    joint_normal = cash_backtest.simulate_limit_up_account(
        joint_signals,
        bars,
        calendar,
        scheduled_execution.EXIT_MODE,
        normal_config,
    )
    joint_double = cash_backtest.simulate_limit_up_account(
        joint_signals,
        bars,
        calendar,
        scheduled_execution.EXIT_MODE,
        double_config,
    )
    joint_market_data_audit = _account_market_data_audit(
        joint_signals,
        daily_bars,
    )
    joint_market_data_audit["normal_account_closed"] = not bool(
        joint_normal.get("open_positions")
    )
    joint_market_data_audit["double_cost_account_closed"] = not bool(
        joint_double.get("open_positions")
    )
    joint_market_data_audit["complete"] = bool(
        joint_market_data_audit.get("complete")
        and joint_market_data_audit["normal_account_closed"]
        and joint_market_data_audit["double_cost_account_closed"]
    )
    original_formal = cash_backtest.simulate_limit_up_account(
        formal,
        bars,
        calendar,
        scheduled_execution.EXIT_MODE,
        normal_config,
    )
    original_formal_double = cash_backtest.simulate_limit_up_account(
        formal,
        bars,
        calendar,
        scheduled_execution.EXIT_MODE,
        double_config,
    )
    chronological_blocks = _build_account_blocks(
        early_normal,
        early_signals,
        validation_dates,
    )
    joint_chronological_blocks = _build_account_blocks(
        joint_normal,
        joint_signals,
        validation_dates,
    )
    formal_market_data_audit["normal_account_closed"] = not bool(
        original_formal.get("open_positions")
    )
    formal_market_data_audit["double_cost_account_closed"] = not bool(
        original_formal_double.get("open_positions")
    )
    formal_market_data_audit["complete"] = bool(
        formal_market_data_audit.get("complete")
        and formal_market_data_audit["normal_account_closed"]
        and formal_market_data_audit["double_cost_account_closed"]
    )
    queue_unknown = [
        action
        for action in action_rows
        if action.get("fill_status") == "queue_unknown_without_l2"
    ]
    other_rejected = [
        action
        for action in action_rows
        if action.get("fill_status") not in {"filled", "queue_unknown_without_l2"}
    ]
    return {
        "early_first_board_normal": early_normal,
        "early_first_board_double_cost": early_double,
        "joint_with_two_to_three_normal": joint_normal,
        "joint_with_two_to_three_double_cost": joint_double,
        "original_formal_normal": original_formal,
        "original_formal_double_cost": original_formal_double,
        "early_first_board_chronological_blocks": chronological_blocks,
        "joint_with_two_to_three_chronological_blocks": (
            joint_chronological_blocks
        ),
        "queue_unknown_rejection": {
            "input_action_count": len(action_rows),
            "accepted_filled_action_count": len(early_signals),
            "queue_unknown_rejected_count": len(queue_unknown),
            "other_unfilled_rejected_count": len(other_rejected),
            "rejected_action_ids": [
                _action_id(action) for action in [*queue_unknown, *other_rejected]
            ],
            "account": early_normal,
        },
        "market_data_audit": market_data_audit,
        "joint_market_data_audit": joint_market_data_audit,
        "original_formal_market_data_audit": formal_market_data_audit,
        "official_action_outcome_audit": official_outcome_audit,
        "interpretation": {
            "early_first_board": "point-trigger-v9 only",
            "joint": "point-trigger-v9 first boards plus unchanged two-to-three orders",
            "reliability_attribution": (
                "early_first_board_quality_and_joint_product_account"
            ),
        },
    }


def load_point_trigger_forward_report() -> dict[str, object]:
    """Load immutable ledgers and build the current forward report."""

    scopes = load_point_trigger_day_scopes()
    models = load_point_trigger_models()
    if len(models) > 1:
        raise RuntimeError("point-trigger study requires one frozen model decision")
    model = models[0] if models else None
    cohorts = freeze_point_trigger_cohorts(scopes, model)
    validation_dates = [
        value
        for raw in cohorts["validation_trade_dates"]
        if (value := _as_date(raw)) is not None
    ]
    if (
        model is None
        or model.get("status") != "active"
        or len(validation_dates) < VALIDATION_DAY_COUNT
    ):
        return build_point_trigger_forward_report(scopes=scopes, model=model)

    model_fingerprint = str(model.get("model_fingerprint") or "")
    actions = load_point_trigger_actions(model_fingerprint=model_fingerprint)
    features = load_point_trigger_feature_rows(validation_dates)
    formal_orders, relay_orders, bars, calendar = _load_formal_account_inputs(
        validation_dates,
        actions,
        scopes,
    )
    return build_point_trigger_forward_report(
        scopes=scopes,
        model=model,
        actions=actions,
        feature_rows=features,
        formal_orders=formal_orders,
        relay_orders=relay_orders,
        daily_bars=bars,
        trade_dates=calendar,
    )


def archive_point_trigger_forward_report(
    report: Mapping[str, object],
    output_directory: str | Path,
) -> dict[str, object]:
    """Atomically archive a mature report in the two planned evidence formats."""

    authoritative = load_point_trigger_forward_report()
    if _fingerprint(report) != _fingerprint(authoritative):
        raise ValueError(
            "forward report does not match the authoritative ledger report"
        )
    phase = _mapping(report.get("phase"))
    _validate_archivable_phase(phase)
    if int(phase.get("validation_complete_day_count") or 0) < VALIDATION_DAY_COUNT:
        raise ValueError("forward report cannot be archived before 60 complete days")
    if report.get("performance_visible") is not True:
        raise ValueError("forward report has no publishable validation metrics")
    raw_gates = report.get("reliability_gates")
    gates = (
        list(raw_gates)
        if isinstance(raw_gates, Sequence) and not isinstance(raw_gates, (str, bytes))
        else []
    )
    metrics = report.get("validation_metrics")
    expected_gates = _reliability_gates(metrics) if isinstance(metrics, Mapping) else []
    if (
        report.get("contract_version") != CONTRACT_VERSION
        or report.get("reliability_gate_version") != RELIABILITY_GATE_VERSION
        or report.get("status") != "forward_reliable_candidate_for_live_review"
        or report.get("production_effect") != "none_research_only"
        or report.get("formal_strategy_changed") is not False
        or report.get("model_record_integrity_verified") is not True
        or not gates
        or gates != expected_gates
        or any(
            not isinstance(gate, Mapping) or gate.get("passed") is not True
            for gate in gates
        )
    ):
        raise ValueError(
            "only a fully gated reliable live-review candidate can be archived"
        )
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{ARCHIVE_BASENAME}.json"
    markdown_path = directory / f"{ARCHIVE_BASENAME}.md"
    payload = dict(report)
    payload["report_fingerprint"] = _fingerprint(report)
    json_content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n"
    )
    markdown_content = _render_markdown(payload)
    _verify_existing_archive(
        json_path,
        markdown_path,
        payload["report_fingerprint"],
        markdown_content,
    )
    if not json_path.exists():
        _atomic_write(json_path, json_content)
    if not markdown_path.exists():
        _atomic_write(markdown_path, markdown_content)
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "report_fingerprint": payload["report_fingerprint"],
        "status": payload.get("status"),
    }


def _validation_metrics(
    actions: Sequence[Mapping[str, object]],
    feature_rows: Sequence[Mapping[str, object]],
    scopes: Sequence[Mapping[str, object]],
    accounts: Mapping[str, object],
    validation_dates: Sequence[date],
    model: Mapping[str, object],
) -> dict[str, object]:
    action_rows = [dict(action) for action in actions]
    feature_rows_by_date: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in feature_rows:
        trade_date = _as_date(row.get("trade_date"))
        if trade_date is not None:
            feature_rows_by_date[trade_date].append(dict(row))
    validation_scope_integrity_count = sum(
        point_trigger_day_record_is_intact(
            scope,
            feature_rows_by_date.get(trade_date, []),
        )
        for scope in scopes
        if (trade_date := _as_date(scope.get("trade_date"))) is not None
    )
    stored_closed = [
        action
        for action in action_rows
        if action.get("fill_status") == "filled" and action.get("d1_status") == "closed"
    ]
    stored_returns = [
        value
        for action in stored_closed
        if (value := _number(action.get("net_return_pct"))) is not None
    ]
    stored_stress_returns = [
        value
        for action in stored_closed
        if (value := _number(action.get("double_cost_net_return_pct"))) is not None
    ]
    official_outcome_audit = _mapping(accounts.get("official_action_outcome_audit"))
    settlement_audit = _mapping(accounts.get("action_settlement_audit"))
    raw_official_outcomes = official_outcome_audit.get("closed_outcomes")
    official_outcomes = (
        [dict(row) for row in raw_official_outcomes if isinstance(row, Mapping)]
        if isinstance(raw_official_outcomes, Sequence)
        and not isinstance(raw_official_outcomes, (str, bytes))
        else []
    )
    returns = [
        value
        for outcome in official_outcomes
        if (value := _number(outcome.get("net_return_pct"))) is not None
    ]
    stress_returns = [
        value
        for outcome in official_outcomes
        if (value := _number(outcome.get("double_cost_net_return_pct"))) is not None
    ]
    known_identity = [
        action
        for action in action_rows
        if str(action.get("formal_identity_status") or "")
        in KNOWN_FORMAL_IDENTITY_STATUSES
        and isinstance(action.get("formal_identity_matched"), bool)
    ]
    original_account_audit = _mapping(accounts.get("original_formal_market_data_audit"))
    original_formal_account = _mapping(accounts.get("original_formal_normal"))
    original_formal_summary = _mapping(
        original_formal_account.get("execution_summary")
    )
    original_formal_double_account = _mapping(
        accounts.get("original_formal_double_cost")
    )
    original_formal_double_summary = _mapping(
        original_formal_double_account.get("execution_summary")
    )
    original_account_pairs = _filled_first_board_pairs(original_formal_account)
    original_identity = [
        action
        for action in action_rows
        if original_account_audit.get("complete") is True
        and _action_stock_day_pair(action) is not None
    ]
    reachable_events = {
        key for row in feature_rows if (key := _formal_event_key(row)) is not None
    }
    scope_reachable_values = [
        _number(
            _mapping(scope.get("audit_metrics")).get(
                "formal_event_static_eligible_within_60s_count"
            )
        )
        for scope in scopes
    ]
    scope_reachable_coverage_count = sum(
        value is not None and value >= 0 and value.is_integer()
        for value in scope_reachable_values
    )
    scope_reachable_event_count = sum(
        int(value)
        for value in scope_reachable_values
        if value is not None and value >= 0 and value.is_integer()
    )
    matched_events = {
        key
        for action in known_identity
        if action.get("formal_identity_matched") is True
        and (key := _formal_event_key(action)) is not None
    }
    early_account = _mapping(accounts.get("early_first_board_normal"))
    early_summary = _mapping(early_account.get("execution_summary"))
    early_double_account = _mapping(accounts.get("early_first_board_double_cost"))
    early_double_summary = _mapping(early_double_account.get("execution_summary"))
    joint_account = _mapping(accounts.get("joint_with_two_to_three_normal"))
    joint_summary = _mapping(joint_account.get("execution_summary"))
    joint_double_account = _mapping(
        accounts.get("joint_with_two_to_three_double_cost")
    )
    joint_double_summary = _mapping(
        joint_double_account.get("execution_summary")
    )
    raw_blocks = accounts.get("early_first_board_chronological_blocks")
    blocks = (
        [dict(block) for block in raw_blocks if isinstance(block, Mapping)]
        if isinstance(raw_blocks, Sequence)
        else []
    )
    raw_joint_blocks = accounts.get(
        "joint_with_two_to_three_chronological_blocks"
    )
    joint_blocks = (
        [dict(block) for block in raw_joint_blocks if isinstance(block, Mapping)]
        if isinstance(raw_joint_blocks, Sequence)
        else []
    )
    contribution, maximum_share = _account_profit_contribution_by_date(early_account)
    market_data_audit = _mapping(accounts.get("market_data_audit"))
    joint_market_data_audit = _mapping(accounts.get("joint_market_data_audit"))
    formal_identity_match_count = sum(
        action.get("formal_identity_matched") is True for action in known_identity
    )
    original_account_identity_match_count = sum(
        _action_stock_day_pair(action) in original_account_pairs
        for action in original_identity
    )
    action_decision_integrity_count = sum(
        _has_intact_action_decision(action) for action in action_rows
    )
    settled_action_stage_count = sum(
        _has_settled_action_stages(action) for action in action_rows
    )
    action_model_replay_integrity_count = _action_model_replay_integrity_count(
        action_rows,
        feature_rows,
        model,
    )
    action_selection_integrity = int(_has_intact_action_selection(action_rows))
    action_set_replay = _action_set_replay_metrics(
        action_rows,
        feature_rows,
        model,
    )
    matched_reachable_event_count = len(reachable_events.intersection(matched_events))
    d1_win_count = sum(value > 0 for value in returns)
    metrics = {
        "validation_complete_day_count": len(validation_dates),
        "validation_scope_integrity_count": validation_scope_integrity_count,
        "total_action_count": len(action_rows),
        "closed_action_count": len(official_outcomes),
        "action_day_count": len(
            {
                value
                for outcome in official_outcomes
                if (value := _as_date(outcome.get("trade_date"))) is not None
            }
        ),
        "normal_return_coverage_count": len(stored_returns),
        "double_cost_return_coverage_count": len(stored_stress_returns),
        "formal_identity_coverage_count": len(known_identity),
        "settled_action_stage_count": settled_action_stage_count,
        "official_d1_outcome_integrity_count": _integer(
            official_outcome_audit.get("integrity_count")
        ),
        "settlement_evidence_integrity_count": _integer(
            settlement_audit.get("evidence_integrity_count")
        ),
        "delayed_fill_integrity_count": _integer(
            settlement_audit.get("delayed_fill_integrity_count")
        ),
        "formal_identity_integrity_count": _integer(
            settlement_audit.get("formal_identity_integrity_count")
        ),
        "physical_touch_integrity_count": _integer(
            settlement_audit.get("physical_touch_integrity_count")
        ),
        "action_decision_integrity_count": action_decision_integrity_count,
        "action_model_replay_integrity_count": (action_model_replay_integrity_count),
        "action_selection_integrity": action_selection_integrity,
        **action_set_replay,
        "original_account_identity_coverage_count": len(original_identity),
        "formal_identity_match_count": formal_identity_match_count,
        "original_account_identity_match_count": (
            original_account_identity_match_count
        ),
        "formal_identity_precision_pct": _ratio_pct(
            formal_identity_match_count,
            len(known_identity),
        ),
        "formal_identity_precision_wilson_lower_pct": _wilson_lower_pct(
            formal_identity_match_count,
            len(known_identity),
        ),
        "original_account_identity_precision_pct": _ratio_pct(
            original_account_identity_match_count,
            len(original_identity),
        ),
        "original_account_identity_precision_wilson_lower_pct": (
            _wilson_lower_pct(
                original_account_identity_match_count,
                len(original_identity),
            )
        ),
        "original_formal_market_data_complete": (
            original_account_audit.get("complete") is True
        ),
        "original_formal_trade_count": _integer(
            original_formal_summary.get("filled_count")
        ),
        "original_formal_win_rate_pct": _number(
            original_formal_summary.get("win_rate")
        ),
        "original_formal_total_return_pct": _number(
            original_formal_summary.get("total_return_pct")
        ),
        "original_formal_max_drawdown_pct": _number(
            original_formal_summary.get("max_drawdown_pct")
        ),
        "original_formal_profit_factor": _number(
            original_formal_summary.get("profit_factor")
        ),
        "original_formal_double_win_rate_pct": _number(
            original_formal_double_summary.get("win_rate")
        ),
        "original_formal_double_total_return_pct": _number(
            original_formal_double_summary.get("total_return_pct")
        ),
        "original_formal_double_max_drawdown_pct": _number(
            original_formal_double_summary.get("max_drawdown_pct")
        ),
        "original_formal_double_profit_factor": _number(
            original_formal_double_summary.get("profit_factor")
        ),
        "reachable_event_scope_coverage_count": (scope_reachable_coverage_count),
        "scope_reachable_formal_event_count": scope_reachable_event_count,
        "labeled_reachable_formal_event_count": len(reachable_events),
        "reachable_event_label_reconciled": int(
            scope_reachable_coverage_count == len(validation_dates)
            and len(reachable_events) == scope_reachable_event_count
        ),
        "reachable_formal_event_count": scope_reachable_event_count,
        "matched_reachable_formal_event_count": matched_reachable_event_count,
        "reachable_recall_pct": _ratio_pct(
            matched_reachable_event_count,
            scope_reachable_event_count,
        ),
        "reachable_recall_wilson_lower_pct": _wilson_lower_pct(
            matched_reachable_event_count,
            scope_reachable_event_count,
        ),
        "d1_win_count": d1_win_count,
        "d1_win_rate_pct": _ratio_pct(
            d1_win_count,
            len(returns),
        ),
        "d1_win_rate_wilson_lower_pct": _wilson_lower_pct(
            d1_win_count,
            len(returns),
        ),
        "proportion_confidence_method": "wilson_two_sided_95pct",
        "average_net_return_pct": (round(mean(returns), 4) if returns else None),
        "profit_factor": _profit_factor(returns),
        "double_cost_profit_factor": _profit_factor(stress_returns),
        "early_account_signal_count": _integer(early_summary.get("signal_count")),
        "early_account_trade_count": _integer(early_summary.get("trade_count")),
        "early_account_total_return_pct": _number(
            early_summary.get("total_return_pct")
        ),
        "early_account_max_drawdown_pct": _number(
            early_summary.get("max_drawdown_pct")
        ),
        "early_account_profit_factor": _number(early_summary.get("profit_factor")),
        "early_double_cost_total_return_pct": _number(
            early_double_summary.get("total_return_pct")
        ),
        "early_double_cost_profit_factor": _number(
            early_double_summary.get("profit_factor")
        ),
        "early_account_market_data_complete": (
            market_data_audit.get("complete") is True
        ),
        "joint_account_signal_count": _integer(joint_summary.get("signal_count")),
        "joint_account_trade_count": _integer(joint_summary.get("trade_count")),
        "joint_account_win_rate_pct": _number(joint_summary.get("win_rate")),
        "joint_account_total_return_pct": _number(
            joint_summary.get("total_return_pct")
        ),
        "joint_account_max_drawdown_pct": _number(
            joint_summary.get("max_drawdown_pct")
        ),
        "joint_account_profit_factor": _number(joint_summary.get("profit_factor")),
        "joint_double_cost_total_return_pct": _number(
            joint_double_summary.get("total_return_pct")
        ),
        "joint_double_cost_win_rate_pct": _number(
            joint_double_summary.get("win_rate")
        ),
        "joint_double_cost_max_drawdown_pct": _number(
            joint_double_summary.get("max_drawdown_pct")
        ),
        "joint_double_cost_profit_factor": _number(
            joint_double_summary.get("profit_factor")
        ),
        "joint_account_market_data_complete": (
            joint_market_data_audit.get("complete") is True
        ),
        "joint_vs_formal_win_rate_delta_pct": _metric_delta(
            joint_summary,
            original_formal_summary,
            "win_rate",
        ),
        "joint_vs_formal_total_return_delta_pct": _metric_delta(
            joint_summary,
            original_formal_summary,
            "total_return_pct",
        ),
        "joint_vs_formal_max_drawdown_delta_pct": _metric_delta(
            joint_summary,
            original_formal_summary,
            "max_drawdown_pct",
        ),
        "joint_vs_formal_profit_factor_ratio": _metric_ratio(
            joint_summary,
            original_formal_summary,
            "profit_factor",
        ),
        "joint_double_vs_formal_win_rate_delta_pct": _metric_delta(
            joint_double_summary,
            original_formal_double_summary,
            "win_rate",
        ),
        "joint_double_vs_formal_total_return_delta_pct": _metric_delta(
            joint_double_summary,
            original_formal_double_summary,
            "total_return_pct",
        ),
        "joint_double_vs_formal_max_drawdown_delta_pct": _metric_delta(
            joint_double_summary,
            original_formal_double_summary,
            "max_drawdown_pct",
        ),
        "joint_double_vs_formal_profit_factor_ratio": _metric_ratio(
            joint_double_summary,
            original_formal_double_summary,
            "profit_factor",
        ),
        "chronological_blocks": blocks,
        "positive_block_count": sum(block.get("positive") is True for block in blocks),
        "joint_chronological_blocks": joint_blocks,
        "joint_positive_block_count": sum(
            block.get("positive") is True for block in joint_blocks
        ),
        "profit_contribution_by_date": contribution,
        "max_single_day_profit_share_pct": maximum_share,
        "queue_unknown_rejected_count": sum(
            action.get("fill_status") == "queue_unknown_without_l2"
            for action in action_rows
        ),
        "physical_touch_rate_pct": _ratio_pct(
            sum(
                action.get("physical_touch_status") == "touched"
                for action in action_rows
            ),
            len(action_rows),
        ),
        "final_seal_rate_pct": _ratio_pct(
            sum(action.get("final_sealed") is True for action in action_rows),
            len(action_rows),
        ),
    }
    return metrics


def _reliability_gates(metrics: Mapping[str, object]) -> list[dict[str, object]]:
    closed_count = _integer(metrics.get("closed_action_count"))
    action_count = _integer(metrics.get("total_action_count"))
    return [
        _gate(
            "validation_complete_days",
            metrics.get("validation_complete_day_count"),
            "= 60",
            lambda value: value == VALIDATION_DAY_COUNT,
        ),
        _gate(
            "validation_scope_integrity",
            metrics.get("validation_scope_integrity_count"),
            f"= {VALIDATION_DAY_COUNT}",
            lambda value: value == VALIDATION_DAY_COUNT,
        ),
        _gate(
            "closed_actions",
            metrics.get("closed_action_count"),
            ">= 60",
            lambda value: value >= 60,
        ),
        _gate(
            "action_days",
            metrics.get("action_day_count"),
            ">= 40",
            lambda value: value >= 40,
        ),
        _gate(
            "normal_return_coverage",
            metrics.get("normal_return_coverage_count"),
            f"= {closed_count}",
            lambda value: value == closed_count,
        ),
        _gate(
            "double_cost_return_coverage",
            metrics.get("double_cost_return_coverage_count"),
            f"= {closed_count}",
            lambda value: value == closed_count,
        ),
        _gate(
            "formal_identity_coverage",
            metrics.get("formal_identity_coverage_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "action_stage_completion",
            metrics.get("settled_action_stage_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "settlement_evidence_integrity",
            metrics.get("settlement_evidence_integrity_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "delayed_fill_integrity",
            metrics.get("delayed_fill_integrity_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "formal_identity_integrity",
            metrics.get("formal_identity_integrity_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "physical_touch_integrity",
            metrics.get("physical_touch_integrity_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "official_d1_outcome_integrity",
            metrics.get("official_d1_outcome_integrity_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "action_decision_integrity",
            metrics.get("action_decision_integrity_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "action_model_replay_integrity",
            metrics.get("action_model_replay_integrity_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "action_selection_integrity",
            metrics.get("action_selection_integrity"),
            "= 1",
            lambda value: value == 1,
        ),
        _gate(
            "action_replay_frame_coverage",
            metrics.get("action_replay_scored_frame_count"),
            f"= {int(metrics.get('action_replay_eligible_frame_count') or 0)}",
            lambda value: (
                value == int(metrics.get("action_replay_eligible_frame_count") or 0)
            ),
        ),
        _gate(
            "complete_action_set_replay",
            metrics.get("complete_action_set_replay"),
            "= 1",
            lambda value: value == 1,
        ),
        _gate(
            "original_account_identity_coverage",
            metrics.get("original_account_identity_coverage_count"),
            f"= {action_count}",
            lambda value: value == action_count,
        ),
        _gate(
            "original_formal_market_data_coverage",
            int(metrics.get("original_formal_market_data_complete") is True),
            "= 1",
            lambda value: value == 1,
        ),
        _gate(
            "account_signal_coverage",
            metrics.get("early_account_signal_count"),
            f"= {closed_count}",
            lambda value: value == closed_count,
        ),
        _gate(
            "early_account_market_data_coverage",
            int(metrics.get("early_account_market_data_complete") is True),
            "= 1",
            lambda value: value == 1,
        ),
        _gate(
            "joint_account_market_data_coverage",
            int(metrics.get("joint_account_market_data_complete") is True),
            "= 1",
            lambda value: value == 1,
        ),
        _gate(
            "formal_identity_precision",
            metrics.get("formal_identity_precision_pct"),
            ">= 70%",
            lambda value: value >= 70.0,
        ),
        _gate(
            "formal_identity_precision_wilson_lower",
            metrics.get("formal_identity_precision_wilson_lower_pct"),
            ">= 70%",
            lambda value: value >= 70.0,
        ),
        _gate(
            "original_account_identity_precision",
            metrics.get("original_account_identity_precision_pct"),
            ">= 70%",
            lambda value: value >= 70.0,
        ),
        _gate(
            "original_account_identity_precision_wilson_lower",
            metrics.get("original_account_identity_precision_wilson_lower_pct"),
            ">= 70%",
            lambda value: value >= 70.0,
        ),
        _gate(
            "reachable_event_scope_coverage",
            metrics.get("reachable_event_scope_coverage_count"),
            f"= {VALIDATION_DAY_COUNT}",
            lambda value: value == VALIDATION_DAY_COUNT,
        ),
        _gate(
            "reachable_event_label_reconciliation",
            metrics.get("reachable_event_label_reconciled"),
            "= 1",
            lambda value: value == 1,
        ),
        _gate(
            "reachable_recall",
            metrics.get("reachable_recall_pct"),
            ">= 30%",
            lambda value: value >= 30.0,
        ),
        _gate(
            "reachable_recall_wilson_lower",
            metrics.get("reachable_recall_wilson_lower_pct"),
            ">= 30%",
            lambda value: value >= 30.0,
        ),
        _gate(
            "d1_win_rate",
            metrics.get("d1_win_rate_pct"),
            ">= 60%",
            lambda value: value >= 60.0,
        ),
        _gate(
            "d1_win_rate_wilson_lower",
            metrics.get("d1_win_rate_wilson_lower_pct"),
            ">= 60%",
            lambda value: value >= 60.0,
        ),
        _gate(
            "average_net_return",
            metrics.get("average_net_return_pct"),
            ">= 1%",
            lambda value: value >= 1.0,
        ),
        _gate(
            "positive_normal_two_slot_compound",
            metrics.get("early_account_total_return_pct"),
            "> 0%",
            lambda value: value > 0.0,
        ),
        _gate(
            "positive_double_cost_two_slot_compound",
            metrics.get("early_double_cost_total_return_pct"),
            "> 0%",
            lambda value: value > 0.0,
        ),
        _gate(
            "two_slot_profit_factor",
            metrics.get("early_account_profit_factor"),
            ">= 1.5",
            lambda value: value >= 1.5,
        ),
        _gate(
            "double_cost_two_slot_profit_factor",
            metrics.get("early_double_cost_profit_factor"),
            ">= 1.2",
            lambda value: value >= 1.2,
        ),
        _gate(
            "maximum_drawdown",
            metrics.get("early_account_max_drawdown_pct"),
            ">= -15%",
            lambda value: value >= -15.0,
        ),
        _gate(
            "positive_joint_two_slot_compound",
            metrics.get("joint_account_total_return_pct"),
            "> 0%",
            lambda value: value > 0.0,
        ),
        _gate(
            "positive_joint_double_cost_two_slot_compound",
            metrics.get("joint_double_cost_total_return_pct"),
            "> 0%",
            lambda value: value > 0.0,
        ),
        _gate(
            "joint_two_slot_profit_factor",
            metrics.get("joint_account_profit_factor"),
            ">= 1.5",
            lambda value: value >= 1.5,
        ),
        _gate(
            "joint_double_cost_two_slot_profit_factor",
            metrics.get("joint_double_cost_profit_factor"),
            ">= 1.2",
            lambda value: value >= 1.2,
        ),
        _gate(
            "joint_maximum_drawdown",
            metrics.get("joint_account_max_drawdown_pct"),
            ">= -15%",
            lambda value: value >= -15.0,
        ),
        _gate(
            "joint_win_rate_vs_formal_baseline",
            metrics.get("joint_vs_formal_win_rate_delta_pct"),
            ">= 0pct",
            lambda value: value >= 0.0,
        ),
        _gate(
            "joint_compound_vs_formal_baseline",
            metrics.get("joint_vs_formal_total_return_delta_pct"),
            ">= 0pct",
            lambda value: value >= 0.0,
        ),
        _gate(
            "joint_drawdown_vs_formal_baseline",
            metrics.get("joint_vs_formal_max_drawdown_delta_pct"),
            ">= -1pct",
            lambda value: value >= -MAXIMUM_BASELINE_DRAWDOWN_DEGRADATION_PCT,
        ),
        _gate(
            "joint_profit_factor_vs_formal_baseline",
            metrics.get("joint_vs_formal_profit_factor_ratio"),
            ">= 0.95x",
            lambda value: value >= MINIMUM_BASELINE_PROFIT_FACTOR_RATIO,
        ),
        _gate(
            "joint_double_win_rate_vs_formal_baseline",
            metrics.get("joint_double_vs_formal_win_rate_delta_pct"),
            ">= 0pct",
            lambda value: value >= 0.0,
        ),
        _gate(
            "joint_double_compound_vs_formal_baseline",
            metrics.get("joint_double_vs_formal_total_return_delta_pct"),
            ">= 0pct",
            lambda value: value >= 0.0,
        ),
        _gate(
            "joint_double_drawdown_vs_formal_baseline",
            metrics.get("joint_double_vs_formal_max_drawdown_delta_pct"),
            ">= -1pct",
            lambda value: value >= -MAXIMUM_BASELINE_DRAWDOWN_DEGRADATION_PCT,
        ),
        _gate(
            "joint_double_profit_factor_vs_formal_baseline",
            metrics.get("joint_double_vs_formal_profit_factor_ratio"),
            ">= 0.95x",
            lambda value: value >= MINIMUM_BASELINE_PROFIT_FACTOR_RATIO,
        ),
        _gate(
            "chronological_block_count",
            len(metrics.get("chronological_blocks") or []),
            "= 5",
            lambda value: value == 5,
        ),
        _gate(
            "positive_chronological_blocks",
            metrics.get("positive_block_count"),
            ">= 4 of 5",
            lambda value: value >= 4,
        ),
        _gate(
            "joint_chronological_block_count",
            len(metrics.get("joint_chronological_blocks") or []),
            "= 5",
            lambda value: value == 5,
        ),
        _gate(
            "joint_positive_chronological_blocks",
            metrics.get("joint_positive_block_count"),
            ">= 4 of 5",
            lambda value: value >= 4,
        ),
        _gate(
            "maximum_single_day_profit_contribution",
            metrics.get("max_single_day_profit_share_pct"),
            "<= 15%",
            lambda value: value <= 15.0,
        ),
    ]


def _gate(
    name: str,
    current: object,
    requirement: str,
    predicate,
) -> dict[str, object]:
    number = _number(current)
    passed = bool(number is not None and predicate(number))
    return {
        "name": name,
        "current": current,
        "requirement": requirement,
        "passed": passed,
    }


def _hidden_report(
    base: Mapping[str, object],
    status: str,
    message: str,
) -> dict[str, object]:
    return {
        **dict(base),
        "status": status,
        "message": message,
        "performance_visible": False,
        "validation_metrics": None,
        "accounts": None,
        "reliability_gates": None,
    }


def _action_signal(action: Mapping[str, object]) -> dict[str, object] | None:
    if action.get("fill_status") != "filled" or action.get("d1_status") != "closed":
        return None
    entry_date = _as_date(action.get("trade_date"))
    entry_price = _number(action.get("fill_price"))
    fill_at = _as_datetime(action.get("fill_at"))
    symbol = str(action.get("vt_symbol") or "").strip()
    if (
        entry_date is None
        or entry_price is None
        or entry_price <= 0
        or fill_at is None
        or not symbol
    ):
        return None
    return {
        "vt_symbol": symbol,
        "name": action.get("name") or symbol,
        "lane": "first_board",
        "entry_date": entry_date,
        "signal_date": entry_date,
        "buy_time": fill_at.astimezone(SHANGHAI).strftime("%H:%M:%S"),
        "signal_time": fill_at.astimezone(SHANGHAI).strftime("%H:%M:%S"),
        "entry_price": entry_price,
        "limit_price": _number(action.get("limit_price")),
        "rank_score": _number(action.get("action_probability")) or 0.0,
        "point_trigger_action": True,
        "model_fingerprint": action.get("model_fingerprint"),
        "captured_at": action.get("captured_at"),
    }


def _account_config(*, cost_multiplier: float) -> cash_backtest.CashBacktestConfig:
    return cash_backtest.CashBacktestConfig(
        initial_cash=100_000.0,
        max_positions=scheduled_execution.MAX_POSITIONS,
        commission_rate=0.0003 * cost_multiplier,
        minimum_commission=5.0 * cost_multiplier,
        stamp_tax_rate=0.0005 * cost_multiplier,
        transfer_fee_rate=0.00001 * cost_multiplier,
        slippage_bps=10.0 * cost_multiplier,
    )


def _build_account_blocks(
    account: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    validation_dates: Sequence[date | str],
) -> list[dict[str, object]]:
    dates = sorted(
        {
            parsed
            for value in validation_dates
            if (parsed := _as_date(value)) is not None
        }
    )
    if len(dates) != VALIDATION_DAY_COUNT:
        return []
    summary = _mapping(account.get("execution_summary"))
    initial_equity = _number(summary.get("initial_cash"))
    if initial_equity is None or initial_equity <= 0:
        return []
    curve = sorted(
        (
            (trade_date, dict(row))
            for raw in account.get("equity_curve") or []
            if isinstance(raw, Mapping)
            and (row := dict(raw))
            and (trade_date := _as_date(row.get("result_date"))) is not None
            and _number(row.get("total_equity")) is not None
        ),
        key=lambda item: item[0],
    )
    orders = [
        dict(row)
        for row in account.get("orders") or []
        if isinstance(row, Mapping)
    ]
    trades = [
        dict(row)
        for row in account.get("executed_trades") or []
        if isinstance(row, Mapping)
    ]
    block_size = VALIDATION_DAY_COUNT // 5
    blocks: list[dict[str, object]] = []
    previous_equity = initial_equity
    for index in range(5):
        block_dates = dates[index * block_size : (index + 1) * block_size]
        allowed = set(block_dates)
        next_block_start = (
            dates[(index + 1) * block_size] if index < 4 else None
        )
        block_curve = [
            (trade_date, row)
            for trade_date, row in curve
            if trade_date >= block_dates[0]
            and (next_block_start is None or trade_date < next_block_start)
        ]
        end_equity = (
            _number(block_curve[-1][1].get("total_equity"))
            if block_curve
            else previous_equity
        )
        if end_equity is None:
            return []
        total_return = (end_equity / previous_equity - 1.0) * 100.0
        block_signals = [
            signal
            for signal in signals
            if _as_date(signal.get("entry_date") or signal.get("signal_date"))
            in allowed
        ]
        filled_orders = [
            order
            for order in orders
            if order.get("side") == "BUY"
            and order.get("status") == "filled"
            and _as_date(order.get("trade_date")) in allowed
        ]
        block_trades = [
            trade
            for trade in trades
            if _as_date(trade.get("entry_date") or trade.get("buy_date")) in allowed
        ]
        block_pnls = [
            value
            for trade in block_trades
            if (value := _number(trade.get("net_pnl"))) is not None
        ]
        local_equities = [
            previous_equity,
            *(
                value
                for _trade_date, row in block_curve
                if (value := _number(row.get("total_equity"))) is not None
            ),
        ]
        blocks.append(
            {
                "block": index + 1,
                "date_start": block_dates[0],
                "date_end": block_dates[-1],
                "complete_day_count": len(block_dates),
                "equity_date_end": block_curve[-1][0] if block_curve else None,
                "initial_equity": round(previous_equity, 4),
                "final_equity": round(end_equity, 4),
                "signal_count": len(block_signals),
                "filled_count": len(filled_orders),
                "trade_count": len(block_trades),
                "total_return_pct": round(total_return, 6),
                "max_drawdown_pct": _equity_slice_max_drawdown(local_equities),
                "profit_factor": _profit_factor(block_pnls),
                "positive": total_return > 0.0,
            }
        )
        previous_equity = end_equity
    return blocks


def _equity_slice_max_drawdown(equities: Sequence[float]) -> float:
    peak = 0.0
    maximum_drawdown = 0.0
    for equity in equities:
        if equity <= 0:
            continue
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, (equity / peak - 1.0) * 100.0)
    return round(maximum_drawdown, 4)


def _official_account_bars(
    daily_bars: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    indexed: dict[tuple[str, date], dict[str, object]] = {}
    for bar in daily_bars:
        row = dict(bar)
        symbol = str(row.get("vt_symbol") or "").strip()
        trade_date = _as_date(row.get("trade_date"))
        if symbol and trade_date is not None:
            indexed[(symbol, trade_date)] = row
    return sorted(
        indexed.values(),
        key=lambda row: (
            _as_date(row.get("trade_date")) or date.max,
            str(row.get("vt_symbol") or ""),
        ),
    )


def _account_market_data_audit(
    early_signals: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    expected = {
        (str(signal.get("vt_symbol") or ""), trade_date)
        for signal in early_signals
        for field in ("entry_date", "result_date")
        if (trade_date := _as_date(signal.get(field))) is not None
        and str(signal.get("vt_symbol") or "")
    }
    supplied = {
        (str(bar.get("vt_symbol") or ""), trade_date)
        for bar in daily_bars
        if (trade_date := _as_date(bar.get("trade_date"))) is not None
        and str(bar.get("vt_symbol") or "")
        and (_number(bar.get("close_price")) or 0.0) > 0
    }
    covered = expected.intersection(supplied)
    missing = sorted(expected.difference(supplied), key=lambda row: (row[1], row[0]))
    return {
        "expected_early_bar_count": len(expected),
        "supplied_early_bar_count": len(covered),
        "missing_early_bars": [
            {"vt_symbol": symbol, "trade_date": trade_date}
            for symbol, trade_date in missing
        ],
        "complete": bool(expected) and not missing,
    }


def _bind_next_close_dates(
    signals: Sequence[Mapping[str, object]],
    calendar: Sequence[date],
) -> list[dict[str, object]]:
    bound: list[dict[str, object]] = []
    for signal in signals:
        row = dict(signal)
        entry_date = _as_date(row.get("entry_date") or row.get("signal_date"))
        result_date = (
            next(
                (trade_date for trade_date in calendar if trade_date > entry_date),
                None,
            )
            if entry_date is not None
            else None
        )
        if result_date is not None:
            row["result_date"] = result_date
        else:
            row.pop("result_date", None)
            row.pop("exit_date", None)
        bound.append(row)
    return bound


def _official_action_outcome_audit(
    actions: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[date],
) -> dict[str, object]:
    bar_index = {
        (str(bar.get("vt_symbol") or "").strip(), trade_date): dict(bar)
        for bar in daily_bars
        if str(bar.get("vt_symbol") or "").strip()
        and (trade_date := _as_date(bar.get("trade_date"))) is not None
    }
    closed_outcomes: list[dict[str, object]] = []
    mismatches: list[dict[str, object]] = []
    integrity_count = 0
    for action in actions:
        expected = _recompute_official_action_outcome(action, bar_index, calendar)
        if expected is not None and expected["d1_status"] == "closed":
            closed_outcomes.append({**_action_id(action), **expected})
        if expected is not None and _stored_action_outcome_matches(action, expected):
            integrity_count += 1
        else:
            mismatches.append(_action_id(action))
    return {
        "action_count": len(actions),
        "integrity_count": integrity_count,
        "closed_outcome_count": len(closed_outcomes),
        "closed_outcomes": closed_outcomes,
        "mismatched_action_ids": mismatches,
        "complete": integrity_count == len(actions),
    }


def _action_settlement_integrity_audit(
    actions: Sequence[Mapping[str, object]],
    feature_rows: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Replay every mutable settlement stage from separately frozen evidence."""

    bar_index = {
        (str(bar.get("vt_symbol") or "").strip(), trade_date): dict(bar)
        for bar in daily_bars
        if str(bar.get("vt_symbol") or "").strip()
        and (trade_date := _as_date(bar.get("trade_date"))) is not None
    }
    counts = {
        "evidence": 0,
        "delayed_fill": 0,
        "formal_identity": 0,
        "physical_touch": 0,
    }
    mismatches: dict[str, list[dict[str, object]]] = {key: [] for key in counts}
    for action in actions:
        action_id = _action_id(action)
        raw_evidence = action.get("settlement_evidence")
        evidence_intact = False
        if isinstance(raw_evidence, Mapping):
            try:
                evidence_intact = bool(
                    settlement_evidence_matches_action(raw_evidence, action)
                    and str(action.get("settlement_evidence_fingerprint") or "")
                    == point_trigger_settlement_evidence_fingerprint(raw_evidence)
                )
            except (TypeError, ValueError):
                evidence_intact = False
        if evidence_intact:
            counts["evidence"] += 1
        else:
            mismatches["evidence"].append(action_id)

        expected_fill = (
            replay_delayed_fill_outcome(action, raw_evidence)
            if evidence_intact and isinstance(raw_evidence, Mapping)
            else None
        )
        if expected_fill is not None and _stored_stage_matches(
            action,
            expected_fill,
            ("fill_status", "fill_at", "fill_price", "fill_quote_observed_at"),
        ):
            counts["delayed_fill"] += 1
        else:
            mismatches["delayed_fill"].append(action_id)

        expected_identity = replay_formal_identity_outcome(action, feature_rows)
        if expected_identity is not None and _stored_stage_matches(
            action,
            expected_identity,
            (
                "formal_identity_status",
                "formal_event_at",
                "formal_identity_vt_symbol",
                "formal_identity_matched",
            ),
        ):
            counts["formal_identity"] += 1
        else:
            mismatches["formal_identity"].append(action_id)

        action_date = _as_date(action.get("trade_date"))
        symbol = str(action.get("vt_symbol") or "").strip()
        expected_touch = (
            replay_physical_touch_outcome(
                action,
                raw_evidence,
                bar_index.get((symbol, action_date)),
            )
            if evidence_intact
            and isinstance(raw_evidence, Mapping)
            and action_date is not None
            and symbol
            else None
        )
        if expected_touch is not None and _stored_stage_matches(
            action,
            expected_touch,
            ("physical_touch_status", "physical_touch_at", "final_sealed"),
        ):
            counts["physical_touch"] += 1
        else:
            mismatches["physical_touch"].append(action_id)
    return {
        "action_count": len(actions),
        "evidence_integrity_count": counts["evidence"],
        "delayed_fill_integrity_count": counts["delayed_fill"],
        "formal_identity_integrity_count": counts["formal_identity"],
        "physical_touch_integrity_count": counts["physical_touch"],
        "mismatched_action_ids": mismatches,
        "complete": all(value == len(actions) for value in counts.values()),
    }


def _stored_stage_matches(
    action: Mapping[str, object],
    expected: Mapping[str, object],
    fields: Sequence[str],
) -> bool:
    for field in fields:
        actual = action.get(field)
        wanted = expected.get(field)
        if field in {
            "fill_at",
            "fill_quote_observed_at",
            "formal_event_at",
            "physical_touch_at",
        }:
            if _as_datetime(actual) != _as_datetime(wanted):
                return False
        elif field == "fill_price":
            if not _same_number(actual, wanted):
                return False
        elif actual != wanted:
            return False
    return True


def _recompute_official_action_outcome(
    action: Mapping[str, object],
    bar_index: Mapping[tuple[str, date], Mapping[str, object]],
    calendar: Sequence[date],
) -> dict[str, object] | None:
    fill_status = str(action.get("fill_status") or "")
    if fill_status == "queue_unknown_without_l2":
        return {
            "d1_status": "not_filled",
            "d1_trade_date": None,
            "d1_close_price": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "double_cost_net_return_pct": None,
        }
    if fill_status != "filled":
        return None
    action_date = _as_date(action.get("trade_date"))
    symbol = str(action.get("vt_symbol") or "").strip()
    fill_price = _number(action.get("fill_price"))
    if (
        action_date is None
        or action_date not in calendar
        or not symbol
        or fill_price is None
        or fill_price <= 0
    ):
        return None
    expected_d1 = next(
        (trade_date for trade_date in calendar if trade_date > action_date),
        None,
    )
    close_price = _number(
        (bar_index.get((symbol, expected_d1)) or {}).get("close_price")
        if expected_d1 is not None
        else None
    )
    if expected_d1 is None or close_price is None or close_price <= 0:
        return None
    limit_price = _number(action.get("limit_price"))
    normal = radar_validation._execution_outcome(
        fill_price,
        close_price,
        limit_price=limit_price,
        cost_multiplier=1.0,
    )
    stress = radar_validation._execution_outcome(
        fill_price,
        close_price,
        limit_price=limit_price,
        cost_multiplier=2.0,
    )
    if normal is None or stress is None:
        return None
    return {
        "d1_status": "closed",
        "d1_trade_date": expected_d1,
        "d1_close_price": close_price,
        "gross_return_pct": round((close_price / fill_price - 1.0) * 100.0, 4),
        "net_return_pct": normal["net_return_pct"],
        "double_cost_net_return_pct": stress["net_return_pct"],
    }


def _stored_action_outcome_matches(
    action: Mapping[str, object],
    expected: Mapping[str, object],
) -> bool:
    if str(action.get("d1_status") or "") != expected.get("d1_status") or _as_date(
        action.get("d1_trade_date")
    ) != _as_date(expected.get("d1_trade_date")):
        return False
    for field in (
        "d1_close_price",
        "gross_return_pct",
        "net_return_pct",
        "double_cost_net_return_pct",
    ):
        actual = action.get(field)
        wanted = expected.get(field)
        if wanted is None:
            if actual is not None:
                return False
        elif not _same_number(actual, wanted):
            return False
    return True


def _has_settled_action_stages(action: Mapping[str, object]) -> bool:
    fill_status = str(action.get("fill_status") or "")
    formal_status = str(action.get("formal_identity_status") or "")
    physical_status = str(action.get("physical_touch_status") or "")
    if (
        fill_status not in {"filled", "queue_unknown_without_l2"}
        or not formal_status
        or formal_status == "pending"
        or physical_status not in {"touched", "not_touched"}
        or not isinstance(action.get("final_sealed"), bool)
    ):
        return False
    evidence = action.get("settlement_evidence")
    if not isinstance(evidence, Mapping):
        return False
    try:
        evidence_intact = bool(
            settlement_evidence_matches_action(evidence, action)
            and str(action.get("settlement_evidence_fingerprint") or "")
            == point_trigger_settlement_evidence_fingerprint(evidence)
        )
    except (TypeError, ValueError):
        evidence_intact = False
    if not evidence_intact:
        return False
    if physical_status == "not_touched" and (
        action.get("physical_touch_at") is not None
        or action.get("final_sealed") is not False
    ):
        return False
    if fill_status == "filled":
        return bool(
            _as_datetime(action.get("fill_at")) is not None
            and (_number(action.get("fill_price")) or 0.0) > 0
            and action.get("d1_status") == "closed"
        )
    return bool(
        action.get("fill_at") is None
        and action.get("fill_price") is None
        and action.get("d1_status") == "not_filled"
        and all(
            action.get(field) is None
            for field in (
                "d1_trade_date",
                "d1_close_price",
                "gross_return_pct",
                "net_return_pct",
                "double_cost_net_return_pct",
            )
        )
    )


def _account_calendar(
    trade_dates: Sequence[date | str],
) -> list[date]:
    return sorted(
        {parsed for raw in trade_dates if (parsed := _as_date(raw)) is not None}
    )


def _account_profit_contribution_by_date(
    account: Mapping[str, object],
) -> tuple[list[dict[str, object]], float | None]:
    grouped: dict[date, float] = defaultdict(float)
    raw_trades = account.get("executed_trades")
    trades = raw_trades if isinstance(raw_trades, Sequence) else []
    for trade in trades:
        if not isinstance(trade, Mapping):
            continue
        trade_date = _as_date(trade.get("entry_date") or trade.get("buy_date"))
        value = _number(trade.get("net_pnl"))
        if trade_date is not None and value is not None:
            grouped[trade_date] += value
    positive_total = sum(max(value, 0.0) for value in grouped.values())
    rows = [
        {
            "trade_date": trade_date,
            "net_profit": round(value, 4),
            "positive_profit_share_pct": (
                round(max(value, 0.0) / positive_total * 100.0, 4)
                if positive_total > 0
                else None
            ),
        }
        for trade_date, value in sorted(grouped.items())
    ]
    shares = [
        float(row["positive_profit_share_pct"])
        for row in rows
        if row["positive_profit_share_pct"] is not None
    ]
    return rows, max(shares, default=None)


def _formal_event_key(row: Mapping[str, object]) -> tuple[date, datetime, str] | None:
    trade_date = _as_date(row.get("trade_date"))
    event_at = _as_datetime(row.get("formal_event_at"))
    symbol = str(row.get("formal_identity_vt_symbol") or "").strip()
    if trade_date is None or event_at is None or not symbol:
        return None
    return trade_date, event_at, symbol


def _action_stock_day_pair(row: Mapping[str, object]) -> tuple[str, date] | None:
    trade_date = _as_date(row.get("trade_date"))
    symbol = str(row.get("vt_symbol") or "").strip()
    if trade_date is None or not symbol:
        return None
    return symbol, trade_date


def _has_intact_action_decision(action: Mapping[str, object]) -> bool:
    try:
        expected = point_trigger_action_decision_fingerprint(action)
    except (TypeError, ValueError):
        return False
    return str(action.get("decision_fingerprint") or "") == expected


def _action_model_replay_integrity_count(
    actions: Sequence[Mapping[str, object]],
    feature_rows: Sequence[Mapping[str, object]],
    model: Mapping[str, object],
) -> int:
    """Rebuild every saved action from its frozen model and same-frame cohort."""

    action_keys = {
        key for action in actions if (key := _decision_frame_key(action)) is not None
    }
    replay_rows = [
        dict(row) for row in feature_rows if _decision_frame_key(row) in action_keys
    ]
    try:
        scored = score_frozen_point_top1(replay_rows, model)
    except Exception:  # noqa: BLE001 - report integrity must fail closed
        return 0
    scored_by_frame = {
        key: dict(row)
        for row in scored
        if (key := _decision_frame_key(row)) is not None
    }
    candidates_by_frame: dict[tuple[date, datetime, str], list[dict[str, object]]] = (
        defaultdict(list)
    )
    for row in replay_rows:
        key = _decision_frame_key(row)
        if key is not None:
            candidates_by_frame[key].append(row)
    return sum(
        _has_intact_action_model_replay(
            action,
            scored_by_frame,
            candidates_by_frame,
            model,
        )
        for action in actions
    )


def _has_intact_action_model_replay(
    action: Mapping[str, object],
    scored_by_frame: Mapping[tuple[date, datetime, str], Mapping[str, object]],
    candidates_by_frame: Mapping[
        tuple[date, datetime, str], Sequence[Mapping[str, object]]
    ],
    model: Mapping[str, object],
) -> bool:
    key = _decision_frame_key(action)
    expected = scored_by_frame.get(key) if key is not None else None
    candidates = candidates_by_frame.get(key, ()) if key is not None else ()
    payload = _mapping(action.get("decision_payload"))
    threshold = _number(model.get("calibration_threshold"))
    expected_score = _number(
        expected.get(ACTION_SCORE_FIELD) if expected is not None else None
    )
    expected_symbols = sorted(
        {
            str(row.get("vt_symbol") or "").strip()
            for row in candidates
            if str(row.get("vt_symbol") or "").strip()
        }
    )
    payload_symbols = payload.get("eligible_candidate_symbols")
    if not isinstance(payload_symbols, Sequence) or isinstance(
        payload_symbols,
        (str, bytes),
    ):
        return False
    normalized_payload_symbols = [
        str(value).strip() for value in payload_symbols if str(value).strip()
    ]
    if (
        expected is None
        or threshold is None
        or expected_score is None
        or expected_score < threshold
        or str(action.get("model_fingerprint") or "")
        != str(model.get("model_fingerprint") or "")
        or str(action.get("vt_symbol") or "") != str(expected.get("vt_symbol") or "")
        or normalized_payload_symbols != expected_symbols
        or len(normalized_payload_symbols) != len(set(normalized_payload_symbols))
        or payload.get("event_model_fingerprint")
        != model.get("event_model_fingerprint")
        or payload.get("identity_model_fingerprint")
        != model.get("identity_model_fingerprint")
        or payload.get("action_model_fingerprint")
        != model.get("action_model_fingerprint")
        or payload.get("concurrent_formal_two_slot_observed")
        is not expected.get("formal_two_slot_observed")
        or _normalized_two_slot_symbols(
            payload.get("concurrent_formal_two_slot_symbols")
        )
        != _normalized_two_slot_symbols(expected.get("formal_two_slot_symbols"))
        or not _same_number(action.get("action_threshold"), threshold)
        or not _same_number(action.get("action_probability"), expected_score)
        or not _same_number(
            action.get("event_probability"), expected.get(EVENT_SCORE_FIELD)
        )
        or not _same_number(
            action.get("identity_score"), expected.get(IDENTITY_SCORE_FIELD)
        )
        or not _same_number(action.get("top1_margin"), expected.get("top1_margin"))
        or _integer(action.get("candidate_count"))
        != _integer(expected.get("candidate_count"))
        or not _same_number(action.get("last_price"), expected.get("last_price"))
        or not _same_number(action.get("limit_price"), expected.get("limit_price"))
        or _as_datetime(action.get("quote_observed_at"))
        != _as_datetime(expected.get("quote_observed_at"))
        or str(action.get("input_fingerprint") or "")
        != point_trigger_input_fingerprint([expected])
    ):
        return False
    return True


def _decision_frame_key(
    row: Mapping[str, object],
) -> tuple[date, datetime, str] | None:
    trade_date = _as_date(row.get("trade_date"))
    captured_at = _as_datetime(row.get("captured_at"))
    frame_id = str(row.get("frame_id") or "").strip()
    if trade_date is None or captured_at is None or not frame_id:
        return None
    return trade_date, captured_at, frame_id


def _same_number(left: object, right: object) -> bool:
    left_value = _number(left)
    right_value = _number(right)
    return bool(
        left_value is not None
        and right_value is not None
        and abs(left_value - right_value) <= 1e-9
    )


def _has_intact_action_selection(
    actions: Sequence[Mapping[str, object]],
) -> bool:
    day_counts: dict[date, int] = defaultdict(int)
    day_actions: dict[date, list[tuple[datetime, int]]] = defaultdict(list)
    stock_days: set[tuple[date, str]] = set()
    day_slots: set[tuple[date, int]] = set()
    frames: set[tuple[date, str]] = set()
    for action in actions:
        trade_date = _as_date(action.get("trade_date"))
        captured_at = _as_datetime(action.get("captured_at"))
        symbol = str(action.get("vt_symbol") or "").strip()
        frame_id = str(action.get("frame_id") or "").strip()
        daily_slot = _integer(action.get("daily_slot"))
        if (
            trade_date is None
            or captured_at is None
            or not symbol
            or not frame_id
            or daily_slot not in (1, 2)
        ):
            return False
        stock_day = (trade_date, symbol)
        day_slot = (trade_date, daily_slot)
        frame = (trade_date, frame_id)
        if stock_day in stock_days or day_slot in day_slots or frame in frames:
            return False
        stock_days.add(stock_day)
        day_slots.add(day_slot)
        frames.add(frame)
        day_counts[trade_date] += 1
        day_actions[trade_date].append((captured_at, daily_slot))
        if day_counts[trade_date] > 2:
            return False
    return all(
        len({captured_at for captured_at, _slot in rows}) == len(rows)
        and [slot for _captured_at, slot in sorted(rows)]
        == list(range(1, len(rows) + 1))
        for rows in day_actions.values()
    )


def _action_set_replay_metrics(
    actions: Sequence[Mapping[str, object]],
    feature_rows: Sequence[Mapping[str, object]],
    model: Mapping[str, object],
) -> dict[str, int]:
    eligible_rows = [
        dict(row) for row in feature_rows if row.get("action_frame_eligible") is True
    ]
    eligible_frame_keys = {
        key for row in eligible_rows if (key := _decision_frame_key(row)) is not None
    }
    try:
        scored = score_frozen_point_top1(eligible_rows, model)
        expected = select_point_actions(
            scored,
            threshold=_number(model.get("calibration_threshold")),
        )
    except Exception:  # noqa: BLE001 - a reliability report must fail closed
        scored = []
        expected = []
    scored_frame_keys = {
        key for row in scored if (key := _decision_frame_key(row)) is not None
    }
    expected_keys = {
        key for row in expected if (key := _action_replay_key(row)) is not None
    }
    actual_keys = {
        key for row in actions if (key := _action_replay_key(row)) is not None
    }
    exact = bool(
        scored_frame_keys == eligible_frame_keys
        and len(expected_keys) == len(expected)
        and len(actual_keys) == len(actions)
        and expected_keys == actual_keys
    )
    return {
        "action_replay_eligible_frame_count": len(eligible_frame_keys),
        "action_replay_scored_frame_count": len(scored_frame_keys),
        "expected_action_count": len(expected_keys),
        "missing_expected_action_count": len(expected_keys - actual_keys),
        "unexpected_action_count": len(actual_keys - expected_keys),
        "complete_action_set_replay": int(exact),
    }


def _action_replay_key(
    row: Mapping[str, object],
) -> tuple[date, datetime, str, str] | None:
    frame_key = _decision_frame_key(row)
    symbol = str(row.get("vt_symbol") or "").strip()
    if frame_key is None or not symbol:
        return None
    return *frame_key, symbol


def _normalized_two_slot_symbols(value: object) -> list[str] | None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        return None
    symbols = [item.strip() for item in value]
    if len(symbols) > 2 or len(symbols) != len(set(symbols)):
        return None
    return symbols


def _has_intact_model_record(model: Mapping[str, object]) -> bool:
    try:
        expected = point_trigger_model_record_fingerprint(model)
    except (TypeError, ValueError):
        return False
    return str(model.get("record_fingerprint") or "") == expected


def _first_board_account_pairs(
    account: Mapping[str, object],
) -> set[tuple[str, date]]:
    trades = account.get("executed_trades")
    trades = trades if isinstance(trades, Sequence) else []
    return {
        pair
        for trade in trades
        if isinstance(trade, Mapping)
        and str(trade.get("lane") or trade.get("board_lane") or "") == "first_board"
        and (pair := _account_trade_pair(trade)) is not None
    }


def _account_trade_pair(row: Mapping[str, object]) -> tuple[str, date] | None:
    trade_date = _as_date(
        row.get("entry_date") or row.get("buy_date") or row.get("trade_date")
    )
    symbol = str(row.get("vt_symbol") or "").strip()
    if trade_date is None or not symbol:
        return None
    return symbol, trade_date


def _filled_first_board_pairs(
    account: Mapping[str, object],
) -> set[tuple[str, date]]:
    trades = account.get("executed_trades")
    rows = trades if isinstance(trades, Sequence) else []
    return {
        pair
        for trade in rows
        if isinstance(trade, Mapping)
        and str(trade.get("lane") or trade.get("board_lane") or "") == "first_board"
        and (pair := _account_trade_pair(trade)) is not None
    }


def _load_formal_account_inputs(
    validation_dates: Sequence[date],
    actions: Sequence[Mapping[str, object]],
    scopes: Sequence[Mapping[str, object]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[date],
]:
    from alphaagent.server.services.limit_up import history_repository
    from alphaagent.server.services.limit_up.preboard_momentum_data import (
        load_reliable_trade_dates,
    )

    start = min(validation_dates)
    end = max(validation_dates)
    selected_scopes = [
        scope
        for scope in scopes
        if _as_date(scope.get("trade_date")) in set(validation_dates)
        and scope.get("contract_version") == CONTRACT_VERSION
    ]
    formal_orders = _frozen_scope_formal_orders(selected_scopes)
    relays = [
        order
        for order in formal_orders
        if str(order.get("lane") or "") == "two_to_three"
    ]
    symbols = {
        str(row.get("vt_symbol") or "")
        for row in [*actions, *formal_orders]
        if str(row.get("vt_symbol") or "")
    }
    discovery_end = max(end, datetime.now(SHANGHAI).date())
    reliable_dates = load_reliable_trade_dates(start, discovery_end)
    required_dates = {
        next_trade_date
        for entry_date in validation_dates
        if (
            next_trade_date := next(
                (value for value in reliable_dates if value > entry_date),
                None,
            )
        )
        is not None
    }
    load_end = max(required_dates, default=end)
    bars = (
        history_repository.load_account_daily_bars(
            sorted(symbols),
            start,
            load_end,
        )
        if symbols
        else []
    )
    calendar = [value for value in reliable_dates if start <= value <= load_end]
    return formal_orders, relays, bars, calendar


def _frozen_scope_formal_orders(
    scopes: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    orders: list[dict[str, object]] = []
    ordered_scopes = sorted(
        scopes,
        key=lambda scope: _as_date(scope.get("trade_date")) or date.max,
    )
    for scope in ordered_scopes:
        scope_date = _as_date(scope.get("trade_date"))
        raw_orders = scope.get("formal_baseline_orders")
        if (
            scope_date is None
            or scope.get("formal_baseline_order_projection_complete") is not True
            or not isinstance(raw_orders, Sequence)
            or isinstance(raw_orders, (str, bytes))
        ):
            return []
        day_orders = [dict(order) for order in raw_orders if isinstance(order, Mapping)]
        if (
            len(day_orders) != len(raw_orders)
            or len(day_orders) != int(scope.get("formal_baseline_order_count") or 0)
            or _fingerprint(day_orders)
            != str(scope.get("formal_baseline_orders_fingerprint") or "")
            or any(
                _as_date(order.get("entry_date") or order.get("signal_date"))
                != scope_date
                for order in day_orders
            )
        ):
            return []
        orders.extend(day_orders)
    return orders


def _render_markdown(report: Mapping[str, object]) -> str:
    phase = _mapping(report.get("phase"))
    metrics = _mapping(report.get("validation_metrics"))
    gates = report.get("reliability_gates")
    gate_rows = gates if isinstance(gates, Sequence) else []
    lines = [
        "# Limit-up preboard point trigger v9 forward report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Contract: `{report.get('contract_version')}`",
        f"- Model: `{report.get('model_fingerprint')}`",
        f"- Validation cohort: `{phase.get('validation_cohort_id')}`",
        f"- Validation complete days: {phase.get('validation_complete_day_count')}",
        f"- Closed actions: {metrics.get('closed_action_count')}",
        f"- Early account return: {metrics.get('early_account_total_return_pct')}%",
        f"- Early account max drawdown: {metrics.get('early_account_max_drawdown_pct')}%",
        f"- Formal baseline return: {metrics.get('original_formal_total_return_pct')}%",
        f"- Joint vs formal win-rate delta: {metrics.get('joint_vs_formal_win_rate_delta_pct')}pct",
        f"- Joint vs formal return delta: {metrics.get('joint_vs_formal_total_return_delta_pct')}pct",
        f"- Joint vs formal drawdown delta: {metrics.get('joint_vs_formal_max_drawdown_delta_pct')}pct",
        "",
        "| Gate | Current | Requirement | Pass |",
        "| --- | ---: | --- | --- |",
    ]
    for raw in gate_rows:
        gate = _mapping(raw)
        lines.append(
            f"| {gate.get('name')} | {gate.get('current')} | "
            f"{gate.get('requirement')} | {gate.get('passed')} |"
        )
    lines.extend(
        [
            "",
            "The joint account replaces formal first-board orders with point-trigger actions and ",
            "keeps two-to-three orders unchanged. Reliability requires both early first-board ",
            "quality and same-window joint-product non-inferiority to the formal account.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _verify_existing_archive(
    json_path: Path,
    markdown_path: Path,
    expected_fingerprint: object,
    expected_markdown: str,
) -> None:
    fingerprint = str(expected_fingerprint or "")
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PointTriggerArchiveConflict(
                "existing point-trigger JSON archive is unreadable"
            ) from exc
        existing_fingerprint = str(existing.pop("report_fingerprint", ""))
        if (
            not existing_fingerprint
            or existing_fingerprint != _fingerprint(existing)
            or existing_fingerprint != fingerprint
        ):
            raise PointTriggerArchiveConflict(
                "point-trigger JSON archive already contains different evidence"
            )
    if markdown_path.exists():
        try:
            existing_markdown = markdown_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PointTriggerArchiveConflict(
                "existing point-trigger Markdown archive is unreadable"
            ) from exc
        if existing_markdown != expected_markdown:
            raise PointTriggerArchiveConflict(
                "point-trigger Markdown archive already contains different evidence"
            )


def _scope_freeze_sort_key(scope: Mapping[str, object]) -> tuple[str, date, str]:
    trade_date = _as_date(scope.get("trade_date")) or date.max
    frozen_at = _as_datetime(scope.get("frozen_at"))
    fallback = datetime.combine(trade_date, time.min, tzinfo=SHANGHAI)
    return (
        (frozen_at or fallback).astimezone(SHANGHAI).isoformat(),
        trade_date,
        str(scope.get("cohort_fingerprint") or ""),
    )


def _validate_archivable_phase(phase: Mapping[str, object]) -> None:
    fit_dates = _required_date_tuple(phase.get("fit_trade_dates"), "fit_trade_dates")
    calibration_dates = _required_date_tuple(
        phase.get("calibration_trade_dates"),
        "calibration_trade_dates",
    )
    validation_dates = _required_date_tuple(
        phase.get("validation_trade_dates"),
        "validation_trade_dates",
    )
    if (
        len(fit_dates) != FIT_DAY_COUNT
        or len(set(fit_dates)) != FIT_DAY_COUNT
        or fit_dates != tuple(sorted(fit_dates))
        or len(calibration_dates) != CALIBRATION_DAY_COUNT
        or len(set(calibration_dates)) != CALIBRATION_DAY_COUNT
        or calibration_dates != tuple(sorted(calibration_dates))
        or fit_dates[-1] >= calibration_dates[0]
    ):
        raise ValueError("forward report does not contain frozen 40/15 cohorts")
    if (
        len(validation_dates) != VALIDATION_DAY_COUNT
        or len(set(validation_dates)) != VALIDATION_DAY_COUNT
        or validation_dates != tuple(sorted(validation_dates))
        or calibration_dates[-1] >= validation_dates[0]
    ):
        raise ValueError(
            "forward report must contain 60 unique chronological validation dates"
        )
    cohort_id = str(phase.get("validation_cohort_id") or "")
    collection_fingerprint = str(phase.get("validation_collection_fingerprint") or "")
    if (
        int(phase.get("validation_complete_day_count") or 0) != VALIDATION_DAY_COUNT
        or not cohort_id
        or cohort_id != collection_fingerprint
    ):
        raise ValueError("forward report validation cohort is not frozen")


def _required_date_tuple(value: object, field: str) -> tuple[date, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be a date sequence")
    dates = tuple(_as_date(item) for item in value)
    if any(item is None for item in dates):
        raise ValueError(f"{field} contains an invalid date")
    return tuple(item for item in dates if item is not None)


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    return round(gains / losses, 4) if losses > 0 else None


def _ratio_pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 4) if denominator else None


def _wilson_lower_pct(successes: int, trials: int) -> float | None:
    if trials <= 0 or successes < 0 or successes > trials:
        return None
    probability = successes / trials
    z_squared = WILSON_95_Z**2
    denominator = 1.0 + z_squared / trials
    center = probability + z_squared / (2.0 * trials)
    margin = WILSON_95_Z * sqrt(
        probability * (1.0 - probability) / trials + z_squared / (4.0 * trials**2)
    )
    return round(max((center - margin) / denominator, 0.0) * 100.0, 4)


def _action_id(action: Mapping[str, object]) -> dict[str, object]:
    return {
        "trade_date": _as_date(action.get("trade_date")),
        "captured_at": _as_datetime(action.get("captured_at")),
        "vt_symbol": action.get("vt_symbol"),
        "fill_status": action.get("fill_status"),
    }


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _integer(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _metric_delta(
    candidate: Mapping[str, object],
    baseline: Mapping[str, object],
    field: str,
) -> float | None:
    candidate_value = _number(candidate.get(field))
    baseline_value = _number(baseline.get(field))
    if candidate_value is None or baseline_value is None:
        return None
    return round(candidate_value - baseline_value, 4)


def _metric_ratio(
    candidate: Mapping[str, object],
    baseline: Mapping[str, object],
    field: str,
) -> float | None:
    candidate_value = _number(candidate.get(field))
    baseline_value = _number(baseline.get(field))
    if candidate_value is None or baseline_value is None or baseline_value < 0:
        return None
    if baseline_value == 0:
        return 1.0
    return round(candidate_value / baseline_value, 4)


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return _local_datetime(value).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return _local_datetime(parsed)


def _local_datetime(value: datetime) -> datetime:
    return value.astimezone(SHANGHAI)


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
