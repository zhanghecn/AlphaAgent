"""Independent study of predicting a later limit touch from a 3% prefix."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from math import isfinite

import numpy as np
import pandas as pd

from alphaagent.server.services.limit_up.preboard_momentum import build_prefix_rows
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    attach_preboard_prior_evidence,
    build_five_minute_coverage,
    load_preboard_daily_bars,
    load_preboard_manifest,
    load_preboard_minute_bars,
    load_reliable_trade_dates,
)
from alphaagent.server.services.limit_up.preboard_momentum_study import (
    _account_report,
    _recommendation_metrics,
)
from alphaagent.server.services.limit_up.preboard_touch_model import (
    MINIMUM_CALIBRATION_SIGNALS,
    MODEL_VARIANTS,
    PRIMARY_VARIANT,
    TouchModelFit,
    TouchThresholdSelection,
    attach_later_touch_targets,
    calibrate_touch_threshold,
    first_touch_signal,
    fit_touch_arrays,
    touch_candidate_outcome,
    touch_training_batch,
)


STUDY_VERSION = "limit-up-preboard-touch-study-v1"
VALIDATION_KIND = "viewed_historical_time_validation"


def chronological_touch_split(
    values: Iterable[date | datetime | str],
    *,
    fit_session_count: int = 30,
    calibration_session_count: int = 10,
) -> tuple[tuple[date, ...], tuple[date, ...], tuple[date, ...]]:
    """Split unique dates into fit, calibration and historical validation."""

    dates = sorted(
        {parsed for value in values if (parsed := _as_date(value)) is not None}
    )
    fit_end = min(max(int(fit_session_count), 0), len(dates))
    calibration_end = min(
        fit_end + max(int(calibration_session_count), 0),
        len(dates),
    )
    return (
        tuple(dates[:fit_end]),
        tuple(dates[fit_end:calibration_end]),
        tuple(dates[calibration_end:]),
    )


def build_preboard_touch_report(
    manifest: pd.DataFrame,
    minute_rows: pd.DataFrame,
    daily_rows: pd.DataFrame,
    *,
    trade_dates: Sequence[date | str],
    fit_session_count: int = 30,
    calibration_session_count: int = 10,
    minimum_calibration_signals: int = MINIMUM_CALIBRATION_SIGNALS,
    model_variants: Sequence[str] = MODEL_VARIANTS,
    primary_variant: str = PRIMARY_VARIANT,
    diagnostic_only: bool = False,
) -> dict[str, object]:
    """Fit frozen touch variants and replay their first causal recommendations."""

    variant_order = tuple(dict.fromkeys(model_variants))
    invalid_variants = sorted(set(variant_order) - set(MODEL_VARIANTS))
    if invalid_variants:
        raise ValueError(f"unsupported variants: {', '.join(invalid_variants)}")
    if not variant_order or primary_variant not in variant_order:
        raise ValueError("primary_variant must belong to model_variants")

    prepared_manifest = _prepare_manifest(manifest)
    coverage = build_five_minute_coverage(prepared_manifest, minute_rows)
    complete_pairs = _complete_pairs(coverage)
    minute_frame = _prepare_minute_frame(minute_rows)
    manifest_by_pair = _manifest_index(prepared_manifest)
    fit_dates, calibration_dates, validation_dates = chronological_touch_split(
        prepared_manifest["trade_date"].tolist(),
        fit_session_count=fit_session_count,
        calibration_session_count=calibration_session_count,
    )

    training_variants = tuple(
        dict.fromkeys(_training_source_variant(variant) for variant in variant_order)
    )
    training_batches: dict[str, list[np.ndarray]] = {
        variant: [] for variant in training_variants
    }
    target_batches: dict[str, list[np.ndarray]] = {
        variant: [] for variant in training_variants
    }
    for _, rows in _iter_prefix_groups(
        minute_frame,
        manifest_by_pair,
        complete_pairs,
        allowed_dates=set(fit_dates),
    ):
        for variant in training_variants:
            matrix, targets = touch_training_batch(rows, variant)
            if len(matrix):
                training_batches[variant].append(matrix)
                target_batches[variant].append(targets)

    training_arrays = {
        variant: (
            np.vstack(training_batches[variant])
            if training_batches[variant]
            else np.empty((0, _feature_count(variant)), dtype=float),
            np.concatenate(target_batches[variant])
            if target_batches[variant]
            else np.empty(0, dtype=int),
        )
        for variant in training_variants
    }
    models: dict[str, TouchModelFit] = {}
    for variant in variant_order:
        source_variant = _training_source_variant(variant)
        matrix, targets = training_arrays[source_variant]
        models[variant] = fit_touch_arrays(
            matrix,
            targets,
            variant=variant,
            fit_dates=set(fit_dates),
        )

    thresholds: dict[str, TouchThresholdSelection] = {}
    for variant in variant_order:
        thresholds[variant] = calibrate_touch_threshold(
            (
                rows
                for _, rows in _iter_prefix_groups(
                    minute_frame,
                    manifest_by_pair,
                    complete_pairs,
                    allowed_dates=set(calibration_dates),
                )
            ),
            models[variant],
            calibration_dates=set(calibration_dates),
            minimum_signal_count=minimum_calibration_signals,
        )

    signals_by_variant: dict[str, list[dict[str, object]]] = {
        variant: [] for variant in variant_order
    }
    outcomes_by_variant: dict[
        str, dict[tuple[str, date], dict[str, bool]]
    ] = {variant: {} for variant in variant_order}
    for pair, rows in _iter_prefix_groups(
        minute_frame,
        manifest_by_pair,
        complete_pairs,
    ):
        for variant in variant_order:
            outcomes_by_variant[variant][pair] = touch_candidate_outcome(rows, variant)
            threshold = thresholds[variant].threshold
            if threshold is None:
                continue
            signal = first_touch_signal(rows, models[variant], threshold=threshold)
            if signal is not None:
                signals_by_variant[variant].append(signal)

    manifest_touch_by_pair = {
        pair: bool(row.get("touched_limit"))
        for pair, row in manifest_by_pair.items()
        if pair in complete_pairs
    }
    date_scopes = {
        "full": set((*fit_dates, *calibration_dates, *validation_dates)),
        "fit": set(fit_dates),
        "calibration": set(calibration_dates),
        "validation": set(validation_dates),
    }
    variants: dict[str, dict[str, object]] = {}
    for variant in variant_order:
        model = models[variant]
        threshold = thresholds[variant]
        signals = sorted(signals_by_variant[variant], key=_signal_sort_key)
        result: dict[str, object] = {
            "model": _model_report(model, threshold),
        }
        for phase, phase_dates in date_scopes.items():
            result[phase] = _phase_report(
                signals,
                phase_dates,
                outcomes_by_variant[variant],
                manifest_touch_by_pair,
                daily_rows,
                trade_dates,
            )
        result["touch_acceptance"] = _touch_acceptance(
            _mapping(result["validation"])
        )
        result["trade_acceptance"] = _trade_acceptance(
            _mapping(result["validation"])
        )
        variants[variant] = result

    complete_count = len(complete_pairs)
    coverage_pct = (
        round(complete_count / len(coverage) * 100, 4) if len(coverage) else 0.0
    )
    primary = _mapping(variants.get(primary_variant))
    primary_touch = _mapping(primary.get("touch_acceptance"))
    primary_trade = _mapping(primary.get("trade_acceptance"))
    decision = (
        "diagnostic_only_not_formal_decision"
        if diagnostic_only
        else _decision(primary_touch, primary_trade, coverage_pct)
    )
    return {
        "study_version": STUDY_VERSION,
        "status": "ready" if coverage_pct >= 95.0 else "blocked_by_minute_coverage",
        "validation_kind": VALIDATION_KIND,
        "selection_scope": (
            "single_variant_diagnostic_replay"
            if diagnostic_only
            else "pre_registered_all_variants"
        ),
        "contract": {
            "capture_gain_pct": 3.0,
            "capture_gain_operator": ">=",
            "target": "later_d_day_exact_limit_touch",
            "decision_bars": "completed_5m_prefix_only",
            "recommendation_uses_next_open": False,
            "execution": "next_5m_open_if_below_exact_limit",
            "exit": "d1_official_close",
            "entry_windows": ["10:00-11:30", "13:00-14:30"],
            "max_positions": 2,
            "formal_strategy_changed": False,
        },
        "manifest": _manifest_report(prepared_manifest),
        "coverage": {
            "complete_pair_count": complete_count,
            "required_pair_count": int(len(coverage)),
            "coverage_pct": coverage_pct,
            "status_counts": {
                str(key): int(value)
                for key, value in coverage["coverage_status"]
                .value_counts()
                .sort_index()
                .items()
            },
        },
        "split": {
            "fit_dates": [_date_text(value) for value in fit_dates],
            "calibration_dates": [_date_text(value) for value in calibration_dates],
            "validation_dates": [_date_text(value) for value in validation_dates],
            "fit_session_count": len(fit_dates),
            "calibration_session_count": len(calibration_dates),
            "validation_session_count": len(validation_dates),
        },
        "variants": variants,
        "variant_order": list(variant_order),
        "primary_variant": primary_variant,
        "decision": decision,
        "limitations": [
            "日线最高价只用于枚举所有盘中曾达到3%的股票日，不进入特征或信号选择。",
            "推荐只读取当前已完成5分钟K线；下一根开盘只在推荐冻结后判断是否可成交。",
            "标签只表示D日稍后首次触及精确涨停价，不等于最终封板，也不等于D+1盈利。",
            "5分钟最高价无法还原K线内部秒级触板顺序、盘口卖单或真实委托成交。",
            "当前名称过滤不能证明更早日期的ST名称状态完全无漂移。",
            "最后20日已经被其他研究查看，只能称历史时间验证，不是新的锁定留出。",
            "任何历史通过只允许新增前向影子，不自动替换v9、v15或正式5%雷达。",
        ],
    }


def render_preboard_touch_markdown(report: Mapping[str, object]) -> str:
    """Render the touch-prediction result as a compact durable report."""

    manifest = _mapping(report.get("manifest"))
    coverage = _mapping(report.get("coverage"))
    variants = _mapping(report.get("variants"))
    variant_order = tuple(report.get("variant_order") or MODEL_VARIANTS)
    primary_variant = str(report.get("primary_variant") or PRIMARY_VARIANT)
    lines = [
        "# 首板 3% 以上后续触板预测研究",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status')}`；结论：`{report.get('decision')}`。",
        f"- 验证性质：`{report.get('validation_kind')}`；正式策略未修改。",
        f"- 选择范围：`{report.get('selection_scope')}`。",
        f"- 清单：{manifest.get('pair_count', 0)} 个股票日、{manifest.get('symbol_count', 0)} 只股票、"
        f"{manifest.get('trade_day_count', 0)} 个交易日；全清单触板率 "
        f"{_pct(manifest.get('touch_rate_pct'))}。",
        f"- 5分钟覆盖：{coverage.get('complete_pair_count', 0)}/{coverage.get('required_pair_count', 0)} "
        f"（{_display(coverage.get('coverage_pct'))}%）。",
        "- 推荐只使用当前已完成5分钟K线；下一根开盘不参与推荐，只在推荐冻结后判断可成交。",
        "",
        "## 历史时间验证",
        "",
        "| 变体 | 阈值 | 推荐 | 触板精确率 | 可成交率 | 可成交触板率 | 合格召回 | 最终封板 | D+1胜率 | D+1均值 | 两仓复利 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant in variant_order:
        result = _mapping(variants.get(variant))
        model = _mapping(result.get("model"))
        validation = _mapping(result.get("validation"))
        prediction = _mapping(validation.get("prediction"))
        recommendations = _mapping(validation.get("fillable_recommendations"))
        account = _mapping(validation.get("two_position_account"))
        account_summary = _mapping(account.get("execution_summary"))
        lines.append(
            f"| `{variant}` | {_display(model.get('threshold'))} | "
            f"{prediction.get('signal_count', 0)} | {_pct(prediction.get('touch_precision_pct'))} | "
            f"{_pct(prediction.get('next_open_fill_rate_pct'))} | "
            f"{_pct(prediction.get('fillable_touch_precision_pct'))} | "
            f"{_pct(prediction.get('eligible_recall_pct'))} | "
            f"{_pct(prediction.get('final_seal_rate_pct'))} | "
            f"{_pct(recommendations.get('win_rate_pct'))} | "
            f"{_signed_pct(recommendations.get('average_net_return_pct'))} | "
            f"{_signed_pct(account_summary.get('total_return_pct'))} |"
        )

    lines.extend(
        [
            "",
            "## 消融诊断",
            "",
            "| 变体 | 合格母池触板率 | 精确率提升 | 信号涨幅P25/中位/P75 | 触板等待中位 | 全触板召回 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for variant in variant_order:
        validation = _mapping(_mapping(variants.get(variant)).get("validation"))
        prediction = _mapping(validation.get("prediction"))
        gain = _mapping(prediction.get("gain_distribution_pct"))
        latency = _mapping(prediction.get("touch_latency_trading_minutes"))
        lines.append(
            f"| `{variant}` | {_pct(prediction.get('eligible_baseline_touch_rate_pct'))} | "
            f"{_display(prediction.get('precision_uplift_multiple'))}x | "
            f"{_pct(gain.get('p25'))} / {_pct(gain.get('median'))} / {_pct(gain.get('p75'))} | "
            f"{_display(latency.get('median'))}分钟 | "
            f"{_pct(prediction.get('manifest_touch_recall_pct'))} |"
        )

    best_variant = _descriptive_best_variant(variants, variant_order)
    best_result = _mapping(variants.get(best_variant))
    best_model = _mapping(best_result.get("model"))
    best_validation = _mapping(best_result.get("validation"))
    best_prediction = _mapping(best_validation.get("prediction"))
    best_calibration = _mapping(best_model.get("selected_threshold_metrics"))
    lines.extend(
        [
            "",
            f"- 验证段描述性最高精确率：`{best_variant}`；该选择只作归因，不能在已查看验证段后替换预注册主模型。",
            f"- 该变体校准段精确率 {_pct(best_calibration.get('precision_pct'))}、"
            f"验证段精确率 {_pct(best_prediction.get('touch_precision_pct'))}。",
            "",
            "### 描述性最佳变体按信号涨幅",
            "",
            "| 信号涨幅 | 推荐 | 后续触板率 | D+1闭合 | D+1胜率 | D+1平均净收益 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    best_gain_outcomes = _mapping(best_prediction.get("touch_by_gain_bucket"))
    best_gain_returns = _mapping(
        best_validation.get("fillable_recommendations_by_gain_bucket")
    )
    for bucket in ("3_to_5", "5_to_7", "7_to_9", "9_plus"):
        touch = _mapping(best_gain_outcomes.get(bucket))
        returns = _mapping(best_gain_returns.get(bucket))
        lines.append(
            f"| `{bucket}` | {touch.get('signal_count', 0)} | "
            f"{_pct(touch.get('touch_precision_pct'))} | "
            f"{returns.get('closed_count', 0)} | {_pct(returns.get('win_rate_pct'))} | "
            f"{_signed_pct(returns.get('average_net_return_pct'))} |"
        )

    primary_result = _mapping(variants.get(primary_variant))
    primary_validation = _mapping(primary_result.get("validation"))
    primary_prediction = _mapping(primary_validation.get("prediction"))
    primary_recommendations = _mapping(
        primary_validation.get("fillable_recommendations")
    )
    primary_account = _mapping(
        _mapping(primary_validation.get("two_position_account")).get(
            "execution_summary"
        )
    )
    lines.extend(
        [
            "",
            "## 主模型",
            "",
            f"- {'诊断变体' if report.get('selection_scope') == 'single_variant_diagnostic_replay' else '主模型'}："
            f"`{primary_variant}`；推荐 {primary_prediction.get('signal_count', 0)} 个，"
            f"后续触板 {primary_prediction.get('true_positive_count', 0)} 个，精确率 "
            f"{_pct(primary_prediction.get('touch_precision_pct'))}，合格召回率 "
            f"{_pct(primary_prediction.get('eligible_recall_pct'))}。",
            f"- 下一根开盘可成交 {primary_prediction.get('fillable_signal_count', 0)} 个，成交率 "
            f"{_pct(primary_prediction.get('next_open_fill_rate_pct'))}，可成交信号触板率 "
            f"{_pct(primary_prediction.get('fillable_touch_precision_pct'))}。",
            f"- 信号涨幅：中位 {_pct(_mapping(primary_prediction.get('gain_distribution_pct')).get('median'))}；"
            f"触板等待：中位 {_display(_mapping(primary_prediction.get('touch_latency_trading_minutes')).get('median'))} 个交易分钟。",
            f"- 可成交D+1：{primary_recommendations.get('closed_count', 0)} 笔，胜率 "
            f"{_pct(primary_recommendations.get('win_rate_pct'))}，平均净收益 "
            f"{_signed_pct(primary_recommendations.get('average_net_return_pct'))}。",
            f"- 两仓：{primary_account.get('trade_count', 0)} 笔，复利 "
            f"{_signed_pct(primary_account.get('total_return_pct'))}，回撤 "
            f"{_signed_pct(primary_account.get('max_drawdown_pct'))}，PF "
            f"{_display(primary_account.get('profit_factor'))}。",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("limitations") or [])
    return "\n".join(lines) + "\n"


def _iter_prefix_groups(
    minute_frame: pd.DataFrame,
    manifest_by_pair: Mapping[tuple[str, date], Mapping[str, object]],
    complete_pairs: set[tuple[str, date]],
    *,
    allowed_dates: set[date] | None = None,
) -> Iterable[tuple[tuple[str, date], list[dict[str, object]]]]:
    for (symbol, trade_date), group in minute_frame.groupby(
        ["vt_symbol", "trade_date"], sort=False
    ):
        pair = (str(symbol), trade_date)
        manifest_row = manifest_by_pair.get(pair)
        if (
            pair not in complete_pairs
            or manifest_row is None
            or (allowed_dates is not None and trade_date not in allowed_dates)
        ):
            continue
        bars = group.to_dict(orient="records")
        prefixes = build_prefix_rows(manifest_row, bars)
        yield pair, attach_later_touch_targets(prefixes, bars)


def _phase_report(
    signals: Sequence[Mapping[str, object]],
    phase_dates: set[date],
    outcomes: Mapping[tuple[str, date], Mapping[str, bool]],
    manifest_touches: Mapping[tuple[str, date], bool],
    daily_rows: pd.DataFrame,
    trade_dates: Sequence[date | str],
) -> dict[str, object]:
    selected = [
        dict(signal)
        for signal in signals
        if _as_date(signal.get("signal_date")) in phase_dates
    ]
    fillable = [signal for signal in selected if signal.get("fillable") is True]
    return {
        "prediction": _prediction_metrics(
            selected,
            phase_dates,
            outcomes,
            manifest_touches,
        ),
        "fillable_recommendations": _recommendation_metrics(fillable),
        "fillable_recommendations_by_gain_bucket": {
            bucket: _recommendation_metrics(
                [
                    signal
                    for signal in fillable
                    if _gain_bucket(_feature_number(signal, "gain_pct")) == bucket
                ]
            )
            for bucket in ("3_to_5", "5_to_7", "7_to_9", "9_plus")
        },
        "two_position_account": _account_report(
            fillable,
            daily_rows,
            trade_dates,
            cost_multiplier=1.0,
        ),
        "double_cost_account": _account_report(
            fillable,
            daily_rows,
            trade_dates,
            cost_multiplier=2.0,
        ),
    }


def _prediction_metrics(
    signals: Sequence[Mapping[str, object]],
    phase_dates: set[date],
    outcomes: Mapping[tuple[str, date], Mapping[str, bool]],
    manifest_touches: Mapping[tuple[str, date], bool],
) -> dict[str, object]:
    true_positives = [signal for signal in signals if signal.get("later_touch") is True]
    fillable = [signal for signal in signals if signal.get("fillable") is True]
    fillable_true_positives = [
        signal for signal in fillable if signal.get("later_touch") is True
    ]
    scoped_outcomes = [
        outcome
        for (_, signal_date), outcome in outcomes.items()
        if signal_date in phase_dates and outcome.get("eligible") is True
    ]
    eligible_positive_count = sum(
        outcome.get("touched") is True for outcome in scoped_outcomes
    )
    manifest_touch_count = sum(
        touched
        for (_, signal_date), touched in manifest_touches.items()
        if signal_date in phase_dates
    )
    gains = [
        value
        for signal in signals
        if (value := _feature_number(signal, "gain_pct")) is not None
    ]
    latencies = [
        value
        for signal in true_positives
        if (value := _number(signal.get("trading_minutes_to_touch"))) is not None
    ]
    seal_count = sum(signal.get("sealed_limit") is True for signal in signals)
    baseline = _ratio_pct(eligible_positive_count, len(scoped_outcomes))
    precision = _ratio_pct(len(true_positives), len(signals))
    return {
        "signal_count": len(signals),
        "true_positive_count": len(true_positives),
        "false_positive_count": len(signals) - len(true_positives),
        "touch_precision_pct": precision,
        "eligible_pair_count": len(scoped_outcomes),
        "eligible_positive_count": eligible_positive_count,
        "eligible_baseline_touch_rate_pct": baseline,
        "eligible_recall_pct": _ratio_pct(
            len(true_positives), eligible_positive_count
        ),
        "manifest_touch_count": manifest_touch_count,
        "manifest_touch_recall_pct": _ratio_pct(
            len(true_positives), manifest_touch_count
        ),
        "precision_uplift_multiple": _ratio(
            precision,
            baseline,
        ),
        "fillable_signal_count": len(fillable),
        "next_open_fill_rate_pct": _ratio_pct(len(fillable), len(signals)),
        "fillable_true_positive_count": len(fillable_true_positives),
        "fillable_touch_precision_pct": _ratio_pct(
            len(fillable_true_positives), len(fillable)
        ),
        "final_seal_count": seal_count,
        "final_seal_rate_pct": _ratio_pct(seal_count, len(signals)),
        "gain_distribution_pct": _distribution(gains, include_buckets=True),
        "touch_by_gain_bucket": _touch_by_gain_bucket(signals),
        "touch_latency_trading_minutes": _latency_distribution(latencies),
    }


def _model_report(
    model: TouchModelFit,
    threshold: TouchThresholdSelection,
) -> dict[str, object]:
    return {
        "status": model.status,
        "variant": model.variant,
        "estimator_kind": model.estimator_kind,
        "training_row_count": model.training_row_count,
        "class_counts": model.class_counts,
        "fit_dates": list(model.fit_dates),
        "feature_names": list(model.feature_names),
        "importance_by_feature": model.importance_by_feature,
        "intercept": model.intercept,
        "training_fingerprint": model.training_fingerprint,
        "threshold_status": threshold.status,
        "threshold": threshold.threshold,
        "minimum_calibration_signals": threshold.minimum_signal_count,
        "calibration_dates": list(threshold.calibration_dates),
        "selected_threshold_metrics": threshold.selected_metrics,
        "metrics_by_threshold": list(threshold.metrics_by_threshold),
    }


def _touch_acceptance(validation: Mapping[str, object]) -> dict[str, object]:
    prediction = _mapping(validation.get("prediction"))
    gates = {
        "raw_signals": _at_least(prediction.get("signal_count"), 30),
        "fillable_signals": _at_least(prediction.get("fillable_signal_count"), 30),
        "raw_precision": _above(prediction.get("touch_precision_pct"), 60.0),
        "fillable_precision": _above(
            prediction.get("fillable_touch_precision_pct"), 60.0
        ),
        "eligible_recall": _at_least(
            prediction.get("eligible_recall_pct"), 10.0
        ),
        "baseline_uplift": _at_least(
            prediction.get("precision_uplift_multiple"), 1.5
        ),
    }
    return {"passed": all(gates.values()), "gates": gates}


def _trade_acceptance(validation: Mapping[str, object]) -> dict[str, object]:
    account = _mapping(
        _mapping(validation.get("two_position_account")).get("execution_summary")
    )
    stress = _mapping(
        _mapping(validation.get("double_cost_account")).get("execution_summary")
    )
    gates = {
        "trades": _at_least(account.get("trade_count"), 30),
        "win_rate": _above(account.get("win_rate"), 60.0),
        "compound_return": _above(account.get("total_return_pct"), 0.0),
        "profit_factor": _at_least(account.get("profit_factor"), 1.5),
        "max_drawdown": _at_least(account.get("max_drawdown_pct"), -10.0),
        "double_cost_profit_factor": _at_least(stress.get("profit_factor"), 1.2),
    }
    return {"passed": all(gates.values()), "gates": gates}


def _decision(
    touch_acceptance: Mapping[str, object],
    trade_acceptance: Mapping[str, object],
    coverage_pct: float,
) -> str:
    if coverage_pct < 95.0:
        return "coverage_incomplete_no_decision"
    if touch_acceptance.get("passed") is not True:
        return "no_reliable_touch_buy_point"
    if trade_acceptance.get("passed") is not True:
        return "touch_prediction_signal_only_d1_edge_failed"
    return "historical_candidate_requires_new_forward_shadow"


def _manifest_report(manifest: pd.DataFrame) -> dict[str, object]:
    touch_count = int(
        manifest.get("touched_limit", pd.Series(dtype=bool)).fillna(False).sum()
    )
    return {
        "pair_count": int(len(manifest)),
        "symbol_count": int(manifest["vt_symbol"].nunique()) if len(manifest) else 0,
        "trade_day_count": int(manifest["trade_date"].nunique()) if len(manifest) else 0,
        "date_start": _date_text(manifest["trade_date"].min()) if len(manifest) else None,
        "date_end": _date_text(manifest["trade_date"].max()) if len(manifest) else None,
        "touch_count": touch_count,
        "touch_rate_pct": _ratio_pct(touch_count, len(manifest)),
        "seal_count": int(
            manifest.get("sealed_limit", pd.Series(dtype=bool)).fillna(False).sum()
        ),
    }


def _prepare_manifest(manifest: pd.DataFrame) -> pd.DataFrame:
    required = {"vt_symbol", "trade_date", "previous_close", "limit_price"}
    missing = sorted(required - set(manifest.columns))
    if missing:
        raise ValueError(f"missing manifest columns: {', '.join(missing)}")
    frame = manifest.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    return frame.sort_values(["trade_date", "vt_symbol"], kind="stable").reset_index(
        drop=True
    )


def _prepare_minute_frame(minute_rows: pd.DataFrame) -> pd.DataFrame:
    if minute_rows.empty:
        return minute_rows.copy()
    frame = minute_rows.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.date
    frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="raise")
    return frame.sort_values(
        ["trade_date", "vt_symbol", "bar_time"], kind="stable"
    ).reset_index(drop=True)


def _manifest_index(
    manifest: pd.DataFrame,
) -> dict[tuple[str, date], dict[str, object]]:
    return {
        (str(row["vt_symbol"]), parsed): dict(row)
        for row in manifest.to_dict(orient="records")
        if (parsed := _as_date(row.get("trade_date"))) is not None
    }


def _complete_pairs(coverage: pd.DataFrame) -> set[tuple[str, date]]:
    return {
        (str(row.vt_symbol), parsed)
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
        if (parsed := _as_date(row.trade_date)) is not None
    }


def _training_source_variant(variant: str) -> str:
    return (
        f"{variant.removesuffix('_lightgbm')}_logistic"
        if variant.endswith("_lightgbm")
        else variant
    )


def _feature_count(variant: str) -> int:
    from alphaagent.server.services.limit_up.preboard_momentum import (
        FEATURE_NAMES,
        HISTORY_FEATURE_NAMES,
    )

    return (
        len((*FEATURE_NAMES, *HISTORY_FEATURE_NAMES))
        if variant.startswith("history_gate_full_")
        else len(FEATURE_NAMES)
    )


def _distribution(
    values: Sequence[float],
    *,
    include_buckets: bool,
) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "minimum": None,
            "p25": None,
            "median": None,
            "p75": None,
            "maximum": None,
            "buckets": {},
        }
    array = np.asarray(values, dtype=float)
    result: dict[str, object] = {
        "count": len(values),
        "minimum": round(float(np.min(array)), 4),
        "p25": round(float(np.percentile(array, 25)), 4),
        "median": round(float(np.median(array)), 4),
        "p75": round(float(np.percentile(array, 75)), 4),
        "maximum": round(float(np.max(array)), 4),
    }
    result["buckets"] = (
        {
            "3_to_5": int(np.sum((array >= 3.0) & (array < 5.0))),
            "5_to_7": int(np.sum((array >= 5.0) & (array < 7.0))),
            "7_to_9": int(np.sum((array >= 7.0) & (array < 9.0))),
            "9_plus": int(np.sum(array >= 9.0)),
        }
        if include_buckets
        else {}
    )
    return result


def _latency_distribution(values: Sequence[float]) -> dict[str, object]:
    result = _distribution(values, include_buckets=False)
    result.update(
        within_5_count=sum(value <= 5 for value in values),
        within_15_count=sum(value <= 15 for value in values),
        within_30_count=sum(value <= 30 for value in values),
        within_60_count=sum(value <= 60 for value in values),
    )
    return result


def _touch_by_gain_bucket(
    signals: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for bucket in ("3_to_5", "5_to_7", "7_to_9", "9_plus"):
        selected = [
            signal
            for signal in signals
            if _gain_bucket(_feature_number(signal, "gain_pct")) == bucket
        ]
        touches = sum(signal.get("later_touch") is True for signal in selected)
        result[bucket] = {
            "signal_count": len(selected),
            "touch_count": touches,
            "touch_precision_pct": _ratio_pct(touches, len(selected)),
        }
    return result


def _gain_bucket(gain: float | None) -> str | None:
    if gain is None or gain < 3.0:
        return None
    if gain < 5.0:
        return "3_to_5"
    if gain < 7.0:
        return "5_to_7"
    if gain < 9.0:
        return "7_to_9"
    return "9_plus"


def _feature_number(signal: Mapping[str, object], name: str) -> float | None:
    features = signal.get("features")
    return _number(features.get(name)) if isinstance(features, Mapping) else None


def _signal_sort_key(signal: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(signal.get("signal_date") or ""),
        str(signal.get("signal_at") or ""),
        str(signal.get("vt_symbol") or ""),
    )


def _descriptive_best_variant(
    variants: Mapping[str, object],
    variant_order: Sequence[str],
) -> str:
    def sort_key(variant: str) -> tuple[float, int]:
        validation = _mapping(_mapping(variants.get(variant)).get("validation"))
        prediction = _mapping(validation.get("prediction"))
        return (
            _number(prediction.get("touch_precision_pct")) or 0.0,
            int(_number(prediction.get("signal_count")) or 0),
        )

    return max(variant_order, key=sort_key)


def _ratio_pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _ratio(numerator: object, denominator: object) -> float | None:
    top = _number(numerator)
    bottom = _number(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    return round(top / bottom, 4)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _date_text(value: object) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed is not None else None


def _at_least(value: object, threshold: float) -> bool:
    number = _number(value)
    return number is not None and number >= threshold


def _above(value: object, threshold: float) -> bool:
    number = _number(value)
    return number is not None and number > threshold


def _display(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _pct(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}%" if number is not None else "-"


def _signed_pct(value: object) -> str:
    number = _number(value)
    return f"{number:+.4f}%" if number is not None else "-"


def _load_report(
    session_count: int,
    *,
    diagnostic_variant: str | None = None,
) -> dict[str, object]:
    from alphaagent.server.services.limit_up import history_engine, history_repository

    manifest = load_preboard_manifest(session_count=session_count)
    history_days = history_repository.load_history_candidate_pools(
        history_engine.HISTORY_STRATEGY_VERSION
    )
    manifest = attach_preboard_prior_evidence(manifest, history_days)
    minutes = load_preboard_minute_bars(manifest)
    daily = load_preboard_daily_bars(manifest)
    start = pd.to_datetime(manifest["trade_date"], errors="raise").min().date()
    end = pd.to_datetime(daily["trade_date"], errors="raise").max().date()
    calendar = load_reliable_trade_dates(start, end)
    return build_preboard_touch_report(
        manifest,
        minutes,
        daily,
        trade_dates=calendar,
        fit_session_count=min(30, max(session_count - 30, 1)),
        calibration_session_count=min(10, max(session_count - 20, 0)),
        model_variants=(diagnostic_variant,) if diagnostic_variant else MODEL_VARIANTS,
        primary_variant=diagnostic_variant or PRIMARY_VARIANT,
        diagnostic_only=diagnostic_variant is not None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--sessions", type=int, default=60)
    evaluate_parser.add_argument(
        "--format", choices=("json", "markdown"), default="json"
    )
    evaluate_parser.add_argument("--variant", choices=MODEL_VARIANTS)
    args = parser.parse_args(argv)

    report = _load_report(args.sessions, diagnostic_variant=args.variant)
    output = (
        render_preboard_touch_markdown(report)
        if args.format == "markdown"
        else json.dumps(report, ensure_ascii=False, indent=2, default=str)
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
