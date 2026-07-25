"""Point-in-time first-board quality shared by historical and live paths."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.domain import is_eligible_main_board
from alphaagent.server.services.limit_up.lane_research import evaluate_lane_candidate
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    historical_prior_from_evidence,
    historical_prior_status,
    is_strictly_preboard,
)


REPLACED_TRIGGER_CHECK_CODES = frozenset({"stock_momentum"})
PREBOARD_DEFERRED_LANE_BLOCKERS = frozenset(
    {
        "first_touch_too_early",
        "industry_heat_unavailable",
        "intraday_support_unavailable",
        "intraday_support_breakdown",
        "first_board_local_setup_unconfirmed",
        "intraday_support_out_of_range",
    }
)


@dataclass(frozen=True)
class PreboardPools:
    adapter_input_count: int
    capture_pool: tuple[dict[str, object], ...]
    eligible_first_board_pool: tuple[dict[str, object], ...]
    quality_pool: tuple[dict[str, object], ...]
    rejection_counts: dict[str, int]
    candidate_audit: tuple[dict[str, object], ...] = ()


def evaluate_first_board_quality_at_time(
    candidate: Mapping[str, object],
    *,
    decision_at: datetime,
    market_gate: Mapping[str, object],
    execution_checks: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Apply the formal first-board quality rules to one visible frame."""

    point_in_time = {
        **dict(candidate),
        "board_lane": "first_board",
        "board_level": 1,
        "target_board": 1,
        "evaluation_time": decision_at.time().replace(microsecond=0).isoformat(),
        "signal_time": decision_at.time().replace(microsecond=0).isoformat(),
    }
    lane = evaluate_lane_candidate(point_in_time)
    with_lane = {**point_in_time, **lane}
    lane_blockers = tuple(str(value) for value in lane.get("blockers") or ())
    hard_blockers, deferred_blockers = _preboard_lane_blockers(lane_blockers)
    profitability = scheduled_execution.first_board_profitability_gate(with_lane)
    environment = first_board_action_environment_gate(
        with_lane,
        market_gate=market_gate,
        execution_checks=execution_checks,
    )
    universe_gate_passed = _universe_gate_passed(candidate)
    quality_gate_passed = bool(
        universe_gate_passed
        and lane.get("lane") == "first_board"
        and not hard_blockers
        and profitability.get("profitability_gate_passed") is True
    )
    evidence = candidate.get("historical_evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    prior = historical_prior_from_evidence(evidence)
    return {
        **with_lane,
        **profitability,
        **environment,
        "board_lane": "first_board",
        "lane_decision": lane.get("decision"),
        "lane_blockers": lane_blockers,
        "preboard_hard_blockers": hard_blockers,
        "preboard_deferred_blockers": deferred_blockers,
        "lane_support_score": lane.get("support_score"),
        "lane_entry_quality_score": lane.get("entry_quality_score"),
        "lane_rank_score": lane.get("rank_score"),
        "universe_gate_passed": universe_gate_passed,
        "quality_gate_passed": quality_gate_passed,
        "historical_prior": prior,
        "historical_prior_status": historical_prior_status(prior),
        "expected_d1_net_return_pct": prior.expected_d1_net_return_pct,
        "d1_win_probability": prior.d1_win_probability,
        "seal_probability_given_touch": prior.seal_probability_given_touch,
        "d1_win_probability_given_seal": prior.d1_win_probability_given_seal,
        "path_analog_expected_return_pct": _number(
            evidence.get("average_return_pct")
        ),
        "path_analog_win_probability": _percentage_probability(
            evidence.get("smoothed_win_rate")
        ),
        "path_analog_sample_count": _count(
            evidence.get("effective_sample_count")
        ),
    }


def first_board_action_environment_gate(
    candidate: Mapping[str, object],
    *,
    market_gate: Mapping[str, object],
    execution_checks: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Preserve every formal execution check except the replaced trigger clock."""

    preserved_failures = tuple(
        str(check.get("code") or "unknown_execution_check")
        for check in execution_checks
        if str(check.get("code") or "") not in REPLACED_TRIGGER_CHECK_CODES
        and str(check.get("parity_status") or "shared") == "shared"
        and check.get("blocking", True) is not False
        and str(check.get("status") or "pending")
        not in {"passed", "informational"}
    )
    diagnostic_failures = tuple(
        str(check.get("code") or "unknown_execution_check")
        for check in execution_checks
        if str(check.get("code") or "") not in REPLACED_TRIGGER_CHECK_CODES
        and str(check.get("parity_status") or "shared") != "shared"
        and check.get("blocking", True) is not False
        and str(check.get("status") or "pending")
        not in {"passed", "informational"}
    )
    raw_environment_parity = candidate.get("environment_check_parity")
    environment_parity = (
        raw_environment_parity
        if isinstance(raw_environment_parity, Mapping)
        else {}
    )
    environment_results = (
        ("snapshot_freshness", candidate.get("snapshot_fresh") is True),
        ("quote_freshness", candidate.get("quote_fresh") is True),
        ("risk_gate", candidate.get("risk_gate_passed") is True),
    )
    freshness_failures = tuple(
        code
        for code, passed in environment_results
        if not passed and str(environment_parity.get(code) or "shared") == "shared"
    )
    diagnostic_environment_failures = tuple(
        code
        for code, passed in environment_results
        if not passed and str(environment_parity.get(code) or "shared") != "shared"
    )
    market_failed = market_gate.get("passed") is not True
    market_shared = str(market_gate.get("parity_status") or "shared") == "shared"
    market_failures = ("market_gate",) if market_failed and market_shared else ()
    diagnostic_market_failures = (
        ("market_gate",) if market_failed and not market_shared else ()
    )
    preparation_failures = (
        *market_failures,
        *preserved_failures,
        *freshness_failures,
    )
    entry_window_failures = (
        () if candidate.get("entry_window_passed") is True else ("entry_window",)
    )
    failed = (*preparation_failures, *entry_window_failures)
    return {
        "preparation_environment_passed": not preparation_failures,
        "execution_environment_passed": not failed,
        "failed_environment_checks": failed,
        "diagnostic_environment_checks": (
            *diagnostic_market_failures,
            *diagnostic_failures,
            *diagnostic_environment_failures,
        ),
    }


def first_board_capture_gate(
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Apply the prior-only upper-bound filters before observation activation."""

    reasons: list[str] = []
    if not _universe_gate_passed(candidate):
        reasons.append("universe_gate")
    financial_risk = candidate.get("financial_risk")
    if (
        not isinstance(financial_risk, Mapping)
        or financial_risk.get("blocked") is not False
    ):
        reasons.append("risk_gate")
    profitability = scheduled_execution.first_board_profitability_gate(candidate)
    if profitability.get("profitability_gate_passed") is not True:
        reasons.append(
            str(
                profitability.get("profitability_gate_reason")
                or "profitability_gate"
            )
        )
    return {
        **profitability,
        "capture_gate_passed": not reasons,
        "capture_gate_reasons": tuple(reasons),
    }


def build_preboard_pools(
    candidates: Sequence[Mapping[str, object]],
    *,
    decision_at: datetime,
    market_gate: Mapping[str, object],
) -> PreboardPools:
    """Build every auditable pre-board layer from the same visible candidates."""

    capture: list[dict[str, object]] = []
    eligible: list[dict[str, object]] = []
    quality: list[dict[str, object]] = []
    candidate_audit: list[dict[str, object]] = []
    rejections: Counter[str] = Counter()
    for raw in candidates:
        candidate = dict(raw)
        capture_gate = first_board_capture_gate(candidate)
        if capture_gate.get("capture_gate_passed") is not True:
            reasons = tuple(
                capture_gate.get("capture_gate_reasons") or ("capture_gate",)
            )
            rejections.update(reasons)
            candidate_audit.append(
                _pool_candidate_audit(
                    candidate,
                    stage="capture_rejected",
                    rejection_codes=reasons,
                )
            )
            continue
        candidate.update(capture_gate)
        capture.append(candidate)
        evaluated = evaluate_first_board_quality_at_time(
            candidate,
            decision_at=decision_at,
            market_gate=market_gate,
            execution_checks=_execution_checks(candidate),
        )
        if evaluated.get("quality_gate_passed") is not True:
            reasons = tuple(
                evaluated.get("preboard_hard_blockers")
                or evaluated.get("lane_blockers")
                or ("quality_gate",)
            )
            rejections.update(reasons)
            candidate_audit.append(
                _pool_candidate_audit(
                    evaluated,
                    stage="quality_rejected",
                    rejection_codes=reasons,
                )
            )
            continue
        eligible.append(evaluated)
        change_pct = _number(evaluated.get("change_pct"))
        if change_pct is None or change_pct < 3.0:
            rejections["below_observation_floor"] += 1
            candidate_audit.append(
                _pool_candidate_audit(
                    evaluated,
                    stage="eligible_below_observation_floor",
                    rejection_codes=("below_observation_floor",),
                )
            )
        elif not is_strictly_preboard(evaluated):
            rejections["already_touched_or_failed"] += 1
            candidate_audit.append(
                _pool_candidate_audit(
                    evaluated,
                    stage="eligible_already_touched_or_failed",
                    rejection_codes=("already_touched_or_failed",),
                )
            )
        else:
            quality.append(evaluated)
            candidate_audit.append(
                _pool_candidate_audit(
                    evaluated,
                    stage="quality_pool",
                    rejection_codes=(),
                )
            )
    return PreboardPools(
        adapter_input_count=len(candidates),
        capture_pool=tuple(capture),
        eligible_first_board_pool=tuple(eligible),
        quality_pool=tuple(quality),
        rejection_counts=dict(sorted(rejections.items())),
        candidate_audit=tuple(candidate_audit),
    )


def _pool_candidate_audit(
    candidate: Mapping[str, object],
    *,
    stage: str,
    rejection_codes: Sequence[object],
) -> dict[str, object]:
    """Return label-free diagnostics for one candidate at one decision time."""

    return {
        "vt_symbol": str(candidate.get("vt_symbol") or ""),
        "trade_date": candidate.get("trade_date") or candidate.get("signal_date"),
        "decision_at": candidate.get("decision_at"),
        "change_pct": _number(candidate.get("change_pct")),
        "last_price": _number(candidate.get("last_price")),
        "limit_price": _number(candidate.get("limit_price")),
        "strictly_preboard": is_strictly_preboard(candidate),
        "pool_stage": stage,
        "rejection_codes": tuple(str(value) for value in rejection_codes),
        "quality_gate_passed": candidate.get("quality_gate_passed"),
        "profitability_gate_passed": candidate.get("profitability_gate_passed"),
        "historical_prior_status": candidate.get("historical_prior_status"),
        "lane_blockers": tuple(
            str(value) for value in candidate.get("lane_blockers") or ()
        ),
        "preboard_hard_blockers": tuple(
            str(value) for value in candidate.get("preboard_hard_blockers") or ()
        ),
        "preboard_deferred_blockers": tuple(
            str(value) for value in candidate.get("preboard_deferred_blockers") or ()
        ),
        "failed_environment_checks": tuple(
            str(value) for value in candidate.get("failed_environment_checks") or ()
        ),
        "diagnostic_environment_checks": tuple(
            str(value)
            for value in candidate.get("diagnostic_environment_checks") or ()
        ),
    }


def _execution_checks(
    candidate: Mapping[str, object],
) -> list[dict[str, object]]:
    raw_checks = candidate.get("execution_checks")
    if isinstance(raw_checks, Sequence) and not isinstance(raw_checks, (str, bytes)):
        return [dict(check) for check in raw_checks if isinstance(check, Mapping)]
    from alphaagent.server.services.limit_up.live_policy import (
        build_first_board_execution_checks_at_time,
    )

    return build_first_board_execution_checks_at_time(candidate)


def _preboard_lane_blockers(
    blockers: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    hard: list[str] = []
    deferred: list[str] = []
    for blocker in blockers:
        if blocker in PREBOARD_DEFERRED_LANE_BLOCKERS:
            deferred.append(blocker)
        else:
            hard.append(blocker)
    return tuple(hard), tuple(deferred)


def _universe_gate_passed(candidate: Mapping[str, object]) -> bool:
    explicit = candidate.get("universe_gate_passed")
    if explicit is not None:
        return explicit is True
    board_level = _integer(candidate.get("board_level"), 1)
    return bool(
        board_level == 1
        and candidate.get("previous_limit_up") is not True
        and is_eligible_main_board(
            str(candidate.get("vt_symbol") or ""),
            str(candidate.get("name") or ""),
        )
    )


def _integer(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _count(value: object) -> int | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    return int(number)


def _percentage_probability(value: object) -> float | None:
    number = _number(value)
    if number is None or not 0 <= number <= 100:
        return None
    return number / 100.0


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None
