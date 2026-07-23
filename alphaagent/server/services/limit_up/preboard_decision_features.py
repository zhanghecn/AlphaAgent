"""Causal feature projection shared by historical and live pre-board scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta
from hashlib import sha256
import json
from math import isfinite, nan

from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
)


MINIMUM_PREFIX_BAR_COUNT = 7
FORBIDDEN_FEATURE_KEYS = frozenset(
    {
        "physical_touch_at",
        "first_limit_time",
        "last_limit_time",
        "final_sealed",
        "formal_identity_matched",
        "d1_trade_date",
        "d1_close_price",
        "net_return_pct",
        "next_close_return_pct",
        "fill_price",
    }
)
COMMON_DYNAMIC_FEATURES = (
    "gain_pct",
    "distance_to_limit_pct",
    "return_1m",
    "return_3m",
    "return_5m",
    "gain_slope_3m",
    "gain_acceleration_1m_3m",
    "max_drawdown_3m",
    "recovery_3m",
    "volume_ratio_1m_5m",
    "turnover_acceleration_3m",
    "transaction_flow_missing",
    *TRANSACTION_FEATURE_NAMES,
    "main_net_inflow_delta_3m",
    "sector_change_1m",
    "sector_breadth_3pct",
    "sector_candidate_acceleration_3m",
    "quality_pool_count",
    "quality_pool_new_count_1m",
    "quality_pool_rank",
    "session_minute_index",
    "minutes_to_next_entry_window",
    "minutes_to_final_entry_cutoff",
    "minutes_since_first_3pct_cross",
    "lane_support_score",
    "lane_entry_quality_score",
)
OPTIONAL_VALUE_FEATURES = (
    *TRANSACTION_FEATURE_NAMES,
    "main_net_inflow_delta_3m",
    "sector_change_1m",
    "sector_breadth_3pct",
    "sector_candidate_acceleration_3m",
    "quality_pool_count",
    "quality_pool_new_count_1m",
    "quality_pool_rank",
    "lane_support_score",
    "lane_entry_quality_score",
)
MISSING_INDICATOR_FEATURES = tuple(
    f"{name}_missing" for name in OPTIONAL_VALUE_FEATURES
)
MODEL_FEATURE_NAMES = (*COMMON_DYNAMIC_FEATURES, *MISSING_INDICATOR_FEATURES)


class FutureFeatureError(ValueError):
    """Raised when a label or settlement field is injected into model inputs."""


def project_historical_decision_features(
    observation: Mapping[str, object],
) -> dict[str, object]:
    cutoff = _as_datetime(observation.get("decision_at"))
    return project_decision_features(
        observation,
        minute_bars=_historical_minute_bars(observation.get("minute_bars"), cutoff),
        quality_pool_snapshots=_minute_cross_section_snapshots(
            observation.get("cross_section_snapshots"),
            cutoff,
            capture_timestamps=False,
        ),
        source_kind="historical_minute",
        source_quality=str(
            observation.get("source_quality") or "official_historical_minute"
        ),
    )


def project_prepared_historical_decision_features(
    observation: Mapping[str, object],
    *,
    minute_bars: Sequence[Mapping[str, object]],
    cross_section_snapshots: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return project_decision_features(
        observation,
        minute_bars=minute_bars,
        quality_pool_snapshots=cross_section_snapshots,
        source_kind="historical_minute",
        source_quality=str(
            observation.get("source_quality") or "official_historical_minute"
        ),
    )


def project_live_decision_features(
    observation: Mapping[str, object],
) -> dict[str, object]:
    cutoff = _as_datetime(observation.get("decision_at"))
    return project_decision_features(
        observation,
        minute_bars=completed_minute_bars(observation, cutoff),
        quality_pool_snapshots=_minute_cross_section_snapshots(
            observation.get("quality_pool_snapshots"),
            cutoff,
            capture_timestamps=False,
        ),
        source_kind="live_frame_minute",
        source_quality=str(observation.get("source_quality") or "unknown"),
    )


def project_decision_features(
    observation: Mapping[str, object],
    *,
    minute_bars: Sequence[Mapping[str, object]],
    quality_pool_snapshots: Sequence[Mapping[str, object]],
    source_kind: str,
    source_quality: str,
) -> dict[str, object]:
    """Project normalized causal inputs through the single feature core."""

    cutoff = _as_datetime(observation.get("decision_at"))
    return _project_decision_features(
        observation,
        bars=_historical_minute_bars(minute_bars, cutoff),
        cross_section_snapshots=_minute_cross_section_snapshots(
            quality_pool_snapshots,
            cutoff,
            capture_timestamps=False,
        ),
        source_kind=source_kind,
        source_quality=source_quality,
    )


def completed_minute_bars(
    observation: Mapping[str, object],
    cutoff: datetime | None,
) -> list[dict[str, object]]:
    """Normalize only explicitly completed live minute bars."""

    return _historical_minute_bars(
        observation.get("completed_minute_bars"),
        cutoff,
    )


def model_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    if row.get("feature_status") != "scoreable":
        return None
    values = row.get("feature_values")
    if not isinstance(values, Mapping):
        return None
    return [
        float(value) if (value := _number(values.get(name))) is not None else nan
        for name in MODEL_FEATURE_NAMES
    ]


def session_minute_index(value: datetime | time) -> int:
    clock = value.time() if isinstance(value, datetime) else value
    minutes = clock.hour * 60 + clock.minute
    if minutes <= 9 * 60 + 30:
        return 0
    if minutes <= 11 * 60 + 30:
        return minutes - (9 * 60 + 30)
    if minutes < 13 * 60:
        return 120
    return min(120 + minutes - 13 * 60, 240)


def build_lane_prefix(
    bars: Sequence[Mapping[str, object]],
    index: int,
    *,
    previous_close: float,
    bar_minutes: int = 1,
) -> dict[str, object]:
    """Project completed bars into the lane evaluator's causal path shape."""

    if bar_minutes not in {1, 5}:
        raise ValueError("bar_minutes must be 1 or 5")
    ordered = sorted(
        (dict(row) for row in bars),
        key=lambda row: _as_datetime(row.get("bar_time")) or datetime.max,
    )
    if previous_close <= 0 or index < 0 or index >= len(ordered):
        return _empty_lane_prefix()
    return build_lane_prefixes(
        ordered[: index + 1],
        previous_close=previous_close,
        bar_minutes=bar_minutes,
    )[-1]


def build_lane_prefixes(
    bars: Sequence[Mapping[str, object]],
    *,
    previous_close: float,
    bar_minutes: int = 1,
) -> list[dict[str, object]]:
    """Build every causal lane prefix in one pass for replay workloads."""

    if bar_minutes not in {1, 5}:
        raise ValueError("bar_minutes must be 1 or 5")
    ordered = sorted(
        (dict(row) for row in bars),
        key=lambda row: _as_datetime(row.get("bar_time")) or datetime.max,
    )
    if previous_close <= 0:
        return [_empty_lane_prefix() for _row in ordered]
    return _build_lane_prefixes(
        ordered,
        previous_close=previous_close,
        bar_minutes=bar_minutes,
    )


def _build_lane_prefixes(
    bars: Sequence[Mapping[str, object]],
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
    prefixes: list[dict[str, object]] = []

    for bar in bars:
        value = _return_pct(previous_close, _number(bar.get("close_price")))
        if value is None:
            prefixes.append(_empty_lane_prefix())
            continue
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

        recent_15m = values[-recent_15m_count:]
        recent_30m = values[-recent_30m_count:]
        observed_at = _as_datetime(bar.get("bar_time"))
        observed_time = (
            observed_at.time().replace(microsecond=0).isoformat()
            if observed_at is not None
            else None
        )
        prefixes.append(
            {
                "signal_time": observed_time,
                "last_point_time": observed_time,
                "point_count": len(values),
                "last_pct": _rounded(values[-1]),
                "maximum_pct": _rounded(maximum),
                "minimum_pct": _rounded(minimum),
                "recent_15m_min_pct": _rounded(min(recent_15m)),
                "recent_15m_change_pct": _rounded(
                    recent_15m[-1] - recent_15m[0]
                ),
                "recent_15m_range_pct": _rounded(
                    max(recent_15m) - min(recent_15m)
                ),
                "recent_15m_drawdown_pct": _rounded(
                    recent_15m[-1] - max(recent_15m)
                ),
                "recent_30m_min_pct": _rounded(min(recent_30m)),
                "recent_30m_change_pct": _rounded(
                    recent_30m[-1] - recent_30m[0]
                ),
                "touch_count": touch_count,
                "break_count": break_count,
                "reseal_count": reseal_count,
                "is_at_limit": values[-1] >= 9.7,
                "approach_3point_pct": _rounded(
                    recent_15m[-1] - recent_15m[0]
                ),
            }
        )
    return prefixes


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


def _project_decision_features(
    observation: Mapping[str, object],
    *,
    bars: Sequence[Mapping[str, object]],
    cross_section_snapshots: Sequence[Mapping[str, object]],
    source_kind: str,
    source_quality: str,
) -> dict[str, object]:
    _guard_forbidden_feature_inputs(observation)
    symbol = str(observation.get("vt_symbol") or "").strip()
    cutoff = _as_datetime(observation.get("decision_at"))
    candidate = observation.get("candidate")
    candidate = candidate if isinstance(candidate, Mapping) else {}
    if candidate.get("quality_gate_passed") is not True:
        return _empty_projection(
            symbol,
            cutoff,
            source_kind,
            source_quality,
            "not_scoreable_quality_gate_failed",
        )
    previous_close = _positive(observation.get("previous_close"))
    limit_price = _positive(observation.get("limit_price"))
    if not symbol or cutoff is None or previous_close is None or limit_price is None:
        return _empty_projection(
            symbol,
            cutoff,
            source_kind,
            source_quality,
            "not_scoreable_invalid_identity",
        )
    if not _has_complete_prefix(bars, cutoff):
        return _empty_projection(
            symbol,
            cutoff,
            source_kind,
            source_quality,
            "not_scoreable_insufficient_prefix",
        )
    if any(
        (_number(row.get("high_price")) or 0.0) >= limit_price - 0.001
        for row in bars
    ):
        return _empty_projection(
            symbol,
            cutoff,
            source_kind,
            source_quality,
            "not_scoreable_already_touched",
        )
    current_close = _positive(bars[-1].get("close_price"))
    gain_pct = _return_pct(previous_close, current_close)
    if gain_pct is None or gain_pct < 3.0:
        return _empty_projection(
            symbol,
            cutoff,
            source_kind,
            source_quality,
            "not_scoreable_below_observation_floor",
        )
    cross_section = _cross_section_features(
        cross_section_snapshots,
        cutoff,
        symbol,
    )
    cross_section = cross_section or {
        "quality_pool_count": None,
        "quality_pool_new_count_1m": None,
        "quality_pool_rank": None,
    }

    path = _path_features(bars)
    transaction = _transaction_features(observation, cutoff)
    first_observed_at = _as_datetime(observation.get("candidate_first_observed_at"))
    values: dict[str, float | None] = {
        "gain_pct": gain_pct,
        "distance_to_limit_pct": _return_pct(current_close, limit_price),
        **path,
        **transaction,
        "main_net_inflow_delta_3m": _number(
            candidate.get("main_net_inflow_delta_3m")
        ),
        "sector_change_1m": _number(candidate.get("sector_change_1m")),
        "sector_breadth_3pct": _number(candidate.get("sector_breadth_3pct")),
        "sector_candidate_acceleration_3m": _number(
            candidate.get("sector_candidate_acceleration_3m")
        ),
        **cross_section,
        "session_minute_index": float(session_minute_index(cutoff)),
        "minutes_to_next_entry_window": float(
            _minutes_to_next_entry_window(cutoff)
        ),
        "minutes_to_final_entry_cutoff": float(
            max(210 - session_minute_index(cutoff), 0)
        ),
        "minutes_since_first_3pct_cross": float(
            _trading_minutes_between(first_observed_at, cutoff)
        ),
        "lane_support_score": _number(
            candidate.get("lane_support_score")
            if candidate.get("lane_support_score") is not None
            else candidate.get("support_score")
        ),
        "lane_entry_quality_score": _number(
            candidate.get("lane_entry_quality_score")
            if candidate.get("lane_entry_quality_score") is not None
            else candidate.get("entry_quality_score")
        ),
    }
    missing_fields = tuple(
        name for name in COMMON_DYNAMIC_FEATURES if values.get(name) is None
    )
    for name in OPTIONAL_VALUE_FEATURES:
        values[f"{name}_missing"] = float(values.get(name) is None)
    normalized = {
        name: _rounded(values.get(name))
        for name in MODEL_FEATURE_NAMES
    }
    required = (
        name
        for name in COMMON_DYNAMIC_FEATURES
        if name not in OPTIONAL_VALUE_FEATURES
        and name != "transaction_flow_missing"
    )
    if any(normalized.get(name) is None for name in required):
        return _empty_projection(
            symbol,
            cutoff,
            source_kind,
            source_quality,
            "not_scoreable_incomplete_core_features",
        )
    fingerprint = _feature_fingerprint(symbol, cutoff, normalized)
    return {
        "feature_contract_version": PREBOARD_DECISION_VERSION,
        "vt_symbol": symbol,
        "decision_feature_cutoff": cutoff.isoformat(),
        "known_at": cutoff.isoformat(),
        "source_kind": source_kind,
        "source_quality": source_quality,
        "feature_status": "scoreable",
        "feature_names": list(MODEL_FEATURE_NAMES),
        "feature_values": normalized,
        "features": normalized,
        "missing_fields": list(missing_fields),
        "feature_fingerprint": fingerprint,
    }


def _path_features(
    bars: Sequence[Mapping[str, object]],
) -> dict[str, float | None]:
    closes = [_positive(row.get("close_price")) for row in bars]
    if any(value is None for value in closes[-7:]):
        return {}
    values = [float(value) for value in closes if value is not None]
    return_1m = _return_pct(values[-2], values[-1])
    return_3m = _return_pct(values[-4], values[-1])
    return_5m = _return_pct(values[-6], values[-1])
    recent = values[-4:]
    return {
        "return_1m": return_1m,
        "return_3m": return_3m,
        "return_5m": return_5m,
        "gain_slope_3m": return_3m / 3.0 if return_3m is not None else None,
        "gain_acceleration_1m_3m": (
            return_1m - return_3m / 3.0
            if return_1m is not None and return_3m is not None
            else None
        ),
        "max_drawdown_3m": _maximum_drawdown_pct(recent),
        "recovery_3m": _return_pct(min(recent), recent[-1]),
        "volume_ratio_1m_5m": _latest_to_prior_mean_ratio(
            bars,
            "volume",
            prior_count=5,
        ),
        "turnover_acceleration_3m": _latest_to_prior_mean_ratio(
            bars,
            "turnover",
            prior_count=3,
        ),
    }


def _historical_minute_bars(
    value: object,
    cutoff: datetime | None,
) -> list[dict[str, object]]:
    if cutoff is None or not _mapping_sequence(value):
        return []
    rows = [
        {**dict(row), "bar_time": _minute_key(bar_time)}
        for row in value
        if (bar_time := _as_datetime(row.get("bar_time"))) is not None
        and bar_time <= cutoff
    ]
    return sorted(rows, key=lambda row: row["bar_time"])


def _minute_cross_section_snapshots(
    value: object,
    cutoff: datetime | None,
    *,
    capture_timestamps: bool,
) -> list[dict[str, object]]:
    if cutoff is None or not _mapping_sequence(value):
        return []
    by_minute: dict[datetime, tuple[datetime, dict[str, object]]] = {}
    for raw in value:
        captured_at = _as_datetime(raw.get("captured_at"))
        candidates = raw.get("candidates")
        if captured_at is None or captured_at > cutoff or not _mapping_sequence(candidates):
            continue
        minute = (
            _live_minute_close(captured_at)
            if capture_timestamps
            else _minute_key(captured_at)
        )
        if minute is None or minute > cutoff:
            continue
        current = by_minute.get(minute)
        if current is None or captured_at > current[0]:
            by_minute[minute] = (
                captured_at,
                {
                    "captured_at": minute,
                    "candidates": [dict(row) for row in candidates],
                },
            )
    return [item[1] for _minute, item in sorted(by_minute.items())]


def _cross_section_features(
    snapshots: Sequence[Mapping[str, object]],
    cutoff: datetime,
    symbol: str,
) -> dict[str, float] | None:
    eligible = [
        row
        for row in snapshots
        if (_as_datetime(row.get("captured_at")) or datetime.max) <= cutoff
    ]
    if len(eligible) < 2:
        return None
    current = _candidate_index(eligible[-1].get("candidates"))
    previous = _candidate_index(eligible[-2].get("candidates"))
    gains = {
        key: gain
        for key, row in current.items()
        if (gain := _candidate_gain(row)) is not None
    }
    if symbol not in gains:
        return None
    ordered = sorted(gains, key=lambda key: (-gains[key], key))
    return {
        "quality_pool_count": float(len(gains)),
        "quality_pool_new_count_1m": float(len(set(current) - set(previous))),
        "quality_pool_rank": float(ordered.index(symbol) + 1),
    }


def _transaction_features(
    observation: Mapping[str, object],
    cutoff: datetime,
) -> dict[str, float | None]:
    raw_values = observation.get("transaction_features")
    feature_at = _as_datetime(observation.get("transaction_feature_at"))
    ready = bool(
        observation.get("transaction_status") == "flow_ready"
        and isinstance(raw_values, Mapping)
        and feature_at is not None
        and feature_at <= cutoff
    )
    parsed = {
        name: _number(raw_values.get(name)) if ready else None
        for name in TRANSACTION_FEATURE_NAMES
    }
    ready = ready and all(value is not None for value in parsed.values())
    return {
        "transaction_flow_missing": float(not ready),
        **{name: parsed[name] if ready else None for name in TRANSACTION_FEATURE_NAMES},
    }


def _guard_forbidden_feature_inputs(observation: Mapping[str, object]) -> None:
    containers = [
        observation.get("feature_values"),
        observation.get("model_features"),
        observation.get("feature_overrides"),
    ]
    candidate = observation.get("candidate")
    if isinstance(candidate, Mapping):
        containers.extend(
            (candidate.get("feature_values"), candidate.get("model_features"))
        )
    for value in containers:
        if not isinstance(value, Mapping):
            continue
        forbidden = sorted(FORBIDDEN_FEATURE_KEYS.intersection(value))
        if forbidden:
            raise FutureFeatureError(
                "forbidden future model feature(s): " + ", ".join(forbidden)
            )


def _has_complete_prefix(
    bars: Sequence[Mapping[str, object]],
    cutoff: datetime,
) -> bool:
    if len(bars) < MINIMUM_PREFIX_BAR_COUNT:
        return False
    if _as_datetime(bars[-1].get("bar_time")) != _minute_key(cutoff):
        return False
    required = ("high_price", "low_price", "close_price", "volume", "turnover")
    return all(
        all(_number(row.get(field)) is not None for field in required)
        for row in bars[-MINIMUM_PREFIX_BAR_COUNT:]
    )


def _minutes_to_next_entry_window(value: datetime) -> int:
    index = session_minute_index(value)
    return max(30 - index, 0) if index < 30 else 0


def _trading_minutes_between(start: datetime | None, end: datetime) -> int:
    if start is None or start > end or start.date() != end.date():
        return 0
    return max(session_minute_index(end) - session_minute_index(start), 0)


def _maximum_drawdown_pct(values: Sequence[float]) -> float:
    peak = values[0]
    drawdown = 0.0
    for value in values[1:]:
        peak = max(peak, value)
        drawdown = max(drawdown, (peak - value) / peak * 100.0)
    return drawdown


def _latest_to_prior_mean_ratio(
    bars: Sequence[Mapping[str, object]],
    field: str,
    *,
    prior_count: int,
) -> float | None:
    current = _positive(bars[-1].get(field))
    prior = [_positive(row.get(field)) for row in bars[-prior_count - 1 : -1]]
    if current is None or len(prior) != prior_count or any(value is None for value in prior):
        return None
    mean_value = sum(float(value) for value in prior if value is not None) / prior_count
    return current / mean_value if mean_value > 0 else None


def _feature_fingerprint(
    symbol: str,
    cutoff: datetime,
    values: Mapping[str, object],
) -> str:
    encoded = json.dumps(
        {
            "feature_contract_version": PREBOARD_DECISION_VERSION,
            "vt_symbol": symbol,
            "decision_feature_cutoff": cutoff.isoformat(),
            "features": values,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _empty_projection(
    symbol: str,
    cutoff: datetime | None,
    source_kind: str,
    source_quality: str,
    status: str,
) -> dict[str, object]:
    return {
        "feature_contract_version": PREBOARD_DECISION_VERSION,
        "vt_symbol": symbol,
        "decision_feature_cutoff": cutoff.isoformat() if cutoff else None,
        "known_at": cutoff.isoformat() if cutoff else None,
        "source_kind": source_kind,
        "source_quality": source_quality,
        "feature_status": status,
        "feature_names": list(MODEL_FEATURE_NAMES),
        "feature_values": {},
        "features": {},
        "missing_fields": [],
        "feature_fingerprint": None,
    }


def _candidate_index(value: object) -> dict[str, Mapping[str, object]]:
    if not _mapping_sequence(value):
        return {}
    return {
        symbol: row
        for row in value
        if (symbol := str(row.get("vt_symbol") or "").strip())
    }


def _candidate_gain(row: Mapping[str, object]) -> float | None:
    return _number(
        row.get("gain_pct")
        if row.get("gain_pct") is not None
        else row.get("change_pct")
    )


def _mapping_sequence(value: object) -> bool:
    return bool(
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and all(isinstance(row, Mapping) for row in value)
    )


def _minute_key(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _live_minute_close(value: datetime) -> datetime | None:
    """Map a sampled quote to its causal A-share one-minute close label."""

    clock = value.time().replace(tzinfo=None)
    if not (
        time(9, 30) <= clock < time(11, 30)
        or time(13, 0) <= clock < time(15, 0)
    ):
        return None
    return _minute_key(value) + timedelta(minutes=1)


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None


def _return_pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def _positive(value: object) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _rounded(value: object) -> float | None:
    parsed = _number(value)
    return round(parsed, 8) if parsed is not None else None
