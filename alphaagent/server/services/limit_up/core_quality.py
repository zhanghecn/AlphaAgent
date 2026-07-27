"""Single formal A+B+C quality contract shared by history and live execution."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from math import isfinite

from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.versions import CORE_ABC_STRATEGY_VERSION


CORE_QUALITY_CONTRACT_VERSION = CORE_ABC_STRATEGY_VERSION
PUBLIC_QUALITY_CONTRACT_VERSION = CORE_QUALITY_CONTRACT_VERSION
PUBLIC_QUALITY_MINIMUM_WIN_PROBABILITY = 0.50
PUBLIC_QUALITY_MINIMUM_EXPECTED_D1_NET_RETURN_PCT = 0.0
PUBLIC_QUALITY_PRIOR_STRENGTH = 10
MINIMUM_PRIOR_LIMIT_COUNT_126 = 2
MAXIMUM_PRIOR_LIMIT_COUNT_126 = 6
MINIMUM_INDUSTRY_TURNOVER_RATIO_5D = 1.0
MAXIMUM_C_STOCK_GENE_COMBINED_WIN_RATE = 30.0
MINIMUM_C_CONCEPT_PRIOR_SEALED_COUNT = 2
MAXIMUM_C_CONCEPT_PRIOR_SEALED_COUNT = 4
MINIMUM_C_CONCEPT_PRIOR_MAX_BOARD = 2
C_EVIDENCE_STATUS = "historical_proxy_pass_forward_unconfirmed"
C_RESCUABLE_REASONS = frozenset(
    {
        "same_stock_d1_samples_below_5",
        "same_stock_joint_rate_below_30",
        "prior_limit_count_126_above_6",
    }
)
C_RESCUABLE_LANES = frozenset({"first_board", "two_to_three"})
QUALITY_TIER_PRIORITY = {
    "A_industry_expanding": 0,
    "C_capital_diffusion_rescue": 1,
    "B_recognition_only": 2,
}
QUALITY_TIER_PRIORS = {
    "A_industry_expanding": {
        "wins": 35,
        "sample_count": 41,
        "expected_d1_net_return_pct": 3.0876,
    },
    "C_capital_diffusion_rescue": {
        "wins": 46,
        "sample_count": 72,
        "expected_d1_net_return_pct": 1.9156,
    },
    "B_recognition_only": {
        "wins": 18,
        "sample_count": 30,
        "expected_d1_net_return_pct": 1.2895,
    },
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


def ab_quality_gate(candidate: Mapping[str, object]) -> dict[str, object]:
    """Evaluate the frozen A+B base without applying the C rescue."""

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


def c_quality_gate(
    candidate: Mapping[str, object],
    *,
    base_decision: Mapping[str, object] | None = None,
    prior_ab_seen: bool = False,
    c_already_selected: bool = False,
) -> dict[str, object]:
    """Evaluate the first daily causal capital/diffusion rescue."""

    base = dict(base_decision or ab_quality_gate(candidate))
    lane = str(candidate.get("lane") or candidate.get("board_lane") or "")
    reason = str(base.get("core_quality_gate_reason") or "")
    phase = str(candidate.get("prior_market_phase") or "")
    prior_return = _optional_number(candidate.get("prior_return_5d_pct"))
    pullback = prior_return is not None and prior_return <= 0
    first_touch = str(candidate.get("signal_kind") or "") == "first_touch"
    industry_ratio = _optional_number(
        candidate.get("prior_industry_turnover_ratio_5d")
    )
    stock_gene = _optional_number(candidate.get("stock_gene_combined_win_rate"))
    prior_sealed = _optional_integer(
        candidate.get("intraday_concept_prior_sealed_count")
    )
    prior_max_board = _optional_integer(
        candidate.get("intraday_concept_prior_max_board")
    )
    concept_evidence = _concept_evidence_allowed(candidate)
    early_diffusion = bool(
        concept_evidence
        and prior_sealed is not None
        and MINIMUM_C_CONCEPT_PRIOR_SEALED_COUNT
        <= prior_sealed
        <= MAXIMUM_C_CONCEPT_PRIOR_SEALED_COUNT
        and prior_max_board is not None
        and prior_max_board >= MINIMUM_C_CONCEPT_PRIOR_MAX_BOARD
    )

    components: list[str] = []
    if (
        reason == "same_stock_d1_samples_below_5"
        and first_touch
        and phase == "mixed"
        and pullback
    ):
        components.append("static_mixed_pullback")
    if (
        industry_ratio is not None
        and industry_ratio >= MINIMUM_INDUSTRY_TURNOVER_RATIO_5D
        and stock_gene is not None
        and stock_gene < MAXIMUM_C_STOCK_GENE_COMBINED_WIN_RATE
        and (phase != "broad_rise" or pullback)
    ):
        components.append("static_industry_override")
    if early_diffusion and (
        (phase == "mixed" and first_touch)
        or (phase != "broad_rise" and pullback)
    ):
        components.append("concept_diffusion")

    passed = bool(
        base.get("core_quality_gate_passed") is not True
        and lane in C_RESCUABLE_LANES
        and reason in C_RESCUABLE_REASONS
        and not prior_ab_seen
        and not c_already_selected
        and components
    )
    if base.get("core_quality_gate_passed") is True:
        c_reason = "base_ab_qualified"
    elif lane not in C_RESCUABLE_LANES:
        c_reason = "lane_not_rescuable"
    elif reason not in C_RESCUABLE_REASONS:
        c_reason = "base_rejection_not_rescuable"
    elif prior_ab_seen:
        c_reason = "prior_ab_already_observed"
    elif c_already_selected:
        c_reason = "daily_c_slot_already_used"
    elif not components:
        c_reason = "c_components_not_qualified"
    else:
        c_reason = "qualified"
    return {
        "c_quality_gate_version": CORE_QUALITY_CONTRACT_VERSION,
        "c_quality_gate_passed": passed,
        "c_quality_gate_reason": c_reason,
        "c_quality_components": components,
        "c_quality_evidence_status": C_EVIDENCE_STATUS,
        "c_quality_prior_ab_seen": prior_ab_seen,
        "c_quality_daily_slot_used": c_already_selected,
    }


def core_quality_gate(
    candidate: Mapping[str, object],
    *,
    prior_ab_seen: bool = False,
    c_already_selected: bool = False,
) -> dict[str, object]:
    """Combine the A+B base, causal C rescue and tier-specific entry time."""

    base = ab_quality_gate(candidate)
    c_decision = c_quality_gate(
        candidate,
        base_decision=base,
        prior_ab_seen=prior_ab_seen,
        c_already_selected=c_already_selected,
    )
    base_passed = base["core_quality_gate_passed"] is True
    c_passed = c_decision["c_quality_gate_passed"] is True
    tier = (
        base.get("quality_priority_tier")
        if base_passed
        else "C_capital_diffusion_rescue"
        if c_passed
        else None
    )
    entry = quality_entry_gate(candidate, tier)
    passed = bool((base_passed or c_passed) and entry["quality_entry_gate_passed"])
    if passed:
        reason = "qualified_c_rescue" if c_passed else "qualified"
    elif (base_passed or c_passed) and not entry["quality_entry_gate_passed"]:
        reason = str(entry["quality_entry_gate_reason"])
    else:
        reason = str(base.get("core_quality_gate_reason") or "core_quality_rejected")
    return {
        **base,
        **c_decision,
        **entry,
        "base_ab_quality_gate_passed": base_passed,
        "base_ab_quality_gate_reason": base.get("core_quality_gate_reason"),
        "quality_priority_tier": tier,
        "core_quality_gate_passed": passed,
        "core_quality_gate_reason": reason,
    }


def public_quality_gate(
    candidate: Mapping[str, object],
    *,
    prior_ab_seen: bool = False,
    c_already_selected: bool = False,
    structural_gate_passed: bool | None = None,
    trigger_observed: bool = False,
) -> dict[str, object]:
    """Publish one A/B/C quality decision for pre-board and triggered paths."""

    core = core_quality_gate(
        candidate,
        prior_ab_seen=prior_ab_seen,
        c_already_selected=c_already_selected,
    )
    tier = str(core.get("quality_priority_tier") or "")
    prior = QUALITY_TIER_PRIORS.get(tier)
    structural_passed = _structural_gate_passed(
        candidate,
        explicit=structural_gate_passed,
    )
    preparation_passed = bool(
        structural_passed
        and (
            core.get("base_ab_quality_gate_passed") is True
            or core.get("c_quality_gate_passed") is True
        )
    )
    estimates = _quality_estimates(candidate, prior)
    win_probability = estimates["quality_win_probability"]
    expected_return = estimates["quality_expected_d1_net_return_pct"]
    estimate_passed = bool(
        win_probability is not None
        and win_probability >= PUBLIC_QUALITY_MINIMUM_WIN_PROBABILITY
        and expected_return is not None
        and expected_return > PUBLIC_QUALITY_MINIMUM_EXPECTED_D1_NET_RETURN_PCT
    )
    current_gate_passed = bool(
        preparation_passed
        and estimate_passed
        and (not trigger_observed or core.get("core_quality_gate_passed") is True)
    )
    actionable = bool(trigger_observed and current_gate_passed)
    if actionable:
        status = "actionable"
        reason = "qualified"
    elif not structural_passed:
        status = "rejected"
        reason = "structural_quality_rejected"
    elif not preparation_passed:
        status = "rejected"
        reason = str(
            core.get("base_ab_quality_gate_reason")
            or core.get("core_quality_gate_reason")
            or "abc_quality_rejected"
        )
    elif win_probability is None:
        status = "rejected"
        reason = "quality_win_probability_unavailable"
    elif win_probability < PUBLIC_QUALITY_MINIMUM_WIN_PROBABILITY:
        status = "rejected"
        reason = "quality_win_probability_below_50pct"
    elif expected_return is None:
        status = "rejected"
        reason = "quality_expected_d1_return_unavailable"
    elif expected_return <= PUBLIC_QUALITY_MINIMUM_EXPECTED_D1_NET_RETURN_PCT:
        status = "rejected"
        reason = "quality_expected_d1_return_not_positive"
    elif not trigger_observed:
        status = "qualified_waiting_trigger"
        reason = "waiting_for_trigger"
    else:
        status = "rejected"
        reason = str(
            core.get("quality_entry_gate_reason")
            or core.get("core_quality_gate_reason")
            or "trigger_not_actionable"
        )
    return {
        **core,
        **estimates,
        "public_quality_contract_version": PUBLIC_QUALITY_CONTRACT_VERSION,
        "public_quality_status": status,
        "public_quality_gate_passed": current_gate_passed,
        "public_quality_preparation_passed": bool(
            preparation_passed and estimate_passed
        ),
        "public_quality_actionable": actionable,
        "public_quality_trigger_observed": trigger_observed,
        "public_quality_structural_gate_passed": structural_passed,
        "public_quality_reason": reason,
        "quality_minimum_win_probability": (
            PUBLIC_QUALITY_MINIMUM_WIN_PROBABILITY
        ),
        "quality_minimum_expected_d1_net_return_pct": (
            PUBLIC_QUALITY_MINIMUM_EXPECTED_D1_NET_RETURN_PCT
        ),
    }


def quality_entry_gate(
    candidate: Mapping[str, object],
    tier: object,
) -> dict[str, object]:
    """Apply the causal A/C 10:00 and B first-board 10:30 entry clocks."""

    lane = str(candidate.get("lane") or candidate.get("board_lane") or "")
    signal_time = _time_text(
        candidate.get("buy_time") or candidate.get("signal_time")
    )
    signal_kind = str(candidate.get("signal_kind") or "first_touch")
    event = candidate.get("event_evidence")
    event = event if isinstance(event, Mapping) else {}
    if lane == "first_board" and signal_kind == "first_touch":
        first_limit_time = _time_text(
            candidate.get("first_limit_time") or event.get("first_limit_time")
        )
        if first_limit_time != "00:00:00":
            signal_time = first_limit_time
    effective_time = signal_time
    effective_kind = signal_kind
    is_b_first_board = tier == "B_recognition_only" and lane == "first_board"
    minimum_time = "10:30:00" if is_b_first_board else "10:00:00"
    if is_b_first_board and signal_time < minimum_time:
        last_limit_time, open_times = _b_reseal_evidence(candidate)
        if last_limit_time >= minimum_time and open_times > 0:
            effective_time = last_limit_time
            effective_kind = "reseal"
    passed = bool(
        tier
        and effective_time >= minimum_time
        and scheduled_execution.is_entry_time(effective_time)
    )
    return {
        "quality_entry_gate_passed": passed,
        "quality_entry_gate_reason": (
            "qualified" if passed else f"{str(tier or 'unclassified')}_outside_entry_window"
        ),
        "quality_entry_minimum_time": minimum_time,
        "quality_entry_effective_time": effective_time if passed else None,
        "quality_entry_effective_kind": effective_kind if passed else None,
    }


def filter_core_quality_qualified_orders(
    orders: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Keep every chronological order admitted by the one formal contract."""

    selected: list[dict[str, object]] = []
    reasons: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    indexed_orders = [
        (index, dict(order)) for index, order in enumerate(orders)
    ]
    indexed_orders.sort(
        key=lambda item: (
            _order_date_text(item[1]),
            _causal_order_time(item[1]),
            item[0],
        )
    )
    copied = [order for _, order in indexed_orders]
    prior_ab_seen = False
    c_already_selected = False
    index = 0
    while index < len(copied):
        order_date = _order_date_text(copied[index])
        signal_time = _causal_order_time(copied[index])
        if index == 0 or order_date != _order_date_text(copied[index - 1]):
            prior_ab_seen = False
            c_already_selected = False
        group: list[dict[str, object]] = []
        while (
            index < len(copied)
            and _order_date_text(copied[index]) == order_date
            and _causal_order_time(copied[index]) == signal_time
        ):
            group.append(copied[index])
            index += 1
        group.sort(
            key=lambda order: (
                quality_tier_priority(
                    public_quality_gate(
                        order,
                        prior_ab_seen=prior_ab_seen,
                        c_already_selected=c_already_selected,
                        trigger_observed=True,
                    )
                ),
                scheduled_execution.execution_lane_priority(order.get("lane")),
                _optional_integer(order.get("pool_rank")) or 1_000_000,
                str(order.get("vt_symbol") or ""),
            )
        )
        group_ab_selected = False
        for order in group:
            decision = public_quality_gate(
                order,
                prior_ab_seen=prior_ab_seen,
                c_already_selected=c_already_selected,
                trigger_observed=True,
            )
            order.update(decision)
            reasons[str(decision["public_quality_reason"])] += 1
            if decision["public_quality_actionable"] is not True:
                continue
            effective_time = decision.get("quality_entry_effective_time")
            if effective_time:
                order["buy_time"] = effective_time
                order["signal_time"] = effective_time
                order["signal_kind"] = decision.get("quality_entry_effective_kind")
            tier = str(decision.get("quality_priority_tier") or "unclassified")
            tiers[tier] += 1
            selected.append(order)
            if decision.get("base_ab_quality_gate_passed") is True:
                group_ab_selected = True
            if decision.get("c_quality_gate_passed") is True:
                c_already_selected = True
        if group_ab_selected:
            prior_ab_seen = True
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
        "contract_version": PUBLIC_QUALITY_CONTRACT_VERSION,
        "base_contract_version": CORE_QUALITY_CONTRACT_VERSION,
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
        "b_first_board_minimum_time": "10:30:00",
        "c_tier_is_actionable": True,
        "c_daily_limit": 1,
        "c_evidence_status": C_EVIDENCE_STATUS,
        "priority_rule": "A > C > B",
        "minimum_quality_win_probability": (
            PUBLIC_QUALITY_MINIMUM_WIN_PROBABILITY
        ),
        "minimum_quality_expected_d1_net_return_pct": (
            PUBLIC_QUALITY_MINIMUM_EXPECTED_D1_NET_RETURN_PCT
        ),
        "quality_estimate_prior_strength": PUBLIC_QUALITY_PRIOR_STRENGTH,
        "quality_tier_priors": {
            tier: dict(prior) for tier, prior in QUALITY_TIER_PRIORS.items()
        },
    }


def quality_tier_priority(candidate: Mapping[str, object]) -> int:
    """Put same-time signals in the formal A, C, B order."""

    tier = str(candidate.get("quality_priority_tier") or "")
    return QUALITY_TIER_PRIORITY.get(tier, len(QUALITY_TIER_PRIORITY))


def is_public_quality_prepared(candidate: Mapping[str, object]) -> bool:
    """Return whether the current public contract admits probability scoring."""

    win_probability = _optional_number(candidate.get("quality_win_probability"))
    expected_return = _optional_number(
        candidate.get("quality_expected_d1_net_return_pct")
    )
    return bool(
        candidate.get("public_quality_contract_version")
        == PUBLIC_QUALITY_CONTRACT_VERSION
        and candidate.get("public_quality_preparation_passed") is True
        and str(candidate.get("public_quality_status") or "")
        in {"qualified_waiting_trigger", "actionable"}
        and win_probability is not None
        and win_probability >= PUBLIC_QUALITY_MINIMUM_WIN_PROBABILITY
        and expected_return is not None
        and expected_return > PUBLIC_QUALITY_MINIMUM_EXPECTED_D1_NET_RETURN_PCT
    )


def _quality_estimates(
    candidate: Mapping[str, object],
    prior: Mapping[str, object] | None,
) -> dict[str, object]:
    if prior is None:
        return {
            "quality_tier_prior_win_probability": None,
            "quality_tier_prior_expected_d1_net_return_pct": None,
            "quality_tier_prior_sample_count": 0,
            "quality_estimate_prior_strength": PUBLIC_QUALITY_PRIOR_STRENGTH,
            "quality_estimate_stock_sample_count": 0,
            "quality_win_probability": None,
            "quality_expected_d1_net_return_pct": None,
        }
    prior_wins = int(prior["wins"])
    prior_count = int(prior["sample_count"])
    prior_win_probability = prior_wins / prior_count
    prior_return = float(prior["expected_d1_net_return_pct"])
    evidence = candidate.get("historical_evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    stock_count = max(
        _optional_integer(
            candidate.get("stock_d1_sample_count")
            if candidate.get("stock_d1_sample_count") is not None
            else evidence.get("d1_money_effect_sample_count")
        )
        or 0,
        0,
    )
    stock_win_rate = _percentage_probability(
        candidate.get("stock_d1_win_rate")
        if candidate.get("stock_d1_win_rate") is not None
        else evidence.get("d1_money_effect_win_rate")
    )
    stock_return = _optional_number(
        candidate.get("stock_d1_average_return_pct")
        if candidate.get("stock_d1_average_return_pct") is not None
        else evidence.get("d1_money_effect_average_return_pct")
    )
    win_sample_count = stock_count if stock_win_rate is not None else 0
    return_sample_count = stock_count if stock_return is not None else 0
    win_probability = _shrunken_estimate(
        prior_win_probability,
        stock_win_rate,
        win_sample_count,
    )
    expected_return = _shrunken_estimate(
        prior_return,
        stock_return,
        return_sample_count,
    )
    return {
        "quality_tier_prior_win_probability": prior_win_probability,
        "quality_tier_prior_expected_d1_net_return_pct": prior_return,
        "quality_tier_prior_sample_count": prior_count,
        "quality_estimate_prior_strength": PUBLIC_QUALITY_PRIOR_STRENGTH,
        "quality_estimate_stock_sample_count": max(
            win_sample_count,
            return_sample_count,
        ),
        "quality_win_probability": win_probability,
        "quality_expected_d1_net_return_pct": expected_return,
    }


def _shrunken_estimate(
    prior_value: float,
    stock_value: float | None,
    stock_sample_count: int,
) -> float:
    if stock_value is None or stock_sample_count <= 0:
        return prior_value
    return (
        prior_value * PUBLIC_QUALITY_PRIOR_STRENGTH
        + stock_value * stock_sample_count
    ) / (PUBLIC_QUALITY_PRIOR_STRENGTH + stock_sample_count)


def _structural_gate_passed(
    candidate: Mapping[str, object],
    *,
    explicit: bool | None,
) -> bool:
    if explicit is not None:
        return explicit
    candidate_value = candidate.get("quality_gate_passed")
    return candidate_value is True if isinstance(candidate_value, bool) else True


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
    if (
        industry_ratio is not None
        and industry_ratio >= MINIMUM_INDUSTRY_TURNOVER_RATIO_5D
    ):
        return "A_industry_expanding"
    return "B_recognition_only"


def _core_reason(
    profitability: Mapping[str, object],
    recognition: Mapping[str, object],
) -> str:
    if profitability.get("profitability_gate_passed") is not True:
        return str(
            profitability.get("profitability_gate_reason")
            or "profitability_rejected"
        )
    if recognition.get("recognition_gate_passed") is not True:
        return str(recognition.get("recognition_gate_reason") or "recognition_rejected")
    return "qualified"


def _concept_evidence_allowed(candidate: Mapping[str, object]) -> bool:
    if candidate.get("intraday_concept_membership_causal") is True:
        return candidate.get("concept_trigger_allowed") is True
    evidence = str(
        candidate.get("intraday_concept_membership_evidence_level") or ""
    )
    return evidence in {"point_in_time", "current_membership_survivorship_proxy"}


def _b_reseal_evidence(candidate: Mapping[str, object]) -> tuple[str, int]:
    event = candidate.get("event_evidence")
    event = event if isinstance(event, Mapping) else {}
    last_limit_time = _time_text(
        candidate.get("last_limit_time") or event.get("last_limit_time")
    )
    open_times = _optional_integer(
        candidate.get("open_times")
        if candidate.get("open_times") is not None
        else event.get("open_times")
    )
    return last_limit_time, open_times or 0


def _time_text(value: object) -> str:
    text = str(value or "").strip()
    if "T" in text:
        text = text.rsplit("T", 1)[-1]
    elif " " in text:
        text = text.rsplit(" ", 1)[-1]
    text = text.split("+", 1)[0].split("Z", 1)[0]
    parts = text.split(":")
    if len(parts) < 2:
        return "00:00:00"
    second = parts[2].split(".", 1)[0] if len(parts) >= 3 else "00"
    return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{second.zfill(2)}"


def _order_date_text(order: Mapping[str, object]) -> str:
    return str(order.get("entry_date") or order.get("signal_date") or "")[:10]


def _causal_order_time(order: Mapping[str, object]) -> str:
    base = ab_quality_gate(order)
    tier = (
        base.get("quality_priority_tier")
        if base.get("core_quality_gate_passed") is True
        else None
    )
    entry = quality_entry_gate(order, tier)
    return str(
        entry.get("quality_entry_effective_time")
        or _time_text(order.get("buy_time") or order.get("signal_time"))
    )


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


def _percentage_probability(value: object) -> float | None:
    number = _optional_number(value)
    if number is None or not 0 <= number <= 100:
        return None
    return number / 100.0
