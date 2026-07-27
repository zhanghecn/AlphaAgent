"""Causal forward shadow for the A+B capacity and concept rescue rule."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from math import isfinite, log1p

import pandas as pd

from alphaagent.server.services.limit_up import cash_backtest, scheduled_execution
from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    performance_summary,
)
from alphaagent.server.services.limit_up.quality_no_trade_reverse import (
    CAUSAL_RULE_VERSION,
    MAXIMUM_CONCEPT_PRIOR_SEALED_COUNT,
    MAXIMUM_STOCK_GENE_COMBINED_WIN_RATE,
    MINIMUM_CONCEPT_PRIOR_MAX_BOARD,
    MINIMUM_CONCEPT_PRIOR_SEALED_COUNT,
    MINIMUM_INDUSTRY_TURNOVER_RATIO_5D,
)
from alphaagent.server.services.limit_up.versions import CORE_ABC_STRATEGY_VERSION


SHADOW_VERSION = "limit-up-no-prior-ab-rescue-shadow-v2"
FORWARD_START_DATE = date(2026, 7, 27)
ENTRY_STATES = frozenset({"sealed", "resealed"})
ELIGIBLE_LANES = frozenset({"first_board", "two_to_three"})
RESCUABLE_REASONS = frozenset(
    {
        "same_stock_d1_samples_below_5",
        "same_stock_joint_rate_below_30",
        "prior_limit_count_126_above_6",
    }
)
MINIMUM_INCREMENTAL_WIN_RATE_PCT = 60.0
MINIMUM_INCREMENTAL_CLOSED_TRADES = 15
MINIMUM_ADDED_TRADE_DAYS = 10


def select_causal_quality_rescue_shadow(
    observations: Sequence[Mapping[str, object]],
    *,
    required_prior_dates: Mapping[date, date],
) -> list[dict[str, object]]:
    """Select the first observable rescue before any A+B signal on each day."""

    ordered = sorted(
        (dict(row) for row in observations),
        key=lambda row: (
            _as_date(row.get("trade_date")) or date.min,
            _as_datetime(row.get("captured_at")) or datetime.min,
            str(row.get("vt_symbol") or ""),
        ),
    )
    first_events = _first_stock_day_events(ordered)
    first_ab_at = _first_ab_times(ordered)
    event_concepts = {
        identity: _concept_ids(row)
        for identity, row in first_events.items()
    }
    event_index: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in first_events.values():
        trade_date = _as_date(row.get("trade_date"))
        if trade_date is not None:
            event_index[trade_date].append(row)

    selected_days: set[date] = set()
    selected: list[dict[str, object]] = []
    for identity, event in sorted(
        first_events.items(),
        key=lambda item: (
            item[0][0],
            _as_datetime(item[1].get("captured_at")) or datetime.min,
            item[0][1],
        ),
    ):
        trade_date, _symbol = identity
        captured_at = _as_datetime(event.get("captured_at"))
        if (
            trade_date < FORWARD_START_DATE
            or trade_date in selected_days
            or captured_at is None
            or not _base_candidate_ready(event)
        ):
            continue
        first_ab = first_ab_at.get(trade_date)
        if first_ab is not None and captured_at >= first_ab:
            continue
        enriched = _attach_intraday_concept_diffusion(
            event,
            prior_events=event_index.get(trade_date, ()),
            event_concepts=event_concepts,
            required_prior_date=required_prior_dates.get(trade_date),
        )
        components = _rescue_components(enriched)
        if not components:
            continue
        selected_days.add(trade_date)
        selected.append(
            {
                **enriched,
                "trade_date": trade_date,
                "signal_time": captured_at.time().replace(microsecond=0).isoformat(),
                "signal_kind": _signal_kind(enriched),
                "shadow_version": SHADOW_VERSION,
                "shadow_rule_version": CAUSAL_RULE_VERSION,
                "shadow_components": components,
                "shadow_reason": "+".join(components),
                "execution_mode": "research_only",
                "formal_strategy_changed": False,
                "promotion_eligible": False,
            }
        )
    return selected


def settle_quality_rescue_shadow(
    selections: Sequence[Mapping[str, object]],
    official_daily_bars: Sequence[Mapping[str, object]],
    *,
    trade_dates: Sequence[date],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Settle frozen shadow entries at the next official daily close."""

    ordered_dates = sorted(set(trade_dates))
    next_date = {
        current: ordered_dates[index + 1]
        for index, current in enumerate(ordered_dates[:-1])
    }
    bar_index = {
        (str(row.get("vt_symbol") or ""), _as_date(row.get("trade_date"))): row
        for row in official_daily_bars
        if str(row.get("vt_symbol") or "") and _as_date(row.get("trade_date"))
    }
    closed: list[dict[str, object]] = []
    right_censored = 0
    missing_exit = 0
    invalid_settlement = 0
    for raw_selection in selections:
        selection = dict(raw_selection)
        signal_date = _as_date(selection.get("trade_date"))
        result_date = next_date.get(signal_date) if signal_date else None
        if result_date is None:
            right_censored += 1
            continue
        symbol = str(selection.get("vt_symbol") or "")
        bar = bar_index.get((symbol, result_date))
        exit_price = _number(bar.get("close_price")) if bar else None
        entry_price = _number(selection.get("limit_price"))
        if exit_price is None or exit_price <= 0:
            missing_exit += 1
            continue
        if entry_price is None or entry_price <= 0:
            invalid_settlement += 1
            continue
        outcome = cash_backtest.calculate_round_trip_outcome(
            entry_price,
            exit_price,
            limit_price=entry_price,
        )
        if outcome is None:
            invalid_settlement += 1
            continue
        closed.append(
            {
                **selection,
                "signal_date": signal_date,
                "result_date": result_date,
                "official_exit_price": exit_price,
                "return_pct": outcome["net_return_pct"],
            }
        )
    return closed, {
        "selection_count": len(selections),
        "closed_count": len(closed),
        "right_censored_count": right_censored,
        "missing_official_exit_count": missing_exit,
        "invalid_settlement_count": invalid_settlement,
    }


def evaluate_quality_rescue_shadow(
    baseline_trades: Sequence[Mapping[str, object]],
    shadow_trades: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Evaluate full-list quality without changing the formal strategy."""

    baseline_frame = _performance_frame(baseline_trades)
    shadow_frame = _performance_frame(shadow_trades)
    combined_frame = pd.concat([baseline_frame, shadow_frame], ignore_index=True)
    baseline = performance_summary(baseline_frame)
    incremental = performance_summary(shadow_frame)
    combined = performance_summary(combined_frame)
    baseline_dates = _trade_date_set(baseline_frame)
    shadow_dates = _trade_date_set(shadow_frame)
    added_days = len(shadow_dates - baseline_dates)
    checks = _acceptance_checks(
        baseline,
        incremental,
        combined,
        added_days=added_days,
    )
    enough_samples = bool(
        int(incremental.get("closed_count") or 0) >= MINIMUM_INCREMENTAL_CLOSED_TRADES
        and added_days >= MINIMUM_ADDED_TRADE_DAYS
    )
    passed = all(check["passed"] for check in checks)
    return {
        "shadow_version": SHADOW_VERSION,
        "shadow_rule_version": CAUSAL_RULE_VERSION,
        "formal_contract": CORE_ABC_STRATEGY_VERSION,
        "execution_mode": "research_only",
        "formal_strategy_changed": False,
        "promotion_eligible": False,
        "baseline": baseline,
        "incremental": incremental,
        "combined": combined,
        "baseline_trade_days": len(baseline_dates),
        "incremental_trade_days": len(shadow_dates),
        "added_trade_days": added_days,
        "acceptance_checks": checks,
        "forward_gate_passed": passed,
        "status": (
            "forward_candidate_research_only"
            if passed
            else "forward_rejected"
            if enough_samples
            else "collecting_forward"
        ),
    }


def _first_stock_day_events(
    observations: Sequence[Mapping[str, object]],
) -> dict[tuple[date, str], dict[str, object]]:
    result: dict[tuple[date, str], dict[str, object]] = {}
    for row in observations:
        trade_date = _as_date(row.get("trade_date"))
        symbol = str(row.get("vt_symbol") or "").strip()
        if (
            trade_date is None
            or not symbol
            or str(row.get("capture_state") or "") not in ENTRY_STATES
        ):
            continue
        result.setdefault((trade_date, symbol), dict(row))
    return result


def _first_ab_times(
    observations: Sequence[Mapping[str, object]],
) -> dict[date, datetime]:
    result: dict[date, datetime] = {}
    for row in observations:
        if str(row.get("formal_action") or "") != "buy_now":
            continue
        trade_date = _as_date(row.get("trade_date"))
        captured_at = _as_datetime(row.get("captured_at"))
        if trade_date is None or captured_at is None:
            continue
        result[trade_date] = min(result.get(trade_date, captured_at), captured_at)
    return result


def _attach_intraday_concept_diffusion(
    candidate: Mapping[str, object],
    *,
    prior_events: Sequence[Mapping[str, object]],
    event_concepts: Mapping[tuple[date, str], set[str]],
    required_prior_date: date | None,
) -> dict[str, object]:
    trade_date = _as_date(candidate.get("trade_date"))
    symbol = str(candidate.get("vt_symbol") or "")
    captured_at = _as_datetime(candidate.get("captured_at"))
    membership_date = _as_date(candidate.get("concept_membership_snapshot_date"))
    membership_causal = bool(
        required_prior_date is not None and membership_date == required_prior_date
    )
    choices: list[dict[str, object]] = []
    if trade_date is not None and captured_at is not None and membership_causal:
        for concept in _concept_candidates(candidate):
            concept_id = str(concept.get("concept_id") or "")
            member_count = _integer(concept.get("member_count"))
            if not concept_id or member_count is None or member_count <= 0:
                continue
            leaders = []
            for event in prior_events:
                event_symbol = str(event.get("vt_symbol") or "")
                event_at = _as_datetime(event.get("captured_at"))
                event_membership = _as_date(
                    event.get("concept_membership_snapshot_date")
                )
                identity = (trade_date, event_symbol)
                if (
                    event_symbol == symbol
                    or event_at is None
                    or event_at > captured_at
                    or event_membership != required_prior_date
                    or concept_id not in event_concepts.get(identity, set())
                ):
                    continue
                leaders.append(event)
            if not leaders:
                continue
            sealed_count = len(leaders)
            density = sealed_count / member_count
            choices.append(
                {
                    "concept_id": concept_id,
                    "concept_name": concept.get("concept_name") or concept_id,
                    "prior_sealed_count": sealed_count,
                    "prior_max_board": max(
                        _integer(row.get("board_level")) or 1 for row in leaders
                    ),
                    "member_count": member_count,
                    "density": density,
                    "score": density * log1p(sealed_count),
                }
            )
    selected = max(
        choices,
        key=lambda row: (
            float(row["score"]),
            int(row["prior_max_board"]),
            -int(row["member_count"]),
            str(row["concept_id"]),
        ),
        default=None,
    )
    return {
        **dict(candidate),
        "intraday_concept_membership_causal": membership_causal,
        "intraday_concept_feature_ready": selected is not None,
        "intraday_concept_id": selected.get("concept_id") if selected else None,
        "intraday_concept_name": selected.get("concept_name") if selected else None,
        "intraday_concept_prior_sealed_count": (
            selected.get("prior_sealed_count") if selected else 0
        ),
        "intraday_concept_candidate_rank": (
            int(selected["prior_sealed_count"]) + 1 if selected else 1
        ),
        "intraday_concept_prior_max_board": (
            selected.get("prior_max_board") if selected else 0
        ),
        "intraday_concept_member_count": (
            selected.get("member_count") if selected else None
        ),
        "intraday_concept_diffusion_density": (
            selected.get("density") if selected else None
        ),
    }


def _rescue_components(row: Mapping[str, object]) -> list[str]:
    phase = str(row.get("prior_market_phase") or "")
    prior_return = _number(row.get("prior_return_5d_pct"))
    pullback = prior_return is not None and prior_return <= 0
    first_touch = _signal_kind(row) == "first_touch"
    reason = str(row.get("core_quality_gate_reason") or "")
    industry_expanding = (
        (_number(row.get("prior_industry_turnover_ratio_5d")) or 0.0)
        >= MINIMUM_INDUSTRY_TURNOVER_RATIO_5D
    )
    weak_stock_gene = (
        _number(row.get("stock_gene_combined_win_rate")) is not None
        and float(row["stock_gene_combined_win_rate"])
        < MAXIMUM_STOCK_GENE_COMBINED_WIN_RATE
    )
    prior_sealed = _integer(row.get("intraday_concept_prior_sealed_count")) or 0
    prior_max_board = _integer(row.get("intraday_concept_prior_max_board")) or 0
    early_diffusion = bool(
        row.get("concept_trigger_allowed") is True
        and row.get("intraday_concept_membership_causal") is True
        and MINIMUM_CONCEPT_PRIOR_SEALED_COUNT
        <= prior_sealed
        <= MAXIMUM_CONCEPT_PRIOR_SEALED_COUNT
        and prior_max_board >= MINIMUM_CONCEPT_PRIOR_MAX_BOARD
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
        industry_expanding
        and weak_stock_gene
        and (phase != "broad_rise" or pullback)
    ):
        components.append("static_industry_override")
    if early_diffusion and (
        (phase == "mixed" and first_touch)
        or (phase != "broad_rise" and pullback)
    ):
        components.append("concept_diffusion")
    return components


def _base_candidate_ready(row: Mapping[str, object]) -> bool:
    captured_at = _as_datetime(row.get("captured_at"))
    return bool(
        str(row.get("strategy_version") or "") == CORE_ABC_STRATEGY_VERSION
        and str(row.get("quality_status") or "") == "ready"
        and row.get("is_stale") is False
        and str(row.get("capture_state") or "") in ENTRY_STATES
        and str(row.get("board_lane") or "") in ELIGIBLE_LANES
        and captured_at is not None
        and scheduled_execution.is_entry_time(captured_at)
        and row.get("core_quality_gate_passed") is False
        and str(row.get("core_quality_gate_reason") or "") in RESCUABLE_REASONS
        and str(row.get("formal_action") or "") != "buy_now"
        and not _string_sequence(row.get("lane_blocker_codes"))
    )


def _concept_candidates(row: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = row.get("concept_candidates")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _concept_ids(row: Mapping[str, object]) -> set[str]:
    return {
        str(item.get("concept_id") or "")
        for item in _concept_candidates(row)
        if str(item.get("concept_id") or "")
    }


def _signal_kind(row: Mapping[str, object]) -> str:
    explicit = str(row.get("signal_kind") or "")
    if explicit:
        return explicit
    return "reseal" if str(row.get("capture_state") or "") == "resealed" else "first_touch"


def _acceptance_checks(
    baseline: Mapping[str, object],
    incremental: Mapping[str, object],
    combined: Mapping[str, object],
    *,
    added_days: int,
) -> list[dict[str, object]]:
    incremental_count = int(incremental.get("closed_count") or 0)
    incremental_win_rate = _number(incremental.get("win_rate_pct"))
    incremental_average = _number(incremental.get("average_return_pct"))
    combined_win_rate = _number(combined.get("win_rate_pct"))
    baseline_compound = _number(baseline.get("daily_equal_weight_compounded_pct"))
    combined_compound = _number(combined.get("daily_equal_weight_compounded_pct"))
    baseline_drawdown = _number(baseline.get("maximum_drawdown_pct"))
    combined_drawdown = _number(combined.get("maximum_drawdown_pct"))
    checks = (
        ("incremental_closed", incremental_count >= MINIMUM_INCREMENTAL_CLOSED_TRADES),
        (
            "incremental_win_rate",
            incremental_win_rate is not None
            and incremental_win_rate >= MINIMUM_INCREMENTAL_WIN_RATE_PCT,
        ),
        (
            "incremental_average_return",
            incremental_average is not None and incremental_average > 0,
        ),
        (
            "combined_win_rate",
            combined_win_rate is not None
            and combined_win_rate >= MINIMUM_INCREMENTAL_WIN_RATE_PCT,
        ),
        ("added_trade_days", added_days >= MINIMUM_ADDED_TRADE_DAYS),
        (
            "compound",
            baseline_compound is not None
            and combined_compound is not None
            and combined_compound > baseline_compound,
        ),
        (
            "maximum_drawdown",
            baseline_drawdown is not None
            and combined_drawdown is not None
            and combined_drawdown >= baseline_drawdown,
        ),
    )
    return [{"code": code, "passed": bool(passed)} for code, passed in checks]


def _performance_frame(rows: Sequence[Mapping[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame([dict(row) for row in rows])
    for field, default in (
        ("trade_date", None),
        ("signal_time", ""),
        ("pool_rank", 0),
        ("vt_symbol", ""),
        ("return_pct", None),
    ):
        if field not in frame:
            frame[field] = default
    return frame


def _trade_date_set(frame: pd.DataFrame) -> set[date]:
    if frame.empty:
        return set()
    return {
        parsed
        for value in frame["trade_date"]
        if (parsed := _as_date(value)) is not None
    }


def _string_sequence(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=scheduled_execution.SHANGHAI)
    return parsed.astimezone(scheduled_execution.SHANGHAI)


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None
