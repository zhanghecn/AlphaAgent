"""Causal pre-board replay layered on the current limit-up strategy filters."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from statistics import median
from typing import Any

import numpy as np

from alphaagent.server.services.execution import cash_ledger
from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.lane_research import (
    FIRST_BOARD_MOMENTUM_MIN_SCORE,
    evaluate_lane_candidate,
)
from alphaagent.server.services.limit_up.lane_repository import (
    FinancialIndex,
    financial_risk_as_of,
    financial_snapshot_as_of,
)
from alphaagent.server.services.limit_up.preboard_momentum import build_prefix_rows


STUDY_VERSION = "limit-up-current-strategy-preboard-replay-v2"
REFERENCE_POSITION_CASH = 50_000.0
IGNITION_THRESHOLDS = tuple(round(value / 100, 2) for value in range(50, 100, 5))
IGNITION_FEATURE_NAMES = (
    "gain_pct",
    "return_5m_pct",
    "return_15m_pct",
    "acceleration_pct",
    "distance_to_limit_pct",
    "session_drawdown_pct",
    "bar_close_location",
    "volume_ratio_30m",
    "amount_ratio_30m",
    "amount_acceleration_ratio",
    "support_score",
    "entry_quality_score",
    "rank_score",
)
_STATIC_CANDIDATE_FIELDS = (
    "industry_id",
    "industry_name",
    "auction_gap_pct",
    "prior_streak",
    "prior_break_streak",
    "prior_limit_count_126",
    "prior_touch_count_126",
    "prior_limit_count_5",
    "prior_limit_count_10",
    "prior_seal_success_rate_126",
    "trade_days_since_prior_limit",
    "pullback_from_prior_limit_pct",
    "prior_position_120",
    "prior_change_pct",
    "prior_open_gap_pct",
    "prior_low_change_pct",
    "prior_amplitude_pct",
    "prior_return_5d_pct",
    "prior_return_20d_pct",
    "prior_turnover_rate",
    "prior_amount_ratio_5d",
    "prior_industry_change_pct",
    "prior_industry_return_5d_pct",
    "prior_industry_advancing_rate",
    "prior_industry_turnover_ratio_5d",
    "prior_industry_sealed_count",
    "prior_industry_sealed_rate",
    "prior_industry_heat_score",
    "prior_industry_heat_rank",
    "prior_industry_count",
    "prior_industry_leadership_score",
    "prior_industry_leader_rank",
    "prior_industry_stock_count",
    "prior_market_phase",
    "prior_market_advancing_rate",
    "prior_market_sealed_count",
    "prior_market_failed_rate",
    "prior_market_max_board",
    "prior_market_first_board_count",
    "prior_market_one_to_two_rate",
    "prior_market_two_to_three_rate",
)
_STATIC_UPPER_BOUND_SIGNAL_TIME = "10:30:00"
_STATIC_UPPER_BOUND_PATH = {
    "signal_time": _STATIC_UPPER_BOUND_SIGNAL_TIME,
    "last_point_time": _STATIC_UPPER_BOUND_SIGNAL_TIME,
    "point_count": 60,
    "last_pct": 9.0,
    "maximum_pct": 9.0,
    "minimum_pct": 0.0,
    "recent_15m_min_pct": 3.0,
    "recent_15m_change_pct": 6.0,
    "recent_15m_range_pct": 6.0,
    "recent_15m_drawdown_pct": 0.0,
    "recent_30m_min_pct": 0.0,
    "recent_30m_change_pct": 9.0,
    "touch_count": 0,
    "break_count": 0,
    "reseal_count": 0,
    "is_at_limit": False,
    "approach_3point_pct": 6.0,
}


@dataclass(frozen=True)
class IgnitionFit:
    """Fit-only model state with an auditable feature fingerprint."""

    status: str
    pipeline: Any | None
    training_row_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    coefficient_by_feature: dict[str, float]
    intercept: float | None

    def probability(self, features: Mapping[str, object]) -> float | None:
        vector = _feature_vector(features)
        if self.pipeline is None or vector is None:
            return None
        return float(
            self.pipeline.predict_proba(np.asarray([vector], dtype=float))[0, 1]
        )


@dataclass(frozen=True)
class IgnitionThreshold:
    status: str
    threshold: float | None
    minimum_signal_count: int
    calibration_dates: tuple[str, ...]
    selected_metrics: dict[str, object] | None
    metrics_by_threshold: tuple[dict[str, object], ...]


def build_lane_prefix(
    bars: Sequence[Mapping[str, object]],
    index: int,
    *,
    previous_close: float,
    bar_minutes: int = 5,
) -> dict[str, object]:
    """Project a completed five-minute prefix into the shared lane feature shape."""

    if bar_minutes not in {1, 5}:
        raise ValueError("bar_minutes must be 1 or 5")
    ordered = sorted(
        (dict(row) for row in bars),
        key=lambda row: _as_datetime(row.get("bar_time")) or datetime.max,
    )
    if previous_close <= 0 or index < 0 or index >= len(ordered):
        return _empty_lane_prefix()
    return _build_lane_prefixes(
        ordered[: index + 1],
        previous_close=previous_close,
        bar_minutes=bar_minutes,
    )[-1]


def _build_lane_prefixes(
    ordered: Sequence[Mapping[str, object]],
    *,
    previous_close: float,
    bar_minutes: int,
) -> list[dict[str, object]]:
    recent_15m_count = 15 // bar_minutes + 1
    recent_30m_count = 30 // bar_minutes + 1
    values: list[float] = []
    maximum: float | None = None
    minimum: float | None = None
    touch_count = 0
    break_count = 0
    reseal_count = 0
    touched = False
    broken = False
    rows: list[dict[str, object]] = []

    for bar in ordered:
        value = _return_pct(previous_close, _number(bar.get("close_price")))
        if value is not None:
            values.append(value)
            maximum = value if maximum is None else max(maximum, value)
            minimum = value if minimum is None else min(minimum, value)
            if value >= 9.7:
                if not touched:
                    touch_count += 1
                    touched = True
                elif broken:
                    touch_count += 1
                    reseal_count += 1
                broken = False
            elif touched and value < 9.2 and not broken:
                break_count += 1
                broken = True
        if not values:
            rows.append(_empty_lane_prefix())
            continue

        recent_15m = values[-recent_15m_count:]
        recent_30m = values[-recent_30m_count:]
        signal_at = _as_datetime(bar.get("bar_time"))
        signal_time = signal_at.strftime("%H:%M:%S") if signal_at else None
        rows.append(
            {
                "signal_time": signal_time,
                "last_point_time": signal_time,
                "point_count": len(values),
                "last_pct": _rounded(values[-1]),
                "maximum_pct": _rounded(maximum),
                "minimum_pct": _rounded(minimum),
                "recent_15m_min_pct": _rounded(min(recent_15m)),
                "recent_15m_change_pct": _change(recent_15m),
                "recent_15m_range_pct": _range(recent_15m),
                "recent_15m_drawdown_pct": _drawdown(recent_15m),
                "recent_30m_min_pct": _rounded(min(recent_30m)),
                "recent_30m_change_pct": _change(recent_30m),
                "touch_count": touch_count,
                "break_count": break_count,
                "reseal_count": reseal_count,
                "is_at_limit": values[-1] >= 9.7,
                "approach_3point_pct": _change(recent_15m),
            }
        )
    return rows


def build_strategy_prefix_rows(
    manifest_row: Mapping[str, object],
    feature_row: Mapping[str, object],
    bars: Sequence[Mapping[str, object]],
    *,
    financial_index: FinancialIndex,
    bar_minutes: int = 5,
) -> list[dict[str, object]]:
    """Run every completed prefix through the current lane and profitability gates."""

    ordered = sorted(
        (dict(row) for row in bars),
        key=lambda row: _as_datetime(row.get("bar_time")) or datetime.max,
    )
    previous_close = _number(manifest_row.get("previous_close"))
    signal_date = _as_date(manifest_row.get("trade_date"))
    symbol = str(manifest_row.get("vt_symbol") or "")
    if (
        previous_close is None
        or previous_close <= 0
        or signal_date is None
        or not symbol
    ):
        return []
    prefix_rows = build_prefix_rows(
        manifest_row,
        ordered,
        bar_minutes=bar_minutes,
    )
    bar_index = {
        value.isoformat(): index
        for index, row in enumerate(ordered)
        if (value := _as_datetime(row.get("bar_time"))) is not None
    }
    lane_prefixes = _build_lane_prefixes(
        ordered,
        previous_close=previous_close,
        bar_minutes=bar_minutes,
    )

    financial_snapshot = feature_row.get("financial_snapshot")
    if not isinstance(financial_snapshot, Mapping):
        financial_snapshot = financial_snapshot_as_of(
            financial_index,
            symbol,
            signal_date,
        )
    financial_risk = feature_row.get("financial_risk")
    if not isinstance(financial_risk, Mapping):
        financial_risk = financial_risk_as_of(
            financial_index,
            symbol,
            signal_date,
        )
    static_candidate = _static_strategy_candidate(
        manifest_row,
        feature_row,
        financial_snapshot=financial_snapshot,
        financial_risk=financial_risk,
    )
    profitability_gate = scheduled_execution.first_board_profitability_gate(
        {
            "lane": "first_board",
            **_profitability_evidence(manifest_row),
        }
    )

    results: list[dict[str, object]] = []
    for raw_prefix in prefix_rows:
        prefix = dict(raw_prefix)
        index = bar_index.get(str(prefix.get("signal_at") or ""))
        if index is None:
            continue
        lane_prefix = lane_prefixes[index]
        candidate = _strategy_candidate_for_prefix(
            static_candidate,
            prefix,
            lane_prefix,
        )
        evaluated = evaluate_lane_candidate(candidate)
        support_score = _number(evaluated.get("support_score"))
        prefix_features = prefix.get("features")
        prefix_features = (
            prefix_features if isinstance(prefix_features, Mapping) else {}
        )
        observable_gain = _number(prefix_features.get("gain_pct"))
        shared_passed = bool(
            evaluated.get("decision") == "eligible"
            and profitability_gate.get("profitability_gate_passed") is True
            and support_score is not None
            and support_score >= FIRST_BOARD_MOMENTUM_MIN_SCORE
            and observable_gain is not None
            and observable_gain >= 3.0
            and prefix.get("before_first_limit_touch") is True
        )
        net_return = (
            _net_return_pct(
                _number(prefix.get("entry_price")),
                _number(manifest_row.get("d1_close_price")),
                limit_price=_number(manifest_row.get("limit_price")),
            )
            if prefix.get("fillable") is True
            else None
        )
        ignition_features = _ignition_features(
            prefix,
            evaluated,
            ordered,
            index,
            bar_minutes=bar_minutes,
        )
        results.append(
            {
                **prefix,
                **profitability_gate,
                "lane": "first_board",
                "board_lane": "first_board",
                "shared_lane_decision": evaluated.get("decision"),
                "shared_lane_blockers": list(evaluated.get("blockers") or []),
                "shared_lane_favorable_factors": list(
                    evaluated.get("favorable_factors") or []
                ),
                "first_board_route": evaluated.get("first_board_route"),
                "support_score": support_score,
                "entry_quality_score": _number(evaluated.get("entry_quality_score")),
                "rank_score": _number(evaluated.get("rank_score")),
                "current_momentum_gate_passed": bool(
                    support_score is not None
                    and support_score >= FIRST_BOARD_MOMENTUM_MIN_SCORE
                ),
                "shared_strategy_passed": shared_passed,
                "ignition_features": ignition_features,
                "net_return_pct": net_return,
                "target_positive": bool(
                    manifest_row.get("touched_limit") is True
                    and manifest_row.get("sealed_limit") is True
                    and net_return is not None
                    and net_return > 0
                ),
                "strategy_filter_version": STUDY_VERSION,
            }
        )
    return results


def evaluate_static_shared_strategy_upper_bound(
    manifest_row: Mapping[str, object],
    feature_row: Mapping[str, object],
    *,
    financial_index: FinancialIndex,
) -> dict[str, object]:
    """Test static gates with a legal path that exceeds every support threshold.

    The result is a necessary-condition prefilter only. A retained stock-day still
    has to pass its real completed-minute path. Because all path-dependent gates
    see a valid 10:30 signal and support above 55, an actual shared-strategy pass
    cannot be rejected here.
    """

    signal_date = _as_date(manifest_row.get("trade_date"))
    symbol = str(manifest_row.get("vt_symbol") or "")
    if signal_date is None or not symbol:
        return {
            "static_upper_bound_passed": False,
            "profitability_gate_passed": False,
            "profitability_gate_reason": "invalid_static_identity",
            "shared_lane_decision": "blocked",
            "shared_lane_blockers": ["invalid_static_identity"],
            "support_score": None,
        }

    financial_snapshot = feature_row.get("financial_snapshot")
    if not isinstance(financial_snapshot, Mapping):
        financial_snapshot = financial_snapshot_as_of(
            financial_index,
            symbol,
            signal_date,
        )
    financial_risk = feature_row.get("financial_risk")
    if not isinstance(financial_risk, Mapping):
        financial_risk = financial_risk_as_of(
            financial_index,
            symbol,
            signal_date,
        )
    static_candidate = _static_strategy_candidate(
        manifest_row,
        feature_row,
        financial_snapshot=financial_snapshot,
        financial_risk=financial_risk,
    )
    candidate = _strategy_candidate_for_prefix(
        static_candidate,
        {
            "signal_time": _STATIC_UPPER_BOUND_SIGNAL_TIME,
            "entry_time": "10:31:00",
            "entry_price": _number(manifest_row.get("limit_price")),
        },
        _STATIC_UPPER_BOUND_PATH,
    )
    evaluated = evaluate_lane_candidate(candidate)
    profitability_gate = scheduled_execution.first_board_profitability_gate(
        {
            "lane": "first_board",
            **_profitability_evidence(manifest_row),
        }
    )
    support_score = _number(evaluated.get("support_score"))
    passed = bool(
        profitability_gate.get("profitability_gate_passed") is True
        and evaluated.get("decision") == "eligible"
        and support_score is not None
        and support_score >= FIRST_BOARD_MOMENTUM_MIN_SCORE
    )
    return {
        "static_upper_bound_passed": passed,
        "profitability_gate_passed": profitability_gate.get(
            "profitability_gate_passed"
        ),
        "profitability_gate_reason": profitability_gate.get(
            "profitability_gate_reason"
        ),
        "shared_lane_decision": evaluated.get("decision"),
        "shared_lane_blockers": list(evaluated.get("blockers") or []),
        "support_score": support_score,
    }


def first_current_support_signal(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    """Return the first prefix passing the current shared support-55 path."""

    for raw in sorted(rows, key=_row_sort_key):
        if raw.get("shared_strategy_passed") is True:
            return {
                **dict(raw),
                "algorithm": "current_support_55",
                "signal_kind": "momentum",
            }
    return None


def fit_ignition_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
) -> IgnitionFit:
    """Fit only shared-strategy prefixes from the declared chronological block."""

    vectors: list[list[float]] = []
    targets: list[int] = []
    used_dates: set[date] = set()
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        features = row.get("ignition_features")
        features = features if isinstance(features, Mapping) else {}
        vector = _feature_vector(features)
        if (
            signal_date not in fit_dates
            or row.get("shared_strategy_passed") is not True
            or vector is None
        ):
            continue
        vectors.append(vector)
        targets.append(int(bool(row.get("target_positive"))))
        used_dates.add(signal_date)

    counts = Counter(targets)
    class_counts = {
        "negative": int(counts.get(0, 0)),
        "positive": int(counts.get(1, 0)),
    }
    date_texts = tuple(value.isoformat() for value in sorted(used_dates))
    if not vectors or len(counts) < 2:
        return IgnitionFit(
            status="blocked_by_training_classes",
            pipeline=None,
            training_row_count=len(vectors),
            class_counts=class_counts,
            fit_dates=date_texts,
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
    matrix = np.asarray(vectors, dtype=float)
    labels = np.asarray(targets, dtype=int)
    pipeline.fit(matrix, labels)
    logistic = pipeline.named_steps["logistic"]
    coefficients = {
        name: round(float(value), 12)
        for name, value in zip(
            IGNITION_FEATURE_NAMES,
            logistic.coef_[0],
            strict=True,
        )
    }
    return IgnitionFit(
        status="ready",
        pipeline=pipeline,
        training_row_count=len(vectors),
        class_counts=class_counts,
        fit_dates=date_texts,
        coefficient_by_feature=coefficients,
        intercept=round(float(logistic.intercept_[0]), 12),
    )


def calibrate_ignition_threshold(
    rows: Sequence[Mapping[str, object]],
    model: IgnitionFit,
    *,
    calibration_dates: set[date],
    minimum_signal_count: int,
) -> IgnitionThreshold:
    """Freeze one threshold from calibration dates without reading validation."""

    date_texts = tuple(value.isoformat() for value in sorted(calibration_dates))
    metrics: list[dict[str, object]] = []
    for threshold in IGNITION_THRESHOLDS:
        signals = _first_signals_by_pair(
            rows,
            model,
            threshold=threshold,
            allowed_dates=calibration_dates,
        )
        positives = sum(bool(row.get("target_positive")) for row in signals)
        available_positives = _positive_pair_count(rows, calibration_dates)
        precision = _ratio(positives, len(signals))
        recall = _ratio(positives, available_positives)
        f_half = _f_beta(precision, recall, beta=0.5)
        metrics.append(
            {
                "threshold": threshold,
                "signal_count": len(signals),
                "positive_count": positives,
                "precision_pct": _pct(precision),
                "recall_pct": _pct(recall),
                "f0_5": None if f_half is None else round(f_half, 8),
            }
        )
    qualified = [
        row
        for row in metrics
        if int(row["signal_count"]) >= max(int(minimum_signal_count), 1)
        and row["f0_5"] is not None
    ]
    if not qualified or model.status != "ready":
        return IgnitionThreshold(
            status=(
                "blocked_by_model"
                if model.status != "ready"
                else "blocked_by_signal_count"
            ),
            threshold=None,
            minimum_signal_count=max(int(minimum_signal_count), 1),
            calibration_dates=date_texts,
            selected_metrics=None,
            metrics_by_threshold=tuple(metrics),
        )
    selected = max(
        qualified,
        key=lambda row: (
            float(row["f0_5"] or 0.0),
            float(row["precision_pct"] or 0.0),
            int(row["signal_count"]),
            float(row["threshold"]),
        ),
    )
    return IgnitionThreshold(
        status="ready",
        threshold=float(selected["threshold"]),
        minimum_signal_count=max(int(minimum_signal_count), 1),
        calibration_dates=date_texts,
        selected_metrics=dict(selected),
        metrics_by_threshold=tuple(metrics),
    )


def first_ignition_signal(
    rows: Sequence[Mapping[str, object]],
    model: IgnitionFit,
    *,
    threshold: float,
) -> dict[str, object] | None:
    """Return the first causal model pass, never a later maximum probability."""

    if model.status != "ready":
        return None
    for raw in sorted(rows, key=_row_sort_key):
        if raw.get("shared_strategy_passed") is not True:
            continue
        features = raw.get("ignition_features")
        features = features if isinstance(features, Mapping) else {}
        probability = model.probability(features)
        if probability is not None and probability >= threshold:
            return {
                **dict(raw),
                "algorithm": "post_filter_ignition",
                "signal_kind": "momentum",
                "model_probability": round(probability, 6),
                "rank_score": round(probability * 100, 6),
            }
    return None


def _static_strategy_candidate(
    manifest_row: Mapping[str, object],
    feature_row: Mapping[str, object],
    *,
    financial_snapshot: Mapping[str, object] | None,
    financial_risk: Mapping[str, object],
) -> dict[str, object]:
    candidate = {
        key: _plain_value(feature_row.get(key)) for key in _STATIC_CANDIDATE_FIELDS
    }
    candidate.update(
        {
            "vt_symbol": str(manifest_row.get("vt_symbol") or ""),
            "name": str(manifest_row.get("name") or ""),
            "target_board": 1,
            "prior_streak": 0,
            "previous_limit_up": bool(manifest_row.get("prior_day_limit_up")),
            "signal_kind": "momentum",
            "financial_snapshot": (
                dict(financial_snapshot)
                if isinstance(financial_snapshot, Mapping)
                else None
            ),
            "financial_risk": dict(financial_risk),
            "limit_price": _number(manifest_row.get("limit_price")),
            "source_mode": "complete_5m_prefix_current_strategy_proxy",
            "has_l2": False,
        }
    )
    return candidate


def _strategy_candidate_for_prefix(
    static_candidate: Mapping[str, object],
    prefix: Mapping[str, object],
    lane_prefix: Mapping[str, object],
) -> dict[str, object]:
    return {
        **static_candidate,
        "signal_time": str(prefix.get("signal_time") or ""),
        "buy_time": str(prefix.get("entry_time") or ""),
        "path_prefix": dict(lane_prefix),
        "entry_price": _number(prefix.get("entry_price")),
    }


def _profitability_evidence(row: Mapping[str, object]) -> dict[str, object]:
    return {
        key: _plain_value(row.get(key))
        for key in (
            "stock_d1_sample_count",
            "stock_d1_win_count",
            "stock_d1_win_rate",
            "stock_d1_average_return_pct",
            "stock_gene_combined_win_rate",
        )
    }


def _ignition_features(
    prefix: Mapping[str, object],
    evaluated: Mapping[str, object],
    bars: Sequence[Mapping[str, object]],
    index: int,
    *,
    bar_minutes: int = 5,
) -> dict[str, float | None]:
    features = prefix.get("features")
    features = features if isinstance(features, Mapping) else {}
    close_price = _number(bars[index].get("close_price"))
    limit_price = _number(prefix.get("limit_price"))
    prior_count = 30 // bar_minutes
    prior_six = bars[max(0, index - prior_count) : index]
    prior_amounts = [
        value
        for row in prior_six
        if (value := _number(row.get("turnover"))) is not None and value > 0
    ]
    current_amount = _number(bars[index].get("turnover"))
    prior_amount = _number(bars[index - 1].get("turnover")) if index > 0 else None
    prior_amount_median = (
        median(prior_amounts) if len(prior_amounts) == prior_count else None
    )
    result = {
        "gain_pct": _number(features.get("gain_pct")),
        "return_5m_pct": _number(features.get("return_5m_pct")),
        "return_15m_pct": _number(features.get("return_15m_pct")),
        "acceleration_pct": _number(features.get("acceleration_pct")),
        "distance_to_limit_pct": (
            _return_pct(close_price, limit_price)
            if close_price is not None and close_price > 0
            else None
        ),
        "session_drawdown_pct": _number(features.get("session_drawdown_pct")),
        "bar_close_location": _number(features.get("bar_close_location")),
        "volume_ratio_30m": _number(features.get("volume_ratio_30m")),
        "amount_ratio_30m": (
            current_amount / prior_amount_median
            if current_amount is not None
            and current_amount > 0
            and prior_amount_median is not None
            and prior_amount_median > 0
            else None
        ),
        "amount_acceleration_ratio": (
            current_amount / prior_amount
            if current_amount is not None
            and current_amount > 0
            and prior_amount is not None
            and prior_amount > 0
            else None
        ),
        "support_score": _number(evaluated.get("support_score")),
        "entry_quality_score": _number(evaluated.get("entry_quality_score")),
        "rank_score": _number(evaluated.get("rank_score")),
    }
    return {key: _rounded(value) for key, value in result.items()}


def _first_signals_by_pair(
    rows: Sequence[Mapping[str, object]],
    model: IgnitionFit,
    *,
    threshold: float,
    allowed_dates: set[date],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, date], list[Mapping[str, object]]] = {}
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        symbol = str(row.get("vt_symbol") or "")
        if signal_date not in allowed_dates or not symbol:
            continue
        grouped.setdefault((symbol, signal_date), []).append(row)
    signals: list[dict[str, object]] = []
    for pair in sorted(grouped, key=lambda item: (item[1], item[0])):
        signal = first_ignition_signal(grouped[pair], model, threshold=threshold)
        if signal is not None:
            signals.append(signal)
    return signals


def _positive_pair_count(
    rows: Sequence[Mapping[str, object]],
    allowed_dates: set[date],
) -> int:
    return len(
        {
            (str(row.get("vt_symbol") or ""), signal_date)
            for row in rows
            if (signal_date := _as_date(row.get("signal_date"))) in allowed_dates
            and row.get("shared_strategy_passed") is True
            and row.get("target_positive") is True
        }
    )


def _feature_vector(features: Mapping[str, object]) -> list[float] | None:
    values = [_number(features.get(name)) for name in IGNITION_FEATURE_NAMES]
    if any(value is None or not isfinite(value) for value in values):
        return None
    return [float(value) for value in values if value is not None]


def _net_return_pct(
    entry_price: float | None,
    exit_price: float | None,
    *,
    limit_price: float | None,
) -> float | None:
    if entry_price is None or entry_price <= 0 or exit_price is None or exit_price <= 0:
        return None
    buy = cash_ledger.calculate_buy_execution(
        raw_price=entry_price,
        cash=REFERENCE_POSITION_CASH,
        target_cash=REFERENCE_POSITION_CASH,
        commission_rate=0.0003,
        slippage_bps=10.0,
        lot_size=100,
        minimum_commission=5.0,
        transfer_fee_rate=0.00001,
        max_price=limit_price,
    )
    if buy.volume <= 0:
        return None
    sell = cash_ledger.calculate_sell_execution(
        raw_price=exit_price,
        volume=buy.volume,
        cost_price=buy.price,
        commission_rate=0.0003,
        stamp_tax_rate=0.0005,
        slippage_bps=10.0,
        minimum_commission=5.0,
        transfer_fee_rate=0.00001,
    )
    cash_cost = buy.amount + buy.fee
    return round((sell.cash_delta - cash_cost) / cash_cost * 100, 6)


def _empty_lane_prefix() -> dict[str, object]:
    return {
        "signal_time": None,
        "last_point_time": None,
        "point_count": 0,
        "last_pct": None,
        "maximum_pct": None,
        "minimum_pct": None,
        "recent_15m_min_pct": None,
        "recent_15m_change_pct": None,
        "recent_15m_range_pct": None,
        "recent_15m_drawdown_pct": None,
        "recent_30m_min_pct": None,
        "recent_30m_change_pct": None,
        "touch_count": 0,
        "break_count": 0,
        "reseal_count": 0,
        "is_at_limit": False,
        "approach_3point_pct": None,
    }


def _plain_value(value: object) -> object:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        return value
    return value


def _row_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("signal_date") or ""),
        str(row.get("signal_at") or ""),
        str(row.get("vt_symbol") or ""),
    )


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _return_pct(baseline: float | None, value: float | None) -> float | None:
    if baseline is None or baseline <= 0 or value is None:
        return None
    return (value / baseline - 1) * 100


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None and isfinite(value) else None


def _change(values: Sequence[float]) -> float | None:
    return _rounded(values[-1] - values[0]) if len(values) >= 2 else None


def _range(values: Sequence[float]) -> float | None:
    return _rounded(max(values) - min(values)) if values else None


def _drawdown(values: Sequence[float]) -> float | None:
    return _rounded(values[-1] - max(values)) if values else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def _pct(value: float | None) -> float | None:
    return round(value * 100, 4) if value is not None else None


def _f_beta(
    precision: float | None,
    recall: float | None,
    *,
    beta: float,
) -> float | None:
    if precision is None or recall is None:
        return None
    denominator = beta * beta * precision + recall
    if denominator <= 0:
        return 0.0
    return (1 + beta * beta) * precision * recall / denominator
