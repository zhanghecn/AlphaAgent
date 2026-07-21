"""Reverse-aligned diagnostics for the formal first-board touch baseline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time
from math import isfinite

import numpy as np

from alphaagent.server.services.limit_up.preboard_baseline_model import (
    BASELINE_FEATURE_NAMES,
)


REVERSE_HORIZONS = (30, 20, 15, 10, 5)
RANKING_FIELDS = (
    "rank_score",
    "support_score",
    "entry_quality_score",
    "gain_pct",
    "distance_to_limit_pct",
    "return_5m_pct",
    "return_15m_pct",
    "return_30m_pct",
    "acceleration_pct",
    "amount_acceleration_ratio",
    "volume_ratio_30m",
    "amount_ratio_30m",
)
_ASCENDING_RANK_FIELDS = {"distance_to_limit_pct"}


def trading_minutes_between(
    start_time: object,
    end_time: object,
) -> float | None:
    """Return elapsed A-share trading minutes, excluding the lunch break."""

    start = _session_coordinate(start_time)
    end = _session_coordinate(end_time)
    if start is None or end is None:
        return None
    return round(end - start, 4)


def align_pair_to_touch_horizons(
    rows: Sequence[Mapping[str, object]],
    *,
    touch_time: str,
    horizons: Sequence[int] = REVERSE_HORIZONS,
) -> dict[int, dict[str, object] | None]:
    """Select the latest causal 3% prefix no later than each touch cutoff."""

    touch_coordinate = _session_coordinate(touch_time)
    normalized_horizons = tuple(sorted({max(int(value), 0) for value in horizons}))
    if touch_coordinate is None:
        return {horizon: None for horizon in normalized_horizons}

    candidates = _observable_rows(rows, touch_coordinate=touch_coordinate)
    return {
        horizon: _latest_row_before_cutoff(
            candidates,
            cutoff=touch_coordinate - horizon,
            touch_coordinate=touch_coordinate,
            horizon=horizon,
        )
        for horizon in normalized_horizons
    }


def snapshot_pair_at_touch_horizons(
    rows: Sequence[Mapping[str, object]],
    *,
    touch_time: str,
    horizons: Sequence[int] = REVERSE_HORIZONS,
) -> dict[int, dict[str, object] | None]:
    """Select the nearest completed prefix at each fixed pre-touch cutoff."""

    touch_coordinate = _session_coordinate(touch_time)
    normalized_horizons = tuple(sorted({max(int(value), 0) for value in horizons}))
    if touch_coordinate is None:
        return {horizon: None for horizon in normalized_horizons}
    causal_rows = _causal_rows(rows, touch_coordinate=touch_coordinate)
    observed_coordinates = [
        coordinate
        for coordinate, row in causal_rows
        if is_observed_three_percent(row)
    ]
    return {
        horizon: _latest_snapshot_before_cutoff(
            causal_rows,
            observed_coordinates=observed_coordinates,
            cutoff=touch_coordinate - horizon,
            touch_coordinate=touch_coordinate,
            horizon=horizon,
        )
        for horizon in normalized_horizons
    }


def first_observable_leads(
    rows: Sequence[Mapping[str, object]],
    *,
    touch_time: str,
) -> dict[str, float | None]:
    """Return first 3% and first shared-filter lead times before touch."""

    touch_coordinate = _session_coordinate(touch_time)
    if touch_coordinate is None:
        return _empty_leads()
    candidates = _observable_rows(rows, touch_coordinate=touch_coordinate)
    if not candidates:
        return _empty_leads()

    first_3pct = candidates[0][0]
    shared = [coordinate for coordinate, row in candidates if _is_shared(row)]
    return {
        "first_3pct_lead_minutes": round(touch_coordinate - first_3pct, 4),
        "first_shared_lead_minutes": (
            round(touch_coordinate - shared[0], 4) if shared else None
        ),
    }


def is_observed_three_percent(row: Mapping[str, object]) -> bool:
    gain = _row_gain(row)
    return bool(
        row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= 3.0
    )


def is_shared_eligible(row: Mapping[str, object]) -> bool:
    return is_observed_three_percent(row) and _is_shared(row)


def matched_risk_set(
    rows: Sequence[Mapping[str, object]],
    anchor: Mapping[str, object],
    *,
    require_shared: bool,
) -> list[dict[str, object]]:
    """Return unique causal competitors at the anchor's exact date and time."""

    anchor_date = _row_date(anchor)
    anchor_time = _row_time(anchor)
    if not anchor_date or not anchor_time:
        return []
    selected: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        if _row_date(row) != anchor_date or _row_time(row) != anchor_time:
            continue
        if require_shared and not is_shared_eligible(row):
            continue
        if not require_shared and not is_observed_three_percent(row):
            continue
        key = (str(row.get("vt_symbol") or ""), anchor_date, anchor_time)
        if key[0]:
            selected.setdefault(key, dict(row))
    return [selected[key] for key in sorted(selected)]


def positive_rank_diagnostics(
    risk_rows: Sequence[Mapping[str, object]],
    positive_pair: tuple[str, str],
) -> dict[str, dict[str, object]]:
    """Rank one positive identity with fixed causal comparators."""

    return {
        field: _rank_one_field(risk_rows, positive_pair, field)
        for field in RANKING_FIELDS
    }


def feature_separation(
    positive_rows: Sequence[Mapping[str, object]],
    control_rows: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    """Describe univariate positive/control separation without fitting a score."""

    result: dict[str, dict[str, object]] = {}
    for field in BASELINE_FEATURE_NAMES:
        positives = _finite_feature_values(positive_rows, field)
        controls = _finite_feature_values(control_rows, field)
        auc = _rank_auc(positives, controls)
        result[field] = {
            "positive_count": len(positives),
            "control_count": len(controls),
            "positive_median": _median(positives),
            "control_median": _median(controls),
            "median_gap": _median_gap(positives, controls),
            "rank_auc": auc,
            "direction": _auc_direction(auc),
        }
    return result


def _observable_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    touch_coordinate: float,
) -> list[tuple[float, Mapping[str, object]]]:
    candidates = [
        (coordinate, row)
        for row in rows
        if is_observed_three_percent(row)
        and (coordinate := _row_coordinate(row)) is not None
        and coordinate < touch_coordinate
    ]
    return sorted(candidates, key=lambda item: item[0])


def _causal_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    touch_coordinate: float,
) -> list[tuple[float, Mapping[str, object]]]:
    candidates = [
        (coordinate, row)
        for row in rows
        if row.get("before_first_limit_touch") is True
        and (coordinate := _row_coordinate(row)) is not None
        and coordinate < touch_coordinate
    ]
    return sorted(candidates, key=lambda item: item[0])


def _latest_snapshot_before_cutoff(
    candidates: Sequence[tuple[float, Mapping[str, object]]],
    *,
    observed_coordinates: Sequence[float],
    cutoff: float,
    touch_coordinate: float,
    horizon: int,
) -> dict[str, object] | None:
    eligible = [item for item in candidates if item[0] <= cutoff + 1e-9]
    if not eligible:
        return None
    coordinate, row = eligible[-1]
    return {
        **dict(row),
        "reverse_horizon_minutes": horizon,
        "reverse_lead_minutes": round(touch_coordinate - coordinate, 4),
        "tracked_after_3pct": any(value <= coordinate for value in observed_coordinates),
        "snapshot_current_gte_3pct": is_observed_three_percent(row),
        "snapshot_shared_eligible": is_shared_eligible(row),
    }


def _rank_one_field(
    rows: Sequence[Mapping[str, object]],
    positive_pair: tuple[str, str],
    field: str,
) -> dict[str, object]:
    scored = [
        (value, row)
        for row in rows
        if (value := _feature_value(row, field)) is not None
    ]
    scored.sort(key=lambda item: _ranking_key(item[0], item[1], field))
    rank = next(
        (
            index
            for index, (_, row) in enumerate(scored, start=1)
            if _row_pair(row) == positive_pair
        ),
        None,
    )
    count = len(scored)
    percentile = None
    if rank is not None:
        percentile = 100.0 if count == 1 else (count - rank) / (count - 1) * 100
    return {
        "rank": rank,
        "candidate_count": count,
        "percentile": round(percentile, 4) if percentile is not None else None,
        "top1": rank == 1,
        "top2": rank is not None and rank <= 2,
    }


def _ranking_key(
    value: float,
    row: Mapping[str, object],
    field: str,
) -> tuple[float, float, str]:
    primary = value if field in _ASCENDING_RANK_FIELDS else -value
    current_rank = _feature_value(row, "rank_score")
    tie_break = -(current_rank if current_rank is not None else float("-inf"))
    return primary, tie_break, str(row.get("vt_symbol") or "")


def _finite_feature_values(
    rows: Sequence[Mapping[str, object]],
    field: str,
) -> list[float]:
    return [
        value
        for row in rows
        if (value := _feature_value(row, field)) is not None
    ]


def _feature_value(row: Mapping[str, object], field: str) -> float | None:
    direct = _number(row.get(field))
    if direct is not None:
        return direct
    for container_name in ("ignition_features", "features"):
        container = row.get(container_name)
        if not isinstance(container, Mapping):
            continue
        value = _number(container.get(field))
        if value is not None:
            return value
    return None


def _rank_auc(positives: Sequence[float], controls: Sequence[float]) -> float | None:
    if not positives or not controls:
        return None
    positive = np.asarray(positives, dtype=float)[:, None]
    control = np.asarray(controls, dtype=float)[None, :]
    auc = float(np.mean(positive > control) + 0.5 * np.mean(positive == control))
    return round(auc, 6)


def _auc_direction(auc: float | None) -> str | None:
    if auc is None:
        return None
    if auc > 0.5:
        return "higher"
    if auc < 0.5:
        return "lower"
    return "flat"


def _median(values: Sequence[float]) -> float | None:
    return round(float(np.median(values)), 6) if values else None


def _median_gap(
    positives: Sequence[float],
    controls: Sequence[float],
) -> float | None:
    if not positives or not controls:
        return None
    return round(float(np.median(positives) - np.median(controls)), 6)


def _latest_row_before_cutoff(
    candidates: Sequence[tuple[float, Mapping[str, object]]],
    *,
    cutoff: float,
    touch_coordinate: float,
    horizon: int,
) -> dict[str, object] | None:
    eligible = [item for item in candidates if item[0] <= cutoff + 1e-9]
    if not eligible:
        return None
    coordinate, row = eligible[-1]
    return {
        **dict(row),
        "reverse_horizon_minutes": horizon,
        "reverse_lead_minutes": round(touch_coordinate - coordinate, 4),
        "observed_3pct": True,
        "shared_eligible": _is_shared(row),
    }


def _row_coordinate(row: Mapping[str, object]) -> float | None:
    return _session_coordinate(row.get("signal_time") or row.get("signal_at"))


def _row_date(row: Mapping[str, object]) -> str:
    return str(row.get("signal_date") or row.get("entry_date") or "")[:10]


def _row_time(row: Mapping[str, object]) -> str:
    parsed = _as_time(row.get("signal_time") or row.get("signal_at"))
    return parsed.strftime("%H:%M:%S") if parsed is not None else ""


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return str(row.get("vt_symbol") or ""), _row_date(row)


def _row_gain(row: Mapping[str, object]) -> float | None:
    for container_name in ("features", "ignition_features"):
        container = row.get(container_name)
        if isinstance(container, Mapping):
            value = _number(container.get("gain_pct"))
            if value is not None:
                return value
    return _number(row.get("gain_pct"))


def _is_shared(row: Mapping[str, object]) -> bool:
    return row.get("shared_strategy_passed") is True


def _session_coordinate(value: object) -> float | None:
    parsed = _as_time(value)
    if parsed is None:
        return None
    minutes = parsed.hour * 60 + parsed.minute + parsed.second / 60
    morning_start = 9 * 60 + 30
    morning_end = 11 * 60 + 30
    afternoon_start = 13 * 60
    afternoon_end = 15 * 60
    if morning_start <= minutes <= morning_end:
        return minutes - morning_start
    if afternoon_start <= minutes <= afternoon_end:
        return 120 + minutes - afternoon_start
    return None


def _as_time(value: object) -> time | None:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    text = str(value or "").strip()
    if "T" in text:
        text = text.rsplit("T", 1)[-1]
    if " " in text:
        text = text.rsplit(" ", 1)[-1]
    try:
        return time.fromisoformat(text[:8])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _empty_leads() -> dict[str, None]:
    return {
        "first_3pct_lead_minutes": None,
        "first_shared_lead_minutes": None,
    }
