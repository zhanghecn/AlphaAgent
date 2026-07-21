"""Historical study for the radar-native pre-board sequence trigger."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from statistics import mean
from time import monotonic

import pandas as pd

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    attach_competing_risk_targets,
)
from alphaagent.server.services.limit_up.preboard_radar_sequence_model import (
    ACTION_SCORE_FIELD,
    CANDIDATE_SCORE_FIELD,
    FIRST_LAYER_FEATURE_NAMES,
    SECOND_LAYER_FEATURE_NAMES,
    TOUCH_TARGET_FIELD,
    CandidateTouchModelFit,
    RadarActionThresholdSelection,
    Top1ActionModelFit,
    build_expanding_oof_top1,
    calibrate_radar_action_threshold,
    enrich_radar_sequence_features,
    fit_candidate_touch_model,
    fit_top1_action_model,
    score_candidate_touch_rows,
    score_top1_action_rows,
    select_minute_top1,
    select_radar_actions,
)
from alphaagent.server.services.research_runtime import require_research_runtime


STUDY_VERSION = "limit-up-preboard-radar-sequence-v8"
SESSION_COUNT = 89
FIT_SESSION_COUNT = 44
CALIBRATION_SESSION_COUNT = 15
VALIDATION_SESSION_COUNT = 30
EXCLUDED_TRAINING_EXTENSION_SESSION_COUNT = 6
PROBED_SESSION_COUNT = SESSION_COUNT + EXCLUDED_TRAINING_EXTENSION_SESSION_COUNT
EXCLUDED_EXTENSION_STATUS = "excluded_training_extension_provider_unavailable"
HISTORY_QUALITY_FINGERPRINT_FIELDS = (
    "stock_d1_sample_count",
    "stock_d1_win_count",
    "stock_d1_win_rate",
    "stock_d1_average_return_pct",
    "stock_gene_combined_win_rate",
)


def split_radar_sequence_dates(
    dates: Sequence[date],
) -> tuple[tuple[date, ...], tuple[date, ...], tuple[date, ...]]:
    ordered = tuple(sorted(set(dates)))
    if len(ordered) != SESSION_COUNT:
        raise ValueError(
            "radar sequence study requires exactly 89 complete trade dates"
        )
    fit_end = FIT_SESSION_COUNT
    calibration_end = fit_end + CALIBRATION_SESSION_COUNT
    return (
        ordered[:fit_end],
        ordered[fit_end:calibration_end],
        ordered[calibration_end:],
    )


def audit_radar_sequence_minute_coverage(
    manifest: pd.DataFrame,
    coverage: pd.DataFrame,
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
) -> dict[str, object]:
    pairs = _normalized_pairs(manifest)
    scope = coverage.copy()
    scope["trade_date"] = pd.to_datetime(
        scope["trade_date"], errors="raise"
    ).dt.date
    scope = scope.loc[
        :, ["vt_symbol", "trade_date", "coverage_status"]
    ].drop_duplicates(["vt_symbol", "trade_date"], keep=False)
    audited = pairs.merge(
        scope,
        on=["vt_symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    audited["coverage_status"] = audited["coverage_status"].fillna("missing")
    incomplete = audited.loc[~audited["coverage_status"].eq("complete")]
    phase_dates = {
        "fit": fit_dates,
        "calibration": calibration_dates,
        "validation": validation_dates,
    }
    phase_missing = {
        phase: int(incomplete["trade_date"].isin(dates).sum())
        for phase, dates in phase_dates.items()
    }
    status = _coverage_status(phase_missing)
    return {
        "passed": not any(phase_missing.values()),
        "status": status,
        "manifest_pair_count": len(pairs),
        "complete_pair_count": int(audited["coverage_status"].eq("complete").sum()),
        "missing_pair_count": len(incomplete),
        "phase_missing_pair_counts": phase_missing,
        "coverage_status_counts": {
            str(key): int(value)
            for key, value in audited["coverage_status"].value_counts().sort_index().items()
        },
    }


def audit_excluded_training_extension(
    manifest: pd.DataFrame,
    coverage: pd.DataFrame,
) -> dict[str, object]:
    """Record provider-unavailable extension rows outside the main study."""

    pairs = _normalized_pairs(manifest)
    scope = coverage.copy()
    scope["trade_date"] = pd.to_datetime(
        scope["trade_date"], errors="raise"
    ).dt.date
    scope = scope.loc[
        :, ["vt_symbol", "trade_date", "coverage_status"]
    ].drop_duplicates(["vt_symbol", "trade_date"], keep=False)
    audited = pairs.merge(
        scope,
        on=["vt_symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    audited["coverage_status"] = audited["coverage_status"].fillna("missing")
    complete = audited["coverage_status"].eq("complete")
    return {
        "status": EXCLUDED_EXTENSION_STATUS,
        "included_in_main_study": False,
        "trade_dates": tuple(
            value.isoformat() for value in sorted(set(pairs["trade_date"]))
        ),
        "manifest_pair_count": len(pairs),
        "complete_pair_count": int(complete.sum()),
        "missing_pair_count": int((~complete).sum()),
    }


def build_radar_sequence_scope_audit(
    manifest: pd.DataFrame,
    coverage: pd.DataFrame,
) -> dict[str, object]:
    """Freeze the complete 89-day window without concealing the six-day gap."""

    pairs = _normalized_pairs(manifest)
    trade_dates = tuple(sorted(set(pairs["trade_date"])))
    if len(trade_dates) != PROBED_SESSION_COUNT:
        raise ValueError(
            "radar sequence scope audit requires exactly 95 probed trade dates"
        )
    excluded_dates = trade_dates[:EXCLUDED_TRAINING_EXTENSION_SESSION_COUNT]
    main_dates = trade_dates[EXCLUDED_TRAINING_EXTENSION_SESSION_COUNT:]
    fit_dates, calibration_dates, validation_dates = split_radar_sequence_dates(
        main_dates
    )
    main_date_set = set(main_dates)
    excluded_date_set = set(excluded_dates)
    main_manifest = _rows_on_dates(manifest, main_date_set)
    excluded_manifest = _rows_on_dates(manifest, excluded_date_set)
    main_coverage = audit_radar_sequence_minute_coverage(
        main_manifest,
        coverage,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
    )
    excluded_audit = audit_excluded_training_extension(
        excluded_manifest,
        coverage,
    )
    daily_scope = _daily_scope_rows(pairs, coverage)
    return {
        "status": str(main_coverage["status"]),
        "probed_trade_date_count": len(trade_dates),
        "probed_date_start": trade_dates[0].isoformat(),
        "probed_date_end": trade_dates[-1].isoformat(),
        "main_window": {
            "trade_date_count": len(main_dates),
            "date_start": main_dates[0].isoformat(),
            "date_end": main_dates[-1].isoformat(),
            "manifest_pair_count": len(_normalized_pairs(main_manifest)),
            "fit_dates": tuple(value.isoformat() for value in fit_dates),
            "calibration_dates": tuple(
                value.isoformat() for value in calibration_dates
            ),
            "validation_dates": tuple(
                value.isoformat() for value in validation_dates
            ),
            "coverage": main_coverage,
        },
        "excluded_training_extension": excluded_audit,
        "daily_scope": tuple(daily_scope),
        "input_fingerprints": {
            "manifest_pairs_sha256": _frame_fingerprint(
                manifest,
                ("trade_date", "vt_symbol"),
            ),
            "minute_coverage_sha256": _frame_fingerprint(
                coverage,
                tuple(
                    field
                    for field in (
                        "trade_date",
                        "vt_symbol",
                        "coverage_status",
                        "raw_row_count",
                        "unique_row_count",
                        "valid_slot_count",
                        "unexpected_time_count",
                        "duplicate_count",
                    )
                    if field in coverage.columns
                ),
            ),
            "history_quality_sha256": _frame_fingerprint(
                manifest,
                (
                    "trade_date",
                    "vt_symbol",
                    *(
                        field
                        for field in HISTORY_QUALITY_FINGERPRINT_FIELDS
                        if field in manifest.columns
                    ),
                ),
            ),
        },
    }


def build_labeled_radar_rows(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Freeze canonical sequence features before attaching future touch labels."""

    featured = enrich_radar_sequence_features(prefix_rows)
    source_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    for raw in prefix_rows:
        row = dict(raw)
        key = _study_row_identity(row)
        if key in source_by_key:
            raise ValueError(f"duplicate historical prefix row: {key}")
        source_by_key[key] = row
    merged: list[dict[str, object]] = []
    for row in featured:
        key = _study_row_identity(row)
        source = source_by_key.get(key)
        if source is None:
            raise ValueError(f"canonical row missing source prefix: {key}")
        merged.append({**source, **dict(row)})
    return attach_competing_risk_targets(merged, formal_orders)


def fit_radar_sequence_policy(
    labeled_rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
) -> dict[str, object]:
    """Fit both frozen layers and select validation actions without leakage."""

    oof_top1 = build_expanding_oof_top1(
        labeled_rows,
        fit_dates=fit_dates,
    )
    action_model = fit_top1_action_model(oof_top1)
    candidate_model = fit_candidate_touch_model(
        labeled_rows,
        fit_dates=fit_dates,
    )
    scoring_dates = calibration_dates | validation_dates
    scoring_rows = [
        dict(row)
        for row in labeled_rows
        if _study_date(row.get("signal_date")) in scoring_dates
    ]
    top1_rows = select_minute_top1(
        score_candidate_touch_rows(scoring_rows, candidate_model)
    )
    action_rows = score_top1_action_rows(top1_rows, action_model)
    threshold = calibrate_radar_action_threshold(
        action_rows,
        calibration_dates=calibration_dates,
    )
    selected = (
        select_radar_actions(action_rows, threshold=threshold.threshold)
        if threshold.threshold is not None
        else []
    )
    return {
        "candidate_model": candidate_model,
        "action_model": action_model,
        "threshold": threshold,
        "oof_top1_rows": oof_top1,
        "top1_rows": top1_rows,
        "action_rows": action_rows,
        "calibration_actions": [
            row
            for row in selected
            if _study_date(row.get("signal_date")) in calibration_dates
        ],
        "validation_actions": [
            row
            for row in selected
            if _study_date(row.get("signal_date")) in validation_dates
        ],
    }


def radar_order(
    signal: Mapping[str, object],
    *,
    conservative_entry: bool,
) -> dict[str, object] | None:
    """Convert one selected Top1 into the unchanged next-minute order shape."""

    if signal.get("fillable") is not True:
        return None
    entry_price = _study_number(signal.get("entry_price"))
    limit_price = _study_number(signal.get("limit_price"))
    if entry_price is None or entry_price <= 0 or limit_price is None:
        return None
    if conservative_entry:
        signal_price = _study_number(signal.get("signal_price")) or entry_price
        entry_price = round(max(entry_price, signal_price * 1.001), 4)
    if entry_price >= limit_price - 0.001:
        return None
    from alphaagent.server.services.limit_up.preboard_strategy_study import (
        _early_order,
    )

    probability = _study_number(signal.get(ACTION_SCORE_FIELD))
    order = _early_order({**dict(signal), "entry_price": entry_price})
    return {
        **order,
        "algorithm": "radar_sequence_top1_v8",
        ACTION_SCORE_FIELD: probability,
        "rank_score": round((probability or 0.0) * 100, 6),
        "confirmation_minutes": 1,
        "conservative_entry": conservative_entry,
        "candidate_source": "all_3pct_shared_strategy_radar_sequence_v8",
    }


def build_radar_acceptance_report(
    validation: Mapping[str, object],
    *,
    validation_blocks: Sequence[Mapping[str, object]],
    candidate_model: CandidateTouchModelFit | object,
    action_model: Top1ActionModelFit | object,
    threshold: RadarActionThresholdSelection | object,
    baseline_parity: Mapping[str, object],
) -> dict[str, object]:
    identity = _study_mapping(validation.get("identity"))
    account_identity = _study_mapping(validation.get("account_identity"))
    accounts = _study_mapping(validation.get("accounts"))
    formal = _study_mapping(accounts.get("formal_touch"))
    action = _study_mapping(accounts.get("joint_action"))
    double_cost = _study_mapping(accounts.get("joint_action_double_cost"))
    positive_blocks = sum(
        (_study_number(account.get("trade_count")) or 0) > 0
        and (_study_number(account.get("total_return_pct")) or 0) > 0
        for block in validation_blocks
        if (
            account := _study_mapping(
                _study_mapping(block.get("accounts")).get("joint_action")
            )
        )
    )
    checks = {
        "baseline_parity": baseline_parity.get("passed") is True,
        "both_models_ready": all(
            getattr(model, "status", None) == "ready"
            for model in (candidate_model, action_model)
        ),
        "calibration_threshold_ready": getattr(threshold, "status", None)
        == "ready",
        "minimum_30_validation_actions": (
            (_study_number(identity.get("selection_count")) or 0) >= 30
        ),
        "minimum_70pct_formal_precision": (
            (_study_number(identity.get("formal_identity_precision_pct")) or 0)
            >= 70.0
        ),
        "minimum_70pct_original_account_identity_precision": (
            (_study_number(account_identity.get("precision_pct")) or 0) >= 70.0
        ),
        "minimum_30pct_reachable_recall": (
            (_study_number(identity.get("reachable_formal_recall_pct")) or 0)
            >= 30.0
        ),
        "positive_normal_account_return": (
            (_study_number(action.get("total_return_pct")) or -1e9) > 0
        ),
        "positive_double_cost_account_return": (
            (_study_number(double_cost.get("total_return_pct")) or -1e9) > 0
        ),
        "maximum_drawdown_no_worse_than_10pct": (
            (_study_number(action.get("max_drawdown_pct")) or -1e9) >= -10.0
        ),
        "d1_win_rate_within_2pct_of_touch_baseline": (
            (_study_number(action.get("win_rate")) or 0)
            >= (_study_number(formal.get("win_rate")) or 0) - 2.0
        ),
        "minimum_1_2_normal_account_profit_factor": (
            (_study_number(action.get("profit_factor")) or 0) >= 1.2
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


def evaluate_preboard_radar_sequence(
    *,
    session_count: int = SESSION_COUNT,
) -> dict[str, object]:
    """Run the frozen radar-native sequence study on the complete 89-day scope."""

    if int(session_count) != SESSION_COUNT:
        raise ValueError("radar sequence v8 is frozen to exactly 89 main sessions")

    from alphaagent.server.services.limit_up import history_repository
    from alphaagent.server.services.limit_up import preboard_competing_risk_study as legacy
    from alphaagent.server.services.limit_up import preboard_transaction_data
    from alphaagent.server.services.limit_up.preboard_hazard_data import (
        load_one_minute_bars,
        load_one_minute_coverage,
        load_static_hazard_manifest,
    )
    from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION

    started = monotonic()
    timings: dict[str, float] = {}
    checkpoint = started

    probed_manifest = load_static_hazard_manifest(session_count=PROBED_SESSION_COUNT)
    checkpoint = _record_timing(timings, "manifest_seconds", checkpoint)
    if probed_manifest.empty:
        return _blocked_study_report("blocked_by_manifest", timings)
    coverage = load_one_minute_coverage(probed_manifest)
    scope_audit = build_radar_sequence_scope_audit(probed_manifest, coverage)
    checkpoint = _record_timing(timings, "scope_coverage_seconds", checkpoint)
    if scope_audit.get("status") != "ready":
        return {
            **_blocked_study_report(str(scope_audit.get("status")), timings),
            "scope_audit": scope_audit,
        }

    main_window = _study_mapping(scope_audit.get("main_window"))
    main_dates = tuple(
        _study_date(value)
        for value in (
            *main_window.get("fit_dates", ()),
            *main_window.get("calibration_dates", ()),
            *main_window.get("validation_dates", ()),
        )
    )
    if any(value is None for value in main_dates):
        return _blocked_study_report("blocked_by_frozen_date_split", timings)
    complete_main_dates = tuple(value for value in main_dates if value is not None)
    fit_dates, calibration_dates, validation_dates = split_radar_sequence_dates(
        complete_main_dates
    )
    main_manifest = _rows_on_dates(probed_manifest, set(complete_main_dates))
    complete_pairs = {
        (str(row.vt_symbol), _study_date(row.trade_date))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
        if _study_date(row.trade_date) in set(complete_main_dates)
    }
    if len(complete_pairs) != len(main_manifest):
        return {
            **_blocked_study_report("blocked_by_main_pair_coverage", timings),
            "scope_audit": scope_audit,
        }

    feature_frame, feature_coverage = legacy._load_bounded_feature_frame(
        main_manifest,
        lookback_sessions=legacy.FEATURE_LOOKBACK_SESSIONS,
    )
    feature_by_pair = legacy._feature_index(feature_frame, set(complete_main_dates))
    financial_index = legacy._load_financial_index()
    prefiltered_manifest, prefilter_audit = (
        preboard_transaction_data.prefilter_shared_transaction_manifest(
            main_manifest,
            complete_pairs,
            feature_by_pair,
            financial_index,
        )
    )
    checkpoint = _record_timing(timings, "static_prefilter_seconds", checkpoint)
    if prefiltered_manifest.empty:
        return {
            **_blocked_study_report("blocked_by_static_prefilter", timings),
            "scope_audit": scope_audit,
            "static_prefilter": prefilter_audit,
        }

    prefiltered_pairs = {
        (str(row.vt_symbol), _study_date(row.trade_date))
        for row in prefiltered_manifest.itertuples()
    }
    minute_rows = load_one_minute_bars(prefiltered_manifest)
    daily_consistency = legacy.audit_minute_daily_consistency(
        prefiltered_manifest,
        minute_rows,
    )
    checkpoint = _record_timing(timings, "minute_load_audit_seconds", checkpoint)
    if _study_number(daily_consistency.get("ready_pair_pct")) != 100.0:
        return {
            **_blocked_study_report(
                "blocked_by_minute_daily_inconsistency",
                timings,
            ),
            "scope_audit": scope_audit,
            "minute_daily_consistency": daily_consistency,
        }

    prefix_rows, filter_audit = legacy._build_all_strategy_prefix_rows(
        prefiltered_manifest,
        minute_rows,
        prefiltered_pairs,
        feature_by_pair,
        financial_index,
        bar_minutes=1,
        passed_only=True,
        row_projection=legacy._project_competing_row,
    )
    checkpoint = _record_timing(timings, "prefix_build_seconds", checkpoint)
    if not prefix_rows:
        return {
            **_blocked_study_report("blocked_by_empty_canonical_scope", timings),
            "scope_audit": scope_audit,
            "filter_audit": filter_audit,
        }

    start = complete_main_dates[0]
    end = complete_main_dates[-1]
    history_days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end,
        False,
    )
    scoped_history_days = [
        day
        for day in history_days
        if start
        <= (legacy._optional_date(day.get("trade_date")) or date.min)
        <= end
    ]
    formal_orders, profitability_audit = legacy._formal_orders(
        history_days,
        scoped_history_days,
        start,
        end,
    )
    labeled_rows = build_labeled_radar_rows(prefix_rows, formal_orders)
    checkpoint = _record_timing(timings, "canonical_label_seconds", checkpoint)

    symbols = sorted(
        {
            *(str(value) for value in prefiltered_manifest["vt_symbol"].unique()),
            *(
                str(order.get("vt_symbol") or "")
                for order in formal_orders
                if order.get("vt_symbol")
            ),
        }
    )
    result_dates = [
        value
        for raw in main_manifest.get("result_date", [])
        if (value := _study_date(raw)) is not None
    ]
    result_dates.extend(
        value
        for order in formal_orders
        if (value := _study_date(order.get("result_date"))) is not None
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
        _study_mapping(service_baseline.get("summary")),
        baseline_summary,
    )
    checkpoint = _record_timing(timings, "baseline_seconds", checkpoint)
    if baseline_parity.get("passed") is not True:
        return {
            **_blocked_study_report("blocked_by_baseline_mismatch", timings),
            "scope_audit": scope_audit,
            "baseline_parity": baseline_parity,
        }

    policy = fit_radar_sequence_policy(
        labeled_rows,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
    )
    candidate_model = policy["candidate_model"]
    action_model = policy["action_model"]
    threshold = policy["threshold"]
    selected_actions = [
        *policy["calibration_actions"],
        *policy["validation_actions"],
    ]
    normal_bundle = build_radar_replay_orders(
        action_signals=selected_actions,
        formal_orders=formal_orders,
        conservative_entry=False,
    )
    conservative_bundle = build_radar_replay_orders(
        action_signals=selected_actions,
        formal_orders=formal_orders,
        conservative_entry=True,
    )

    phases = {
        phase: _radar_phase_report(
            labeled_rows=labeled_rows,
            formal_orders=formal_orders,
            action_signals=selected_actions,
            action_orders=normal_bundle["combined_orders"],
            conservative_orders=conservative_bundle["combined_orders"],
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
        )
        for phase, allowed_dates in (
            ("calibration", set(calibration_dates)),
            ("validation", set(validation_dates)),
        )
    }
    validation_blocks = [
        {
            "block": index,
            "date_range": legacy._date_range(block_dates),
            **_radar_phase_report(
                labeled_rows=labeled_rows,
                formal_orders=formal_orders,
                action_signals=selected_actions,
                action_orders=normal_bundle["combined_orders"],
                conservative_orders=conservative_bundle["combined_orders"],
                bars=bars,
                trade_dates=trade_dates,
                allowed_dates=set(block_dates),
            ),
        }
        for index, block_dates in enumerate(
            legacy._fixed_validation_blocks(validation_dates),
            start=1,
        )
    ]
    acceptance = build_radar_acceptance_report(
        _study_mapping(phases.get("validation")),
        validation_blocks=validation_blocks,
        candidate_model=candidate_model,
        action_model=action_model,
        threshold=threshold,
        baseline_parity=baseline_parity,
    )
    checkpoint = _record_timing(timings, "model_replay_seconds", checkpoint)
    timings["total_seconds"] = round(monotonic() - started, 3)

    date_split = {
        phase: {
            "count": len(values),
            "start": values[0].isoformat(),
            "end": values[-1].isoformat(),
            "dates": tuple(value.isoformat() for value in values),
        }
        for phase, values in (
            ("fit", fit_dates),
            ("calibration", calibration_dates),
            ("validation", validation_dates),
        )
    }
    model_reports = {
        "candidate_touch_3m": _candidate_model_report(candidate_model),
        "top1_action_3m": _action_model_report(action_model),
    }
    threshold_report = _threshold_report(threshold)
    validation_accounts = _study_mapping(
        _study_mapping(phases.get("validation")).get("accounts")
    )
    report = {
        "study_version": STUDY_VERSION,
        "status": (
            "ready_historical_pass"
            if acceptance.get("passed") is True
            else "ready_historical_rejected"
        ),
        "decision": (
            "historical_pass_forward_shadow_candidate"
            if acceptance.get("passed") is True
            else "historical_rejected_no_live_promotion"
        ),
        "formal_strategy_changed": False,
        "historical_validation_kind": "viewed_historical_counterexample",
        "contract": {
            "observation_gain_operator": ">=",
            "observation_gain_pct": 3.0,
            "candidate_target": TOUCH_TARGET_FIELD,
            "candidate_score": CANDIDATE_SCORE_FIELD,
            "action_score": ACTION_SCORE_FIELD,
            "first_layer_features": list(FIRST_LAYER_FEATURE_NAMES),
            "second_layer_features": list(SECOND_LAYER_FEATURE_NAMES),
            "maximum_daily_first_board_actions": 2,
            "entry": "next_one_minute_open_strictly_below_limit",
            "conservative_entry": "max(next_open,signal_price_x_1_001)",
            "exit": "d1_official_close",
            "execution_effect": "none_research_only",
            "excluded_historical_features": [
                "transaction_flow",
                "dynamic_concept",
                "sector_fund_flow",
                "stock_fund_flow",
                "market_timing_state",
                "l2_order_queue",
            ],
        },
        "date_split": date_split,
        "scope_audit": scope_audit,
        "feature_coverage": feature_coverage,
        "static_prefilter": prefilter_audit,
        "minute_daily_consistency": daily_consistency,
        "filter_audit": filter_audit,
        "formal_profitability_filter": profitability_audit,
        "baseline_parity": baseline_parity,
        "dataset": _dataset_report(
            labeled_rows,
            oof_rows=policy["oof_top1_rows"],
            top1_rows=policy["top1_rows"],
        ),
        "models": model_reports,
        "threshold_selection": threshold_report,
        "phases": phases,
        "validation_blocks": validation_blocks,
        "acceptance": acceptance,
        "deterministic_fingerprints": {
            "scope_inputs": dict(scope_audit.get("input_fingerprints") or {}),
            "canonical_rows": _stable_json_fingerprint(
                _stable_canonical_rows(labeled_rows)
            ),
            "models": _stable_json_fingerprint(model_reports),
            "threshold": _stable_json_fingerprint(threshold_report),
            "validation_actions": _stable_json_fingerprint(
                _stable_action_rows(policy["validation_actions"])
            ),
            "validation_accounts": _stable_json_fingerprint(validation_accounts),
        },
        "performance": timings,
        "forward_validation": {
            "status": (
                "not_connected_historical_pass"
                if acceptance.get("passed") is True
                else "not_promoted_historical_rejected"
            ),
            "trade_day_count": 0,
            "closed_action_event_count": 0,
            "execution_effect": "none_research_only",
        },
        "limitations": [
            "后30日已经被多轮历史研究查看，只能作反证，不能称新锁定留出。",
            "一分钟K线不能证明十秒级拉板中的委托、撤单、排队或真实成交。",
            "六日训练扩展因公共供应商不可用被明确排除，主报告只称89日完整研究。",
            "历史通过也只能接冻结后只读前向；正式v9/v15保持不变。",
        ],
    }
    return report


def build_radar_replay_orders(
    *,
    action_signals: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    conservative_entry: bool,
) -> dict[str, list[dict[str, object]]]:
    early_orders = [
        order
        for signal in action_signals
        if (
            order := radar_order(
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
        "action_signals": [dict(row) for row in action_signals],
        "early_orders": early_orders,
        "relay_orders": relay_orders,
        "combined_orders": [*relay_orders, *early_orders],
    }


def _radar_phase_report(
    *,
    labeled_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_signals: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
) -> dict[str, object]:
    from alphaagent.server.services.limit_up import preboard_competing_risk_study as legacy

    return {
        "identity": _radar_identity_report(
            labeled_rows,
            formal_orders,
            action_signals,
            allowed_dates=allowed_dates,
        ),
        "accounts": _radar_phase_accounts(
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


def _radar_identity_report(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    signals: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> dict[str, object]:
    eligible = [
        row for row in rows if _study_date(row.get("signal_date")) in allowed_dates
    ]
    formal_pairs = {
        _study_order_pair(order)
        for order in formal_orders
        if str(order.get("lane") or "") == "first_board"
        and _study_date(order.get("entry_date")) in allowed_dates
    }
    selected = [
        row
        for row in signals
        if _study_date(row.get("signal_date")) in allowed_dates
    ]
    selected_pairs = {_study_order_pair(row) for row in selected}
    reachable_pairs = {
        _study_order_pair(row)
        for row in eligible
        if row.get(TOUCH_TARGET_FIELD) is True
    }
    touch_true = [row for row in selected if row.get(TOUCH_TARGET_FIELD) is True]
    formal_true_pairs = selected_pairs & formal_pairs
    returns = [
        value
        for row in selected
        if (value := _study_number(row.get("net_return_pct"))) is not None
    ]
    return {
        "selection_count": len(selected),
        "fillable_selection_count": sum(row.get("fillable") is True for row in selected),
        "formal_first_board_pair_count": len(formal_pairs),
        "reachable_formal_pair_count": len(reachable_pairs),
        "formal_identity_true_positive_count": len(formal_true_pairs),
        "touch_true_positive_count": len(touch_true),
        "formal_identity_precision_pct": _percentage(
            len(formal_true_pairs),
            len(selected),
        ),
        "touch_precision_pct": _percentage(len(touch_true), len(selected)),
        "reachable_formal_recall_pct": _percentage(
            len(selected_pairs & reachable_pairs),
            len(reachable_pairs),
        ),
        "d1_closed_count": len(returns),
        "d1_win_rate_pct": _percentage(sum(value > 0 for value in returns), len(returns)),
        "d1_average_return_pct": round(mean(returns), 4) if returns else None,
    }


def _radar_phase_accounts(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
) -> dict[str, object]:
    from alphaagent.server.services.limit_up import preboard_competing_risk_study as legacy

    formal = legacy._orders_on_dates(formal_orders, allowed_dates)
    action = legacy._orders_on_dates(action_orders, allowed_dates)
    conservative = legacy._orders_on_dates(conservative_orders, allowed_dates)
    relay = [order for order in formal if str(order.get("lane") or "") == "two_to_three"]
    formal_first = [
        order for order in formal if str(order.get("lane") or "") == "first_board"
    ]
    early = [
        order
        for order in action
        if str(order.get("algorithm") or "") == "radar_sequence_top1_v8"
    ]
    return {
        "formal_touch": legacy._account_metrics(formal, bars, trade_dates),
        "formal_first_board_only": legacy._account_metrics(
            formal_first,
            bars,
            trade_dates,
        ),
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


def _candidate_model_report(model: CandidateTouchModelFit) -> dict[str, object]:
    return {
        "status": model.status,
        "training_row_count": model.training_row_count,
        "training_date_count": model.training_date_count,
        "class_counts": dict(model.class_counts),
        "fit_dates": list(model.fit_dates),
        "parameters": dict(model.parameters),
        "feature_importance_by_name": dict(model.feature_importance_by_name),
        "fingerprint": model.fingerprint,
    }


def _action_model_report(model: Top1ActionModelFit) -> dict[str, object]:
    return {
        "status": model.status,
        "training_row_count": model.training_row_count,
        "training_date_count": model.training_date_count,
        "class_counts": dict(model.class_counts),
        "fit_dates": list(model.fit_dates),
        "scaler_mean_by_feature": dict(model.scaler_mean_by_feature),
        "scaler_scale_by_feature": dict(model.scaler_scale_by_feature),
        "coefficient_by_feature": dict(model.coefficient_by_feature),
        "intercept": model.intercept,
        "fingerprint": model.fingerprint,
    }


def _threshold_report(
    threshold: RadarActionThresholdSelection,
) -> dict[str, object]:
    return {
        "status": threshold.status,
        "threshold": threshold.threshold,
        "calibration_dates": list(threshold.calibration_dates),
        "minimum_action_count": threshold.minimum_action_count,
        "minimum_precision": threshold.minimum_precision,
        "selected_metrics": dict(threshold.selected_metrics),
        "metrics_by_threshold": [dict(row) for row in threshold.metrics_by_threshold],
    }


def _dataset_report(
    rows: Sequence[Mapping[str, object]],
    *,
    oof_rows: Sequence[Mapping[str, object]],
    top1_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "canonical_row_count": len(rows),
        "canonical_stock_day_count": len({_study_order_pair(row) for row in rows}),
        "canonical_trade_day_count": len(
            {_study_date(row.get("signal_date")) for row in rows}
        ),
        "positive_touch_row_count": sum(
            row.get(TOUCH_TARGET_FIELD) is True for row in rows
        ),
        "oof_top1_row_count": len(oof_rows),
        "final_top1_row_count": len(top1_rows),
    }


def render_radar_sequence_markdown(report: Mapping[str, object]) -> str:
    models = _study_mapping(report.get("models"))
    candidate = _study_mapping(models.get("candidate_touch_3m"))
    action = _study_mapping(models.get("top1_action_3m"))
    threshold = _study_mapping(report.get("threshold_selection"))
    validation = _study_mapping(_study_mapping(report.get("phases")).get("validation"))
    identity = _study_mapping(validation.get("identity"))
    accounts = _study_mapping(validation.get("accounts"))
    joint = _study_mapping(accounts.get("joint_action"))
    formal = _study_mapping(accounts.get("formal_touch"))
    scope = _study_mapping(report.get("scope_audit"))
    main = _study_mapping(scope.get("main_window"))
    excluded = _study_mapping(scope.get("excluded_training_extension"))
    lines = [
        "# 首板雷达原生序列触发 v8 研究",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status')}`；结论：`{report.get('decision')}`。",
        "- 正式策略修改：`False`；执行影响：`none_research_only`。",
        f"- 主窗口：{main.get('date_start')}..{main.get('date_end')}，"
        f"{main.get('trade_date_count', 0)} 日、{main.get('manifest_pair_count', 0)} 个股票日。",
        f"- 排除扩展：{excluded.get('manifest_pair_count', 0)} 个股票日，"
        f"缺失 {excluded.get('missing_pair_count', 0)}，状态 `{excluded.get('status')}`。",
        "",
        "## Models and calibration",
        "",
        f"- 第一层：`{candidate.get('status')}`，训练 {candidate.get('training_row_count', 0)} 行，"
        f"指纹 `{candidate.get('fingerprint')}`。",
        f"- 第二层：`{action.get('status')}`，OOF Top1 训练 {action.get('training_row_count', 0)} 行，"
        f"指纹 `{action.get('fingerprint')}`。",
        f"- 校准：`{threshold.get('status')}`，阈值 `{threshold.get('threshold')}`；"
        f"最低 {threshold.get('minimum_action_count', 10)} 个股票日且精度至少"
        f" {_display_pct_ratio(threshold.get('minimum_precision'))}。",
        "",
        "## Validation",
        "",
        "| 方案 | 动作/成交 | 胜率 | 复利 | 回撤 | PF |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| 当前触板基线 | {formal.get('trade_count', 0)} | {_display_pct(formal.get('win_rate'))} |"
        f" {_display_signed_pct(formal.get('total_return_pct'))} | {_display_signed_pct(formal.get('max_drawdown_pct'))} |"
        f" {_display_number(formal.get('profit_factor'))} |",
        f"| v8 联合账户 | {identity.get('selection_count', 0)}/{joint.get('trade_count', 0)} |"
        f" {_display_pct(joint.get('win_rate'))} | {_display_signed_pct(joint.get('total_return_pct'))} |"
        f" {_display_signed_pct(joint.get('max_drawdown_pct'))} | {_display_number(joint.get('profit_factor'))} |",
        "",
        f"- 三分钟触板精度：{_display_pct(identity.get('touch_precision_pct'))}；"
        f"正式身份精度：{_display_pct(identity.get('formal_identity_precision_pct'))}；"
        f"可达召回：{_display_pct(identity.get('reachable_formal_recall_pct'))}。",
        "",
        "## Decision",
        "",
    ]
    acceptance = _study_mapping(report.get("acceptance"))
    for name, passed in _study_mapping(acceptance.get("checks")).items():
        lines.append(f"- `{name}`：{'通过' if passed else '未通过'}。")
    lines.extend(
        [
            "",
            "后 30 日是已查看历史反证；即使全部历史门通过，也只能进入冻结后只读前向。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_output(path_text: str, content: str) -> None:
    path = Path(path_text).resolve()
    evidence_root = (Path.cwd() / "memory" / "06_backtests").resolve()
    if evidence_root not in path.parents:
        raise ValueError("radar sequence report must stay under memory/06_backtests")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate radar-native pre-board sequence")
    parser.add_argument("--sessions", type=int, default=SESSION_COUNT)
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
    require_research_runtime()
    report = evaluate_preboard_radar_sequence(session_count=args.sessions)
    markdown = render_radar_sequence_markdown(report)
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
        print(content)


def _normalized_pairs(manifest: pd.DataFrame) -> pd.DataFrame:
    pairs = manifest.loc[:, ["vt_symbol", "trade_date"]].drop_duplicates().copy()
    pairs["vt_symbol"] = pairs["vt_symbol"].astype(str)
    pairs["trade_date"] = pd.to_datetime(
        pairs["trade_date"], errors="raise"
    ).dt.date
    return pairs.sort_values(["trade_date", "vt_symbol"], kind="stable")


def _rows_on_dates(frame: pd.DataFrame, dates: set[date]) -> pd.DataFrame:
    rows = frame.copy()
    normalized_dates = pd.to_datetime(rows["trade_date"], errors="raise").dt.date
    return rows.loc[normalized_dates.isin(dates)].copy()


def _daily_scope_rows(
    pairs: pd.DataFrame,
    coverage: pd.DataFrame,
) -> list[dict[str, object]]:
    normalized = coverage.copy()
    normalized["trade_date"] = pd.to_datetime(
        normalized["trade_date"], errors="raise"
    ).dt.date
    normalized = normalized.loc[
        :, ["vt_symbol", "trade_date", "coverage_status"]
    ].drop_duplicates(["vt_symbol", "trade_date"], keep=False)
    audited = pairs.merge(
        normalized,
        on=["vt_symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    audited["coverage_status"] = audited["coverage_status"].fillna("missing")
    rows: list[dict[str, object]] = []
    for trade_date, group in audited.groupby("trade_date", sort=True):
        complete = int(group["coverage_status"].eq("complete").sum())
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "manifest_pair_count": len(group),
                "complete_pair_count": complete,
                "missing_pair_count": len(group) - complete,
            }
        )
    return rows


def _frame_fingerprint(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    selected = frame.loc[:, list(columns)].copy()
    sort_columns = [
        field for field in ("trade_date", "vt_symbol") if field in selected.columns
    ]
    if sort_columns:
        selected = selected.sort_values(sort_columns, kind="stable")
    payload = [
        {field: _fingerprint_value(value) for field, value in row.items()}
        for row in selected.to_dict(orient="records")
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _fingerprint_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 12) if isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _coverage_status(phase_missing: dict[str, int]) -> str:
    for phase in ("validation", "calibration", "fit"):
        if phase_missing[phase]:
            return f"blocked_by_{'training' if phase == 'fit' else phase}_minute_coverage"
    return "ready"


def _study_row_identity(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("signal_date") or row.get("trade_date") or "")[:10],
        str(row.get("signal_time") or "")[:5],
        str(row.get("vt_symbol") or ""),
    )


def _study_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _study_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _study_mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _study_order_pair(row: Mapping[str, object]) -> tuple[str, date | None]:
    return (
        str(row.get("vt_symbol") or ""),
        _study_date(row.get("entry_date") or row.get("signal_date")),
    )


def _record_timing(timings: dict[str, float], field: str, started: float) -> float:
    now = monotonic()
    timings[field] = round(now - started, 3)
    return now


def _blocked_study_report(
    status: str,
    timings: Mapping[str, float],
) -> dict[str, object]:
    performance = dict(timings)
    performance.setdefault("total_seconds", round(sum(performance.values()), 3))
    return {
        "study_version": STUDY_VERSION,
        "status": status,
        "decision": "blocked_no_conclusion",
        "formal_strategy_changed": False,
        "requested_session_count": SESSION_COUNT,
        "performance": performance,
    }


def _stable_json_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _stable_canonical_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "signal_date": row.get("signal_date"),
            "signal_time": str(row.get("signal_time") or "")[:5],
            "vt_symbol": row.get("vt_symbol"),
            "sequence_features": dict(row.get("sequence_features") or {}),
        }
        for row in sorted(rows, key=_study_row_identity)
    ]


def _stable_action_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "signal_date": row.get("signal_date"),
            "signal_time": str(row.get("signal_time") or "")[:5],
            "vt_symbol": row.get("vt_symbol"),
            CANDIDATE_SCORE_FIELD: row.get(CANDIDATE_SCORE_FIELD),
            ACTION_SCORE_FIELD: row.get(ACTION_SCORE_FIELD),
        }
        for row in sorted(rows, key=_study_row_identity)
    ]


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _display_number(value: object) -> str:
    number = _study_number(value)
    return f"{number:.4f}" if number is not None else "-"


def _display_pct(value: object) -> str:
    number = _study_number(value)
    return f"{number:.2f}%" if number is not None else "-"


def _display_signed_pct(value: object) -> str:
    number = _study_number(value)
    return f"{number:+.2f}%" if number is not None else "-"


def _display_pct_ratio(value: object) -> str:
    number = _study_number(value)
    return f"{number * 100:.2f}%" if number is not None else "-"


if __name__ == "__main__":
    main()
