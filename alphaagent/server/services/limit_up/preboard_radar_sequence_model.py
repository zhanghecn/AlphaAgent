"""Shared causal rows and sequence features for the pre-board radar."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from math import isfinite, log1p
from typing import Any

import numpy as np

from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.preboard_reverse_profile import (
    trading_minutes_between,
)


MODEL_VERSION = "limit-up-preboard-radar-sequence-v8"
CANONICAL_CONTRACT_VERSION = "preboard-radar-canonical-row-v1"
MINIMUM_GAIN_PCT = 3.0
MINIMUM_SUPPORT_SCORE = 55.0
MINIMUM_HISTORY_SAMPLE_COUNT = 5
MINIMUM_HISTORICAL_COMBINED_RATE = 30.0
MAXIMUM_LIVE_QUOTE_AGE_SECONDS = 60.0
NEAR_LIMIT_GAIN_PCT = 8.0
TOUCH_TARGET_FIELD = "formal_touch_within_3m"
CANDIDATE_SCORE_FIELD = "candidate_touch_3m_probability"
ACTION_SCORE_FIELD = "top1_touch_3m_probability"
MINIMUM_OOF_SEED_DATES = 20
OOF_BLOCK_SIZE = 5
MAXIMUM_DAILY_ACTIONS = 2
MINIMUM_CALIBRATION_ACTIONS = 10
MINIMUM_CALIBRATION_PRECISION = 0.70
DEFAULT_ACTION_THRESHOLDS = tuple(round(value / 100, 2) for value in range(5, 100, 5))
CANDIDATE_MODEL_PARAMETERS: dict[str, object] = {
    "objective": "binary",
    "n_estimators": 120,
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

CANONICAL_ROW_FIELDS = (
    "signal_date",
    "signal_time",
    "vt_symbol",
    "gain_pct",
    "rank_score",
    "history_sample_count",
    "historical_combined_rate",
    "support_score",
    "entry_quality_score",
    "shared_strategy_passed",
    "before_first_limit_touch",
)

FIRST_LAYER_FEATURE_NAMES = (
    "candidate_gain_pct",
    "candidate_rank_score",
    "candidate_history_sample_count_log1p",
    "candidate_historical_combined_rate",
    "candidate_gain_strength_pct",
    "candidate_rank_strength_pct",
    "candidate_age_minutes_log1p",
    "candidate_visible_count_3m",
    "candidate_gain_delta_1m",
    "candidate_gain_delta_3m",
    "candidate_rank_delta_1m",
    "candidate_rank_delta_3m",
    "market_active_candidate_count_log1p",
    "market_new_candidate_count_1m_log1p",
    "market_near_limit_candidate_count_log1p",
    "market_gain_max_pct",
    "market_gain_p75_pct",
    "market_upward_momentum_ratio_1m",
    "market_active_candidate_count_delta_1m",
    "market_upward_momentum_ratio_delta_1m",
)
SECOND_LAYER_FEATURE_NAMES = (
    *FIRST_LAYER_FEATURE_NAMES,
    "first_layer_touch_probability",
    "first_layer_top1_margin",
    "first_layer_candidate_count_log1p",
)


@dataclass(frozen=True)
class CandidateTouchModelFit:
    status: str
    model: Any | None
    training_row_count: int
    training_date_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    parameters: dict[str, object]
    feature_importance_by_name: dict[str, float]
    booster_model_text: str | None
    fingerprint: str | None


@dataclass(frozen=True)
class Top1ActionModelFit:
    status: str
    pipeline: Any | None
    training_row_count: int
    training_date_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    scaler_mean_by_feature: dict[str, float]
    scaler_scale_by_feature: dict[str, float]
    coefficient_by_feature: dict[str, float]
    intercept: float | None
    fingerprint: str | None


@dataclass(frozen=True)
class RadarActionThresholdSelection:
    status: str
    threshold: float | None
    calibration_dates: tuple[str, ...]
    minimum_action_count: int
    minimum_precision: float
    selected_metrics: dict[str, float | int | None]
    metrics_by_threshold: tuple[dict[str, float | int | None], ...]


def canonical_contract_fingerprint() -> str:
    payload = {
        "contract_version": CANONICAL_CONTRACT_VERSION,
        "canonical_fields": CANONICAL_ROW_FIELDS,
        "first_layer_features": FIRST_LAYER_FEATURE_NAMES,
        "eligibility": {
            "minimum_gain_pct": MINIMUM_GAIN_PCT,
            "minimum_support_score": MINIMUM_SUPPORT_SCORE,
            "minimum_history_sample_count": MINIMUM_HISTORY_SAMPLE_COUNT,
            "minimum_historical_combined_rate": MINIMUM_HISTORICAL_COMBINED_RATE,
            "maximum_live_quote_age_seconds": MAXIMUM_LIVE_QUOTE_AGE_SECONDS,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def canonicalize_historical_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Project reconstructed completed-minute rows into the shared contract."""

    return _canonicalize_rows(rows, live=False)


def canonicalize_live_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    maximum_quote_age_seconds: float = MAXIMUM_LIVE_QUOTE_AGE_SECONDS,
) -> list[dict[str, object]]:
    """Project fresh saved radar observations into the same shared contract."""

    return _canonicalize_rows(
        rows,
        live=True,
        maximum_quote_age_seconds=maximum_quote_age_seconds,
    )


def enrich_radar_sequence_features(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach deterministic current-and-past-only candidate and market features."""

    canonical = canonicalize_historical_rows(rows)
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in canonical:
        groups[(str(row["signal_date"]), str(row["signal_time"]))].append(row)

    first_seen: dict[tuple[str, str], str] = {}
    history: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    previous_market: dict[str, tuple[str, dict[str, float]]] = {}
    enriched: list[dict[str, object]] = []

    for minute_key in sorted(groups):
        date_text, signal_time = minute_key
        minute_rows = sorted(groups[minute_key], key=lambda row: str(row["vt_symbol"]))
        gain_strengths = _strength_percentiles(minute_rows, "gain_pct")
        rank_strengths = _strength_percentiles(minute_rows, "rank_score")
        candidate_rows: list[dict[str, object]] = []
        candidate_features: list[dict[str, float]] = []

        for row, gain_strength, rank_strength in zip(
            minute_rows,
            gain_strengths,
            rank_strengths,
            strict=True,
        ):
            symbol = str(row["vt_symbol"])
            pair = (date_text, symbol)
            first_time = first_seen.setdefault(pair, signal_time)
            prior_rows = history[pair]
            prior_1m = _prior_at_distance(prior_rows, signal_time, 1)
            prior_3m = _prior_at_distance(prior_rows, signal_time, 3)
            age = _minute_distance(first_time, signal_time) or 0.0
            visible_count = 1 + sum(
                distance is not None and 0.0 < distance <= 2.0
                for prior in prior_rows
                if (distance := _minute_distance(prior["signal_time"], signal_time))
                is not None
            )
            features = {
                "candidate_gain_pct": float(row["gain_pct"]),
                "candidate_rank_score": float(row["rank_score"]),
                "candidate_history_sample_count_log1p": log1p(
                    float(row["history_sample_count"])
                ),
                "candidate_historical_combined_rate": float(
                    row["historical_combined_rate"]
                ),
                "candidate_gain_strength_pct": float(gain_strength),
                "candidate_rank_strength_pct": float(rank_strength),
                "candidate_age_minutes_log1p": log1p(max(age, 0.0)),
                "candidate_visible_count_3m": float(visible_count),
                "candidate_gain_delta_1m": _delta(row, prior_1m, "gain_pct"),
                "candidate_gain_delta_3m": _delta(row, prior_3m, "gain_pct"),
                "candidate_rank_delta_1m": _delta(row, prior_1m, "rank_score"),
                "candidate_rank_delta_3m": _delta(row, prior_3m, "rank_score"),
            }
            candidate_rows.append(row)
            candidate_features.append(features)
            history[pair].append(row)

        market = _market_features(
            candidate_rows,
            candidate_features,
            date_text=date_text,
            signal_time=signal_time,
            first_seen=first_seen,
            previous_market=previous_market,
        )
        for row, features in zip(candidate_rows, candidate_features, strict=True):
            enriched.append(
                {
                    **row,
                    "canonical_contract_version": CANONICAL_CONTRACT_VERSION,
                    "canonical_contract_fingerprint": canonical_contract_fingerprint(),
                    "sequence_features": {
                        name: _canonical_float((features | market)[name])
                        for name in FIRST_LAYER_FEATURE_NAMES
                    },
                }
            )
        previous_market[date_text] = (signal_time, market)
    return enriched


def candidate_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    features = row.get("sequence_features")
    if not isinstance(features, Mapping):
        return None
    values = [_number(features.get(name)) for name in FIRST_LAYER_FEATURE_NAMES]
    if any(value is None for value in values):
        return None
    return [float(value) for value in values if value is not None]


def candidate_touch_training_batch(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    tuple[tuple[str, str, str], ...],
]:
    prepared: list[tuple[list[float], int, tuple[str, str, str]]] = []
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        vector = candidate_feature_vector(row)
        if signal_date not in allowed_dates or vector is None:
            continue
        prepared.append(
            (
                vector,
                int(row.get(TOUCH_TARGET_FIELD) is True),
                _row_identity(row),
            )
        )
    prepared.sort(key=lambda item: item[2])
    matrix = (
        np.asarray([vector for vector, _, _ in prepared], dtype=float)
        if prepared
        else np.empty((0, len(FIRST_LAYER_FEATURE_NAMES)), dtype=float)
    )
    labels = np.asarray([label for _, label, _ in prepared], dtype=int)
    keys = tuple(key for _, _, key in prepared)
    weights = _date_equal_class_balanced_weights(labels, keys)
    return matrix, labels, weights, keys


def fit_candidate_touch_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
) -> CandidateTouchModelFit:
    matrix, labels, weights, _ = candidate_touch_training_batch(
        rows,
        allowed_dates=fit_dates,
    )
    date_texts = tuple(value.isoformat() for value in sorted(fit_dates))
    common = {
        "training_row_count": len(labels),
        "training_date_count": len(fit_dates),
        "class_counts": _class_counts(labels),
        "fit_dates": date_texts,
        "parameters": dict(CANDIDATE_MODEL_PARAMETERS),
    }
    if len(labels) < 2 or len(set(labels.tolist())) < 2:
        return CandidateTouchModelFit(
            status="insufficient_training_classes",
            model=None,
            feature_importance_by_name={},
            booster_model_text=None,
            fingerprint=None,
            **common,
        )

    import pandas as pd
    from lightgbm import LGBMClassifier

    model = LGBMClassifier(**CANDIDATE_MODEL_PARAMETERS)
    frame = pd.DataFrame(matrix, columns=FIRST_LAYER_FEATURE_NAMES)
    model.fit(frame, labels, sample_weight=weights)
    booster_text = str(model.booster_.model_to_string())
    importance = {
        name: _canonical_float(value)
        for name, value in zip(
            FIRST_LAYER_FEATURE_NAMES,
            model.booster_.feature_importance(importance_type="gain"),
            strict=True,
        )
    }
    fingerprint = _stable_fingerprint(
        {
            "model": "lightgbm_binary_classifier",
            "canonical_contract_fingerprint": canonical_contract_fingerprint(),
            "features": FIRST_LAYER_FEATURE_NAMES,
            "fit_dates": date_texts,
            "parameters": CANDIDATE_MODEL_PARAMETERS,
            "booster_sha256": sha256(booster_text.encode()).hexdigest(),
        }
    )
    return CandidateTouchModelFit(
        status="ready",
        model=model,
        feature_importance_by_name=importance,
        booster_model_text=booster_text,
        fingerprint=fingerprint,
        **common,
    )


def score_candidate_touch_rows(
    rows: Sequence[Mapping[str, object]],
    model: CandidateTouchModelFit,
) -> list[dict[str, object]]:
    if model.status != "ready" or model.model is None:
        return []
    prepared = [
        (dict(row), vector)
        for row in rows
        if (vector := candidate_feature_vector(row)) is not None
    ]
    if not prepared:
        return []
    import pandas as pd

    matrix = pd.DataFrame(
        [vector for _, vector in prepared],
        columns=FIRST_LAYER_FEATURE_NAMES,
    )
    probabilities = model.model.predict_proba(matrix)[:, 1]
    return [
        {
            **row,
            CANDIDATE_SCORE_FIELD: _canonical_float(probability),
            "candidate_model_fingerprint": model.fingerprint,
        }
        for (row, _), probability in zip(prepared, probabilities, strict=True)
    ]


def select_minute_top1(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for raw in rows:
        if _number(raw.get(CANDIDATE_SCORE_FIELD)) is None:
            continue
        row = dict(raw)
        groups[_minute_key(row)].append(row)
    selected: list[dict[str, object]] = []
    for key in sorted(groups):
        ranked = sorted(groups[key], key=_candidate_ranking_key)
        top = ranked[0]
        top_score = float(top[CANDIDATE_SCORE_FIELD])
        second_score = (
            float(ranked[1][CANDIDATE_SCORE_FIELD]) if len(ranked) > 1 else 0.0
        )
        selected.append(
            {
                **top,
                "candidate_rank": 1,
                "candidate_count": len(ranked),
                "candidate_top1_score_margin": _canonical_float(
                    top_score - second_score
                ),
            }
        )
    return selected


def build_expanding_oof_top1(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
    minimum_seed_dates: int = MINIMUM_OOF_SEED_DATES,
    block_size: int = OOF_BLOCK_SIZE,
) -> list[dict[str, object]]:
    ordered_dates = tuple(sorted(fit_dates))
    seed_count = max(int(minimum_seed_dates), 2)
    step = max(int(block_size), 1)
    if len(ordered_dates) <= seed_count:
        return []
    oof_rows: list[dict[str, object]] = []
    for block_start in range(seed_count, len(ordered_dates), step):
        training_dates = set(ordered_dates[:block_start])
        scoring_dates = set(ordered_dates[block_start : block_start + step])
        model = fit_candidate_touch_model(rows, fit_dates=training_dates)
        if model.status != "ready":
            return []
        scoring_rows = [
            row
            for row in rows
            if _as_date(row.get("signal_date")) in scoring_dates
        ]
        top1 = select_minute_top1(score_candidate_touch_rows(scoring_rows, model))
        for row in top1:
            oof_rows.append(
                {
                    **row,
                    "oof_training_date_start": ordered_dates[0].isoformat(),
                    "oof_training_date_end": ordered_dates[block_start - 1].isoformat(),
                    "oof_scoring_block_start": min(scoring_dates).isoformat(),
                    "oof_scoring_block_end": max(scoring_dates).isoformat(),
                    "oof_candidate_model_fingerprint": model.fingerprint,
                }
            )
    return sorted(oof_rows, key=_row_sort_key)


def action_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    candidate = candidate_feature_vector(row)
    probability = _number(row.get(CANDIDATE_SCORE_FIELD))
    margin = _number(row.get("candidate_top1_score_margin"))
    candidate_count = _number(row.get("candidate_count"))
    if (
        candidate is None
        or probability is None
        or margin is None
        or candidate_count is None
        or candidate_count < 1
    ):
        return None
    return [
        *candidate,
        probability,
        margin,
        log1p(candidate_count),
    ]


def build_top1_action_training_batch(
    rows: Sequence[Mapping[str, object]],
) -> tuple[np.ndarray, np.ndarray, tuple[tuple[str, str, str], ...]]:
    prepared: list[tuple[list[float], int, tuple[str, str, str]]] = []
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        training_end = _as_date(row.get("oof_training_date_end"))
        model_fingerprint = str(
            row.get("oof_candidate_model_fingerprint") or ""
        ).strip()
        vector = action_feature_vector(row)
        if (
            vector is None
            or signal_date is None
            or training_end is None
            or training_end >= signal_date
            or not model_fingerprint
        ):
            continue
        prepared.append(
            (
                vector,
                int(row.get(TOUCH_TARGET_FIELD) is True),
                _row_identity(row),
            )
        )
    prepared.sort(key=lambda item: item[2])
    matrix = (
        np.asarray([vector for vector, _, _ in prepared], dtype=float)
        if prepared
        else np.empty((0, len(SECOND_LAYER_FEATURE_NAMES)), dtype=float)
    )
    labels = np.asarray([label for _, label, _ in prepared], dtype=int)
    keys = tuple(key for _, _, key in prepared)
    return matrix, labels, keys


def fit_top1_action_model(
    oof_top1_rows: Sequence[Mapping[str, object]],
) -> Top1ActionModelFit:
    matrix, labels, keys = build_top1_action_training_batch(oof_top1_rows)
    fit_dates = tuple(sorted({key[0] for key in keys}))
    common = {
        "training_row_count": len(labels),
        "training_date_count": len(fit_dates),
        "class_counts": _class_counts(labels),
        "fit_dates": fit_dates,
    }
    if len(labels) < 2 or len(set(labels.tolist())) < 2:
        return Top1ActionModelFit(
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
    pipeline.fit(matrix, labels)
    scaler = pipeline.named_steps["scaler"]
    logistic = pipeline.named_steps["logistic"]
    means = _feature_mapping(SECOND_LAYER_FEATURE_NAMES, scaler.mean_)
    scales = _feature_mapping(SECOND_LAYER_FEATURE_NAMES, scaler.scale_)
    coefficients = _feature_mapping(
        SECOND_LAYER_FEATURE_NAMES,
        logistic.coef_[0],
    )
    intercept = _canonical_float(logistic.intercept_[0])
    fingerprint = _stable_fingerprint(
        {
            "model": "standard_scaler_logistic_regression",
            "canonical_contract_fingerprint": canonical_contract_fingerprint(),
            "features": SECOND_LAYER_FEATURE_NAMES,
            "fit_dates": fit_dates,
            "oof_candidate_model_fingerprints": sorted(
                {
                    str(row.get("oof_candidate_model_fingerprint") or "")
                    for row in oof_top1_rows
                }
            ),
            "means": means,
            "scales": scales,
            "coefficients": coefficients,
            "intercept": intercept,
        }
    )
    return Top1ActionModelFit(
        status="ready",
        pipeline=pipeline,
        scaler_mean_by_feature=means,
        scaler_scale_by_feature=scales,
        coefficient_by_feature=coefficients,
        intercept=intercept,
        fingerprint=fingerprint,
        **common,
    )


def score_top1_action_rows(
    rows: Sequence[Mapping[str, object]],
    model: Top1ActionModelFit,
) -> list[dict[str, object]]:
    if model.status != "ready" or model.pipeline is None:
        return []
    prepared = [
        (dict(row), vector)
        for row in rows
        if (vector := action_feature_vector(row)) is not None
    ]
    if not prepared:
        return []
    matrix = np.asarray([vector for _, vector in prepared], dtype=float)
    probabilities = model.pipeline.predict_proba(matrix)[:, 1]
    return [
        {
            **row,
            ACTION_SCORE_FIELD: _canonical_float(probability),
            "action_model_fingerprint": model.fingerprint,
        }
        for (row, _), probability in zip(prepared, probabilities, strict=True)
    ]


def select_radar_actions(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    max_daily_actions: int = MAXIMUM_DAILY_ACTIONS,
) -> list[dict[str, object]]:
    selected_pairs: set[tuple[str, str]] = set()
    daily_counts: Counter[str] = Counter()
    selected: list[dict[str, object]] = []
    for raw in sorted(rows, key=_row_sort_key):
        row = dict(raw)
        score = _number(row.get(ACTION_SCORE_FIELD))
        date_text = str(row.get("signal_date") or "")[:10]
        pair = (date_text, str(row.get("vt_symbol") or ""))
        if (
            score is None
            or score < float(threshold)
            or pair in selected_pairs
            or daily_counts[date_text] >= max(int(max_daily_actions), 1)
        ):
            continue
        selected_pairs.add(pair)
        daily_counts[date_text] += 1
        selected.append(row)
    return selected


def calibrate_radar_action_threshold(
    rows: Sequence[Mapping[str, object]],
    *,
    calibration_dates: set[date],
    thresholds: Sequence[float] = DEFAULT_ACTION_THRESHOLDS,
    minimum_action_count: int = MINIMUM_CALIBRATION_ACTIONS,
    minimum_precision: float = MINIMUM_CALIBRATION_PRECISION,
) -> RadarActionThresholdSelection:
    calibration_rows = [
        dict(row)
        for row in rows
        if _as_date(row.get("signal_date")) in calibration_dates
    ]
    reachable_pairs = {
        _row_pair(row)
        for row in calibration_rows
        if row.get(TOUCH_TARGET_FIELD) is True
    }
    metrics = tuple(
        _action_threshold_metrics(
            calibration_rows,
            threshold=float(threshold),
            reachable_pairs=reachable_pairs,
        )
        for threshold in thresholds
    )
    supported = [
        row
        for row in metrics
        if int(row["selection_count"] or 0) >= max(int(minimum_action_count), 1)
    ]
    qualified = [
        row
        for row in supported
        if float(row["precision"] or 0.0) >= float(minimum_precision)
    ]
    selected = max(
        qualified,
        key=lambda row: (
            float(row["reachable_recall"] or 0.0),
            float(row["precision"] or 0.0),
            float(row["threshold"] or 0.0),
        ),
        default=None,
    )
    status = (
        "ready"
        if selected is not None
        else "calibration_precision_gate_failed"
        if supported
        else "insufficient_calibration_actions"
    )
    return RadarActionThresholdSelection(
        status=status,
        threshold=float(selected["threshold"]) if selected is not None else None,
        calibration_dates=tuple(
            value.isoformat() for value in sorted(calibration_dates)
        ),
        minimum_action_count=max(int(minimum_action_count), 1),
        minimum_precision=float(minimum_precision),
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def _canonicalize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    live: bool,
    maximum_quote_age_seconds: float = MAXIMUM_LIVE_QUOTE_AGE_SECONDS,
) -> list[dict[str, object]]:
    ordered = sorted((dict(row) for row in rows), key=_raw_sort_key)
    projected: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in ordered:
        canonical = _project_canonical_row(
            row,
            live=live,
            maximum_quote_age_seconds=maximum_quote_age_seconds,
        )
        if canonical is None:
            continue
        key = (
            str(canonical["signal_date"]),
            str(canonical["signal_time"]),
            str(canonical["vt_symbol"]),
        )
        projected.setdefault(key, canonical)
    return [projected[key] for key in sorted(projected)]


def _project_canonical_row(
    row: Mapping[str, object],
    *,
    live: bool,
    maximum_quote_age_seconds: float,
) -> dict[str, object] | None:
    signal_date = _as_date(row.get("signal_date") or row.get("trade_date"))
    signal_time = _signal_time(row)
    symbol = str(row.get("vt_symbol") or "").strip()
    if signal_date is None or signal_time is None or not symbol:
        return None
    if live and not _is_fresh_live_row(
        row,
        signal_date=signal_date,
        signal_time=signal_time,
        maximum_quote_age_seconds=maximum_quote_age_seconds,
    ):
        return None

    lane = str(row.get("board_lane") or row.get("lane") or "")
    if (live and lane != "first_board") or (lane and lane != "first_board"):
        return None
    if str(row.get("capture_state") or "") == "fill_followup":
        return None
    if str(row.get("blocking_scope") or "none") != "none":
        return None
    if _blockers(row):
        return None

    gain = _feature_number(row, "gain_pct")
    rank = _feature_number(row, "rank_score")
    support = _feature_number(row, "support_score")
    entry_quality = _feature_number(row, "entry_quality_score")
    samples = _first_number(
        row,
        "history_sample_count",
        "profitability_gate_sample_count",
        "stock_d1_sample_count",
    )
    combined_rate = _first_number(
        row,
        "historical_combined_rate",
        "profitability_gate_combined_rate",
        "stock_gene_combined_win_rate",
    )
    if not (
        row.get("shared_strategy_passed") is True
        and row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= MINIMUM_GAIN_PCT
        and rank is not None
        and support is not None
        and support >= MINIMUM_SUPPORT_SCORE
        and entry_quality is not None
        and samples is not None
        and samples >= MINIMUM_HISTORY_SAMPLE_COUNT
        and combined_rate is not None
        and combined_rate >= MINIMUM_HISTORICAL_COMBINED_RATE
    ):
        return None
    return {
        "signal_date": signal_date.isoformat(),
        "signal_time": signal_time,
        "vt_symbol": symbol,
        "gain_pct": _canonical_float(gain),
        "rank_score": _canonical_float(rank),
        "history_sample_count": _canonical_float(samples),
        "historical_combined_rate": _canonical_float(combined_rate),
        "support_score": _canonical_float(support),
        "entry_quality_score": _canonical_float(entry_quality),
        "shared_strategy_passed": True,
        "before_first_limit_touch": True,
    }


def _is_fresh_live_row(
    row: Mapping[str, object],
    *,
    signal_date: date,
    signal_time: str,
    maximum_quote_age_seconds: float,
) -> bool:
    if row.get("frame_is_stale", row.get("is_stale")) is not False:
        return False
    if _as_date(row.get("source_trade_date")) != signal_date:
        return False
    captured_at = _as_datetime(row.get("captured_at"))
    quote_at = _as_datetime(row.get("quote_observed_at"))
    if captured_at is None or quote_at is None:
        return False
    local_captured_at = _local_datetime(captured_at)
    if local_captured_at.date() != signal_date:
        return False
    try:
        age_seconds = (captured_at - quote_at).total_seconds()
    except TypeError:
        return False
    if not 0 <= age_seconds <= max(float(maximum_quote_age_seconds), 0.0):
        return False
    return local_captured_at.strftime("%H:%M") == signal_time


def _market_features(
    rows: Sequence[Mapping[str, object]],
    candidate_features: Sequence[Mapping[str, float]],
    *,
    date_text: str,
    signal_time: str,
    first_seen: Mapping[tuple[str, str], str],
    previous_market: Mapping[str, tuple[str, dict[str, float]]],
) -> dict[str, float]:
    gains = [float(row["gain_pct"]) for row in rows]
    active_count = float(len(rows))
    new_count = float(
        sum(
            first_seen.get((date_text, str(row["vt_symbol"]))) == signal_time
            for row in rows
        )
    )
    upward_ratio = (
        sum(float(features["candidate_gain_delta_1m"]) > 0 for features in candidate_features)
        / len(candidate_features)
        if candidate_features
        else 0.0
    )
    previous = previous_market.get(date_text)
    previous_values: Mapping[str, float] = {}
    if (
        previous is not None
        and _minute_distance(previous[0], signal_time) == 1.0
    ):
        previous_values = previous[1]
    previous_active = float(
        previous_values.get("market_active_candidate_count", 0.0)
    )
    previous_upward = float(
        previous_values.get("market_upward_momentum_ratio_1m", 0.0)
    )
    return {
        "market_active_candidate_count": active_count,
        "market_active_candidate_count_log1p": log1p(active_count),
        "market_new_candidate_count_1m_log1p": log1p(new_count),
        "market_near_limit_candidate_count_log1p": log1p(
            sum(value >= NEAR_LIMIT_GAIN_PCT for value in gains)
        ),
        "market_gain_max_pct": max(gains),
        "market_gain_p75_pct": _quantile(gains, 0.75),
        "market_upward_momentum_ratio_1m": upward_ratio,
        "market_active_candidate_count_delta_1m": active_count - previous_active,
        "market_upward_momentum_ratio_delta_1m": upward_ratio - previous_upward,
    }


def _strength_percentiles(
    rows: Sequence[Mapping[str, object]],
    field: str,
) -> list[float]:
    values = [float(row[field]) for row in rows]
    ordered = sorted(values)
    return [sum(candidate <= value for candidate in ordered) / len(ordered) for value in values]


def _prior_at_distance(
    rows: Sequence[Mapping[str, object]],
    signal_time: str,
    distance: int,
) -> Mapping[str, object] | None:
    for row in reversed(rows):
        elapsed = _minute_distance(row.get("signal_time"), signal_time)
        if elapsed == float(distance):
            return row
        if elapsed is not None and elapsed > distance:
            break
    return None


def _delta(
    current: Mapping[str, object],
    previous: Mapping[str, object] | None,
    field: str,
) -> float:
    current_value = _number(current.get(field)) or 0.0
    previous_value = _number(previous.get(field)) if previous else None
    return current_value - (previous_value if previous_value is not None else current_value)


def _minute_distance(start: object, end: object) -> float | None:
    value = trading_minutes_between(start, end)
    return float(value) if value is not None else None


def _signal_time(row: Mapping[str, object]) -> str | None:
    signal_at = _as_datetime(row.get("signal_at"))
    if signal_at is not None:
        return _local_datetime(signal_at).strftime("%H:%M")
    value = str(row.get("signal_time") or "").strip()
    if len(value) >= 5 and value[2] == ":":
        return value[:5]
    return None


def _blockers(row: Mapping[str, object]) -> list[str]:
    result: list[str] = []
    for field in ("blocker_codes", "shared_lane_blockers", "lane_blockers"):
        values = row.get(field)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            continue
        result.extend(str(value) for value in values if str(value).strip())
    return result


def _first_number(row: Mapping[str, object], *fields: str) -> float | None:
    for field in fields:
        value = _feature_number(row, field)
        if value is not None:
            return value
    return None


def _feature_number(row: Mapping[str, object], field: str) -> float | None:
    direct = _number(row.get(field))
    if direct is not None:
        return direct
    for container_name in ("features", "ignition_features", "competing_features"):
        container = row.get(container_name)
        if isinstance(container, Mapping):
            value = _number(container.get(field))
            if value is not None:
                return value
    return None


def _raw_sort_key(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    signal_date = _as_date(row.get("signal_date") or row.get("trade_date"))
    return (
        signal_date.isoformat() if signal_date else "",
        _signal_time(row) or "",
        str(row.get("vt_symbol") or ""),
        str(row.get("captured_at") or ""),
    )


def _row_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return _row_identity(row)


def _row_identity(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("signal_date") or row.get("trade_date") or "")[:10],
        str(row.get("signal_time") or "")[:5],
        str(row.get("vt_symbol") or ""),
    )


def _minute_key(row: Mapping[str, object]) -> tuple[str, str]:
    identity = _row_identity(row)
    return identity[0], identity[1]


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    identity = _row_identity(row)
    return identity[0], identity[2]


def _candidate_ranking_key(row: Mapping[str, object]) -> tuple[float, float, str]:
    return (
        -float(row[CANDIDATE_SCORE_FIELD]),
        -(_number(row.get("rank_score")) or 0.0),
        str(row.get("vt_symbol") or ""),
    )


def _date_equal_class_balanced_weights(
    labels: np.ndarray,
    keys: Sequence[tuple[str, str, str]],
) -> np.ndarray:
    if len(labels) == 0:
        return np.asarray([], dtype=float)
    date_counts = Counter(key[0] for key in keys)
    weights = np.asarray([1.0 / date_counts[key[0]] for key in keys], dtype=float)
    class_weight_sums = {
        label: float(weights[labels == label].sum()) for label in set(labels.tolist())
    }
    if len(class_weight_sums) == 2:
        target_sum = sum(class_weight_sums.values()) / 2.0
        weights = np.asarray(
            [
                weight * target_sum / class_weight_sums[int(label)]
                for weight, label in zip(weights, labels, strict=True)
            ],
            dtype=float,
        )
    return weights


def _class_counts(labels: np.ndarray) -> dict[str, int]:
    counts = Counter(int(value) for value in labels.tolist())
    return {
        "negative": int(counts.get(0, 0)),
        "positive": int(counts.get(1, 0)),
    }


def _feature_mapping(
    names: Sequence[str],
    values: Sequence[object],
) -> dict[str, float]:
    return {
        name: _canonical_float(value)
        for name, value in zip(names, values, strict=True)
    }


def _stable_fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _action_threshold_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    reachable_pairs: set[tuple[str, str]],
) -> dict[str, float | int | None]:
    selected = select_radar_actions(rows, threshold=threshold)
    true_positive_pairs = {
        _row_pair(row)
        for row in selected
        if row.get(TOUCH_TARGET_FIELD) is True
    }
    precision = _ratio(len(true_positive_pairs), len(selected))
    recall = _ratio(len(true_positive_pairs), len(reachable_pairs))
    return {
        "threshold": round(float(threshold), 4),
        "selection_count": len(selected),
        "true_positive_count": len(true_positive_pairs),
        "precision": precision,
        "reachable_recall": recall,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 8) if denominator else None


def _quantile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = min(max(float(quantile), 0.0), 1.0) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _canonical_float(value: object) -> float:
    parsed = _number(value)
    if parsed is None:
        raise ValueError("canonical value must be finite")
    rounded = round(parsed, 8)
    return 0.0 if rounded == 0 else rounded


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
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(scheduled_execution.SHANGHAI)
