"""Frozen three-stage models for the forward-only pre-board point trigger."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from math import exp, isfinite
from typing import Any

import numpy as np

from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CONTRACT_VERSION,
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
)


MODEL_VERSION = "limit-up-preboard-point-trigger-model-v9"
EVENT_SCORE_FIELD = "point_event_probability"
IDENTITY_SCORE_FIELD = "point_identity_score"
ACTION_SCORE_FIELD = "point_action_probability"
MINIMUM_OOF_SEED_DATES = 20
OOF_BLOCK_SIZE = 5
MAXIMUM_DAILY_ACTIONS = 2
DEFAULT_ACTION_THRESHOLDS = tuple(
    round(value / 100.0, 2) for value in range(5, 100, 5)
)

EVENT_MODEL_PARAMETERS: dict[str, object] = {
    "objective": "binary",
    "n_estimators": 160,
    "learning_rate": 0.025,
    "num_leaves": 7,
    "max_depth": 3,
    "min_child_samples": 50,
    "reg_alpha": 2,
    "reg_lambda": 8,
    "colsample_bytree": 0.8,
    "random_state": 0,
    "deterministic": True,
    "force_col_wise": True,
    "n_jobs": 1,
}
IDENTITY_MODEL_PARAMETERS: dict[str, object] = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "n_estimators": 120,
    "learning_rate": 0.03,
    "num_leaves": 7,
    "max_depth": 3,
    "min_child_samples": 20,
    "reg_alpha": 1,
    "reg_lambda": 5,
    "colsample_bytree": 0.8,
    "random_state": 0,
    "deterministic": True,
    "force_col_wise": True,
    "n_jobs": 1,
}
ACTION_MODEL_PARAMETERS: dict[str, object] = {
    "class_weight": None,
    "max_iter": 2_000,
    "random_state": 0,
}

IDENTITY_MODEL_FEATURE_FIELDS = (*FRAME_FEATURE_FIELDS, *IDENTITY_FEATURE_FIELDS)
ACTION_FEATURE_FIELDS = (
    *FRAME_FEATURE_FIELDS,
    *IDENTITY_FEATURE_FIELDS,
    EVENT_SCORE_FIELD,
    IDENTITY_SCORE_FIELD,
    "top1_margin",
    "candidate_count",
)


@dataclass(frozen=True)
class PointEventModelFit:
    status: str
    model: Any | None
    training_row_count: int
    training_date_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    parameters: dict[str, object]
    training_weight_by_date: dict[str, float]
    feature_importance_by_name: dict[str, float]
    booster_model_text: str | None
    training_input_fingerprint: str | None
    fingerprint: str | None


@dataclass(frozen=True)
class PointIdentityModelFit:
    status: str
    model: Any | None
    training_row_count: int
    training_date_count: int
    training_group_count: int
    class_counts: dict[str, int]
    group_sizes: tuple[int, ...]
    fit_dates: tuple[str, ...]
    parameters: dict[str, object]
    feature_importance_by_name: dict[str, float]
    booster_model_text: str | None
    training_input_fingerprint: str | None
    fingerprint: str | None


@dataclass(frozen=True)
class PointActionModelFit:
    status: str
    pipeline: Any | None
    training_row_count: int
    training_date_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    parameters: dict[str, object]
    scaler_mean_by_feature: dict[str, float]
    scaler_scale_by_feature: dict[str, float]
    coefficient_by_feature: dict[str, float]
    intercept: float | None
    training_input_fingerprint: str | None
    fingerprint: str | None


@dataclass(frozen=True)
class PointThresholdSelection:
    status: str
    threshold: float | None
    minimum_action_count: int
    minimum_precision: float
    selected_metrics: dict[str, float | int | None]
    metrics_by_threshold: tuple[dict[str, float | int | None], ...]


def build_event_training_batch(
    rows: Sequence[Mapping[str, object]],
    fit_dates: Sequence[date] | set[date],
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    tuple[tuple[str, str, str], ...],
]:
    """Build one market-event observation per frame with equal date mass."""

    allowed_dates = set(_normalized_dates(fit_dates))
    prepared: dict[
        tuple[str, str, str],
        tuple[list[float], int],
    ] = {}
    for row in rows:
        trade_date = _as_date(row.get("trade_date"))
        vector = _feature_vector(row.get("frame_features"), FRAME_FEATURE_FIELDS)
        label = _known_label(row, "formal_event_within_60s")
        key = _frame_key(row)
        if (
            trade_date not in allowed_dates
            or vector is None
            or label is None
            or key is None
        ):
            continue
        existing = prepared.get(key)
        candidate = (vector, label)
        if existing is not None and existing != candidate:
            raise ValueError("inconsistent event features or labels inside one frame")
        prepared.setdefault(key, candidate)
    keys = tuple(sorted(prepared))
    matrix = _matrix(
        [prepared[key][0] for key in keys],
        len(FRAME_FEATURE_FIELDS),
    )
    labels = np.asarray([prepared[key][1] for key in keys], dtype=int)
    weights = _date_equal_class_balanced_weights(labels, keys)
    return matrix, labels, weights, keys


def fit_event_model(
    rows: Sequence[Mapping[str, object]],
    fit_dates: Sequence[date] | set[date],
) -> PointEventModelFit:
    """Fit the fixed date-equal 60-second formal-event classifier."""

    ordered_dates = _normalized_dates(fit_dates)
    matrix, labels, weights, keys = build_event_training_batch(rows, ordered_dates)
    input_fingerprint = _training_fingerprint(matrix, labels, keys, weights)
    common = {
        "training_row_count": len(labels),
        "training_date_count": len({key[0] for key in keys}),
        "class_counts": _class_counts(labels),
        "fit_dates": tuple(value.isoformat() for value in ordered_dates),
        "parameters": dict(EVENT_MODEL_PARAMETERS),
        "training_weight_by_date": _weight_totals_by_date(weights, keys),
        "training_input_fingerprint": input_fingerprint,
    }
    if len(labels) < 2 or len(set(labels.tolist())) < 2:
        return PointEventModelFit(
            status="not_ready_event_classes",
            model=None,
            feature_importance_by_name={},
            booster_model_text=None,
            fingerprint=None,
            **common,
        )

    import pandas as pd
    from lightgbm import LGBMClassifier

    model = LGBMClassifier(**EVENT_MODEL_PARAMETERS)
    frame = pd.DataFrame(matrix, columns=FRAME_FEATURE_FIELDS)
    model.fit(frame, labels, sample_weight=weights)
    booster_text = str(model.booster_.model_to_string())
    importance = _feature_mapping(
        FRAME_FEATURE_FIELDS,
        model.booster_.feature_importance(importance_type="gain"),
    )
    fingerprint = _stable_fingerprint(
        {
            "model_version": MODEL_VERSION,
            "stage": "event",
            "contract_version": CONTRACT_VERSION,
            "features": FRAME_FEATURE_FIELDS,
            "fit_dates": common["fit_dates"],
            "parameters": EVENT_MODEL_PARAMETERS,
            "training_input_fingerprint": input_fingerprint,
            "booster_sha256": sha256(booster_text.encode()).hexdigest(),
        }
    )
    return PointEventModelFit(
        status="ready",
        model=model,
        feature_importance_by_name=importance,
        booster_model_text=booster_text,
        fingerprint=fingerprint,
        **common,
    )


def score_event_rows(
    rows: Sequence[Mapping[str, object]],
    model: PointEventModelFit,
) -> list[dict[str, object]]:
    if model.status != "ready" or model.model is None:
        return []
    prepared = [
        (dict(row), vector)
        for row in rows
        if (vector := _feature_vector(row.get("frame_features"), FRAME_FEATURE_FIELDS))
        is not None
    ]
    if not prepared:
        return []

    import pandas as pd

    frame = pd.DataFrame(
        [vector for _, vector in prepared],
        columns=FRAME_FEATURE_FIELDS,
    )
    probabilities = model.model.predict_proba(frame)[:, 1]
    return [
        {
            **row,
            EVENT_SCORE_FIELD: _canonical_float(probability),
            "event_model_fingerprint": model.fingerprint,
        }
        for (row, _), probability in zip(prepared, probabilities, strict=True)
    ]


def build_identity_training_batch(
    rows: Sequence[Mapping[str, object]],
    fit_dates: Sequence[date] | set[date],
) -> tuple[
    np.ndarray,
    np.ndarray,
    tuple[int, ...],
    tuple[tuple[str, str, str, str], ...],
]:
    """Build contiguous LambdaRank groups from event-positive frames only."""

    allowed_dates = set(_normalized_dates(fit_dates))
    grouped: dict[
        tuple[str, str, str],
        dict[str, tuple[list[float], int]],
    ] = defaultdict(dict)
    for row in rows:
        trade_date = _as_date(row.get("trade_date"))
        frame_key = _frame_key(row)
        event_label = _known_label(row, "formal_event_within_60s")
        identity_label = _known_label(row, "formal_identity_within_60s")
        vector = _combined_feature_vector(row)
        symbol = str(row.get("vt_symbol") or "").strip()
        if (
            trade_date not in allowed_dates
            or frame_key is None
            or event_label != 1
            or identity_label is None
            or vector is None
            or not symbol
        ):
            continue
        candidate = (vector, identity_label)
        existing = grouped[frame_key].get(symbol)
        if existing is not None and existing != candidate:
            raise ValueError("inconsistent identity features or labels for one candidate")
        grouped[frame_key].setdefault(symbol, candidate)

    vectors: list[list[float]] = []
    labels: list[int] = []
    group_sizes: list[int] = []
    keys: list[tuple[str, str, str, str]] = []
    for frame_key in sorted(grouped):
        candidates = grouped[frame_key]
        if not candidates:
            continue
        positive_count = sum(label for _vector, label in candidates.values())
        if positive_count == 0:
            continue
        if positive_count != 1:
            raise ValueError("identity frame must contain exactly one reachable identity")
        group_sizes.append(len(candidates))
        for symbol in sorted(candidates):
            vector, label = candidates[symbol]
            vectors.append(vector)
            labels.append(label)
            keys.append((*frame_key, symbol))
    return (
        _matrix(vectors, len(IDENTITY_MODEL_FEATURE_FIELDS)),
        np.asarray(labels, dtype=int),
        tuple(group_sizes),
        tuple(keys),
    )


def fit_identity_ranker(
    rows: Sequence[Mapping[str, object]],
    fit_dates: Sequence[date] | set[date],
) -> PointIdentityModelFit:
    """Fit the fixed within-frame earliest-formal-identity ranker."""

    ordered_dates = _normalized_dates(fit_dates)
    matrix, labels, groups, keys = build_identity_training_batch(rows, ordered_dates)
    input_fingerprint = _training_fingerprint(matrix, labels, keys, groups)
    common = {
        "training_row_count": len(labels),
        "training_date_count": len({key[0] for key in keys}),
        "training_group_count": len(groups),
        "class_counts": _class_counts(labels),
        "group_sizes": groups,
        "fit_dates": tuple(value.isoformat() for value in ordered_dates),
        "parameters": dict(IDENTITY_MODEL_PARAMETERS),
        "training_input_fingerprint": input_fingerprint,
    }
    if (
        not groups
        or not any(size >= 2 for size in groups)
        or len(set(labels.tolist())) < 2
    ):
        return PointIdentityModelFit(
            status="not_ready_identity_groups",
            model=None,
            feature_importance_by_name={},
            booster_model_text=None,
            fingerprint=None,
            **common,
        )

    import pandas as pd
    from lightgbm import LGBMRanker

    model = LGBMRanker(**IDENTITY_MODEL_PARAMETERS)
    frame = pd.DataFrame(matrix, columns=IDENTITY_MODEL_FEATURE_FIELDS)
    model.fit(frame, labels, group=list(groups))
    booster_text = str(model.booster_.model_to_string())
    importance = _feature_mapping(
        IDENTITY_MODEL_FEATURE_FIELDS,
        model.booster_.feature_importance(importance_type="gain"),
    )
    fingerprint = _stable_fingerprint(
        {
            "model_version": MODEL_VERSION,
            "stage": "identity",
            "contract_version": CONTRACT_VERSION,
            "features": IDENTITY_MODEL_FEATURE_FIELDS,
            "fit_dates": common["fit_dates"],
            "parameters": IDENTITY_MODEL_PARAMETERS,
            "training_input_fingerprint": input_fingerprint,
            "booster_sha256": sha256(booster_text.encode()).hexdigest(),
        }
    )
    return PointIdentityModelFit(
        status="ready",
        model=model,
        feature_importance_by_name=importance,
        booster_model_text=booster_text,
        fingerprint=fingerprint,
        **common,
    )


def score_identity_rows(
    rows: Sequence[Mapping[str, object]],
    model: PointIdentityModelFit,
) -> list[dict[str, object]]:
    if model.status != "ready" or model.model is None:
        return []
    prepared = [
        (dict(row), vector)
        for row in rows
        if (vector := _combined_feature_vector(row)) is not None
    ]
    if not prepared:
        return []

    import pandas as pd

    frame = pd.DataFrame(
        [vector for _, vector in prepared],
        columns=IDENTITY_MODEL_FEATURE_FIELDS,
    )
    scores = model.model.predict(frame)
    return [
        {
            **row,
            IDENTITY_SCORE_FIELD: _canonical_float(score),
            "identity_model_fingerprint": model.fingerprint,
        }
        for (row, _), score in zip(prepared, scores, strict=True)
    ]


def select_point_top1(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Select one stable identity per frame from already scored candidates."""

    groups: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        key = _frame_key(row)
        if (
            key is None
            or _number(row.get(EVENT_SCORE_FIELD)) is None
            or _number(row.get(IDENTITY_SCORE_FIELD)) is None
        ):
            continue
        groups[key].append(dict(row))
    selected: list[dict[str, object]] = []
    for key in sorted(groups):
        ranked = sorted(groups[key], key=_identity_ranking_key)
        top = ranked[0]
        top_score = float(top[IDENTITY_SCORE_FIELD])
        second_score = (
            float(ranked[1][IDENTITY_SCORE_FIELD])
            if len(ranked) > 1
            else top_score
        )
        selected.append(
            {
                **top,
                "identity_rank": 1,
                "candidate_count": len(ranked),
                "top1_margin": _canonical_float(top_score - second_score),
            }
        )
    return sorted(selected, key=_row_sort_key)


def build_walk_forward_top1(
    rows: Sequence[Mapping[str, object]],
    fit_dates: Sequence[date] | set[date],
) -> list[dict[str, object]]:
    """Produce expanding-window OOF Top1 rows in frozen five-date blocks."""

    ordered_dates = _normalized_dates(fit_dates)
    if len(ordered_dates) <= MINIMUM_OOF_SEED_DATES:
        return []
    oof_rows: list[dict[str, object]] = []
    for block_start in range(
        MINIMUM_OOF_SEED_DATES,
        len(ordered_dates),
        OOF_BLOCK_SIZE,
    ):
        training_dates = ordered_dates[:block_start]
        scoring_dates = ordered_dates[
            block_start : block_start + OOF_BLOCK_SIZE
        ]
        event_model = fit_event_model(rows, training_dates)
        identity_model = fit_identity_ranker(rows, training_dates)
        if event_model.status != "ready" or identity_model.status != "ready":
            return []
        scoring_date_set = set(scoring_dates)
        scoring_rows = [
            row
            for row in rows
            if _as_date(row.get("trade_date")) in scoring_date_set
        ]
        scored = score_identity_rows(
            score_event_rows(scoring_rows, event_model),
            identity_model,
        )
        for top in select_point_top1(scored):
            oof_rows.append(
                {
                    **top,
                    "oof_training_date_start": training_dates[0],
                    "oof_training_date_end": training_dates[-1],
                    "oof_scoring_block_start": scoring_dates[0],
                    "oof_scoring_block_end": scoring_dates[-1],
                    "oof_event_model_fingerprint": event_model.fingerprint,
                    "oof_identity_model_fingerprint": identity_model.fingerprint,
                }
            )
    return sorted(oof_rows, key=_row_sort_key)


def build_action_training_batch(
    rows: Sequence[Mapping[str, object]],
) -> tuple[
    np.ndarray,
    np.ndarray,
    tuple[tuple[str, str, str, str], ...],
]:
    """Build direct Top1 identity labels from strictly OOF upstream scores."""

    prepared: list[tuple[list[float], int, tuple[str, str, str, str]]] = []
    for row in rows:
        trade_date = _as_date(row.get("trade_date"))
        training_end = _as_date(row.get("oof_training_date_end"))
        event_fingerprint = str(
            row.get("oof_event_model_fingerprint") or ""
        ).strip()
        identity_fingerprint = str(
            row.get("oof_identity_model_fingerprint") or ""
        ).strip()
        vector = _action_feature_vector(row)
        target = _known_label(row, "formal_identity_within_60s")
        key = _candidate_key(row)
        if (
            trade_date is None
            or training_end is None
            or training_end >= trade_date
            or not event_fingerprint
            or not identity_fingerprint
            or vector is None
            or target is None
            or key is None
            or row.get("action_frame_eligible") is not True
        ):
            continue
        prepared.append((vector, target, key))
    prepared.sort(key=lambda item: item[2])
    return (
        _matrix([item[0] for item in prepared], len(ACTION_FEATURE_FIELDS)),
        np.asarray([item[1] for item in prepared], dtype=int),
        tuple(item[2] for item in prepared),
    )


def fit_action_model(
    oof_top1: Sequence[Mapping[str, object]],
) -> PointActionModelFit:
    """Fit the fixed natural-prevalence direct Top1 action model."""

    matrix, labels, keys = build_action_training_batch(oof_top1)
    fit_dates = tuple(sorted({key[0] for key in keys}))
    input_fingerprint = _training_fingerprint(matrix, labels, keys)
    common = {
        "training_row_count": len(labels),
        "training_date_count": len(fit_dates),
        "class_counts": _class_counts(labels),
        "fit_dates": fit_dates,
        "parameters": dict(ACTION_MODEL_PARAMETERS),
        "training_input_fingerprint": input_fingerprint,
    }
    if len(labels) < 2 or len(set(labels.tolist())) < 2:
        return PointActionModelFit(
            status="not_ready_action_classes",
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
            ("logistic", LogisticRegression(**ACTION_MODEL_PARAMETERS)),
        ]
    )
    pipeline.fit(matrix, labels)
    scaler = pipeline.named_steps["scaler"]
    logistic = pipeline.named_steps["logistic"]
    means = _exact_feature_mapping(ACTION_FEATURE_FIELDS, scaler.mean_)
    scales = _exact_feature_mapping(ACTION_FEATURE_FIELDS, scaler.scale_)
    coefficients = _exact_feature_mapping(
        ACTION_FEATURE_FIELDS,
        logistic.coef_[0],
    )
    intercept = float(logistic.intercept_[0])
    fingerprint = _stable_fingerprint(
        {
            "model_version": MODEL_VERSION,
            "stage": "action",
            "contract_version": CONTRACT_VERSION,
            "features": ACTION_FEATURE_FIELDS,
            "fit_dates": fit_dates,
            "parameters": ACTION_MODEL_PARAMETERS,
            "training_input_fingerprint": input_fingerprint,
            "upstream_event_fingerprints": sorted(
                {
                    str(row.get("oof_event_model_fingerprint") or "")
                    for row in oof_top1
                    if row.get("oof_event_model_fingerprint")
                }
            ),
            "upstream_identity_fingerprints": sorted(
                {
                    str(row.get("oof_identity_model_fingerprint") or "")
                    for row in oof_top1
                    if row.get("oof_identity_model_fingerprint")
                }
            ),
            "means": means,
            "scales": scales,
            "coefficients": coefficients,
            "intercept": intercept,
        }
    )
    return PointActionModelFit(
        status="ready",
        pipeline=pipeline,
        scaler_mean_by_feature=means,
        scaler_scale_by_feature=scales,
        coefficient_by_feature=coefficients,
        intercept=intercept,
        fingerprint=fingerprint,
        **common,
    )


def score_action_rows(
    rows: Sequence[Mapping[str, object]],
    model: PointActionModelFit,
) -> list[dict[str, object]]:
    if model.status != "ready" or model.pipeline is None:
        return []
    prepared = [
        (dict(row), vector)
        for row in rows
        if (vector := _action_feature_vector(row)) is not None
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


def score_frozen_point_top1(
    rows: Sequence[Mapping[str, object]],
    model_record: Mapping[str, object],
) -> list[dict[str, object]]:
    """Score current rows from immutable numeric/model-text artifacts."""

    artifact = model_record.get("model_artifact")
    if not isinstance(artifact, Mapping):
        return []
    event_text = str(artifact.get("event_booster_model_text") or "")
    identity_text = str(artifact.get("identity_booster_model_text") or "")
    if not event_text or not identity_text:
        return []

    import pandas as pd
    from lightgbm import Booster

    event_prepared = [
        (dict(row), vector)
        for row in rows
        if (vector := _feature_vector(row.get("frame_features"), FRAME_FEATURE_FIELDS))
        is not None
    ]
    if not event_prepared:
        return []
    event_frame = pd.DataFrame(
        [vector for _, vector in event_prepared],
        columns=FRAME_FEATURE_FIELDS,
    )
    event_scores = Booster(model_str=event_text).predict(event_frame)
    event_rows = [
        {
            **row,
            EVENT_SCORE_FIELD: _canonical_float(score),
            "event_model_fingerprint": model_record.get(
                "event_model_fingerprint"
            ),
        }
        for (row, _), score in zip(event_prepared, event_scores, strict=True)
    ]

    identity_prepared = [
        (row, vector)
        for row in event_rows
        if (vector := _combined_feature_vector(row)) is not None
    ]
    if not identity_prepared:
        return []
    identity_frame = pd.DataFrame(
        [vector for _, vector in identity_prepared],
        columns=IDENTITY_MODEL_FEATURE_FIELDS,
    )
    identity_scores = Booster(model_str=identity_text).predict(identity_frame)
    ranked_rows = [
        {
            **row,
            IDENTITY_SCORE_FIELD: _canonical_float(score),
            "identity_model_fingerprint": model_record.get(
                "identity_model_fingerprint"
            ),
        }
        for (row, _), score in zip(
            identity_prepared,
            identity_scores,
            strict=True,
        )
    ]
    top1 = select_point_top1(ranked_rows)

    means = artifact.get("action_scaler_mean_by_feature")
    scales = artifact.get("action_scaler_scale_by_feature")
    coefficients = artifact.get("action_coefficient_by_feature")
    intercept = _number(artifact.get("action_intercept"))
    if not all(
        isinstance(value, Mapping) for value in (means, scales, coefficients)
    ) or intercept is None:
        return []
    scored: list[dict[str, object]] = []
    for row in top1:
        vector = _action_feature_vector(row)
        if vector is None:
            continue
        logit = intercept
        valid = True
        for field, value in zip(ACTION_FEATURE_FIELDS, vector, strict=True):
            mean_value = _number(means.get(field))
            scale_value = _number(scales.get(field))
            coefficient = _number(coefficients.get(field))
            if (
                mean_value is None
                or scale_value is None
                or scale_value <= 0
                or coefficient is None
            ):
                valid = False
                break
            logit += coefficient * (value - mean_value) / scale_value
        if not valid:
            continue
        probability = (
            1.0 / (1.0 + exp(-logit))
            if logit >= 0
            else (lambda value: value / (1.0 + value))(exp(logit))
        )
        scored.append(
            {
                **row,
                ACTION_SCORE_FIELD: _canonical_float(probability),
                "action_model_fingerprint": model_record.get(
                    "action_model_fingerprint"
                ),
            }
        )
    return scored


def select_point_actions(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float | None,
    maximum_daily_actions: int = MAXIMUM_DAILY_ACTIONS,
) -> list[dict[str, object]]:
    """Apply frozen first-stock-day, one-frame and two-per-day constraints."""

    if threshold is None:
        return []
    parsed_threshold = _number(threshold)
    if parsed_threshold is None or not 0.0 <= parsed_threshold <= 1.0:
        return []
    selected_pairs: set[tuple[str, str]] = set()
    selected_frames: set[tuple[str, str, str]] = set()
    daily_counts: Counter[str] = Counter()
    selected: list[dict[str, object]] = []
    for row in sorted((dict(raw) for raw in rows), key=_action_selection_key):
        score = _number(row.get(ACTION_SCORE_FIELD))
        trade_date = _as_date(row.get("trade_date"))
        frame_key = _frame_key(row)
        symbol = str(row.get("vt_symbol") or "").strip()
        if score is None or trade_date is None or frame_key is None or not symbol:
            continue
        date_text = trade_date.isoformat()
        pair = (date_text, symbol)
        if (
            row.get("action_frame_eligible") is not True
            or score < parsed_threshold
            or pair in selected_pairs
            or frame_key in selected_frames
            or daily_counts[date_text] >= max(int(maximum_daily_actions), 1)
        ):
            continue
        selected_pairs.add(pair)
        selected_frames.add(frame_key)
        daily_counts[date_text] += 1
        selected.append(row)
    return selected


def calibrate_point_actions(
    rows: Sequence[Mapping[str, object]],
    minimum_actions: int = 20,
    minimum_precision: float = 0.70,
    *,
    reachable_stock_day_pairs: set[tuple[str, str]] | None = None,
) -> PointThresholdSelection:
    """Select the only legal threshold without reading validation outcomes."""

    calibration_rows = [
        dict(row)
        for row in rows
        if _known_label(row, "formal_identity_within_60s") is not None
        and _number(row.get(ACTION_SCORE_FIELD)) is not None
        and row.get("action_frame_eligible") is True
    ]
    if reachable_stock_day_pairs is None:
        reachable_pairs = {
            pair
            for row in calibration_rows
            if row.get("formal_identity_within_60s") is True
            and (pair := _stock_day_pair(row)) is not None
        }
    else:
        reachable_pairs = {
            (str(trade_date), str(symbol))
            for trade_date, symbol in reachable_stock_day_pairs
            if str(trade_date).strip() and str(symbol).strip()
        }
    metrics = tuple(
        _threshold_metrics(
            calibration_rows,
            threshold=threshold,
            reachable_pairs=reachable_pairs,
        )
        for threshold in DEFAULT_ACTION_THRESHOLDS
    )
    required_actions = max(int(minimum_actions), 1)
    required_precision = min(max(float(minimum_precision), 0.0), 1.0)
    supported = [
        metric
        for metric in metrics
        if int(metric["stock_day_action_count"] or 0) >= required_actions
    ]
    qualified = [
        metric
        for metric in supported
        if float(metric["formal_identity_precision"] or 0.0)
        >= required_precision
    ]
    selected = max(
        qualified,
        key=lambda metric: (
            float(metric["reachable_recall"] or 0.0),
            float(metric["formal_identity_precision"] or 0.0),
            float(metric["threshold"] or 0.0),
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
    return PointThresholdSelection(
        status=status,
        threshold=float(selected["threshold"]) if selected is not None else None,
        minimum_action_count=required_actions,
        minimum_precision=required_precision,
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def _combined_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    frame = _feature_vector(row.get("frame_features"), FRAME_FEATURE_FIELDS)
    identity = _feature_vector(
        row.get("identity_features"), IDENTITY_FEATURE_FIELDS
    )
    if frame is None or identity is None:
        return None
    return [*frame, *identity]


def _action_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    candidate = _combined_feature_vector(row)
    event_probability = _number(row.get(EVENT_SCORE_FIELD))
    identity_score = _number(row.get(IDENTITY_SCORE_FIELD))
    margin = _number(row.get("top1_margin"))
    candidate_count = _number(row.get("candidate_count"))
    if (
        candidate is None
        or event_probability is None
        or identity_score is None
        or margin is None
        or candidate_count is None
        or candidate_count < 1
    ):
        return None
    return [
        *candidate,
        event_probability,
        identity_score,
        margin,
        candidate_count,
    ]


def _feature_vector(
    value: object,
    fields: Sequence[str],
) -> list[float] | None:
    if not isinstance(value, Mapping):
        return None
    parsed = [_number(value.get(field)) for field in fields]
    if any(item is None for item in parsed):
        return None
    return [float(item) for item in parsed if item is not None]


def _date_equal_class_balanced_weights(
    labels: np.ndarray,
    keys: Sequence[tuple[str, ...]],
) -> np.ndarray:
    if len(labels) == 0:
        return np.asarray([], dtype=float)
    by_date_class = Counter(
        (key[0], int(label))
        for key, label in zip(keys, labels, strict=True)
    )
    classes_by_date: dict[str, set[int]] = defaultdict(set)
    for date_text, label in by_date_class:
        classes_by_date[date_text].add(label)
    return np.asarray(
        [
            1.0
            / len(classes_by_date[key[0]])
            / by_date_class[(key[0], int(label))]
            for key, label in zip(keys, labels, strict=True)
        ],
        dtype=float,
    )


def _weight_totals_by_date(
    weights: np.ndarray,
    keys: Sequence[tuple[str, ...]],
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for key, weight in zip(keys, weights, strict=True):
        totals[key[0]] += float(weight)
    return {
        key: _canonical_float(value)
        for key, value in sorted(totals.items())
    }


def _threshold_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    reachable_pairs: set[tuple[str, str]],
) -> dict[str, float | int | None]:
    selected = select_point_actions(rows, threshold=threshold)
    true_positive_pairs = {
        pair
        for row in selected
        if row.get("formal_identity_within_60s") is True
        and (pair := _stock_day_pair(row)) is not None
    }
    return {
        "threshold": round(float(threshold), 2),
        "stock_day_action_count": len(selected),
        "formal_identity_true_positive_count": len(true_positive_pairs),
        "formal_identity_precision": _ratio(len(true_positive_pairs), len(selected)),
        "reachable_recall": _ratio(len(true_positive_pairs), len(reachable_pairs)),
    }


def _identity_ranking_key(row: Mapping[str, object]) -> tuple[float, float, str]:
    identity = row.get("identity_features")
    identity = identity if isinstance(identity, Mapping) else {}
    lane_rank = _number(identity.get("candidate_lane_rank_score"))
    if lane_rank is None:
        lane_rank = _number(row.get("candidate_lane_rank_score"))
    return (
        -float(row[IDENTITY_SCORE_FIELD]),
        -(lane_rank or 0.0),
        str(row.get("vt_symbol") or ""),
    )


def _action_selection_key(
    row: Mapping[str, object],
) -> tuple[str, str, float, float, str]:
    trade_date = _as_date(row.get("trade_date"))
    captured_at = _as_datetime(row.get("captured_at"))
    identity = row.get("identity_features")
    identity = identity if isinstance(identity, Mapping) else {}
    lane_rank = _number(identity.get("candidate_lane_rank_score")) or 0.0
    return (
        trade_date.isoformat() if trade_date else "",
        _datetime_key(captured_at),
        -(_number(row.get(ACTION_SCORE_FIELD)) or 0.0),
        -lane_rank,
        str(row.get("vt_symbol") or ""),
    )


def _row_sort_key(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    key = _candidate_key(row)
    return key or ("", "", "", "")


def _frame_key(row: Mapping[str, object]) -> tuple[str, str, str] | None:
    trade_date = _as_date(row.get("trade_date"))
    captured_at = _as_datetime(row.get("captured_at"))
    frame_id = row.get("frame_id")
    if trade_date is None or captured_at is None or frame_id in (None, ""):
        return None
    return trade_date.isoformat(), _datetime_key(captured_at), str(frame_id)


def _candidate_key(row: Mapping[str, object]) -> tuple[str, str, str, str] | None:
    frame_key = _frame_key(row)
    symbol = str(row.get("vt_symbol") or "").strip()
    if frame_key is None or not symbol:
        return None
    return *frame_key, symbol


def _stock_day_pair(row: Mapping[str, object]) -> tuple[str, str] | None:
    trade_date = _as_date(row.get("trade_date"))
    symbol = str(row.get("vt_symbol") or "").strip()
    if trade_date is None or not symbol:
        return None
    return trade_date.isoformat(), symbol


def _known_label(row: Mapping[str, object], field: str) -> int | None:
    if str(row.get("label_status") or "") != "known":
        return None
    value = row.get(field)
    return int(value) if isinstance(value, bool) else None


def _training_fingerprint(
    matrix: np.ndarray,
    labels: np.ndarray,
    keys: Sequence[tuple[str, ...]],
    auxiliary: Sequence[object] | np.ndarray = (),
) -> str:
    return _stable_fingerprint(
        {
            "matrix": [
                [_canonical_float(value) for value in row]
                for row in matrix.tolist()
            ],
            "labels": [int(value) for value in labels.tolist()],
            "keys": [list(key) for key in keys],
            "auxiliary": [
                _canonical_float(value)
                if isinstance(value, (float, np.floating))
                else int(value)
                if isinstance(value, (int, np.integer))
                else str(value)
                for value in list(auxiliary)
            ],
        }
    )


def _matrix(rows: Sequence[Sequence[float]], width: int) -> np.ndarray:
    return (
        np.asarray(rows, dtype=float)
        if rows
        else np.empty((0, width), dtype=float)
    )


def _class_counts(labels: np.ndarray) -> dict[str, int]:
    counts = Counter(int(value) for value in labels.tolist())
    return {
        "negative": int(counts.get(0, 0)),
        "positive": int(counts.get(1, 0)),
    }


def _feature_mapping(
    fields: Sequence[str],
    values: Sequence[object],
) -> dict[str, float]:
    return {
        field: _canonical_float(value)
        for field, value in zip(fields, values, strict=True)
    }


def _exact_feature_mapping(
    fields: Sequence[str],
    values: Sequence[object],
) -> dict[str, float]:
    parsed = [_number(value) for value in values]
    if any(value is None for value in parsed):
        raise ValueError("model parameters must be finite")
    return {
        field: float(value)
        for field, value in zip(fields, parsed, strict=True)
        if value is not None
    }


def _normalized_dates(values: Sequence[date] | set[date]) -> tuple[date, ...]:
    parsed = {_as_date(value) for value in values}
    parsed.discard(None)
    return tuple(sorted(value for value in parsed if value is not None))


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
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _datetime_key(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).isoformat() if value is not None else ""


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _canonical_float(value: object) -> float:
    parsed = _number(value)
    if parsed is None:
        raise ValueError("model values must be finite")
    rounded = round(parsed, 10)
    return 0.0 if rounded == 0 else rounded


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 10) if denominator else None


def _stable_fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"
