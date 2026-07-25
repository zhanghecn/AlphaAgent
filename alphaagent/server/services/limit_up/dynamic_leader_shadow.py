"""Causal dynamic-concept leader identity for pre-board shadow ranking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from statistics import mean
from threading import Lock


POLICY_VERSION = "dynamic-concept-leader-shadow-v1"
ELIGIBLE_CONCEPT_STATES = frozenset({"warming", "launch"})
MAX_CONCEPT_LEADER_RANK = 5
LOCK_GRACE_SECONDS = 60.0
GLOBAL_TOP_LIMIT = 5


@dataclass
class _LeaderLock:
    concept_id: str
    concept_name: str
    locked_at: datetime
    last_observed_at: datetime
    last_eligible_at: datetime
    observed_frames: int = 1
    eligible_frames: int = 1
    consecutive_eligible_frames: int = 1
    drop_count: int = 0
    previously_eligible: bool = True


class DynamicLeaderTracker:
    """Lock the first valid theme and ignore stronger transient alternatives."""

    def __init__(self, *, grace_seconds: float = LOCK_GRACE_SECONDS) -> None:
        self._grace_seconds = max(float(grace_seconds), 0.0)
        self._trade_date: date | None = None
        self._locks: dict[str, _LeaderLock] = {}
        self._lock = Lock()

    def attach(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        captured_at: datetime,
        market_gate_passed: bool | None,
        universe_rows: Sequence[Mapping[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        """Attach locked identities while preserving the input D+1 ordering."""

        with self._lock:
            if self._trade_date != captured_at.date():
                self._trade_date = captured_at.date()
                self._locks.clear()
            market_theme_components = _market_theme_components(
                universe_rows if universe_rows is not None else rows
            )
            result = [
                self._attach_row(
                    row,
                    captured_at=captured_at,
                    market_gate_passed=market_gate_passed,
                    market_theme_components=market_theme_components,
                )
                for row in rows
            ]
            global_candidates = [
                row
                for row in result
                if _shadow(row).get("current_concept_top5") is True
            ]
            for global_rank, row in enumerate(global_candidates, start=1):
                shadow = _shadow(row)
                shadow["global_rank"] = global_rank
                shadow["global_top5"] = global_rank <= GLOBAL_TOP_LIMIT
            return result

    def _attach_row(
        self,
        row: Mapping[str, object],
        *,
        captured_at: datetime,
        market_gate_passed: bool | None,
        market_theme_components: Mapping[str, object],
    ) -> dict[str, object]:
        result = dict(row)
        symbol = str(result.get("vt_symbol") or "").strip().upper()
        contexts = _concept_contexts(result)
        contexts_by_id = {
            str(context.get("concept_id") or ""): context
            for context in contexts
            if context.get("concept_id")
        }
        trigger_allowed = result.get("concept_trigger_allowed") is True
        lock = self._locks.get(symbol)
        status = "waiting_theme" if contexts else "unavailable"
        current_context: Mapping[str, object] | None = None
        current_eligible = False

        if lock is not None:
            current_context = contexts_by_id.get(lock.concept_id)
            current_eligible = bool(
                trigger_allowed
                and current_context is not None
                and _is_eligible_context(current_context)
            )
            if current_context is not None:
                self._observe_lock(lock, captured_at, current_eligible)
            grace_active = bool(
                current_context is not None
                and str(current_context.get("concept_state") or "") == "observe"
                and _elapsed_seconds(lock.last_eligible_at, captured_at)
                <= self._grace_seconds
            )
            if current_eligible:
                status = "locked"
            elif grace_active:
                status = "cooling"
            else:
                self._locks.pop(symbol, None)
                lock = None
                current_context = None

        if lock is None:
            eligible = [
                context
                for context in contexts
                if trigger_allowed and _is_eligible_context(context)
            ]
            if eligible and symbol:
                current_context = min(eligible, key=_context_selection_key)
                lock = _LeaderLock(
                    concept_id=str(current_context.get("concept_id") or ""),
                    concept_name=str(current_context.get("concept_name") or ""),
                    locked_at=captured_at,
                    last_observed_at=captured_at,
                    last_eligible_at=captured_at,
                )
                self._locks[symbol] = lock
                current_eligible = True
                status = "locked"

        result["dynamic_leader_shadow"] = _shadow_payload(
            result,
            lock=lock,
            context=current_context,
            status=status,
            current_eligible=current_eligible,
            market_gate_passed=market_gate_passed,
            market_theme_components=market_theme_components,
        )
        return result

    @staticmethod
    def _observe_lock(
        lock: _LeaderLock,
        captured_at: datetime,
        eligible: bool,
    ) -> None:
        if captured_at <= lock.last_observed_at:
            return
        lock.observed_frames += 1
        if eligible:
            lock.eligible_frames += 1
            lock.consecutive_eligible_frames += 1
            lock.last_eligible_at = captured_at
        else:
            if lock.previously_eligible:
                lock.drop_count += 1
            lock.consecutive_eligible_frames = 0
        lock.previously_eligible = eligible
        lock.last_observed_at = captured_at


def _shadow_payload(
    row: Mapping[str, object],
    *,
    lock: _LeaderLock | None,
    context: Mapping[str, object] | None,
    status: str,
    current_eligible: bool,
    market_gate_passed: bool | None,
    market_theme_components: Mapping[str, object],
) -> dict[str, object]:
    observed = lock.observed_frames if lock is not None else 0
    eligible = lock.eligible_frames if lock is not None else 0
    financial = _mapping(row.get("financial_snapshot"))
    return {
        "policy_version": POLICY_VERSION,
        "status": status,
        "execution_effect": "none_research_only",
        "market_gate_passed": market_gate_passed,
        "concept_id": lock.concept_id if lock is not None else None,
        "concept_name": lock.concept_name if lock is not None else None,
        "concept_state": context.get("concept_state") if context else None,
        "concept_leader_rank": _integer(context.get("leader_rank")) if context else None,
        "locked_at": lock.locked_at.isoformat() if lock is not None else None,
        "observed_frames": observed,
        "eligible_frames": eligible,
        "consecutive_eligible_frames": (
            lock.consecutive_eligible_frames if lock is not None else 0
        ),
        "persistence_ratio": round(eligible / observed, 6) if observed else None,
        "drop_count": lock.drop_count if lock is not None else 0,
        "current_concept_top5": current_eligible,
        "global_rank": None,
        "global_top5": False,
        "components": {
            **dict(market_theme_components),
            "market_timing_state": _text(row.get("market_timing_state")),
            "prior_market_phase": _text(row.get("prior_market_phase")),
            "prior_market_advancing_rate": _number(
                row.get("prior_market_advancing_rate")
            ),
            "prior_market_failed_rate": _number(
                row.get("prior_market_failed_rate")
            ),
            "prior_market_sealed_count": _number(
                row.get("prior_market_sealed_count")
            ),
            "prior_market_first_board_count": _number(
                row.get("prior_market_first_board_count")
            ),
            "expected_d1_net_return_pct": _number(
                row.get("expected_d1_net_return_pct")
            ),
            "d1_win_probability": _number(row.get("d1_win_probability")),
            "touch_probability_3m": _number(row.get("touch_probability_3m")),
            "eventual_touch_probability": _number(
                row.get("eventual_touch_probability")
            ),
            "seal_probability_given_touch": _number(
                row.get("seal_probability_given_touch")
            ),
            "prior_turnover_percentile": _number(
                row.get("prior_turnover_percentile")
            ),
            "prior_amount_ratio_5d": _number(row.get("prior_amount_ratio_5d")),
            "current_turnover": _number(row.get("turnover")),
            "quote_main_net_inflow": _number(
                row.get("quote_main_net_inflow")
            ),
            "sector_main_net_inflow": _number(
                row.get("sector_main_net_inflow")
            ),
            "stock_main_net_inflow": _number(
                row.get("stock_main_net_inflow")
            ),
            "cash_flow_quality": _number(financial.get("cash_flow_quality")),
            "roe": _number(financial.get("roe")),
            "net_profit_yoy": _number(financial.get("net_profit_yoy")),
            "concept_strength_score": _number(
                context.get("strength_score") if context else None
            ),
            "concept_strength_rank": _integer(
                context.get("strength_rank") if context else None
            ),
            "concept_coverage_ratio": _number(
                context.get("coverage_ratio") if context else None
            ),
            "concept_observed_count": _number(
                context.get("observed_count") if context else None
            ),
            "concept_rise_ratio": _number(
                context.get("rise_ratio") if context else None
            ),
            "concept_median_change_pct": _number(
                context.get("median_change_pct") if context else None
            ),
            "concept_strong_5_count": _number(
                context.get("strong_5_count") if context else None
            ),
            "concept_strong_5_ratio": _number(
                context.get("strong_5_ratio") if context else None
            ),
            "concept_near_limit_count": _number(
                context.get("near_limit_count") if context else None
            ),
            "concept_near_limit_ratio": _number(
                context.get("near_limit_ratio") if context else None
            ),
            "concept_touched_count": _number(
                context.get("touched_count") if context else None
            ),
            "concept_sealed_count": _number(
                context.get("sealed_count") if context else None
            ),
            "concept_failed_count": _number(
                context.get("failed_count") if context else None
            ),
            "concept_seal_quality": _number(
                context.get("seal_quality") if context else None
            ),
            **{
                f"concept_{metric}_acceleration_{minutes}m": _number(
                    context.get(f"{metric}_acceleration_{minutes}m")
                    if context
                    else None
                )
                for metric in ("change", "turnover")
                for minutes in (1, 3, 5)
            },
        },
    }


def _market_theme_components(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    unique_contexts: dict[str, dict[str, object]] = {}
    for row in rows:
        for context in _concept_contexts(row):
            concept_id = str(context.get("concept_id") or "")
            if concept_id and concept_id not in unique_contexts:
                unique_contexts[concept_id] = context

    contexts = list(unique_contexts.values())
    ranked = sorted(contexts, key=_market_context_rank_key)[:10]
    rise_ratio = _mean_context_metric(ranked, "rise_ratio")
    strong_5_ratio = _mean_context_metric(ranked, "strong_5_ratio")
    near_limit_ratio = _mean_context_metric(ranked, "near_limit_ratio")
    return {
        "market_theme_scope": "all_ge3_trace_candidates",
        "market_theme_observed_concept_count": len(contexts),
        "market_theme_launch_count": sum(
            context.get("concept_state") == "launch" for context in contexts
        ),
        "market_theme_warming_count": sum(
            context.get("concept_state") == "warming" for context in contexts
        ),
        "market_theme_top10_strength_score": _mean_context_metric(
            ranked, "strength_score"
        ),
        "market_theme_top10_rise_ratio": rise_ratio,
        "market_theme_top10_strong_5_ratio": strong_5_ratio,
        "market_theme_top10_near_limit_ratio": near_limit_ratio,
        "market_theme_top10_strong_conversion": _ratio(
            strong_5_ratio, rise_ratio
        ),
        "market_theme_top10_near_limit_conversion": _ratio(
            near_limit_ratio, rise_ratio
        ),
    }


def _market_context_rank_key(context: Mapping[str, object]) -> tuple[object, ...]:
    return (
        _integer(context.get("strength_rank")) or 1_000_000,
        -(_number(context.get("strength_score")) or 0.0),
        str(context.get("concept_id") or ""),
    )


def _mean_context_metric(
    contexts: Sequence[Mapping[str, object]],
    field: str,
) -> float | None:
    values = [
        value
        for context in contexts
        if (value := _number(context.get(field))) is not None
    ]
    return round(mean(values), 6) if values else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0.0):
        return None
    return round(numerator / denominator, 6)


def _concept_contexts(row: Mapping[str, object]) -> list[dict[str, object]]:
    raw = row.get("concept_candidates")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        contexts = [dict(item) for item in raw if isinstance(item, Mapping)]
        if contexts:
            return contexts
    concept_id = str(row.get("concept_id") or "")
    if not concept_id:
        return []
    return [
        {
            "concept_id": concept_id,
            "concept_name": row.get("concept_name"),
            "concept_state": row.get("concept_state"),
            "strength_score": row.get("concept_strength_score"),
            "strength_rank": row.get("concept_strength_rank"),
            "leader_rank": row.get("concept_leader_rank"),
        }
    ]


def _is_eligible_context(context: Mapping[str, object]) -> bool:
    leader_rank = _integer(context.get("leader_rank"))
    return bool(
        str(context.get("concept_state") or "") in ELIGIBLE_CONCEPT_STATES
        and leader_rank is not None
        and 1 <= leader_rank <= MAX_CONCEPT_LEADER_RANK
    )


def _context_selection_key(context: Mapping[str, object]) -> tuple[object, ...]:
    return (
        0 if str(context.get("concept_state") or "") == "launch" else 1,
        _integer(context.get("leader_rank")) or 1_000_000,
        _integer(context.get("strength_rank")) or 1_000_000,
        -(_number(context.get("strength_score")) or 0.0),
        str(context.get("concept_id") or ""),
    )


def _shadow(row: Mapping[str, object]) -> dict[str, object]:
    value = row.get("dynamic_leader_shadow")
    return value if isinstance(value, dict) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    resolved = str(value or "").strip()
    return resolved or None


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _elapsed_seconds(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds(), 0.0)
