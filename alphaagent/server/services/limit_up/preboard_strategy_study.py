"""Database study comparing current touch entry with causal pre-board entry."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from math import prod
from pathlib import Path
from statistics import mean, median

import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.limit_up import (
    cash_backtest,
    history_engine,
    history_repository,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.first_board_stock_gene_research import (
    attach_prior_stock_gene_evidence_to_orders,
)
from alphaagent.server.services.limit_up.lane_repository import (
    FinancialIndex,
    build_financial_index,
)
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    attach_preboard_prior_evidence,
    load_five_minute_coverage,
    load_preboard_manifest,
    load_preboard_minute_bars,
    load_reliable_trade_dates,
)
from alphaagent.server.services.limit_up.preboard_baseline_model import (
    BASELINE_FEATURE_NAMES,
    BaselineModelFit,
    BaselineThresholdSelection,
    attach_baseline_account_targets,
    attach_formal_baseline_targets,
    baseline_reachability,
    calibrate_baseline_thresholds,
    first_baseline_signal,
    fit_baseline_model,
    formal_first_board_pairs,
)
from alphaagent.server.services.limit_up.preboard_strategy_replay import (
    IGNITION_FEATURE_NAMES,
    STUDY_VERSION,
    IgnitionFit,
    IgnitionThreshold,
    build_strategy_prefix_rows,
    calibrate_ignition_threshold,
    first_current_support_signal,
    first_ignition_signal,
    fit_ignition_model,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


DEFAULT_SESSION_COUNT = 60
FIT_SESSION_COUNT = 30
CALIBRATION_SESSION_COUNT = 10
MINIMUM_CALIBRATION_SIGNALS = 10
FEATURE_LOOKBACK_SESSIONS = 140
REPORT_DIRECTORY = Path("memory/06_backtests")
_BASELINE_PARITY_FIELDS = (
    "signal_count",
    "filled_count",
    "trade_count",
    "win_count",
    "win_rate",
    "total_return_pct",
    "max_drawdown_pct",
)


def evaluate_current_strategy_preboard(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
) -> dict[str, object]:
    """Run the bounded database replay without changing production versions."""

    manifest = load_preboard_manifest(session_count=session_count)
    if manifest.empty:
        return _blocked_report("blocked_by_manifest", session_count=session_count)
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
        if start <= _as_date(day.get("trade_date"), date.min) <= end
    ]
    manifest = attach_preboard_prior_evidence(manifest, history_days)
    coverage = load_five_minute_coverage(manifest)
    complete_pairs = {
        (str(row.vt_symbol), _as_date(row.trade_date, date.min))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    complete_ratio = len(complete_pairs) / len(manifest) if len(manifest) else 0.0
    if complete_ratio < 0.95:
        return {
            **_blocked_report("blocked_by_minute_coverage", session_count=session_count),
            "coverage": _coverage_report(manifest, coverage),
        }

    minute_rows = load_preboard_minute_bars(manifest)
    feature_frame, feature_coverage = _load_bounded_feature_frame(
        manifest,
        lookback_sessions=FEATURE_LOOKBACK_SESSIONS,
    )
    feature_by_pair = _feature_index(feature_frame, set(dates))
    financial_index = _load_financial_index()
    prefix_rows, filter_audit = _build_all_strategy_prefix_rows(
        manifest,
        minute_rows,
        complete_pairs,
        feature_by_pair,
        financial_index,
    )

    fit_dates, calibration_dates, validation_dates = _date_split(dates)
    formal_orders, profitability_audit = _formal_orders(
        history_days,
        scoped_history_days,
        start,
        end,
    )
    formal_symbols = sorted(
        {
            str(order.get("vt_symbol") or "")
            for order in formal_orders
            if str(order.get("vt_symbol") or "")
        }
    )
    formal_result_dates = [
        parsed
        for order in formal_orders
        if (parsed := _optional_date(order.get("result_date"))) is not None
    ]
    formal_account_end = max(formal_result_dates, default=end)
    formal_bars = history_repository.load_account_daily_bars(
        formal_symbols,
        start,
        formal_account_end,
    )
    formal_trade_dates = load_reliable_trade_dates(start, formal_account_end)
    baseline_account_orders = _baseline_account_orders_by_phase(
        formal_orders,
        formal_bars,
        formal_trade_dates,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
    )
    labeled_prefix_rows = attach_formal_baseline_targets(prefix_rows, formal_orders)
    labeled_prefix_rows = attach_baseline_account_targets(
        labeled_prefix_rows,
        [
            *baseline_account_orders["fit"],
            *baseline_account_orders["calibration"],
            *baseline_account_orders["validation"],
        ],
    )
    model = fit_ignition_model(labeled_prefix_rows, fit_dates=set(fit_dates))
    threshold = calibrate_ignition_threshold(
        labeled_prefix_rows,
        model,
        calibration_dates=set(calibration_dates),
        minimum_signal_count=MINIMUM_CALIBRATION_SIGNALS,
    )
    current_support_signals = _first_support_signals(labeled_prefix_rows)
    ignition_signals = (
        _first_model_signals(labeled_prefix_rows, model, threshold.threshold)
        if threshold.threshold is not None
        else []
    )
    baseline_prepare_model = fit_baseline_model(
        labeled_prefix_rows,
        fit_dates=set(fit_dates),
        target_field="formal_touch_baseline_target",
    )
    baseline_prepare_thresholds = calibrate_baseline_thresholds(
        labeled_prefix_rows,
        baseline_prepare_model,
        calibration_dates=set(calibration_dates),
        minimum_signal_count=MINIMUM_CALIBRATION_SIGNALS,
        target_field="formal_touch_baseline_target",
    )
    baseline_action_model = fit_baseline_model(
        labeled_prefix_rows,
        fit_dates=set(fit_dates),
        target_field="formal_touch_account_target",
    )
    baseline_action_thresholds = calibrate_baseline_thresholds(
        labeled_prefix_rows,
        baseline_action_model,
        calibration_dates=set(calibration_dates),
        minimum_signal_count=MINIMUM_CALIBRATION_SIGNALS,
        target_field="formal_touch_account_target",
    )
    baseline_prepare_signals = _first_baseline_signals(
        labeled_prefix_rows,
        baseline_prepare_model,
        baseline_prepare_thresholds.prepare_threshold,
        stage="prepare",
    )
    baseline_action_signals = _first_baseline_signals(
        labeled_prefix_rows,
        baseline_action_model,
        baseline_action_thresholds.action_threshold,
        stage="action",
    )
    early_signal_orders = {
        "current_support_55": [
            _early_order(signal) for signal in current_support_signals
        ],
        "post_filter_ignition": [_early_order(signal) for signal in ignition_signals],
        "baseline_precursor_action": [
            _early_order(signal) for signal in baseline_action_signals
        ],
    }
    early_orders = {
        key: [
            order
            for order in orders
            if order.get("fillable") is True
        ]
        for key, orders in early_signal_orders.items()
    }
    variant_orders = _build_variant_orders(
        formal_orders,
        support_orders=early_orders["current_support_55"],
        ignition_orders=early_orders["post_filter_ignition"],
        baseline_action_orders=early_orders["baseline_precursor_action"],
        baseline_prepare_signals=baseline_prepare_signals,
    )
    all_symbols = {
        str(order.get("vt_symbol") or "")
        for orders in variant_orders.values()
        for order in orders
        if str(order.get("vt_symbol") or "")
    }
    result_dates = [
        parsed
        for orders in variant_orders.values()
        for order in orders
        if (parsed := _optional_date(order.get("result_date"))) is not None
    ]
    account_end = max(result_dates, default=end)
    bars = history_repository.load_account_daily_bars(
        sorted(all_symbols),
        start,
        account_end,
    )
    trade_dates = load_reliable_trade_dates(start, account_end)
    variants = {
        name: _variant_report(
            orders,
            bars,
            trade_dates,
            validation_dates=set(validation_dates),
            early_signals=(
                current_support_signals
                if name == "current_support_55"
                else ignition_signals
                if name == "post_filter_ignition"
                else baseline_action_signals
                if name == "baseline_precursor_action"
                else []
            ),
        )
        for name, orders in variant_orders.items()
    }
    baseline_match = _baseline_match_report(
        labeled_prefix_rows,
        formal_orders,
        baseline_account_orders,
        baseline_prepare_signals,
        baseline_action_signals,
        validation_dates=set(validation_dates),
    )

    from alphaagent.server.services.limit_up.history_service import (
        get_scheduled_history_backtest,
    )

    service_baseline = get_scheduled_history_backtest(
        start,
        end,
        trade_limit=None,
    )
    expected_summary = _mapping(service_baseline.get("summary"))
    actual_summary = _mapping(
        _mapping(variants["formal_touch_current"].get("full")).get("normal")
    )
    baseline_parity = compare_baseline_summaries(expected_summary, actual_summary)
    legacy_decision = _optimization_decision(
        variants,
        threshold,
        baseline_parity,
    )
    precursor_reliability = _baseline_precursor_decision(
        variants,
        baseline_match,
        baseline_prepare_thresholds,
        baseline_action_thresholds,
        baseline_parity,
    )
    status = "ready_historical_candidate_proxy"
    decision = str(precursor_reliability["decision"])
    if baseline_parity["passed"] is not True:
        status = "blocked_by_baseline_mismatch"
        decision = "no_optimization_result"
    elif (
        baseline_prepare_thresholds.prepare_threshold is None
        or baseline_action_thresholds.action_threshold is None
    ):
        status = "blocked_by_baseline_precursor_sample"
        decision = "no_baseline_precursor_result"

    report = {
        "study_version": STUDY_VERSION,
        "status": status,
        "decision": decision,
        "validation_kind": "viewed_historical_time_validation",
        "contract": {
            "baseline_history_version": HISTORY_STRATEGY_VERSION,
            "baseline_execution_version": scheduled_execution.SCHEDULED_EXECUTION_VERSION,
            "candidate_core": "lane_research.evaluate_lane_candidate",
            "profitability_gate": scheduled_execution.first_board_profitability_filter_metadata(),
            "current_momentum_min_score": 55.0,
            "capture_gain_pct": 3.0,
            "capture_operator": ">=",
            "baseline_precursor_target": "current_formal_first_board_touch_order_membership",
            "prepare_state_trades": False,
            "action_state_trades": True,
            "decision_bars": "completed_5m_prefix_only",
            "entry": "next_5m_open_same_window",
            "unchanged_lane": "two_to_three",
            "exit": "D+1 official close",
            "max_positions": 2,
            "formal_strategy_changed": False,
            "live_equivalent": False,
        },
        "scope": {
            "session_count": len(dates),
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "fit_dates": [value.isoformat() for value in fit_dates],
            "calibration_dates": [value.isoformat() for value in calibration_dates],
            "validation_dates": [value.isoformat() for value in validation_dates],
        },
        "coverage": {
            **_coverage_report(manifest, coverage),
            **feature_coverage,
            "history_day_count": len(history_days),
            "scoped_history_day_count": len(scoped_history_days),
            "financial_symbol_count": len(financial_index),
        },
        "filter_audit": {
            **filter_audit,
            "formal_profitability_filter": profitability_audit,
        },
        "model": _model_report(model, threshold),
        "legacy_composite_target_decision": legacy_decision,
        "baseline_precursor": {
            "prepare_model": _baseline_model_report(
                baseline_prepare_model,
                baseline_prepare_thresholds,
            ),
            "action_model": _baseline_model_report(
                baseline_action_model,
                baseline_action_thresholds,
            ),
            "match": baseline_match,
            "reliability": precursor_reliability,
        },
        "baseline_parity": baseline_parity,
        "variants": variants,
        "simultaneous_signals": {
            "current_support_55": _simultaneous_signal_report(
                early_signal_orders["current_support_55"]
            ),
            "post_filter_ignition": _simultaneous_signal_report(
                early_signal_orders["post_filter_ignition"]
            ),
            "baseline_precursor_action": _simultaneous_signal_report(
                early_signal_orders["baseline_precursor_action"]
            ),
        },
        "execution_comparability": {
            "status": "candidate_proxy_only",
            "live_equivalent": False,
            "missing_evidence": [
                "intraday_market_repair_frames",
                "intraday_sector_fund_flow",
                "intraday_stock_fund_flow",
                "intraday_sector_expansion_frames",
                "tick_l2_queue",
            ],
            "order_flow_feature_level": "5m_volume_and_amount_proxy",
            "real_large_order_label": False,
        },
        "limitations": [
            "全体3%以上母池先进入共用lane和同股联合率门；最终未触板股票保留为负样本。",
            "日线最高价只用于完整枚举母池，不进入信号、过滤、排序或阈值选择。",
            "当前历史70%账户本身是候选代理；缺少逐时点市场、板块、资金帧，不能称实时等价。",
            "五分钟成交量和成交额只表示聚合动能，不能证明主动大单、撤单速度或L2队列。",
            "阈值在校准段冻结，最后20日已经被查看，只能称历史时间验证。",
            "正式v15/v9、实时5%推荐、两仓规则和二进三规则均未修改。",
        ],
    }
    return report


def compare_baseline_summaries(
    expected: Mapping[str, object],
    actual: Mapping[str, object],
) -> dict[str, object]:
    """Require exact integer and rounded metric parity before optimization."""

    fields: dict[str, dict[str, object]] = {}
    for key in _BASELINE_PARITY_FIELDS:
        expected_value = _number(expected.get(key))
        actual_value = _number(actual.get(key))
        integer = key in {"signal_count", "filled_count", "trade_count", "win_count"}
        passed = bool(
            expected_value is not None
            and actual_value is not None
            and (
                int(expected_value) == int(actual_value)
                if integer
                else abs(expected_value - actual_value) <= 0.0001
            )
        )
        fields[key] = {
            "passed": passed,
            "expected": expected_value,
            "actual": actual_value,
        }
    return {
        "passed": all(row["passed"] is True for row in fields.values()),
        "fields": fields,
    }


def render_current_strategy_preboard_markdown(
    report: Mapping[str, object],
) -> str:
    """Render the decision and exact account comparison for durable memory."""

    scope = _mapping(report.get("scope"))
    coverage = _mapping(report.get("coverage"))
    audit = _mapping(report.get("filter_audit"))
    model = _mapping(report.get("model"))
    threshold = _mapping(model.get("threshold_selection"))
    precursor = _mapping(report.get("baseline_precursor"))
    precursor_prepare_model = _mapping(precursor.get("prepare_model"))
    precursor_action_model = _mapping(precursor.get("action_model"))
    precursor_prepare_threshold = _mapping(
        precursor_prepare_model.get("threshold_selection")
    )
    precursor_action_threshold = _mapping(
        precursor_action_model.get("threshold_selection")
    )
    precursor_match = _mapping(precursor.get("match"))
    precursor_reliability = _mapping(precursor.get("reliability"))
    parity = _mapping(report.get("baseline_parity"))
    variants = _mapping(report.get("variants"))
    lines = [
        "# 当前打板策略 >=3% 触板基线前置识别研究",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status')}`；结论：`{report.get('decision')}`。",
        f"- 区间：`{scope.get('date_start')}..{scope.get('date_end')}`，{scope.get('session_count', 0)} 个交易日。",
        f"- 全体>=3%母池：{coverage.get('manifest_pair_count', 0)} 个股票日；完整5分钟路径 "
        f"{coverage.get('complete_pair_count', 0)}/{coverage.get('manifest_pair_count', 0)} "
        f"（{_display(coverage.get('complete_pair_pct'))}%）。",
        f"- 当前策略共用过滤后：{audit.get('shared_candidate_pair_count', 0)} 个股票日、"
        f"{audit.get('shared_prefix_count', 0)} 个可评估前缀；未触板负样本 "
        f"{audit.get('shared_non_touch_pair_count', 0)} 个。",
        f"- 正式基线一致性：`{parity.get('passed')}`；不一致时禁止输出优化结论。",
        "",
        "## Same-account comparison",
        "",
        "| 方案 | 阶段 | 信号 | 两仓成交 | 胜率 | 复利 | 最大回撤 | PF | 双倍成本复利 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    labels = {
        "formal_touch_current": "当前触板基线",
        "current_support_55": "共用规则后直接买入对照",
        "post_filter_ignition": "旧复合收益标签动能模型",
        "baseline_precursor_action": "触板基线前置买入模型",
    }
    for key in (
        "formal_touch_current",
        "current_support_55",
        "post_filter_ignition",
        "baseline_precursor_action",
    ):
        variant = _mapping(variants.get(key))
        for phase, phase_label in (("full", "全区间"), ("validation", "最后20日")):
            phase_row = _mapping(variant.get(phase))
            normal = _mapping(phase_row.get("normal"))
            stress = _mapping(phase_row.get("double_cost"))
            lines.append(
                f"| {labels[key]} | {phase_label} | {normal.get('signal_count', 0)} | "
                f"{normal.get('trade_count', 0)} | {_display(normal.get('win_rate'))}% | "
                f"{_signed(normal.get('total_return_pct'))}% | {_signed(normal.get('max_drawdown_pct'))}% | "
                f"{_display(normal.get('profit_factor'))} | {_signed(stress.get('total_return_pct'))}% |"
            )

    lines.extend(
        [
            "",
            "## Early first-board quality",
            "",
            "| 方案 | 阶段 | 首板推荐 | 可成交 | 后续触板率 | 最终封板率 | D+1胜率 | D+1均值 | 日等权复利 | 回撤 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key in (
        "current_support_55",
        "post_filter_ignition",
        "baseline_precursor_action",
    ):
        variant = _mapping(variants.get(key))
        for phase, phase_label in (("full", "全区间"), ("validation", "最后20日")):
            quality = _mapping(
                _mapping(variant.get(phase)).get("early_first_board_quality")
            )
            lines.append(
                f"| {labels[key]} | {phase_label} | {quality.get('signal_count', 0)} | "
                f"{quality.get('closed_count', 0)} | "
                f"{_display(quality.get('later_touch_rate_pct'))}% | "
                f"{_display(quality.get('final_seal_rate_pct'))}% | "
                f"{_display(quality.get('win_rate_pct'))}% | "
                f"{_signed(quality.get('average_net_return_pct'))}% | "
                f"{_signed(quality.get('daily_equal_weight_compound_return_pct'))}% | "
                f"{_signed(quality.get('max_drawdown_pct'))}% |"
            )

    lines.extend(
        [
            "",
            "## Formal-touch baseline precursor",
            "",
            f"- 准备模型：`{precursor_prepare_model.get('status')}`；买入模型："
            f"`{precursor_action_model.get('status')}`；训练股票日前缀 "
            f"{precursor_action_model.get('training_row_count', 0)} 行/"
            f"{precursor_action_model.get('training_pair_count', 0)} 对。",
            f"- 准备阈值：`{precursor_prepare_threshold.get('prepare_threshold')}`；买入阈值："
            f"`{precursor_action_threshold.get('action_threshold')}`；准备状态不进入账户。",
            "- 准备标签是稍后进入正式首板候选；买入标签是触板基线两仓实际成交的首板身份。D+1收益不参与标签或阈值。",
            "",
            "| 阶段 | 状态 | 信号 | 正式候选精度/召回 | 两仓身份精度/召回 | 提前中位 | 涨幅中位 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for phase, phase_label in (("full", "全区间"), ("validation", "最后20日")):
        phase_match = _mapping(precursor_match.get(phase))
        for state, state_label in (("prepare", "准备"), ("action", "买入")):
            row = _mapping(phase_match.get(state))
            lines.append(
                f"| {phase_label} | {state_label} | {row.get('signal_count', 0)} | "
                f"{_display(row.get('formal_baseline_precision_pct'))}%/"
                f"{_display(row.get('reachable_baseline_recall_pct'))}% | "
                f"{_display(row.get('baseline_account_precision_pct'))}%/"
                f"{_display(row.get('reachable_baseline_account_recall_pct'))}% | "
                f"{_display(row.get('lead_minutes_median'))}分 | "
                f"{_display(row.get('signal_gain_median_pct'))}% |"
            )
    validation_action = _mapping(
        _mapping(precursor_match.get("validation")).get("action")
    )
    true_d1 = _mapping(validation_action.get("account_true_positive_d1"))
    false_d1 = _mapping(validation_action.get("account_false_positive_d1"))
    lines.extend(
        [
            "",
            f"- 最后20日买入信号中，两仓身份真阳性 D+1 为 "
            f"{true_d1.get('closed_count', 0)} 笔/胜率 {_display(true_d1.get('win_rate_pct'))}%/"
            f"均值 {_signed(true_d1.get('average_net_return_pct'))}%；假阳性为 "
            f"{false_d1.get('closed_count', 0)} 笔/胜率 {_display(false_d1.get('win_rate_pct'))}%/"
            f"均值 {_signed(false_d1.get('average_net_return_pct'))}%。",
            f"- 可靠性：`{precursor_reliability.get('decision')}`；失败门："
            f"`{json.dumps(precursor_reliability.get('failed_checks') or [], ensure_ascii=False)}`。",
            "",
            "## Legacy composite-target layer",
            "",
            f"- 模型状态：`{model.get('status')}`；训练前缀 {model.get('training_row_count', 0)}；"
            f"类别 {json.dumps(model.get('class_counts') or {}, ensure_ascii=False)}。",
            f"- 校准状态：`{threshold.get('status')}`；冻结阈值：`{threshold.get('threshold')}`；"
            f"最低校准信号：{threshold.get('minimum_signal_count')}。",
            "- 目标是“后续触板且最终封板且按提前成交价到 D+1 收盘费用后为正”；"
            "报告仍分别列出触板率、封板率和 D+1 胜率，不能用触板率代替收益。",
            "",
            "## Filter audit",
            "",
            f"- 联合率门拒绝：{json.dumps(audit.get('profitability_rejection_counts') or {}, ensure_ascii=False)}。",
            f"- lane主要拒绝：{json.dumps(audit.get('lane_blocker_counts') or {}, ensure_ascii=False)}。",
            f"- 特征缺失：{audit.get('missing_feature_pair_count', 0)}；完整路径但无共用候选："
            f"{audit.get('no_shared_candidate_pair_count', 0)}。",
            f"- 同时拉升冲突见 `simultaneous_signals`：只有同一可成交时刻超过两只时，"
            "模型概率/当前rank才参与两仓排序；任何后来更高概率都不能替换首次信号。",
            "",
            "## Decision",
            "",
        ]
    )
    simultaneous = _mapping(report.get("simultaneous_signals"))
    for key in (
        "current_support_55",
        "post_filter_ignition",
        "baseline_precursor_action",
    ):
        quality = _mapping(
            _mapping(_mapping(variants.get(key)).get("validation")).get(
                "early_first_board_quality"
            )
        )
        collision = _mapping(simultaneous.get(key))
        lines.append(
            f"- {labels[key]}最后20日信号涨幅 P25/中位/P75："
            f"`{_display(quality.get('signal_gain_p25_pct'))}%/"
            f"{_display(quality.get('signal_gain_median_pct'))}%/"
            f"{_display(quality.get('signal_gain_p75_pct'))}%`；"
            f"全区间同刻多股 {collision.get('same_timestamp_group_count', 0)} 组、"
            f"超过两仓 {collision.get('oversubscribed_group_count', 0)} 组，"
            f"单刻最多 {collision.get('max_candidates_same_timestamp', 0)} 只。"
        )
    decision = str(report.get("decision") or "")
    if decision == "baseline_precursor_historical_pass_requires_forward_validation":
        lines.append(
            "触板基线前置模型通过已查看历史门，但仍不能上线；下一步只允许用已启用的3%前向帧验证。"
        )
    elif decision == "no_baseline_precursor_result":
        lines.append(
            "触板基线前置模型样本或校准信号不足，不能输出可靠性结论。"
        )
    elif decision == "no_optimization_result":
        lines.append("正式基线未精确复现，本次不比较提前方案收益。")
    else:
        lines.append(
            "触板基线前置模型没有同时守住基线精度、胜率、复利、回撤和双倍成本门，不替换当前触板规则。"
        )
    lines.extend(
        [
            "",
            "## Data boundary",
            "",
            "- 本次确实复用了当前候选核与联合率门，没有从最终涨停名单事后前移。",
            "- 历史5分钟量价不是逐笔主动买单。真实大单失衡只能由未来保存的逐笔/L2或近端逐笔审计证明。",
            "- 当前历史账户仍缺盘中市场修复、行业/概念扩散、板块资金、个股资金和L2队列，"
            "因此结论固定为候选代理而非实时等价。",
            "",
            "## How to verify",
            "",
            "```bash",
            "docker compose run --rm -T --no-deps \\",
            '  -v "$PWD:/workspace:ro" -w /workspace \\',
            "  -e PYTHONPATH=/workspace:/app/third_party/akshare \\",
            "  --entrypoint python alphaagent-api \\",
            "  -m alphaagent.server.services.limit_up.preboard_strategy_study evaluate \\",
            "  --sessions 60 --format markdown",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _load_bounded_feature_frame(
    manifest: pd.DataFrame,
    *,
    lookback_sessions: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    raw_frame, raw_coverage = history_repository.load_reliable_history_frame()
    evaluation_start = pd.to_datetime(manifest["trade_date"]).min().normalize()
    all_dates = sorted(pd.to_datetime(raw_frame["trade_date"]).dropna().unique())
    start_index = next(
        (index for index, value in enumerate(all_dates) if value >= evaluation_start),
        len(all_dates) - 1,
    )
    context_start = all_dates[max(start_index - max(int(lookback_sessions), 1), 0)]
    bounded = raw_frame.loc[raw_frame["trade_date"].ge(context_start)].copy()
    feature_frame = history_engine.build_daily_feature_frame(bounded)
    return feature_frame, {
        "feature_context_start": pd.Timestamp(context_start).date().isoformat(),
        "feature_loaded_rows": int(len(bounded)),
        "feature_computed_rows": int(len(feature_frame)),
        "feature_source_loaded_rows": int(raw_coverage.get("loaded_rows") or 0),
        "industry_membership_mode": raw_coverage.get("industry_membership_mode"),
        "industry_membership_survivorship_risk": raw_coverage.get(
            "industry_membership_survivorship_risk"
        ),
    }


def _load_financial_index() -> FinancialIndex:
    schema.ensure_schema_once(get_engine())
    with session_scope() as session:
        rows = [
            dict(row)
            for row in session.execute(
                select(schema.stock_financial_reports)
            ).mappings()
        ]
    return build_financial_index(rows)


def _feature_index(
    frame: pd.DataFrame,
    evaluation_dates: set[date],
) -> dict[tuple[str, date], dict[str, object]]:
    selected = frame.loc[
        pd.to_datetime(frame["trade_date"]).dt.date.isin(evaluation_dates)
    ]
    return {
        (str(row["vt_symbol"]), _as_date(row["trade_date"], date.min)): dict(row)
        for row in selected.to_dict(orient="records")
    }


def _build_all_strategy_prefix_rows(
    manifest: pd.DataFrame,
    minute_rows: pd.DataFrame,
    complete_pairs: set[tuple[str, date]],
    feature_by_pair: Mapping[tuple[str, date], Mapping[str, object]],
    financial_index: FinancialIndex,
    *,
    bar_minutes: int = 5,
    passed_only: bool = False,
    row_projection: Callable[[Mapping[str, object]], dict[str, object]] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    manifest_by_pair = {
        (str(row["vt_symbol"]), _as_date(row["trade_date"], date.min)): dict(row)
        for row in manifest.to_dict(orient="records")
    }
    minute = minute_rows.copy()
    minute["trade_date"] = pd.to_datetime(minute["trade_date"]).dt.date
    profitability_rejections: Counter[str] = Counter()
    lane_blockers: Counter[str] = Counter()
    prefix_rows: list[dict[str, object]] = []
    shared_pairs: set[tuple[str, date]] = set()
    shared_non_touch_pairs: set[tuple[str, date]] = set()
    missing_features = 0
    no_shared = 0
    qualified_by_profitability = 0
    evaluated_prefix_count = 0
    shared_prefix_count = 0

    groups = minute.groupby(["vt_symbol", "trade_date"], sort=False)
    for (symbol, trade_date), group in groups:
        pair = (str(symbol), trade_date)
        if pair not in complete_pairs:
            continue
        manifest_row = manifest_by_pair.get(pair)
        if manifest_row is None:
            continue
        gate = scheduled_execution.first_board_profitability_gate(
            {**manifest_row, "lane": "first_board"}
        )
        if gate["profitability_gate_passed"] is not True:
            profitability_rejections[str(gate["profitability_gate_reason"])] += 1
            continue
        qualified_by_profitability += 1
        feature_row = feature_by_pair.get(pair)
        if feature_row is None:
            missing_features += 1
            continue
        rows = build_strategy_prefix_rows(
            manifest_row,
            feature_row,
            group.to_dict(orient="records"),
            financial_index=financial_index,
            bar_minutes=bar_minutes,
        )
        shared_rows = [
            row for row in rows if row.get("shared_strategy_passed") is True
        ]
        selected_rows = shared_rows if passed_only else rows
        prefix_rows.extend(
            row_projection(row) if row_projection is not None else row
            for row in selected_rows
        )
        evaluated_prefix_count += len(rows)
        shared_prefix_count += len(shared_rows)
        for row in rows:
            lane_blockers.update(str(value) for value in row.get("shared_lane_blockers") or [])
        if shared_rows:
            shared_pairs.add(pair)
            if manifest_row.get("touched_limit") is not True:
                shared_non_touch_pairs.add(pair)
        else:
            no_shared += 1

    return prefix_rows, {
        "manifest_pair_count": len(manifest_by_pair),
        "complete_pair_count": len(complete_pairs),
        "profitability_qualified_pair_count": qualified_by_profitability,
        "profitability_rejection_counts": dict(sorted(profitability_rejections.items())),
        "missing_feature_pair_count": missing_features,
        "shared_candidate_pair_count": len(shared_pairs),
        "shared_non_touch_pair_count": len(shared_non_touch_pairs),
        "shared_prefix_count": shared_prefix_count,
        "evaluated_prefix_count": evaluated_prefix_count,
        "no_shared_candidate_pair_count": no_shared,
        "lane_blocker_counts": dict(lane_blockers.most_common(20)),
    }


def _formal_orders(
    history_days: Sequence[Mapping[str, object]],
    scoped_days: Sequence[Mapping[str, object]],
    start: date,
    end: date,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    extracted = scheduled_execution.extract_scheduled_orders(scoped_days)
    enriched = attach_prior_stock_gene_evidence_to_orders(history_days, extracted)
    qualified, audit = scheduled_execution.filter_profitability_qualified_orders(enriched)
    return [
        dict(order)
        for order in qualified
        if start <= _as_date(order.get("entry_date"), date.min) <= end
    ], audit


def _build_variant_orders(
    formal_orders: Sequence[Mapping[str, object]],
    *,
    support_orders: Sequence[Mapping[str, object]],
    ignition_orders: Sequence[Mapping[str, object]],
    baseline_action_orders: Sequence[Mapping[str, object]],
    baseline_prepare_signals: Sequence[Mapping[str, object]],
) -> dict[str, list[dict[str, object]]]:
    if any(
        signal.get("baseline_state") != "baseline_prepare"
        for signal in baseline_prepare_signals
    ):
        raise ValueError("prepare collection contains a non-prepare signal")
    relay_orders = [
        dict(order)
        for order in formal_orders
        if str(order.get("lane") or "") == "two_to_three"
    ]
    return {
        "formal_touch_current": [dict(order) for order in formal_orders],
        "current_support_55": [
            *relay_orders,
            *(dict(order) for order in support_orders),
        ],
        "post_filter_ignition": [
            *relay_orders,
            *(dict(order) for order in ignition_orders),
        ],
        "baseline_precursor_action": [
            *relay_orders,
            *(dict(order) for order in baseline_action_orders),
        ],
    }


def _first_support_signals(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for group in _prefix_groups(rows).values():
        signal = first_current_support_signal(group)
        if signal is not None:
            result.append(signal)
    return sorted(result, key=_signal_sort_key)


def _first_model_signals(
    rows: Sequence[Mapping[str, object]],
    model: IgnitionFit,
    threshold: float | None,
) -> list[dict[str, object]]:
    if threshold is None:
        return []
    result: list[dict[str, object]] = []
    for group in _prefix_groups(rows).values():
        signal = first_ignition_signal(group, model, threshold=threshold)
        if signal is not None:
            result.append(signal)
    return sorted(result, key=_signal_sort_key)


def _first_baseline_signals(
    rows: Sequence[Mapping[str, object]],
    model: BaselineModelFit,
    threshold: float | None,
    *,
    stage: str,
) -> list[dict[str, object]]:
    if threshold is None:
        return []
    result: list[dict[str, object]] = []
    for group in _prefix_groups(rows).values():
        signal = first_baseline_signal(
            group,
            model,
            threshold=threshold,
            stage=stage,
        )
        if signal is not None:
            result.append(signal)
    return sorted(result, key=_signal_sort_key)


def _prefix_groups(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], list[Mapping[str, object]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                str(row.get("signal_date") or "")[:10],
                str(row.get("vt_symbol") or ""),
            )
        ].append(row)
    return dict(grouped)


def _early_order(signal: Mapping[str, object]) -> dict[str, object]:
    return {
        **dict(signal),
        "entry_date": str(signal.get("signal_date") or "")[:10],
        "buy_time": str(signal.get("entry_time") or signal.get("signal_time") or ""),
        "lane": "first_board",
        "board_lane": "first_board",
        "signal_kind": "momentum",
        "entry_price": _number(signal.get("entry_price")),
        "result_date": str(signal.get("result_date") or "")[:10] or None,
        "d_board_status": "sealed" if signal.get("sealed_limit") else "failed",
        "outcome": {
            "touched": bool(signal.get("touched_limit")),
            "sealed": bool(signal.get("sealed_limit")),
            "next_close_price": _number(signal.get("d1_close_price")),
        },
        "candidate_source": "all_3pct_shared_strategy_prefix",
    }


def _baseline_match_phase(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    signals: Sequence[Mapping[str, object]],
    baseline_account_orders: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    formal_pairs = formal_first_board_pairs(formal_orders)
    reachability = baseline_reachability(prefix_rows, formal_orders)
    account_orders = list(baseline_account_orders or formal_orders)
    account_pairs = formal_first_board_pairs(account_orders)
    account_reachability = baseline_reachability(prefix_rows, account_orders)
    signal_rows = [dict(signal) for signal in signals]
    true_positive_rows = [
        signal for signal in signal_rows if _signal_pair(signal) in formal_pairs
    ]
    true_positive_count = len(true_positive_rows)
    account_true_positive_rows = [
        signal for signal in signal_rows if _signal_pair(signal) in account_pairs
    ]
    account_true_positive_count = len(account_true_positive_rows)
    reachable_count = int(reachability["reachable_formal_pair_count"])
    reachable_account_count = int(
        account_reachability["reachable_formal_pair_count"]
    )
    touch_time_by_pair = _formal_touch_time_by_pair(formal_orders)
    lead_minutes = [
        lead
        for signal in true_positive_rows
        if (
            lead := _lead_minutes(
                str(signal.get("signal_time") or ""),
                touch_time_by_pair.get(_signal_pair(signal)),
            )
        )
        is not None
        and lead >= 0
    ]
    gains = [
        value
        for signal in signal_rows
        if (
            value := _number(
                _mapping(signal.get("features")).get("gain_pct")
            )
        )
        is not None
    ]
    return {
        **reachability,
        "signal_count": len(signal_rows),
        "fillable_count": sum(signal.get("fillable") is True for signal in signal_rows),
        "true_positive_count": true_positive_count,
        "false_positive_count": len(signal_rows) - true_positive_count,
        "formal_baseline_precision_pct": _percentage(
            true_positive_count,
            len(signal_rows),
        ),
        "all_baseline_recall_pct": _percentage(
            true_positive_count,
            len(formal_pairs),
        ),
        "reachable_baseline_recall_pct": _percentage(
            true_positive_count,
            reachable_count,
        ),
        "baseline_account_pair_count": len(account_pairs),
        "reachable_baseline_account_pair_count": reachable_account_count,
        "account_true_positive_count": account_true_positive_count,
        "account_false_positive_count": len(signal_rows) - account_true_positive_count,
        "baseline_account_precision_pct": _percentage(
            account_true_positive_count,
            len(signal_rows),
        ),
        "all_baseline_account_recall_pct": _percentage(
            account_true_positive_count,
            len(account_pairs),
        ),
        "reachable_baseline_account_recall_pct": _percentage(
            account_true_positive_count,
            reachable_account_count,
        ),
        "lead_minutes_p25": _quantile(lead_minutes, 0.25),
        "lead_minutes_median": _median(lead_minutes),
        "lead_minutes_p75": _quantile(lead_minutes, 0.75),
        "signal_gain_p25_pct": _quantile(gains, 0.25),
        "signal_gain_median_pct": _median(gains),
        "signal_gain_p75_pct": _quantile(gains, 0.75),
        "true_positive_d1": _baseline_return_quality(true_positive_rows),
        "false_positive_d1": _baseline_return_quality(
            [
                signal
                for signal in signal_rows
                if _signal_pair(signal) not in formal_pairs
            ]
        ),
        "account_true_positive_d1": _baseline_return_quality(
            account_true_positive_rows
        ),
        "account_false_positive_d1": _baseline_return_quality(
            [
                signal
                for signal in signal_rows
                if _signal_pair(signal) not in account_pairs
            ]
        ),
    }


def _baseline_match_report(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    baseline_account_orders: Mapping[str, Sequence[Mapping[str, object]]],
    prepare_signals: Sequence[Mapping[str, object]],
    action_signals: Sequence[Mapping[str, object]],
    *,
    validation_dates: set[date],
) -> dict[str, object]:
    validation_prefixes = [
        row
        for row in prefix_rows
        if _as_date(row.get("signal_date"), date.min) in validation_dates
    ]
    validation_orders = [
        order
        for order in formal_orders
        if _as_date(order.get("entry_date"), date.min) in validation_dates
    ]
    validation_prepare = [
        signal
        for signal in prepare_signals
        if _as_date(signal.get("signal_date"), date.min) in validation_dates
    ]
    validation_action = [
        signal
        for signal in action_signals
        if _as_date(signal.get("signal_date"), date.min) in validation_dates
    ]
    return {
        "full": {
            "prepare": _baseline_match_phase(
                prefix_rows,
                formal_orders,
                prepare_signals,
                baseline_account_orders.get("full", []),
            ),
            "action": _baseline_match_phase(
                prefix_rows,
                formal_orders,
                action_signals,
                baseline_account_orders.get("full", []),
            ),
        },
        "validation": {
            "prepare": _baseline_match_phase(
                validation_prefixes,
                validation_orders,
                validation_prepare,
                baseline_account_orders.get("validation", []),
            ),
            "action": _baseline_match_phase(
                validation_prefixes,
                validation_orders,
                validation_action,
                baseline_account_orders.get("validation", []),
            ),
        },
    }


def _formal_touch_time_by_pair(
    formal_orders: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for order in formal_orders:
        if str(order.get("lane") or "") != "first_board":
            continue
        pair = _signal_pair(order)
        signal_time = str(order.get("buy_time") or order.get("signal_time") or "")
        if not all(pair) or not signal_time:
            continue
        current = result.get(pair)
        if current is None or signal_time < current:
            result[pair] = signal_time
    return result


def _baseline_return_quality(
    signals: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    returns = [
        value
        for signal in signals
        if (value := _number(signal.get("net_return_pct"))) is not None
    ]
    return {
        "signal_count": len(signals),
        "closed_count": len(returns),
        "win_count": sum(value > 0 for value in returns),
        "win_rate_pct": _percentage(
            sum(value > 0 for value in returns),
            len(returns),
        ),
        "average_net_return_pct": _average(returns),
        "median_net_return_pct": _median(returns),
    }


def _signal_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("vt_symbol") or ""),
        str(row.get("signal_date") or row.get("entry_date") or "")[:10],
    )


def _lead_minutes(signal_time: str, touch_time: str | None) -> float | None:
    try:
        signal = datetime.strptime(signal_time[:8], "%H:%M:%S")
        touch = datetime.strptime(str(touch_time or "")[:8], "%H:%M:%S")
    except ValueError:
        return None
    minutes = (touch - signal).total_seconds() / 60
    if signal_time[:8] < "11:30:00" and str(touch_time or "")[:8] >= "13:00:00":
        minutes -= 90
    return round(minutes, 4)


def _variant_report(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    validation_dates: set[date],
    early_signals: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    full_orders = [dict(order) for order in orders]
    validation_orders = [
        dict(order)
        for order in orders
        if _as_date(order.get("entry_date") or order.get("signal_date"), date.min)
        in validation_dates
    ]
    early_quality = {
        "full": _early_signal_quality(early_signals),
        "validation": _early_signal_quality(
            [
                signal
                for signal in early_signals
                if _as_date(signal.get("signal_date"), date.min) in validation_dates
            ]
        ),
    }
    return {
        "full": {
            "normal": _account_summary(full_orders, bars, trade_dates, cost_multiplier=1.0),
            "double_cost": _account_summary(
                full_orders,
                bars,
                trade_dates,
                cost_multiplier=2.0,
            ),
            "early_first_board_quality": early_quality["full"],
        },
        "validation": {
            "normal": _account_summary(
                validation_orders,
                bars,
                trade_dates,
                cost_multiplier=1.0,
            ),
            "double_cost": _account_summary(
                validation_orders,
                bars,
                trade_dates,
                cost_multiplier=2.0,
            ),
            "early_first_board_quality": early_quality["validation"],
        },
    }


def _baseline_account_orders_by_phase(
    formal_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
) -> dict[str, list[dict[str, object]]]:
    scopes: dict[str, set[date] | None] = {
        "full": None,
        "fit": fit_dates,
        "calibration": calibration_dates,
        "validation": validation_dates,
    }
    result: dict[str, list[dict[str, object]]] = {}
    for phase, allowed_dates in scopes.items():
        phase_orders = [
            dict(order)
            for order in formal_orders
            if allowed_dates is None
            or _as_date(order.get("entry_date"), date.min) in allowed_dates
        ]
        account = _account_replay(
            phase_orders,
            bars,
            trade_dates,
            cost_multiplier=1.0,
        )
        result[phase] = [
            dict(order)
            for order in account["orders"]
            if order.get("side") == "BUY" and order.get("status") == "filled"
        ]
    return result


def _account_summary(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    cost_multiplier: float,
) -> dict[str, object]:
    account = _account_replay(
        orders,
        bars,
        trade_dates,
        cost_multiplier=cost_multiplier,
    )
    return dict(account["execution_summary"])


def _account_replay(
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    cost_multiplier: float,
) -> dict[str, object]:
    config = cash_backtest.CashBacktestConfig(
        initial_cash=100_000,
        max_positions=scheduled_execution.MAX_POSITIONS,
        commission_rate=0.0003 * cost_multiplier,
        minimum_commission=5.0 * cost_multiplier,
        stamp_tax_rate=0.0005 * cost_multiplier,
        transfer_fee_rate=0.00001 * cost_multiplier,
        slippage_bps=10.0 * cost_multiplier,
    )
    return cash_backtest.simulate_limit_up_account(
        orders,
        bars,
        trade_dates,
        scheduled_execution.EXIT_MODE,
        config,
    )


def _early_signal_quality(
    signals: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    closed = [
        (signal, value)
        for signal in signals
        if (value := _number(signal.get("net_return_pct"))) is not None
    ]
    returns = [value for _, value in closed]
    positives = sum(value > 0 for value in returns)
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value <= 0))
    daily: dict[str, list[float]] = defaultdict(list)
    for signal, value in closed:
        daily[str(signal.get("signal_date") or "")[:10]].append(value)
    daily_returns = [mean(daily[key]) for key in sorted(daily)]
    signal_gains = [
        value
        for signal in signals
        if isinstance(signal.get("features"), Mapping)
        and (
            value := _number(_mapping(signal.get("features")).get("gain_pct"))
        )
        is not None
    ]
    return {
        "signal_count": len(signals),
        "closed_count": len(closed),
        "win_count": positives,
        "win_rate_pct": _percentage(positives, len(closed)),
        "average_net_return_pct": _average(returns),
        "median_net_return_pct": _median(returns),
        "profit_factor": round(gains / losses, 4) if losses > 0 else None,
        "daily_equal_weight_compound_return_pct": _compound(daily_returns),
        "max_drawdown_pct": _drawdown(daily_returns),
        "later_touch_count": sum(
            signal.get("touched_limit") is True for signal in signals
        ),
        "later_touch_rate_pct": _percentage(
            sum(signal.get("touched_limit") is True for signal in signals),
            len(signals),
        ),
        "final_seal_count": sum(
            signal.get("sealed_limit") is True for signal in signals
        ),
        "final_seal_rate_pct": _percentage(
            sum(signal.get("sealed_limit") is True for signal in signals),
            len(signals),
        ),
        "signal_gain_p25_pct": _quantile(signal_gains, 0.25),
        "signal_gain_median_pct": _quantile(signal_gains, 0.50),
        "signal_gain_p75_pct": _quantile(signal_gains, 0.75),
        "gain_buckets": _gain_bucket_quality(signals),
    }


def _gain_bucket_quality(
    signals: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    buckets: dict[str, list[Mapping[str, object]]] = {
        "3_to_5": [],
        "5_to_7": [],
        "7_to_9": [],
        "gte_9": [],
    }
    for signal in signals:
        gain = _number(_mapping(signal.get("features")).get("gain_pct"))
        if gain is None:
            continue
        if gain < 5:
            key = "3_to_5"
        elif gain < 7:
            key = "5_to_7"
        elif gain < 9:
            key = "7_to_9"
        else:
            key = "gte_9"
        buckets[key].append(signal)
    return {
        key: {
            "signal_count": len(rows),
            "fillable_count": sum(row.get("fillable") is True for row in rows),
            "later_touch_rate_pct": _percentage(
                sum(row.get("touched_limit") is True for row in rows),
                len(rows),
            ),
            "d1_win_rate_pct": _percentage(
                sum((_number(row.get("net_return_pct")) or 0) > 0 for row in rows),
                sum(_number(row.get("net_return_pct")) is not None for row in rows),
            ),
        }
        for key, rows in buckets.items()
    }


def _model_report(
    model: IgnitionFit,
    threshold: IgnitionThreshold,
) -> dict[str, object]:
    return {
        "status": model.status,
        "training_row_count": model.training_row_count,
        "class_counts": model.class_counts,
        "fit_dates": list(model.fit_dates),
        "features": list(IGNITION_FEATURE_NAMES),
        "feature_semantics": "5m_price_volume_amount_proxy_after_shared_strategy_filters",
        "coefficient_by_feature": model.coefficient_by_feature,
        "intercept": model.intercept,
        "threshold_selection": {
            "status": threshold.status,
            "threshold": threshold.threshold,
            "minimum_signal_count": threshold.minimum_signal_count,
            "calibration_dates": list(threshold.calibration_dates),
            "selected_metrics": threshold.selected_metrics,
            "metrics_by_threshold": list(threshold.metrics_by_threshold),
        },
    }


def _baseline_model_report(
    model: BaselineModelFit,
    thresholds: BaselineThresholdSelection,
) -> dict[str, object]:
    return {
        "status": model.status,
        "target_field": model.target_field,
        "training_row_count": model.training_row_count,
        "training_pair_count": model.training_pair_count,
        "class_counts": model.class_counts,
        "fit_dates": list(model.fit_dates),
        "features": list(BASELINE_FEATURE_NAMES),
        "feature_semantics": "completed_5m_prefix_and_point_in_time_shared_strategy",
        "coefficient_by_feature": model.coefficient_by_feature,
        "intercept": model.intercept,
        "threshold_selection": {
            "status": thresholds.status,
            "prepare_threshold": thresholds.prepare_threshold,
            "action_threshold": thresholds.action_threshold,
            "minimum_signal_count": thresholds.minimum_signal_count,
            "calibration_dates": list(thresholds.calibration_dates),
            "prepare_metrics": thresholds.prepare_metrics,
            "action_metrics": thresholds.action_metrics,
            "metrics_by_threshold": list(thresholds.metrics_by_threshold),
        },
    }


def _baseline_precursor_decision(
    variants: Mapping[str, Mapping[str, object]],
    match: Mapping[str, object],
    prepare_thresholds: BaselineThresholdSelection,
    action_thresholds: BaselineThresholdSelection,
    parity: Mapping[str, object],
) -> dict[str, object]:
    validation_action = _mapping(
        _mapping(match.get("validation")).get("action")
    )
    baseline_account = _mapping(
        _mapping(_mapping(variants.get("formal_touch_current")).get("validation")).get(
            "normal"
        )
    )
    precursor_phase = _mapping(
        _mapping(variants.get("baseline_precursor_action")).get("validation")
    )
    precursor_account = _mapping(precursor_phase.get("normal"))
    precursor_stress = _mapping(precursor_phase.get("double_cost"))
    checks = {
        "baseline_parity": parity.get("passed") is True,
        "thresholds_ready": (
            prepare_thresholds.status == "ready"
            and action_thresholds.status == "ready"
        ),
        "minimum_action_signals": (
            (_number(validation_action.get("signal_count")) or 0) >= 10
        ),
        "baseline_account_precision": (
            (_number(validation_action.get("baseline_account_precision_pct")) or 0)
            >= 80.0
        ),
        "reachable_baseline_account_recall": (
            (
                _number(
                    validation_action.get(
                        "reachable_baseline_account_recall_pct"
                    )
                )
                or 0
            )
            >= 30.0
        ),
        "positive_account_return": (
            (_number(precursor_account.get("total_return_pct")) or -1e9) > 0
        ),
        "win_rate_near_touch_baseline": (
            (_number(precursor_account.get("win_rate")) or 0)
            >= (_number(baseline_account.get("win_rate")) or 0) - 2.0
        ),
        "drawdown_within_limit": (
            (_number(precursor_account.get("max_drawdown_pct")) or -1e9) >= -10.0
        ),
        "positive_double_cost_return": (
            (_number(precursor_stress.get("total_return_pct")) or -1e9) > 0
        ),
    }
    passed = all(checks.values())
    return {
        "decision": (
            "baseline_precursor_historical_pass_requires_forward_validation"
            if passed
            else "no_reliable_baseline_precursor"
        ),
        "passed": passed,
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if value is not True],
        "frozen_gates": {
            "minimum_validation_action_signals": 10,
            "minimum_baseline_account_precision_pct": 80.0,
            "minimum_reachable_baseline_account_recall_pct": 30.0,
            "maximum_win_rate_gap_pct_points": 2.0,
            "minimum_max_drawdown_pct": -10.0,
            "positive_normal_and_double_cost_return": True,
        },
    }


def _optimization_decision(
    variants: Mapping[str, Mapping[str, object]],
    threshold: IgnitionThreshold,
    parity: Mapping[str, object],
) -> str:
    if parity.get("passed") is not True:
        return "no_optimization_result"
    if threshold.threshold is None:
        return "current_support_only_no_reliable_model"
    baseline = _mapping(
        _mapping(_mapping(variants.get("formal_touch_current")).get("validation")).get(
            "normal"
        )
    )
    ignition_phase = _mapping(
        _mapping(variants.get("post_filter_ignition")).get("validation")
    )
    ignition = _mapping(ignition_phase.get("normal"))
    stress = _mapping(ignition_phase.get("double_cost"))
    checks = (
        (_number(ignition.get("trade_count")) or 0) >= 30,
        (_number(ignition.get("win_rate")) or 0)
        >= (_number(baseline.get("win_rate")) or 0) - 2.0,
        (_number(ignition.get("total_return_pct")) or -1e9)
        > (_number(baseline.get("total_return_pct")) or -1e9),
        (_number(ignition.get("max_drawdown_pct")) or -1e9) >= -10.0,
        (_number(stress.get("total_return_pct")) or -1e9) > 0,
    )
    return (
        "historical_optimization_passed_requires_forward_validation"
        if all(checks)
        else "no_reliable_historical_optimization"
    )


def _simultaneous_signal_report(
    orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for order in orders:
        grouped[
            (
                str(order.get("entry_date") or order.get("signal_date") or "")[:10],
                str(order.get("buy_time") or order.get("signal_time") or ""),
            )
        ].append(order)
    collisions = [
        (key, rows)
        for key, rows in sorted(grouped.items())
        if len(rows) > scheduled_execution.MAX_POSITIONS
    ]
    return {
        "same_timestamp_group_count": sum(len(rows) > 1 for rows in grouped.values()),
        "oversubscribed_group_count": len(collisions),
        "max_candidates_same_timestamp": max(
            (len(rows) for rows in grouped.values()),
            default=0,
        ),
        "examples": [
            {
                "entry_date": key[0],
                "buy_time": key[1],
                "candidate_count": len(rows),
                "ordered_symbols": [
                    str(row.get("vt_symbol") or "")
                    for row in sorted(
                        rows,
                        key=lambda row: (
                            -(_number(row.get("rank_score")) or 0.0),
                            str(row.get("vt_symbol") or ""),
                        ),
                    )
                ],
            }
            for key, rows in collisions[:20]
        ],
    }


def _date_split(
    dates: Sequence[date],
) -> tuple[tuple[date, ...], tuple[date, ...], tuple[date, ...]]:
    ordered = tuple(sorted(set(dates)))
    fit_end = min(FIT_SESSION_COUNT, len(ordered))
    calibration_end = min(fit_end + CALIBRATION_SESSION_COUNT, len(ordered))
    return (
        ordered[:fit_end],
        ordered[fit_end:calibration_end],
        ordered[calibration_end:],
    )


def _coverage_report(
    manifest: pd.DataFrame,
    coverage: pd.DataFrame,
) -> dict[str, object]:
    complete = int(coverage["coverage_status"].eq("complete").sum())
    return {
        "manifest_pair_count": int(len(manifest)),
        "manifest_symbol_count": int(manifest["vt_symbol"].nunique()),
        "manifest_trade_day_count": int(manifest["trade_date"].nunique()),
        "complete_pair_count": complete,
        "complete_pair_pct": round(complete / len(manifest) * 100, 4)
        if len(manifest)
        else 0.0,
        "coverage_status_counts": {
            str(key): int(value)
            for key, value in coverage["coverage_status"].value_counts().items()
        },
    }


def _blocked_report(status: str, *, session_count: int) -> dict[str, object]:
    return {
        "study_version": STUDY_VERSION,
        "status": status,
        "decision": "no_optimization_result",
        "scope": {"requested_session_count": int(session_count)},
        "formal_strategy_changed": False,
    }


def _signal_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("signal_date") or "")[:10],
        str(row.get("entry_time") or row.get("signal_time") or ""),
        str(row.get("vt_symbol") or ""),
    )


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_date(value: object, default: date) -> date:
    parsed = _optional_date(value)
    return parsed if parsed is not None else default


def _optional_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _average(values: Sequence[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _median(values: Sequence[float]) -> float | None:
    return round(median(values), 4) if values else None


def _quantile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    return round(float(pd.Series(values, dtype=float).quantile(quantile)), 4)


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator > 0 else None


def _compound(values: Sequence[float]) -> float | None:
    return round((prod(1 + value / 100 for value in values) - 1) * 100, 4) if values else None


def _drawdown(values: Sequence[float]) -> float | None:
    if not values:
        return None
    equity = 1.0
    peak = 1.0
    result = 0.0
    for value in values:
        equity *= 1 + value / 100
        peak = max(peak, equity)
        result = min(result, (equity / peak - 1) * 100)
    return round(result, 4)


def _display(value: object) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.4f}"


def _signed(value: object) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:+.4f}"


def _write_output(path_text: str, content: str) -> None:
    path = Path(path_text)
    resolved = path.resolve()
    report_root = REPORT_DIRECTORY.resolve()
    if report_root not in resolved.parents:
        raise ValueError("output must be under memory/06_backtests")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--sessions", type=int, default=DEFAULT_SESSION_COUNT)
    evaluate.add_argument("--format", choices=("json", "markdown"), default="json")
    evaluate.add_argument("--output")
    args = parser.parse_args()
    if args.command != "evaluate":
        raise ValueError(f"unsupported command: {args.command}")
    report = evaluate_current_strategy_preboard(session_count=args.sessions)
    content = (
        render_current_strategy_preboard_markdown(report)
        if args.format == "markdown"
        else json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    if args.output:
        _write_output(args.output, content)
    else:
        print(content)


if __name__ == "__main__":
    main()
