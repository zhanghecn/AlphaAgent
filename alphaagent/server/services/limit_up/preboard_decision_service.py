"""Single orchestration entry for historical-equivalent live pre-board scoring."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.first_board_quality import (
    build_preboard_pools,
)
from alphaagent.server.services.limit_up.dynamic_leader_shadow import (
    DynamicLeaderTracker,
)
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    PreboardExecutionMode,
    PreboardPolicyThresholds,
    preboard_market_gate,
)
from alphaagent.server.services.limit_up.preboard_decision_features import (
    project_live_decision_features,
)
from alphaagent.server.services.limit_up.preboard_decision_policy import (
    evaluate_preboard_decisions,
    preboard_action_sort_key,
)
from alphaagent.server.services.limit_up.preboard_live_minute_buffer import (
    LiveMinuteBuffer,
)
from alphaagent.server.services.limit_up import (
    live_repository,
    preboard_decision_repository,
    radar_observation_repository,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.preboard_decision_settlement import (
    build_touch_labels,
    settle_decision_actions,
)

if TYPE_CHECKING:
    from alphaagent.server.services.limit_up.preboard_decision_model import (
        PreboardModelBundle,
    )


SHANGHAI = ZoneInfo("Asia/Shanghai")
CURRENT_DAY_FREEZE_TIME = time(15, 0)
MAXIMUM_SCAN_GAP_SECONDS = 60.0
MAXIMUM_SCAN_P90_SECONDS = 20.0
_LIVE_DYNAMIC_LEADER_TRACKER = DynamicLeaderTracker()


def score_live_preboard_snapshot(
    snapshot: Mapping[str, object],
    *,
    model_bundle: PreboardModelBundle | None,
    thresholds: PreboardPolicyThresholds | None,
    execution_mode: PreboardExecutionMode,
    minute_buffer: LiveMinuteBuffer,
    historical_promotion_status: str | None = None,
    leader_tracker: DynamicLeaderTracker | None = None,
) -> dict[str, object]:
    """Score the current high-quality pool with the shared causal pipeline."""

    decision_at = _decision_at(snapshot.get("captured_at"))
    candidates = _live_adapter_rows(snapshot)
    pools = build_preboard_pools(
        candidates,
        decision_at=decision_at,
        market_gate=_market_gate(snapshot),
    )
    minute_buffer.ingest_quality_pool(decision_at, pools.quality_pool)
    quality_pool_snapshots = minute_buffer.completed_quality_pool_snapshots(
        decision_at
    )
    projected = [
        _project_candidate(
            row,
            decision_at=decision_at,
            minute_buffer=minute_buffer,
            quality_pool_snapshots=quality_pool_snapshots,
        )
        for row in pools.quality_pool
    ]
    prior_actions = (
        preboard_decision_repository.load_decision_actions(
            trade_date=decision_at.date()
        )
        if thresholds is not None
        and execution_mode is not PreboardExecutionMode.RESEARCH_ONLY
        else []
    )
    decisions = evaluate_preboard_decisions(
        projected,
        model_bundle=model_bundle,
        thresholds=thresholds,
        prior_actions=prior_actions,
        execution_mode=execution_mode,
    )
    ranked = sorted(
        (
            dict(row)
            for row in decisions
            if str(row.get("decision_state") or "") not in {"missed", "rejected"}
        ),
        key=preboard_action_sort_key,
    )
    ranked = (leader_tracker or DynamicLeaderTracker()).attach(
        ranked,
        captured_at=decision_at,
        market_gate_passed=_market_gate(snapshot).get("passed") is True,
        universe_rows=candidates,
    )
    public_candidates = [
        row for row in ranked if _has_real_touch_probabilities(row)
    ]
    formal_changed = any(
        row.get("formal_strategy_changed") is True for row in ranked
    )
    action_saved = (
        preboard_decision_repository.save_decision_actions(
            ranked,
            thresholds=thresholds,
        )
        if thresholds is not None
        and execution_mode is not PreboardExecutionMode.RESEARCH_ONLY
        else 0
    )
    probability_status = (
        _probability_status(ranked)
        if projected
        else "no_eligible_candidates"
        if model_bundle is not None
        else "model_unavailable"
    )
    return {
        "status": probability_status,
        "probability_status": probability_status,
        "decision_version": PREBOARD_DECISION_VERSION,
        "historical_promotion_status": (
            historical_promotion_status or _historical_status(execution_mode)
        ),
        "execution_mode": execution_mode.value,
        "model_fingerprint": getattr(model_bundle, "fingerprint", None),
        "pool_counts": {
            "adapter_input": pools.adapter_input_count,
            "capture": len(pools.capture_pool),
            "eligible": len(pools.eligible_first_board_pool),
            "quality": len(pools.quality_pool),
        },
        "rejection_counts": dict(pools.rejection_counts),
        "preboard_candidates": public_candidates,
        "feature_rows": ranked,
        "observation_count": len(public_candidates),
        "action_saved": action_saved,
        "formal_strategy_changed": formal_changed,
    }


def score_active_live_preboard_snapshot(
    snapshot: Mapping[str, object],
    *,
    minute_buffer: LiveMinuteBuffer,
) -> dict[str, object]:
    """Load the sole current runtime and score without widening its execution mode."""

    if _optional_datetime(snapshot.get("captured_at")) is None:
        return _empty_live_score()
    runtime = preboard_decision_repository.load_active_decision_runtime()
    if runtime is None:
        return score_live_preboard_snapshot(
            snapshot,
            model_bundle=None,
            thresholds=None,
            execution_mode=PreboardExecutionMode.RESEARCH_ONLY,
            minute_buffer=minute_buffer,
            leader_tracker=_LIVE_DYNAMIC_LEADER_TRACKER,
        )
    result = score_live_preboard_snapshot(
        snapshot,
        model_bundle=runtime["model_bundle"],
        thresholds=runtime.get("thresholds"),
        execution_mode=runtime["execution_mode"],
        minute_buffer=minute_buffer,
        historical_promotion_status=str(
            runtime.get("historical_promotion_status") or ""
        ),
        leader_tracker=_LIVE_DYNAMIC_LEADER_TRACKER,
    )
    return {
        **result,
        "probability_qualification_status": runtime.get(
            "probability_qualification_status"
        ),
        "model_fingerprint": runtime.get("model_fingerprint"),
        "feature_fingerprint": runtime.get("feature_fingerprint"),
        "historical_promotion_status": runtime.get(
            "historical_promotion_status"
        ),
        "execution_mode": runtime["execution_mode"].value,
    }


def score_active_live_preboard_snapshot_safely(
    snapshot: Mapping[str, object],
    *,
    minute_buffer: LiveMinuteBuffer,
) -> dict[str, object]:
    """Reduce research-path failures to an explicit empty result."""

    try:
        return score_active_live_preboard_snapshot(
            snapshot,
            minute_buffer=minute_buffer,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            **_empty_live_score(status="error"),
            "error": str(exc),
        }


def freeze_and_settle(
    *,
    as_of: datetime | None = None,
    trade_date: date | None = None,
) -> dict[str, object]:
    """Freeze one completed live decision day and attach only future labels."""

    current_at = _local_datetime(as_of or datetime.now(SHANGHAI))
    target_date = _resolve_target_trade_date(current_at, trade_date)
    base = {
        "decision_version": PREBOARD_DECISION_VERSION,
        "probability_status": "model_unavailable",
        "historical_promotion_status": "insufficient_for_portfolio_promotion",
        "formal_strategy_changed": False,
        "action_saved": 0,
    }
    action_settlement = settle_decision_actions(as_of=current_at)
    settlement_rows = int(action_settlement.get("stages_closed") or 0)
    if target_date is None:
        return {
            **base,
            "status": "no_eligible_radar_day",
            "day_freeze_status": "not_run",
            "settlement": action_settlement,
            "rows_written": settlement_rows,
            "message": "no completed unfrozen radar day",
        }

    frames = radar_observation_repository.load_frames(target_date, target_date)
    observations = radar_observation_repository.load_observations(
        target_date,
        target_date,
    )
    publication_rows = live_repository.load_publication_audit_rows(target_date)
    feature_rows = preboard_decision_repository.load_decision_feature_rows(
        [target_date]
    )
    audit = _audit_label_scope(
        target_date,
        frames,
        observations,
        publication_rows,
    )
    missing_payload_count = sum(
        row.get("_decision_payload_present") is not True for row in feature_rows
    )
    raw_preboard_count = sum(_is_raw_preboard_observation(row) for row in observations)
    missing_live_decision_rows = missing_payload_count
    if raw_preboard_count and not feature_rows:
        missing_live_decision_rows = raw_preboard_count

    reasons = list(audit["reason_codes"])
    if missing_live_decision_rows:
        reasons.append("missing_live_decision_rows")
    reasons = list(dict.fromkeys(reasons))
    scope_complete = not reasons
    labels = build_touch_labels(
        feature_rows,
        observations,
        scope_complete=scope_complete,
    )
    labeled_rows = [
        {
            **{key: value for key, value in row.items() if not key.startswith("_")},
            **labels[(int(row["frame_id"]), str(row["vt_symbol"]))],
        }
        for row in feature_rows
    ]
    labels_written = preboard_decision_repository.label_decision_feature_rows(
        target_date,
        labels,
    )
    scope = preboard_decision_repository.save_decision_day_scope(
        target_date,
        status="complete" if scope_complete else "incomplete",
        frame_count=int(audit["frame_count"]),
        observation_count=len(observations),
        feature_rows=labeled_rows,
        reason_codes=reasons,
        audit_metrics={
            **dict(audit["metrics"]),
            "raw_preboard_observation_count": raw_preboard_count,
            "shared_feature_row_count": len(feature_rows),
            "scoreable_feature_row_count": sum(
                row.get("feature_status") == "scoreable" for row in feature_rows
            ),
            "missing_live_decision_rows": missing_live_decision_rows,
        },
    )
    rows_written = settlement_rows + labels_written + (
        1 if scope.get("status") == "frozen" else 0
    )
    status = "complete" if scope_complete else "incomplete_scope"
    return {
        **base,
        "status": status,
        "trade_date": target_date.isoformat(),
        "day_freeze_status": str(scope.get("status") or "unknown"),
        "feature_row_count": len(feature_rows),
        "labels_written": labels_written,
        "rows_written": rows_written,
        "settlement": action_settlement,
        "reason_codes": reasons,
        "audit_metrics": {
            **dict(audit["metrics"]),
            "missing_live_decision_rows": missing_live_decision_rows,
        },
        "message": (
            "shared live decisions frozen and causally labeled"
            if scope_complete
            else "scope incomplete; negative touch labels withheld"
        ),
    }


def _project_candidate(
    row: Mapping[str, object],
    *,
    decision_at: datetime,
    minute_buffer: LiveMinuteBuffer,
    quality_pool_snapshots: list[dict[str, object]],
) -> dict[str, object]:
    symbol = str(row.get("vt_symbol") or "")
    completed_bars = minute_buffer.completed_bars(symbol, decision_at)
    prepared = {
        **dict(row),
        "candidate": dict(row),
        "trade_date": decision_at.date().isoformat(),
        "decision_at": decision_at.isoformat(),
        "completed_minute_bars": completed_bars,
        "quality_pool_snapshots": quality_pool_snapshots,
        "source_quality": minute_buffer.source_quality(symbol, decision_at),
        "minute_source": "live_quote_buffer",
        "transaction_status": "incomplete_prefix",
        "transaction_feature_at": None,
        "transaction_features": {},
        "transaction_source": "unavailable",
    }
    return {
        **dict(row),
        "trade_date": prepared["trade_date"],
        "decision_at": prepared["decision_at"],
        **project_live_decision_features(prepared),
    }


def _live_adapter_rows(snapshot: Mapping[str, object]) -> list[dict[str, object]]:
    from alphaagent.server.services.limit_up.live_service import (
        live_preboard_adapter_rows,
    )

    return live_preboard_adapter_rows(snapshot)


def _market_gate(snapshot: Mapping[str, object]) -> Mapping[str, object]:
    recommendations = snapshot.get("early_radar_recommendations")
    recommendations = (
        recommendations if isinstance(recommendations, Mapping) else {}
    )
    market_gate = recommendations.get("market_gate")
    resolved = market_gate if isinstance(market_gate, Mapping) else {"passed": False}
    return preboard_market_gate(resolved)


def _decision_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError("captured_at must be an ISO datetime") from exc


def _resolve_target_trade_date(
    current_at: datetime,
    explicit: date | None,
) -> date | None:
    latest_completed = (
        current_at.date()
        if current_at.time().replace(tzinfo=None) >= CURRENT_DAY_FREEZE_TIME
        else current_at.date() - timedelta(days=1)
    )
    if explicit is not None:
        return explicit if explicit <= latest_completed else None
    frozen_dates = {
        value
        for row in preboard_decision_repository.load_decision_day_scopes()
        if (value := _as_date(row.get("trade_date"))) is not None
    }
    candidates = {
        value
        for value in radar_observation_repository.load_frame_dates()
        if value <= latest_completed and value not in frozen_dates
    }
    return min(candidates, default=None)


def _audit_label_scope(
    trade_date: date,
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
    publication_rows: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    window_frames = [
        dict(row)
        for row in frames
        if _as_date(row.get("trade_date")) == trade_date
        and (captured_at := _optional_datetime(row.get("captured_at"))) is not None
        and scheduled_execution.is_entry_time(_local_datetime(captured_at))
    ]
    window_frames.sort(key=lambda row: _datetime_key(row.get("captured_at")))
    reasons: list[str] = []
    if not window_frames:
        reasons.append("no_frames_in_entry_windows")
    frame_ids = {
        int(value)
        for row in window_frames
        if (value := row.get("id", row.get("frame_id"))) is not None
    }
    observation_counts = Counter(
        int(row["frame_id"])
        for row in observations
        if row.get("frame_id") in frame_ids
    )
    mismatch_count = 0
    for frame in window_frames:
        frame_id = frame.get("id", frame.get("frame_id"))
        expected = _integer(frame.get("capture_count"))
        if (
            frame_id is None
            or expected is None
            or expected != observation_counts.get(int(frame_id), 0)
        ):
            mismatch_count += 1
    if mismatch_count:
        reasons.append("observation_capture_count_mismatch")

    ready_ratio = _ratio(
        sum(row.get("quality_status") == "ready" for row in window_frames),
        len(window_frames),
    )
    non_stale_ratio = _ratio(
        sum(row.get("is_stale") is False for row in window_frames),
        len(window_frames),
    )
    if window_frames and ready_ratio < 0.98:
        reasons.append("ready_frame_ratio_below_98pct")
    if window_frames and non_stale_ratio < 0.98:
        reasons.append("non_stale_frame_ratio_below_98pct")

    gaps = _entry_window_gaps(trade_date, window_frames)
    maximum_gap = max(gaps, default=None)
    scan_p90 = _quantile(gaps, 0.90)
    if maximum_gap is None or maximum_gap > MAXIMUM_SCAN_GAP_SECONDS:
        reasons.append("entry_window_max_gap_above_60s")
    if scan_p90 is None or scan_p90 > MAXIMUM_SCAN_P90_SECONDS:
        reasons.append("scan_interval_p90_above_20s")
    publication = _publication_audit(trade_date, publication_rows)
    reasons.extend(publication["reason_codes"])
    return {
        "frame_count": len(window_frames),
        "reason_codes": tuple(dict.fromkeys(reasons)),
        "metrics": {
            "ready_frame_ratio": round(ready_ratio, 6),
            "non_stale_frame_ratio": round(non_stale_ratio, 6),
            "observation_capture_count_mismatch_count": mismatch_count,
            "entry_window_max_gap_seconds": maximum_gap,
            "scan_interval_p90_seconds": scan_p90,
            **dict(publication["metrics"]),
        },
    }


def _publication_audit(
    trade_date: date,
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    expected_minutes: set[datetime] = set()
    for start_text, end_text in scheduled_execution.ENTRY_WINDOWS:
        current = datetime.combine(
            trade_date,
            time.fromisoformat(start_text),
            tzinfo=SHANGHAI,
        )
        end = datetime.combine(
            trade_date,
            time.fromisoformat(end_text),
            tzinfo=SHANGHAI,
        )
        while current < end:
            expected_minutes.add(current)
            current += timedelta(minutes=1)

    published_minutes: set[datetime] = set()
    first_write_delays: list[float] = []
    for row in rows:
        captured_minute = _optional_datetime(
            row.get("captured_minute") or row.get("captured_at")
        )
        if captured_minute is None:
            continue
        local_minute = _local_datetime(captured_minute).replace(second=0, microsecond=0)
        if local_minute not in expected_minutes:
            continue
        published_minutes.add(local_minute)
        created_at = _optional_datetime(row.get("created_at"))
        if created_at is not None:
            first_write_delays.append(
                max(
                    (_local_datetime(created_at) - local_minute).total_seconds(),
                    0.0,
                )
            )

    expected_count = len(expected_minutes)
    published_count = len(published_minutes)
    coverage = _ratio(published_count, expected_count)
    delay_p90 = _quantile(first_write_delays, 0.90)
    reasons: list[str] = []
    if coverage < 0.98:
        reasons.append("public_snapshot_minute_coverage_below_98pct")
    if delay_p90 is None or delay_p90 > 30.0:
        reasons.append("public_first_write_delay_p90_above_30s")
    return {
        "reason_codes": tuple(reasons),
        "metrics": {
            "public_snapshot_expected_minute_count": expected_count,
            "public_snapshot_minute_count": published_count,
            "public_snapshot_minute_coverage_ratio": round(coverage, 6),
            "public_first_write_delay_p90_seconds": delay_p90,
        },
    }


def _entry_window_gaps(
    trade_date: date,
    frames: Sequence[Mapping[str, object]],
) -> list[float]:
    parsed = [
        _local_datetime(value)
        for row in frames
        if (value := _optional_datetime(row.get("captured_at"))) is not None
    ]
    result: list[float] = []
    for start_text, end_text in scheduled_execution.ENTRY_WINDOWS:
        start = datetime.combine(
            trade_date,
            time.fromisoformat(start_text),
            tzinfo=SHANGHAI,
        )
        end = datetime.combine(
            trade_date,
            time.fromisoformat(end_text),
            tzinfo=SHANGHAI,
        )
        in_window = sorted(value for value in parsed if start <= value < end)
        boundaries = [start, *in_window, end]
        result.extend(
            max((right - left).total_seconds(), 0.0)
            for left, right in zip(boundaries, boundaries[1:], strict=False)
        )
    return result


def _is_raw_preboard_observation(row: Mapping[str, object]) -> bool:
    if (
        str(row.get("board_lane") or "") != "first_board"
        or str(row.get("capture_state") or "")
        in {"sealed", "resealed", "failed", "limit_touch", "touched", "fill_followup"}
        or str(row.get("formal_action") or "") == "buy_now"
    ):
        return False
    change_pct = _number(row.get("change_pct"))
    last_price = _number(row.get("last_price"))
    limit_price = _number(row.get("limit_price"))
    return bool(
        change_pct is not None
        and change_pct >= 3.0
        and last_price is not None
        and limit_price is not None
        and 0 < last_price < limit_price
    )


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _datetime_key(value: object) -> str:
    parsed = _optional_datetime(value)
    return _local_datetime(parsed).isoformat() if parsed is not None else ""


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return _local_datetime(value).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _quantile(values: Sequence[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    index = min(int((len(ordered) - 1) * quantile), len(ordered) - 1)
    return round(ordered[index], 6)


def _probability_status(rows: list[dict[str, object]]) -> str:
    if any(_has_real_touch_probabilities(row) for row in rows):
        return "ready"
    for row in rows:
        status = str(row.get("probability_status") or "").strip()
        if status and status != "ready":
            return status
    return "model_unavailable"


def _has_real_touch_probabilities(row: Mapping[str, object]) -> bool:
    if str(row.get("probability_status") or "") != "ready":
        return False
    probabilities = (
        _number(row.get("touch_probability_3m")),
        _number(row.get("eventual_touch_probability")),
    )
    return all(
        value is not None and isfinite(value) and 0.0 <= value <= 1.0
        for value in probabilities
    )


def _empty_live_score(*, status: str = "model_unavailable") -> dict[str, object]:
    return {
        "status": status,
        "probability_status": status,
        "decision_version": PREBOARD_DECISION_VERSION,
        "historical_promotion_status": "insufficient_for_portfolio_promotion",
        "execution_mode": PreboardExecutionMode.RESEARCH_ONLY.value,
        "model_fingerprint": None,
        "feature_fingerprint": None,
        "preboard_candidates": [],
        "feature_rows": [],
        "observation_count": 0,
        "action_saved": 0,
        "formal_strategy_changed": False,
    }


def _historical_status(execution_mode: PreboardExecutionMode) -> str:
    return (
        "forward_pass_for_formal"
        if execution_mode is PreboardExecutionMode.FORMAL
        else "historical_pass_for_shadow"
        if execution_mode is PreboardExecutionMode.SHADOW
        else "insufficient_for_portfolio_promotion"
    )
