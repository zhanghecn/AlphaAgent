"""Single formal A+B quality contract shared by history and live execution."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from math import isfinite

from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.versions import CORE_AB_STRATEGY_VERSION


CORE_QUALITY_CONTRACT_VERSION = CORE_AB_STRATEGY_VERSION
MINIMUM_PRIOR_LIMIT_COUNT_126 = 2
MAXIMUM_PRIOR_LIMIT_COUNT_126 = 6
MINIMUM_INDUSTRY_TURNOVER_RATIO_5D = 1.0
QUALITY_TIER_PRIORITY = {
    "A_industry_expanding": 0,
    "B_recognition_only": 1,
}


def recognition_quality_gate(candidate: Mapping[str, object]) -> dict[str, object]:
    """Require prior market recognition without admitting overtraded stocks."""

    limit_count = _optional_integer(candidate.get("prior_limit_count_126"))
    passed, reason = _recognition_decision(limit_count)
    industry_ratio = _optional_number(
        candidate.get("prior_industry_turnover_ratio_5d")
    )
    tier = _priority_tier(passed, industry_ratio)
    return {
        "recognition_gate_version": CORE_QUALITY_CONTRACT_VERSION,
        "recognition_gate_passed": passed,
        "recognition_gate_reason": reason,
        "recognition_gate_prior_limit_count_126": limit_count,
        "recognition_gate_minimum_count": MINIMUM_PRIOR_LIMIT_COUNT_126,
        "recognition_gate_maximum_count": MAXIMUM_PRIOR_LIMIT_COUNT_126,
        "recognition_gate_industry_turnover_ratio_5d": industry_ratio,
        "quality_priority_tier": tier,
    }


def core_quality_gate(candidate: Mapping[str, object]) -> dict[str, object]:
    """Combine the causal base profitability gate with the A+B hard gate."""

    profitability = scheduled_execution.first_board_profitability_gate(candidate)
    recognition = recognition_quality_gate(candidate)
    profitability_passed = profitability["profitability_gate_passed"] is True
    recognition_passed = recognition["recognition_gate_passed"] is True
    passed = profitability_passed and recognition_passed
    return {
        **profitability,
        **recognition,
        "core_quality_contract_version": CORE_QUALITY_CONTRACT_VERSION,
        "core_quality_gate_passed": passed,
        "core_quality_gate_reason": _core_reason(
            profitability,
            recognition,
        ),
    }


def filter_core_quality_qualified_orders(
    orders: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Keep every chronological order admitted by the one formal contract."""

    selected: list[dict[str, object]] = []
    reasons: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    for raw_order in orders:
        order = dict(raw_order)
        decision = core_quality_gate(order)
        order.update(decision)
        reasons[str(decision["core_quality_gate_reason"])] += 1
        if decision["core_quality_gate_passed"] is not True:
            continue
        tier = str(decision.get("quality_priority_tier") or "unclassified")
        tiers[tier] += 1
        selected.append(order)
    return selected, {
        **core_quality_filter_metadata(),
        "input_count": len(orders),
        "selected_count": len(selected),
        "excluded_count": len(orders) - len(selected),
        "reason_counts": dict(sorted(reasons.items())),
        "tier_counts": dict(sorted(tiers.items())),
    }


def core_quality_filter_metadata() -> dict[str, object]:
    return {
        "contract_version": CORE_QUALITY_CONTRACT_VERSION,
        "first_board_minimum_d1_samples": (
            scheduled_execution.FIRST_BOARD_MIN_D1_SAMPLES
        ),
        "first_board_minimum_combined_rate": (
            scheduled_execution.FIRST_BOARD_MIN_COMBINED_RATE
        ),
        "minimum_prior_limit_count_126": MINIMUM_PRIOR_LIMIT_COUNT_126,
        "maximum_prior_limit_count_126": MAXIMUM_PRIOR_LIMIT_COUNT_126,
        "a_tier_industry_turnover_ratio_5d": MINIMUM_INDUSTRY_TURNOVER_RATIO_5D,
        "b_tier_is_actionable": True,
        "fallback_contract": None,
    }


def quality_tier_priority(candidate: Mapping[str, object]) -> int:
    """Put industry-expanding A signals before actionable B signals."""

    tier = str(candidate.get("quality_priority_tier") or "")
    return QUALITY_TIER_PRIORITY.get(tier, len(QUALITY_TIER_PRIORITY))


def _recognition_decision(limit_count: int | None) -> tuple[bool, str]:
    if limit_count is None:
        return False, "prior_limit_count_126_unavailable"
    if limit_count < MINIMUM_PRIOR_LIMIT_COUNT_126:
        return False, f"prior_limit_count_126_below_{MINIMUM_PRIOR_LIMIT_COUNT_126}"
    if limit_count > MAXIMUM_PRIOR_LIMIT_COUNT_126:
        return False, f"prior_limit_count_126_above_{MAXIMUM_PRIOR_LIMIT_COUNT_126}"
    return True, "qualified"


def _priority_tier(passed: bool, industry_ratio: float | None) -> str | None:
    if not passed:
        return None
    if industry_ratio is not None and industry_ratio >= MINIMUM_INDUSTRY_TURNOVER_RATIO_5D:
        return "A_industry_expanding"
    return "B_recognition_only"


def _core_reason(
    profitability: Mapping[str, object],
    recognition: Mapping[str, object],
) -> str:
    if profitability.get("profitability_gate_passed") is not True:
        return str(profitability.get("profitability_gate_reason") or "profitability_rejected")
    if recognition.get("recognition_gate_passed") is not True:
        return str(recognition.get("recognition_gate_reason") or "recognition_rejected")
    return "qualified"


def _optional_integer(value: object) -> int | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    if number is None or not isfinite(number) or not number.is_integer():
        return None
    return int(number)


def _optional_number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None
