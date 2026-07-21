"""Frozen one-minute hazard study for causal pre-board recommendations."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
import json
from math import isfinite
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

import pandas as pd

from alphaagent.server.services.limit_up import history_repository
from alphaagent.server.services.limit_up.preboard_hazard_data import (
    load_one_minute_bars,
    load_one_minute_coverage,
    load_static_hazard_manifest,
)
from alphaagent.server.services.limit_up.preboard_hazard_model import (
    HAZARD_FEATURE_NAMES,
    HAZARD_HORIZONS,
    HazardModelFit,
    HazardThresholdSelection,
    attach_hazard_targets,
    calibrate_hazard_threshold,
    fit_hazard_model,
    hazard_feature_vector,
    select_top2_first_crossings,
)
from alphaagent.server.services.limit_up.preboard_momentum import build_prefix_rows
from alphaagent.server.services.limit_up.preboard_strategy_replay import (
    _net_return_pct,
)
from alphaagent.server.services.limit_up.preboard_strategy_study import (
    FEATURE_LOOKBACK_SESSIONS,
    _account_replay,
    _account_summary,
    _build_all_strategy_prefix_rows,
    _coverage_report,
    _date_split,
    _early_order,
    _feature_index,
    _formal_orders,
    _load_bounded_feature_frame,
    _load_financial_index,
    compare_baseline_summaries,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


STUDY_VERSION = "limit-up-preboard-hazard-v1"
DEFAULT_SESSION_COUNT = 60
MINIMUM_ONE_MINUTE_COVERAGE_PCT = 95.0
MINIMUM_CALIBRATION_SELECTIONS = 10
ACTION_HORIZON = 3
PREPARE_HORIZON = 5
URGENCY_HORIZON = 1
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FORWARD_OVERLAY_FIELDS = (
    "concept_id",
    "concept_state",
    "concept_strength_score",
    "concept_leader_rank",
    "concept_strong_5_count",
    "concept_change_acceleration_1m",
    "concept_change_acceleration_3m",
    "concept_change_acceleration_5m",
    "concept_turnover_acceleration_1m",
    "concept_turnover_acceleration_3m",
    "concept_turnover_acceleration_5m",
    "sector_main_net_inflow",
    "stock_main_net_inflow",
    "market_timing_state",
)


def build_hazard_replay_orders(
    *,
    action_rows: Sequence[Mapping[str, object]],
    prepare_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_threshold: float,
    prepare_threshold: float,
    conservative_entry: bool = False,
    action_probability_field: str = "hazard_probability",
    prepare_probability_field: str = "hazard_probability",
) -> dict[str, list[dict[str, object]]]:
    """Freeze Top2 action/prepare signals and keep prepare out of the ledger."""

    action_signals = select_top2_first_crossings(
        action_rows,
        threshold=float(action_threshold),
        probability_field=action_probability_field,
    )
    prepare_signals = select_top2_first_crossings(
        prepare_rows,
        threshold=float(prepare_threshold),
        probability_field=prepare_probability_field,
    )
    early_orders = [
        order
        for signal in action_signals
        if (
            order := _hazard_order(
                signal,
                conservative_entry=conservative_entry,
                probability_field=action_probability_field,
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
        "prepare_signals": prepare_signals,
        "early_orders": early_orders,
        "relay_orders": relay_orders,
        "combined_orders": [*relay_orders, *early_orders],
    }


def replay_hazard_account(
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


def settle_forward_actions(
    actions: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
) -> list[dict[str, object]]:
    """Close fillable forward actions at the next reliable official close."""

    calendar = sorted(set(trade_dates))
    next_date = {
        current: calendar[index + 1]
        for index, current in enumerate(calendar[:-1])
    }
    closes = {
        (str(row.get("vt_symbol") or ""), _as_date(row.get("trade_date"))): _number(
            row.get("close_price")
        )
        for row in daily_bars
    }
    settled: list[dict[str, object]] = []
    for action in actions:
        if action.get("fillable") is not True:
            continue
        signal_date = _order_date(action)
        result_date = next_date.get(signal_date)
        symbol = str(action.get("vt_symbol") or "")
        exit_price = closes.get((symbol, result_date or date.min))
        net_return = _net_return_pct(
            _number(action.get("entry_price")),
            exit_price,
            limit_price=_number(action.get("limit_price")),
        )
        if result_date is None or exit_price is None or net_return is None:
            continue
        settled.append(
            {
                **dict(action),
                "result_date": result_date.isoformat(),
                "d1_close_price": exit_price,
                "net_return_pct": net_return,
                "is_win": net_return > 0,
            }
        )
    return settled


def build_forward_overlay_rows(
    observations: Sequence[Mapping[str, object]],
    minute_rows: pd.DataFrame,
) -> list[dict[str, object]]:
    """Join saved live gates to completed causal one-minute features."""

    if not observations or minute_rows.empty:
        return []
    minute = minute_rows.copy()
    minute["trade_date"] = pd.to_datetime(
        minute["trade_date"], errors="coerce"
    ).dt.date
    minute["bar_time"] = pd.to_datetime(minute["bar_time"], errors="coerce")
    minute = minute.dropna(subset=["trade_date", "bar_time"])
    bars_by_pair = {
        (str(symbol), trade_date): group.to_dict(orient="records")
        for (symbol, trade_date), group in minute.groupby(
            ["vt_symbol", "trade_date"],
            sort=False,
        )
    }
    prefix_cache: dict[tuple[str, date], list[dict[str, object]]] = {}
    result: list[dict[str, object]] = []
    for observation in sorted(observations, key=_forward_observation_key):
        symbol = str(observation.get("vt_symbol") or "")
        trade_date = _as_date(observation.get("trade_date"))
        captured_at = _optional_datetime(observation.get("captured_at"))
        pair = (symbol, trade_date)
        if not symbol or trade_date == date.min or captured_at is None:
            continue
        if pair not in prefix_cache:
            prefix_cache[pair] = build_prefix_rows(
                {
                    "vt_symbol": symbol,
                    "name": str(observation.get("name") or symbol),
                    "trade_date": trade_date.isoformat(),
                    "previous_close": observation.get("previous_close"),
                    "limit_price": observation.get("limit_price"),
                },
                bars_by_pair.get(pair, []),
                bar_minutes=1,
            )
        completed_at = _wall_clock(captured_at).replace(second=0, microsecond=0)
        available = [
            row
            for row in prefix_cache[pair]
            if (
                signal_at := _optional_datetime(row.get("signal_at"))
            ) is not None
            and _wall_clock(signal_at) <= completed_at
        ]
        if not available:
            continue
        prefix = max(available, key=lambda row: str(row.get("signal_at") or ""))
        support = _number(observation.get("support_score"))
        entry_quality = _number(observation.get("entry_quality_score"))
        rank_score = _number(observation.get("rank_score"))
        current_price = _number(observation.get("last_price"))
        limit_price = _number(observation.get("limit_price"))
        blocker_codes = observation.get("blocker_codes")
        blockers = list(blocker_codes) if isinstance(blocker_codes, list) else []
        history_samples = _number(observation.get("history_sample_count"))
        combined_rate = _number(observation.get("historical_combined_rate"))
        shared_passed = bool(
            str(observation.get("board_lane") or "") == "first_board"
            and str(observation.get("capture_state") or "") != "fill_followup"
            and str(observation.get("blocking_scope") or "none") == "none"
            and not blockers
            and support is not None
            and support >= 55.0
            and entry_quality is not None
            and rank_score is not None
            and history_samples is not None
            and history_samples >= 5
            and combined_rate is not None
            and combined_rate >= 30.0
            and prefix.get("before_first_limit_touch") is True
            and current_price is not None
            and limit_price is not None
            and current_price < limit_price - 0.001
        )
        projected = _project_hazard_row(
            {
                **prefix,
                "support_score": support,
                "entry_quality_score": entry_quality,
                "rank_score": rank_score,
                "profitability_gate_sample_count": history_samples,
                "profitability_gate_combined_rate": combined_rate,
                "shared_strategy_passed": shared_passed,
            }
        )
        projected.update(
            {
                "captured_at": captured_at.isoformat(),
                "quote_observed_at": observation.get("quote_observed_at"),
                "frame_is_stale": observation.get("is_stale"),
                "frame_quality_status": observation.get("quality_status"),
                "source_trade_date": observation.get("source_trade_date"),
                **{
                    field: observation.get(field)
                    for field in _FORWARD_OVERLAY_FIELDS
                },
            }
        )
        result.append(projected)
    return result


def build_hazard_analysis(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
    baseline_parity: Mapping[str, object],
    minimum_calibration_selections: int = MINIMUM_CALIBRATION_SELECTIONS,
) -> tuple[dict[str, object], dict[int, HazardModelFit]]:
    """Fit frozen horizons and compare action orders on the same account."""

    labeled_rows = attach_hazard_targets(prefix_rows, formal_orders)
    models: dict[int, HazardModelFit] = {}
    thresholds: dict[int, HazardThresholdSelection] = {}
    for horizon in HAZARD_HORIZONS:
        target = _target_field(horizon)
        model = fit_hazard_model(
            labeled_rows,
            fit_dates=fit_dates,
            target_field=target,
        )
        threshold = calibrate_hazard_threshold(
            labeled_rows,
            model,
            calibration_dates=calibration_dates,
            target_field=target,
            minimum_selection_count=minimum_calibration_selections,
        )
        models[horizon] = model
        thresholds[horizon] = threshold

    scored_rows = _score_hazard_rows(labeled_rows, models)

    action_threshold = _threshold_or_block(thresholds[ACTION_HORIZON])
    prepare_threshold = _threshold_or_block(thresholds[PREPARE_HORIZON])
    bundle = build_hazard_replay_orders(
        action_rows=scored_rows,
        prepare_rows=scored_rows,
        formal_orders=formal_orders,
        action_threshold=action_threshold,
        prepare_threshold=prepare_threshold,
        action_probability_field=_probability_field(ACTION_HORIZON),
        prepare_probability_field=_probability_field(PREPARE_HORIZON),
    )
    conservative_bundle = build_hazard_replay_orders(
        action_rows=scored_rows,
        prepare_rows=scored_rows,
        formal_orders=formal_orders,
        action_threshold=action_threshold,
        prepare_threshold=prepare_threshold,
        conservative_entry=True,
        action_probability_field=_probability_field(ACTION_HORIZON),
        prepare_probability_field=_probability_field(PREPARE_HORIZON),
    )
    urgency_signals = select_top2_first_crossings(
        scored_rows,
        threshold=_threshold_or_block(thresholds[URGENCY_HORIZON]),
        probability_field=_probability_field(URGENCY_HORIZON),
    )

    all_dates = fit_dates | calibration_dates | validation_dates
    phase_dates = {
        "full": all_dates,
        "validation": validation_dates,
    }
    phases: dict[str, dict[str, object]] = {}
    for phase, allowed_dates in phase_dates.items():
        phases[phase] = {
            "identity": _identity_report(
                labeled_rows,
                formal_orders,
                bundle["action_signals"],
                allowed_dates=allowed_dates,
                horizon=ACTION_HORIZON,
            ),
            "prepare": _identity_report(
                labeled_rows,
                formal_orders,
                bundle["prepare_signals"],
                allowed_dates=allowed_dates,
                horizon=PREPARE_HORIZON,
            ),
            "urgency": _identity_report(
                labeled_rows,
                formal_orders,
                urgency_signals,
                allowed_dates=allowed_dates,
                horizon=URGENCY_HORIZON,
            ),
            "accounts": _phase_accounts(
                formal_orders=formal_orders,
                action_orders=bundle["combined_orders"],
                conservative_orders=conservative_bundle["combined_orders"],
                bars=bars,
                trade_dates=trade_dates,
                allowed_dates=allowed_dates,
            ),
        }

    acceptance = _acceptance_report(
        phases.get("validation", {}),
        thresholds=thresholds,
        baseline_parity=baseline_parity,
    )
    return {
        "models": {
            str(horizon): _model_report(models[horizon], thresholds[horizon])
            for horizon in HAZARD_HORIZONS
        },
        "phases": phases,
        "signal_counts": {
            "action_3m": len(bundle["action_signals"]),
            "action_3m_fillable": len(bundle["early_orders"]),
            "prepare_5m": len(bundle["prepare_signals"]),
            "urgency_1m": len(urgency_signals),
        },
        "acceptance": acceptance,
        "decision": (
            "historical_pass_forward_shadow_only"
            if acceptance["passed"] is True
            else "historical_rejected_no_live_promotion"
        ),
    }, models


def evaluate_preboard_hazard(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
) -> dict[str, object]:
    """Load the bounded database scope and refuse results below hard gates."""

    manifest = load_static_hazard_manifest(session_count=session_count)
    if manifest.empty:
        return _blocked_report("blocked_by_manifest", session_count=session_count)
    coverage = load_one_minute_coverage(manifest)
    coverage_report = _coverage_report(manifest, coverage)
    if float(coverage_report["complete_pair_pct"]) < MINIMUM_ONE_MINUTE_COVERAGE_PCT:
        return {
            **_blocked_report(
                "blocked_by_one_minute_coverage",
                session_count=session_count,
            ),
            "coverage": coverage_report,
            "next_data_task": "sync_limit_up_preboard_hazard_minutes",
        }

    dates = sorted(pd.to_datetime(manifest["trade_date"]).dt.date.unique())
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
        row_projection=_project_hazard_row,
    )
    fit_dates, calibration_dates, validation_dates = _date_split(dates)
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

    analysis, models = build_hazard_analysis(
        prefix_rows,
        formal_orders,
        bars,
        trade_dates,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
        baseline_parity=baseline_parity,
    )
    forward_overlay = _forward_overlay_report(
        models[ACTION_HORIZON],
        _mapping(analysis["models"][str(ACTION_HORIZON)]).get("threshold"),
    )
    return {
        "study_version": STUDY_VERSION,
        "status": (
            "ready_historical_pass"
            if _mapping(analysis.get("acceptance")).get("passed") is True
            else "ready_historical_rejected"
        ),
        "formal_strategy_changed": False,
        "contract": {
            "observation_gain_operator": ">=",
            "observation_gain_pct": 3.0,
            "action_horizon_minutes": ACTION_HORIZON,
            "prepare_horizon_minutes": PREPARE_HORIZON,
            "urgency_horizon_minutes": URGENCY_HORIZON,
            "selection": "first_threshold_crossing_then_same_minute_top2",
            "entry": "next_1m_open_strictly_below_limit",
            "exit": "d1_official_close",
            "dynamic_concept_in_historical_model": False,
            "production_versions_changed": False,
        },
        "scope": {
            "requested_session_count": int(session_count),
            "session_count": len(dates),
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "fit_dates": [value.isoformat() for value in fit_dates],
            "calibration_dates": [value.isoformat() for value in calibration_dates],
            "validation_dates": [value.isoformat() for value in validation_dates],
        },
        "coverage": {**coverage_report, **feature_coverage},
        "filter_audit": {
            **filter_audit,
            "formal_profitability_filter": profitability_audit,
        },
        "baseline_parity": baseline_parity,
        **analysis,
        "forward_overlay": forward_overlay,
        "limitations": [
            "TDX一分钟K线不是Tick/L2，无法验证排队、撤单和秒级成交。",
            "历史核心模型不使用缺失的动态概念历史；概念加速度仅进入前向overlay。",
            "最后20日已被查看，只能称历史时间验证，不是新的锁定留出。",
            "历史通过也只允许影子排序，必须再积累60个交易日或300个闭合动作事件。",
        ],
    }


def render_hazard_markdown(report: Mapping[str, object]) -> str:
    """Render the frozen evidence without hiding blocked data coverage."""

    coverage = _mapping(report.get("coverage"))
    lines = [
        "# 首板短时触板 Hazard 研究",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status')}`；结论：`{report.get('decision') or 'no_optimization_result'}`。",
        f"- 一分钟完整覆盖：{coverage.get('complete_pair_count', 0)}/"
        f"{coverage.get('manifest_pair_count', 0)}（{_display(coverage.get('complete_pair_pct'))}%）。",
        "- `>=3%` 只是观测母池；只有3分钟模型首次过阈且同分钟进入Top2才形成行动信号。",
        "- 5分钟模型只做准备提醒，1分钟模型只报告紧迫度；两者均不下单。",
    ]
    if str(report.get("status") or "").startswith("blocked_"):
        lines.extend(
            [
                "",
                "## Blocker",
                "",
                f"- 当前不能输出收益结论；先运行数据管理任务 `{report.get('next_data_task') or 'n/a'}`。",
            ]
        )
        return "\n".join(lines) + "\n"

    models = _mapping(report.get("models"))
    lines.extend(
        [
            "",
            "## Frozen models",
            "",
            "| 目标 | 状态 | 阈值 | 训练股票日 | 校准选择 | 校准精确率 | 指纹 |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for horizon in HAZARD_HORIZONS:
        model = _mapping(models.get(str(horizon)))
        calibration = _mapping(model.get("selected_threshold_metrics"))
        lines.append(
            f"| {horizon}分钟 | `{model.get('status')}` | {_display(model.get('threshold'))} | "
            f"{model.get('training_pair_count', 0)} | {calibration.get('selection_count', 0)} | "
            f"{_ratio_pct(calibration.get('precision'))} | `{model.get('fingerprint') or 'n/a'}` |"
        )

    action_model = _mapping(models.get(str(ACTION_HORIZON)))
    coefficients = [
        (str(field), value)
        for field, raw in _mapping(
            action_model.get("coefficient_by_feature")
        ).items()
        if (value := _number(raw)) is not None
    ]
    strongest_positive = sorted(coefficients, key=lambda item: item[1], reverse=True)[:4]
    strongest_negative = sorted(coefficients, key=lambda item: item[1])[:4]
    lines.extend(
        [
            "",
            "- 3分钟模型主要正向系数："
            + _coefficient_text(strongest_positive)
            + "。",
            "- 3分钟模型主要负向系数："
            + _coefficient_text(strongest_negative)
            + "。",
        ]
    )

    lines.extend(
        [
            "",
            "## Same-account validation",
            "",
            "| 方案 | 信号 | 基线身份精确率 | 3分钟命中率 | 可达召回 | 成交 | 胜率 | 复利 | 回撤 | PF |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    validation = _mapping(_mapping(report.get("phases")).get("validation"))
    identity = _mapping(validation.get("identity"))
    accounts = _mapping(validation.get("accounts"))
    for label, key, cost_key in (
        ("当前触板基线", "formal_touch", "normal"),
        ("仅二进三", "relay_only", "normal"),
        ("3分钟提前行动", "hazard_action", "normal"),
        ("3分钟行动-双倍成本", "hazard_action", "double_cost"),
        ("3分钟行动-保守成交", "hazard_action", "conservative_entry"),
    ):
        account = _mapping(_mapping(accounts.get(key)).get(cost_key))
        is_action = key == "hazard_action"
        lines.append(
            f"| {label} | {identity.get('selection_count', 0) if is_action else account.get('signal_count', 0)} | "
            f"{_pct(identity.get('formal_identity_precision_pct')) if is_action else '-'} | "
            f"{_pct(identity.get('horizon_precision_pct')) if is_action else '-'} | "
            f"{_pct(identity.get('reachable_formal_recall_pct')) if is_action else '-'} | "
            f"{account.get('trade_count', 0)} | {_pct(account.get('win_rate'))} | "
            f"{_signed_pct(account.get('total_return_pct'))} | {_signed_pct(account.get('max_drawdown_pct'))} | "
            f"{_display(account.get('profit_factor'))} |"
        )

    lead = _mapping(identity.get("touch_lead_minutes"))
    action_account = _mapping(_mapping(accounts.get("hazard_action")).get("normal"))
    lines.extend(
        [
            "",
            f"- 验证段行动 {identity.get('selection_count', 0)} 个；正式基线身份命中 "
            f"{identity.get('formal_identity_true_positive_count', 0)} 个，3分钟内实际触板 "
            f"{identity.get('horizon_true_positive_count', 0)} 个。",
            f"- 正确触板提前量 P25/中位/P75：{_display(lead.get('p25'))}/"
            f"{_display(lead.get('median'))}/{_display(lead.get('p75'))} 分钟；"
            f"仅剩不到1分钟才可见的正式票 {identity.get('sub_minute_only_formal_pair_count', 0)} 个，"
            f"其中漏掉 {identity.get('missed_sub_minute_identity_count', 0)} 个。",
            f"- 两仓冲突：提前首板因已有仓位未成交 "
            f"{action_account.get('early_first_board_conflict_count', 0)} 个；原因 "
            f"`{action_account.get('early_first_board_conflict_reasons') or {}}`。",
        ]
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
    overlay = _mapping(report.get("forward_overlay"))
    lines.extend(
        [
            "",
            "## Forward overlay",
            "",
            f"- 状态：`{overlay.get('status')}`；交易日 {overlay.get('trade_day_count', 0)}，"
            f"雷达帧 {overlay.get('frame_count', 0)}，可评分观测 "
            f"{overlay.get('scoreable_observation_count', 0)}，动作事件 "
            f"{overlay.get('action_event_count', 0)}。",
            f"- {overlay.get('note') or ''}",
        ]
    )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations") or [])
    return "\n".join(lines) + "\n"


def _hazard_order(
    signal: Mapping[str, object],
    *,
    conservative_entry: bool,
    probability_field: str,
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
    order = _early_order({**dict(signal), "entry_price": entry_price})
    probability = _number(signal.get(probability_field))
    return {
        **order,
        "algorithm": "formal_baseline_hazard_3m",
        "hazard_horizon_minutes": ACTION_HORIZON,
        "hazard_probability": probability,
        "rank_score": round((probability or 0.0) * 100, 6),
        "conservative_entry": conservative_entry,
        "candidate_source": "all_3pct_shared_strategy_1m_hazard",
    }


def _project_hazard_row(row: Mapping[str, object]) -> dict[str, object]:
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


def _score_hazard_rows(
    rows: Sequence[Mapping[str, object]],
    models: Mapping[int, HazardModelFit],
) -> list[dict[str, object]]:
    ready_models = {
        horizon: model for horizon, model in models.items() if model.status == "ready"
    }
    if not ready_models:
        return []
    scored: list[dict[str, object]] = []
    for raw in rows:
        if not _is_hazard_observation(raw):
            continue
        probabilities = {
            _probability_field(horizon): model.probability(raw)
            for horizon, model in ready_models.items()
        }
        if any(
            probability is None or not isfinite(probability)
            for probability in probabilities.values()
        ):
            continue
        scored.append(
            {
                **dict(raw),
                **{
                    field: round(float(probability), 8)
                    for field, probability in probabilities.items()
                    if probability is not None
                },
            }
        )
    return scored


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
    early = [order for order in action if str(order.get("lane") or "") == "first_board"]
    return {
        "formal_touch": {
            "normal": _account_metrics(formal, bars, trade_dates),
            "double_cost": _account_metrics(
                formal,
                bars,
                trade_dates,
                cost_multiplier=2.0,
            ),
        },
        "relay_only": {
            "normal": _account_metrics(relay, bars, trade_dates),
            "double_cost": _account_metrics(
                relay,
                bars,
                trade_dates,
                cost_multiplier=2.0,
            ),
        },
        "early_first_board_only": {
            "normal": _account_metrics(early, bars, trade_dates),
        },
        "hazard_action": {
            "normal": _account_metrics(action, bars, trade_dates),
            "double_cost": _account_metrics(
                action,
                bars,
                trade_dates,
                cost_multiplier=2.0,
            ),
            "conservative_entry": _account_metrics(
                conservative,
                bars,
                trade_dates,
            ),
        },
    }


def _account_metrics(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    cost_multiplier: float = 1.0,
) -> dict[str, object]:
    account = replay_hazard_account(
        orders,
        bars,
        trade_dates,
        cost_multiplier=cost_multiplier,
    )
    summary = dict(account["execution_summary"])
    conflicts = [
        order
        for order in account["orders"]
        if order.get("side") == "BUY"
        and order.get("lane") == "first_board"
        and order.get("status") == "skipped"
    ]
    daily_conflicts = Counter(str(order.get("trade_date") or "") for order in conflicts)
    return {
        **summary,
        "early_first_board_conflict_count": len(conflicts),
        "daily_selection_conflicts": dict(sorted(daily_conflicts.items())),
        "early_first_board_conflict_reasons": dict(
            Counter(str(order.get("reason") or "unknown") for order in conflicts)
        ),
    }


def _identity_report(
    labeled_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    signals: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
    horizon: int,
) -> dict[str, object]:
    formal_pairs = {
        _order_pair(order)
        for order in formal_orders
        if str(order.get("lane") or "") == "first_board"
        and _order_date(order) in allowed_dates
    }
    eligible_rows = [
        row
        for row in labeled_rows
        if _order_date(row) in allowed_dates
        and _is_hazard_observation(row)
        and hazard_feature_vector(row) is not None
    ]
    target = _target_field(horizon)
    reachable_pairs = {
        _order_pair(row) for row in eligible_rows if row.get(target) is True
    }
    selected = [row for row in signals if _order_date(row) in allowed_dates]
    selected_pairs = {_order_pair(row) for row in selected}
    formal_true_pairs = selected_pairs & formal_pairs
    horizon_true = [row for row in selected if row.get(target) is True]
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
    lead_by_pair: dict[tuple[str, date], list[float]] = defaultdict(list)
    for row in eligible_rows:
        lead = _number(row.get("formal_touch_lead_minutes"))
        pair = _order_pair(row)
        if pair in formal_pairs and lead is not None and 0 < lead <= horizon:
            lead_by_pair[pair].append(lead)
    sub_minute_only = {
        pair
        for pair, values in lead_by_pair.items()
        if any(value < 1.0 for value in values)
        and not any(value >= 1.0 for value in values)
    }
    return {
        "selection_count": len(selected),
        "fillable_selection_count": sum(row.get("fillable") is True for row in selected),
        "formal_first_board_pair_count": len(formal_pairs),
        "reachable_formal_pair_count": len(reachable_pairs),
        "formal_identity_true_positive_count": len(formal_true_pairs),
        "horizon_true_positive_count": len(horizon_true),
        "formal_identity_precision_pct": _percentage(
            len(formal_true_pairs),
            len(selected),
        ),
        "horizon_precision_pct": _percentage(len(horizon_true), len(selected)),
        "reachable_formal_recall_pct": _percentage(
            len(selected_pairs & reachable_pairs),
            len(reachable_pairs),
        ),
        "all_formal_recall_pct": _percentage(
            len(formal_true_pairs),
            len(formal_pairs),
        ),
        "touch_lead_minutes": _distribution(leads),
        "signal_gain_pct": _distribution(gains),
        "sub_minute_only_formal_pair_count": len(sub_minute_only),
        "missed_sub_minute_identity_count": len(sub_minute_only - selected_pairs),
        "d1_closed_count": len(returns),
        "d1_win_rate_pct": _percentage(sum(value > 0 for value in returns), len(returns)),
        "d1_average_return_pct": round(mean(returns), 4) if returns else None,
    }


def _acceptance_report(
    validation: Mapping[str, object],
    *,
    thresholds: Mapping[int, HazardThresholdSelection],
    baseline_parity: Mapping[str, object],
) -> dict[str, object]:
    identity = _mapping(validation.get("identity"))
    accounts = _mapping(validation.get("accounts"))
    formal = _mapping(_mapping(accounts.get("formal_touch")).get("normal"))
    action_group = _mapping(accounts.get("hazard_action"))
    action = _mapping(action_group.get("normal"))
    double_cost = _mapping(action_group.get("double_cost"))
    checks = {
        "baseline_parity": baseline_parity.get("passed") is True,
        "all_horizon_models_and_thresholds_ready": all(
            selection.status == "ready" for selection in thresholds.values()
        ),
        "minimum_30_validation_actions": (
            (_number(identity.get("selection_count")) or 0) >= 30
        ),
        "minimum_70pct_formal_precision": (
            (_number(identity.get("formal_identity_precision_pct")) or 0) >= 70.0
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
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "thresholds_frozen_from_calibration_only": True,
    }


def _model_report(
    model: HazardModelFit,
    threshold: HazardThresholdSelection,
) -> dict[str, object]:
    return {
        "status": model.status,
        "target_field": model.target_field,
        "features": list(HAZARD_FEATURE_NAMES),
        "training_row_count": model.training_row_count,
        "training_pair_count": model.training_pair_count,
        "class_counts": model.class_counts,
        "fit_dates": list(model.fit_dates),
        "coefficient_by_feature": model.coefficient_by_feature,
        "intercept": model.intercept,
        "fingerprint": model.fingerprint,
        "threshold_status": threshold.status,
        "threshold": threshold.threshold,
        "calibration_dates": list(threshold.calibration_dates),
        "selected_threshold_metrics": threshold.selected_metrics,
        "metrics_by_threshold": list(threshold.metrics_by_threshold),
    }


def _forward_overlay_report(
    model: HazardModelFit,
    threshold: object,
) -> dict[str, object]:
    from alphaagent.server.services.limit_up import radar_observation_repository

    coverage = radar_observation_repository.load_frame_coverage()
    base = {
        "status": "collecting_forward_overlay",
        "historical_model_fingerprint": model.fingerprint,
        "historical_action_threshold": _number(threshold),
        "trade_day_count": int(coverage.get("trade_day_count") or 0),
        "frame_count": int(coverage.get("frame_count") or 0),
        "observation_count": int(coverage.get("observation_count") or 0),
        "closed_action_event_count": 0,
        "promotion_requirements": {
            "minimum_trade_days": 60,
            "minimum_closed_action_events": 300,
        },
        "live_minute_source": "sync_stock_minute_bars(symbols, interval=1m, limit=240)",
        "eod_path_source": "sync_limit_up_radar_minutes",
    }
    threshold_value = _number(threshold)
    if (
        model.status != "ready"
        or threshold_value is None
        or int(coverage.get("trade_day_count") or 0) == 0
    ):
        return {
            **base,
            "scoreable_observation_count": 0,
            "action_event_count": 0,
            "probability_deciles": [],
            "note": "尚无可连接的一分钟雷达轨迹；动态概念和资金字段不反向进入历史模型。",
        }

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
    scored = _score_hazard_rows(overlay_rows, {ACTION_HORIZON: model})
    probability_field = _probability_field(ACTION_HORIZON)
    actions = select_top2_first_crossings(
        scored,
        threshold=threshold_value,
        probability_field=probability_field,
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
        from alphaagent.server.services.limit_up.preboard_momentum_data import (
            load_reliable_trade_dates,
        )

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
    trade_day_count = int(coverage.get("trade_day_count") or 0)
    ready_for_review = trade_day_count >= 60 and len(settled) >= 300
    returns = [float(row["net_return_pct"]) for row in settled]
    return {
        **base,
        "status": "ready_for_review" if ready_for_review else "collecting_forward_overlay",
        "scoreable_observation_count": len(scored),
        "scoreable_stock_day_count": len({_order_pair(row) for row in scored}),
        "action_event_count": len(actions),
        "closed_action_event_count": len(settled),
        "closed_action_win_rate_pct": _percentage(
            sum(value > 0 for value in returns),
            len(returns),
        ),
        "closed_action_average_return_pct": (
            round(mean(returns), 4) if returns else None
        ),
        "probability_deciles": _forward_probability_deciles(
            scored,
            probability_field=probability_field,
        ),
        "note": "概念和资金字段只按历史核心概率分层诊断，不改变概率或行动阈值。",
    }


def _blocked_report(status: str, *, session_count: int) -> dict[str, object]:
    return {
        "study_version": STUDY_VERSION,
        "status": status,
        "decision": "no_optimization_result",
        "scope": {"requested_session_count": int(session_count)},
        "formal_strategy_changed": False,
    }


def _forward_probability_deciles(
    rows: Sequence[Mapping[str, object]],
    *,
    probability_field: str,
) -> list[dict[str, object]]:
    first_by_pair: dict[tuple[str, date], Mapping[str, object]] = {}
    for row in sorted(rows, key=_forward_observation_key):
        first_by_pair.setdefault(_order_pair(row), row)
    ranked = sorted(
        first_by_pair.values(),
        key=lambda row: _number(row.get(probability_field)) or 0.0,
    )
    if not ranked:
        return []
    grouped: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for index, row in enumerate(ranked):
        decile = min(index * 10 // len(ranked) + 1, 10)
        grouped[decile].append(row)
    numeric_fields = (
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
    result: list[dict[str, object]] = []
    for decile in sorted(grouped):
        decile_rows = grouped[decile]
        probabilities = [
            value
            for row in decile_rows
            if (value := _number(row.get(probability_field))) is not None
        ]
        result.append(
            {
                "decile": decile,
                "stock_day_count": len(decile_rows),
                "probability_min": min(probabilities) if probabilities else None,
                "probability_max": max(probabilities) if probabilities else None,
                **{
                    f"average_{field}": (
                        round(mean(values), 4)
                        if (
                            values := [
                                value
                                for row in decile_rows
                                if (value := _number(row.get(field))) is not None
                            ]
                        )
                        else None
                    )
                    for field in numeric_fields
                },
            }
        )
    return result


def _forward_observation_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("trade_date") or row.get("signal_date") or "")[:10],
        str(row.get("captured_at") or row.get("signal_at") or ""),
        str(row.get("vt_symbol") or ""),
    )


def _orders_on_dates(
    orders: Sequence[Mapping[str, object]],
    allowed_dates: set[date],
) -> list[dict[str, object]]:
    return [dict(order) for order in orders if _order_date(order) in allowed_dates]


def _is_hazard_observation(row: Mapping[str, object]) -> bool:
    gain = _feature_number(row, "gain_pct")
    return bool(
        row.get("shared_strategy_passed") is True
        and row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= 3.0
    )


def _feature_number(row: Mapping[str, object], field: str) -> float | None:
    direct = _number(row.get(field))
    if direct is not None:
        return direct
    for container_name in ("features", "ignition_features"):
        container = row.get(container_name)
        if isinstance(container, Mapping):
            value = _number(container.get(field))
            if value is not None:
                return value
    return None


def _target_field(horizon: int) -> str:
    return f"formal_touch_within_{int(horizon)}m"


def _probability_field(horizon: int) -> str:
    return f"hazard_probability_{int(horizon)}m"


def _threshold_or_block(selection: HazardThresholdSelection) -> float:
    return float(selection.threshold) if selection.threshold is not None else 1.1


def _order_pair(row: Mapping[str, object]) -> tuple[str, date]:
    return str(row.get("vt_symbol") or ""), _order_date(row)


def _order_date(row: Mapping[str, object]) -> date:
    return _as_date(row.get("entry_date") or row.get("signal_date"))


def _as_date(value: object) -> date:
    parsed = _optional_date(value)
    return parsed or date.min


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
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _wall_clock(value: datetime) -> datetime:
    local = value.astimezone(_SHANGHAI) if value.tzinfo is not None else value
    return local.replace(tzinfo=None)


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


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


def _quantile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    return round(float(pd.Series(values).quantile(quantile)), 4)


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _display(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.4f}" if parsed is not None else "-"


def _pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.2f}%" if parsed is not None else "-"


def _ratio_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed * 100:.2f}%" if parsed is not None else "-"


def _signed_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:+.2f}%" if parsed is not None else "-"


def _coefficient_text(rows: Sequence[tuple[str, float]]) -> str:
    return "、".join(f"`{field}` {value:+.4f}" for field, value in rows) or "无"


def _write_output(path_text: str, content: str) -> None:
    path = Path(path_text)
    resolved = path.resolve()
    report_root = Path("memory/06_backtests").resolve()
    if report_root not in resolved.parents:
        raise ValueError("hazard report output must stay under memory/06_backtests")
    resolved.write_text(content, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate one-minute pre-board hazard")
    parser.add_argument("command", choices=("evaluate",))
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSION_COUNT)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_preboard_hazard(session_count=args.sessions)
    content = (
        render_hazard_markdown(report)
        if args.format == "markdown"
        else json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    if args.output:
        _write_output(args.output, content)
    print(content, end="")


if __name__ == "__main__":
    main()
