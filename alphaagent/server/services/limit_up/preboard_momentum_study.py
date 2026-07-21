"""Frozen recent-cross-section study for buying before first limit touch."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from math import isfinite, prod
from statistics import mean, median
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.execution import cash_ledger
from alphaagent.server.services.limit_up import cash_backtest
from alphaagent.server.services.limit_up.preboard_momentum import (
    ALGORITHMS,
    FEATURE_NAMES,
    RULE_ALGORITHMS,
    SEAL_MODEL_FEATURE_NAMES,
    build_prefix_rows,
    first_rule_signal,
)
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    attach_preboard_prior_evidence,
    backfill_preboard_five_minute,
    build_five_minute_coverage,
    load_five_minute_coverage,
    load_preboard_daily_bars,
    load_preboard_manifest,
    load_preboard_minute_bars,
    load_reliable_trade_dates,
)
from alphaagent.server.services.limit_up.preboard_seal_model import (
    MINIMUM_CALIBRATION_SIGNALS,
    MINIMUM_COMBINED_RATE,
    MINIMUM_D1_SAMPLES,
    PRIMARY_ALGORITHM,
    calibrate_seal_threshold,
    first_quality_gated_seal_signal,
    fit_quality_gated_seal_arrays,
    quality_candidate_outcome,
    seal_model_training_batch,
)


STUDY_VERSION = "limit-up-preboard-momentum-study-v2"
LOGISTIC_THRESHOLD = 0.5
REFERENCE_POSITION_CASH = 50_000.0
SEAL_MODEL_CALIBRATION_SESSIONS = 10
REPORT_ALGORITHMS = (*ALGORITHMS, PRIMARY_ALGORITHM)


@dataclass(frozen=True)
class LogisticFit:
    """Design-only fitted model plus a compact auditable fingerprint."""

    status: str
    pipeline: Any | None
    training_row_count: int
    class_counts: dict[str, int]
    design_dates: tuple[str, ...]
    coefficient_by_feature: dict[str, float]
    intercept: float | None

    def probability(self, features: Mapping[str, object]) -> float | None:
        if self.pipeline is None:
            return None
        vector = _feature_vector(features)
        if vector is None:
            return None
        return float(self.pipeline.predict_proba(np.asarray([vector]))[0, 1])


def chronological_date_split(
    values: Iterable[date | datetime | str],
    *,
    design_session_count: int = 40,
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    """Split chronological unique dates, never rows, into design and validation."""

    dates = sorted(
        {parsed for value in values if (parsed := _as_date(value)) is not None}
    )
    split = min(max(int(design_session_count), 0), len(dates))
    return tuple(dates[:split]), tuple(dates[split:])


def seal_model_date_split(
    design_dates: Sequence[date],
    *,
    calibration_session_count: int = SEAL_MODEL_CALIBRATION_SESSIONS,
) -> tuple[tuple[date, ...], tuple[date, ...]]:
    """Reserve the final design sessions for threshold calibration."""

    ordered = tuple(sorted(set(design_dates)))
    calibration_count = min(
        max(int(calibration_session_count), 0),
        max(len(ordered) - 1, 0),
    )
    if calibration_count == 0:
        return ordered, ()
    return ordered[:-calibration_count], ordered[-calibration_count:]


def fit_design_logistic(
    prefix_rows: Sequence[Mapping[str, object]],
    *,
    design_dates: set[date],
) -> LogisticFit:
    """Fit only finite, fillable design rows and ignore all later labels."""

    vectors: list[list[float]] = []
    targets: list[int] = []
    used_dates: set[date] = set()
    for row in prefix_rows:
        signal_date = _as_date(row.get("signal_date"))
        features = row.get("features")
        features = features if isinstance(features, Mapping) else {}
        vector = _feature_vector(features)
        if (
            signal_date not in design_dates
            or not _is_observable_model_candidate(row)
            or vector is None
            or row.get("model_target") is None
        ):
            continue
        vectors.append(vector)
        targets.append(int(bool(row.get("model_target"))))
        used_dates.add(signal_date)
    matrix = (
        np.asarray(vectors, dtype=float)
        if vectors
        else np.empty((0, len(FEATURE_NAMES)))
    )
    labels = np.asarray(targets, dtype=int)
    return _fit_logistic_arrays(matrix, labels, used_dates)


def build_preboard_momentum_report(
    manifest: pd.DataFrame,
    minute_rows: pd.DataFrame,
    daily_rows: pd.DataFrame,
    *,
    trade_dates: Sequence[date | str],
    design_session_count: int = 40,
) -> dict[str, object]:
    """Fit on design dates and replay every frozen algorithm chronologically."""

    prepared_manifest = _prepare_manifest(manifest)
    coverage = build_five_minute_coverage(prepared_manifest, minute_rows)
    complete_pairs = {
        (str(row.vt_symbol), _as_date(row.trade_date))
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    complete_pairs.discard(("", None))
    design_dates, validation_dates = chronological_date_split(
        prepared_manifest["trade_date"].tolist(),
        design_session_count=design_session_count,
    )
    seal_fit_dates, seal_calibration_dates = seal_model_date_split(design_dates)
    design_date_set = set(design_dates)
    seal_fit_date_set = set(seal_fit_dates)
    manifest_by_pair = _manifest_index(prepared_manifest)
    training_batches: list[np.ndarray] = []
    target_batches: list[np.ndarray] = []
    seal_training_batches: list[np.ndarray] = []
    seal_target_batches: list[np.ndarray] = []

    for pair, prefix_rows in _iter_labeled_prefix_groups(
        minute_rows,
        manifest_by_pair,
        complete_pairs,
        allowed_dates=design_date_set,
    ):
        if pair[1] in design_date_set:
            matrix, targets = _model_training_batch(prefix_rows)
            if len(matrix):
                training_batches.append(matrix)
                target_batches.append(targets)
        if pair[1] in seal_fit_date_set:
            matrix, targets = seal_model_training_batch(prefix_rows)
            if len(matrix):
                seal_training_batches.append(matrix)
                seal_target_batches.append(targets)

    training_matrix = (
        np.vstack(training_batches)
        if training_batches
        else np.empty((0, len(FEATURE_NAMES)))
    )
    training_targets = (
        np.concatenate(target_batches) if target_batches else np.empty(0, dtype=int)
    )
    model = _fit_logistic_arrays(
        training_matrix,
        training_targets,
        design_date_set,
    )
    seal_training_matrix = (
        np.vstack(seal_training_batches)
        if seal_training_batches
        else np.empty((0, len(SEAL_MODEL_FEATURE_NAMES)))
    )
    seal_training_targets = (
        np.concatenate(seal_target_batches)
        if seal_target_batches
        else np.empty(0, dtype=int)
    )
    seal_model = fit_quality_gated_seal_arrays(
        seal_training_matrix,
        seal_training_targets,
        fit_dates=seal_fit_date_set,
    )
    threshold_selection = calibrate_seal_threshold(
        (
            prefix_rows
            for _, prefix_rows in _iter_labeled_prefix_groups(
                minute_rows,
                manifest_by_pair,
                complete_pairs,
                allowed_dates=set(seal_calibration_dates),
            )
        ),
        seal_model,
        calibration_dates=set(seal_calibration_dates),
        minimum_signal_count=MINIMUM_CALIBRATION_SIGNALS,
    )
    signals_by_algorithm: dict[str, list[dict[str, object]]] = {
        algorithm: [] for algorithm in REPORT_ALGORITHMS
    }
    quality_outcomes: dict[tuple[str, date], dict[str, bool]] = {}
    for pair, prefix_rows in _iter_labeled_prefix_groups(
        minute_rows,
        manifest_by_pair,
        complete_pairs,
    ):
        quality_outcomes[pair] = quality_candidate_outcome(prefix_rows)
        for algorithm in RULE_ALGORITHMS:
            signal = first_rule_signal(prefix_rows, algorithm)
            if signal is not None:
                signals_by_algorithm[algorithm].append(signal)
        logistic = _first_logistic_signal(prefix_rows, model)
        if logistic is not None:
            signals_by_algorithm["logistic_imminent"].append(logistic)
        if threshold_selection.threshold is not None:
            seal_signal = first_quality_gated_seal_signal(
                prefix_rows,
                seal_model,
                threshold=threshold_selection.threshold,
            )
            if seal_signal is not None:
                signals_by_algorithm[PRIMARY_ALGORITHM].append(seal_signal)

    date_scopes = {
        "full": set((*design_dates, *validation_dates)),
        "design": set(design_dates),
        "validation": set(validation_dates),
    }
    algorithms: dict[str, dict[str, object]] = {}
    for algorithm in REPORT_ALGORITHMS:
        signals = sorted(signals_by_algorithm[algorithm], key=_signal_sort_key)
        algorithms[algorithm] = {
            phase: _phase_report(
                signals,
                phase_dates,
                daily_rows,
                trade_dates,
            )
            for phase, phase_dates in date_scopes.items()
        }
        if algorithm == PRIMARY_ALGORITHM:
            for phase, phase_dates in date_scopes.items():
                algorithms[algorithm][phase]["seal_prediction"] = (
                    _seal_prediction_metrics(
                        signals,
                        phase_dates,
                        quality_outcomes,
                    )
                )
        algorithms[algorithm]["acceptance"] = _forward_shadow_acceptance(
            algorithms[algorithm]["validation"]
        )

    complete_count = int(coverage["coverage_status"].eq("complete").sum())
    coverage_pct = (
        round(complete_count / len(coverage) * 100, 4) if len(coverage) else 0.0
    )
    forward_candidates = [
        algorithm
        for algorithm, result in algorithms.items()
        if result["acceptance"]["passed"] is True
    ]
    return {
        "study_version": STUDY_VERSION,
        "status": "ready" if coverage_pct >= 95.0 else "blocked_by_minute_coverage",
        "contract": {
            "capture_gain_pct": 3.0,
            "capture_gain_operator": ">=",
            "artificial_gain_ceiling": None,
            "decision_bars": "completed_5m_prefix_only",
            "entry": "next_5m_open_same_window",
            "exit": "d1_official_close",
            "max_positions": 2,
            "formal_strategy_changed": False,
        },
        "manifest": {
            "pair_count": int(len(prepared_manifest)),
            "symbol_count": int(prepared_manifest["vt_symbol"].nunique())
            if len(prepared_manifest)
            else 0,
            "trade_day_count": int(prepared_manifest["trade_date"].nunique())
            if len(prepared_manifest)
            else 0,
            "date_start": _date_text(prepared_manifest["trade_date"].min())
            if len(prepared_manifest)
            else None,
            "date_end": _date_text(prepared_manifest["trade_date"].max())
            if len(prepared_manifest)
            else None,
            "later_touch_count": int(
                prepared_manifest.get("touched_limit", pd.Series(dtype=bool)).sum()
            ),
            "final_seal_count": int(
                prepared_manifest.get("sealed_limit", pd.Series(dtype=bool)).sum()
            ),
            "history_quality_pair_count": _history_quality_pair_count(
                prepared_manifest
            ),
        },
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
            "design_dates": [_date_text(value) for value in design_dates],
            "seal_fit_dates": [_date_text(value) for value in seal_fit_dates],
            "seal_calibration_dates": [
                _date_text(value) for value in seal_calibration_dates
            ],
            "validation_dates": [_date_text(value) for value in validation_dates],
            "design_fingerprint": _date_fingerprint(design_dates),
        },
        "model": {
            "status": model.status,
            "training_row_count": model.training_row_count,
            "class_counts": model.class_counts,
            "design_dates": list(model.design_dates),
            "features": list(FEATURE_NAMES),
            "coefficient_by_feature": model.coefficient_by_feature,
            "intercept": model.intercept,
            "probability_threshold": LOGISTIC_THRESHOLD,
        },
        "seal_prediction_model": {
            "status": seal_model.status,
            "target": "d_day_final_seal",
            "training_row_count": seal_model.training_row_count,
            "class_counts": seal_model.class_counts,
            "fit_dates": list(seal_model.fit_dates),
            "features": list(SEAL_MODEL_FEATURE_NAMES),
            "coefficient_by_feature": seal_model.coefficient_by_feature,
            "intercept": seal_model.intercept,
            "minimum_d1_samples": MINIMUM_D1_SAMPLES,
            "minimum_combined_rate": MINIMUM_COMBINED_RATE,
            "threshold_selection": {
                "status": threshold_selection.status,
                "threshold": threshold_selection.threshold,
                "minimum_signal_count": threshold_selection.minimum_signal_count,
                "calibration_dates": list(threshold_selection.calibration_dates),
                "selected_metrics": threshold_selection.selected_metrics,
                "metrics_by_threshold": list(threshold_selection.metrics_by_threshold),
            },
        },
        "algorithms": algorithms,
        "forward_shadow_candidates": forward_candidates,
        "decision": (
            "historical_candidate_requires_new_forward_shadow"
            if forward_candidates
            else "no_algorithm_passed"
            if coverage_pct >= 95.0
            else "coverage_incomplete_no_performance_decision"
        ),
        "limitations": [
            "日线最高价只用于完整列出所有曾越过3%的股票日，不进入任何信号特征。",
            "3%表示大于等于3%；只用精确涨停价判断是否已经触板，不使用9.5%上限。",
            "信号只读取已完成5分钟K线，成交只取同一窗口下一根5分钟开盘。",
            "主模型只预测D日最终封板；D+1价格仅在信号冻结后用于收益结算。",
            "5分钟K线无法还原一根K线内部的秒级先后、盘口队列或真实委托成交。",
            "当前股票名称用于近期主板/ST过滤，不能证明更早日期名称状态完全无漂移。",
            "本轮历史日期已被其他研究查看，只是时间验证，不是新的锁定留出。",
            "历史通过最多进入前向影子，不自动替换limit-up-scheduled-v9或5%正式雷达。",
        ],
    }


def render_preboard_momentum_markdown(report: Mapping[str, object]) -> str:
    """Render the compact durable research report."""

    manifest = _mapping(report.get("manifest"))
    coverage = _mapping(report.get("coverage"))
    model = _mapping(report.get("model"))
    seal_model = _mapping(report.get("seal_prediction_model"))
    threshold = _mapping(seal_model.get("threshold_selection"))
    algorithms = _mapping(report.get("algorithms"))
    primary = _mapping(algorithms.get(PRIMARY_ALGORITHM))
    primary_validation = _mapping(primary.get("validation"))
    primary_recommendations = _mapping(primary_validation.get("all_recommendations"))
    primary_prediction = _mapping(primary_validation.get("seal_prediction"))
    primary_account = _mapping(
        _mapping(primary_validation.get("two_position_account")).get(
            "execution_summary"
        )
    )
    lines = [
        "# 首板 3% 以上提前动能研究",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status')}`；正式策略未修改。",
        f"- 清单：{manifest.get('pair_count', 0)} 个股票日、{manifest.get('symbol_count', 0)} 只股票、"
        f"{manifest.get('trade_day_count', 0)} 个交易日。",
        f"- 5分钟覆盖：{coverage.get('complete_pair_count', 0)}/{coverage.get('required_pair_count', 0)} "
        f"（{_display(coverage.get('coverage_pct'))}%）。",
        f"- 历史质量门：{manifest.get('history_quality_pair_count', 0)} 个股票日满足至少"
        f"{MINIMUM_D1_SAMPLES}个样本且联合率不低于{MINIMUM_COMBINED_RATE:g}%。",
        "- 信号只使用已完成的5分钟前缀，成交价固定为同一买入窗口的下一根5分钟开盘。",
        "",
        "## 时间验证",
        "",
        "| 算法 | 信号 | 两仓闭合 | 胜率 | 复利 | 回撤 | PF | 后续触板 | 最终封板 | 结论 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for algorithm in REPORT_ALGORITHMS:
        result = _mapping(algorithms.get(algorithm))
        validation = _mapping(result.get("validation"))
        recommendations = _mapping(validation.get("all_recommendations"))
        account = _mapping(validation.get("two_position_account"))
        summary = _mapping(account.get("execution_summary"))
        acceptance = _mapping(result.get("acceptance"))
        lines.append(
            "| "
            f"`{algorithm}` | {recommendations.get('signal_count', 0)} | "
            f"{summary.get('trade_count', 0)} | {_pct(summary.get('win_rate'))} | "
            f"{_signed_pct(summary.get('total_return_pct'))} | {_signed_pct(summary.get('max_drawdown_pct'))} | "
            f"{_display(summary.get('profit_factor'))} | {_pct(recommendations.get('later_touch_rate_pct'))} | "
            f"{_pct(recommendations.get('final_seal_rate_pct'))} | "
            f"{'通过影子门' if acceptance.get('passed') is True else '不通过'} |"
        )
    lines.extend(
        [
            "",
            "## Model",
            "",
            f"- 状态：`{model.get('status')}`；设计样本 {model.get('training_row_count', 0)} 行。",
            f"- 分类计数：`{json.dumps(model.get('class_counts') or {}, ensure_ascii=False, sort_keys=True)}`。",
            f"- 最终封板模型：`{seal_model.get('status')}`；训练样本 "
            f"{seal_model.get('training_row_count', 0)} 行；目标只为D日最终封板。",
            f"- 校准状态：`{threshold.get('status')}`；冻结概率阈值 "
            f"`{threshold.get('threshold')}`。",
            "",
            "## 主封板模型验证",
            "",
            f"- 预测 {primary_prediction.get('prediction_count', 0)} 个，最终封板 "
            f"{primary_prediction.get('true_positive_count', 0)} 个，精确率 "
            f"{_pct(primary_prediction.get('precision_pct'))}，召回率 "
            f"{_pct(primary_prediction.get('recall_pct'))}。",
            f"- 全推荐D+1：{primary_recommendations.get('closed_count', 0)} 笔，胜率 "
            f"{_pct(primary_recommendations.get('win_rate_pct'))}，平均净收益 "
            f"{_signed_pct(primary_recommendations.get('average_net_return_pct'))}，PF "
            f"{_display(primary_recommendations.get('profit_factor'))}。",
            f"- 两仓现金：{primary_account.get('trade_count', 0)} 笔，胜率 "
            f"{_pct(primary_account.get('win_rate'))}，复利 "
            f"{_signed_pct(primary_account.get('total_return_pct'))}，回撤 "
            f"{_signed_pct(primary_account.get('max_drawdown_pct'))}，PF "
            f"{_display(primary_account.get('profit_factor'))}。",
            "",
            "## Decision",
            "",
            f"`{report.get('decision')}`",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("limitations") or [])
    return "\n".join(lines) + "\n"


def _iter_labeled_prefix_groups(
    minute_rows: pd.DataFrame,
    manifest_by_pair: Mapping[tuple[str, date], Mapping[str, object]],
    complete_pairs: set[tuple[str, date | None]],
    *,
    allowed_dates: set[date] | None = None,
) -> Iterable[tuple[tuple[str, date], list[dict[str, object]]]]:
    if minute_rows.empty:
        return
    frame = minute_rows.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    frame = frame.sort_values(["trade_date", "vt_symbol", "bar_time"], kind="stable")
    for (symbol, trade_date), group in frame.groupby(
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
        prefix_rows = build_prefix_rows(manifest_row, bars)
        yield pair, _attach_model_targets(prefix_rows, bars)


def _attach_model_targets(
    prefix_rows: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    ordered = sorted(
        (dict(row) for row in bars),
        key=lambda row: str(row.get("bar_time") or ""),
    )
    index_by_time = {
        (_as_datetime(row.get("bar_time")) or datetime.min).isoformat(): index
        for index, row in enumerate(ordered)
    }
    labeled: list[dict[str, object]] = []
    for raw in prefix_rows:
        row = dict(raw)
        index = index_by_time.get(str(row.get("signal_at") or ""))
        limit_price = _number(row.get("limit_price"))
        imminent = False
        if index is not None and limit_price is not None:
            future_highs = [
                value
                for future in ordered[index + 1 : index + 7]
                if (value := _number(future.get("high_price"))) is not None
            ]
            imminent = bool(future_highs and max(future_highs) >= limit_price - 0.001)
        net_return = _execution_return(
            _number(row.get("entry_price")),
            _number(row.get("d1_close_price")),
            limit_price=limit_price,
            cost_multiplier=1.0,
        )
        row["touch_within_30m"] = imminent
        row["model_target"] = bool(
            row.get("before_first_limit_touch") is True
            and imminent
            and row.get("sealed_limit") is True
            and net_return is not None
            and net_return > 0
        )
        labeled.append(row)
    return labeled


def _model_training_batch(
    rows: Sequence[Mapping[str, object]],
) -> tuple[np.ndarray, np.ndarray]:
    vectors: list[list[float]] = []
    targets: list[int] = []
    for row in rows:
        features = row.get("features")
        features = features if isinstance(features, Mapping) else {}
        vector = _feature_vector(features)
        if not _is_observable_model_candidate(row) or vector is None:
            continue
        vectors.append(vector)
        targets.append(int(bool(row.get("model_target"))))
    matrix = (
        np.asarray(vectors, dtype=float)
        if vectors
        else np.empty((0, len(FEATURE_NAMES)))
    )
    return matrix, np.asarray(targets, dtype=int)


def _fit_logistic_arrays(
    matrix: np.ndarray,
    targets: np.ndarray,
    design_dates: set[date],
) -> LogisticFit:
    counts = Counter(int(value) for value in targets.tolist())
    class_counts = {"negative": counts.get(0, 0), "positive": counts.get(1, 0)}
    date_texts = tuple(_date_text(value) for value in sorted(design_dates))
    if len(matrix) == 0 or len(counts) < 2:
        return LogisticFit(
            status="blocked_by_training_classes",
            pipeline=None,
            training_row_count=int(len(matrix)),
            class_counts=class_counts,
            design_dates=date_texts,
            coefficient_by_feature={},
            intercept=None,
        )
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=0,
                ),
            ),
        ]
    )
    pipeline.fit(matrix, targets)
    logistic = pipeline.named_steps["logistic"]
    coefficients = {
        name: round(float(value), 12)
        for name, value in zip(FEATURE_NAMES, logistic.coef_[0], strict=True)
    }
    return LogisticFit(
        status="ready",
        pipeline=pipeline,
        training_row_count=int(len(matrix)),
        class_counts=class_counts,
        design_dates=date_texts,
        coefficient_by_feature=coefficients,
        intercept=round(float(logistic.intercept_[0]), 12),
    )


def _first_logistic_signal(
    rows: Sequence[Mapping[str, object]],
    model: LogisticFit,
) -> dict[str, object] | None:
    if model.status != "ready":
        return None
    candidates: list[dict[str, object]] = []
    vectors: list[list[float]] = []
    for raw in sorted(rows, key=lambda row: str(row.get("signal_at") or "")):
        row = dict(raw)
        if not _is_observable_model_candidate(row):
            continue
        features = row.get("features")
        features = features if isinstance(features, Mapping) else {}
        vector = _feature_vector(features)
        if vector is None:
            continue
        candidates.append(row)
        vectors.append(vector)
    if not candidates or model.pipeline is None:
        return None
    probabilities = model.pipeline.predict_proba(np.asarray(vectors, dtype=float))[:, 1]
    for row, probability in zip(candidates, probabilities, strict=True):
        if probability is not None and probability >= LOGISTIC_THRESHOLD:
            return {
                **row,
                "algorithm": "logistic_imminent",
                "model_probability": round(probability, 6),
            }
    return None


def _phase_report(
    signals: Sequence[Mapping[str, object]],
    phase_dates: set[date],
    daily_rows: pd.DataFrame,
    trade_dates: Sequence[date | str],
) -> dict[str, object]:
    selected = [
        dict(signal)
        for signal in signals
        if _as_date(signal.get("signal_date")) in phase_dates
    ]
    return {
        "all_recommendations": _recommendation_metrics(selected),
        "two_position_account": _account_report(
            selected,
            daily_rows,
            trade_dates,
            cost_multiplier=1.0,
        ),
        "double_cost_account": _account_report(
            selected,
            daily_rows,
            trade_dates,
            cost_multiplier=2.0,
        ),
    }


def _recommendation_metrics(
    signals: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    settled: list[dict[str, object]] = []
    for signal in signals:
        normal = _execution_return(
            _number(signal.get("entry_price")),
            _number(signal.get("d1_close_price")),
            limit_price=_number(signal.get("limit_price")),
            cost_multiplier=1.0,
        )
        stress = _execution_return(
            _number(signal.get("entry_price")),
            _number(signal.get("d1_close_price")),
            limit_price=_number(signal.get("limit_price")),
            cost_multiplier=2.0,
        )
        if normal is None or stress is None:
            continue
        settled.append(
            {**dict(signal), "net_return_pct": normal, "double_cost_return_pct": stress}
        )
    returns = [float(row["net_return_pct"]) for row in settled]
    stress_returns = [float(row["double_cost_return_pct"]) for row in settled]
    daily: dict[str, list[float]] = defaultdict(list)
    for row in settled:
        daily[str(row.get("signal_date") or "")].append(float(row["net_return_pct"]))
    daily_returns = [mean(daily[key]) for key in sorted(daily)]
    touch_count = sum(bool(row.get("touched_limit")) for row in settled)
    seal_count = sum(bool(row.get("sealed_limit")) for row in settled)
    return {
        "signal_count": len(signals),
        "closed_count": len(settled),
        "win_count": sum(value > 0 for value in returns),
        "loss_count": sum(value <= 0 for value in returns),
        "win_rate_pct": _ratio_pct(sum(value > 0 for value in returns), len(returns)),
        "average_net_return_pct": _average(returns),
        "median_net_return_pct": _median(returns),
        "profit_factor": _profit_factor(returns),
        "daily_equal_weight_compound_return_pct": _compound_return(daily_returns),
        "max_drawdown_pct": _max_drawdown(daily_returns),
        "hard_loss_count": sum(value <= -5 for value in returns),
        "later_touch_count": touch_count,
        "later_touch_rate_pct": _ratio_pct(touch_count, len(settled)),
        "final_seal_count": seal_count,
        "final_seal_rate_pct": _ratio_pct(seal_count, len(settled)),
        "double_cost_average_net_return_pct": _average(stress_returns),
        "double_cost_profit_factor": _profit_factor(stress_returns),
    }


def _seal_prediction_metrics(
    signals: Sequence[Mapping[str, object]],
    phase_dates: set[date],
    quality_outcomes: Mapping[tuple[str, date], Mapping[str, bool]],
) -> dict[str, object]:
    selected = [
        signal
        for signal in signals
        if _as_date(signal.get("signal_date")) in phase_dates
    ]
    true_positives = sum(bool(signal.get("sealed_limit")) for signal in selected)
    scoped_outcomes = [
        outcome
        for (_, signal_date), outcome in quality_outcomes.items()
        if signal_date in phase_dates and outcome.get("eligible") is True
    ]
    eligible_positives = sum(
        outcome.get("sealed") is True for outcome in scoped_outcomes
    )
    return {
        "prediction_count": len(selected),
        "true_positive_count": true_positives,
        "false_positive_count": len(selected) - true_positives,
        "precision_pct": _ratio_pct(true_positives, len(selected)),
        "eligible_pair_count": len(scoped_outcomes),
        "eligible_positive_count": eligible_positives,
        "recall_pct": _ratio_pct(true_positives, eligible_positives),
    }


def _history_quality_pair_count(manifest: pd.DataFrame) -> int:
    required = {"stock_d1_sample_count", "stock_gene_combined_win_rate"}
    if manifest.empty or not required <= set(manifest.columns):
        return 0
    samples = pd.to_numeric(manifest["stock_d1_sample_count"], errors="coerce")
    combined = pd.to_numeric(manifest["stock_gene_combined_win_rate"], errors="coerce")
    return int(
        (samples.ge(MINIMUM_D1_SAMPLES) & combined.ge(MINIMUM_COMBINED_RATE)).sum()
    )


def _account_report(
    signals: Sequence[Mapping[str, object]],
    daily_rows: pd.DataFrame,
    trade_dates: Sequence[date | str],
    *,
    cost_multiplier: float,
) -> dict[str, object]:
    config = cash_backtest.CashBacktestConfig(
        max_positions=2,
        commission_rate=0.0003 * cost_multiplier,
        minimum_commission=5.0 * cost_multiplier,
        stamp_tax_rate=0.0005 * cost_multiplier,
        transfer_fee_rate=0.00001 * cost_multiplier,
        slippage_bps=10.0 * cost_multiplier,
    )
    account_signals = [_account_signal(signal) for signal in signals]
    symbols = {str(signal.get("vt_symbol") or "") for signal in signals}
    if symbols and not daily_rows.empty:
        scoped_bars = daily_rows.loc[
            daily_rows["vt_symbol"].astype(str).isin(symbols)
        ].copy()
        scoped_bars["trade_date"] = pd.to_datetime(
            scoped_bars["trade_date"], errors="raise"
        ).dt.date
    else:
        scoped_bars = daily_rows.iloc[0:0].copy()
    result = cash_backtest.simulate_limit_up_account(
        account_signals,
        scoped_bars.to_dict(orient="records"),
        trade_dates,
        "next_close",
        config,
    )
    summary = {**result["execution_summary"], "max_positions": config.max_positions}
    return {
        "account_config": result["account_config"],
        "execution_version": result["execution_version"],
        "execution_summary": summary,
    }


def _account_signal(signal: Mapping[str, object]) -> dict[str, object]:
    return {
        **dict(signal),
        "entry_date": str(signal.get("signal_date") or "")[:10],
        "buy_time": str(signal.get("entry_time") or ""),
        "lane": "first_board",
        "signal_kind": "momentum",
        "entry_price": _number(signal.get("entry_price")),
        "result_date": str(signal.get("result_date") or "")[:10] or None,
        "d_board_status": "sealed" if signal.get("sealed_limit") else "failed",
    }


def _execution_return(
    entry_price: float | None,
    exit_price: float | None,
    *,
    limit_price: float | None,
    cost_multiplier: float,
) -> float | None:
    if entry_price is None or entry_price <= 0 or exit_price is None or exit_price <= 0:
        return None
    buy = cash_ledger.calculate_buy_execution(
        raw_price=entry_price,
        cash=REFERENCE_POSITION_CASH,
        target_cash=REFERENCE_POSITION_CASH,
        commission_rate=0.0003 * cost_multiplier,
        slippage_bps=10.0 * cost_multiplier,
        lot_size=100,
        minimum_commission=5.0 * cost_multiplier,
        transfer_fee_rate=0.00001 * cost_multiplier,
        max_price=limit_price,
    )
    if buy.volume <= 0:
        return None
    sell = cash_ledger.calculate_sell_execution(
        raw_price=exit_price,
        volume=buy.volume,
        cost_price=buy.price,
        commission_rate=0.0003 * cost_multiplier,
        stamp_tax_rate=0.0005 * cost_multiplier,
        slippage_bps=10.0 * cost_multiplier,
        minimum_commission=5.0 * cost_multiplier,
        transfer_fee_rate=0.00001 * cost_multiplier,
    )
    cash_cost = buy.amount + buy.fee
    return round((sell.cash_delta - cash_cost) / cash_cost * 100, 6)


def _forward_shadow_acceptance(phase: Mapping[str, object]) -> dict[str, object]:
    account = _mapping(
        _mapping(phase.get("two_position_account")).get("execution_summary")
    )
    stress = _mapping(
        _mapping(phase.get("double_cost_account")).get("execution_summary")
    )
    gates = {
        "closed_trades": _at_least(account.get("trade_count"), 30),
        "win_rate": _above(account.get("win_rate"), 60.0),
        "compound_return": _above(account.get("total_return_pct"), 0.0),
        "profit_factor": _profit_factor_gate(account, 1.5),
        "max_drawdown": _at_least(account.get("max_drawdown_pct"), -10.0),
        "double_cost_profit_factor": _profit_factor_gate(stress, 1.2),
    }
    return {"passed": all(gates.values()), "gates": gates}


def _feature_vector(features: Mapping[str, object]) -> list[float] | None:
    values = [_number(features.get(name)) for name in FEATURE_NAMES]
    if any(value is None or not isfinite(value) for value in values):
        return None
    return [float(value) for value in values if value is not None]


def _is_observable_model_candidate(row: Mapping[str, object]) -> bool:
    features = row.get("features")
    features = features if isinstance(features, Mapping) else {}
    gain = _number(features.get("gain_pct"))
    return bool(
        row.get("fillable") is True
        and row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= 3.0
    )


def _prepare_manifest(manifest: pd.DataFrame) -> pd.DataFrame:
    required = {"vt_symbol", "trade_date", "previous_close", "limit_price"}
    missing = sorted(required - set(manifest.columns))
    if missing:
        raise ValueError(f"missing manifest columns: {', '.join(missing)}")
    frame = manifest.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    return frame.sort_values(["trade_date", "vt_symbol"], kind="stable").reset_index(
        drop=True
    )


def _manifest_index(
    manifest: pd.DataFrame,
) -> dict[tuple[str, date], dict[str, object]]:
    return {
        (str(row["vt_symbol"]), parsed): dict(row)
        for row in manifest.to_dict(orient="records")
        if (parsed := _as_date(row.get("trade_date"))) is not None
    }


def _signal_sort_key(signal: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(signal.get("signal_date") or ""),
        str(signal.get("signal_time") or ""),
        str(signal.get("vt_symbol") or ""),
    )


def _date_fingerprint(values: Sequence[date]) -> str | None:
    if not values:
        return None
    payload = f"{STUDY_VERSION}:{','.join(_date_text(value) for value in values)}"
    return f"sha256:{sha256(payload.encode('ascii')).hexdigest()}"


def _compound_return(returns_pct: Sequence[float]) -> float:
    return round((prod(1 + value / 100 for value in returns_pct) - 1) * 100, 4)


def _max_drawdown(returns_pct: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in returns_pct:
        equity *= 1 + value / 100
        peak = max(peak, equity)
        drawdown = min(drawdown, (equity / peak - 1) * 100)
    return round(drawdown, 4)


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value <= 0))
    if losses <= 0:
        return None
    return round(gains / losses, 4)


def _profit_factor_gate(summary: Mapping[str, object], threshold: float) -> bool:
    factor = _number(summary.get("profit_factor"))
    loss_count = int(_number(summary.get("trade_count")) or 0) - int(
        _number(summary.get("win_count")) or 0
    )
    return (factor is not None and factor >= threshold) or (
        factor is None
        and loss_count == 0
        and int(_number(summary.get("trade_count")) or 0) > 0
    )


def _ratio_pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _average(values: Sequence[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _median(values: Sequence[float]) -> float | None:
    return round(median(values), 4) if values else None


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


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _date_text(value: object) -> str:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed is not None else ""


def _at_least(value: object, threshold: float) -> bool:
    parsed = _number(value)
    return parsed is not None and parsed >= threshold


def _above(value: object, threshold: float) -> bool:
    parsed = _number(value)
    return parsed is not None and parsed > threshold


def _display(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.4f}" if parsed is not None else "null"


def _pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.4f}%" if parsed is not None else "null"


def _signed_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:+.4f}%" if parsed is not None else "null"


def _manifest_summary(session_count: int) -> dict[str, object]:
    manifest = load_preboard_manifest(session_count=session_count)
    coverage = load_five_minute_coverage(manifest)
    complete = int(coverage["coverage_status"].eq("complete").sum())
    return {
        "study_version": STUDY_VERSION,
        "manifest_pairs": int(len(manifest)),
        "symbols": int(manifest["vt_symbol"].nunique()) if len(manifest) else 0,
        "dates": int(manifest["trade_date"].nunique()) if len(manifest) else 0,
        "complete_pairs": complete,
        "coverage_pct": round(complete / len(coverage) * 100, 4)
        if len(coverage)
        else 0.0,
        "status_counts": coverage["coverage_status"].value_counts().to_dict(),
    }


def _load_report(session_count: int) -> dict[str, object]:
    from alphaagent.server.services.limit_up import history_engine, history_repository

    manifest = load_preboard_manifest(session_count=session_count)
    history_days = history_repository.load_history_candidate_pools(
        history_engine.HISTORY_STRATEGY_VERSION
    )
    manifest = attach_preboard_prior_evidence(manifest, history_days)
    minutes = load_preboard_minute_bars(manifest)
    daily = load_preboard_daily_bars(manifest)
    start = pd.to_datetime(manifest["trade_date"]).min().date()
    end = pd.to_datetime(daily["trade_date"], errors="raise").max().date()
    calendar = load_reliable_trade_dates(start, end)
    return build_preboard_momentum_report(
        manifest,
        minutes,
        daily,
        trade_dates=calendar,
        design_session_count=min(40, max(session_count - 20, 1)),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("--sessions", type=int, default=60)
    backfill_parser = subparsers.add_parser("backfill")
    backfill_parser.add_argument("--sessions", type=int, default=60)
    backfill_parser.add_argument("--max-symbols", type=int, default=50)
    backfill_parser.add_argument("--symbol-offset", type=int, default=0)
    backfill_parser.add_argument("--write", action="store_true")
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--sessions", type=int, default=60)
    evaluate_parser.add_argument(
        "--format", choices=("json", "markdown"), default="json"
    )
    args = parser.parse_args(argv)

    if args.command == "manifest":
        result: Mapping[str, object] = _manifest_summary(args.sessions)
        output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    elif args.command == "backfill":
        result = backfill_preboard_five_minute(
            dry_run=not args.write,
            max_symbols=args.max_symbols,
            symbol_offset=args.symbol_offset,
            session_count=args.sessions,
        )
        output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    else:
        result = _load_report(args.sessions)
        output = (
            render_preboard_momentum_markdown(result)
            if args.format == "markdown"
            else json.dumps(result, ensure_ascii=False, indent=2, default=str)
        )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
