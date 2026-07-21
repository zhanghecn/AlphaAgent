"""Immutable evidence and replay for point-trigger action settlement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
SETTLEMENT_EVIDENCE_VERSION = "limit-up-preboard-point-trigger-settlement-evidence-v1"
TOUCHED_CAPTURE_STATES = frozenset(
    {"sealed", "resealed", "failed", "limit_touch", "touched"}
)


def build_point_trigger_settlement_evidence(
    action: Mapping[str, object],
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Project the raw rows needed to replay fill and touch outcomes."""

    captured_at = _required_datetime(action.get("captured_at"), "captured_at")
    trade_date = _required_date(action.get("trade_date"), "trade_date")
    symbol = _required_text(action.get("vt_symbol"), "vt_symbol")
    if captured_at.astimezone(SHANGHAI).date() != trade_date:
        raise ValueError("settlement action date does not match captured_at")

    frame_by_id: dict[int, datetime] = {}
    for frame in frames:
        frame_id = _optional_integer(frame.get("id", frame.get("frame_id")))
        frame_at = _optional_datetime(frame.get("captured_at"))
        frame_date = _optional_date(frame.get("trade_date"))
        if (
            frame_id is None
            or frame_at is None
            or (frame_date is not None and frame_date != trade_date)
            or frame_at.astimezone(SHANGHAI).date() != trade_date
        ):
            continue
        if frame_id in frame_by_id and frame_by_id[frame_id] != frame_at:
            raise ValueError("settlement evidence has a duplicate frame identity")
        frame_by_id[frame_id] = frame_at

    horizon_end = captured_at + timedelta(seconds=60)
    horizon_frames = [
        {"frame_id": frame_id, "captured_at": frame_at}
        for frame_id, frame_at in frame_by_id.items()
        if captured_at < frame_at <= horizon_end
    ]
    horizon_frames.sort(
        key=lambda row: (
            _required_datetime(row["captured_at"], "captured_at"),
            int(row["frame_id"]),
        )
    )

    symbol_observations: list[dict[str, object]] = []
    seen_observation_frames: set[int] = set()
    for observation in observations:
        if str(observation.get("vt_symbol") or "").strip() != symbol:
            continue
        frame_id = _optional_integer(observation.get("frame_id"))
        observed_at = _optional_datetime(observation.get("captured_at"))
        if observed_at is None and frame_id is not None:
            observed_at = frame_by_id.get(frame_id)
        if (
            frame_id is None
            or observed_at is None
            or observed_at < captured_at
            or observed_at.astimezone(SHANGHAI).date() != trade_date
        ):
            continue
        if frame_id in seen_observation_frames:
            raise ValueError("settlement evidence has duplicate symbol observations")
        seen_observation_frames.add(frame_id)
        symbol_observations.append(
            {
                "frame_id": frame_id,
                "captured_at": observed_at,
                "quote_observed_at": _optional_datetime(
                    observation.get("quote_observed_at")
                ),
                "last_price": _required_positive_number(
                    observation.get("last_price"), "last_price"
                ),
                "capture_state": str(observation.get("capture_state") or ""),
            }
        )
    symbol_observations.sort(
        key=lambda row: (
            _required_datetime(row["captured_at"], "captured_at"),
            int(row["frame_id"]),
        )
    )
    return normalize_point_trigger_settlement_evidence(
        {
            "version": SETTLEMENT_EVIDENCE_VERSION,
            "trade_date": trade_date,
            "captured_at": captured_at,
            "vt_symbol": symbol,
            "horizon_frames": horizon_frames,
            "symbol_observations": symbol_observations,
        }
    )


def normalize_point_trigger_settlement_evidence(
    evidence: Mapping[str, object],
) -> dict[str, object]:
    """Validate and canonicalize one stored settlement evidence object."""

    if not isinstance(evidence, Mapping):
        raise ValueError("settlement_evidence must be a mapping")
    expected_fields = {
        "version",
        "trade_date",
        "captured_at",
        "vt_symbol",
        "horizon_frames",
        "symbol_observations",
    }
    if set(evidence) != expected_fields:
        raise ValueError("settlement_evidence does not match its frozen contract")
    if evidence.get("version") != SETTLEMENT_EVIDENCE_VERSION:
        raise ValueError("settlement_evidence version is invalid")

    trade_date = _required_date(evidence.get("trade_date"), "trade_date")
    captured_at = _required_datetime(evidence.get("captured_at"), "captured_at")
    symbol = _required_text(evidence.get("vt_symbol"), "vt_symbol")
    if captured_at.astimezone(SHANGHAI).date() != trade_date:
        raise ValueError("settlement_evidence date does not match captured_at")

    raw_frames = _required_rows(evidence.get("horizon_frames"), "horizon_frames")
    horizon_end = captured_at + timedelta(seconds=60)
    frames: list[dict[str, object]] = []
    seen_frame_ids: set[int] = set()
    for raw in raw_frames:
        if set(raw) != {"frame_id", "captured_at"}:
            raise ValueError("settlement horizon frame has unexpected fields")
        frame_id = _required_nonnegative_integer(raw.get("frame_id"), "frame_id")
        frame_at = _required_datetime(raw.get("captured_at"), "captured_at")
        if frame_id in seen_frame_ids or not captured_at < frame_at <= horizon_end:
            raise ValueError("settlement horizon frame is duplicate or out of range")
        seen_frame_ids.add(frame_id)
        frames.append({"frame_id": frame_id, "captured_at": _iso_datetime(frame_at)})
    frames.sort(key=lambda row: (str(row["captured_at"]), int(row["frame_id"])))

    raw_observations = _required_rows(
        evidence.get("symbol_observations"), "symbol_observations"
    )
    observations: list[dict[str, object]] = []
    seen_observation_frames: set[int] = set()
    for raw in raw_observations:
        if set(raw) != {
            "frame_id",
            "captured_at",
            "quote_observed_at",
            "last_price",
            "capture_state",
        }:
            raise ValueError("settlement observation has unexpected fields")
        frame_id = _required_nonnegative_integer(raw.get("frame_id"), "frame_id")
        observation_at = _required_datetime(raw.get("captured_at"), "captured_at")
        quote_at = _optional_datetime(raw.get("quote_observed_at"))
        if (
            frame_id in seen_observation_frames
            or observation_at < captured_at
            or observation_at.astimezone(SHANGHAI).date() != trade_date
        ):
            raise ValueError("settlement observation is duplicate or out of range")
        seen_observation_frames.add(frame_id)
        observations.append(
            {
                "frame_id": frame_id,
                "captured_at": _iso_datetime(observation_at),
                "quote_observed_at": _iso_datetime(quote_at) if quote_at else None,
                "last_price": _required_positive_number(
                    raw.get("last_price"), "last_price"
                ),
                "capture_state": str(raw.get("capture_state") or ""),
            }
        )
    observations.sort(key=lambda row: (str(row["captured_at"]), int(row["frame_id"])))
    return {
        "version": SETTLEMENT_EVIDENCE_VERSION,
        "trade_date": trade_date.isoformat(),
        "captured_at": _iso_datetime(captured_at),
        "vt_symbol": symbol,
        "horizon_frames": frames,
        "symbol_observations": observations,
    }


def point_trigger_settlement_evidence_fingerprint(
    evidence: Mapping[str, object],
) -> str:
    """Hash the complete canonical evidence object."""

    normalized = normalize_point_trigger_settlement_evidence(evidence)
    payload = json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"


def settlement_evidence_matches_action(
    evidence: Mapping[str, object],
    action: Mapping[str, object],
) -> bool:
    """Check that frozen evidence belongs to the exact saved action."""

    try:
        normalized = normalize_point_trigger_settlement_evidence(evidence)
        captured_at = _required_datetime(action.get("captured_at"), "captured_at")
        trade_date = _required_date(action.get("trade_date"), "trade_date")
        symbol = _required_text(action.get("vt_symbol"), "vt_symbol")
    except (TypeError, ValueError):
        return False
    return bool(
        normalized["trade_date"] == trade_date.isoformat()
        and normalized["captured_at"] == _iso_datetime(captured_at)
        and normalized["vt_symbol"] == symbol
    )


def replay_delayed_fill_outcome(
    action: Mapping[str, object],
    evidence: Mapping[str, object],
) -> dict[str, object] | None:
    """Recompute the conservative 20..60 second fill proxy."""

    if not settlement_evidence_matches_action(evidence, action):
        return None
    normalized = normalize_point_trigger_settlement_evidence(evidence)
    captured_at = _required_datetime(action.get("captured_at"), "captured_at")
    limit_price = _optional_number(action.get("limit_price"))
    if limit_price is None or limit_price <= 0:
        return None
    quotes: list[tuple[datetime, datetime, float]] = []
    for row in normalized["symbol_observations"]:
        observed_at = _required_datetime(row.get("captured_at"), "captured_at")
        quote_at = _optional_datetime(row.get("quote_observed_at"))
        price = _optional_number(row.get("last_price"))
        if quote_at is None or price is None:
            continue
        elapsed = (observed_at - captured_at).total_seconds()
        quote_elapsed = (quote_at - captured_at).total_seconds()
        quote_age = (observed_at - quote_at).total_seconds()
        if (
            20.0 <= elapsed <= 60.0
            and 20.0 <= quote_elapsed <= 60.0
            and 0.0 <= quote_age <= 60.0
        ):
            quotes.append((observed_at, quote_at, price))
    quotes.sort()
    first_quote = quotes[0] if quotes else None
    if first_quote is not None and first_quote[2] < limit_price:
        return {
            "fill_status": "filled",
            "fill_at": first_quote[0],
            "fill_price": first_quote[2],
            "fill_quote_observed_at": first_quote[1],
        }
    return {
        "fill_status": "queue_unknown_without_l2",
        "fill_at": None,
        "fill_price": None,
        "fill_quote_observed_at": first_quote[1] if first_quote else None,
    }


def replay_formal_identity_outcome(
    action: Mapping[str, object],
    feature_rows: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    """Recompute formal identity from the immutable same-frame feature label."""

    captured_at = _optional_datetime(action.get("captured_at"))
    trade_date = _optional_date(action.get("trade_date"))
    symbol = str(action.get("vt_symbol") or "").strip()
    frame_id = _optional_integer(action.get("frame_id"))
    if captured_at is None or trade_date is None or not symbol or frame_id is None:
        return None
    matches = [
        row
        for row in feature_rows
        if _optional_date(row.get("trade_date")) == trade_date
        and _optional_datetime(row.get("captured_at")) == captured_at
        and _optional_integer(row.get("frame_id")) == frame_id
        and str(row.get("vt_symbol") or "").strip() == symbol
    ]
    if len(matches) != 1 or matches[0].get("label_status") != "known":
        return None
    label = matches[0]
    event = label.get("formal_event_within_60s")
    identity = label.get("formal_identity_within_60s")
    identity_symbol = str(label.get("formal_identity_vt_symbol") or "").strip() or None
    event_at = _optional_datetime(label.get("formal_event_at"))
    if event is True:
        if (
            identity_symbol is None
            or event_at is None
            or not isinstance(identity, bool)
        ):
            return None
        matched = identity is True
        if matched != (identity_symbol == symbol):
            return None
        status = "matched" if matched else "missed"
    elif event is False:
        if identity is not False or identity_symbol is not None or event_at is not None:
            return None
        matched = False
        status = "no_event"
    else:
        return None
    return {
        "formal_identity_status": status,
        "formal_event_at": event_at,
        "formal_identity_vt_symbol": identity_symbol,
        "formal_identity_matched": matched,
    }


def replay_physical_touch_outcome(
    action: Mapping[str, object],
    evidence: Mapping[str, object],
    daily_bar: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """Recompute touch from radar evidence and final seal from the D-day bar."""

    if not settlement_evidence_matches_action(evidence, action):
        return None
    action_date = _optional_date(action.get("trade_date"))
    symbol = str(action.get("vt_symbol") or "").strip()
    limit_price = _optional_number(action.get("limit_price"))
    if (
        action_date is None
        or not symbol
        or limit_price is None
        or limit_price <= 0
        or not isinstance(daily_bar, Mapping)
        or _optional_date(daily_bar.get("trade_date")) != action_date
        or str(daily_bar.get("vt_symbol") or "").strip() != symbol
    ):
        return None
    high_price = _optional_number(daily_bar.get("high_price"))
    close_price = _optional_number(daily_bar.get("close_price"))
    if high_price is None or close_price is None or high_price <= 0 or close_price <= 0:
        return None

    normalized = normalize_point_trigger_settlement_evidence(evidence)
    observed_touch = next(
        (
            row
            for row in normalized["symbol_observations"]
            if str(row.get("capture_state") or "") in TOUCHED_CAPTURE_STATES
            or (_optional_number(row.get("last_price")) or 0.0) >= limit_price
        ),
        None,
    )
    official_touch = high_price + 1e-8 >= limit_price
    if observed_touch is not None and not official_touch:
        return None
    if not official_touch:
        return {
            "physical_touch_status": "not_touched",
            "physical_touch_at": None,
            "final_sealed": False,
        }
    return {
        "physical_touch_status": "touched",
        "physical_touch_at": (
            _required_datetime(observed_touch.get("captured_at"), "captured_at")
            if observed_touch is not None
            else None
        ),
        "final_sealed": close_price + 1e-8 >= limit_price,
    }


def _required_rows(value: object, name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    if any(not isinstance(row, Mapping) for row in value):
        raise ValueError(f"{name} must contain mappings")
    return list(value)


def _required_text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _required_date(value: object, name: str) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise ValueError(f"{name} must be a date")
    return parsed


def _optional_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(SHANGHAI).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _required_datetime(value: object, name: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _iso_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _optional_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0 or (isinstance(value, float) and not value.is_integer()):
        return None
    return parsed


def _required_nonnegative_integer(value: object, name: str) -> int:
    parsed = _optional_integer(value)
    if parsed is None:
        raise ValueError(f"{name} must be a non-negative integer")
    return parsed


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _required_positive_number(value: object, name: str) -> float:
    parsed = _optional_number(value)
    if parsed is None or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed
