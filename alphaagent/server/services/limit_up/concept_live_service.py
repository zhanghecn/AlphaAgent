"""Atomic runtime cache for 30-second full-market concept snapshots."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.services.limit_up import concept_snapshot_repository as repository
from alphaagent.server.services.limit_up.concept_resonance import (
    aggregate_concept_strength,
    build_membership_index,
)
from alphaagent.server.services.limit_up.domain import is_eligible_main_board


SHANGHAI = ZoneInfo("Asia/Shanghai")
CONCEPT_REFRESH_SECONDS = 30
CONCEPT_MAX_AGE_SECONDS = 45
CONCEPT_MIN_QUOTE_COVERAGE = 0.90
_runtime_lock = Lock()
_refresh_lock = Lock()
_runtime_snapshot: dict[str, object] | None = None
_history: deque[dict[str, object]] = deque(maxlen=16)


class ConceptSnapshotUnavailable(RuntimeError):
    """Raised when a complete point-in-time concept frame cannot be built."""


def refresh_live_concept_snapshot(
    captured_at: datetime | None = None,
    *,
    adapter: AkShareAdapter | None = None,
    persist: bool = True,
) -> dict[str, object]:
    """Fetch, aggregate, persist, and atomically publish one complete frame."""

    local_at = _local_datetime(captured_at or datetime.now(SHANGHAI))
    if not _market_window_open(local_at):
        latest = get_latest_live_concept_snapshot(local_at)
        if latest is None:
            return _snapshot_after_refresh_error(
                local_at,
                ConceptSnapshotUnavailable("当前不在A股盘中概念扫描时段"),
            )
        quality = dict(latest.get("data_quality") or {})
        errors = list(quality.get("source_errors") or [])
        errors.append("当前不在A股盘中概念扫描时段")
        quality.update(
            {
                "status": "stale",
                "is_stale": True,
                "trigger_allowed": False,
                "source_errors": errors[-3:],
            }
        )
        latest["data_quality"] = quality
        return latest
    if not _refresh_lock.acquire(blocking=False):
        return _snapshot_after_refresh_error(
            local_at,
            ConceptSnapshotUnavailable("上一轮全市场概念扫描仍在运行"),
        )
    try:
        live_adapter = adapter or AkShareAdapter()
        quote_payload = live_adapter.all_stock_quotes()
        snapshot_date, membership_rows = repository.load_frozen_membership_rows(local_at.date())
        if snapshot_date is None or not membership_rows:
            raise ConceptSnapshotUnavailable("缺少 D-1 概念成员版本")
        membership = build_membership_index(
            membership_rows,
            snapshot_date=snapshot_date,
        )
        concepts = aggregate_concept_strength(
            _mapping_rows(quote_payload.get("items")),
            membership,
            captured_at=local_at,
            history_by_concept=_history_by_concept(_history),
        )
        snapshot = _runtime_payload(local_at, quote_payload, membership, concepts)
        quality = dict(snapshot.get("data_quality") or {})
        if quality.get("trigger_allowed") is not True:
            reasons: list[str] = []
            if quality.get("source_trade_date_valid") is not True:
                reasons.append(
                    f"来源交易日 {quality.get('source_trade_date') or '未知'} 与扫描日不一致"
                )
            coverage = _float(quality.get("quote_coverage_ratio"))
            if coverage < CONCEPT_MIN_QUOTE_COVERAGE:
                reasons.append(f"全市场行情覆盖率仅 {coverage * 100:.1f}%")
            raise ConceptSnapshotUnavailable("；".join(reasons) or "概念行情质量未通过")
        if persist:
            rows = repository.build_strength_snapshot_rows(
                repository.select_persisted_concepts(concepts),
                captured_at=local_at,
                membership_snapshot_date=snapshot_date,
                source=str(quote_payload.get("source") or "unknown"),
                source_updated_at=_optional_datetime(quote_payload.get("updated_at")),
            )
            repository.save_strength_snapshots(rows)
        _replace_runtime_snapshot(snapshot)
        return deepcopy(snapshot)
    except Exception as exc:
        return _snapshot_after_refresh_error(local_at, exc)
    finally:
        _refresh_lock.release()


def get_latest_live_concept_snapshot(
    now: datetime | None = None,
) -> dict[str, object] | None:
    local_now = _local_datetime(now or datetime.now(SHANGHAI))
    with _runtime_lock:
        snapshot = deepcopy(_runtime_snapshot)
    if snapshot is None:
        return None
    captured_at = _local_datetime(_required_datetime(snapshot.get("captured_at")))
    age_seconds = max((local_now - captured_at).total_seconds(), 0.0)
    quality = dict(snapshot.get("data_quality") or {})
    same_day = captured_at.date() == local_now.date()
    coverage = _float(quality.get("quote_coverage_ratio"))
    is_stale = age_seconds > CONCEPT_MAX_AGE_SECONDS or not same_day
    quality.update(
        {
            "age_seconds": round(age_seconds, 3),
            "is_stale": is_stale,
            "trigger_allowed": (
                not is_stale
                and coverage >= CONCEPT_MIN_QUOTE_COVERAGE
                and quality.get("source_trade_date_valid") is True
            ),
        }
    )
    if is_stale:
        quality["status"] = "stale"
    snapshot["data_quality"] = quality
    return snapshot


def clear_runtime_snapshot() -> None:
    global _runtime_snapshot
    with _runtime_lock:
        _runtime_snapshot = None
        _history.clear()


def _replace_runtime_snapshot(snapshot: Mapping[str, object]) -> None:
    global _runtime_snapshot
    materialized = deepcopy(dict(snapshot))
    with _runtime_lock:
        _runtime_snapshot = materialized
        _history.append(
            {
                "captured_at": materialized.get("captured_at"),
                "concepts": list(materialized.get("concepts") or []),
            }
        )


def _runtime_payload(
    captured_at: datetime,
    quote_payload: Mapping[str, object],
    membership: Mapping[str, object],
    concepts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    quotes = _mapping_rows(quote_payload.get("items"))
    quote_by_symbol = {
        str(quote.get("vt_symbol") or "").upper(): quote
        for quote in quotes
        if quote.get("vt_symbol")
    }
    by_symbol = membership.get("by_symbol")
    membership_symbols = set(by_symbol) if isinstance(by_symbol, Mapping) else set()
    observed_members = membership_symbols & quote_by_symbol.keys()
    coverage = (
        len(observed_members) / len(membership_symbols)
        if membership_symbols
        else 0.0
    )
    source_time = _optional_datetime(quote_payload.get("updated_at"))
    source_trade_date = _source_trade_date(quote_payload, source_time)
    source_date_valid = source_trade_date == captured_at.date().isoformat()
    radar_quotes = [
        dict(quote)
        for quote in quotes
        if is_eligible_main_board(
            str(quote.get("vt_symbol") or ""),
            str(quote.get("name") or ""),
        )
        and _float(quote.get("change_pct"), default=-100.0) >= 5.0
    ]
    ready = coverage >= CONCEPT_MIN_QUOTE_COVERAGE and source_date_valid
    return {
        "captured_at": captured_at.isoformat(),
        "trade_date": captured_at.date().isoformat(),
        "membership_snapshot_date": membership.get("snapshot_date"),
        "source": str(quote_payload.get("source") or "unknown"),
        "source_updated_at": source_time.isoformat() if source_time else None,
        "quotes": [dict(quote) for quote in quotes],
        "radar_quotes": radar_quotes,
        "membership": deepcopy(dict(membership)),
        "concepts": [dict(concept) for concept in concepts],
        "concepts_by_id": {
            str(concept.get("concept_id") or ""): dict(concept)
            for concept in concepts
            if concept.get("concept_id")
        },
        "concept_count": len(concepts),
        "data_quality": {
            "status": "ready" if ready else "degraded",
            "is_stale": False,
            "trigger_allowed": ready,
            "age_seconds": 0.0,
            "quote_count": len(quotes),
            "membership_symbol_count": len(membership_symbols),
            "observed_membership_symbol_count": len(observed_members),
            "quote_coverage_ratio": round(coverage, 6),
            "source_trade_date": source_trade_date,
            "source_trade_date_valid": source_date_valid,
            "source_errors": [],
        },
    }


def _snapshot_after_refresh_error(
    captured_at: datetime,
    error: Exception,
) -> dict[str, object]:
    with _runtime_lock:
        previous = deepcopy(_runtime_snapshot)
    if previous is None:
        return {
            "captured_at": captured_at.isoformat(),
            "trade_date": captured_at.date().isoformat(),
            "membership_snapshot_date": None,
            "source": "unavailable",
            "quotes": [],
            "radar_quotes": [],
            "membership": {},
            "concepts": [],
            "concepts_by_id": {},
            "concept_count": 0,
            "data_quality": {
                "status": "unavailable",
                "is_stale": True,
                "trigger_allowed": False,
                "age_seconds": None,
                "quote_coverage_ratio": 0.0,
                "source_trade_date_valid": False,
                "source_errors": [str(error)[:500]],
            },
        }
    quality = dict(previous.get("data_quality") or {})
    errors = list(quality.get("source_errors") or [])
    errors.append(str(error)[:500])
    quality.update(
        {
            "status": "degraded",
            "trigger_allowed": False,
            "source_errors": errors[-3:],
            "last_refresh_failed_at": captured_at.isoformat(),
        }
    )
    previous["data_quality"] = quality
    return previous


def _history_by_concept(
    history: Sequence[Mapping[str, object]],
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    for frame in history:
        captured_at = frame.get("captured_at")
        for concept in frame.get("concepts") or []:
            if not isinstance(concept, Mapping):
                continue
            concept_id = str(concept.get("concept_id") or "")
            if concept_id:
                result[concept_id].append({**dict(concept), "captured_at": captured_at})
    return result


def _source_trade_date(
    quote_payload: Mapping[str, object],
    source_time: datetime | None,
) -> str | None:
    explicit = str(quote_payload.get("trade_date") or "").strip()
    if explicit:
        return explicit[:10]
    return source_time.astimezone(SHANGHAI).date().isoformat() if source_time else None


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _required_datetime(value: object) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise ValueError("captured_at is required")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _market_window_open(value: datetime) -> bool:
    local = _local_datetime(value)
    if local.weekday() >= 5:
        return False
    minute = local.hour * 60 + local.minute
    return (
        9 * 60 + 15 <= minute <= 11 * 60 + 30
        or 13 * 60 <= minute <= 14 * 60 + 57
    )


def _float(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default
