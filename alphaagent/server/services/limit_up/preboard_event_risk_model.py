"""Causal market-event and candidate-ranking models for pre-board actions."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from math import isfinite, log1p
from statistics import mean
from typing import Any

import numpy as np

from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    DEFAULT_ACTION_THRESHOLDS,
)
from alphaagent.server.services.limit_up.preboard_reverse_profile import (
    trading_minutes_between,
)
from alphaagent.server.services.limit_up.preboard_transaction_trigger_model import (
    TRANSACTION_TRIGGER_FEATURE_NAMES,
    transaction_trigger_feature_vector,
)


EVENT_FEATURE_VERSION = "limit-up-preboard-event-risk-v1"
TOUCH_TARGET_FIELD = "formal_touch_within_3m"
EVENT_MARKET_TARGET_FIELD = "market_formal_touch_within_3m"
EVENT_MARKET_SCORE_FIELD = "event_market_touch_3m_probability"
EVENT_RANK_SCORE_FIELD = "event_candidate_rank_score"
EVENT_CANDIDATE_RANK_FIELD = "event_candidate_rank"
MINIMUM_CALIBRATION_SELECTIONS = 10
MINIMUM_CALIBRATION_PRECISION = 0.70
MAX_DAILY_FIRST_BOARD_ACTIONS = 2

MARKET_EVENT_FEATURE_NAMES = (
    "event_active_candidate_count_log1p",
    "event_new_candidate_count_1m_log1p",
    "event_new_candidate_count_3m_log1p",
    "event_near_limit_candidate_count_log1p",
    "event_gain_max_pct",
    "event_gain_p75_pct",
    "event_positive_return_1m_ratio",
    "event_positive_return_3m_ratio",
    "event_tx_price_imbalance_mean_1m",
    "event_tx_trade_acceleration_mean_1m_5m",
    "event_active_candidate_count_delta_1m",
    "event_positive_return_1m_ratio_delta_1m",
)
CANDIDATE_EVENT_FEATURE_NAMES = (
    "event_candidate_age_minutes_log1p",
    "event_candidate_visible_count_3m",
    "event_gain_strength_delta_1m",
    "event_rank_strength_delta_1m",
    "event_tx_price_imbalance_delta_1m",
)
EVENT_RANK_FEATURE_NAMES = (
    *TRANSACTION_TRIGGER_FEATURE_NAMES,
    *CANDIDATE_EVENT_FEATURE_NAMES,
)
EVENT_RANK_MODEL_PARAMETERS: dict[str, object] = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "n_estimators": 80,
    "learning_rate": 0.03,
    "num_leaves": 7,
    "max_depth": 3,
    "min_child_samples": 20,
    "reg_alpha": 1.0,
    "reg_lambda": 5.0,
    "colsample_bytree": 0.8,
    "random_state": 0,
    "deterministic": True,
    "force_col_wise": True,
    "n_jobs": 1,
    "verbosity": -1,
}


@dataclass(frozen=True)
class EventMarketModelFit:
    status: str
    pipeline: Any | None
    target_field: str
    feature_version: str
    training_row_count: int
    training_date_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    scaler_mean_by_feature: dict[str, float]
    scaler_scale_by_feature: dict[str, float]
    coefficient_by_feature: dict[str, float]
    intercept: float | None
    fingerprint: str | None

    def probability(self, row: Mapping[str, object]) -> float | None:
        vector = event_market_feature_vector(row)
        if self.pipeline is None or vector is None:
            return None
        return float(
            self.pipeline.predict_proba(np.asarray([vector], dtype=float))[0, 1]
        )


@dataclass(frozen=True)
class EventRankModelFit:
    status: str
    model: Any | None
    feature_version: str
    training_row_count: int
    training_group_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    parameters: dict[str, object]
    feature_importance_by_name: dict[str, float]
    booster_model_text: str | None
    fingerprint: str | None

    def score(self, row: Mapping[str, object]) -> float | None:
        vector = event_rank_feature_vector(row)
        if self.model is None or vector is None:
            return None
        return float(self.model.predict(np.asarray([vector], dtype=float))[0])


@dataclass(frozen=True)
class EventThresholdSelection:
    status: str
    threshold: float | None
    calibration_dates: tuple[str, ...]
    minimum_selection_count: int
    minimum_precision: float
    selected_metrics: dict[str, float | int | None]
    metrics_by_threshold: tuple[dict[str, float | int | None], ...]


def enrich_event_risk_features(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach current-and-past-only market and candidate event features."""

    ordered = sorted((dict(row) for row in rows), key=_row_sort_key)
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in ordered:
        if _scoreable_candidate(row):
            groups[_minute_key(row)].append(row)

    enriched_by_identity: dict[tuple[str, str, str], dict[str, object]] = {}
    first_seen: dict[tuple[str, str], str] = {}
    visible_times: dict[tuple[str, str], list[str]] = defaultdict(list)
    previous_candidate: dict[tuple[str, str], dict[str, object]] = {}
    previous_market: dict[str, tuple[str, dict[str, float]]] = {}

    for minute_key in sorted(groups):
        date_text, signal_time = minute_key
        minute_rows = sorted(groups[minute_key], key=_symbol_sort_key)
        market_features = _market_event_features(
            minute_rows,
            date_text=date_text,
            signal_time=signal_time,
            first_seen=first_seen,
            previous_market=previous_market,
        )
        for row in minute_rows:
            symbol = str(row.get("vt_symbol") or "")
            candidate_key = (date_text, symbol)
            first_time = first_seen.setdefault(candidate_key, signal_time)
            visible_times[candidate_key].append(signal_time)
            prior = previous_candidate.get(candidate_key)
            candidate_features = _candidate_event_features(
                row,
                signal_time=signal_time,
                first_time=first_time,
                visible_times=visible_times[candidate_key],
                previous=prior,
            )
            enriched = {
                **row,
                "event_feature_version": EVENT_FEATURE_VERSION,
                "event_feature_cutoff": row.get("signal_at")
                or f"{date_text}T{signal_time}",
                "event_active_candidate_count": len(minute_rows),
                "event_market_features": market_features,
                "event_candidate_features": candidate_features,
            }
            enriched_by_identity[_row_identity(row)] = enriched
            previous_candidate[candidate_key] = enriched
        previous_market[date_text] = (signal_time, market_features)

    return [
        enriched_by_identity.get(_row_identity(row), row)
        for row in ordered
    ]


def event_market_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    features = row.get("event_market_features")
    if not isinstance(features, Mapping):
        return None
    values = [_number(features.get(name)) for name in MARKET_EVENT_FEATURE_NAMES]
    if any(value is None for value in values):
        return None
    return [float(value) for value in values if value is not None]


def event_rank_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    core = transaction_trigger_feature_vector(row)
    event = row.get("event_candidate_features")
    if core is None or not isinstance(event, Mapping):
        return None
    values = [_number(event.get(name)) for name in CANDIDATE_EVENT_FEATURE_NAMES]
    if any(value is None for value in values):
        return None
    return [*core, *(float(value) for value in values if value is not None)]


def event_market_training_batch(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[tuple[str, str], ...]]:
    prepared = _event_market_rows(rows, allowed_dates=allowed_dates)
    date_counts = Counter(key[0] for _, _, key in prepared)
    matrix = (
        np.asarray([vector for vector, _, _ in prepared], dtype=float)
        if prepared
        else np.empty((0, len(MARKET_EVENT_FEATURE_NAMES)), dtype=float)
    )
    labels = np.asarray([label for _, label, _ in prepared], dtype=int)
    keys = tuple(key for _, _, key in prepared)
    weights = np.asarray(
        [1.0 / date_counts[key[0]] for key in keys],
        dtype=float,
    )
    return matrix, labels, weights, keys


def event_ranking_training_batch(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> tuple[
    np.ndarray,
    np.ndarray,
    tuple[int, ...],
    tuple[tuple[str, str], ...],
    tuple[tuple[str, str, str], ...],
]:
    groups: dict[
        tuple[str, str],
        list[tuple[list[float], int, tuple[str, str, str]]],
    ] = defaultdict(list)
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        vector = event_rank_feature_vector(row)
        if signal_date not in allowed_dates or vector is None:
            continue
        groups[_minute_key(row)].append(
            (vector, int(row.get(TOUCH_TARGET_FIELD) is True), _row_identity(row))
        )

    prepared: list[tuple[list[float], int, tuple[str, str, str]]] = []
    group_sizes: list[int] = []
    group_keys: list[tuple[str, str]] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda item: item[2])
        if {label for _, label, _ in group} != {0, 1}:
            continue
        prepared.extend(group)
        group_sizes.append(len(group))
        group_keys.append(key)

    matrix = (
        np.asarray([vector for vector, _, _ in prepared], dtype=float)
        if prepared
        else np.empty((0, len(EVENT_RANK_FEATURE_NAMES)), dtype=float)
    )
    labels = np.asarray([label for _, label, _ in prepared], dtype=int)
    row_keys = tuple(key for _, _, key in prepared)
    return matrix, labels, tuple(group_sizes), tuple(group_keys), row_keys


def fit_event_market_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
) -> EventMarketModelFit:
    matrix, labels, weights, keys = event_market_training_batch(
        rows,
        allowed_dates=fit_dates,
    )
    common = {
        "target_field": EVENT_MARKET_TARGET_FIELD,
        "feature_version": EVENT_FEATURE_VERSION,
        "training_row_count": len(labels),
        "training_date_count": len({key[0] for key in keys}),
        "class_counts": _class_counts(labels),
        "fit_dates": tuple(value.isoformat() for value in sorted(fit_dates)),
    }
    if len(labels) < 2 or len(set(labels.tolist())) < 2:
        return EventMarketModelFit(
            status="insufficient_training_classes",
            pipeline=None,
            scaler_mean_by_feature={},
            scaler_scale_by_feature={},
            coefficient_by_feature={},
            intercept=None,
            fingerprint=None,
            **common,
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
                    class_weight=None,
                    max_iter=2_000,
                    random_state=0,
                ),
            ),
        ]
    )
    pipeline.fit(
        matrix,
        labels,
        scaler__sample_weight=weights,
        logistic__sample_weight=weights,
    )
    scaler = pipeline.named_steps["scaler"]
    logistic = pipeline.named_steps["logistic"]
    means = _feature_mapping(MARKET_EVENT_FEATURE_NAMES, scaler.mean_)
    scales = _feature_mapping(MARKET_EVENT_FEATURE_NAMES, scaler.scale_)
    coefficients = _feature_mapping(
        MARKET_EVENT_FEATURE_NAMES,
        logistic.coef_[0],
    )
    intercept = _canonical_float(logistic.intercept_[0])
    fingerprint = _stable_fingerprint(
        {
            "model": "standard_scaler_logistic_regression",
            "feature_version": EVENT_FEATURE_VERSION,
            "features": MARKET_EVENT_FEATURE_NAMES,
            "fit_dates": common["fit_dates"],
            "means": means,
            "scales": scales,
            "coefficients": coefficients,
            "intercept": intercept,
        }
    )
    return EventMarketModelFit(
        status="ready",
        pipeline=pipeline,
        scaler_mean_by_feature=means,
        scaler_scale_by_feature=scales,
        coefficient_by_feature=coefficients,
        intercept=intercept,
        fingerprint=fingerprint,
        **common,
    )


def fit_event_rank_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
) -> EventRankModelFit:
    matrix, labels, group_sizes, group_keys, _ = event_ranking_training_batch(
        rows,
        allowed_dates=fit_dates,
    )
    common = {
        "feature_version": EVENT_FEATURE_VERSION,
        "training_row_count": len(labels),
        "training_group_count": len(group_sizes),
        "class_counts": _class_counts(labels),
        "fit_dates": tuple(value.isoformat() for value in sorted(fit_dates)),
        "parameters": dict(EVENT_RANK_MODEL_PARAMETERS),
    }
    if (
        len(labels) < 2
        or len(group_sizes) < 1
        or len(set(labels.tolist())) < 2
        or sum(group_sizes) != len(labels)
    ):
        return EventRankModelFit(
            status="insufficient_mixed_risk_sets",
            model=None,
            feature_importance_by_name={},
            booster_model_text=None,
            fingerprint=None,
            **common,
        )

    import pandas as pd
    from lightgbm import LGBMRanker

    model = LGBMRanker(**EVENT_RANK_MODEL_PARAMETERS)
    frame = pd.DataFrame(matrix, columns=EVENT_RANK_FEATURE_NAMES)
    model.fit(frame, labels, group=list(group_sizes))
    booster_text = str(model.booster_.model_to_string())
    importance = {
        name: _canonical_float(value)
        for name, value in zip(
            EVENT_RANK_FEATURE_NAMES,
            model.booster_.feature_importance(importance_type="gain"),
            strict=True,
        )
    }
    fingerprint = _stable_fingerprint(
        {
            "model": "lightgbm_lambdarank",
            "feature_version": EVENT_FEATURE_VERSION,
            "features": EVENT_RANK_FEATURE_NAMES,
            "fit_dates": common["fit_dates"],
            "parameters": EVENT_RANK_MODEL_PARAMETERS,
            "group_keys": group_keys,
            "booster_sha256": sha256(booster_text.encode()).hexdigest(),
        }
    )
    return EventRankModelFit(
        status="ready",
        model=model,
        feature_importance_by_name=importance,
        booster_model_text=booster_text,
        fingerprint=fingerprint,
        **common,
    )


def score_event_risk_rows(
    rows: Sequence[Mapping[str, object]],
    market_model: EventMarketModelFit,
    rank_model: EventRankModelFit,
) -> list[dict[str, object]]:
    if (
        market_model.status != "ready"
        or market_model.pipeline is None
        or rank_model.status != "ready"
        or rank_model.model is None
    ):
        return []

    prepared = [
        (dict(row), market_vector, rank_vector)
        for row in rows
        if (market_vector := event_market_feature_vector(row)) is not None
        and (rank_vector := event_rank_feature_vector(row)) is not None
    ]
    if not prepared:
        return []

    minute_vectors: dict[tuple[str, str], list[float]] = {}
    for row, market_vector, _ in prepared:
        minute_vectors.setdefault(_minute_key(row), market_vector)
    minute_keys = sorted(minute_vectors)
    market_matrix = np.asarray(
        [minute_vectors[key] for key in minute_keys],
        dtype=float,
    )
    market_probabilities = market_model.pipeline.predict_proba(market_matrix)[:, 1]
    probability_by_minute = {
        key: round(float(probability), 8)
        for key, probability in zip(
            minute_keys,
            market_probabilities,
            strict=True,
        )
    }

    import pandas as pd

    rank_matrix = pd.DataFrame(
        [rank_vector for _, _, rank_vector in prepared],
        columns=EVENT_RANK_FEATURE_NAMES,
    )
    rank_scores = rank_model.model.predict(rank_matrix)
    scored = [
        {
            **row,
            EVENT_MARKET_SCORE_FIELD: probability_by_minute[_minute_key(row)],
            EVENT_RANK_SCORE_FIELD: round(float(rank_score), 8),
        }
        for (row, _, _), rank_score in zip(prepared, rank_scores, strict=True)
    ]
    return _attach_candidate_ranks(scored)


def select_event_risk_signals(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    max_daily_actions: int = MAX_DAILY_FIRST_BOARD_ACTIONS,
) -> list[dict[str, object]]:
    """Select only the top-ranked candidate in each qualifying complete minute."""

    daily_limit = max(int(max_daily_actions), 1)
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        if (
            row.get("shared_strategy_passed") is True
            and row.get("before_first_limit_touch") is True
            and _number(row.get(EVENT_MARKET_SCORE_FIELD)) is not None
            and _number(row.get(EVENT_RANK_SCORE_FIELD)) is not None
        ):
            groups[_minute_key(row)].append(row)

    selected_pairs: set[tuple[str, str]] = set()
    daily_counts: Counter[str] = Counter()
    selected: list[dict[str, object]] = []
    for minute_key in sorted(groups):
        date_text = minute_key[0]
        if daily_counts[date_text] >= daily_limit:
            continue
        choices = sorted(groups[minute_key], key=_action_ranking_key)
        if not choices:
            continue
        top = choices[0]
        probability = _number(top.get(EVENT_MARKET_SCORE_FIELD))
        pair = _row_pair(top)
        if probability is None or probability < float(threshold) or pair in selected_pairs:
            continue
        selected_pairs.add(pair)
        daily_counts[date_text] += 1
        selected.append(
            {
                **top,
                EVENT_CANDIDATE_RANK_FIELD: 1,
                "event_action_score": probability,
            }
        )
    return selected


def calibrate_event_risk_threshold(
    rows: Sequence[Mapping[str, object]],
    *,
    calibration_dates: set[date],
    thresholds: Sequence[float] = DEFAULT_ACTION_THRESHOLDS,
    minimum_selection_count: int = MINIMUM_CALIBRATION_SELECTIONS,
    minimum_precision: float = MINIMUM_CALIBRATION_PRECISION,
) -> EventThresholdSelection:
    required_count = max(int(minimum_selection_count), 1)
    required_precision = float(minimum_precision)
    if not isfinite(required_precision) or not 0.0 <= required_precision <= 1.0:
        raise ValueError("minimum_precision must be between 0 and 1")
    calibration_rows = [
        dict(row)
        for row in rows
        if _as_date(row.get("signal_date")) in calibration_dates
    ]
    reachable_pairs = {
        _row_pair(row)
        for row in calibration_rows
        if row.get(TOUCH_TARGET_FIELD) is True
        and _number(row.get(EVENT_MARKET_SCORE_FIELD)) is not None
        and _number(row.get(EVENT_RANK_SCORE_FIELD)) is not None
    }
    metrics = tuple(
        _threshold_metrics(
            calibration_rows,
            threshold=float(threshold),
            reachable_pairs=reachable_pairs,
        )
        for threshold in thresholds
    )
    qualified = [
        row
        for row in metrics
        if int(row.get("selection_count") or 0) >= required_count
        and (_number(row.get("touch_precision")) or 0.0) >= required_precision
    ]
    selected = max(
        qualified,
        key=lambda row: (
            float(row.get("reachable_recall") or 0.0),
            float(row.get("touch_precision") or 0.0),
            float(row.get("threshold") or 0.0),
        ),
        default=None,
    )
    return EventThresholdSelection(
        status="ready" if selected is not None else "calibration_precision_gate_failed",
        threshold=float(selected["threshold"]) if selected is not None else None,
        calibration_dates=tuple(
            value.isoformat() for value in sorted(calibration_dates)
        ),
        minimum_selection_count=required_count,
        minimum_precision=required_precision,
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def score_frozen_event_market_probability(
    row: Mapping[str, object],
    model: EventMarketModelFit,
) -> float | None:
    vector = event_market_feature_vector(row)
    if vector is None or model.intercept is None:
        return None
    logit = float(model.intercept)
    for name, value in zip(MARKET_EVENT_FEATURE_NAMES, vector, strict=True):
        center = _number(model.scaler_mean_by_feature.get(name))
        scale = _number(model.scaler_scale_by_feature.get(name))
        coefficient = _number(model.coefficient_by_feature.get(name))
        if center is None or scale is None or scale <= 0 or coefficient is None:
            return None
        logit += coefficient * (value - center) / scale
    if logit >= 0:
        exponential = np.exp(-logit)
        return float(1.0 / (1.0 + exponential))
    exponential = np.exp(logit)
    return float(exponential / (1.0 + exponential))


def _market_event_features(
    rows: Sequence[Mapping[str, object]],
    *,
    date_text: str,
    signal_time: str,
    first_seen: Mapping[tuple[str, str], str],
    previous_market: Mapping[str, tuple[str, dict[str, float]]],
) -> dict[str, float]:
    symbols = {str(row.get("vt_symbol") or "") for row in rows}
    new_symbols = {
        symbol for symbol in symbols if (date_text, symbol) not in first_seen
    }
    first_times = {
        symbol: first_time
        for (seen_date, symbol), first_time in first_seen.items()
        if seen_date == date_text
    }
    first_times.update({symbol: signal_time for symbol in new_symbols})
    recent_new = sum(
        0.0 <= _minute_distance(first_time, signal_time) <= 2.0
        for first_time in first_times.values()
    )
    gains = [_feature_value(row, "gain_pct") or 0.0 for row in rows]
    return_1m = [_feature_value(row, "return_1m_pct") or 0.0 for row in rows]
    return_3m = [_feature_value(row, "return_3m_pct") or 0.0 for row in rows]
    tx_imbalance = [
        _transaction_value(row, "tx_price_move_turnover_imbalance_1m") or 0.0
        for row in rows
    ]
    tx_acceleration = [
        _transaction_value(row, "tx_trade_count_acceleration_1m_5m") or 0.0
        for row in rows
    ]
    positive_1m_ratio = _ratio(sum(value > 0 for value in return_1m), len(rows))
    previous = previous_market.get(date_text)
    consecutive_previous = (
        previous is not None
        and _minute_distance(previous[0], signal_time) == 1.0
    )
    previous_features = previous[1] if consecutive_previous and previous else {}
    current_count = float(len(rows))
    features = {
        "event_active_candidate_count_log1p": log1p(current_count),
        "event_new_candidate_count_1m_log1p": log1p(len(new_symbols)),
        "event_new_candidate_count_3m_log1p": log1p(recent_new),
        "event_near_limit_candidate_count_log1p": log1p(
            sum(value >= 8.0 for value in gains)
        ),
        "event_gain_max_pct": max(gains),
        "event_gain_p75_pct": _quantile(gains, 0.75),
        "event_positive_return_1m_ratio": positive_1m_ratio,
        "event_positive_return_3m_ratio": _ratio(
            sum(value > 0 for value in return_3m),
            len(rows),
        ),
        "event_tx_price_imbalance_mean_1m": mean(tx_imbalance),
        "event_tx_trade_acceleration_mean_1m_5m": mean(tx_acceleration),
        "event_active_candidate_count_delta_1m": current_count
        - _previous_active_count(previous_features),
        "event_positive_return_1m_ratio_delta_1m": positive_1m_ratio
        - float(previous_features.get("event_positive_return_1m_ratio") or 0.0),
    }
    return {name: float(features[name]) for name in MARKET_EVENT_FEATURE_NAMES}


def _candidate_event_features(
    row: Mapping[str, object],
    *,
    signal_time: str,
    first_time: str,
    visible_times: Sequence[str],
    previous: Mapping[str, object] | None,
) -> dict[str, float]:
    previous_time = str(previous.get("signal_time") or "") if previous else ""
    consecutive = bool(
        previous_time and _minute_distance(previous_time, signal_time) == 1.0
    )
    prior = previous if consecutive else {}
    features = {
        "event_candidate_age_minutes_log1p": log1p(
            max(_minute_distance(first_time, signal_time), 0.0)
        ),
        "event_candidate_visible_count_3m": float(
            sum(
                0.0 <= _minute_distance(value, signal_time) <= 2.0
                for value in visible_times
            )
        ),
        "event_gain_strength_delta_1m": _competing_value(row, "gain_strength_pct")
        - _competing_value(prior, "gain_strength_pct"),
        "event_rank_strength_delta_1m": _competing_value(row, "rank_strength_pct")
        - _competing_value(prior, "rank_strength_pct"),
        "event_tx_price_imbalance_delta_1m": _transaction_value(
            row,
            "tx_price_move_turnover_imbalance_1m",
        )
        - _transaction_value(prior, "tx_price_move_turnover_imbalance_1m"),
    }
    return {name: float(features[name]) for name in CANDIDATE_EVENT_FEATURE_NAMES}


def _event_market_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> list[tuple[list[float], int, tuple[str, str]]]:
    groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if _as_date(row.get("signal_date")) in allowed_dates:
            groups[_minute_key(row)].append(row)
    prepared: list[tuple[list[float], int, tuple[str, str]]] = []
    for key in sorted(groups):
        group = groups[key]
        vector = next(
            (
                value
                for row in group
                if (value := event_market_feature_vector(row)) is not None
            ),
            None,
        )
        if vector is None:
            continue
        prepared.append(
            (
                vector,
                int(any(row.get(TOUCH_TARGET_FIELD) is True for row in group)),
                key,
            )
        )
    return prepared


def _attach_candidate_ranks(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    result = [dict(row) for row in rows]
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(result):
        groups[_minute_key(row)].append(index)
    for indices in groups.values():
        ordered = sorted(indices, key=lambda index: _action_ranking_key(result[index]))
        for rank, index in enumerate(ordered, start=1):
            result[index][EVENT_CANDIDATE_RANK_FIELD] = rank
    return result


def _threshold_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    reachable_pairs: set[tuple[str, str]],
) -> dict[str, float | int | None]:
    selected = select_event_risk_signals(rows, threshold=threshold)
    selected_pairs = {_row_pair(row) for row in selected}
    true_pairs = {
        _row_pair(row)
        for row in selected
        if row.get(TOUCH_TARGET_FIELD) is True
    }
    return {
        "threshold": round(float(threshold), 4),
        "selection_count": len(selected_pairs),
        "touch_true_positive_count": len(true_pairs),
        "touch_precision": _optional_ratio(len(true_pairs), len(selected_pairs)),
        "reachable_recall": _optional_ratio(len(true_pairs), len(reachable_pairs)),
    }


def _scoreable_candidate(row: Mapping[str, object]) -> bool:
    gain = _feature_value(row, "gain_pct")
    return bool(
        row.get("shared_strategy_passed") is True
        and row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= 3.0
        and transaction_trigger_feature_vector(row) is not None
    )


def _action_ranking_key(
    row: Mapping[str, object],
) -> tuple[float, float, str]:
    return (
        -(_number(row.get(EVENT_RANK_SCORE_FIELD)) or 0.0),
        -(_number(row.get("rank_score")) or 0.0),
        str(row.get("vt_symbol") or ""),
    )


def _row_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    date_text, signal_time = _minute_key(row)
    return date_text, signal_time, str(row.get("vt_symbol") or "")


def _symbol_sort_key(row: Mapping[str, object]) -> str:
    return str(row.get("vt_symbol") or "")


def _minute_key(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("signal_date") or row.get("trade_date") or "")[:10],
        str(row.get("signal_time") or "")[:8],
    )


def _row_identity(row: Mapping[str, object]) -> tuple[str, str, str]:
    date_text, signal_time = _minute_key(row)
    return str(row.get("vt_symbol") or ""), date_text, signal_time


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("vt_symbol") or ""),
        str(row.get("signal_date") or row.get("trade_date") or "")[:10],
    )


def _feature_value(row: Mapping[str, object], field: str) -> float | None:
    if field in row:
        return _number(row.get(field))
    features = row.get("features")
    return _number(features.get(field)) if isinstance(features, Mapping) else None


def _competing_value(row: Mapping[str, object], field: str) -> float:
    features = row.get("competing_features")
    value = _number(features.get(field)) if isinstance(features, Mapping) else None
    return value if value is not None else 0.0


def _transaction_value(row: Mapping[str, object], field: str) -> float:
    features = row.get("transaction_features")
    value = _number(features.get(field)) if isinstance(features, Mapping) else None
    return value if value is not None else 0.0


def _previous_active_count(features: Mapping[str, object]) -> float:
    encoded = _number(features.get("event_active_candidate_count_log1p"))
    return float(np.expm1(encoded)) if encoded is not None else 0.0


def _minute_distance(start: object, end: object) -> float:
    value = trading_minutes_between(start, end)
    return float(value) if value is not None else 1_000.0


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.quantile(np.asarray(values, dtype=float), q, method="linear"))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _optional_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _as_date(value: object) -> date | None:
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
    return parsed if isfinite(parsed) else None


def _class_counts(labels: np.ndarray) -> dict[str, int]:
    return {
        str(label): int(count)
        for label, count in sorted(Counter(labels.tolist()).items())
    }


def _feature_mapping(
    names: Sequence[str],
    values: Sequence[object],
) -> dict[str, float]:
    return {
        name: _canonical_float(value)
        for name, value in zip(names, values, strict=True)
    }


def _canonical_float(value: object) -> float:
    rounded = round(float(value), 10)
    return 0.0 if rounded == 0.0 else rounded


def _stable_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("ascii")
    return f"sha256:{sha256(encoded).hexdigest()}"
