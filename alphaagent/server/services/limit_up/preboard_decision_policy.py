"""Pure state and two-slot selection policy for pre-board decisions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from math import isfinite
from typing import TYPE_CHECKING

from alphaagent.server.services.limit_up import core_quality
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    PreboardExecutionMode,
    PreboardOpportunityCalibration,
    PreboardPolicyThresholds,
    PreboardRankingMode,
    PreboardState,
    is_observable_first_board,
    is_strictly_preboard,
)
from alphaagent.server.services.limit_up.scheduled_execution import MAX_POSITIONS

if TYPE_CHECKING:
    from alphaagent.server.services.limit_up.preboard_decision_model import (
        PreboardModelBundle,
    )


def evaluate_preboard_decisions(
    rows: Sequence[Mapping[str, object]],
    *,
    model_bundle: PreboardModelBundle | None,
    thresholds: PreboardPolicyThresholds | None,
    prior_actions: Sequence[Mapping[str, object]] = (),
    unavailable_status: str = "model_unavailable",
    execution_mode: PreboardExecutionMode = PreboardExecutionMode.RESEARCH_ONLY,
    ranking_mode: PreboardRankingMode = PreboardRankingMode.CURRENT_D1_FIRST,
    opportunity_calibration: PreboardOpportunityCalibration | None = None,
    enforce_position_capacity: bool = True,
) -> list[dict[str, object]]:
    """Run the shared scorer/state entry, failing closed without a promoted policy."""

    projected = [dict(row) for row in rows]
    if model_bundle is not None:
        from alphaagent.server.services.limit_up.preboard_decision_model import (
            score_preboard_rows,
        )

        projected = score_preboard_rows(model_bundle, projected)
    if thresholds is not None:
        return select_preboard_decisions(
            projected,
            thresholds,
            prior_actions=prior_actions,
            execution_mode=execution_mode,
            ranking_mode=ranking_mode,
            opportunity_calibration=opportunity_calibration,
            enforce_position_capacity=enforce_position_capacity,
        )
    decisions = [
        _research_only_decision(
            row,
            unavailable_status=unavailable_status,
            clear_probabilities=model_bundle is None,
        )
        for row in projected
    ]
    return sorted(
        decisions,
        key=lambda row: preboard_action_sort_key(
            row,
            ranking_mode=ranking_mode,
            opportunity_calibration=opportunity_calibration,
        ),
    )


def can_compete_for_action(
    row: Mapping[str, object],
    thresholds: PreboardPolicyThresholds,
) -> bool:
    """Return whether a row may compete for a real first-board slot now."""

    touch = _number(row.get("touch_probability_3m"))
    eventual = _number(row.get("eventual_touch_probability"))
    return bool(
        is_observable_first_board(row)
        and is_strictly_preboard(row)
        and core_quality.is_public_quality_prepared(row)
        and row.get("execution_environment_passed") is True
        and row.get("entry_window_passed") is True
        and str(row.get("probability_status") or "") == "ready"
        and touch is not None
        and touch >= thresholds.minimum_touch_probability_3m
        and eventual is not None
        and eventual >= thresholds.minimum_eventual_touch_probability
    )


def preboard_action_sort_key(
    row: Mapping[str, object],
    *,
    ranking_mode: PreboardRankingMode = PreboardRankingMode.CURRENT_D1_FIRST,
    opportunity_calibration: PreboardOpportunityCalibration | None = None,
) -> tuple[object, ...]:
    """Return one preregistered ordering with deterministic final ties."""

    stable_tail = (
        -_sort_number(row.get("lane_support_score")),
        str(row.get("decision_at") or row.get("signal_at") or ""),
        str(row.get("vt_symbol") or ""),
    )
    if ranking_mode is PreboardRankingMode.CURRENT_D1_FIRST:
        return (
            core_quality.quality_tier_priority(row),
            -_sort_number(row.get("quality_win_probability")),
            -_sort_number(row.get("quality_expected_d1_net_return_pct")),
            -_sort_number(row.get("touch_probability_3m")),
            -_sort_number(row.get("eventual_touch_probability")),
            -_sort_number(row.get("seal_probability_given_touch")),
            *stable_tail,
        )
    if ranking_mode is PreboardRankingMode.PURE_TOUCH_PROBABILITY:
        return (
            -_sort_number(row.get("touch_probability_3m")),
            -_sort_number(row.get("eventual_touch_probability")),
            -_sort_number(row.get("seal_probability_given_touch")),
            -_sort_number(row.get("expected_d1_net_return_pct")),
            -_sort_number(row.get("d1_win_probability")),
            *stable_tail,
        )
    if opportunity_calibration is None:
        raise ValueError("combined opportunity ranking requires fit calibration")
    return (
        core_quality.quality_tier_priority(row),
        -_sort_number(row.get("quality_win_probability")),
        -_sort_number(
            preboard_opportunity_value_pct(row, opportunity_calibration)
        ),
        -_sort_number(row.get("touch_probability_3m")),
        -_sort_number(row.get("eventual_touch_probability")),
        -_sort_number(row.get("seal_probability_given_touch")),
        -_sort_number(row.get("expected_d1_net_return_pct")),
        *stable_tail,
    )


def preboard_opportunity_value_pct(
    row: Mapping[str, object],
    calibration: PreboardOpportunityCalibration,
) -> float | None:
    """Estimate board-front net return across touch, seal, and failure branches."""

    eventual = _probability(row.get("eventual_touch_probability"))
    seal = _probability(row.get("seal_probability_given_touch"))
    expected_d1 = _number(row.get("quality_expected_d1_net_return_pct"))
    if eventual is None or seal is None or expected_d1 is None:
        return None
    return (
        eventual * seal * expected_d1
        + eventual
        * (1.0 - seal)
        * calibration.touched_unsealed_expected_return_pct
        + (1.0 - eventual) * calibration.non_touch_expected_return_pct
    )


def advance_preboard_state(
    row: Mapping[str, object],
    thresholds: PreboardPolicyThresholds,
    *,
    slot_available: bool,
    already_acted: bool,
) -> PreboardState:
    """Classify one visible row before the selector assigns a slot."""

    if _is_touched_or_failed(row):
        return PreboardState.MISSED
    if not is_observable_first_board(row):
        return PreboardState.REJECTED
    if already_acted:
        return PreboardState.OBSERVE
    if can_compete_for_action(row, thresholds):
        return (
            PreboardState.ACTIONABLE
            if slot_available
            else PreboardState.PREPARE
        )
    if _meets_prepare_thresholds(row, thresholds):
        return PreboardState.PREPARE
    return PreboardState.OBSERVE


def select_preboard_decisions(
    rows: Sequence[Mapping[str, object]],
    thresholds: PreboardPolicyThresholds,
    *,
    prior_actions: Sequence[Mapping[str, object]] = (),
    execution_mode: PreboardExecutionMode = PreboardExecutionMode.SHADOW,
    ranking_mode: PreboardRankingMode = PreboardRankingMode.CURRENT_D1_FIRST,
    opportunity_calibration: PreboardOpportunityCalibration | None = None,
    enforce_position_capacity: bool = True,
) -> list[dict[str, object]]:
    """Select full recommendations or a capacity-constrained account."""

    used_slots, acted_pairs = _prior_action_state(prior_actions)
    grouped: defaultdict[datetime, list[tuple[int, dict[str, object]]]] = defaultdict(list)
    invalid: list[tuple[int, dict[str, object]]] = []
    for index, raw in enumerate(rows):
        row = _ranking_fields(
            raw,
            ranking_mode=ranking_mode,
            opportunity_calibration=opportunity_calibration,
        )
        decision_at = _decision_at(row)
        if decision_at is None:
            invalid.append((index, row))
            continue
        row["decision_at"] = decision_at.isoformat()
        grouped[decision_at].append((index, row))

    decisions: list[dict[str, object]] = []
    for decision_at in sorted(grouped):
        indexed_rows = grouped[decision_at]
        trade_date = decision_at.date()
        available_slots = (
            [
                slot
                for slot in range(1, MAX_POSITIONS + 1)
                if slot not in used_slots[trade_date]
            ]
            if enforce_position_capacity
            else []
        )
        competitors = [
            (index, row)
            for index, row in indexed_rows
            if (pair := _pair(row, trade_date)) not in acted_pairs
            and can_compete_for_action(row, thresholds)
        ]
        competitors.sort(
            key=lambda item: preboard_action_sort_key(
                item[1],
                ranking_mode=ranking_mode,
                opportunity_calibration=opportunity_calibration,
            )
        )
        selected = (
            competitors[: len(available_slots)]
            if enforce_position_capacity
            else competitors
        )
        selected_slots = (
            {
                index: slot
                for (index, _row), slot in zip(
                    selected,
                    available_slots[: len(selected)],
                    strict=True,
                )
            }
            if enforce_position_capacity
            else {}
        )
        selected_indices = {index for index, _row in selected}

        ordered = [*selected]
        ordered.extend(
            item for item in indexed_rows if item[0] not in selected_indices
        )
        for index, row in ordered:
            pair = _pair(row, trade_date)
            selected_slot = selected_slots.get(index)
            selected_for_action = index in selected_indices
            already_acted = pair in acted_pairs
            state = advance_preboard_state(
                row,
                thresholds,
                slot_available=selected_for_action,
                already_acted=already_acted,
            )
            if state is PreboardState.ACTIONABLE:
                if selected_slot is not None:
                    used_slots[trade_date].add(selected_slot)
                if pair is not None:
                    acted_pairs.add(pair)
            decisions.append(
                {
                    **row,
                    "preboard_state": state,
                    "decision_state": state.value,
                    "daily_slot": (
                        selected_slot
                        if state is PreboardState.ACTIONABLE
                        and enforce_position_capacity
                        else None
                    ),
                    "portfolio_selected": bool(
                        state is PreboardState.ACTIONABLE
                        and enforce_position_capacity
                    ),
                    "selection_scope": (
                        "portfolio" if enforce_position_capacity else "recommendation"
                    ),
                    "decision_version": PREBOARD_DECISION_VERSION,
                    "policy_version": PREBOARD_DECISION_VERSION,
                    "policy_fingerprint": thresholds.fingerprint,
                    "ranking_mode": ranking_mode.value,
                    "action_locked": already_acted,
                    "execution_mode": execution_mode.value,
                    "actionable": bool(
                        state is PreboardState.ACTIONABLE
                        and execution_mode is PreboardExecutionMode.FORMAL
                    ),
                    "formal_strategy_changed": bool(
                        state is PreboardState.ACTIONABLE
                        and execution_mode is PreboardExecutionMode.FORMAL
                    ),
                }
            )

    for _index, row in invalid:
        decisions.append(
            {
                **row,
                "preboard_state": PreboardState.REJECTED,
                "decision_state": PreboardState.REJECTED.value,
                "daily_slot": None,
                "portfolio_selected": False,
                "selection_scope": (
                    "portfolio" if enforce_position_capacity else "recommendation"
                ),
                "decision_version": PREBOARD_DECISION_VERSION,
                "policy_version": PREBOARD_DECISION_VERSION,
                "policy_fingerprint": thresholds.fingerprint,
                "ranking_mode": ranking_mode.value,
                "action_locked": False,
                "execution_mode": execution_mode.value,
                "actionable": False,
                "formal_strategy_changed": False,
            }
        )
    return decisions


def _research_only_decision(
    row: Mapping[str, object],
    *,
    unavailable_status: str,
    clear_probabilities: bool,
) -> dict[str, object]:
    if _is_touched_or_failed(row):
        state = PreboardState.MISSED
    elif is_observable_first_board(row):
        state = PreboardState.OBSERVE
    else:
        state = PreboardState.REJECTED
    result = {
        **dict(row),
        "preboard_state": state,
        "decision_state": state.value,
        "daily_slot": None,
        "decision_version": PREBOARD_DECISION_VERSION,
        "policy_version": PREBOARD_DECISION_VERSION,
        "policy_fingerprint": None,
        "action_locked": False,
        "execution_mode": PreboardExecutionMode.RESEARCH_ONLY.value,
        "actionable": False,
        "formal_strategy_changed": False,
    }
    if clear_probabilities:
        result.update(
            {
                "probability_status": unavailable_status,
                "model_fingerprint": None,
                "touch_probability_3m": None,
                "eventual_touch_probability": None,
            }
        )
    return result


def _ranking_fields(
    raw: Mapping[str, object],
    *,
    ranking_mode: PreboardRankingMode,
    opportunity_calibration: PreboardOpportunityCalibration | None,
) -> dict[str, object]:
    row = dict(raw)
    row["ranking_mode"] = ranking_mode.value
    row["opportunity_value_pct"] = (
        preboard_opportunity_value_pct(row, opportunity_calibration)
        if opportunity_calibration is not None
        else None
    )
    return row


def _meets_prepare_thresholds(
    row: Mapping[str, object],
    thresholds: PreboardPolicyThresholds,
) -> bool:
    touch = _number(row.get("touch_probability_3m"))
    eventual = _number(row.get("eventual_touch_probability"))
    return bool(
        is_observable_first_board(row)
        and is_strictly_preboard(row)
        and core_quality.is_public_quality_prepared(row)
        and row.get("preparation_environment_passed") is True
        and str(row.get("probability_status") or "") == "ready"
        and touch is not None
        and touch >= thresholds.minimum_touch_probability_3m
        and eventual is not None
        and eventual >= thresholds.minimum_eventual_touch_probability
    )


def _is_touched_or_failed(row: Mapping[str, object]) -> bool:
    return bool(
        str(row.get("state") or "") in {"sealed", "resealed", "failed"}
        or not is_strictly_preboard(row)
        and is_observable_first_board(row)
    )


def _prior_action_state(
    rows: Sequence[Mapping[str, object]],
) -> tuple[defaultdict[date, set[int]], set[tuple[date, str]]]:
    used_slots: defaultdict[date, set[int]] = defaultdict(set)
    acted_pairs: set[tuple[date, str]] = set()
    for row in rows:
        state = str(row.get("preboard_state") or row.get("decision_state") or "")
        slot = _integer(row.get("daily_slot"))
        trade_date = _as_date(
            row.get("trade_date") or row.get("signal_date") or row.get("entry_date")
        )
        symbol = str(row.get("vt_symbol") or "").strip()
        if (
            state not in {PreboardState.ACTIONABLE.value, "action"}
            or slot is None
            or not 1 <= slot <= MAX_POSITIONS
            or trade_date is None
            or not symbol
        ):
            continue
        used_slots[trade_date].add(slot)
        acted_pairs.add((trade_date, symbol))
    return used_slots, acted_pairs


def _pair(
    row: Mapping[str, object],
    fallback_date: date,
) -> tuple[date, str] | None:
    trade_date = _as_date(row.get("trade_date") or row.get("signal_date"))
    symbol = str(row.get("vt_symbol") or "").strip()
    return (trade_date or fallback_date, symbol) if symbol else None


def _decision_at(row: Mapping[str, object]) -> datetime | None:
    value = row.get("decision_at") or row.get("signal_at")
    if isinstance(value, datetime):
        return value
    if value not in (None, ""):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    trade_date = _as_date(row.get("trade_date") or row.get("signal_date"))
    signal_time = str(row.get("signal_time") or "")
    if trade_date is None or not signal_time:
        return None
    try:
        return datetime.fromisoformat(f"{trade_date.isoformat()}T{signal_time}")
    except ValueError:
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


def _sort_number(value: object) -> float:
    parsed = _number(value)
    return parsed if parsed is not None else float("-inf")


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _probability(value: object) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and 0.0 <= parsed <= 1.0 else None


def _integer(value: object) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None else None
