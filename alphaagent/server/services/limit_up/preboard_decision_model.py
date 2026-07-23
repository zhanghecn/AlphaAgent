"""Two-head causal model for formal first-board touch timing."""

from __future__ import annotations

import base64
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from math import ceil, isfinite
import pickle
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score

from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    is_observable_first_board,
    is_strictly_preboard,
)
from alphaagent.server.services.limit_up.preboard_decision_features import (
    MODEL_FEATURE_NAMES,
    model_feature_vector,
)


PREBOARD_MODEL_ARTIFACT_FORMAT = "limit-up-preboard-decision-artifact-v1"
HEAD_TARGETS = {
    "touch_3m": ("formal_touch_within_3m",),
    "eventual_touch": ("eventual_formal_touch", "formal_touch_eventually"),
}
MODEL_PARAMETERS: dict[str, object] = {
    "learning_rate": 0.05,
    "max_iter": 200,
    "max_depth": 3,
    "min_samples_leaf": 10,
    "l2_regularization": 1.0,
    "class_weight": "balanced",
    "early_stopping": False,
    "random_state": 17,
}
MINIMUM_CALIBRATION_PAIR_COUNT = 20
MINIMUM_QUALIFICATION_CLASS_STOCK_DAYS = 20


@dataclass(frozen=True)
class _ProbabilityHead:
    status: str
    estimator: Any | None
    calibrator: Any | None
    feature_indices: tuple[int, ...] = ()

    def probabilities(self, matrix: np.ndarray) -> np.ndarray | None:
        if (
            self.status != "ready"
            or self.estimator is None
            or self.calibrator is None
            or not self.feature_indices
        ):
            return None
        projected = np.take(matrix, self.feature_indices, axis=1)
        raw = np.asarray(self.estimator.predict_proba(projected)[:, 1], dtype=float)
        return np.clip(
            np.asarray(self.calibrator.predict(raw), dtype=float),
            0.0,
            1.0,
        )


@dataclass(frozen=True)
class PreboardModelBundle:
    status: str
    feature_version: str
    model_version: str
    fit_dates: tuple[date, ...]
    calibration_dates: tuple[date, ...]
    feature_names: tuple[str, ...]
    touch_3m_model: _ProbabilityHead
    eventual_touch_model: _ProbabilityHead
    fingerprint: str
    training_input_fingerprint: str
    head_reports: dict[str, dict[str, object]]


def fit_preboard_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date] | Sequence[date],
    calibration_dates: set[date] | Sequence[date],
) -> PreboardModelBundle:
    """Fit and calibrate both heads without consulting any validation rows."""

    fit_scope = tuple(sorted(set(fit_dates)))
    calibration_scope = tuple(sorted(set(calibration_dates)))
    if set(fit_scope).intersection(calibration_scope):
        raise ValueError("fit_dates and calibration_dates must be disjoint")
    scoped_rows = [
        dict(row)
        for row in rows
        if (_row_date(row) in set(fit_scope) | set(calibration_scope))
    ]
    training_input_fingerprint = _training_fingerprint(
        scoped_rows,
        fit_scope,
        calibration_scope,
    )
    heads: dict[str, _ProbabilityHead] = {}
    reports: dict[str, dict[str, object]] = {}
    for head_name, target_fields in HEAD_TARGETS.items():
        head, report = _fit_head(
            scoped_rows,
            target_fields=target_fields,
            fit_dates=set(fit_scope),
            calibration_dates=set(calibration_scope),
        )
        heads[head_name] = head
        reports[head_name] = report
    statuses = {head.status for head in heads.values()}
    if statuses == {"ready"}:
        status = "ready"
    elif any(value.startswith("insufficient_calibration") for value in statuses):
        status = "insufficient_calibration"
    else:
        status = "insufficient_fit"
    fingerprint = _model_fingerprint(
        status=status,
        fit_dates=fit_scope,
        calibration_dates=calibration_scope,
        training_input_fingerprint=training_input_fingerprint,
        reports=reports,
    )
    return PreboardModelBundle(
        status=status,
        feature_version=PREBOARD_DECISION_VERSION,
        model_version=PREBOARD_DECISION_VERSION,
        fit_dates=fit_scope,
        calibration_dates=calibration_scope,
        feature_names=tuple(MODEL_FEATURE_NAMES),
        touch_3m_model=heads["touch_3m"],
        eventual_touch_model=heads["eventual_touch"],
        fingerprint=fingerprint,
        training_input_fingerprint=training_input_fingerprint,
        head_reports=reports,
    )


def score_preboard_candidate(
    bundle: PreboardModelBundle,
    row: Mapping[str, object],
) -> dict[str, object]:
    """Score one quality-qualified row while preserving the frozen D+1 priors."""

    priors = _prior_projection(row)
    base = {
        "model_version": bundle.model_version,
        "model_fingerprint": bundle.fingerprint,
        "touch_probability_3m": None,
        "eventual_touch_probability": None,
        **priors,
    }
    if row.get("quality_gate_passed") is not True:
        return {**base, "probability_status": "quality_gate_failed"}
    if not _model_input_eligible(row):
        return {**base, "probability_status": "model_input_ineligible"}
    if bundle.status != "ready":
        return {**base, "probability_status": "model_not_ready"}
    if row.get("feature_contract_version") != bundle.feature_version:
        return {**base, "probability_status": "feature_contract_mismatch"}
    vector = model_feature_vector(row)
    if vector is None:
        return {**base, "probability_status": "features_not_scoreable"}
    matrix = np.asarray([vector], dtype=float)
    touch_values = bundle.touch_3m_model.probabilities(matrix)
    eventual_values = bundle.eventual_touch_model.probabilities(matrix)
    if touch_values is None or eventual_values is None:
        return {**base, "probability_status": "model_not_ready"}
    touch_probability = float(touch_values[0])
    eventual_probability = max(float(eventual_values[0]), touch_probability)
    return {
        **base,
        "probability_status": "ready",
        "touch_probability_3m": round(touch_probability, 10),
        "eventual_touch_probability": round(eventual_probability, 10),
    }


def score_preboard_rows(
    bundle: PreboardModelBundle,
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {**dict(row), **score_preboard_candidate(bundle, row)}
        for row in rows
    ]


def qualify_preboard_probabilities(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Qualify point probabilities without letting long paths dominate the result."""

    head_fields = {
        "touch_3m": ("touch_probability_3m", HEAD_TARGETS["touch_3m"]),
        "eventual_touch": (
            "eventual_touch_probability",
            HEAD_TARGETS["eventual_touch"],
        ),
    }
    reports: dict[str, dict[str, object]] = {}
    reasons: list[str] = []
    all_pairs: set[tuple[date, str]] = set()
    for head_name, (probability_field, target_fields) in head_fields.items():
        clustered: defaultdict[tuple[date, str], list[tuple[float, int]]] = (
            defaultdict(list)
        )
        for row in rows:
            trade_date = _row_date(row)
            symbol = str(row.get("vt_symbol") or "").strip()
            probability = _canonical_number(row.get(probability_field))
            target = _target(row, target_fields)
            if (
                trade_date is None
                or not symbol
                or row.get("probability_status") != "ready"
                or probability is None
                or target is None
                or not 0.0 <= probability <= 1.0
            ):
                continue
            pair = (trade_date, symbol)
            clustered[pair].append((probability, int(target)))
        all_pairs.update(clustered)
        ordered_pairs = sorted(clustered)
        probabilities = np.asarray(
            [
                probability
                for pair in ordered_pairs
                for probability, _target_value in clustered[pair]
            ],
            dtype=float,
        )
        labels = np.asarray(
            [
                target_value
                for pair in ordered_pairs
                for _probability, target_value in clustered[pair]
            ],
            dtype=int,
        )
        sample_weights = np.asarray(
            [
                1.0 / len(clustered[pair])
                for pair in ordered_pairs
                for _row in clustered[pair]
            ],
            dtype=float,
        )
        opportunity_probabilities = np.asarray(
            [max(value[0] for value in clustered[pair]) for pair in ordered_pairs],
            dtype=float,
        )
        opportunity_labels = np.asarray(
            [max(value[1] for value in clustered[pair]) for pair in ordered_pairs],
            dtype=int,
        )
        report = _probability_head_qualification(
            probabilities,
            labels,
            sample_weights=sample_weights,
            opportunity_probabilities=opportunity_probabilities,
            opportunity_labels=opportunity_labels,
        )
        reports[head_name] = report
        reasons.extend(
            f"{head_name}:{reason}" for reason in report.get("reasons", [])
        )
    return {
        "status": "ready" if not reasons and len(reports) == 2 else "model_unavailable",
        "stock_day_count": len(all_pairs),
        "heads": reports,
        "reasons": reasons,
    }


def serialize_preboard_model_bundle(
    bundle: PreboardModelBundle,
) -> dict[str, object]:
    payload = pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL)
    return {
        "format": PREBOARD_MODEL_ARTIFACT_FORMAT,
        "model_fingerprint": bundle.fingerprint,
        "payload_sha256": sha256(payload).hexdigest(),
        "payload": base64.b64encode(payload).decode("ascii"),
    }


def deserialize_preboard_model_bundle(
    artifact: Mapping[str, object],
) -> PreboardModelBundle:
    if artifact.get("format") != PREBOARD_MODEL_ARTIFACT_FORMAT:
        raise ValueError("unsupported preboard model artifact")
    try:
        payload = base64.b64decode(str(artifact.get("payload") or ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid preboard model payload") from exc
    if sha256(payload).hexdigest() != str(artifact.get("payload_sha256") or ""):
        raise ValueError("preboard model artifact checksum mismatch")
    restored = pickle.loads(payload)  # noqa: S301 - trusted internal database artifact
    if not isinstance(restored, PreboardModelBundle):
        raise ValueError("preboard model artifact has an invalid type")
    if restored.fingerprint != str(artifact.get("model_fingerprint") or ""):
        raise ValueError("preboard model fingerprint mismatch")
    return restored


def _fit_head(
    rows: Sequence[Mapping[str, object]],
    *,
    target_fields: Sequence[str],
    fit_dates: set[date],
    calibration_dates: set[date],
) -> tuple[_ProbabilityHead, dict[str, object]]:
    fit = _examples(rows, target_fields, fit_dates)
    calibration = _examples(rows, target_fields, calibration_dates)
    report: dict[str, object] = {
        "target_fields": list(target_fields),
        "fit_row_count": len(fit.rows),
        "fit_pair_count": len(fit.pair_weight_sums),
        "fit_class_counts": fit.class_counts,
        "fit_pair_weight_sum_min": fit.minimum_pair_weight,
        "fit_pair_weight_sum_max": fit.maximum_pair_weight,
        "calibration_row_count": len(calibration.rows),
        "calibration_pair_count": len(calibration.pair_weight_sums),
        "calibration_class_counts": calibration.class_counts,
        "calibration_pair_weight_sum_min": calibration.minimum_pair_weight,
        "calibration_pair_weight_sum_max": calibration.maximum_pair_weight,
    }
    if not fit.rows or len(fit.class_counts) < 2:
        report["status"] = "insufficient_fit_classes"
        return _ProbabilityHead("insufficient_fit_classes", None, None), report
    active_indices = _variable_feature_indices(fit.matrix)
    active_names = [MODEL_FEATURE_NAMES[index] for index in active_indices]
    dropped_names = [
        name
        for index, name in enumerate(MODEL_FEATURE_NAMES)
        if index not in set(active_indices)
    ]
    report.update(
        {
            "active_fit_feature_count": len(active_names),
            "active_fit_feature_names": active_names,
            "dropped_fit_feature_count": len(dropped_names),
            "dropped_fit_feature_names": dropped_names,
        }
    )
    if not active_indices:
        report["status"] = "insufficient_fit_features"
        return _ProbabilityHead("insufficient_fit_features", None, None), report
    fit_matrix = np.take(fit.matrix, active_indices, axis=1)
    monotonic_constraints = tuple(
        _monotonic_constraints()[index] for index in active_indices
    )
    estimator = HistGradientBoostingClassifier(
        **MODEL_PARAMETERS,
        monotonic_cst=monotonic_constraints,
    )
    estimator.fit(fit_matrix, fit.labels, sample_weight=fit.weights)
    if not calibration.rows or len(calibration.class_counts) < 2:
        report["status"] = "insufficient_calibration_classes"
        return (
            _ProbabilityHead(
                "insufficient_calibration_classes",
                estimator,
                None,
                active_indices,
            ),
            report,
        )
    if len(calibration.pair_weight_sums) < MINIMUM_CALIBRATION_PAIR_COUNT:
        report["status"] = "insufficient_calibration_pairs"
        return (
            _ProbabilityHead(
                "insufficient_calibration_pairs",
                estimator,
                None,
                active_indices,
            ),
            report,
        )
    calibration_matrix = np.take(calibration.matrix, active_indices, axis=1)
    raw = np.asarray(estimator.predict_proba(calibration_matrix)[:, 1], dtype=float)
    calibrator = IsotonicRegression(out_of_bounds="clip", increasing=True)
    calibrator.fit(raw, calibration.labels, sample_weight=calibration.weights)
    calibrated = np.asarray(calibrator.predict(raw), dtype=float)
    report.update(
        {
            "status": "ready",
            "calibration_brier": round(
                float(
                    np.average(
                        np.square(calibrated - calibration.labels),
                        weights=calibration.weights,
                    )
                ),
                10,
            ),
            "raw_probability_min": round(float(raw.min()), 10),
            "raw_probability_max": round(float(raw.max()), 10),
            "calibrated_probability_min": round(float(calibrated.min()), 10),
            "calibrated_probability_max": round(float(calibrated.max()), 10),
        }
    )
    return _ProbabilityHead("ready", estimator, calibrator, active_indices), report


@dataclass(frozen=True)
class _Examples:
    rows: tuple[dict[str, object], ...]
    matrix: np.ndarray
    labels: np.ndarray
    weights: np.ndarray
    class_counts: dict[str, int]
    pair_weight_sums: dict[tuple[date, str], float]

    @property
    def minimum_pair_weight(self) -> float | None:
        return (
            round(min(self.pair_weight_sums.values()), 10)
            if self.pair_weight_sums
            else None
        )

    @property
    def maximum_pair_weight(self) -> float | None:
        return (
            round(max(self.pair_weight_sums.values()), 10)
            if self.pair_weight_sums
            else None
        )


def _examples(
    rows: Sequence[Mapping[str, object]],
    target_fields: Sequence[str],
    allowed_dates: set[date],
) -> _Examples:
    accepted: list[tuple[dict[str, object], list[float], int, tuple[date, str]]] = []
    pair_counts: Counter[tuple[date, str]] = Counter()
    for raw in rows:
        row = dict(raw)
        trade_date = _row_date(row)
        symbol = str(row.get("vt_symbol") or "").strip()
        target = _target(row, target_fields)
        vector = model_feature_vector(row)
        if (
            trade_date not in allowed_dates
            or not symbol
            or not _model_input_eligible(row)
            or target is None
            or vector is None
        ):
            continue
        pair = (trade_date, symbol)
        accepted.append((row, vector, int(target), pair))
        pair_counts[pair] += 1
    vectors = [entry[1] for entry in accepted]
    labels = np.asarray([entry[2] for entry in accepted], dtype=int)
    weights = np.asarray(
        [1.0 / pair_counts[entry[3]] for entry in accepted],
        dtype=float,
    )
    pair_weight_sums: defaultdict[tuple[date, str], float] = defaultdict(float)
    for entry, weight in zip(accepted, weights, strict=True):
        pair_weight_sums[entry[3]] += float(weight)
    counts = Counter(int(value) for value in labels)
    return _Examples(
        rows=tuple(entry[0] for entry in accepted),
        matrix=(
            np.asarray(vectors, dtype=float)
            if vectors
            else np.empty((0, len(MODEL_FEATURE_NAMES)), dtype=float)
        ),
        labels=labels,
        weights=weights,
        class_counts={
            name: int(counts.get(value, 0))
            for name, value in (("negative", 0), ("positive", 1))
            if counts.get(value, 0)
        },
        pair_weight_sums=dict(pair_weight_sums),
    )


def _monotonic_constraints() -> list[int]:
    return [
        1 if name == "gain_pct" else -1 if name == "distance_to_limit_pct" else 0
        for name in MODEL_FEATURE_NAMES
    ]


def _variable_feature_indices(matrix: np.ndarray) -> tuple[int, ...]:
    if matrix.ndim != 2 or matrix.shape[1] != len(MODEL_FEATURE_NAMES):
        return ()
    active: list[int] = []
    for index in range(matrix.shape[1]):
        column = matrix[:, index]
        finite = column[np.isfinite(column)]
        if finite.size >= 2 and np.unique(finite).size >= 2:
            active.append(index)
    return tuple(active)


def _training_fingerprint(
    rows: Sequence[Mapping[str, object]],
    fit_dates: Sequence[date],
    calibration_dates: Sequence[date],
) -> str:
    allowed = set(fit_dates) | set(calibration_dates)
    payload = []
    for row in rows:
        trade_date = _row_date(row)
        if trade_date not in allowed:
            continue
        values = row.get("feature_values")
        values = values if isinstance(values, Mapping) else {}
        payload.append(
            {
                "trade_date": trade_date.isoformat(),
                "vt_symbol": str(row.get("vt_symbol") or ""),
                "decision_at": str(row.get("decision_at") or row.get("signal_at") or ""),
                "quality_gate_passed": row.get("quality_gate_passed") is True,
                "features": {
                    name: _canonical_number(values.get(name))
                    for name in MODEL_FEATURE_NAMES
                },
                "formal_touch_within_3m": _target(
                    row,
                    HEAD_TARGETS["touch_3m"],
                ),
                "eventual_formal_touch": _target(
                    row,
                    HEAD_TARGETS["eventual_touch"],
                ),
            }
        )
    payload.sort(
        key=lambda item: (
            item["trade_date"],
            item["decision_at"],
            item["vt_symbol"],
        )
    )
    return _fingerprint(
        {
            "feature_version": PREBOARD_DECISION_VERSION,
            "feature_names": list(MODEL_FEATURE_NAMES),
            "fit_dates": [value.isoformat() for value in fit_dates],
            "calibration_dates": [value.isoformat() for value in calibration_dates],
            "rows": payload,
        }
    )


def _model_fingerprint(
    *,
    status: str,
    fit_dates: Sequence[date],
    calibration_dates: Sequence[date],
    training_input_fingerprint: str,
    reports: Mapping[str, Mapping[str, object]],
) -> str:
    return _fingerprint(
        {
            "model_version": PREBOARD_DECISION_VERSION,
            "feature_version": PREBOARD_DECISION_VERSION,
            "feature_names": list(MODEL_FEATURE_NAMES),
            "parameters": MODEL_PARAMETERS,
            "monotonic_constraints": _monotonic_constraints(),
            "status": status,
            "fit_dates": [value.isoformat() for value in fit_dates],
            "calibration_dates": [value.isoformat() for value in calibration_dates],
            "training_input_fingerprint": training_input_fingerprint,
            "head_reports": reports,
        }
    )


def _prior_projection(row: Mapping[str, object]) -> dict[str, object]:
    return {
        field: row.get(field)
        for field in (
            "expected_d1_net_return_pct",
            "d1_win_probability",
            "seal_probability_given_touch",
            "d1_win_probability_given_seal",
        )
    }


def _target(
    row: Mapping[str, object],
    fields: Sequence[str],
) -> bool | None:
    for field in fields:
        value = row.get(field)
        if isinstance(value, bool):
            return value
    return None


def _model_input_eligible(row: Mapping[str, object]) -> bool:
    decision_at = _row_datetime(row.get("decision_at") or row.get("signal_at"))
    known_at = _row_datetime(row.get("known_at"))
    fingerprint = str(row.get("feature_fingerprint") or "")
    return bool(
        row.get("quality_gate_passed") is True
        and is_observable_first_board(row)
        and is_strictly_preboard(row)
        and row.get("feature_contract_version") == PREBOARD_DECISION_VERSION
        and row.get("feature_status") == "scoreable"
        and fingerprint.startswith("sha256:")
        and len(fingerprint) == 71
        and decision_at is not None
        and known_at is not None
        and _datetime_not_after(known_at, decision_at)
    )


def _probability_head_qualification(
    probabilities: np.ndarray,
    labels: np.ndarray,
    *,
    sample_weights: np.ndarray | None = None,
    opportunity_probabilities: np.ndarray | None = None,
    opportunity_labels: np.ndarray | None = None,
) -> dict[str, object]:
    weights = (
        np.asarray(sample_weights, dtype=float)
        if sample_weights is not None
        else np.ones(labels.size, dtype=float)
    )
    opportunity_scores = (
        np.asarray(opportunity_probabilities, dtype=float)
        if opportunity_probabilities is not None
        else probabilities
    )
    opportunity_targets = (
        np.asarray(opportunity_labels, dtype=int)
        if opportunity_labels is not None
        else labels
    )
    if probabilities.size != labels.size or weights.size != labels.size:
        raise ValueError("probability qualification arrays differ in size")
    if opportunity_scores.size != opportunity_targets.size:
        raise ValueError("opportunity qualification arrays differ in size")
    positives = int(np.sum(opportunity_targets == 1))
    negatives = int(np.sum(opportunity_targets == 0))
    reasons: list[str] = []
    if positives < MINIMUM_QUALIFICATION_CLASS_STOCK_DAYS:
        reasons.append(
            f"positive_stock_days_below_{MINIMUM_QUALIFICATION_CLASS_STOCK_DAYS}"
        )
    if negatives < MINIMUM_QUALIFICATION_CLASS_STOCK_DAYS:
        reasons.append(
            f"negative_stock_days_below_{MINIMUM_QUALIFICATION_CLASS_STOCK_DAYS}"
        )
    if labels.size == 0:
        return {
            "status": "model_unavailable",
            "stock_day_count": 0,
            "point_count": 0,
            "positive_stock_days": 0,
            "negative_stock_days": 0,
            "base_rate": None,
            "opportunity_base_rate": None,
            "brier": None,
            "climatology_brier": None,
            "brier_skill": None,
            "pr_auc": None,
            "top_quintile_count": 0,
            "top_quintile_rate": None,
            "top_quintile_lift": None,
            "quantile_touch_rates": [],
            "calibration_points": [],
            "reasons": reasons,
        }
    weight_sum = float(np.sum(weights))
    if weight_sum <= 0:
        raise ValueError("probability qualification weights must be positive")
    base_rate = float(np.average(labels, weights=weights))
    brier = float(np.average(np.square(probabilities - labels), weights=weights))
    climatology_brier = float(
        np.average(np.square(base_rate - labels), weights=weights)
    )
    pr_auc = (
        float(
            average_precision_score(
                labels,
                probabilities,
                sample_weight=weights,
            )
        )
        if np.any(labels == 1) and np.any(labels == 0)
        else base_rate
    )
    opportunity_base_rate = (
        float(np.mean(opportunity_targets))
        if opportunity_targets.size
        else 0.0
    )
    top_count = max(ceil(opportunity_targets.size * 0.2), 1)
    top_indices = np.argsort(-opportunity_scores, kind="stable")[:top_count]
    top_rate = float(np.mean(opportunity_targets[top_indices]))
    top_lift = (
        top_rate / opportunity_base_rate if opportunity_base_rate > 0 else 0.0
    )
    brier_skill = (
        1.0 - brier / climatology_brier
        if climatology_brier > 0
        else None
    )
    if not brier < climatology_brier:
        reasons.append("brier_not_better_than_climatology")
    if not pr_auc > base_rate:
        reasons.append("pr_auc_not_above_base_rate")
    if not top_lift > 1.0:
        reasons.append("top_quintile_lift_not_above_one")
    return {
        "status": "ready" if not reasons else "model_unavailable",
        "evaluation_unit": "stock_day_equal_weighted_point_time",
        "stock_day_count": int(opportunity_targets.size),
        "point_count": int(labels.size),
        "stock_day_weight_sum": round(weight_sum, 10),
        "positive_stock_days": positives,
        "negative_stock_days": negatives,
        "base_rate": round(base_rate, 10),
        "opportunity_base_rate": round(opportunity_base_rate, 10),
        "brier": round(brier, 10),
        "climatology_brier": round(climatology_brier, 10),
        "brier_skill": (
            round(brier_skill, 10) if brier_skill is not None else None
        ),
        "pr_auc": round(pr_auc, 10),
        "top_quintile_count": top_count,
        "top_quintile_rate": round(top_rate, 10),
        "top_quintile_lift": round(top_lift, 10),
        "quantile_touch_rates": _quantile_touch_rates(
            opportunity_scores,
            opportunity_targets,
        ),
        "calibration_points": _calibration_points(
            probabilities,
            labels,
            weights=weights,
        ),
        "reasons": reasons,
    }


def _quantile_touch_rates(
    probabilities: np.ndarray,
    labels: np.ndarray,
) -> list[dict[str, object]]:
    ordered = np.argsort(probabilities, kind="stable")
    groups = np.array_split(ordered, min(5, max(int(labels.size), 1)))
    return [
        {
            "quantile": index,
            "count": int(group.size),
            "minimum_probability": round(float(np.min(probabilities[group])), 10),
            "maximum_probability": round(float(np.max(probabilities[group])), 10),
            "mean_probability": round(float(np.mean(probabilities[group])), 10),
            "touch_rate": round(float(np.mean(labels[group])), 10),
        }
        for index, group in enumerate(groups, start=1)
        if group.size
    ]


def _calibration_points(
    probabilities: np.ndarray,
    labels: np.ndarray,
    *,
    weights: np.ndarray | None = None,
) -> list[dict[str, object]]:
    sample_weights = (
        np.asarray(weights, dtype=float)
        if weights is not None
        else np.ones(labels.size, dtype=float)
    )
    points: list[dict[str, object]] = []
    for index in range(10):
        lower = index / 10
        upper = (index + 1) / 10
        mask = (
            (probabilities >= lower) & (probabilities <= upper)
            if index == 9
            else (probabilities >= lower) & (probabilities < upper)
        )
        if not np.any(mask):
            continue
        points.append(
            {
                "bin": index + 1,
                "lower_probability": lower,
                "upper_probability": upper,
                "count": int(np.sum(mask)),
                "stock_day_weight": round(float(np.sum(sample_weights[mask])), 10),
                "mean_probability": round(
                    float(
                        np.average(
                            probabilities[mask],
                            weights=sample_weights[mask],
                        )
                    ),
                    10,
                ),
                "observed_touch_rate": round(
                    float(
                        np.average(
                            labels[mask],
                            weights=sample_weights[mask],
                        )
                    ),
                    10,
                ),
            }
        )
    return points


def _row_date(row: Mapping[str, object]) -> date | None:
    value = row.get("trade_date") or row.get("signal_date")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _row_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _datetime_not_after(value: datetime, cutoff: datetime) -> bool:
    if value.tzinfo is None and cutoff.tzinfo is not None:
        value = value.replace(tzinfo=cutoff.tzinfo)
    elif value.tzinfo is not None and cutoff.tzinfo is None:
        value = value.replace(tzinfo=None)
    return value <= cutoff


def _canonical_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return round(parsed, 12) if isfinite(parsed) else None


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()
