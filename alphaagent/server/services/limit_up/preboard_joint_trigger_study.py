"""Frozen direct joint-utility study for pre-board first-board actions."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from statistics import mean
from time import monotonic
from zoneinfo import ZoneInfo

import pandas as pd

from alphaagent.server.services.limit_up import history_repository
from alphaagent.server.services.limit_up import preboard_competing_risk_study as legacy
from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    ACTION_SCORE_FIELD as LEGACY_ACTION_SCORE_FIELD,
    attach_competing_risk_targets,
    enrich_same_minute_competition,
    select_confirmed_competing_signals,
)
from alphaagent.server.services.limit_up.preboard_competing_risk_study import (
    _account_replay,
)
from alphaagent.server.services.limit_up.preboard_hazard_data import (
    load_one_minute_bars,
    load_one_minute_coverage,
    load_static_hazard_manifest,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    ACTION_SCORE_FIELD,
    ACTION_TARGET_FIELD,
    PREPARE_SCORE_FIELD,
    PREPARE_TARGET_FIELD,
    JointThresholdSelection,
    JointTriggerModelFit,
    attach_joint_trigger_targets,
    calibrate_joint_threshold,
    fit_joint_trigger_model,
    probability_calibration_report,
    score_joint_trigger_rows,
)
from alphaagent.server.services.limit_up.preboard_strategy_study import _early_order
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


STUDY_VERSION = "limit-up-preboard-joint-trigger-v3"
DEFAULT_SESSION_COUNT = 89
CONFIRMATION_MINUTES = 2
MAX_DAILY_FIRST_BOARD_ACTIONS = 2
MINIMUM_EXACT_COVERAGE_PCT = 100.0
MINIMUM_CALIBRATION_SELECTIONS = 10
FORWARD_MINIMUM_TRADE_DAYS = 60
FORWARD_MINIMUM_CLOSED_ACTIONS = 300
FORWARD_MINIMUM_REVIEW_ACTIONS = 30
FORWARD_EVENT_SAMPLE_LIMIT = 100
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def build_joint_trigger_analysis(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
    baseline_parity: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, JointTriggerModelFit]]:
    """Fit frozen direct models and replay the joint action policy."""

    identity_labeled = attach_competing_risk_targets(prefix_rows, formal_orders)
    joint_labeled = attach_joint_trigger_targets(identity_labeled, formal_orders)
    enriched_rows = enrich_same_minute_competition(joint_labeled)
    prepare_model = fit_joint_trigger_model(
        enriched_rows,
        fit_dates=fit_dates,
        target_field=PREPARE_TARGET_FIELD,
    )
    action_model = fit_joint_trigger_model(
        enriched_rows,
        fit_dates=fit_dates,
        target_field=ACTION_TARGET_FIELD,
    )
    prepare_rows = score_joint_trigger_rows(
        enriched_rows,
        prepare_model,
        score_field=PREPARE_SCORE_FIELD,
    )
    action_rows = score_joint_trigger_rows(enriched_rows, action_model)
    threshold = calibrate_joint_threshold(
        action_rows,
        calibration_dates=calibration_dates,
        minimum_selection_count=MINIMUM_CALIBRATION_SELECTIONS,
        confirmation_minutes=CONFIRMATION_MINUTES,
        max_daily_actions=MAX_DAILY_FIRST_BOARD_ACTIONS,
    )
    action_threshold = threshold.threshold if threshold.threshold is not None else 1.1
    normal_bundle = build_joint_replay_orders(
        action_rows=action_rows,
        formal_orders=formal_orders,
        action_threshold=action_threshold,
    )
    conservative_bundle = build_joint_replay_orders(
        action_rows=action_rows,
        formal_orders=formal_orders,
        action_threshold=action_threshold,
        conservative_entry=True,
    )
    diagnostic_observations = _legacy_score_alias(enriched_rows)
    diagnostic_scores = _legacy_score_alias(action_rows)
    diagnostic_signals = _legacy_score_alias(normal_bundle["action_signals"])

    all_dates = fit_dates | calibration_dates | validation_dates
    phase_dates = {"full": all_dates, "validation": validation_dates}
    phases: dict[str, dict[str, object]] = {}
    for phase, allowed_dates in phase_dates.items():
        phases[phase] = _phase_report(
            enriched_rows=enriched_rows,
            formal_orders=formal_orders,
            action_signals=normal_bundle["action_signals"],
            action_orders=normal_bundle["combined_orders"],
            conservative_orders=conservative_bundle["combined_orders"],
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
            diagnostic_observations=diagnostic_observations,
            diagnostic_scores=diagnostic_scores,
            diagnostic_signals=diagnostic_signals,
            action_threshold=action_threshold,
        )

    validation_blocks: list[dict[str, object]] = []
    for index, block_dates in enumerate(
        legacy._fixed_validation_blocks(validation_dates),
        start=1,
    ):
        block_set = set(block_dates)
        phase = _phase_report(
            enriched_rows=enriched_rows,
            formal_orders=formal_orders,
            action_signals=normal_bundle["action_signals"],
            action_orders=normal_bundle["combined_orders"],
            conservative_orders=conservative_bundle["combined_orders"],
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=block_set,
            diagnostic_observations=(),
            diagnostic_scores=(),
            diagnostic_signals=(),
            action_threshold=action_threshold,
            include_attribution=False,
        )
        validation_blocks.append(
            {
                "block": index,
                "date_range": legacy._date_range(block_dates),
                **phase,
            }
        )

    validation = _mapping(phases.get("validation"))
    acceptance = _acceptance_report(
        validation,
        validation_blocks=validation_blocks,
        models=(prepare_model, action_model),
        threshold=threshold,
        baseline_parity=baseline_parity,
    )
    return {
        "dataset": legacy._dataset_report(enriched_rows),
        "models": {
            "prepare_5m": _model_report(prepare_model),
            "joint_action_3m": _model_report(action_model),
        },
        "threshold_selection": _threshold_report(threshold),
        "probability_calibration": {
            "calibration": probability_calibration_report(
                action_rows,
                allowed_dates=calibration_dates,
            ),
            "validation": probability_calibration_report(
                action_rows,
                allowed_dates=validation_dates,
            ),
        },
        "prepare_score_count": len(prepare_rows),
        "phases": phases,
        "validation_blocks": validation_blocks,
        "signal_counts": {
            "action": len(normal_bundle["action_signals"]),
            "fillable_action": len(normal_bundle["early_orders"]),
        },
        "acceptance": acceptance,
        "decision": (
            "historical_pass_forward_shadow_only"
            if acceptance["passed"] is True
            else "historical_rejected_no_live_promotion"
        ),
    }, {"prepare_5m": prepare_model, "joint_action_3m": action_model}


def evaluate_preboard_joint_trigger(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
) -> dict[str, object]:
    """Load the frozen 89-session scope and evaluate the v3 contract."""

    started = monotonic()
    timings: dict[str, float] = {}
    checkpoint = started

    manifest = load_static_hazard_manifest(session_count=session_count)
    checkpoint = _record_timing(timings, "manifest_seconds", checkpoint)
    if manifest.empty:
        return _blocked_report("blocked_by_manifest", session_count, timings)
    coverage = load_one_minute_coverage(manifest)
    coverage_report = legacy._coverage_report(manifest, coverage)
    checkpoint = _record_timing(timings, "coverage_seconds", checkpoint)
    if float(coverage_report["complete_pair_pct"]) < MINIMUM_EXACT_COVERAGE_PCT:
        return {
            **_blocked_report("blocked_by_one_minute_coverage", session_count, timings),
            "coverage": coverage_report,
            "next_data_task": "sync_limit_up_preboard_hazard_minutes",
        }

    dates = sorted(pd.to_datetime(manifest["trade_date"]).dt.date.unique())
    fit_dates, calibration_dates, validation_dates = legacy.split_competing_dates(dates)
    if (
        len(fit_dates) != legacy.FIT_SESSION_COUNT
        or len(calibration_dates) != legacy.CALIBRATION_SESSION_COUNT
        or len(validation_dates) != legacy.VALIDATION_SESSION_COUNT
    ):
        return {
            **_blocked_report("blocked_by_frozen_date_split", session_count, timings),
            "coverage": coverage_report,
            "date_split": legacy._date_split_report(
                fit_dates,
                calibration_dates,
                validation_dates,
            ),
        }

    start, end = dates[0], dates[-1]
    history_days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end,
        False,
    )
    scoped_history_days = [
        day
        for day in history_days
        if start <= (legacy._optional_date(day.get("trade_date")) or date.min) <= end
    ]
    checkpoint = _record_timing(timings, "history_seconds", checkpoint)
    complete_pairs = {
        (str(row.vt_symbol), legacy._as_date(row.trade_date))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    minute_rows = load_one_minute_bars(manifest)
    daily_consistency = legacy.audit_minute_daily_consistency(manifest, minute_rows)
    checkpoint = _record_timing(timings, "minute_load_audit_seconds", checkpoint)
    if float(daily_consistency["ready_pair_pct"]) < 99.5:
        return {
            **_blocked_report("blocked_by_minute_daily_inconsistency", session_count, timings),
            "coverage": coverage_report,
            "minute_daily_consistency": daily_consistency,
        }

    feature_frame, feature_coverage = legacy._load_bounded_feature_frame(
        manifest,
        lookback_sessions=legacy.FEATURE_LOOKBACK_SESSIONS,
    )
    feature_by_pair = legacy._feature_index(feature_frame, set(dates))
    financial_index = legacy._load_financial_index()
    checkpoint = _record_timing(timings, "feature_seconds", checkpoint)
    prefix_rows, filter_audit = legacy._build_all_strategy_prefix_rows(
        manifest,
        minute_rows,
        complete_pairs,
        feature_by_pair,
        financial_index,
        bar_minutes=1,
        passed_only=True,
        row_projection=legacy._project_competing_row,
    )
    checkpoint = _record_timing(timings, "prefix_build_seconds", checkpoint)
    formal_orders, profitability_audit = legacy._formal_orders(
        history_days,
        scoped_history_days,
        start,
        end,
    )
    symbols = sorted(
        {
            *manifest["vt_symbol"].astype(str).tolist(),
            *(
                str(order.get("vt_symbol") or "")
                for order in formal_orders
                if order.get("vt_symbol")
            ),
        }
    )
    result_dates = [
        parsed
        for value in manifest.get("result_date", [])
        if (parsed := legacy._optional_date(value)) is not None
    ]
    result_dates.extend(
        parsed
        for order in formal_orders
        if (parsed := legacy._optional_date(order.get("result_date"))) is not None
    )
    account_end = max(result_dates, default=end)
    bars = history_repository.load_account_daily_bars(symbols, start, account_end)
    from alphaagent.server.services.limit_up.preboard_momentum_data import (
        load_reliable_trade_dates,
    )

    trade_dates = load_reliable_trade_dates(start, account_end)
    checkpoint = _record_timing(timings, "account_data_seconds", checkpoint)
    from alphaagent.server.services.limit_up.history_service import (
        get_scheduled_history_backtest,
    )

    service_baseline = get_scheduled_history_backtest(start, end, trade_limit=None)
    baseline_summary = legacy._account_summary(
        formal_orders,
        bars,
        trade_dates,
        cost_multiplier=1.0,
    )
    baseline_parity = legacy.compare_baseline_summaries(
        _mapping(service_baseline.get("summary")),
        baseline_summary,
    )
    checkpoint = _record_timing(timings, "baseline_seconds", checkpoint)
    if baseline_parity.get("passed") is not True:
        return {
            **_blocked_report("blocked_by_baseline_mismatch", session_count, timings),
            "coverage": {**coverage_report, **feature_coverage},
            "baseline_parity": baseline_parity,
        }

    analysis, models = build_joint_trigger_analysis(
        prefix_rows,
        formal_orders,
        bars,
        trade_dates,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
        baseline_parity=baseline_parity,
    )
    _record_timing(timings, "model_and_replay_seconds", checkpoint)
    timings["total_seconds"] = round(monotonic() - started, 3)
    date_split = {
        phase: {
            **legacy._date_range(values),
            "dates": [value.isoformat() for value in values],
        }
        for phase, values in (
            ("fit", fit_dates),
            ("calibration", calibration_dates),
            ("validation", validation_dates),
        )
    }
    research_fingerprints = build_research_fingerprints(
        date_split=date_split,
        models=_mapping(analysis.get("models")),
        threshold_selection=_mapping(analysis.get("threshold_selection")),
    )
    return {
        "study_version": STUDY_VERSION,
        "status": (
            "ready_historical_pass"
            if _mapping(analysis.get("acceptance")).get("passed") is True
            else "ready_historical_rejected"
        ),
        "formal_strategy_changed": False,
        "historical_validation_kind": "viewed_expanded_historical_time_validation",
        "contract": {
            "observation_gain_operator": ">=",
            "observation_gain_pct": 3.0,
            "prepare_target": PREPARE_TARGET_FIELD,
            "action_target": ACTION_TARGET_FIELD,
            "action_score": ACTION_SCORE_FIELD,
            "confirmation_minutes": CONFIRMATION_MINUTES,
            "maximum_daily_first_board_actions": MAX_DAILY_FIRST_BOARD_ACTIONS,
            "entry": "next_one_minute_open_strictly_below_limit",
            "exit": "d1_official_close",
            "execution_effect": "none_research_only",
        },
        "date_split": date_split,
        "research_fingerprints": research_fingerprints,
        "performance": timings,
        "coverage": {**coverage_report, **feature_coverage},
        "minute_daily_consistency": daily_consistency,
        "filter_audit": filter_audit,
        "formal_profitability_filter": profitability_audit,
        "baseline_parity": baseline_parity,
        **analysis,
        "forward_validation": _forward_validation_report(
            models,
            _number(
                _mapping(analysis.get("threshold_selection")).get("threshold")
            ),
        ),
        "limitations": [
            "89日中的后30日已被此前研究查看，只能称扩展历史时间反证，不是新的锁定留出。",
            "TDX一分钟K线不是Tick/L2，不能证明主动大单方向、排队、撤单或秒级成交。",
            "历史没有完整点时动态概念、行业扩散、资金流和快照新鲜度，这些字段只允许前向保存。",
            "历史门通过也只允许冻结前向影子；正式v9/v15保持不变。",
        ],
    }


def build_joint_replay_orders(
    *,
    action_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_threshold: float,
    conservative_entry: bool = False,
) -> dict[str, list[dict[str, object]]]:
    """Build joint first-board orders beside unchanged two-to-three orders."""

    action_signals = select_confirmed_competing_signals(
        action_rows,
        threshold=float(action_threshold),
        score_field=ACTION_SCORE_FIELD,
        confirmation_minutes=CONFIRMATION_MINUTES,
        max_daily_actions=MAX_DAILY_FIRST_BOARD_ACTIONS,
    )
    early_orders = [
        order
        for signal in action_signals
        if (
            order := _joint_order(
                signal,
                conservative_entry=conservative_entry,
            )
        )
        is not None
    ]
    relay_orders = [
        dict(order)
        for order in formal_orders
        if str(order.get("lane") or "") == "two_to_three"
    ]
    return {
        "action_signals": action_signals,
        "early_orders": early_orders,
        "relay_orders": relay_orders,
        "combined_orders": [*relay_orders, *early_orders],
    }


def replay_joint_account(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    cost_multiplier: float = 1.0,
) -> dict[str, object]:
    """Replay joint orders through the unchanged formal cash account."""

    return _account_replay(
        orders,
        bars,
        trade_dates,
        cost_multiplier=cost_multiplier,
    )


def _phase_report(
    *,
    enriched_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_signals: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
    diagnostic_observations: Sequence[Mapping[str, object]],
    diagnostic_scores: Sequence[Mapping[str, object]],
    diagnostic_signals: Sequence[Mapping[str, object]],
    action_threshold: float,
    include_attribution: bool = True,
) -> dict[str, object]:
    report = {
        "identity": legacy._identity_report(
            enriched_rows,
            formal_orders,
            action_signals,
            allowed_dates=allowed_dates,
        ),
        "joint_quality": _joint_signal_report(
            action_signals,
            allowed_dates=allowed_dates,
        ),
        "accounts": _phase_accounts(
            formal_orders=formal_orders,
            action_orders=action_orders,
            conservative_orders=conservative_orders,
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
        ),
        "account_identity": legacy._account_identity_report(
            formal_orders=formal_orders,
            action_orders=action_orders,
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
        ),
    }
    if include_attribution:
        report["account_path_attribution"] = legacy.build_account_path_attribution(
            formal_orders=formal_orders,
            action_orders=action_orders,
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
            observation_rows=diagnostic_observations,
            scored_rows=diagnostic_scores,
            selected_signals=diagnostic_signals,
            action_threshold=action_threshold,
        )
    return report


def _phase_accounts(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
) -> dict[str, object]:
    formal = legacy._orders_on_dates(formal_orders, allowed_dates)
    action = legacy._orders_on_dates(action_orders, allowed_dates)
    conservative = legacy._orders_on_dates(conservative_orders, allowed_dates)
    relay = [order for order in formal if str(order.get("lane") or "") == "two_to_three"]
    early = [
        order
        for order in action
        if str(order.get("algorithm") or "") == "profitable_formal_touch_3m"
    ]
    return {
        "formal_touch": legacy._account_metrics(formal, bars, trade_dates),
        "two_to_three_only": legacy._account_metrics(relay, bars, trade_dates),
        "early_first_board_only": legacy._account_metrics(early, bars, trade_dates),
        "joint_action": legacy._account_metrics(action, bars, trade_dates),
        "joint_action_double_cost": legacy._account_metrics(
            action,
            bars,
            trade_dates,
            cost_multiplier=2.0,
        ),
        "joint_action_conservative": legacy._account_metrics(
            conservative,
            bars,
            trade_dates,
        ),
    }


def _joint_signal_report(
    signals: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> dict[str, object]:
    selected = [
        row
        for row in signals
        if legacy._order_date(row) in allowed_dates
    ]
    joint_true = [row for row in selected if row.get(ACTION_TARGET_FIELD) is True]
    returns = [
        value
        for row in selected
        if (value := _number(row.get("net_return_pct"))) is not None
    ]
    return {
        "selection_count": len(selected),
        "joint_true_positive_count": len(joint_true),
        "joint_precision_pct": _percentage(len(joint_true), len(selected)),
        "d1_closed_count": len(returns),
        "d1_win_rate_pct": _percentage(
            sum(value > 0 for value in returns),
            len(returns),
        ),
        "d1_average_return_pct": round(mean(returns), 4) if returns else None,
    }


def _legacy_score_alias(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            **dict(row),
            LEGACY_ACTION_SCORE_FIELD: row.get(ACTION_SCORE_FIELD),
        }
        for row in rows
    ]


def _model_report(model: JointTriggerModelFit) -> dict[str, object]:
    return {
        "status": model.status,
        "target_field": model.target_field,
        "features": list(legacy.COMPETING_FEATURE_NAMES),
        "training_row_count": model.training_row_count,
        "training_pair_count": model.training_pair_count,
        "class_counts": dict(model.class_counts),
        "fit_dates": list(model.fit_dates),
        "scaler_mean_by_feature": dict(model.scaler_mean_by_feature),
        "scaler_scale_by_feature": dict(model.scaler_scale_by_feature),
        "coefficient_by_feature": dict(model.coefficient_by_feature),
        "intercept": model.intercept,
        "fingerprint": model.fingerprint,
    }


def _threshold_report(selection: JointThresholdSelection) -> dict[str, object]:
    return {
        "status": selection.status,
        "threshold": selection.threshold,
        "calibration_dates": list(selection.calibration_dates),
        "minimum_selection_count": selection.minimum_selection_count,
        "selected_metrics": dict(selection.selected_metrics),
        "metrics_by_threshold": [dict(row) for row in selection.metrics_by_threshold],
    }


def _forward_validation_report(
    models: Mapping[str, JointTriggerModelFit],
    threshold: float | None,
) -> dict[str, object]:
    from alphaagent.server.services.limit_up import radar_observation_repository

    coverage = radar_observation_repository.load_frame_coverage()
    base = {
        "status": "collecting_forward_overlay",
        "trade_day_count": int(coverage.get("trade_day_count") or 0),
        "frame_count": int(coverage.get("frame_count") or 0),
        "observation_count": int(coverage.get("observation_count") or 0),
        "closed_action_event_count": 0,
        "ready_for_review": False,
        "models_ready": all(model.status == "ready" for model in models.values()),
        "historical_action_threshold": threshold,
        "review_gate": {
            "minimum_trade_days": FORWARD_MINIMUM_TRADE_DAYS,
            "alternative_closed_actions": FORWARD_MINIMUM_CLOSED_ACTIONS,
            "minimum_closed_actions_for_review": FORWARD_MINIMUM_REVIEW_ACTIONS,
        },
        "execution_effect": "none_research_only",
    }
    prepare_model = models.get("prepare_5m")
    action_model = models.get("joint_action_3m")
    if (
        prepare_model is None
        or action_model is None
        or prepare_model.status != "ready"
        or action_model.status != "ready"
        or threshold is None
        or int(coverage.get("trade_day_count") or 0) == 0
    ):
        return {
            **base,
            "scoreable_observation_count": 0,
            "research_prepare_count": 0,
            "research_action_count": 0,
            "action_event_count": 0,
            "dynamic_overlay": _forward_dynamic_overlay((), ()),
            "note": "尚无可连接的新鲜同源雷达帧，或冻结模型/阈值未就绪。",
        }

    from alphaagent.server.services.limit_up.preboard_hazard_data import (
        load_one_minute_bars,
    )
    from alphaagent.server.services.limit_up.preboard_hazard_study import (
        build_forward_overlay_rows,
    )
    from alphaagent.server.services.limit_up.preboard_momentum_data import (
        load_reliable_trade_dates,
    )

    frame_dates = radar_observation_repository.load_frame_dates()
    observations = radar_observation_repository.load_observations(
        min(frame_dates),
        max(frame_dates),
    )
    pairs = pd.DataFrame(
        [
            {
                "vt_symbol": str(row.get("vt_symbol") or ""),
                "trade_date": legacy._as_date(row.get("trade_date")),
            }
            for row in observations
            if row.get("vt_symbol")
            and legacy._as_date(row.get("trade_date")) != date.min
        ]
    ).drop_duplicates()
    minute_rows = load_one_minute_bars(pairs) if not pairs.empty else pd.DataFrame()
    overlay_rows = build_forward_overlay_rows(observations, minute_rows)
    symbols = sorted(pairs["vt_symbol"].astype(str).unique()) if not pairs.empty else []
    settlement_end = date.today()
    daily_bars = (
        history_repository.load_account_daily_bars(
            symbols,
            min(frame_dates),
            settlement_end,
        )
        if symbols
        else []
    )
    shadow = build_forward_joint_shadow(
        overlay_rows,
        models=models,
        action_threshold=threshold,
        daily_bars=daily_bars,
        trade_dates=load_reliable_trade_dates(min(frame_dates), settlement_end),
    )
    return {**base, **shadow}


def prepare_forward_joint_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    maximum_quote_age_seconds: float = 60.0,
) -> list[dict[str, object]]:
    """Keep only fresh rows whose completed minute reaches the frame minute."""

    aligned: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        captured_at = legacy._optional_datetime(row.get("captured_at"))
        signal_at = legacy._optional_datetime(row.get("signal_at"))
        quote_at = legacy._optional_datetime(row.get("quote_observed_at"))
        if captured_at is None or signal_at is None or quote_at is None:
            continue
        captured_minute = _local_minute(captured_at)
        signal_minute = _local_minute(signal_at)
        if captured_minute != signal_minute:
            continue
        try:
            quote_age = (captured_at - quote_at).total_seconds()
        except TypeError:
            continue
        row["quote_age_seconds"] = round(float(quote_age), 4)
        aligned.append(row)
    return legacy.prepare_forward_competing_rows(
        aligned,
        maximum_quote_age_seconds=maximum_quote_age_seconds,
    )


def build_forward_joint_shadow(
    overlay_rows: Sequence[Mapping[str, object]],
    *,
    models: Mapping[str, JointTriggerModelFit],
    action_threshold: float,
    daily_bars: Sequence[Mapping[str, object]] = (),
    trade_dates: Sequence[date] = (),
) -> dict[str, object]:
    """Score frozen v3 models and emit research-only prepare/action states."""

    from alphaagent.server.services.limit_up import radar_validation
    from alphaagent.server.services.limit_up.preboard_hazard_study import (
        settle_forward_actions,
    )

    prepare_model = models.get("prepare_5m")
    action_model = models.get("joint_action_3m")
    if (
        prepare_model is None
        or action_model is None
        or prepare_model.status != "ready"
        or action_model.status != "ready"
    ):
        return {
            "scoreable_observation_count": 0,
            "research_prepare_count": 0,
            "research_action_count": 0,
            "action_event_count": 0,
            "closed_action_event_count": 0,
            "ready_for_review": False,
            "execution_effect": radar_validation.RESEARCH_EXECUTION_EFFECT,
        }

    prepared = prepare_forward_joint_rows(overlay_rows)
    prepare_scored = score_joint_trigger_rows(
        prepared,
        prepare_model,
        score_field=PREPARE_SCORE_FIELD,
    )
    scored = score_joint_trigger_rows(prepare_scored, action_model)
    actions = select_confirmed_competing_signals(
        scored,
        threshold=float(action_threshold),
        score_field=ACTION_SCORE_FIELD,
        confirmation_minutes=CONFIRMATION_MINUTES,
        max_daily_actions=MAX_DAILY_FIRST_BOARD_ACTIONS,
    )
    action_keys = {_forward_signal_key(row) for row in actions}
    events = [
        radar_validation.build_read_only_research_event(
            row,
            state=(
                radar_validation.RESEARCH_ACTION_STATE
                if _forward_signal_key(row) in action_keys
                else radar_validation.RESEARCH_PREPARE_STATE
            ),
            prepare_score_field=PREPARE_SCORE_FIELD,
            action_score_field=ACTION_SCORE_FIELD,
        )
        for row in scored
    ]
    settled = (
        settle_forward_actions(actions, daily_bars, trade_dates)
        if daily_bars and trade_dates
        else []
    )
    returns = [
        value
        for row in settled
        if (value := _number(row.get("net_return_pct"))) is not None
    ]
    trade_day_count = len(
        {
            legacy._order_date(row)
            for row in scored
            if legacy._order_date(row) != date.min
        }
    )
    ready_for_review = (
        (
            trade_day_count >= FORWARD_MINIMUM_TRADE_DAYS
            or len(settled) >= FORWARD_MINIMUM_CLOSED_ACTIONS
        )
        and len(settled) >= FORWARD_MINIMUM_REVIEW_ACTIONS
    )
    return {
        "status": "ready_for_review" if ready_for_review else "collecting_forward_overlay",
        "scoreable_observation_count": len(scored),
        "scoreable_stock_day_count": len(
            {legacy._order_pair(row) for row in scored}
        ),
        "research_prepare_count": len(events) - len(actions),
        "research_action_count": len(actions),
        "action_event_count": len(actions),
        "closed_action_event_count": len(settled),
        "closed_action_win_rate_pct": _percentage(
            sum(value > 0 for value in returns),
            len(returns),
        ),
        "closed_action_average_return_pct": (
            round(mean(returns), 4) if returns else None
        ),
        "recent_research_events": events[-FORWARD_EVENT_SAMPLE_LIMIT:],
        "dynamic_overlay": _forward_dynamic_overlay(actions, settled),
        "ready_for_review": ready_for_review,
        "execution_effect": radar_validation.RESEARCH_EXECUTION_EFFECT,
        "note": "动态字段只做前向分层；research_prepare/research_action均不可执行。",
    }


def _forward_dynamic_overlay(
    actions: Sequence[Mapping[str, object]],
    settled: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    numeric_fields = (
        "concept_change_acceleration_1m",
        "concept_change_acceleration_3m",
        "concept_change_acceleration_5m",
        "concept_turnover_acceleration_1m",
        "concept_turnover_acceleration_3m",
        "concept_turnover_acceleration_5m",
        "sector_main_net_inflow",
        "stock_main_net_inflow",
        "active_candidate_count_log1p",
        "quote_age_seconds",
    )
    return {
        "action_count": len(actions),
        "numeric_fields": {
            field: _numeric_overlay_field(actions, settled, field)
            for field in numeric_fields
        },
        "market_timing_state": _categorical_overlay_field(
            actions,
            settled,
            "market_timing_state",
        ),
    }


def _numeric_overlay_field(
    actions: Sequence[Mapping[str, object]],
    settled: Sequence[Mapping[str, object]],
    field: str,
) -> dict[str, object]:
    action_values = [
        value
        for row in actions
        if (value := legacy._feature_number(row, field)) is not None
    ]
    closed_rows = [
        row
        for row in settled
        if legacy._feature_number(row, field) is not None
        and _number(row.get("net_return_pct")) is not None
    ]
    returns = [float(row["net_return_pct"]) for row in closed_rows]
    return {
        "coverage_count": len(action_values),
        "coverage_pct": _percentage(len(action_values), len(actions)),
        "average": round(mean(action_values), 4) if action_values else None,
        "closed_count": len(returns),
        "closed_win_rate_pct": _percentage(
            sum(value > 0 for value in returns),
            len(returns),
        ),
        "closed_average_return_pct": round(mean(returns), 4) if returns else None,
    }


def _categorical_overlay_field(
    actions: Sequence[Mapping[str, object]],
    settled: Sequence[Mapping[str, object]],
    field: str,
) -> dict[str, object]:
    action_counts = Counter(
        str(row.get(field) or "missing")
        for row in actions
    )
    settled_groups: dict[str, list[float]] = {}
    for row in settled:
        value = _number(row.get("net_return_pct"))
        if value is None:
            continue
        settled_groups.setdefault(str(row.get(field) or "missing"), []).append(value)
    return {
        "coverage_count": sum(
            count for key, count in action_counts.items() if key != "missing"
        ),
        "action_counts": dict(sorted(action_counts.items())),
        "closed_results": {
            key: {
                "count": len(values),
                "win_rate_pct": _percentage(
                    sum(value > 0 for value in values),
                    len(values),
                ),
                "average_return_pct": round(mean(values), 4),
            }
            for key, values in sorted(settled_groups.items())
        },
    }


def _local_minute(value: datetime) -> tuple[str, str]:
    local = value.astimezone(_SHANGHAI) if value.tzinfo is not None else value
    return local.date().isoformat(), local.strftime("%H:%M")


def _forward_signal_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("signal_date") or "")[:10],
        str(row.get("signal_time") or "")[:5],
        str(row.get("vt_symbol") or ""),
    )


def _record_timing(
    timings: dict[str, float],
    field: str,
    started: float,
) -> float:
    now = monotonic()
    timings[field] = round(now - started, 3)
    return now


def build_research_fingerprints(
    *,
    date_split: Mapping[str, object],
    models: Mapping[str, object],
    threshold_selection: Mapping[str, object],
    action_model_key: str = "joint_action_3m",
    confirmation_minutes: int = CONFIRMATION_MINUTES,
) -> dict[str, str]:
    """Fingerprint the frozen chronological scope and executable action policy."""

    date_payload = {
        phase: _mapping(date_split.get(phase))
        for phase in ("fit", "calibration", "validation")
    }
    action_model = _mapping(models.get(action_model_key))
    threshold_payload = {
        "action_model_fingerprint": action_model.get("fingerprint"),
        "threshold": threshold_selection.get("threshold"),
        "calibration_dates": list(
            threshold_selection.get("calibration_dates") or []
        ),
        "confirmation_minutes": int(confirmation_minutes),
        "maximum_daily_first_board_actions": MAX_DAILY_FIRST_BOARD_ACTIONS,
    }
    return {
        "date_split": _stable_fingerprint(date_payload),
        "action_policy": _stable_fingerprint(threshold_payload),
    }


def _stable_fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _blocked_report(
    status: str,
    session_count: int,
    timings: Mapping[str, float],
) -> dict[str, object]:
    return {
        "study_version": STUDY_VERSION,
        "status": status,
        "decision": "blocked_no_conclusion",
        "formal_strategy_changed": False,
        "requested_session_count": int(session_count),
        "performance": dict(timings),
    }


def _acceptance_report(
    validation: Mapping[str, object],
    *,
    validation_blocks: Sequence[Mapping[str, object]],
    models: Sequence[object],
    threshold: object,
    baseline_parity: Mapping[str, object],
) -> dict[str, object]:
    identity = _mapping(validation.get("identity"))
    account_identity = _mapping(validation.get("account_identity"))
    accounts = _mapping(validation.get("accounts"))
    formal = _mapping(accounts.get("formal_touch"))
    action = _mapping(accounts.get("joint_action"))
    double_cost = _mapping(accounts.get("joint_action_double_cost"))
    positive_blocks = sum(
        (_number(account.get("trade_count")) or 0) > 0
        and (_number(account.get("total_return_pct")) or 0) > 0
        for block in validation_blocks
        if (
            account := _mapping(
                _mapping(block.get("accounts")).get("joint_action")
            )
        )
    )
    checks = {
        "baseline_parity": baseline_parity.get("passed") is True,
        "both_models_ready": all(
            str(getattr(model, "status", "")) == "ready" for model in models
        ),
        "calibration_threshold_ready": (
            str(getattr(threshold, "status", "")) == "ready"
        ),
        "minimum_30_validation_actions": (
            (_number(identity.get("selection_count")) or 0) >= 30
        ),
        "minimum_70pct_formal_precision": (
            (_number(identity.get("formal_identity_precision_pct")) or 0) >= 70.0
        ),
        "minimum_70pct_original_account_identity_precision": (
            (_number(account_identity.get("precision_pct")) or 0) >= 70.0
        ),
        "minimum_30pct_reachable_recall": (
            (_number(identity.get("reachable_formal_recall_pct")) or 0) >= 30.0
        ),
        "positive_normal_account_return": (
            (_number(action.get("total_return_pct")) or -1e9) > 0
        ),
        "positive_double_cost_account_return": (
            (_number(double_cost.get("total_return_pct")) or -1e9) > 0
        ),
        "maximum_drawdown_no_worse_than_10pct": (
            (_number(action.get("max_drawdown_pct")) or -1e9) >= -10.0
        ),
        "d1_win_rate_within_2pct_of_touch_baseline": (
            (_number(action.get("win_rate")) or 0)
            >= (_number(formal.get("win_rate")) or 0) - 2.0
        ),
        "minimum_3_of_5_positive_validation_blocks": positive_blocks >= 3,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "positive_validation_block_count": positive_blocks,
        "threshold_frozen_from_calibration_only": True,
        "production_promotion_allowed": False,
    }


def render_joint_trigger_markdown(report: Mapping[str, object]) -> str:
    """Render the compact auditable v3 historical report."""

    lines = [
        "# 首板提前联合触发 v3 研究",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status')}`；结论：`{report.get('decision')}`。",
        f"- 研究版本：`{report.get('study_version')}`；正式策略修改：`False`。",
    ]
    dataset = _mapping(report.get("dataset"))
    lines.append(
        "- 共用规则后股票日："
        f"{dataset.get('candidate_pair_count', dataset.get('pair_count', 0))}；"
        "可评分分钟前缀："
        f"{dataset.get('observable_prefix_count', dataset.get('row_count', 0))}。"
    )
    fingerprints = _mapping(report.get("research_fingerprints"))
    if fingerprints:
        lines.append(
            f"- 日期切分指纹：`{fingerprints.get('date_split') or '-'}`；"
            f"行动策略指纹：`{fingerprints.get('action_policy') or '-'}`。"
        )
    models = _mapping(report.get("models"))
    lines.extend(["", "## Frozen models", ""])
    lines.append("| 模型 | 状态 | 训练股票日 | 指纹 |")
    lines.append("| --- | --- | ---: | --- |")
    for key, label in (("prepare_5m", "5分钟准备"), ("joint_action_3m", "3分钟联合行动")):
        model = _mapping(models.get(key))
        lines.append(
            f"| {label} | `{model.get('status')}` | "
            f"{model.get('training_pair_count', 0)} | `{model.get('fingerprint') or '-'}` |"
        )
    threshold = _mapping(report.get("threshold_selection"))
    lines.append("")
    lines.append(
        f"- 联合行动阈值：{_display(threshold.get('threshold'))}；"
        f"状态：`{threshold.get('status')}`。"
    )

    validation = _mapping(_mapping(report.get("phases")).get("validation"))
    identity = _mapping(validation.get("identity"))
    joint = _mapping(validation.get("joint_quality"))
    account_identity = _mapping(validation.get("account_identity"))
    lines.extend(["", "## Same-account validation", ""])
    lines.append(
        "| 信号 | 候选身份精度 | 3分钟命中 | 联合标签精度 | 原账户身份精度 | 原账户召回 |"
    )
    lines.append("| ---: | ---: | ---: | ---: | ---: | ---: |")
    lines.append(
        f"| {identity.get('selection_count', 0)} | "
        f"{_pct(identity.get('formal_identity_precision_pct'))} | "
        f"{_pct(identity.get('horizon_precision_pct'))} | "
        f"{_pct(joint.get('joint_precision_pct'))} | "
        f"{_pct(account_identity.get('precision_pct'))} | "
        f"{_pct(account_identity.get('recall_pct'))} |"
    )
    accounts = _mapping(validation.get("accounts"))
    lines.extend(
        [
            "",
            "| 账户 | 成交 | 胜率 | 复利 | 回撤 | PF |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in (
        ("formal_touch", "当前触板基线"),
        ("joint_action", "v3联合行动"),
        ("joint_action_double_cost", "v3双倍成本"),
        ("joint_action_conservative", "v3保守成交"),
    ):
        account = _mapping(accounts.get(key))
        lines.append(
            f"| {label} | {account.get('trade_count', 0)} | "
            f"{_pct(account.get('win_rate'))} | "
            f"{_signed_pct(account.get('total_return_pct'))} | "
            f"{_signed_pct(account.get('max_drawdown_pct'))} | "
            f"{_display(account.get('profit_factor'))} |"
        )

    lines.extend(["", "## Validation blocks", ""])
    lines.append("| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for block in report.get("validation_blocks") or []:
        block = _mapping(block)
        date_range = _mapping(block.get("date_range"))
        block_identity = _mapping(block.get("identity"))
        account = _mapping(_mapping(block.get("accounts")).get("joint_action"))
        lines.append(
            f"| {block.get('block')} | {date_range.get('start')}..{date_range.get('end')} | "
            f"{block_identity.get('selection_count', 0)} | "
            f"{account.get('trade_count', 0)} | {_pct(account.get('win_rate'))} | "
            f"{_signed_pct(account.get('total_return_pct'))} | "
            f"{_signed_pct(account.get('max_drawdown_pct'))} |"
        )

    lines.extend(["", "## Decision", ""])
    acceptance = _mapping(report.get("acceptance"))
    lines.append(f"- 历史门禁：`{'PASS' if acceptance.get('passed') else 'FAIL'}`。")
    for key, passed in _mapping(acceptance.get("checks")).items():
        lines.append(f"- `{key}`：{'通过' if passed else '未通过'}。")

    lines.extend(["", "## Forward validation", ""])
    forward = _mapping(report.get("forward_validation"))
    lines.append(
        f"- 状态：`{forward.get('status') or 'not_started'}`；"
        f"交易日 {forward.get('trade_day_count', 0)}，"
        f"雷达帧 {forward.get('frame_count', 0)}。"
    )
    limitations = [str(value) for value in report.get("limitations") or []]
    if limitations:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {value}" for value in limitations)
    return "\n".join(lines) + "\n"


def _joint_order(
    signal: Mapping[str, object],
    *,
    conservative_entry: bool,
) -> dict[str, object] | None:
    if signal.get("fillable") is not True:
        return None
    entry_price = _number(signal.get("entry_price"))
    limit_price = _number(signal.get("limit_price"))
    if entry_price is None or entry_price <= 0 or limit_price is None:
        return None
    if conservative_entry:
        signal_price = _number(signal.get("signal_price")) or entry_price
        entry_price = round(max(entry_price, signal_price * 1.001), 4)
    if entry_price >= limit_price - 0.001:
        return None
    probability = _number(signal.get(ACTION_SCORE_FIELD))
    order = _early_order({**dict(signal), "entry_price": entry_price})
    return {
        **order,
        "algorithm": "profitable_formal_touch_3m",
        ACTION_SCORE_FIELD: probability,
        LEGACY_ACTION_SCORE_FIELD: probability,
        "action_score_kind": ACTION_SCORE_FIELD,
        "base_rank_score": _number(signal.get("rank_score")),
        "rank_score": round((probability or 0.0) * 100, 6),
        "confirmation_minutes": CONFIRMATION_MINUTES,
        "conservative_entry": conservative_entry,
        "candidate_source": "all_3pct_shared_strategy_1m_joint_trigger",
    }


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _display(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.4f}" if parsed is not None else "-"


def _pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.2f}%" if parsed is not None else "-"


def _signed_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:+.2f}%" if parsed is not None else "-"


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _write_output(path_text: str, content: str) -> None:
    path = Path(path_text).resolve()
    evidence_root = (Path.cwd() / "memory" / "06_backtests").resolve()
    if evidence_root not in path.parents:
        raise ValueError("joint-trigger report must stay under memory/06_backtests")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate direct joint pre-board trigger")
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSION_COUNT)
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "both"),
        default="markdown",
    )
    parser.add_argument(
        "--output",
        help="Output path for one format, or path prefix when --format=both",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_preboard_joint_trigger(session_count=args.sessions)
    markdown = render_joint_trigger_markdown(report)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.format == "both":
        if not args.output:
            raise ValueError("--output is required when --format=both")
        _write_output(f"{args.output}.md", markdown)
        _write_output(f"{args.output}.json", json_text)
        return
    content = json_text if args.format == "json" else markdown
    if args.output:
        _write_output(args.output, content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
