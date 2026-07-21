"""Frozen competing-risk study for causal pre-board action triggers."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
import json
from math import isfinite
from pathlib import Path
from statistics import mean, median

import pandas as pd

from alphaagent.server.services.limit_up import history_repository
from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    ACTION_SCORE_FIELD,
    COMPETING_FEATURE_NAMES,
    IDENTITY_TARGET_FIELD,
    TIMING_TARGET_FIELD,
    CompetingRiskModelFit,
    CompetingThresholdSelection,
    attach_competing_risk_targets,
    calibrate_competing_threshold,
    competing_feature_vector,
    enrich_same_minute_competition,
    fit_competing_risk_model,
    score_competing_risk_rows,
    select_confirmed_competing_signals,
)
from alphaagent.server.services.limit_up.preboard_hazard_data import (
    load_one_minute_bars,
    load_one_minute_coverage,
    load_static_hazard_manifest,
)
from alphaagent.server.services.limit_up.preboard_hazard_model import (
    HAZARD_FEATURE_NAMES,
)
from alphaagent.server.services.limit_up.preboard_reverse_profile import (
    trading_minutes_between,
)
from alphaagent.server.services.limit_up.preboard_strategy_study import (
    FEATURE_LOOKBACK_SESSIONS,
    _account_replay,
    _account_summary,
    _build_all_strategy_prefix_rows,
    _coverage_report,
    _early_order,
    _feature_index,
    _formal_orders,
    _load_bounded_feature_frame,
    _load_financial_index,
    compare_baseline_summaries,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


STUDY_VERSION = "limit-up-preboard-competing-risk-v2"
DEFAULT_SESSION_COUNT = 89
FIT_SESSION_COUNT = 44
CALIBRATION_SESSION_COUNT = 15
VALIDATION_SESSION_COUNT = 30
MINIMUM_CALIBRATION_SELECTIONS = 10
MINIMUM_EXACT_COVERAGE_PCT = 100.0
CONFIRMATION_MINUTES = 2
MAX_DAILY_FIRST_BOARD_ACTIONS = 2
ATTRIBUTION_PROFILE_FIELDS = (
    "identity_probability",
    "timing_probability",
    ACTION_SCORE_FIELD,
    "gain_pct",
    "support_score",
    "base_rank_score",
    "return_3m_pct",
    "prior_30m_floor_pct",
)


def build_competing_replay_orders(
    *,
    action_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_threshold: float,
    conservative_entry: bool = False,
) -> dict[str, list[dict[str, object]]]:
    """Build confirmed first-board orders alongside unchanged two-to-three orders."""

    action_signals = select_confirmed_competing_signals(
        action_rows,
        threshold=float(action_threshold),
        confirmation_minutes=CONFIRMATION_MINUTES,
        max_daily_actions=MAX_DAILY_FIRST_BOARD_ACTIONS,
    )
    early_orders = [
        order
        for signal in action_signals
        if (
            order := _competing_order(
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


def replay_competing_account(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    cost_multiplier: float = 1.0,
) -> dict[str, object]:
    """Replay through the unchanged formal two-position cash ledger."""

    return _account_replay(
        orders,
        bars,
        trade_dates,
        cost_multiplier=cost_multiplier,
    )


def split_competing_dates(
    dates: Sequence[date],
) -> tuple[tuple[date, ...], tuple[date, ...], tuple[date, ...]]:
    """Return the frozen 44/15/remainder chronological split."""

    ordered = tuple(sorted(set(dates)))
    fit_end = min(FIT_SESSION_COUNT, len(ordered))
    calibration_end = min(
        fit_end + CALIBRATION_SESSION_COUNT,
        len(ordered),
    )
    return (
        ordered[:fit_end],
        ordered[fit_end:calibration_end],
        ordered[calibration_end:],
    )


def prepare_forward_competing_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    maximum_quote_age_seconds: float = 60.0,
) -> list[dict[str, object]]:
    """Keep the first fresh frame per completed stock-minute and enrich it."""

    earliest: dict[tuple[str, str, str], dict[str, object]] = {}
    ordered = sorted(rows, key=_forward_row_key)
    for raw in ordered:
        row = dict(raw)
        if not _is_fresh_forward_row(
            row,
            maximum_quote_age_seconds=maximum_quote_age_seconds,
        ):
            continue
        key = (
            str(row.get("signal_date") or "")[:10],
            str(row.get("signal_time") or "")[:5],
            str(row.get("vt_symbol") or ""),
        )
        if all(key):
            earliest.setdefault(key, row)
    return enrich_same_minute_competition(list(earliest.values()))


def audit_minute_daily_consistency(
    manifest: pd.DataFrame,
    minute_rows: pd.DataFrame,
    *,
    expected_bar_count: int = 240,
) -> dict[str, object]:
    """Audit the entire scope without selecting pairs by their later outcome."""

    daily_columns = (
        "vt_symbol",
        "trade_date",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    )
    minute_columns = (*daily_columns[:2], "bar_time", *daily_columns[2:])
    missing_daily = sorted(set(daily_columns) - set(manifest.columns))
    missing_minute = sorted(set(minute_columns) - set(minute_rows.columns))
    if missing_daily or missing_minute:
        raise ValueError(
            "minute/daily consistency columns missing: "
            + ", ".join([*missing_daily, *missing_minute])
        )

    daily = manifest.loc[:, daily_columns].drop_duplicates(
        ["vt_symbol", "trade_date"]
    ).copy()
    minute = minute_rows.loc[:, minute_columns].copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.date
    minute["trade_date"] = pd.to_datetime(minute["trade_date"]).dt.date
    minute["bar_time"] = pd.to_datetime(minute["bar_time"])
    minute = minute.sort_values(["vt_symbol", "trade_date", "bar_time"])
    grouped = minute.groupby(["vt_symbol", "trade_date"], sort=False)
    aggregate = grouped.agg(
        bar_count=("bar_time", "size"),
        minute_high=("high_price", "max"),
        minute_low=("low_price", "min"),
        minute_volume=("volume", "sum"),
        minute_turnover=("turnover", "sum"),
    ).reset_index()
    closes = grouped.tail(1).loc[
        :, ["vt_symbol", "trade_date", "close_price"]
    ].rename(columns={"close_price": "minute_close"})
    aggregate = aggregate.merge(
        closes,
        on=["vt_symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    audited = daily.merge(
        aggregate,
        on=["vt_symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    numeric_columns = (
        *daily_columns[2:],
        "bar_count",
        "minute_high",
        "minute_low",
        "minute_close",
        "minute_volume",
        "minute_turnover",
    )
    for column in numeric_columns:
        audited[column] = pd.to_numeric(audited[column], errors="coerce")

    audited["high_abs_diff"] = (
        audited["minute_high"] - audited["high_price"]
    ).abs()
    audited["low_abs_diff"] = (
        audited["minute_low"] - audited["low_price"]
    ).abs()
    audited["close_abs_diff"] = (
        audited["minute_close"] - audited["close_price"]
    ).abs()
    audited["volume_unit_ratio"] = audited["minute_volume"] / audited["volume"]
    audited["turnover_ratio"] = audited["minute_turnover"] / audited["turnover"]
    audited["volume_unit_scale"] = audited["volume_unit_ratio"].map(
        _recognized_volume_unit_scale
    )
    audited["ready"] = (
        audited["bar_count"].eq(int(expected_bar_count))
        & audited["high_abs_diff"].le(0.011)
        & audited["low_abs_diff"].le(0.011)
        & audited["close_abs_diff"].le(0.011)
        & audited["volume_unit_scale"].notna()
        & audited["turnover_ratio"].sub(1.0).abs().le(0.001)
    )
    pair_count = len(audited)
    ready_count = int(audited["ready"].sum())
    invalid = audited.loc[~audited["ready"]]
    return {
        "pair_count": pair_count,
        "ready_pair_count": ready_count,
        "ready_pair_pct": round(ready_count / pair_count * 100, 4)
        if pair_count
        else 0.0,
        "expected_bar_count": int(expected_bar_count),
        "price_tolerance": 0.011,
        "accepted_volume_unit_ratios": [1.0, 100.0],
        "volume_ratio_tolerance": 0.01,
        "turnover_ratio_tolerance": 0.001,
        "volume_unit_ratio_median": _series_median(
            audited["volume_unit_ratio"]
        ),
        "volume_unit_scale_counts": {
            str(key): int(value)
            for key, value in audited["volume_unit_scale"].value_counts().items()
        },
        "turnover_ratio_median": _series_median(audited["turnover_ratio"]),
        "maximum_high_abs_diff": _series_max(audited["high_abs_diff"]),
        "maximum_low_abs_diff": _series_max(audited["low_abs_diff"]),
        "maximum_close_abs_diff": _series_max(audited["close_abs_diff"]),
        "invalid_examples": [
            {
                "vt_symbol": str(row.vt_symbol),
                "trade_date": row.trade_date.isoformat(),
                "bar_count": _optional_integer(row.bar_count),
                "high_abs_diff": _optional_float(row.high_abs_diff),
                "low_abs_diff": _optional_float(row.low_abs_diff),
                "close_abs_diff": _optional_float(row.close_abs_diff),
                "volume_unit_ratio": _optional_float(row.volume_unit_ratio),
                "turnover_ratio": _optional_float(row.turnover_ratio),
            }
            for row in invalid.head(20).itertuples()
        ],
    }


def build_competing_analysis(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
    baseline_parity: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, CompetingRiskModelFit]]:
    """Fit the frozen heads and replay their confirmed action policy."""

    labeled_rows = attach_competing_risk_targets(prefix_rows, formal_orders)
    enriched_rows = enrich_same_minute_competition(labeled_rows)
    identity_model = fit_competing_risk_model(
        enriched_rows,
        fit_dates=fit_dates,
        target_field=IDENTITY_TARGET_FIELD,
    )
    timing_model = fit_competing_risk_model(
        enriched_rows,
        fit_dates=fit_dates,
        target_field=TIMING_TARGET_FIELD,
    )
    scored_rows = score_competing_risk_rows(
        enriched_rows,
        identity_model,
        timing_model,
    )
    threshold = calibrate_competing_threshold(
        scored_rows,
        calibration_dates=calibration_dates,
        minimum_selection_count=MINIMUM_CALIBRATION_SELECTIONS,
    )
    action_threshold = threshold.threshold if threshold.threshold is not None else 1.1
    normal_bundle = build_competing_replay_orders(
        action_rows=scored_rows,
        formal_orders=formal_orders,
        action_threshold=action_threshold,
    )
    conservative_bundle = build_competing_replay_orders(
        action_rows=scored_rows,
        formal_orders=formal_orders,
        action_threshold=action_threshold,
        conservative_entry=True,
    )

    all_dates = fit_dates | calibration_dates | validation_dates
    phase_dates = {"full": all_dates, "validation": validation_dates}
    phases: dict[str, dict[str, object]] = {}
    for phase, allowed_dates in phase_dates.items():
        phases[phase] = {
            "identity": _identity_report(
                enriched_rows,
                formal_orders,
                normal_bundle["action_signals"],
                allowed_dates=allowed_dates,
            ),
            "accounts": _phase_accounts(
                formal_orders=formal_orders,
                action_orders=normal_bundle["combined_orders"],
                conservative_orders=conservative_bundle["combined_orders"],
                bars=bars,
                trade_dates=trade_dates,
                allowed_dates=allowed_dates,
            ),
            "account_identity": _account_identity_report(
                formal_orders=formal_orders,
                action_orders=normal_bundle["combined_orders"],
                bars=bars,
                trade_dates=trade_dates,
                allowed_dates=allowed_dates,
            ),
            "account_path_attribution": build_account_path_attribution(
                formal_orders=formal_orders,
                action_orders=normal_bundle["combined_orders"],
                bars=bars,
                trade_dates=trade_dates,
                allowed_dates=allowed_dates,
                observation_rows=enriched_rows,
                scored_rows=scored_rows,
                selected_signals=normal_bundle["action_signals"],
                action_threshold=action_threshold,
            ),
        }

    validation_blocks = []
    for index, block_dates in enumerate(_fixed_validation_blocks(validation_dates), start=1):
        block_set = set(block_dates)
        validation_blocks.append(
            {
                "block": index,
                "date_range": _date_range(block_dates),
                "identity": _identity_report(
                    enriched_rows,
                    formal_orders,
                    normal_bundle["action_signals"],
                    allowed_dates=block_set,
                ),
                "account_identity": _account_identity_report(
                    formal_orders=formal_orders,
                    action_orders=normal_bundle["combined_orders"],
                    bars=bars,
                    trade_dates=trade_dates,
                    allowed_dates=block_set,
                ),
                "accounts": _phase_accounts(
                    formal_orders=formal_orders,
                    action_orders=normal_bundle["combined_orders"],
                    conservative_orders=conservative_bundle["combined_orders"],
                    bars=bars,
                    trade_dates=trade_dates,
                    allowed_dates=block_set,
                ),
            }
        )

    acceptance = _acceptance_report(
        phases.get("validation", {}),
        validation_blocks=validation_blocks,
        models=(identity_model, timing_model),
        threshold=threshold,
        baseline_parity=baseline_parity,
    )
    return {
        "dataset": _dataset_report(enriched_rows),
        "models": {
            "identity": _model_report(identity_model),
            "timing_3m": _model_report(timing_model),
        },
        "threshold_selection": _threshold_report(threshold),
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
    }, {"identity": identity_model, "timing_3m": timing_model}


def evaluate_preboard_competing_risk(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
) -> dict[str, object]:
    """Load the bounded 89-session scope and enforce every historical gate."""

    manifest = load_static_hazard_manifest(session_count=session_count)
    if manifest.empty:
        return _blocked_report("blocked_by_manifest", session_count=session_count)
    coverage = load_one_minute_coverage(manifest)
    coverage_report = _coverage_report(manifest, coverage)
    if float(coverage_report["complete_pair_pct"]) < MINIMUM_EXACT_COVERAGE_PCT:
        return {
            **_blocked_report(
                "blocked_by_one_minute_coverage",
                session_count=session_count,
            ),
            "coverage": coverage_report,
            "next_data_task": "sync_limit_up_preboard_hazard_minutes",
        }

    dates = sorted(pd.to_datetime(manifest["trade_date"]).dt.date.unique())
    fit_dates, calibration_dates, validation_dates = split_competing_dates(dates)
    if (
        len(fit_dates) != FIT_SESSION_COUNT
        or len(calibration_dates) != CALIBRATION_SESSION_COUNT
        or len(validation_dates) != VALIDATION_SESSION_COUNT
    ):
        return {
            **_blocked_report(
                "blocked_by_frozen_date_split",
                session_count=session_count,
            ),
            "coverage": coverage_report,
            "date_split": _date_split_report(
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
        if start <= (_optional_date(day.get("trade_date")) or date.min) <= end
    ]
    complete_pairs = {
        (str(row.vt_symbol), _as_date(row.trade_date))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    minute_rows = load_one_minute_bars(manifest)
    daily_consistency = audit_minute_daily_consistency(manifest, minute_rows)
    if float(daily_consistency["ready_pair_pct"]) < 99.5:
        return {
            **_blocked_report(
                "blocked_by_minute_daily_inconsistency",
                session_count=session_count,
            ),
            "coverage": coverage_report,
            "minute_daily_consistency": daily_consistency,
        }
    feature_frame, feature_coverage = _load_bounded_feature_frame(
        manifest,
        lookback_sessions=FEATURE_LOOKBACK_SESSIONS,
    )
    feature_by_pair = _feature_index(feature_frame, set(dates))
    prefix_rows, filter_audit = _build_all_strategy_prefix_rows(
        manifest,
        minute_rows,
        complete_pairs,
        feature_by_pair,
        _load_financial_index(),
        bar_minutes=1,
        passed_only=True,
        row_projection=_project_competing_row,
    )
    formal_orders, profitability_audit = _formal_orders(
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
        if (parsed := _optional_date(value)) is not None
    ]
    result_dates.extend(
        parsed
        for order in formal_orders
        if (parsed := _optional_date(order.get("result_date"))) is not None
    )
    account_end = max(result_dates, default=end)
    bars = history_repository.load_account_daily_bars(symbols, start, account_end)

    from alphaagent.server.services.limit_up.history_service import (
        get_scheduled_history_backtest,
    )
    from alphaagent.server.services.limit_up.preboard_momentum_data import (
        load_reliable_trade_dates,
    )

    trade_dates = load_reliable_trade_dates(start, account_end)
    service_baseline = get_scheduled_history_backtest(start, end, trade_limit=None)
    baseline_summary = _account_summary(
        formal_orders,
        bars,
        trade_dates,
        cost_multiplier=1.0,
    )
    baseline_parity = compare_baseline_summaries(
        _mapping(service_baseline.get("summary")),
        baseline_summary,
    )
    if baseline_parity.get("passed") is not True:
        return {
            **_blocked_report(
                "blocked_by_baseline_mismatch",
                session_count=session_count,
            ),
            "coverage": {**coverage_report, **feature_coverage},
            "baseline_parity": baseline_parity,
        }

    analysis, models = build_competing_analysis(
        prefix_rows,
        formal_orders,
        bars,
        trade_dates,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
        baseline_parity=baseline_parity,
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
            "identity_target": IDENTITY_TARGET_FIELD,
            "timing_target": TIMING_TARGET_FIELD,
            "action_score": "identity_probability * timing_probability",
            "confirmation_minutes": CONFIRMATION_MINUTES,
            "maximum_daily_first_board_actions": MAX_DAILY_FIRST_BOARD_ACTIONS,
            "entry": "next_one_minute_open_strictly_below_limit",
            "exit": "d1_official_close",
            "execution_effect": "none_research_only",
        },
        "date_split": _date_split_report(
            fit_dates,
            calibration_dates,
            validation_dates,
        ),
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
            "89日中的后30日已被此前研究查看，只能称扩展历史时间验证，不是新的锁定留出。",
            "TDX一分钟K线不是Tick/L2，不能证明主动大单方向、排队、撤单或秒级成交。",
            "历史没有完整点时动态概念、行业扩散、资金流和快照新鲜度，这些字段只允许前向保存。",
            "历史门通过也只允许冻结前向影子；正式v9/v15保持不变。",
        ],
    }


def render_competing_markdown(report: Mapping[str, object]) -> str:
    """Render the frozen evidence in a compact durable report."""

    if not str(report.get("status") or "").startswith("ready_"):
        return _render_blocked_markdown(report)
    lines = [
        "# 首板双阶段竞争风险触发研究",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status')}`；结论：`{report.get('decision')}`。",
        f"- 研究版本：`{report.get('study_version')}`；正式策略修改：`False`。",
        f"- 验证性质：`{report.get('historical_validation_kind')}`。",
    ]
    coverage = _mapping(report.get("coverage"))
    lines.append(
        f"- 一分钟完整覆盖：{coverage.get('complete_pair_count', 0)}/"
        f"{coverage.get('manifest_pair_count', 0)}（{_pct(coverage.get('complete_pair_pct'))}）。"
    )
    dataset = _mapping(report.get("dataset"))
    daily_candidates = _mapping(dataset.get("candidate_pairs_per_day"))
    lines.append(
        f"- 共用规则后股票日：{dataset.get('candidate_pair_count', 0)}；"
        f"每日中位 {daily_candidates.get('median') or 0}，最多 "
        f"{daily_candidates.get('maximum') or 0}。"
    )
    lines.append(
        f"- 同刻多股竞争分钟：{dataset.get('multi_candidate_minute_count', 0)}；"
        f"同刻最多 {dataset.get('maximum_candidates_in_one_minute', 0)} 只。"
    )
    consistency = _mapping(report.get("minute_daily_consistency"))
    lines.append(
        f"- 分钟/日线数值一致：{consistency.get('ready_pair_count', 0)}/"
        f"{consistency.get('pair_count', 0)}（{_pct(consistency.get('ready_pair_pct'))}）。"
    )

    lines.extend(["", "## Frozen models", ""])
    lines.append("| 模型 | 状态 | 训练股票日 | 指纹 |")
    lines.append("| --- | --- | ---: | --- |")
    for key, label in (("identity", "正式身份"), ("timing_3m", "3分钟到板")):
        model = _mapping(_mapping(report.get("models")).get(key))
        lines.append(
            f"| {label} | `{model.get('status')}` | "
            f"{model.get('training_pair_count', 0)} | `{model.get('fingerprint') or '-'}` |"
        )
    for key, label in (("identity", "正式身份"), ("timing_3m", "3分钟到板")):
        model = _mapping(_mapping(report.get("models")).get(key))
        coefficient_summary = _mapping(model.get("coefficient_summary"))
        lines.append(
            f"- {label}主要正向标准化系数："
            f"{_coefficient_entries(coefficient_summary.get('positive'))}；"
            f"主要负向：{_coefficient_entries(coefficient_summary.get('negative'))}。"
        )
    threshold = _mapping(report.get("threshold_selection"))
    lines.extend(
        [
            "",
            f"- 校准阈值：{_display(threshold.get('threshold'))}；状态："
            f"`{threshold.get('status')}`。",
            "",
            "## Same-account validation",
            "",
            "| 方案 | 信号 | 身份精度 | 3分钟命中 | 可达召回 | 成交 | 胜率 | 复利 | 回撤 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    validation = _mapping(_mapping(report.get("phases")).get("validation"))
    identity = _mapping(validation.get("identity"))
    account_identity = _mapping(validation.get("account_identity"))
    accounts = _mapping(validation.get("accounts"))
    variants = (
        ("当前触板基线", "formal_touch", False),
        ("双阶段确认行动", "competing_action", True),
        ("双阶段行动-双倍成本", "competing_action_double_cost", True),
        ("双阶段行动-保守成交", "competing_action_conservative", True),
    )
    for label, key, is_action in variants:
        account = _mapping(accounts.get(key))
        lines.append(
            f"| {label} | {identity.get('selection_count', 0) if is_action else '-'} | "
            f"{_pct(identity.get('formal_identity_precision_pct')) if is_action else '-'} | "
            f"{_pct(identity.get('horizon_precision_pct')) if is_action else '-'} | "
            f"{_pct(identity.get('reachable_formal_recall_pct')) if is_action else '-'} | "
            f"{account.get('trade_count', 0)} | {_pct(account.get('win_rate'))} | "
            f"{_signed_pct(account.get('total_return_pct'))} | "
            f"{_signed_pct(account.get('max_drawdown_pct'))} |"
        )
    lines.append("")
    lines.append(
        f"- 原账户成交身份精度/召回：{_pct(account_identity.get('precision_pct'))}/"
        f"{_pct(account_identity.get('recall_pct'))}。"
    )
    lines.extend(
        _render_account_path_attribution(
            _mapping(validation.get("account_path_attribution"))
        )
    )
    lines.extend(["", "## Validation blocks", ""])
    lines.append("| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for block in report.get("validation_blocks") or []:
        block = _mapping(block)
        date_range = _mapping(block.get("date_range"))
        block_identity = _mapping(block.get("identity"))
        block_account = _mapping(
            _mapping(block.get("accounts")).get("competing_action")
        )
        lines.append(
            f"| {block.get('block')} | {date_range.get('start')}..{date_range.get('end')} | "
            f"{block_identity.get('selection_count', 0)} | "
            f"{block_account.get('trade_count', 0)} | "
            f"{_pct(block_account.get('win_rate'))} | "
            f"{_signed_pct(block_account.get('total_return_pct'))} | "
            f"{_signed_pct(block_account.get('max_drawdown_pct'))} |"
        )

    acceptance = _mapping(report.get("acceptance"))
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- 历史门禁：`{'PASS' if acceptance.get('passed') is True else 'FAIL'}`。",
        ]
    )
    for name, passed in _mapping(acceptance.get("checks")).items():
        lines.append(f"- `{name}`：{'通过' if passed is True else '未通过'}。")
    forward = _mapping(report.get("forward_validation"))
    lines.extend(
        [
            "",
            "## Forward validation",
            "",
            f"- 状态：`{forward.get('status')}`；交易日 "
            f"{forward.get('trade_day_count', 0)}，雷达帧 {forward.get('frame_count', 0)}。",
            "- 正式执行影响固定为 `none_research_only`。",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("limitations") or [])
    return "\n".join(lines) + "\n"


def _render_account_path_attribution(
    attribution: Mapping[str, object],
) -> list[str]:
    if not attribution:
        return []
    categories = _mapping(attribution.get("action_filled_categories"))
    lines = [
        "",
        "## Account-path attribution",
        "",
        "| 类别 | 股票日 | 触板/封板 | 闭合 | 胜率 | 平均收益 | 净损益 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category in (
        "matched_original_account",
        "formal_identity_true_but_not_original_account",
        "formal_identity_false_positive",
    ):
        summary = _mapping(categories.get(category))
        lines.append(
            f"| `{category}` | {summary.get('pair_count', 0)} | "
            f"{summary.get('eventually_touched_count', 0)}/"
            f"{summary.get('eventually_sealed_count', 0)} | "
            f"{summary.get('closed_trade_count', 0)} | "
            f"{_pct(summary.get('win_rate_pct'))} | "
            f"{_signed_pct(summary.get('average_return_pct'))} | "
            f"{_signed_number(summary.get('total_net_pnl'))} |"
        )
    profiles = _mapping(attribution.get("action_filled_feature_profiles"))
    if profiles:
        lines.extend(
            [
                "",
                "| 类别 | 涨幅中位 | identity P | timing P | action score | support | 原Rank | 3分钟收益 | 30分钟底部 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for category in (
            "matched_original_account",
            "formal_identity_true_but_not_original_account",
            "formal_identity_false_positive",
        ):
            profile = _mapping(profiles.get(category))
            lines.append(
                f"| `{category}` | {_signed_pct(_profile_median(profile, 'gain_pct'))} | "
                f"{_display(_profile_median(profile, 'identity_probability'))} | "
                f"{_display(_profile_median(profile, 'timing_probability'))} | "
                f"{_display(_profile_median(profile, ACTION_SCORE_FIELD))} | "
                f"{_display(_profile_median(profile, 'support_score'))} | "
                f"{_display(_profile_median(profile, 'base_rank_score'))} | "
                f"{_signed_pct(_profile_median(profile, 'return_3m_pct'))} | "
                f"{_signed_pct(_profile_median(profile, 'prior_30m_floor_pct'))} |"
            )
    missed = _mapping(attribution.get("missed_original_account"))
    position_path = _mapping(attribution.get("position_path"))
    matched = _mapping(attribution.get("matched_trade_comparison"))
    lines.extend(
        [
            "",
            f"- 原账户已成交但提前账户未成交：{missed.get('pair_count', 0)} 个股票日；"
            f"归因 `{json.dumps(missed.get('category_counts') or {}, ensure_ascii=False)}`。",
            f"- 提前首板因仓位上限跳过："
            f"{position_path.get('action_order_position_limit_count', 0)}；其中正式候选 "
            f"{position_path.get('formal_candidate_signal_blocked_by_position_limit_count', 0)}，"
            f"原账户身份 "
            f"{position_path.get('original_account_signal_blocked_by_position_limit_count', 0)}。",
            f"- 同一账户身份闭合 {matched.get('closed_both_count', 0)} 笔；"
            f"提前相对触板平均收益差 "
            f"{_signed_pct(matched.get('average_return_delta_pct'))}。",
        ]
    )
    divergent = [
        _mapping(row)
        for row in attribution.get("early_order_ledger") or []
        if isinstance(row, Mapping)
        and row.get("execution_status") == "filled"
        and row.get("category") != "filled_matched_original_account"
    ]
    if divergent:
        lines.extend(
            [
                "",
                "### Filled divergence ledger",
                "",
                "| 日期 | 股票 | 类别 | D+1净收益 |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for row in divergent:
            lines.append(
                f"| {row.get('trade_date')} | {row.get('vt_symbol')} | "
                f"`{row.get('category')}` | {_signed_pct(row.get('return_pct'))} |"
            )
    missed_ledger = [
        _mapping(row)
        for row in missed.get("ledger") or []
        if isinstance(row, Mapping)
    ]
    if missed_ledger:
        lines.extend(
            [
                "",
                "### Missed original-account ledger",
                "",
                "| 日期 | 股票 | 原因 | 最高action score | 首次确认 | 原触板账户收益 |",
                "| --- | --- | --- | ---: | --- | ---: |",
            ]
        )
        for row in missed_ledger:
            diagnostic = _mapping(row.get("selection_diagnostic"))
            lines.append(
                f"| {row.get('trade_date')} | {row.get('vt_symbol')} | "
                f"`{row.get('category')}` | "
                f"{_display(diagnostic.get('maximum_action_score'))} | "
                f"{diagnostic.get('first_confirmation_time') or '-'} | "
                f"{_signed_pct(row.get('formal_return_pct'))} |"
            )
    return lines


def _competing_order(
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
    base_rank = _number(signal.get("rank_score"))
    action_score = _number(signal.get(ACTION_SCORE_FIELD))
    order = _early_order({**dict(signal), "entry_price": entry_price})
    return {
        **order,
        "algorithm": "formal_identity_x_3m_timing_confirmed",
        "identity_probability": _number(signal.get("identity_probability")),
        "timing_probability": _number(signal.get("timing_probability")),
        ACTION_SCORE_FIELD: action_score,
        "base_rank_score": base_rank,
        "rank_score": round((action_score or 0.0) * 100, 6),
        "confirmation_minutes": CONFIRMATION_MINUTES,
        "conservative_entry": conservative_entry,
        "candidate_source": "all_3pct_shared_strategy_1m_competing_risk",
    }


def _project_competing_row(row: Mapping[str, object]) -> dict[str, object]:
    features = row.get("features")
    features = features if isinstance(features, Mapping) else {}
    return {
        key: row.get(key)
        for key in (
            "vt_symbol",
            "name",
            "signal_date",
            "result_date",
            "signal_at",
            "signal_time",
            "signal_price",
            "entry_at",
            "entry_time",
            "entry_price",
            "limit_price",
            "fillable",
            "before_first_limit_touch",
            "touched_limit",
            "sealed_limit",
            "d1_close_price",
            "support_score",
            "entry_quality_score",
            "rank_score",
            "shared_strategy_passed",
            "profitability_gate_sample_count",
            "profitability_gate_combined_rate",
            "net_return_pct",
        )
    } | {
        "features": {
            field: features.get(field)
            for field in HAZARD_FEATURE_NAMES
            if field not in {"support_score", "entry_quality_score"}
        }
    }


def _phase_accounts(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
) -> dict[str, object]:
    formal = _orders_on_dates(formal_orders, allowed_dates)
    action = _orders_on_dates(action_orders, allowed_dates)
    conservative = _orders_on_dates(conservative_orders, allowed_dates)
    relay = [order for order in formal if str(order.get("lane") or "") == "two_to_three"]
    early = [
        order
        for order in action
        if str(order.get("algorithm") or "")
        == "formal_identity_x_3m_timing_confirmed"
    ]
    return {
        "formal_touch": _account_metrics(formal, bars, trade_dates),
        "two_to_three_only": _account_metrics(relay, bars, trade_dates),
        "early_first_board_only": _account_metrics(early, bars, trade_dates),
        "competing_action": _account_metrics(action, bars, trade_dates),
        "competing_action_double_cost": _account_metrics(
            action,
            bars,
            trade_dates,
            cost_multiplier=2.0,
        ),
        "competing_action_conservative": _account_metrics(
            conservative,
            bars,
            trade_dates,
        ),
    }


def _account_metrics(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    cost_multiplier: float = 1.0,
) -> dict[str, object]:
    account = replay_competing_account(
        orders,
        bars,
        trade_dates,
        cost_multiplier=cost_multiplier,
    )
    summary = dict(account["execution_summary"])
    skipped = [
        order
        for order in account["orders"]
        if order.get("side") == "BUY"
        and order.get("lane") == "first_board"
        and order.get("status") == "skipped"
    ]
    return {
        **summary,
        "early_first_board_conflict_count": len(skipped),
        "early_first_board_conflict_reasons": dict(
            Counter(str(order.get("reason") or "unknown") for order in skipped)
        ),
    }


def _account_identity_report(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
) -> dict[str, object]:
    formal_account = replay_competing_account(
        _orders_on_dates(formal_orders, allowed_dates),
        bars,
        trade_dates,
    )
    action_account = replay_competing_account(
        _orders_on_dates(action_orders, allowed_dates),
        bars,
        trade_dates,
    )
    formal_pairs = _filled_first_board_pairs(formal_account)
    action_pairs = _filled_first_board_pairs(action_account)
    matched = formal_pairs & action_pairs
    return {
        "formal_filled_first_board_count": len(formal_pairs),
        "action_filled_first_board_count": len(action_pairs),
        "matched_filled_first_board_count": len(matched),
        "precision_pct": _percentage(len(matched), len(action_pairs)),
        "recall_pct": _percentage(len(matched), len(formal_pairs)),
    }


def build_account_path_attribution(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
    observation_rows: Sequence[Mapping[str, object]] = (),
    scored_rows: Sequence[Mapping[str, object]] = (),
    selected_signals: Sequence[Mapping[str, object]] = (),
    action_threshold: float | None = None,
    confirmation_minutes: int = CONFIRMATION_MINUTES,
) -> dict[str, object]:
    """Explain filled-identity mismatch without changing the frozen replay."""

    formal_scope = _orders_on_dates(formal_orders, allowed_dates)
    action_scope = _orders_on_dates(action_orders, allowed_dates)
    formal_account = replay_competing_account(formal_scope, bars, trade_dates)
    action_account = replay_competing_account(action_scope, bars, trade_dates)
    formal_candidate_pairs = {
        _order_pair(order)
        for order in formal_scope
        if str(order.get("lane") or "") == "first_board"
    }
    formal_filled_pairs = _filled_first_board_pairs(formal_account)
    action_filled_pairs = _filled_first_board_pairs(action_account)
    matched_pairs = formal_filled_pairs & action_filled_pairs
    action_only_pairs = action_filled_pairs - formal_filled_pairs
    formal_only_pairs = formal_filled_pairs - action_filled_pairs
    action_order_index = _first_board_source_order_index(action_scope)
    action_execution_index = _first_board_buy_order_index(action_account)
    action_trade_index = _first_board_trade_index(action_account)
    formal_trade_index = _first_board_trade_index(formal_account)
    category_pairs = {
        "matched_original_account": matched_pairs,
        "formal_identity_true_but_not_original_account": (
            action_only_pairs & formal_candidate_pairs
        ),
        "formal_identity_false_positive": (
            action_only_pairs - formal_candidate_pairs
        ),
    }
    selection_diagnostics = diagnose_signal_selection_failures(
        formal_only_pairs,
        observation_rows=observation_rows,
        scored_rows=scored_rows,
        selected_signals=selected_signals,
        threshold=action_threshold,
        confirmation_minutes=confirmation_minutes,
        max_daily_actions=MAX_DAILY_FIRST_BOARD_ACTIONS,
    )
    missed_ledger = _missed_original_account_ledger(
        formal_only_pairs,
        action_order_index=action_order_index,
        action_execution_index=action_execution_index,
        formal_trade_index=formal_trade_index,
        selection_diagnostics=selection_diagnostics,
    )
    early_order_ledger = _early_order_attribution_ledger(
        action_order_index,
        execution_index=action_execution_index,
        trade_index=action_trade_index,
        formal_candidate_pairs=formal_candidate_pairs,
        formal_filled_pairs=formal_filled_pairs,
    )
    position_limited = [
        row
        for row in early_order_ledger
        if row.get("execution_reason") == "position_limit"
    ]
    return {
        "path_counts": {
            "formal_candidate_pair_count": len(formal_candidate_pairs),
            "formal_filled_pair_count": len(formal_filled_pairs),
            "action_order_pair_count": len(action_order_index),
            "action_filled_pair_count": len(action_filled_pairs),
            "matched_filled_pair_count": len(matched_pairs),
            "action_only_filled_pair_count": len(action_only_pairs),
            "formal_only_filled_pair_count": len(formal_only_pairs),
        },
        "selection_confirmation_minutes": max(int(confirmation_minutes), 1),
        "action_filled_categories": {
            category: {
                **_pair_outcome_summary(pairs, action_trade_index),
                **_pair_source_outcome_summary(pairs, action_order_index),
            }
            for category, pairs in category_pairs.items()
        },
        "action_filled_feature_profiles": _action_feature_profiles(
            category_pairs,
            action_order_index,
        ),
        "missed_original_account": {
            **_pair_outcome_summary(formal_only_pairs, formal_trade_index),
            "category_counts": dict(
                sorted(
                    Counter(str(row["category"]) for row in missed_ledger).items()
                )
            ),
            "ledger": missed_ledger,
        },
        "position_path": {
            "action_order_position_limit_count": len(position_limited),
            "formal_candidate_signal_blocked_by_position_limit_count": sum(
                row.get("formal_candidate_identity") is True
                for row in position_limited
            ),
            "original_account_signal_blocked_by_position_limit_count": sum(
                row.get("original_account_identity") is True
                for row in position_limited
            ),
        },
        "matched_trade_comparison": _matched_trade_comparison(
            matched_pairs,
            action_trade_index=action_trade_index,
            formal_trade_index=formal_trade_index,
        ),
        "early_order_ledger": early_order_ledger,
    }


def diagnose_signal_selection_failures(
    pairs: set[tuple[str, date]],
    *,
    observation_rows: Sequence[Mapping[str, object]],
    scored_rows: Sequence[Mapping[str, object]],
    selected_signals: Sequence[Mapping[str, object]],
    threshold: float | None,
    confirmation_minutes: int,
    max_daily_actions: int,
) -> dict[tuple[str, date], dict[str, object]]:
    """Locate the first causal stage that prevented an action signal."""

    observation_by_pair = _rows_by_requested_pair(observation_rows, pairs)
    scored_by_pair = _rows_by_requested_pair(scored_rows, pairs)
    selected_pairs = {_order_pair(row) for row in selected_signals}
    selected_by_date: dict[date, list[Mapping[str, object]]] = defaultdict(list)
    for row in selected_signals:
        selected_by_date[_order_date(row)].append(row)
    result: dict[tuple[str, date], dict[str, object]] = {}
    for pair in sorted(pairs, key=lambda value: (value[1], value[0])):
        observations = observation_by_pair.get(pair, [])
        scored = scored_by_pair.get(pair, [])
        common = {
            "eligible_prefix_count": len(observations),
            "scoreable_prefix_count": len(scored),
            "maximum_action_score": _maximum_feature(scored, ACTION_SCORE_FIELD),
        }
        if pair in selected_pairs:
            result[pair] = {**common, "category": "action_signal_selected"}
            continue
        if not observations:
            result[pair] = {
                **common,
                "category": "no_eligible_preboard_prefix",
            }
            continue
        if not scored:
            result[pair] = {**common, "category": "no_scoreable_model_prefix"}
            continue
        if threshold is None:
            result[pair] = {**common, "category": "action_threshold_unavailable"}
            continue
        passing = [
            row
            for row in scored
            if (_number(row.get(ACTION_SCORE_FIELD)) or -1.0) >= threshold
        ]
        first_confirmation = _first_confirmation_time(
            scored,
            threshold=threshold,
            confirmation_minutes=confirmation_minutes,
        )
        details = {
            **common,
            "above_threshold_prefix_count": len(passing),
            "first_above_threshold_time": (
                min(str(row.get("signal_time") or "") for row in passing)
                if passing
                else None
            ),
            "first_confirmation_time": first_confirmation,
        }
        if not passing:
            result[pair] = {
                **details,
                "category": "score_below_action_threshold",
            }
            continue
        if first_confirmation is None:
            result[pair] = {
                **details,
                "category": "threshold_not_confirmed_two_minutes",
            }
            continue
        day_selections = selected_by_date.get(pair[1], [])
        earlier_count = sum(
            str(row.get("signal_time") or "") < first_confirmation
            for row in day_selections
        )
        through_confirmation_count = sum(
            str(row.get("signal_time") or "") <= first_confirmation
            for row in day_selections
        )
        daily_limit = max(int(max_daily_actions), 1)
        if earlier_count >= daily_limit:
            category = "daily_action_slots_already_filled"
        elif through_confirmation_count >= daily_limit:
            category = "same_minute_competition_lost"
        else:
            category = "confirmed_not_selected_unexpected"
        result[pair] = {**details, "category": category}
    return result


def _rows_by_requested_pair(
    rows: Sequence[Mapping[str, object]],
    pairs: set[tuple[str, date]],
) -> dict[tuple[str, date], list[Mapping[str, object]]]:
    grouped: dict[tuple[str, date], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        pair = _order_pair(row)
        if pair in pairs:
            grouped[pair].append(row)
    for pair_rows in grouped.values():
        pair_rows.sort(key=lambda row: str(row.get("signal_time") or ""))
    return grouped


def _first_confirmation_time(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    confirmation_minutes: int,
) -> str | None:
    required = max(int(confirmation_minutes), 1)
    streak = 0
    previous_time: str | None = None
    for row in sorted(rows, key=lambda value: str(value.get("signal_time") or "")):
        score = _number(row.get(ACTION_SCORE_FIELD))
        current_time = str(row.get("signal_time") or "")
        if score is None or score < threshold:
            streak = 0
            previous_time = None
            continue
        consecutive = (
            previous_time is not None
            and trading_minutes_between(previous_time, current_time) == 1.0
        )
        streak = streak + 1 if consecutive else 1
        previous_time = current_time
        if streak >= required:
            return current_time
    return None


def _maximum_feature(
    rows: Sequence[Mapping[str, object]],
    field: str,
) -> float | None:
    values = [
        value
        for row in rows
        if (value := _feature_number(row, field)) is not None
    ]
    return round(max(values), 8) if values else None


def _first_board_source_order_index(
    orders: Sequence[Mapping[str, object]],
) -> dict[tuple[str, date], dict[str, object]]:
    return {
        _order_pair(order): dict(order)
        for order in orders
        if str(order.get("lane") or "") == "first_board"
    }


def _first_board_buy_order_index(
    account: Mapping[str, object],
) -> dict[tuple[str, date], dict[str, object]]:
    rows = account.get("orders")
    orders = rows if isinstance(rows, list) else []
    return {
        (
            str(order.get("vt_symbol") or ""),
            _as_date(order.get("trade_date")),
        ): dict(order)
        for order in orders
        if isinstance(order, Mapping)
        and order.get("side") == "BUY"
        and str(order.get("lane") or "") == "first_board"
    }


def _first_board_trade_index(
    account: Mapping[str, object],
) -> dict[tuple[str, date], dict[str, object]]:
    rows = account.get("executed_trades")
    trades = rows if isinstance(rows, list) else []
    return {
        (
            str(trade.get("vt_symbol") or ""),
            _as_date(trade.get("entry_date") or trade.get("buy_date")),
        ): dict(trade)
        for trade in trades
        if isinstance(trade, Mapping)
        and str(trade.get("lane") or "") == "first_board"
    }


def _pair_outcome_summary(
    pairs: set[tuple[str, date]],
    trade_index: Mapping[tuple[str, date], Mapping[str, object]],
) -> dict[str, object]:
    trades = [trade_index[pair] for pair in sorted(pairs) if pair in trade_index]
    returns = [
        value
        for trade in trades
        if (value := _number(trade.get("return_pct"))) is not None
    ]
    net_pnls = [
        value
        for trade in trades
        if (value := _number(trade.get("net_pnl"))) is not None
    ]
    return {
        "pair_count": len(pairs),
        "closed_trade_count": len(trades),
        "win_count": sum(value > 0 for value in returns),
        "win_rate_pct": _percentage(sum(value > 0 for value in returns), len(returns)),
        "average_return_pct": round(mean(returns), 4) if returns else None,
        "total_net_pnl": round(sum(net_pnls), 4) if net_pnls else None,
    }


def _pair_source_outcome_summary(
    pairs: set[tuple[str, date]],
    source_index: Mapping[tuple[str, date], Mapping[str, object]],
) -> dict[str, object]:
    touched = [
        value
        for pair in pairs
        if pair in source_index
        and (value := _source_outcome_flag(source_index[pair], "touched")) is not None
    ]
    sealed = [
        value
        for pair in pairs
        if pair in source_index
        and (value := _source_outcome_flag(source_index[pair], "sealed")) is not None
    ]
    return {
        "eventually_touched_count": sum(touched),
        "eventually_touched_rate_pct": _percentage(sum(touched), len(touched)),
        "eventually_sealed_count": sum(sealed),
        "eventually_sealed_rate_pct": _percentage(sum(sealed), len(sealed)),
    }


def _source_outcome_flag(
    source: Mapping[str, object],
    field: str,
) -> bool | None:
    direct_field = "touched_limit" if field == "touched" else "sealed_limit"
    direct = source.get(direct_field)
    if direct is not None:
        return bool(direct)
    outcome = source.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    value = outcome.get(field)
    return bool(value) if value is not None else None


def _action_feature_profiles(
    category_pairs: Mapping[str, set[tuple[str, date]]],
    source_index: Mapping[tuple[str, date], Mapping[str, object]],
) -> dict[str, dict[str, dict[str, float | int | None]]]:
    return {
        category: {
            field: _distribution(
                [
                    value
                    for pair in pairs
                    if pair in source_index
                    and (value := _feature_number(source_index[pair], field))
                    is not None
                ]
            )
            for field in ATTRIBUTION_PROFILE_FIELDS
        }
        for category, pairs in category_pairs.items()
    }


def _missed_original_account_ledger(
    pairs: set[tuple[str, date]],
    *,
    action_order_index: Mapping[tuple[str, date], Mapping[str, object]],
    action_execution_index: Mapping[tuple[str, date], Mapping[str, object]],
    formal_trade_index: Mapping[tuple[str, date], Mapping[str, object]],
    selection_diagnostics: Mapping[
        tuple[str, date], Mapping[str, object]
    ],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for symbol, trade_date in sorted(pairs):
        pair = (symbol, trade_date)
        source = action_order_index.get(pair)
        execution = action_execution_index.get(pair)
        trade = formal_trade_index.get(pair)
        selection_diagnostic = _mapping(selection_diagnostics.get(pair))
        if source is None:
            category = str(
                selection_diagnostic.get("category") or "no_action_signal"
            )
        elif execution and execution.get("reason") == "position_limit":
            category = "action_signal_blocked_by_position_limit"
        elif execution and execution.get("status") == "skipped":
            category = "action_signal_skipped_other"
        else:
            category = "action_signal_without_execution_record"
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "vt_symbol": symbol,
                "category": category,
                "action_signal_time": (
                    str(source.get("buy_time") or source.get("signal_time") or "")
                    if source
                    else None
                ),
                "execution_reason": execution.get("reason") if execution else None,
                "formal_return_pct": _optional_float(
                    trade.get("return_pct") if trade else None
                ),
                "formal_net_pnl": _optional_float(
                    trade.get("net_pnl") if trade else None
                ),
                "selection_diagnostic": selection_diagnostic,
            }
        )
    return rows


def _early_order_attribution_ledger(
    action_order_index: Mapping[tuple[str, date], Mapping[str, object]],
    *,
    execution_index: Mapping[tuple[str, date], Mapping[str, object]],
    trade_index: Mapping[tuple[str, date], Mapping[str, object]],
    formal_candidate_pairs: set[tuple[str, date]],
    formal_filled_pairs: set[tuple[str, date]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (symbol, trade_date), source in sorted(action_order_index.items()):
        pair = (symbol, trade_date)
        execution = execution_index.get(pair)
        trade = trade_index.get(pair)
        status = str((execution or {}).get("status") or "missing")
        reason = (execution or {}).get("reason")
        if status == "filled" and pair in formal_filled_pairs:
            category = "filled_matched_original_account"
        elif status == "filled" and pair in formal_candidate_pairs:
            category = "filled_formal_identity_not_original_account"
        elif status == "filled":
            category = "filled_formal_identity_false_positive"
        elif reason == "position_limit" and pair in formal_filled_pairs:
            category = "skipped_original_account_position_limit"
        elif reason == "position_limit" and pair in formal_candidate_pairs:
            category = "skipped_formal_candidate_position_limit"
        elif reason == "position_limit":
            category = "skipped_nonformal_position_limit"
        else:
            category = "skipped_other"
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "vt_symbol": symbol,
                "name": source.get("name"),
                "signal_time": str(
                    source.get("buy_time") or source.get("signal_time") or ""
                ),
                "execution_status": status,
                "execution_reason": reason,
                "formal_candidate_identity": pair in formal_candidate_pairs,
                "original_account_identity": pair in formal_filled_pairs,
                "category": category,
                "identity_probability": _optional_float(
                    source.get("identity_probability")
                ),
                "timing_probability": _optional_float(
                    source.get("timing_probability")
                ),
                ACTION_SCORE_FIELD: _optional_float(
                    source.get(ACTION_SCORE_FIELD)
                ),
                "gain_pct": _optional_float(_feature_number(source, "gain_pct")),
                "support_score": _optional_float(
                    _feature_number(source, "support_score")
                ),
                "base_rank_score": _optional_float(
                    _feature_number(source, "base_rank_score")
                ),
                "return_3m_pct": _optional_float(
                    _feature_number(source, "return_3m_pct")
                ),
                "prior_30m_floor_pct": _optional_float(
                    _feature_number(source, "prior_30m_floor_pct")
                ),
                "eventually_touched_limit": _source_outcome_flag(
                    source, "touched"
                ),
                "eventually_sealed_limit": _source_outcome_flag(source, "sealed"),
                "return_pct": _optional_float(
                    trade.get("return_pct") if trade else None
                ),
                "net_pnl": _optional_float(trade.get("net_pnl") if trade else None),
            }
        )
    return rows


def _matched_trade_comparison(
    pairs: set[tuple[str, date]],
    *,
    action_trade_index: Mapping[tuple[str, date], Mapping[str, object]],
    formal_trade_index: Mapping[tuple[str, date], Mapping[str, object]],
) -> dict[str, object]:
    deltas: list[float] = []
    action_returns: list[float] = []
    formal_returns: list[float] = []
    for pair in sorted(pairs):
        action_return = _number((action_trade_index.get(pair) or {}).get("return_pct"))
        formal_return = _number((formal_trade_index.get(pair) or {}).get("return_pct"))
        if action_return is None or formal_return is None:
            continue
        action_returns.append(action_return)
        formal_returns.append(formal_return)
        deltas.append(action_return - formal_return)
    return {
        "pair_count": len(pairs),
        "closed_both_count": len(deltas),
        "action_average_return_pct": (
            round(mean(action_returns), 4) if action_returns else None
        ),
        "formal_average_return_pct": (
            round(mean(formal_returns), 4) if formal_returns else None
        ),
        "average_return_delta_pct": round(mean(deltas), 4) if deltas else None,
    }


def _filled_first_board_pairs(
    account: Mapping[str, object],
) -> set[tuple[str, date]]:
    orders = account.get("orders")
    rows = orders if isinstance(orders, list) else []
    return {
        (
            str(row.get("vt_symbol") or ""),
            _as_date(
                row.get("trade_date")
                or row.get("entry_date")
                or row.get("signal_date")
            ),
        )
        for row in rows
        if isinstance(row, Mapping)
        and row.get("side") == "BUY"
        and row.get("status") == "filled"
        and str(row.get("lane") or "") == "first_board"
    }


def _identity_report(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    signals: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> dict[str, object]:
    eligible_rows = [
        row
        for row in rows
        if _order_date(row) in allowed_dates
        and competing_feature_vector(row) is not None
    ]
    formal_pairs = {
        _order_pair(order)
        for order in formal_orders
        if str(order.get("lane") or "") == "first_board"
        and _order_date(order) in allowed_dates
    }
    selected = [row for row in signals if _order_date(row) in allowed_dates]
    selected_pairs = {_order_pair(row) for row in selected}
    formal_true_pairs = selected_pairs & formal_pairs
    horizon_true = [row for row in selected if row.get(TIMING_TARGET_FIELD) is True]
    reachable_formal_pairs = _confirmed_target_pairs(
        eligible_rows,
        target_field=IDENTITY_TARGET_FIELD,
    )
    reachable_horizon_pairs = _confirmed_target_pairs(
        eligible_rows,
        target_field=TIMING_TARGET_FIELD,
    )
    leads = [
        value
        for row in selected
        if (value := _number(row.get("formal_touch_lead_minutes"))) is not None
        and value > 0
    ]
    gains = [
        value
        for row in selected
        if (value := _feature_number(row, "gain_pct")) is not None
    ]
    returns = [
        value
        for row in selected
        if (value := _number(row.get("net_return_pct"))) is not None
    ]
    return {
        "selection_count": len(selected),
        "fillable_selection_count": sum(row.get("fillable") is True for row in selected),
        "formal_first_board_pair_count": len(formal_pairs),
        "reachable_formal_pair_count": len(reachable_formal_pairs),
        "reachable_horizon_pair_count": len(reachable_horizon_pairs),
        "formal_identity_true_positive_count": len(formal_true_pairs),
        "horizon_true_positive_count": len(horizon_true),
        "formal_identity_precision_pct": _percentage(
            len(formal_true_pairs),
            len(selected),
        ),
        "horizon_precision_pct": _percentage(len(horizon_true), len(selected)),
        "reachable_formal_recall_pct": _percentage(
            len(selected_pairs & reachable_formal_pairs),
            len(reachable_formal_pairs),
        ),
        "reachable_horizon_recall_pct": _percentage(
            len(selected_pairs & reachable_horizon_pairs),
            len(reachable_horizon_pairs),
        ),
        "all_formal_recall_pct": _percentage(
            len(formal_true_pairs),
            len(formal_pairs),
        ),
        "touch_lead_minutes": _distribution(leads),
        "signal_gain_pct": _distribution(gains),
        "d1_closed_count": len(returns),
        "d1_win_rate_pct": _percentage(sum(value > 0 for value in returns), len(returns)),
        "d1_average_return_pct": round(mean(returns), 4) if returns else None,
    }


def _confirmed_target_pairs(
    rows: Sequence[Mapping[str, object]],
    *,
    target_field: str,
) -> set[tuple[str, date]]:
    grouped: dict[tuple[str, date], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[_order_pair(row)].append(row)
    reachable: set[tuple[str, date]] = set()
    for pair, pair_rows in grouped.items():
        streak = 0
        previous_time: str | None = None
        for row in sorted(pair_rows, key=lambda value: str(value.get("signal_time") or "")):
            current_time = str(row.get("signal_time") or "")
            consecutive = (
                previous_time is not None
                and trading_minutes_between(previous_time, current_time) == 1.0
            )
            streak = streak + 1 if consecutive else 1
            previous_time = current_time
            if streak >= CONFIRMATION_MINUTES and row.get(target_field) is True:
                reachable.add(pair)
                break
    return reachable


def _acceptance_report(
    validation: Mapping[str, object],
    *,
    validation_blocks: Sequence[Mapping[str, object]],
    models: Sequence[CompetingRiskModelFit],
    threshold: CompetingThresholdSelection,
    baseline_parity: Mapping[str, object],
) -> dict[str, object]:
    identity = _mapping(validation.get("identity"))
    account_identity = _mapping(validation.get("account_identity"))
    accounts = _mapping(validation.get("accounts"))
    formal = _mapping(accounts.get("formal_touch"))
    action = _mapping(accounts.get("competing_action"))
    double_cost = _mapping(accounts.get("competing_action_double_cost"))
    positive_blocks = 0
    for block in validation_blocks:
        block_account = _mapping(
            _mapping(block.get("accounts")).get("competing_action")
        )
        if (
            (_number(block_account.get("trade_count")) or 0) > 0
            and (_number(block_account.get("total_return_pct")) or 0) > 0
        ):
            positive_blocks += 1
    checks = {
        "baseline_parity": baseline_parity.get("passed") is True,
        "both_models_ready": all(model.status == "ready" for model in models),
        "calibration_threshold_ready": threshold.status == "ready",
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
        "threshold_frozen_from_calibration_only": True,
        "production_promotion_allowed": False,
        "positive_validation_block_count": positive_blocks,
    }


def _model_report(model: CompetingRiskModelFit) -> dict[str, object]:
    return {
        "status": model.status,
        "target_field": model.target_field,
        "features": list(COMPETING_FEATURE_NAMES),
        "training_row_count": model.training_row_count,
        "training_pair_count": model.training_pair_count,
        "class_counts": model.class_counts,
        "fit_dates": list(model.fit_dates),
        "scaler_mean_by_feature": model.scaler_mean_by_feature,
        "scaler_scale_by_feature": model.scaler_scale_by_feature,
        "coefficient_by_feature": model.coefficient_by_feature,
        "coefficient_summary": summarize_model_coefficients(
            model.coefficient_by_feature
        ),
        "intercept": model.intercept,
        "fingerprint": model.fingerprint,
    }


def summarize_model_coefficients(
    coefficients: Mapping[str, object],
    *,
    limit: int = 5,
) -> dict[str, list[dict[str, object]]]:
    """Return the largest standardized positive and negative coefficients."""

    finite = [
        (str(feature), value)
        for feature, raw_value in coefficients.items()
        if (value := _number(raw_value)) is not None and value != 0
    ]
    maximum = max(int(limit), 0)
    positive = sorted(
        (item for item in finite if item[1] > 0),
        key=lambda item: (-item[1], item[0]),
    )[:maximum]
    negative = sorted(
        (item for item in finite if item[1] < 0),
        key=lambda item: (item[1], item[0]),
    )[:maximum]
    return {
        "positive": [
            {"feature": feature, "coefficient": round(value, 6)}
            for feature, value in positive
        ],
        "negative": [
            {"feature": feature, "coefficient": round(value, 6)}
            for feature, value in negative
        ],
    }


def _threshold_report(selection: CompetingThresholdSelection) -> dict[str, object]:
    return {
        "status": selection.status,
        "threshold": selection.threshold,
        "calibration_dates": list(selection.calibration_dates),
        "minimum_selection_count": selection.minimum_selection_count,
        "selected_metrics": selection.selected_metrics,
        "metrics_by_threshold": list(selection.metrics_by_threshold),
    }


def _dataset_report(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    pairs = {_order_pair(row) for row in rows}
    daily_pairs: dict[date, set[str]] = defaultdict(set)
    minute_pairs: dict[tuple[date, str], set[str]] = defaultdict(set)
    for symbol, trade_date in pairs:
        if symbol and trade_date != date.min:
            daily_pairs[trade_date].add(symbol)
    for row in rows:
        trade_date = _order_date(row)
        symbol = str(row.get("vt_symbol") or "")
        signal_time = str(row.get("signal_time") or "")[:5]
        if trade_date != date.min and symbol and signal_time:
            minute_pairs[(trade_date, signal_time)].add(symbol)
    daily_counts = [len(symbols) for symbols in daily_pairs.values()]
    minute_counts = [len(symbols) for symbols in minute_pairs.values()]
    return {
        "observable_prefix_count": len(rows),
        "candidate_pair_count": len(pairs),
        "candidate_trade_day_count": len(daily_pairs),
        "candidate_pairs_per_day": _count_distribution(daily_counts),
        "candidate_minute_count": len(minute_pairs),
        "multi_candidate_minute_count": sum(count >= 2 for count in minute_counts),
        "maximum_candidates_in_one_minute": max(minute_counts, default=0),
    }


def _forward_validation_report(
    models: Mapping[str, CompetingRiskModelFit],
    threshold: float | None,
) -> dict[str, object]:
    from alphaagent.server.services.limit_up import radar_observation_repository

    coverage = radar_observation_repository.load_frame_coverage()
    trade_days = int(coverage.get("trade_day_count") or 0)
    base = {
        "status": "collecting_forward_overlay",
        "trade_day_count": trade_days,
        "frame_count": int(coverage.get("frame_count") or 0),
        "observation_count": int(coverage.get("observation_count") or 0),
        "closed_action_event_count": 0,
        "review_gate": "60_new_trade_days_or_300_closed_actions",
        "ready_for_review": False,
        "execution_effect": "none_research_only",
    }
    identity_model = models.get("identity")
    timing_model = models.get("timing_3m")
    if (
        identity_model is None
        or timing_model is None
        or identity_model.status != "ready"
        or timing_model.status != "ready"
        or threshold is None
        or trade_days == 0
    ):
        return {
            **base,
            "scoreable_observation_count": 0,
            "action_event_count": 0,
            "note": "尚无可连接的前向雷达帧，或冻结模型/阈值尚未就绪。",
        }

    from alphaagent.server.services.limit_up.preboard_hazard_study import (
        build_forward_overlay_rows,
        settle_forward_actions,
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
                "trade_date": _as_date(row.get("trade_date")),
            }
            for row in observations
            if row.get("vt_symbol") and _as_date(row.get("trade_date")) != date.min
        ]
    ).drop_duplicates()
    minute_rows = load_one_minute_bars(pairs) if not pairs.empty else pd.DataFrame()
    overlay_rows = build_forward_overlay_rows(observations, minute_rows)
    prepared_rows = prepare_forward_competing_rows(overlay_rows)
    scored_rows = score_competing_risk_rows(
        prepared_rows,
        identity_model,
        timing_model,
    )
    actions = select_confirmed_competing_signals(
        scored_rows,
        threshold=threshold,
        confirmation_minutes=CONFIRMATION_MINUTES,
        max_daily_actions=MAX_DAILY_FIRST_BOARD_ACTIONS,
    )
    action_symbols = sorted(
        {
            str(row.get("vt_symbol") or "")
            for row in actions
            if row.get("vt_symbol")
        }
    )
    action_dates = sorted({_order_date(row) for row in actions})
    settled: list[dict[str, object]] = []
    if action_symbols and action_dates:
        settlement_end = date.today()
        daily_bars = history_repository.load_account_daily_bars(
            action_symbols,
            action_dates[0],
            settlement_end,
        )
        settled = settle_forward_actions(
            actions,
            daily_bars,
            load_reliable_trade_dates(action_dates[0], settlement_end),
        )
    returns = [float(row["net_return_pct"]) for row in settled]
    ready_for_review = (
        trade_days >= 60 or len(settled) >= 300
    ) and len(settled) >= 30
    return {
        **base,
        "status": "ready_for_review" if ready_for_review else "collecting_forward_overlay",
        "scoreable_observation_count": len(scored_rows),
        "scoreable_stock_day_count": len({_order_pair(row) for row in scored_rows}),
        "action_event_count": len(actions),
        "closed_action_event_count": len(settled),
        "closed_action_win_rate_pct": _percentage(
            sum(value > 0 for value in returns),
            len(returns),
        ),
        "closed_action_average_return_pct": (
            round(mean(returns), 4) if returns else None
        ),
        "ready_for_review": ready_for_review,
        "dynamic_overlay": _dynamic_overlay_summary(actions),
        "note": "动态概念、资金和新鲜度只做前向分层，执行影响仍为none。",
    }


def _dynamic_overlay_summary(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    fields = (
        "concept_strength_score",
        "concept_change_acceleration_1m",
        "concept_change_acceleration_3m",
        "concept_change_acceleration_5m",
        "concept_turnover_acceleration_1m",
        "concept_turnover_acceleration_3m",
        "concept_turnover_acceleration_5m",
        "sector_main_net_inflow",
        "stock_main_net_inflow",
    )
    return {
        "action_count": len(rows),
        **{
            f"average_{field}": (
                round(mean(values), 4)
                if (
                    values := [
                        value
                        for row in rows
                        if (value := _number(row.get(field))) is not None
                    ]
                )
                else None
            )
            for field in fields
        },
    }


def _date_split_report(
    fit_dates: Sequence[date],
    calibration_dates: Sequence[date],
    validation_dates: Sequence[date],
) -> dict[str, object]:
    return {
        "fit": _date_range(fit_dates),
        "calibration": _date_range(calibration_dates),
        "validation": _date_range(validation_dates),
    }


def _fixed_validation_blocks(
    validation_dates: set[date] | Sequence[date],
) -> tuple[tuple[date, ...], ...]:
    ordered = tuple(sorted(set(validation_dates)))
    if len(ordered) != VALIDATION_SESSION_COUNT:
        return tuple()
    block_size = VALIDATION_SESSION_COUNT // 5
    return tuple(
        ordered[start : start + block_size]
        for start in range(0, VALIDATION_SESSION_COUNT, block_size)
    )


def _date_range(values: Sequence[date]) -> dict[str, object]:
    ordered = sorted(set(values))
    return {
        "count": len(ordered),
        "start": ordered[0].isoformat() if ordered else None,
        "end": ordered[-1].isoformat() if ordered else None,
    }


def _orders_on_dates(
    orders: Sequence[Mapping[str, object]],
    allowed_dates: set[date],
) -> list[dict[str, object]]:
    return [dict(order) for order in orders if _order_date(order) in allowed_dates]


def _is_fresh_forward_row(
    row: Mapping[str, object],
    *,
    maximum_quote_age_seconds: float,
) -> bool:
    if row.get("frame_is_stale") is not False:
        return False
    signal_date = _optional_date(row.get("signal_date"))
    source_date = _optional_date(row.get("source_trade_date"))
    captured_at = _optional_datetime(row.get("captured_at"))
    quote_at = _optional_datetime(row.get("quote_observed_at"))
    if (
        signal_date is None
        or source_date != signal_date
        or captured_at is None
        or quote_at is None
    ):
        return False
    try:
        age_seconds = (captured_at - quote_at).total_seconds()
    except TypeError:
        return False
    return 0 <= age_seconds <= max(float(maximum_quote_age_seconds), 0.0)


def _forward_row_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("captured_at") or ""),
        str(row.get("signal_at") or ""),
        str(row.get("vt_symbol") or ""),
    )


def _order_pair(row: Mapping[str, object]) -> tuple[str, date]:
    return str(row.get("vt_symbol") or ""), _order_date(row)


def _order_date(row: Mapping[str, object]) -> date:
    return _as_date(row.get("entry_date") or row.get("signal_date"))


def _as_date(value: object) -> date:
    return _optional_date(value) or date.min


def _optional_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _feature_number(row: Mapping[str, object], field: str) -> float | None:
    direct = _number(row.get(field))
    if direct is not None:
        return direct
    for name in ("features", "competing_features"):
        container = row.get(name)
        if isinstance(container, Mapping):
            value = _number(container.get(field))
            if value is not None:
                return value
    return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _optional_float(value: object) -> float | None:
    parsed = _number(value)
    return round(parsed, 8) if parsed is not None else None


def _recognized_volume_unit_scale(value: object) -> float | None:
    parsed = _number(value)
    if parsed is None:
        return None
    for scale in (1.0, 100.0):
        if abs(parsed - scale) <= 0.01:
            return scale
    return None


def _optional_integer(value: object) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None else None


def _series_median(values: pd.Series) -> float | None:
    finite = pd.to_numeric(values, errors="coerce").dropna()
    return round(float(finite.median()), 8) if not finite.empty else None


def _series_max(values: pd.Series) -> float | None:
    finite = pd.to_numeric(values, errors="coerce").dropna()
    return round(float(finite.max()), 8) if not finite.empty else None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p25": _quantile(ordered, 0.25),
        "median": round(median(ordered), 4) if ordered else None,
        "p75": _quantile(ordered, 0.75),
    }


def _count_distribution(values: Sequence[int]) -> dict[str, float | int | None]:
    ordered = sorted(int(value) for value in values)
    return {
        "count": len(ordered),
        "minimum": min(ordered) if ordered else None,
        "p25": _quantile(ordered, 0.25),
        "median": round(median(ordered), 4) if ordered else None,
        "p75": _quantile(ordered, 0.75),
        "maximum": max(ordered) if ordered else None,
        "average": round(mean(ordered), 4) if ordered else None,
    }


def _quantile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    return round(float(pd.Series(values).quantile(quantile)), 4)


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _blocked_report(status: str, *, session_count: int) -> dict[str, object]:
    return {
        "study_version": STUDY_VERSION,
        "status": status,
        "decision": "no_optimization_result",
        "scope": {"requested_session_count": int(session_count)},
        "formal_strategy_changed": False,
    }


def _render_blocked_markdown(report: Mapping[str, object]) -> str:
    coverage = _mapping(report.get("coverage"))
    return "\n".join(
        [
            "# 首板双阶段竞争风险触发研究",
            "",
            f"- 状态：`{report.get('status')}`。",
            f"- 决策：`{report.get('decision')}`。",
            f"- 完整一分钟股票日：{coverage.get('complete_pair_count', 0)}/"
            f"{coverage.get('manifest_pair_count', 0)}。",
            f"- 下一数据任务：`{report.get('next_data_task') or '-'}`。",
            "",
        ]
    )


def _display(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.4f}" if parsed is not None else "-"


def _profile_median(profile: Mapping[str, object], field: str) -> object:
    return _mapping(profile.get(field)).get("median")


def _coefficient_entries(value: object) -> str:
    rows = value if isinstance(value, list) else []
    entries = []
    for raw in rows:
        row = _mapping(raw)
        coefficient = _number(row.get("coefficient"))
        if coefficient is not None and row.get("feature"):
            entries.append(f"`{row['feature']}` {coefficient:+.4f}")
    return "、".join(entries) if entries else "-"


def _pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.2f}%" if parsed is not None else "-"


def _signed_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:+.2f}%" if parsed is not None else "-"


def _signed_number(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:+.2f}" if parsed is not None else "-"


def _write_output(path_text: str, content: str) -> None:
    resolved = Path(path_text).resolve()
    report_root = Path("memory/06_backtests").resolve()
    if report_root not in resolved.parents:
        raise ValueError("competing-risk report must stay under memory/06_backtests")
    resolved.write_text(content, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate competing pre-board risk")
    parser.add_argument("command", choices=("evaluate",))
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSION_COUNT)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output")
    parser.add_argument("--json-output")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_preboard_competing_risk(session_count=args.sessions)
    json_content = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    content = (
        render_competing_markdown(report)
        if args.format == "markdown"
        else json_content
    )
    if args.output:
        _write_output(args.output, content)
    if args.json_output:
        _write_output(args.json_output, json_content)
    print(content, end="")


if __name__ == "__main__":
    main()
