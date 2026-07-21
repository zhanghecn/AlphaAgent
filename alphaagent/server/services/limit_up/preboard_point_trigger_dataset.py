"""Causal sub-minute dataset for the forward-only point trigger study."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from math import isfinite, log1p
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.domain import is_eligible_main_board
from alphaagent.server.services.limit_up.capture_runtime import (
    is_capture_runtime_fingerprint,
)
from alphaagent.server.services.limit_up.preboard_point_trigger_contract import (
    CONTRACT_VERSION,
    ELIGIBLE_AFTER,
    ENTRY_WINDOWS,
    FRAME_FEATURE_FIELDS,
    IDENTITY_FEATURE_FIELDS,
    MAXIMUM_LABEL_GAP_SECONDS,
    MAXIMUM_CANDIDATE_AGE_SECONDS,
    MAXIMUM_QUOTE_AGE_SECONDS,
    MAXIMUM_QUOTE_ENRICHMENT_AGE_SECONDS,
    MAXIMUM_SEQUENCE_ANCHOR_LAG_SECONDS,
    MAXIMUM_VISIBLE_FRAME_COUNT,
    MINIMUM_GAIN_PCT,
    MINIMUM_FORMAL_TWO_SLOT_EVIDENCE_RATIO,
    MINIMUM_HISTORICAL_COMBINED_RATE,
    MINIMUM_HISTORY_SAMPLE_COUNT,
    MINIMUM_LABEL_KNOWN_ELIGIBLE_HORIZON_RATIO,
    PointTriggerDayAudit,
    SEQUENCE_HORIZONS_SECONDS,
    TRANSIENT_LANE_BLOCKER_CODES,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TOUCHED_CAPTURE_STATES = frozenset(
    {"sealed", "resealed", "failed", "limit_touch", "touched"}
)
CONCEPT_ACCELERATION_FIELDS = tuple(
    f"concept_{metric}_acceleration_{minutes}m"
    for metric in ("change", "turnover")
    for minutes in (1, 3, 5)
)
FORMAL_BASELINE_LANES = frozenset({"first_board", "two_to_three"})


def audit_point_trigger_day(
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
) -> PointTriggerDayAudit:
    normalized_frames = _normalized_frames(frames)
    trade_dates = {frame["trade_date"] for frame in normalized_frames}
    trade_date = next(iter(trade_dates)) if len(trade_dates) == 1 else None
    reasons: list[str] = []
    if trade_date is None:
        reasons.append("invalid_or_multiple_trade_dates")

    window_frames = [
        frame
        for frame in normalized_frames
        if trade_date is not None
        and frame["trade_date"] == trade_date
        and _entry_window(frame["captured_at"]) is not None
    ]
    if not window_frames:
        reasons.append("no_frames_in_entry_windows")

    window_frame_groups = _entry_window_frame_groups(window_frames, trade_date)

    frame_by_id = {frame["id"]: frame for frame in window_frames}
    window_observations = [
        row
        for row in observations
        if row.get("frame_id") in frame_by_id
    ]
    frame_count = len(window_frames)
    observation_count = len(window_observations)
    observation_counts = Counter(
        row.get("frame_id") for row in window_observations
    )
    observation_capture_count_mismatch_count = 0
    for frame in window_frames:
        expected_count = _number(frame.get("capture_count"))
        actual_count = int(observation_counts.get(frame["id"], 0))
        if (
            expected_count is None
            or expected_count < 0
            or not expected_count.is_integer()
            or int(expected_count) != actual_count
        ):
            observation_capture_count_mismatch_count += 1

    ready_ratio = min(
        (
            _ratio(
                sum(frame.get("quality_status") == "ready" for frame in group),
                len(group),
            )
            if group
            else 0.0
        )
        for group in window_frame_groups
    )
    non_stale_ratio = min(
        (
            _ratio(
                sum(frame.get("is_stale") is False for frame in group),
                len(group),
            )
            if group
            else 0.0
        )
        for group in window_frame_groups
    )
    source_mismatch_count = sum(
        frame.get("source_trade_date") != frame.get("trade_date")
        for frame in window_frames
    )
    scan_gap_groups = _entry_window_gap_groups(window_frames, trade_date)
    scan_gaps = [gap for group in scan_gap_groups for gap in group]
    scan_p90 = max(
        (_quantile(group, 0.90) or 0.0 for group in scan_gap_groups),
        default=None,
    )
    maximum_gap = max(scan_gaps, default=None)
    quote_coverage_p10 = min(
        (
            _quantile(
                [
                    _normalized_ratio(
                        frame.get("quote_coverage_ratio"), missing=0.0
                    )
                    for frame in group
                ],
                0.10,
            )
            or 0.0
        )
        for group in window_frame_groups
    )
    timing_ratio = min(
        (
            _ratio(
                sum(
                    bool(str(frame.get("market_timing_state") or "").strip())
                    for frame in group
                ),
                len(group),
            )
            if group
            else 0.0
        )
        for group in window_frame_groups
    )
    two_slot_evidence_ratio = min(
        (
            _ratio(
                sum(_formal_two_slot_symbols(frame) is not None for frame in group),
                len(group),
            )
            if group
            else 0.0
        )
        for group in window_frame_groups
    )
    formal_baseline_orders: list[dict[str, object]] = []
    formal_baseline_order_projection_complete = False
    if trade_date is not None and window_frames and two_slot_evidence_ratio == 1.0:
        try:
            formal_baseline_orders = build_formal_baseline_orders(
                window_frames,
                window_observations,
            )
            formal_baseline_order_projection_complete = True
        except ValueError:
            pass

    eligible_count = 0
    fresh_quote_ratios: list[float] = []
    concept_ratios: list[float] = []
    for group in window_frame_groups:
        group_ids = {frame["id"] for frame in group}
        group_observations = [
            row for row in window_observations if row.get("frame_id") in group_ids
        ]
        fresh_quote_count = 0
        quote_count = 0
        group_eligible_count = 0
        concept_ready_count = 0
        for raw in group_observations:
            frame = frame_by_id.get(raw.get("frame_id"))
            if frame is None:
                continue
            captured_at = frame["captured_at"]
            quote_at = _as_datetime(raw.get("quote_observed_at"))
            if str(raw.get("capture_state") or "") != "fill_followup":
                quote_count += 1
                age = (
                    (captured_at - quote_at).total_seconds()
                    if quote_at is not None
                    else None
                )
                if age is not None and 0.0 <= age <= MAXIMUM_QUOTE_AGE_SECONDS:
                    fresh_quote_count += 1
            if _candidate_gate(raw, frame, require_fresh_quote=False):
                group_eligible_count += 1
                if all(
                    _number(raw.get(field)) is not None
                    for field in CONCEPT_ACCELERATION_FIELDS
                ):
                    concept_ready_count += 1
        eligible_count += group_eligible_count
        fresh_quote_ratios.append(
            _ratio(fresh_quote_count, quote_count)
            if quote_count
            else 1.0
            if observation_capture_count_mismatch_count == 0
            else 0.0
        )
        concept_ratios.append(
            _ratio(concept_ready_count, group_eligible_count)
            if group_eligible_count
            else 1.0
        )
    fresh_quote_ratio = min(fresh_quote_ratios, default=0.0)
    concept_ratio = min(concept_ratios, default=0.0)

    runtime_fingerprints = [
        str(frame.get("capture_runtime_fingerprint") or "").strip()
        for frame in window_frames
    ]
    runtime_fingerprint_coverage = _ratio(
        sum(bool(value) for value in runtime_fingerprints),
        frame_count,
    )
    invalid_runtime_fingerprint_count = sum(
        bool(value) and not is_capture_runtime_fingerprint(value)
        for value in runtime_fingerprints
    )
    distinct_runtime_fingerprints = {
        value
        for value in runtime_fingerprints
        if is_capture_runtime_fingerprint(value)
    }
    capture_runtime_fingerprint = (
        next(iter(distinct_runtime_fingerprints))
        if runtime_fingerprint_coverage == 1.0
        and invalid_runtime_fingerprint_count == 0
        and len(distinct_runtime_fingerprints) == 1
        else None
    )
    if frame_count and ready_ratio < 0.98:
        reasons.append("ready_frame_ratio_below_98pct")
    if frame_count and non_stale_ratio < 0.98:
        reasons.append("non_stale_frame_ratio_below_98pct")
    if source_mismatch_count:
        reasons.append("source_trade_date_mismatch")
    if observation_capture_count_mismatch_count:
        reasons.append("observation_capture_count_mismatch")
    if fresh_quote_ratio < 0.98:
        reasons.append("fresh_quote_ratio_below_98pct")
    if scan_p90 is None or scan_p90 > 20.0:
        reasons.append("scan_interval_p90_above_20s")
    if maximum_gap is None or maximum_gap > 60.0:
        reasons.append("entry_window_max_gap_above_60s")
    if quote_coverage_p10 is None or quote_coverage_p10 < 0.90:
        reasons.append("quote_coverage_p10_below_90pct")
    if frame_count == 0 or timing_ratio < 0.98:
        reasons.append("market_timing_coverage_below_98pct")
    if two_slot_evidence_ratio < MINIMUM_FORMAL_TWO_SLOT_EVIDENCE_RATIO:
        reasons.append("formal_two_slot_evidence_incomplete")
    if not formal_baseline_order_projection_complete:
        reasons.append("formal_baseline_order_projection_incomplete")
    if concept_ratio < 0.95:
        reasons.append("concept_acceleration_coverage_below_95pct")
    if runtime_fingerprint_coverage < 1.0:
        reasons.append("capture_runtime_fingerprint_missing")
    if invalid_runtime_fingerprint_count:
        reasons.append("capture_runtime_fingerprint_invalid")
    if len(distinct_runtime_fingerprints) > 1:
        reasons.append("capture_runtime_fingerprint_changed")

    reason_codes = tuple(dict.fromkeys(reasons))
    is_complete = not reason_codes
    eligible_for_model = bool(
        is_complete and trade_date is not None and trade_date > ELIGIBLE_AFTER
    )
    status = (
        "complete"
        if eligible_for_model
        else "excluded_shakedown"
        if is_complete
        else "incomplete"
    )
    metrics: dict[str, float | int | None] = {
        "ready_frame_ratio": _rounded(ready_ratio),
        "non_stale_frame_ratio": _rounded(non_stale_ratio),
        "source_trade_date_mismatch_count": source_mismatch_count,
        "observation_capture_count_mismatch_count": (
            observation_capture_count_mismatch_count
        ),
        "fresh_quote_ratio": _rounded(fresh_quote_ratio),
        "scan_interval_p90_seconds": _rounded(scan_p90),
        "entry_window_max_gap_seconds": _rounded(maximum_gap),
        "quote_coverage_p10": _rounded(quote_coverage_p10),
        "market_timing_coverage_ratio": _rounded(timing_ratio),
        "formal_two_slot_evidence_coverage_ratio": _rounded(
            two_slot_evidence_ratio
        ),
        "eligible_candidate_count": eligible_count,
        "concept_acceleration_coverage_ratio": _rounded(concept_ratio),
        "capture_runtime_fingerprint_coverage_ratio": _rounded(
            runtime_fingerprint_coverage
        ),
        "capture_runtime_fingerprint_unique_count": len(
            distinct_runtime_fingerprints
        ),
        "capture_runtime_fingerprint_invalid_count": (
            invalid_runtime_fingerprint_count
        ),
        **_reachability_funnel_metrics(normalized_frames, observations),
    }
    return PointTriggerDayAudit(
        contract_version=CONTRACT_VERSION,
        trade_date=trade_date,
        status=status,
        is_complete=is_complete,
        eligible_for_model=eligible_for_model,
        reason_codes=reason_codes,
        frame_count=frame_count,
        observation_count=observation_count,
        metrics=metrics,
        capture_runtime_fingerprint=capture_runtime_fingerprint,
        formal_baseline_order_projection_complete=(
            formal_baseline_order_projection_complete
        ),
        formal_baseline_orders=tuple(formal_baseline_orders),
    )


def build_formal_baseline_orders(
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Project the first live formal portfolio signal for each stock-day."""

    normalized_frames = _normalized_frames(frames)
    observations_by_frame_symbol: dict[
        tuple[object, str], list[Mapping[str, object]]
    ] = defaultdict(list)
    for observation in observations:
        frame_id = observation.get("frame_id")
        symbol = str(observation.get("vt_symbol") or "").strip()
        if frame_id is not None and symbol:
            observations_by_frame_symbol[(frame_id, symbol)].append(observation)

    seen: set[tuple[date, str]] = set()
    orders: list[dict[str, object]] = []
    for frame in normalized_frames:
        symbols = _formal_two_slot_symbols(frame)
        if symbols is None:
            raise ValueError("formal portfolio evidence is missing or invalid")
        for slot, symbol in enumerate(symbols, start=1):
            candidates = observations_by_frame_symbol.get((frame["id"], symbol), [])
            matching = [
                row
                for row in candidates
                if str(row.get("formal_action") or "") == "buy_now"
                and str(row.get("board_lane") or "") in FORMAL_BASELINE_LANES
            ]
            if not matching:
                raise ValueError("formal portfolio symbol is not buy_now in its frame")
            pair = (frame["trade_date"], symbol)
            if pair in seen:
                continue
            observation = matching[0]
            limit_price = _number(observation.get("limit_price"))
            if limit_price is None or limit_price <= 0:
                raise ValueError("formal portfolio order limit_price is invalid")
            seen.add(pair)
            captured_at = frame["captured_at"]
            orders.append(
                {
                    "vt_symbol": symbol,
                    "name": str(observation.get("name") or symbol),
                    "lane": str(observation.get("board_lane") or ""),
                    "entry_date": frame["trade_date"],
                    "signal_date": frame["trade_date"],
                    "buy_time": captured_at.astimezone(SHANGHAI).strftime(
                        "%H:%M:%S"
                    ),
                    "entry_price": limit_price,
                    "limit_price": limit_price,
                    "rank_score": _number(observation.get("rank_score")) or 0.0,
                    "pool_rank": slot,
                    "source_frame_id": frame["id"],
                    "source_captured_at": captured_at,
                    "source": "saved_live_formal_portfolio",
                }
            )
    return orders


def point_trigger_label_metrics(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, float | int | None]:
    """Summarize label coverage without exposing labels as model features."""

    statuses = Counter(str(row.get("label_status") or "unknown_missing_status") for row in rows)
    known_count = int(statuses.get("known", 0))
    cross_session_count = int(statuses.get("unknown_cross_session_horizon", 0))
    eligible_horizon_count = max(len(rows) - cross_session_count, 0)
    reachable_events = {
        (
            _iso_value(row.get("trade_date")),
            _iso_value(row.get("formal_event_at")),
            str(row.get("formal_identity_vt_symbol") or ""),
        )
        for row in rows
        if str(row.get("label_status") or "") == "known"
        and row.get("formal_event_within_60s") is True
        and row.get("formal_event_at") is not None
        and str(row.get("formal_identity_vt_symbol") or "")
    }
    return {
        "label_row_count": len(rows),
        "label_eligible_horizon_row_count": eligible_horizon_count,
        "label_known_row_count": known_count,
        "label_unknown_incomplete_horizon_row_count": int(
            statuses.get("unknown_incomplete_horizon", 0)
        ),
        "label_unknown_cross_session_row_count": cross_session_count,
        "label_unknown_other_row_count": sum(
            count
            for status, count in statuses.items()
            if status
            not in {
                "known",
                "unknown_incomplete_horizon",
                "unknown_cross_session_horizon",
            }
        ),
        "label_known_ratio": _rounded(
            _ratio(known_count, len(rows)) if rows else 1.0
        ),
        "label_known_eligible_horizon_ratio": _rounded(
            _ratio(known_count, eligible_horizon_count)
            if eligible_horizon_count
            else 1.0
        ),
        "reachable_formal_event_count": len(reachable_events),
    }


def finalize_point_trigger_day_audit(
    audit: PointTriggerDayAudit,
    rows: Sequence[Mapping[str, object]],
) -> PointTriggerDayAudit:
    """Apply label completeness without turning unobserved horizons into negatives."""

    if not audit.is_complete:
        return audit
    label_metrics = point_trigger_label_metrics(rows)
    expected_reachable = _number(
        audit.metrics.get("formal_event_static_eligible_within_60s_count")
    )
    labeled_reachable = int(
        label_metrics.get("reachable_formal_event_count") or 0
    )
    reachable_coverage = (
        labeled_reachable / expected_reachable
        if expected_reachable is not None and expected_reachable > 0
        else 1.0
        if expected_reachable == 0
        else None
    )
    metrics = {
        **audit.metrics,
        **label_metrics,
        "reachable_event_label_coverage_ratio": _rounded(
            reachable_coverage
        ),
    }
    reasons = list(audit.reason_codes)
    label_ratio = _number(
        label_metrics.get("label_known_eligible_horizon_ratio")
    )
    if (
        label_ratio is None
        or label_ratio < MINIMUM_LABEL_KNOWN_ELIGIBLE_HORIZON_RATIO
    ):
        reasons.append("label_known_eligible_horizon_ratio_below_98pct")
    if (
        expected_reachable is None
        or not expected_reachable.is_integer()
        or int(expected_reachable) != labeled_reachable
    ):
        reasons.append("reachable_event_label_cohort_incomplete")
    reason_codes = tuple(dict.fromkeys(reasons))
    is_complete = not reason_codes
    eligible_for_model = bool(
        is_complete
        and audit.trade_date is not None
        and audit.trade_date > ELIGIBLE_AFTER
    )
    status = (
        "complete"
        if eligible_for_model
        else "excluded_shakedown"
        if is_complete
        else "incomplete"
    )
    return replace(
        audit,
        status=status,
        is_complete=is_complete,
        eligible_for_model=eligible_for_model,
        reason_codes=reason_codes,
        metrics=metrics,
    )


def build_point_trigger_rows(
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    normalized_frames = _normalized_frames(frames)
    frame_by_id = {frame["id"]: frame for frame in normalized_frames}
    observations_by_frame: dict[object, list[dict[str, object]]] = defaultdict(list)
    first_formal_events: dict[tuple[date, str], datetime] = {}
    for raw in observations:
        frame = frame_by_id.get(raw.get("frame_id"))
        if frame is None:
            continue
        row = dict(raw)
        row["captured_at"] = frame["captured_at"]
        observations_by_frame[frame["id"]].append(row)
        symbol = str(row.get("vt_symbol") or "")
        if (
            symbol
            and str(row.get("formal_action") or "") == "buy_now"
            and str(row.get("board_lane") or "") == "first_board"
        ):
            key = (frame["trade_date"], symbol)
            previous = first_formal_events.get(key)
            if previous is None or frame["captured_at"] < previous:
                first_formal_events[key] = frame["captured_at"]

    event_times = sorted(first_formal_events.values())
    history: dict[tuple[date, str], list[dict[str, object]]] = defaultdict(list)
    first_seen: dict[tuple[date, str], datetime] = {}
    previous_frame_gap_by_id = _previous_frame_gap_by_id(normalized_frames)
    result: list[dict[str, object]] = []
    for frame in normalized_frames:
        captured_at = frame["captured_at"]
        if _entry_window(captured_at) is None:
            continue
        raw_candidates = sorted(
            observations_by_frame.get(frame["id"], []),
            key=lambda row: str(row.get("vt_symbol") or ""),
        )
        observed = [
            row for row in raw_candidates if _observation_gate(row, frame)
        ]
        if not observed:
            continue
        eligible = [
            row for row in observed if _candidate_gate(row, frame)
        ]
        formal_two_slot_symbols = _formal_two_slot_symbols(frame)
        action_frame_eligible = bool(
            formal_two_slot_symbols is not None
            and _action_frame_quality_ready(frame)
            and _complete_action_horizon(captured_at)
            and (
                (gap := previous_frame_gap_by_id.get(frame["id"])) is not None
                and 0.0 < gap <= MAXIMUM_SEQUENCE_ANCHOR_LAG_SECONDS
            )
        )
        current_by_symbol: dict[str, dict[str, object]] = {}
        for candidate in observed:
            pair = (frame["trade_date"], str(candidate["vt_symbol"]))
            prior_records = history[pair]
            prior_at = prior_records[-1].get("captured_at") if prior_records else None
            gap = (
                (captured_at - prior_at).total_seconds()
                if isinstance(prior_at, datetime)
                else None
            )
            if prior_records and (
                gap is None or gap > MAXIMUM_SEQUENCE_ANCHOR_LAG_SECONDS
            ):
                prior_records.clear()
                first_seen[pair] = captured_at
            first_seen.setdefault(pair, captured_at)
            current_by_symbol[str(candidate["vt_symbol"])] = _history_record(
                candidate,
                captured_at,
            )
        frame_features = (
            _frame_features(
                frame,
                observed,
                history=history,
                first_seen=first_seen,
                event_times=event_times,
            )
            if eligible
            else None
        )
        for candidate in eligible:
            symbol = str(candidate["vt_symbol"])
            pair = (frame["trade_date"], symbol)
            prior_records = history[pair]
            current = current_by_symbol[symbol]
            records = [*prior_records, current]
            identity_features = _identity_features(
                candidate,
                frame,
                records=records,
                first_seen_at=first_seen[pair],
            )
            row = {
                "contract_version": CONTRACT_VERSION,
                "frame_id": frame["id"],
                "trade_date": frame["trade_date"],
                "captured_at": captured_at,
                "vt_symbol": symbol,
                "name": str(candidate.get("name") or ""),
                "last_price": _number(candidate.get("last_price")),
                "limit_price": _number(candidate.get("limit_price")),
                "quote_observed_at": _as_datetime(
                    candidate.get("quote_observed_at")
                ),
                "action_frame_eligible": action_frame_eligible,
                "action_previous_frame_gap_seconds": (
                    previous_frame_gap_by_id.get(frame["id"])
                ),
                "action_quote_coverage_ratio": _number(
                    frame.get("quote_coverage_ratio")
                ),
                "action_market_timing_observed": _market_timing_observed(frame),
                "formal_two_slot_observed": formal_two_slot_symbols is not None,
                "formal_two_slot_symbols": formal_two_slot_symbols or [],
                "frame_features": {
                    field: frame_features[field]
                    for field in FRAME_FEATURE_FIELDS
                },
                "identity_features": {
                    field: identity_features[field]
                    for field in IDENTITY_FEATURE_FIELDS
                },
            }
            row["feature_fingerprint"] = point_trigger_input_fingerprint([row])
            result.append(row)
        for candidate in observed:
            symbol = str(candidate["vt_symbol"])
            pair = (frame["trade_date"], symbol)
            history[pair].append(current_by_symbol[symbol])
    return sorted(
        result,
        key=lambda row: (
            row["captured_at"],
            str(row["vt_symbol"]),
        ),
    )


def attach_point_trigger_labels(
    rows: Sequence[Mapping[str, object]],
    future_observations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    future = [
        normalized
        for raw in future_observations
        if (normalized := _normalized_future_observation(raw)) is not None
    ]
    future.sort(key=_future_sort_key)
    future_times = [item["captured_at"] for item in future]
    first_formal_events: dict[tuple[date, str], dict[str, object]] = {}
    for item in future:
        symbol = str(item.get("vt_symbol") or "").strip()
        if (
            not symbol
            or item["formal_action"] != "buy_now"
            or item["board_lane"] != "first_board"
        ):
            continue
        key = (item["captured_at"].date(), symbol)
        if key not in first_formal_events:
            first_formal_events[key] = item
    formal_events = sorted(first_formal_events.values(), key=_future_sort_key)
    formal_event_times = [item["captured_at"] for item in formal_events]
    anchors: dict[tuple[str, datetime], set[str]] = defaultdict(set)
    for raw in rows:
        captured_at = _as_datetime(raw.get("captured_at"))
        symbol = str(raw.get("vt_symbol") or "").strip()
        if captured_at is None or not symbol:
            continue
        anchors[(str(raw.get("frame_id") or ""), captured_at)].add(symbol)

    label_by_anchor: dict[tuple[str, datetime], dict[str, object]] = {}
    for key, candidate_symbols in anchors.items():
        _, captured_at = key
        window = _entry_window(captured_at)
        horizon_end = captured_at + timedelta(seconds=60)
        if window is None or horizon_end > window[1]:
            label_by_anchor[key] = {"label_status": "unknown_cross_session_horizon"}
            continue
        horizon = future[
            bisect_right(future_times, captured_at) : bisect_right(
                future_times,
                horizon_end,
            )
        ]
        horizon = [
            item
            for item in horizon
            if item["captured_at"].date() == captured_at.date()
        ]
        events = [
            item
            for item in formal_events[
                bisect_right(formal_event_times, captured_at) : bisect_right(
                    formal_event_times,
                    horizon_end,
                )
            ]
            if item["vt_symbol"] in candidate_symbols
        ]
        event = min(events, key=_future_sort_key, default=None)
        coverage_end = event["captured_at"] if event is not None else horizon_end
        observed_times = sorted(
            {
                item["captured_at"]
                for item in horizon
                if item["captured_at"] <= coverage_end
            }
        )
        if not _continuous_horizon(captured_at, coverage_end, observed_times):
            label_by_anchor[key] = {"label_status": "unknown_incomplete_horizon"}
            continue
        label_by_anchor[key] = {
            "label_status": "known",
            "formal_event_within_60s": event is not None,
            "formal_identity_vt_symbol": (
                str(event["vt_symbol"]) if event is not None else None
            ),
            "formal_event_at": event["captured_at"] if event is not None else None,
        }

    labeled: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        captured_at = _as_datetime(row.get("captured_at"))
        if captured_at is None:
            labeled.append(_unknown_label(row, "unknown_invalid_anchor"))
            continue
        key = (str(row.get("frame_id") or ""), captured_at)
        anchor_label = label_by_anchor.get(key)
        if anchor_label is None or anchor_label.get("label_status") != "known":
            labeled.append(
                _unknown_label(
                    row,
                    str(
                        (anchor_label or {}).get("label_status")
                        or "unknown_invalid_anchor"
                    ),
                )
            )
            continue
        identity = anchor_label.get("formal_identity_vt_symbol")
        labeled.append(
            {
                **row,
                **anchor_label,
                "formal_identity_within_60s": (
                    str(row.get("vt_symbol") or "") == identity
                    if identity is not None
                    else False
                ),
            }
        )
    return labeled


def point_trigger_input_fingerprint(
    rows: Sequence[Mapping[str, object]],
) -> str:
    payload = []
    for raw in sorted(
        rows,
        key=lambda row: (
            _iso_value(row.get("captured_at")),
            str(row.get("vt_symbol") or ""),
            str(row.get("frame_id") or ""),
        ),
    ):
        frame_features = raw.get("frame_features")
        identity_features = raw.get("identity_features")
        frame_features = frame_features if isinstance(frame_features, Mapping) else {}
        identity_features = (
            identity_features if isinstance(identity_features, Mapping) else {}
        )
        payload.append(
            {
                "contract_version": str(
                    raw.get("contract_version") or CONTRACT_VERSION
                ),
                "frame_id": str(raw.get("frame_id") or ""),
                "trade_date": _iso_value(raw.get("trade_date")),
                "captured_at": _iso_value(raw.get("captured_at")),
                "vt_symbol": str(raw.get("vt_symbol") or ""),
                "action_frame_eligible": (
                    raw.get("action_frame_eligible")
                    if isinstance(raw.get("action_frame_eligible"), bool)
                    else None
                ),
                "action_previous_frame_gap_seconds": _json_number(
                    raw.get("action_previous_frame_gap_seconds")
                ),
                "action_quote_coverage_ratio": _json_number(
                    raw.get("action_quote_coverage_ratio")
                ),
                "action_market_timing_observed": (
                    raw.get("action_market_timing_observed")
                    if isinstance(raw.get("action_market_timing_observed"), bool)
                    else None
                ),
                "formal_two_slot_observed": (
                    raw.get("formal_two_slot_observed")
                    if isinstance(raw.get("formal_two_slot_observed"), bool)
                    else None
                ),
                "formal_two_slot_symbols": (
                    list(raw.get("formal_two_slot_symbols") or [])
                    if isinstance(raw.get("formal_two_slot_symbols"), Sequence)
                    and not isinstance(
                        raw.get("formal_two_slot_symbols"), (str, bytes)
                    )
                    else None
                ),
                "frame_features": {
                    field: _json_number(frame_features.get(field))
                    for field in FRAME_FEATURE_FIELDS
                },
                "identity_features": {
                    field: _json_number(identity_features.get(field))
                    for field in IDENTITY_FEATURE_FIELDS
                },
            }
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _normalized_frames(
    frames: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    normalized: dict[object, dict[str, object]] = {}
    for raw in frames:
        frame_id = raw.get("id", raw.get("frame_id"))
        captured_at = _as_datetime(raw.get("captured_at"))
        trade_date = _as_date(raw.get("trade_date"))
        if frame_id is None or captured_at is None or trade_date is None:
            continue
        normalized.setdefault(
            frame_id,
            {
                **dict(raw),
                "id": frame_id,
                "trade_date": trade_date,
                "captured_at": captured_at,
                "source_trade_date": _as_date(raw.get("source_trade_date")),
            },
        )
    return sorted(
        normalized.values(),
        key=lambda frame: (frame["captured_at"], str(frame["id"])),
    )


def _entry_window(value: datetime) -> tuple[datetime, datetime] | None:
    local = value.astimezone(SHANGHAI)
    for start_time, end_time in ENTRY_WINDOWS:
        start = datetime.combine(local.date(), start_time, SHANGHAI)
        end = datetime.combine(local.date(), end_time, SHANGHAI)
        if start <= local <= end:
            return start, end
    return None


def _previous_frame_gap_by_id(
    frames: Sequence[Mapping[str, object]],
) -> dict[object, float | None]:
    previous_by_window: dict[tuple[date, datetime, datetime], datetime] = {}
    result: dict[object, float | None] = {}
    for frame in frames:
        captured_at = frame.get("captured_at")
        trade_date = frame.get("trade_date")
        frame_id = frame.get("id")
        if (
            not isinstance(captured_at, datetime)
            or not isinstance(trade_date, date)
            or frame_id is None
            or (window := _entry_window(captured_at)) is None
        ):
            continue
        key = (trade_date, *window)
        previous = previous_by_window.get(key)
        result[frame_id] = (
            (captured_at - previous).total_seconds()
            if previous is not None
            else None
        )
        previous_by_window[key] = captured_at
    return result


def _complete_action_horizon(value: datetime) -> bool:
    window = _entry_window(value)
    return bool(window is not None and value + timedelta(seconds=60) <= window[1])


def _action_frame_quality_ready(frame: Mapping[str, object]) -> bool:
    coverage = _number(frame.get("quote_coverage_ratio"))
    return bool(
        frame.get("quality_status") == "ready"
        and frame.get("is_stale") is False
        and frame.get("source_trade_date") == frame.get("trade_date")
        and coverage is not None
        and coverage >= 0.90
        and _market_timing_observed(frame)
    )


def _market_timing_observed(frame: Mapping[str, object]) -> bool:
    return bool(str(frame.get("market_timing_state") or "").strip())


def _formal_two_slot_symbols(
    frame: Mapping[str, object],
) -> list[str] | None:
    values = frame.get("formal_two_slot_symbols")
    if (
        frame.get("formal_two_slot_observed") is not True
        or not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or any(not isinstance(value, str) or not value.strip() for value in values)
    ):
        return None
    symbols = [value.strip() for value in values]
    if len(symbols) > 2 or len(symbols) != len(set(symbols)):
        return None
    return symbols


def _entry_window_gaps(
    frames: Sequence[Mapping[str, object]],
    trade_date: date | None,
) -> list[float]:
    return [
        gap
        for group in _entry_window_gap_groups(frames, trade_date)
        for gap in group
    ]


def _entry_window_frame_groups(
    frames: Sequence[Mapping[str, object]],
    trade_date: date | None,
) -> list[list[Mapping[str, object]]]:
    if trade_date is None:
        return [[] for _window in ENTRY_WINDOWS]
    groups: list[list[Mapping[str, object]]] = []
    for start_time, end_time in ENTRY_WINDOWS:
        start = datetime.combine(trade_date, start_time, SHANGHAI)
        end = datetime.combine(trade_date, end_time, SHANGHAI)
        groups.append(
            [
                frame
                for frame in frames
                if start <= frame["captured_at"] <= end
            ]
        )
    return groups


def _entry_window_gap_groups(
    frames: Sequence[Mapping[str, object]],
    trade_date: date | None,
) -> list[list[float]]:
    if trade_date is None:
        return []
    groups: list[list[float]] = []
    for (start_time, end_time), group in zip(
        ENTRY_WINDOWS,
        _entry_window_frame_groups(frames, trade_date),
        strict=True,
    ):
        start = datetime.combine(trade_date, start_time, SHANGHAI)
        end = datetime.combine(trade_date, end_time, SHANGHAI)
        times = sorted({frame["captured_at"] for frame in group})
        boundaries = [start, *times, end]
        groups.append(
            [
                max((right - left).total_seconds(), 0.0)
                for left, right in zip(
                    boundaries,
                    boundaries[1:],
                    strict=False,
                )
            ]
        )
    return groups


def _candidate_gate(
    row: Mapping[str, object],
    frame: Mapping[str, object],
    *,
    require_fresh_quote: bool = True,
) -> bool:
    if not _observation_gate(
        row,
        frame,
        require_fresh_quote=require_fresh_quote,
    ):
        return False
    if not _history_quality_gate(row):
        return False
    return _static_lane_gate(row)


def _observation_gate(
    row: Mapping[str, object],
    frame: Mapping[str, object],
    *,
    require_fresh_quote: bool = True,
) -> bool:
    captured_at = frame.get("captured_at")
    if not isinstance(captured_at, datetime):
        return False
    if (
        frame.get("quality_status") != "ready"
        or frame.get("is_stale") is not False
        or frame.get("source_trade_date") != frame.get("trade_date")
        or not _raw_three_percent_gate(row)
    ):
        return False
    if not require_fresh_quote:
        return True
    quote_at = _as_datetime(row.get("quote_observed_at"))
    age = (
        (captured_at - quote_at).total_seconds()
        if quote_at is not None
        else None
    )
    return bool(age is not None and 0.0 <= age <= MAXIMUM_QUOTE_AGE_SECONDS)


def _raw_three_percent_gate(row: Mapping[str, object]) -> bool:
    if (
        str(row.get("board_lane") or "") != "first_board"
        or str(row.get("capture_state") or "") in TOUCHED_CAPTURE_STATES
        or str(row.get("capture_state") or "") == "fill_followup"
        or str(row.get("formal_action") or "") == "buy_now"
        or not is_eligible_main_board(
            str(row.get("vt_symbol") or ""),
            str(row.get("name") or ""),
        )
    ):
        return False
    gain = _number(row.get("change_pct"))
    last_price = _number(row.get("last_price"))
    limit_price = _number(row.get("limit_price"))
    return bool(
        gain is not None
        and gain >= MINIMUM_GAIN_PCT
        and last_price is not None
        and limit_price is not None
        and 0 < last_price < limit_price
    )


def _history_quality_gate(row: Mapping[str, object]) -> bool:
    rank = _number(row.get("rank_score"))
    samples = _number(row.get("history_sample_count"))
    combined_rate = _number(row.get("historical_combined_rate"))
    return bool(
        rank is not None
        and samples is not None
        and samples >= MINIMUM_HISTORY_SAMPLE_COUNT
        and combined_rate is not None
        and combined_rate >= MINIMUM_HISTORICAL_COMBINED_RATE
    )


def _static_lane_gate(row: Mapping[str, object]) -> bool:
    lane_blockers = _lane_blockers(row)
    return bool(
        lane_blockers is not None
        and not (set(lane_blockers) - TRANSIENT_LANE_BLOCKER_CODES)
    )


def _reachability_funnel_metrics(
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
) -> dict[str, float | int | None]:
    frame_by_id = {frame["id"]: frame for frame in frames}
    records_by_pair: dict[
        tuple[date, str],
        list[tuple[Mapping[str, object], Mapping[str, object]]],
    ] = defaultdict(list)
    events: dict[tuple[date, str], datetime] = {}
    for raw in observations:
        frame = frame_by_id.get(raw.get("frame_id"))
        if frame is None or _entry_window(frame["captured_at"]) is None:
            continue
        row = raw
        symbol = str(row.get("vt_symbol") or "").strip()
        if symbol:
            records_by_pair[(frame["trade_date"], symbol)].append((row, frame))
        if (
            symbol
            and str(row.get("formal_action") or "") == "buy_now"
            and str(row.get("board_lane") or "") == "first_board"
        ):
            key = (frame["trade_date"], symbol)
            event_at = frame["captured_at"]
            if key not in events or event_at < events[key]:
                events[key] = event_at

    stage_counts = Counter(
        {
            "raw_3pct": 0,
            "quality_3pct": 0,
            "fresh_3pct": 0,
            "history_eligible": 0,
            "lane_contract_available": 0,
            "static_eligible": 0,
        }
    )
    for (trade_date, symbol), event_at in events.items():
        event_window = _entry_window(event_at)
        prefix = [
            (row, frame)
            for row, frame in records_by_pair.get((trade_date, symbol), [])
            if event_at - timedelta(seconds=60) <= frame["captured_at"] < event_at
            and _entry_window(frame["captured_at"]) == event_window
        ]
        raw = [(row, frame) for row, frame in prefix if _raw_three_percent_gate(row)]
        quality = [
            (row, frame)
            for row, frame in prefix
            if _observation_gate(row, frame, require_fresh_quote=False)
        ]
        fresh = [
            (row, frame) for row, frame in prefix if _observation_gate(row, frame)
        ]
        history = [
            (row, frame) for row, frame in fresh if _history_quality_gate(row)
        ]
        lane_contract = [
            (row, frame) for row, frame in history if _lane_blockers(row) is not None
        ]
        static = [
            (row, frame) for row, frame in lane_contract if _static_lane_gate(row)
        ]
        stage_counts["raw_3pct"] += bool(raw)
        stage_counts["quality_3pct"] += bool(quality)
        stage_counts["fresh_3pct"] += bool(fresh)
        stage_counts["history_eligible"] += bool(history)
        stage_counts["lane_contract_available"] += bool(lane_contract)
        stage_counts["static_eligible"] += bool(static)

    event_count = len(events)
    metrics: dict[str, float | int | None] = {
        "formal_first_board_event_count": event_count,
    }
    for stage in (
        "raw_3pct",
        "quality_3pct",
        "fresh_3pct",
        "history_eligible",
        "lane_contract_available",
        "static_eligible",
    ):
        count = int(stage_counts[stage])
        metrics[f"formal_event_{stage}_within_60s_count"] = count
        metrics[f"formal_event_{stage}_within_60s_ratio"] = _rounded(
            _ratio(count, event_count)
        )
    return metrics


def _frame_features(
    frame: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
    *,
    history: Mapping[tuple[date, str], list[dict[str, object]]],
    first_seen: Mapping[tuple[date, str], datetime],
    event_times: Sequence[datetime],
) -> dict[str, float]:
    captured_at = frame["captured_at"]
    trade_date = frame["trade_date"]
    gains = [float(_number(row.get("change_pct")) or 0.0) for row in candidates]
    upward = 0
    new_count = 0
    for row in candidates:
        symbol = str(row.get("vt_symbol") or "")
        pair = (trade_date, symbol)
        prior = history.get(pair, [])
        prior_record = prior[-1] if prior else None
        if prior_record is not None and gains:
            upward += float(row.get("change_pct") or 0.0) > float(
                prior_record["gain_pct"]
            )
        first_at = first_seen.get(pair)
        if first_at is None or (captured_at - first_at).total_seconds() <= 20.0:
            new_count += 1
    concepts = Counter(
        str(row.get("concept_id") or "")
        for row in candidates
        if str(row.get("concept_id") or "")
    )
    concept_accelerations = [
        value
        for row in candidates
        if (value := _number(row.get("concept_change_acceleration_1m"))) is not None
    ]
    flow_values = []
    for row in candidates:
        stock_flow, stock_missing = _same_day_flow(
            row.get("stock_main_net_inflow_ratio"),
            row.get("stock_flow_trade_date"),
            trade_date,
        )
        sector_flow, sector_missing = _same_day_flow(
            row.get("sector_main_net_inflow_ratio"),
            row.get("sector_flow_trade_date"),
            trade_date,
        )
        if not stock_missing:
            flow_values.append(stock_flow)
        elif not sector_missing:
            flow_values.append(sector_flow)
    timing = str(frame.get("market_timing_state") or "NONE").upper()
    fading_timing_states = {"FADING", "GOLD_FADING", "SILVER_FADING"}
    features = {
        "market_candidate_count_total": float(len(candidates)),
        "market_candidate_count_3_5": float(sum(3.0 <= gain < 5.0 for gain in gains)),
        "market_candidate_count_5_7": float(sum(5.0 <= gain < 7.0 for gain in gains)),
        "market_candidate_count_7_9_5": float(sum(7.0 <= gain < 9.5 for gain in gains)),
        "market_new_candidate_count_20s": float(new_count),
        "market_upward_candidate_ratio_20s": _ratio(upward, len(candidates)),
        "market_gain_max_pct": max(gains, default=0.0),
        "market_gain_p75_pct": _quantile(gains, 0.75) or 0.0,
        "market_near_limit_candidate_count": float(
            sum(
                gain >= 9.0
                or _distance_to_limit(row) <= 1.0
                for row, gain in zip(candidates, gains, strict=True)
            )
        ),
        **{
            f"market_formal_event_count_{horizon}s": float(
                sum(
                    captured_at - timedelta(seconds=horizon) < event_at <= captured_at
                    for event_at in event_times
                )
            )
            for horizon in SEQUENCE_HORIZONS_SECONDS
        },
        "market_concept_concentration_ratio": _ratio(
            max(concepts.values(), default=0),
            len(candidates),
        ),
        "market_positive_concept_acceleration_ratio": _ratio(
            sum(value > 0 for value in concept_accelerations),
            len(concept_accelerations),
        ),
        "market_same_day_positive_flow_ratio": _ratio(
            sum(value > 0 for value in flow_values),
            len(flow_values),
        ),
        "market_timing_gold_active": float(timing == "GOLD_ACTIVE"),
        "market_timing_silver_active": float(timing == "SILVER_ACTIVE"),
        "market_timing_fading": float(timing in fading_timing_states),
        "market_timing_stale": float(timing == "STALE"),
        "market_timing_none": float(
            timing
            not in {
                "GOLD_ACTIVE",
                "SILVER_ACTIVE",
                *fading_timing_states,
                "STALE",
            }
        ),
    }
    return _finite_feature_mapping(features, FRAME_FEATURE_FIELDS)


def _identity_features(
    candidate: Mapping[str, object],
    frame: Mapping[str, object],
    *,
    records: Sequence[Mapping[str, object]],
    first_seen_at: datetime,
) -> dict[str, float | None]:
    current = records[-1]
    captured_at = frame["captured_at"]
    trade_date = frame["trade_date"]
    sector_flow, sector_missing = _same_day_flow(
        candidate.get("sector_main_net_inflow_ratio"),
        candidate.get("sector_flow_trade_date"),
        trade_date,
    )
    stock_flow, stock_missing = _same_day_flow(
        candidate.get("stock_main_net_inflow_ratio"),
        candidate.get("stock_flow_trade_date"),
        trade_date,
    )
    support = _number(candidate.get("support_score"))
    entry_quality = _number(candidate.get("entry_quality_score"))
    quote_speed = _fresh_quote_enrichment_value(
        candidate,
        "quote_speed",
        captured_at,
    )
    quote_amplitude = _fresh_quote_enrichment_value(
        candidate,
        "quote_amplitude_pct",
        captured_at,
    )
    quote_main_flow = _fresh_quote_enrichment_value(
        candidate,
        "quote_main_net_inflow_ratio",
        captured_at,
    )
    concept_accelerations = [
        _number(candidate.get(field)) for field in CONCEPT_ACCELERATION_FIELDS
    ]
    concept_missing = not str(candidate.get("concept_id") or "").strip()
    concept_acceleration_missing = any(
        value is None for value in concept_accelerations
    )
    blocking_scope = str(candidate.get("blocking_scope") or "none")
    lane_blockers = _lane_blockers(candidate) or ()
    features: dict[str, float | None] = {
        "candidate_gain_pct": _number(candidate.get("change_pct")),
        "candidate_distance_to_limit_pct": _distance_to_limit(candidate),
        "candidate_lane_rank_score": _number(candidate.get("rank_score")),
        "candidate_support_score": support or 0.0,
        "candidate_support_missing": float(support is None),
        "candidate_entry_quality_score": entry_quality or 0.0,
        "candidate_entry_quality_missing": float(entry_quality is None),
        "candidate_market_blocked": float(blocking_scope == "market"),
        "candidate_dynamic_blocked": float(blocking_scope == "dynamic"),
        "candidate_soft_structural_blocked": float(
            blocking_scope == "structural"
        ),
        "candidate_transient_lane_blocker_count_log1p": log1p(
            len(lane_blockers)
        ),
        "candidate_history_sample_count_log1p": log1p(
            max(float(_number(candidate.get("history_sample_count")) or 0.0), 0.0)
        ),
        "candidate_historical_combined_rate": _number(
            candidate.get("historical_combined_rate")
        ),
        "candidate_age_seconds_log1p": log1p(
            min(
                max((captured_at - first_seen_at).total_seconds(), 0.0),
                MAXIMUM_CANDIDATE_AGE_SECONDS,
            )
        ),
        "candidate_visible_frame_count_log1p": log1p(
            min(len(records), MAXIMUM_VISIBLE_FRAME_COUNT)
        ),
        "candidate_quote_speed": quote_speed or 0.0,
        "candidate_quote_speed_missing": float(quote_speed is None),
        "candidate_quote_amplitude_pct": quote_amplitude or 0.0,
        "candidate_quote_amplitude_missing": float(quote_amplitude is None),
        "candidate_quote_main_net_inflow_ratio": quote_main_flow or 0.0,
        "candidate_quote_main_net_inflow_missing": float(quote_main_flow is None),
        "candidate_concept_strength_score": _number(
            candidate.get("concept_strength_score")
        ) or 0.0,
        "candidate_concept_leader_rank": _number(
            candidate.get("concept_leader_rank")
        ) or 0.0,
        "candidate_concept_strong_5_count_log1p": log1p(
            max(float(_number(candidate.get("concept_strong_5_count")) or 0.0), 0.0)
        ),
        "candidate_concept_change_acceleration_1m": concept_accelerations[0] or 0.0,
        "candidate_concept_change_acceleration_3m": concept_accelerations[1] or 0.0,
        "candidate_concept_change_acceleration_5m": concept_accelerations[2] or 0.0,
        "candidate_concept_turnover_acceleration_1m": concept_accelerations[3] or 0.0,
        "candidate_concept_turnover_acceleration_3m": concept_accelerations[4] or 0.0,
        "candidate_concept_turnover_acceleration_5m": concept_accelerations[5] or 0.0,
        "candidate_concept_missing": float(concept_missing),
        "candidate_concept_acceleration_missing": float(
            concept_acceleration_missing
        ),
        "candidate_sector_main_net_inflow_ratio": sector_flow,
        "candidate_sector_flow_missing": float(sector_missing),
        "candidate_stock_main_net_inflow_ratio": stock_flow,
        "candidate_stock_flow_missing": float(stock_missing),
    }
    for horizon in SEQUENCE_HORIZONS_SECONDS:
        slope, slope_missing = _slope_feature(
            records, current, horizon, "gain_pct"
        )
        acceleration, acceleration_missing = _acceleration_feature(
            records, current, horizon
        )
        features[f"candidate_gain_slope_{horizon}s"] = slope
        features[f"candidate_gain_slope_{horizon}s_missing"] = float(
            slope_missing
        )
        features[f"candidate_gain_acceleration_{horizon}s"] = acceleration
        features[f"candidate_gain_acceleration_{horizon}s_missing"] = float(
            acceleration_missing
        )
        window = _records_in_window(records, captured_at, horizon)
        features[f"candidate_max_drawdown_{horizon}s"] = _maximum_drawdown(window)
        features[f"candidate_recovery_{horizon}s"] = _recovery(window)
    for horizon in (20, 60):
        anchor = _anchor(records, captured_at, horizon)
        volume_delta, volume_delta_missing = _delta_rate_feature(
            current, anchor, "volume"
        )
        turnover_delta, turnover_delta_missing = _delta_rate_feature(
            current, anchor, "turnover"
        )
        features[f"candidate_volume_delta_rate_{horizon}s"] = volume_delta
        features[f"candidate_volume_delta_rate_{horizon}s_missing"] = float(
            volume_delta_missing
        )
        features[f"candidate_turnover_delta_rate_{horizon}s"] = turnover_delta
        features[f"candidate_turnover_delta_rate_{horizon}s_missing"] = float(
            turnover_delta_missing
        )
        rank_delta, rank_delta_missing = _delta_feature(
            current,
            anchor,
            "rank_score",
        )
        features[f"candidate_rank_delta_{horizon}s"] = rank_delta
        features[f"candidate_rank_delta_{horizon}s_missing"] = float(
            rank_delta_missing
        )
        flow_delta, flow_delta_missing = _delta_feature(
            current,
            anchor,
            "quote_main_net_inflow_ratio",
        )
        features[
            f"candidate_quote_main_net_inflow_ratio_delta_{horizon}s"
        ] = flow_delta
        features[
            f"candidate_quote_main_net_inflow_ratio_delta_{horizon}s_missing"
        ] = float(flow_delta_missing)
    return _finite_feature_mapping(features, IDENTITY_FEATURE_FIELDS)


def _history_record(
    row: Mapping[str, object], captured_at: datetime
) -> dict[str, object]:
    return {
        "captured_at": captured_at,
        "gain_pct": _number(row.get("change_pct")) or 0.0,
        "rank_score": _number(row.get("rank_score")) or 0.0,
        "volume": _number(row.get("volume")),
        "turnover": _number(row.get("turnover")),
        "quote_main_net_inflow_ratio": _fresh_quote_enrichment_value(
            row,
            "quote_main_net_inflow_ratio",
            captured_at,
        ),
    }


def _fresh_quote_enrichment_value(
    row: Mapping[str, object],
    field: str,
    captured_at: datetime,
) -> float | None:
    observed_at = _as_datetime(row.get("quote_flow_observed_at"))
    age = (
        (captured_at - observed_at).total_seconds()
        if observed_at is not None
        else None
    )
    if age is None or not 0.0 <= age <= MAXIMUM_QUOTE_ENRICHMENT_AGE_SECONDS:
        return None
    return _number(row.get(field))


def _lane_blockers(row: Mapping[str, object]) -> tuple[str, ...] | None:
    raw = row.get("lane_blocker_codes")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return None
    return tuple(
        dict.fromkeys(
            text
            for item in raw
            if (text := str(item).strip())
        )
    )


def _anchor(
    records: Sequence[Mapping[str, object]],
    captured_at: datetime,
    horizon_seconds: int | float,
) -> Mapping[str, object] | None:
    target = captured_at - timedelta(seconds=float(horizon_seconds))
    candidates = [
        record
        for record in records
        if isinstance(record.get("captured_at"), datetime)
        and record["captured_at"] <= target
        and (target - record["captured_at"]).total_seconds()
        <= MAXIMUM_SEQUENCE_ANCHOR_LAG_SECONDS
    ]
    return max(candidates, key=lambda record: record["captured_at"], default=None)


def _slope_feature(
    records: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    horizon: int,
    field: str,
) -> tuple[float, bool]:
    current_at = current["captured_at"]
    anchor = _anchor(records, current_at, horizon)
    if anchor is None:
        return 0.0, True
    elapsed = (current_at - anchor["captured_at"]).total_seconds()
    delta = _delta(current, anchor, field)
    if delta is None or elapsed <= 0:
        return 0.0, True
    return delta / elapsed * 60.0, False


def _acceleration_feature(
    records: Sequence[Mapping[str, object]],
    current: Mapping[str, object],
    horizon: int,
) -> tuple[float, bool]:
    current_at = current["captured_at"]
    start = _anchor(records, current_at, horizon)
    middle = _anchor(records, current_at, horizon / 2)
    if start is None or middle is None or start is middle:
        return 0.0, True
    first_elapsed = (middle["captured_at"] - start["captured_at"]).total_seconds()
    second_elapsed = (current_at - middle["captured_at"]).total_seconds()
    if first_elapsed <= 0 or second_elapsed <= 0:
        return 0.0, True
    first_slope = (
        float(middle["gain_pct"]) - float(start["gain_pct"])
    ) / first_elapsed * 60.0
    second_slope = (
        float(current["gain_pct"]) - float(middle["gain_pct"])
    ) / second_elapsed * 60.0
    return (second_slope - first_slope) / second_elapsed * 60.0, False


def _records_in_window(
    records: Sequence[Mapping[str, object]],
    captured_at: datetime,
    horizon: int,
) -> list[Mapping[str, object]]:
    start = captured_at - timedelta(seconds=horizon)
    return [
        record
        for record in records
        if isinstance(record.get("captured_at"), datetime)
        and start <= record["captured_at"] <= captured_at
    ]


def _maximum_drawdown(records: Sequence[Mapping[str, object]]) -> float:
    peak: float | None = None
    maximum = 0.0
    for record in records:
        gain = float(record["gain_pct"])
        peak = gain if peak is None else max(peak, gain)
        maximum = max(maximum, peak - gain)
    return maximum


def _recovery(records: Sequence[Mapping[str, object]]) -> float:
    if not records:
        return 0.0
    gains = [float(record["gain_pct"]) for record in records]
    return max(gains[-1] - min(gains), 0.0)


def _delta_rate_feature(
    current: Mapping[str, object],
    anchor: Mapping[str, object] | None,
    field: str,
) -> tuple[float, bool]:
    current_value = _number(current.get(field))
    anchor_value = _number(anchor.get(field)) if anchor is not None else None
    if current_value is None or anchor_value is None:
        return 0.0, True
    return (current_value - anchor_value) / max(abs(anchor_value), 1.0), False


def _delta(
    current: Mapping[str, object],
    anchor: Mapping[str, object] | None,
    field: str,
) -> float | None:
    current_value = _number(current.get(field))
    anchor_value = _number(anchor.get(field)) if anchor is not None else None
    if current_value is None or anchor_value is None:
        return None
    return current_value - anchor_value


def _delta_feature(
    current: Mapping[str, object],
    anchor: Mapping[str, object] | None,
    field: str,
) -> tuple[float, bool]:
    value = _delta(current, anchor, field)
    return (0.0, True) if value is None else (value, False)


def _distance_to_limit(row: Mapping[str, object]) -> float:
    last_price = _number(row.get("last_price"))
    limit_price = _number(row.get("limit_price"))
    if last_price is None or limit_price is None or limit_price <= 0:
        return 99.0
    return max((limit_price - last_price) / limit_price * 100.0, 0.0)


def _same_day_flow(
    value: object,
    source_date: object,
    trade_date: date,
) -> tuple[float, bool]:
    number = _number(value)
    if number is None or _as_date(source_date) != trade_date:
        return 0.0, True
    return number, False


def _normalized_future_observation(
    row: Mapping[str, object],
) -> dict[str, object] | None:
    captured_at = _as_datetime(row.get("captured_at"))
    if captured_at is None or row.get("is_stale", row.get("frame_is_stale")) is True:
        return None
    return {
        "captured_at": captured_at,
        "vt_symbol": str(row.get("vt_symbol") or ""),
        "board_lane": str(row.get("board_lane") or ""),
        "formal_action": str(row.get("formal_action") or "pass"),
        "formal_rank": _number(row.get("formal_rank")),
        "rank_score": _number(row.get("rank_score")),
    }


def _future_sort_key(row: Mapping[str, object]) -> tuple[object, ...]:
    formal_rank = _number(row.get("formal_rank"))
    rank_score = _number(row.get("rank_score"))
    rank_key = (0, formal_rank) if formal_rank is not None else (1, -(rank_score or 0.0))
    return (
        row["captured_at"],
        *rank_key,
        str(row.get("vt_symbol") or ""),
    )


def _continuous_horizon(
    start: datetime,
    end: datetime,
    observed_times: Sequence[datetime],
) -> bool:
    boundaries = [start, *observed_times, end]
    return bool(
        observed_times
        and all(
            0.0 <= (right - left).total_seconds() <= MAXIMUM_LABEL_GAP_SECONDS
            for left, right in zip(boundaries, boundaries[1:], strict=False)
        )
    )


def _unknown_label(row: dict[str, object], status: str) -> dict[str, object]:
    return {
        **row,
        "label_status": status,
        "formal_event_within_60s": None,
        "formal_identity_within_60s": None,
        "formal_identity_vt_symbol": None,
        "formal_event_at": None,
    }


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value not in (None, ""):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(SHANGHAI)


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(SHANGHAI).date() if value.tzinfo else None
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        digits = "".join(character for character in text if character.isdigit())
        if len(digits) < 8:
            return None
        try:
            return date.fromisoformat(f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}")
        except ValueError:
            return None


def _number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _normalized_ratio(value: object, *, missing: float) -> float:
    number = _number(value)
    if number is None:
        return missing
    return number / 100.0 if number > 1.0 else number


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _quantile(values: Sequence[float], quantile: float) -> float | None:
    finite = sorted(value for value in values if isfinite(float(value)))
    if not finite:
        return None
    position = (len(finite) - 1) * min(max(float(quantile), 0.0), 1.0)
    lower = int(position)
    upper = min(lower + 1, len(finite) - 1)
    weight = position - lower
    return finite[lower] * (1.0 - weight) + finite[upper] * weight


def _canonical_number(value: object) -> float | None:
    number = _number(value)
    return round(number, 10) if number is not None else None


def _finite_feature_mapping(
    values: Mapping[str, object],
    fields: Sequence[str],
) -> dict[str, float]:
    result: dict[str, float] = {}
    for field in fields:
        number = _canonical_number(values.get(field))
        if number is None:
            raise ValueError(f"point-trigger feature {field} must be finite")
        result[field] = number
    return result


def _rounded(value: object) -> float | None:
    number = _number(value)
    return round(number, 6) if number is not None else None


def _json_number(value: object) -> float | None:
    return _canonical_number(value)


def _iso_value(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value or "")
