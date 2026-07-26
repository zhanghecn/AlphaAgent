"""Evaluate daily capital-mainline evidence against frozen formal candidates."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence, Set
from datetime import date
from math import ceil, floor, isfinite, sqrt
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.limit_up.capital_mainline_contract import (
    CapitalRole,
    ConceptCyclePhase,
    validate_asof_fields,
)
from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CapitalMainlineInputs,
    load_capital_mainline_inputs,
)
from alphaagent.server.services.limit_up.capital_mainline_research import (
    build_membership_contexts,
    build_research_bundle,
    select_primary_concept,
)
from alphaagent.server.services.limit_up import (
    cash_backtest,
    first_board_stock_gene_research,
    scheduled_execution,
)


STUDY_VERSION = "limit-up-capital-mainline-evaluation-v1"
TARGET_WIN_RATE_PCT = 70.0
MINIMUM_FORMAL_RETENTION = 0.80
ACTIVE_PHASES = {
    ConceptCyclePhase.IGNITION.value,
    ConceptCyclePhase.CONFIRMATION.value,
    ConceptCyclePhase.DIFFUSION.value,
    ConceptCyclePhase.ACCELERATION.value,
    ConceptCyclePhase.REFLUX.value,
}
RISK_PHASES = {
    ConceptCyclePhase.DIVERGENCE.value,
    ConceptCyclePhase.EBB.value,
}


def validate_candidate_feature_names(names: Sequence[str]) -> None:
    validate_asof_fields(names)


def extract_formal_candidates(
    days: Sequence[Mapping[str, object]],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    identities: set[tuple[object, ...]] = set()
    for day in days:
        trade_date = _as_date(day.get("trade_date"))
        pools = _mapping(_mapping(day.get("lane_portfolio")).get("candidate_pool"))
        for pool_name in ("first_board", "two_to_three", "high_board"):
            candidates = pools.get(pool_name)
            if not isinstance(candidates, Sequence) or isinstance(
                candidates, (str, bytes)
            ):
                continue
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                if (
                    str(candidate.get("decision") or "") != "eligible"
                    or _number(candidate.get("entry_price")) is None
                ):
                    continue
                signal_date = _as_date(candidate.get("signal_date")) or trade_date
                identity = (
                    signal_date,
                    str(candidate.get("vt_symbol") or "").upper(),
                    str(candidate.get("lane") or pool_name),
                    str(candidate.get("signal_time") or ""),
                    _integer(candidate.get("target_board")),
                )
                if signal_date is None or identity in identities:
                    continue
                identities.add(identity)
                outcome = _mapping(candidate.get("outcome"))
                financial_risk = _mapping(candidate.get("financial_risk"))
                records.append(
                    {
                        "trade_date": signal_date,
                        "vt_symbol": identity[1],
                        "name": str(candidate.get("name") or identity[1]),
                        "lane": str(candidate.get("lane") or pool_name),
                        "signal_time": str(candidate.get("signal_time") or "99:99:99"),
                        "pool_rank": _integer(candidate.get("pool_rank"), 1_000_000),
                        "target_board": _integer(candidate.get("target_board")),
                        "entry_price": _number(candidate.get("entry_price")),
                        "limit_price": _number(candidate.get("limit_price")),
                        "formal_score": _first_number(
                            candidate.get("rank_score"),
                            candidate.get("entry_quality_score"),
                            candidate.get("setup_confidence"),
                        ),
                        "prior_turnover_rate": _number(
                            candidate.get("prior_turnover_rate")
                        ),
                        "prior_market_phase_formal": str(
                            candidate.get("prior_market_phase") or "unavailable"
                        ),
                        "financial_risk_level": str(
                            financial_risk.get("level") or "unavailable"
                        ),
                        "financial_blocked": bool(financial_risk.get("blocked")),
                        "validation_phase": str(
                            candidate.get("validation_phase")
                            or day.get("validation_phase")
                            or "unknown"
                        ),
                        "outcome_sealed": bool(outcome.get("sealed")),
                        "return_pct": _number(
                            outcome.get("next_close_return_pct")
                        ),
                    }
                )
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "signal_time", "pool_rank", "vt_symbol"]
    ).reset_index(drop=True)


def extract_formal_recommendations(
    days: Sequence[Mapping[str, object]],
    *,
    start: date,
    end: date,
    available_exit_keys: Set[tuple[str, date]] | None = None,
    available_exit_prices: Mapping[tuple[str, date], float] | None = None,
    formal_settlement_returns: Mapping[tuple[str, date], float] | None = None,
) -> pd.DataFrame:
    """Extract full recommendations using the formal independent-slot outcome."""

    orders = scheduled_execution.extract_scheduled_orders(days)
    enriched = first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders(
        days,
        orders,
    )
    qualified, _ = scheduled_execution.filter_profitability_qualified_orders(enriched)
    records: list[dict[str, object]] = []
    for candidate in qualified:
        signal_date = _as_date(
            candidate.get("signal_date") or candidate.get("entry_date")
        )
        if signal_date is None or not start <= signal_date <= end:
            continue
        result_date = _as_date(candidate.get("result_date"))
        outcome = _mapping(candidate.get("outcome"))
        vt_symbol = str(candidate.get("vt_symbol") or "").upper()
        exit_bar_available = (
            available_exit_keys is None
            or (
                result_date is not None
                and (vt_symbol, result_date) in available_exit_keys
            )
        )
        official_exit_price = (
            available_exit_prices.get((vt_symbol, result_date))
            if available_exit_prices is not None and result_date is not None
            else None
        )
        standard_slot_return = _standard_slot_return(
            candidate,
            outcome,
            official_exit_price=official_exit_price,
        )
        if formal_settlement_returns is not None:
            standard_slot_return = formal_settlement_returns.get(
                (vt_symbol, signal_date)
            )
        return_pct = (
            standard_slot_return
            if result_date is not None
            and result_date <= end
            and exit_bar_available
            else None
        )
        financial_risk = _mapping(candidate.get("financial_risk"))
        records.append(
            {
                "trade_date": signal_date,
                "vt_symbol": vt_symbol,
                "name": str(candidate.get("name") or candidate.get("vt_symbol") or ""),
                "lane": str(candidate.get("lane") or ""),
                "signal_time": str(
                    candidate.get("signal_time")
                    or candidate.get("buy_time")
                    or "99:99:99"
                ),
                "pool_rank": _integer(candidate.get("pool_rank"), 1_000_000),
                "target_board": _integer(candidate.get("target_board")),
                "entry_price": _number(candidate.get("entry_price")),
                "limit_price": _number(candidate.get("limit_price")),
                "formal_score": _first_number(
                    candidate.get("rank_score"),
                    candidate.get("entry_quality_score"),
                    candidate.get("setup_confidence"),
                ),
                "prior_turnover_rate": _number(
                    candidate.get("prior_turnover_rate")
                ),
                "prior_market_phase_formal": str(
                    candidate.get("prior_market_phase") or "unavailable"
                ),
                "financial_risk_level": str(
                    financial_risk.get("level") or "unavailable"
                ),
                "financial_blocked": bool(financial_risk.get("blocked")),
                "validation_phase": str(
                    candidate.get("validation_phase") or "unknown"
                ),
                "outcome_sealed": bool(outcome.get("sealed")),
                "return_pct": return_pct,
                "candidate_scope": "formal_recommendations",
                "profitability_gate_version": candidate.get(
                    "profitability_gate_version"
                ),
            }
        )
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "signal_time", "pool_rank", "vt_symbol"]
    ).reset_index(drop=True)


def _standard_slot_return(
    candidate: Mapping[str, object],
    outcome: Mapping[str, object],
    *,
    official_exit_price: object = None,
) -> float | None:
    entry_price = _number(candidate.get("entry_price"))
    if entry_price is None or entry_price <= 0:
        return None
    limit_price = _number(candidate.get("limit_price"))
    exit_price = _first_number(
        official_exit_price,
        outcome.get("next_close_price"),
    )
    formal = cash_backtest.calculate_round_trip_outcome(
        entry_price,
        exit_price if exit_price is not None else entry_price,
        limit_price=limit_price,
    )
    if formal is None:
        return None
    if exit_price is None:
        return _number(outcome.get("next_close_return_pct"))
    return _number(formal.get("net_return_pct"))


def build_candidate_feature_frame(
    inputs: CapitalMainlineInputs,
    bundle: Mapping[str, pd.DataFrame],
    *,
    candidate_scope: str = "eligible_pool",
) -> pd.DataFrame:
    if candidate_scope == "eligible_pool":
        candidates = extract_formal_candidates(inputs.formal_candidate_days)
    elif candidate_scope == "formal_recommendations":
        candidates = extract_formal_recommendations(
            inputs.formal_candidate_days,
            start=_as_date(inputs.coverage.get("start")) or inputs.trade_dates[0],
            end=_as_date(inputs.coverage.get("end")) or inputs.trade_dates[-1],
            available_exit_keys=set(inputs.formal_exit_keys),
            available_exit_prices={
                (vt_symbol, trade_date): close_price
                for vt_symbol, trade_date, close_price in inputs.formal_exit_prices
            },
            formal_settlement_returns=(
                {
                    (vt_symbol, signal_date): return_pct
                    for vt_symbol, signal_date, return_pct in inputs.formal_settlement_returns
                }
                if inputs.formal_settlement_returns is not None
                else None
            ),
        )
    else:
        raise ValueError(f"unsupported candidate scope: {candidate_scope}")
    if candidates.empty:
        return candidates
    panel_by_date = _group_frame(bundle["concept_panel"], "trade_date")
    cycles_by_date = _group_frame(bundle["concept_cycles"], "trade_date")
    roles_by_identity = _roles_by_identity(bundle["roles"])
    events_by_identity = _events_by_identity(bundle["event_ledger"])
    market_by_date = _records_by_date(bundle["market_cycles"])
    contexts = build_membership_contexts(inputs)
    previous_date = {
        current: inputs.trade_dates[index - 1] if index else None
        for index, current in enumerate(inputs.trade_dates)
    }
    records = [
        _attach_candidate_features(
            candidate,
            previous_date=previous_date,
            contexts=contexts,
            panel_by_date=panel_by_date,
            cycles_by_date=cycles_by_date,
            roles_by_identity=roles_by_identity,
            events_by_identity=events_by_identity,
            market_by_date=market_by_date,
        )
        for candidate in candidates.to_dict("records")
    ]
    result = pd.DataFrame.from_records(records)
    validate_candidate_feature_names(
        [
            column
            for column in result.columns
            if column.startswith("prior_") or column.startswith("lag2_")
        ]
    )
    return result.sort_values(
        ["trade_date", "signal_time", "pool_rank", "vt_symbol"]
    ).reset_index(drop=True)


def _attach_candidate_features(
    candidate: Mapping[str, object],
    *,
    previous_date: Mapping[date, date | None],
    contexts: Mapping[date, Any],
    panel_by_date: Mapping[date, pd.DataFrame],
    cycles_by_date: Mapping[date, pd.DataFrame],
    roles_by_identity: Mapping[tuple[date, str], list[dict[str, object]]],
    events_by_identity: Mapping[tuple[date, str], Mapping[str, object]],
    market_by_date: Mapping[date, Mapping[str, object]],
) -> dict[str, object]:
    trade_date = candidate["trade_date"]
    symbol = str(candidate["vt_symbol"])
    prior_date = previous_date.get(trade_date)
    lag2_date = previous_date.get(prior_date) if prior_date is not None else None
    context = contexts.get(trade_date)
    sector_ids = tuple(context.by_symbol.get(symbol, ())) if context else ()
    prior = _concept_snapshot(
        prior_date,
        sector_ids,
        panel_by_date=panel_by_date,
        cycles_by_date=cycles_by_date,
    )
    lag2 = _concept_snapshot(
        lag2_date,
        sector_ids,
        panel_by_date=panel_by_date,
        cycles_by_date=cycles_by_date,
    )
    role_rows = roles_by_identity.get((prior_date, symbol), []) if prior_date else []
    roles_asof = sorted(
        {
            role
            for row in role_rows
            for role in _string_sequence(row.get("role_asof"))
        }
    )
    prior_event = events_by_identity.get((prior_date, symbol), {}) if prior_date else {}
    market = market_by_date.get(prior_date, {}) if prior_date else {}
    capital_state = str(prior.get("capital_state") or "unavailable")
    concept_phase = str(prior.get("concept_phase") or ConceptCyclePhase.WATCH.value)
    return {
        **dict(candidate),
        "prior_trade_date": prior_date,
        "prior_market_cycle_id": market.get("market_cycle_id"),
        "prior_market_phase": market.get("market_phase", "unavailable"),
        "prior_sector_id": prior.get("sector_id"),
        "prior_sector_name": prior.get("sector_name"),
        "prior_attribution": prior.get("attribution", "unavailable"),
        "prior_concept_count": len(sector_ids),
        "prior_concept_phase": concept_phase,
        "prior_concept_cycle_id": prior.get("concept_cycle_id"),
        "prior_index_strength": prior.get("index_strength"),
        "prior_ladder_strength": prior.get("ladder_strength"),
        "prior_turnover_strength": prior.get("turnover_strength"),
        "prior_mainline_score": prior.get("mainline_score"),
        "prior_mainline_percentile": prior.get("mainline_percentile"),
        "prior_flow_strength": prior.get("flow_strength"),
        "prior_capital_state": capital_state,
        "prior_member_count": prior.get("eligible_member_count"),
        "prior_membership_evidence_level": (
            context.evidence_level.value if context else "unavailable"
        ),
        "prior_roles_asof": roles_asof,
        "prior_board_pattern": prior_event.get("board_pattern"),
        "prior_active_concept": concept_phase in ACTIVE_PHASES,
        "prior_flow_confirmed": capital_state == "real_flow_confirmed",
        "prior_divergence_risk": (
            capital_state == "divergent" or concept_phase in RISK_PHASES
        ),
        "lag2_mainline_percentile": lag2.get("mainline_percentile"),
        "lag2_concept_phase": lag2.get("concept_phase"),
    }


def _concept_snapshot(
    trade_date: date | None,
    sector_ids: Sequence[str],
    *,
    panel_by_date: Mapping[date, pd.DataFrame],
    cycles_by_date: Mapping[date, pd.DataFrame],
) -> dict[str, object]:
    if trade_date is None or not sector_ids:
        return {}
    panel = panel_by_date.get(trade_date)
    if panel is None or panel.empty:
        return {}
    rows = panel.loc[panel["sector_id"].astype(str).isin(sector_ids)].copy()
    if rows.empty:
        return {}
    cycles = cycles_by_date.get(trade_date)
    cycle_fields: dict[str, dict[str, object]] = {}
    if cycles is not None and not cycles.empty:
        cycle_fields = {
            str(row["sector_id"]): row
            for row in cycles.to_dict("records")
            if str(row.get("sector_id") or "") in sector_ids
        }
    candidates: list[dict[str, object]] = []
    for row in rows.to_dict("records"):
        sector_id = str(row.get("sector_id") or "")
        candidates.append({**row, **cycle_fields.get(sector_id, {})})
    selected_sector = select_primary_concept(candidates)
    attribution = "primary"
    if selected_sector is None:
        selected = max(
            candidates,
            key=lambda row: _number(row.get("mainline_score")) or 0.0,
        )
        attribution = "multi_theme_unresolved"
    else:
        selected = next(
            row for row in candidates if str(row.get("sector_id")) == selected_sector
        )
    return {
        **selected,
        "concept_phase": selected.get("concept_phase", ConceptCyclePhase.WATCH.value),
        "attribution": attribution,
    }


def performance_summary(
    frame: pd.DataFrame,
    *,
    baseline_count: int | None = None,
) -> dict[str, object]:
    closed = frame.loc[pd.to_numeric(frame.get("return_pct"), errors="coerce").notna()].copy()
    returns = pd.to_numeric(closed.get("return_pct"), errors="coerce").astype(float)
    count = int(len(closed))
    wins = int(returns.gt(0).sum()) if count else 0
    compounded, maximum_drawdown = _daily_equity(closed)
    lower, upper = _wilson_interval(wins, count)
    return {
        "selection_count": int(len(frame)),
        "closed_count": count,
        "win_count": wins,
        "win_rate_pct": _percentage(wins, count),
        "win_rate_ci95_low_pct": lower,
        "win_rate_ci95_high_pct": upper,
        "average_return_pct": round(float(returns.mean()), 4) if count else None,
        "median_return_pct": round(float(returns.median()), 4) if count else None,
        "daily_equal_weight_compounded_pct": compounded,
        "maximum_drawdown_pct": maximum_drawdown,
        "hard_loss_rate_pct": _percentage(int(returns.le(-5.0).sum()), count),
        "maximum_consecutive_losses": _maximum_consecutive_losses(closed),
        "retention_pct": (
            round(count / baseline_count * 100.0, 4)
            if baseline_count
            else None
        ),
    }


def quality_ceiling(
    frame: pd.DataFrame,
    *,
    minimum_retention: float = MINIMUM_FORMAL_RETENTION,
    target_win_rate_pct: float = TARGET_WIN_RATE_PCT,
) -> dict[str, object]:
    returns = pd.to_numeric(frame.get("return_pct"), errors="coerce").dropna()
    closed_count = int(len(returns))
    win_count = int(returns.gt(0).sum())
    required_count = ceil(closed_count * minimum_retention)
    maximum_wins = min(win_count, required_count)
    maximum_rate = _percentage(maximum_wins, required_count)
    maximum_count_at_target = floor(
        win_count / (target_win_rate_pct / 100.0)
    ) if target_win_rate_pct > 0 else closed_count
    return {
        "closed_count": closed_count,
        "win_count": win_count,
        "minimum_retention_pct": round(minimum_retention * 100.0, 4),
        "required_closed_count": required_count,
        "maximum_possible_win_rate_pct": maximum_rate,
        "target_win_rate_pct": target_win_rate_pct,
        "maximum_closed_count_at_target": maximum_count_at_target,
        "maximum_retention_at_target_pct": _percentage(
            maximum_count_at_target,
            closed_count,
        ),
        "target_70_possible": bool(
            maximum_rate is not None and maximum_rate >= target_win_rate_pct
        ),
    }


def select_two_slot_account(
    frame: pd.DataFrame,
    *,
    trade_dates: Sequence[date],
    slot_count: int = 2,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    date_position = {value: index for index, value in enumerate(trade_dates)}
    occupied_until: list[int] = []
    selected_indexes: list[int] = []
    ordered = frame.sort_values(
        ["trade_date", "signal_time", "pool_rank", "lane", "vt_symbol"]
    )
    for trade_date, rows in ordered.groupby("trade_date", sort=True):
        position = date_position.get(_as_date(trade_date))
        if position is None:
            continue
        occupied_until = [release for release in occupied_until if release > position]
        available = max(slot_count - len(occupied_until), 0)
        for index in rows.index[:available]:
            selected_indexes.append(int(index))
            occupied_until.append(position + 2)
    return ordered.loc[selected_indexes].reset_index(drop=True)


def pre_registered_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    index_strength = _numeric_series(frame, "prior_index_strength")
    ladder_strength = _numeric_series(frame, "prior_ladder_strength")
    turnover_strength = _numeric_series(frame, "prior_turnover_strength")
    mainline_percentile = _numeric_series(frame, "prior_mainline_percentile")
    phase = _string_series(frame, "prior_concept_phase")
    capital = _string_series(frame, "prior_capital_state")
    roles = frame.get(
        "prior_roles_asof",
        pd.Series([[] for _ in range(len(frame))], index=frame.index),
    )
    board_pattern = _string_series(frame, "prior_board_pattern")
    non_divergent = ~_boolean_series(frame, "prior_divergence_risk")
    index_ladder = index_strength.ge(0.55) & ladder_strength.ge(0.55)
    return {
        "formal_baseline": pd.Series(True, index=frame.index),
        "prior_active_concept": phase.isin(ACTIVE_PHASES),
        "prior_ignition_or_confirmation": phase.isin(
            {
                ConceptCyclePhase.IGNITION.value,
                ConceptCyclePhase.CONFIRMATION.value,
            }
        ),
        "index_ladder_confirmed": index_ladder,
        "turnover_proxy_confirmed": index_ladder & turnover_strength.ge(0.60),
        "prior_mainline_top20": mainline_percentile.ge(0.80),
        "prior_mainline_top20_non_divergent": (
            mainline_percentile.ge(0.80) & non_divergent
        ),
        "leader_ladder_asof": roles.map(
            lambda values: bool(
                set(_string_sequence(values))
                & {
                    CapitalRole.IGNITION_CANDIDATE.value,
                    CapitalRole.LEADER_2.value,
                    CapitalRole.LEADER_3.value,
                    CapitalRole.CAPACITY_CORE.value,
                }
            )
        ),
        "prior_continuation_pattern": board_pattern.isin(
            {
                CapitalRole.CONTINUOUS_TWO_TO_THREE.value,
                CapitalRole.SHORT_CYCLE_REBOARD_THREE.value,
            }
        ),
        "real_fund_available": capital.isin(
            {"real_flow_confirmed", "real_flow_observed", "divergent"}
        ),
        "real_fund_confirmed": capital.eq("real_flow_confirmed"),
        "real_fund_divergent": capital.eq("divergent"),
        "cycle_divergence_or_ebb": phase.isin(RISK_PHASES),
        "fund_divergent_or_cycle_risk": ~non_divergent,
    }


def evaluate_slices(
    frame: pd.DataFrame,
    *,
    trade_dates: Sequence[date],
) -> dict[str, dict[str, object]]:
    baseline_count = int(pd.to_numeric(frame["return_pct"], errors="coerce").notna().sum())
    results: dict[str, dict[str, object]] = {}
    for name, mask in pre_registered_masks(frame).items():
        selected = frame.loc[mask.fillna(False)]
        account = select_two_slot_account(selected, trade_dates=trade_dates)
        results[name] = {
            "full": performance_summary(selected, baseline_count=baseline_count),
            "two_slot": performance_summary(account),
            "monthly": monthly_summaries(selected),
            "matched": matched_same_day_effect(frame, mask),
        }
    return results


def monthly_summaries(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if frame.empty:
        return {}
    months = frame["trade_date"].map(lambda value: str(value)[:7])
    return {
        month: performance_summary(frame.loc[months.eq(month)])
        for month in sorted(months.unique())
    }


def matched_same_day_effect(
    frame: pd.DataFrame,
    treatment_mask: pd.Series,
) -> dict[str, object]:
    treatment = frame.loc[treatment_mask.fillna(False)].copy()
    controls = frame.loc[~treatment_mask.fillna(False)].copy()
    pairs: list[tuple[float, float]] = []
    used_controls: set[int] = set()
    for index, row in treatment.iterrows():
        candidates = controls.loc[
            controls["trade_date"].eq(row["trade_date"])
            & controls["lane"].eq(row["lane"])
            & controls["financial_risk_level"].eq(row["financial_risk_level"])
        ].drop(index=list(used_controls), errors="ignore")
        if candidates.empty:
            continue
        distance = (
            (_numeric_series(candidates, "formal_score") - (_number(row.get("formal_score")) or 0.0)).abs()
            + (_numeric_series(candidates, "prior_turnover_rate") - (_number(row.get("prior_turnover_rate")) or 0.0)).abs()
        )
        control_index = int(distance.idxmin())
        treated_return = _number(row.get("return_pct"))
        control_return = _number(controls.at[control_index, "return_pct"])
        if treated_return is None or control_return is None:
            continue
        used_controls.add(control_index)
        pairs.append((treated_return, control_return))
    if not pairs:
        return {"pair_count": 0, "average_return_effect_pct": None, "win_rate_effect_pct": None}
    return {
        "pair_count": len(pairs),
        "average_return_effect_pct": round(mean(left - right for left, right in pairs), 4),
        "win_rate_effect_pct": round(
            mean(float(left > 0) - float(right > 0) for left, right in pairs) * 100.0,
            4,
        ),
    }


def search_pre_registered_rules(frame: pd.DataFrame) -> dict[str, object]:
    rules = _quality_rule_masks(frame)
    baseline_count = int(pd.to_numeric(frame["return_pct"], errors="coerce").notna().sum())
    train_mask = frame["trade_date"].le(date(2026, 5, 31))
    holdout_mask = frame["trade_date"].ge(date(2026, 6, 1))
    evaluated: list[dict[str, object]] = []
    for rule_name, mask in rules.items():
        selected = frame.loc[mask.fillna(False)]
        if len(selected) < 20:
            continue
        full = performance_summary(selected, baseline_count=baseline_count)
        train = performance_summary(selected.loc[selected.index.intersection(frame.index[train_mask])])
        holdout = performance_summary(selected.loc[selected.index.intersection(frame.index[holdout_mask])])
        months = monthly_summaries(selected)
        evaluated.append(
            {
                "rule": rule_name,
                "full": full,
                "train_mar_may": train,
                "holdout_jun_jul": holdout,
                "months_with_at_least_5": sum(
                    int(summary["closed_count"] or 0) >= 5
                    for summary in months.values()
                ),
                "minimum_month_win_rate_pct": min(
                    (
                        float(summary["win_rate_pct"])
                        for summary in months.values()
                        if int(summary["closed_count"] or 0) >= 5
                        and summary["win_rate_pct"] is not None
                    ),
                    default=None,
                ),
            }
        )
    robust_train = [
        row
        for row in evaluated
        if int(row["train_mar_may"]["closed_count"] or 0) >= 20
        and int(row["months_with_at_least_5"] or 0) >= 3
    ]
    robust_train.sort(
        key=lambda row: (
            _number(row["train_mar_may"]["win_rate_pct"]) or 0.0,
            _number(row["train_mar_may"]["average_return_pct"]) or -999.0,
            int(row["train_mar_may"]["closed_count"] or 0),
        ),
        reverse=True,
    )
    target_rows = [
        row
        for row in evaluated
        if (_number(row["full"]["win_rate_pct"]) or 0.0) >= TARGET_WIN_RATE_PCT
        and int(row["full"]["closed_count"] or 0) >= 30
        and int(row["months_with_at_least_5"] or 0) >= 3
    ]
    target_rows.sort(
        key=lambda row: (
            int(row["full"]["closed_count"] or 0),
            _number(row["full"]["average_return_pct"]) or -999.0,
        ),
        reverse=True,
    )
    retained_rows = [
        row
        for row in evaluated
        if (_number(row["full"]["retention_pct"]) or 0.0)
        >= MINIMUM_FORMAL_RETENTION * 100.0
    ]
    retained_rows.sort(
        key=lambda row: (
            _number(row["full"]["win_rate_pct"]) or 0.0,
            _number(row["full"]["average_return_pct"]) or -999.0,
        ),
        reverse=True,
    )
    return {
        "rule_count": len(evaluated),
        "selected_by_train": robust_train[0] if robust_train else None,
        "target_70_candidates": target_rows[:10],
        "best_at_80pct_retention": retained_rows[0] if retained_rows else None,
    }


def _quality_rule_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    features = {
        "mainline": _numeric_series(frame, "prior_mainline_percentile"),
        "index": _numeric_series(frame, "prior_index_strength"),
        "ladder": _numeric_series(frame, "prior_ladder_strength"),
        "turnover": _numeric_series(frame, "prior_turnover_strength"),
    }
    non_divergent = ~_boolean_series(frame, "prior_divergence_risk")
    active = _boolean_series(frame, "prior_active_concept")
    rules: dict[str, pd.Series] = {}
    for threshold in (0.50, 0.60, 0.70, 0.80, 0.90):
        for name, values in features.items():
            rules[f"{name}>={threshold:.2f}"] = values.ge(threshold)
        rules[f"mainline>={threshold:.2f}+non_divergent"] = (
            features["mainline"].ge(threshold) & non_divergent
        )
        rules[f"mainline>={threshold:.2f}+active"] = (
            features["mainline"].ge(threshold) & active
        )
        rules[f"index+ladder>={threshold:.2f}"] = (
            features["index"].ge(threshold) & features["ladder"].ge(threshold)
        )
        rules[f"index+ladder+turnover>={threshold:.2f}"] = (
            features["index"].ge(threshold)
            & features["ladder"].ge(threshold)
            & features["turnover"].ge(threshold)
        )
    return rules


def negative_control_summaries(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    baseline_count = int(pd.to_numeric(frame["return_pct"], errors="coerce").notna().sum())
    rng = np.random.default_rng(20260725)
    shuffled = _numeric_series(frame, "prior_mainline_percentile").to_numpy(copy=True)
    rng.shuffle(shuffled)
    random_mask = pd.Series(shuffled, index=frame.index).ge(0.80)
    lag2_mask = _numeric_series(frame, "lag2_mainline_percentile").ge(0.80)
    member_count = _numeric_series(frame, "prior_member_count")
    broad_cutoff = member_count.quantile(0.80) if member_count.notna().any() else np.nan
    broad_mask = member_count.ge(broad_cutoff) if np.isfinite(broad_cutoff) else pd.Series(False, index=frame.index)
    return {
        "randomized_concept_assignment": performance_summary(
            frame.loc[random_mask], baseline_count=baseline_count
        ),
        "concept_state_shifted_one_extra_day": performance_summary(
            frame.loc[lag2_mask], baseline_count=baseline_count
        ),
        "largest_member_count_only": performance_summary(
            frame.loc[broad_mask], baseline_count=baseline_count
        ),
    }


def render_fund_ablation_report(
    inputs: CapitalMainlineInputs,
    frame: pd.DataFrame,
) -> str:
    results = evaluate_slices(frame, trade_dates=inputs.trade_dates)
    lines = _report_header(
        "日级资金主线消融",
        inputs,
        frame,
    )
    lines.extend(
        [
            "## Three evidence tracks",
            "",
            "| 轨道 | 全量闭合 | 保留率 | 胜率 | 均值 | 复利 | 回撤 | 硬亏 | 同日匹配对数/收益效应/胜率效应 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    tracks = {
        "A index+ladder": "index_ladder_confirmed",
        "B turnover proxy": "turnover_proxy_confirmed",
        "C0 real fund available": "real_fund_available",
        "C1 real fund confirmed": "real_fund_confirmed",
        "C2 real fund divergent": "real_fund_divergent",
        "Cycle divergence/ebb": "cycle_divergence_or_ebb",
    }
    for label, key in tracks.items():
        result = results[key]
        summary = result["full"]
        matched = result["matched"]
        lines.append(
            f"| {label} | {_fmt(summary['closed_count'])} | {_fmt(summary['retention_pct'])}% | "
            f"{_fmt(summary['win_rate_pct'])}% | {_fmt(summary['average_return_pct'])}% | "
            f"{_fmt(summary['daily_equal_weight_compounded_pct'])}% | {_fmt(summary['maximum_drawdown_pct'])}% | "
            f"{_fmt(summary['hard_loss_rate_pct'])}% | {matched['pair_count']}/{_fmt(matched['average_return_effect_pct'])}%/{_fmt(matched['win_rate_effect_pct'])}% |"
        )
    flow_available = frame["prior_capital_state"].isin(
        {"real_flow_confirmed", "real_flow_observed", "divergent"}
    )
    lines.extend(
        [
            "",
            "## Coverage and conclusion",
            "",
            f"- D-1 真实板块资金可用候选：`{int(flow_available.sum())}/{len(frame)}`；其余日期不把缺失资金填成流出。",
            "- A/B 覆盖 3-7 月；C 只评价 6 月中旬以后通过 `known_at` 门的候选，不能与 A/B 的全区间样本直接比较绝对胜率。",
            "- `real_fund_confirmed` 若没有同时改善同日匹配收益和风险，结论即为资金本身没有稳定增量，而不是继续调权重。",
            "",
        ]
    )
    return "\n".join(lines)


def render_candidate_counterfactual_report(
    inputs: CapitalMainlineInputs,
    frame: pd.DataFrame,
) -> str:
    results = evaluate_slices(frame, trade_dates=inputs.trade_dates)
    baseline = results["formal_baseline"]["full"]
    two_slot = results["formal_baseline"]["two_slot"]
    ceiling = quality_ceiling(frame)
    search = search_pre_registered_rules(frame)
    negatives = negative_control_summaries(frame)
    selected = search["selected_by_train"]
    retained = search["best_at_80pct_retention"]
    target_rows = search["target_70_candidates"]
    lines = _report_header(
        "正式候选资金主线反事实",
        inputs,
        frame,
    )
    lines.extend(
        [
            "## Frozen baseline",
            "",
            f"- 3-7 月正式全量：`{baseline['win_count']}/{baseline['closed_count']}`，胜率 `{_fmt(baseline['win_rate_pct'])}%`，均值 `{_fmt(baseline['average_return_pct'])}%`。",
            f"- 同一母池两仓 T+1 到达顺序账户：`{two_slot['win_count']}/{two_slot['closed_count']}`，胜率 `{_fmt(two_slot['win_rate_pct'])}%`。",
            "- 旧口头 `70.1031%` 来自旧两仓成交子集 `68/97`；同批全量只有 `102/164=62.1951%`，不能把两仓跳过的后排票当成规则自动过滤。",
            "",
            "## Pre-registered slices",
            "",
            "| 切片 | 闭合 | 保留率 | 胜率 | 均值 | 复利 | 回撤 | 硬亏 | 最大连亏 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for key in (
        "formal_baseline",
        "prior_active_concept",
        "prior_ignition_or_confirmation",
        "prior_mainline_top20",
        "prior_mainline_top20_non_divergent",
        "leader_ladder_asof",
        "prior_continuation_pattern",
        "real_fund_confirmed",
        "fund_divergent_or_cycle_risk",
    ):
        summary = results[key]["full"]
        lines.append(
            f"| {key} | {summary['closed_count']} | {_fmt(summary['retention_pct'])}% | "
            f"{_fmt(summary['win_rate_pct'])}% | {_fmt(summary['average_return_pct'])}% | "
            f"{_fmt(summary['daily_equal_weight_compounded_pct'])}% | {_fmt(summary['maximum_drawdown_pct'])}% | "
            f"{_fmt(summary['hard_loss_rate_pct'])}% | {summary['maximum_consecutive_losses']} |"
        )
    lines.extend(
        [
            "",
            "## Can 70% be restored without shrinking the pool",
            "",
            f"- 80% 保留门要求至少 `{ceiling['required_closed_count']}` 笔；当前母池全部赢家只有 `{ceiling['win_count']}` 笔。",
            f"- 即使事后完美删除亏损，80% 保留下数学最高胜率也只有 `{_fmt(ceiling['maximum_possible_win_rate_pct'])}%`；达到 70%：`{'可能' if ceiling['target_70_possible'] else '不可能'}`。",
            f"- 即使事后完美保留全部赢家，要达到 70% 最多也只能留下 `{ceiling['maximum_closed_count_at_target']}` 笔，保留率上限 `{_fmt(ceiling['maximum_retention_at_target_pct'])}%`。",
            f"- 预注册规则数：`{search['rule_count']}`。",
        ]
    )
    if retained:
        lines.append(
            f"- 80% 保留门内最好规则：`{retained['rule']}`，`{retained['full']['closed_count']}` 笔，胜率 `{_fmt(retained['full']['win_rate_pct'])}%`，均值 `{_fmt(retained['full']['average_return_pct'])}%`。"
        )
    else:
        lines.append("- 没有预注册规则达到 80% 保留门。")
    if selected:
        lines.append(
            f"- 仅按 3-5 月训练选择的规则：`{selected['rule']}`；全样本 `{selected['full']['closed_count']}` 笔/{_fmt(selected['full']['win_rate_pct'])}%/保留 {_fmt(selected['full']['retention_pct'])}%，训练 `{selected['train_mar_may']['closed_count']}` 笔/{_fmt(selected['train_mar_may']['win_rate_pct'])}%，6-7 月留出 `{selected['holdout_jun_jul']['closed_count']}` 笔/{_fmt(selected['holdout_jun_jul']['win_rate_pct'])}%。"
        )
    lines.append(
        f"- 满足至少 30 笔、至少 3 个月且全样本胜率 >=70% 的诊断规则：`{len(target_rows)}` 个。"
    )
    for row in target_rows[:5]:
        lines.append(
            f"  - `{row['rule']}`：{row['full']['closed_count']} 笔，保留 {_fmt(row['full']['retention_pct'])}%，胜率 {_fmt(row['full']['win_rate_pct'])}%，6-7 月 {_fmt(row['holdout_jun_jul']['win_rate_pct'])}%。"
        )
    lines.extend(
        [
            "",
            "## Negative controls",
            "",
            "| 负对照 | 闭合 | 胜率 | 均值 |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, summary in negatives.items():
        lines.append(
            f"| {name} | {summary['closed_count']} | {_fmt(summary['win_rate_pct'])}% | {_fmt(summary['average_return_pct'])}% |"
        )
    lines.extend(
        [
            "",
            "- `final_role/final_highest_board/D+1 return` 由未来字段守卫拒绝，不能作为质量规则。",
            "- 3-6 月概念成员是当前成员幸存者代理；本报告只能否定不稳健规则，不能据此批准生产接入。",
            "",
        ]
    )
    return "\n".join(lines)


def _report_header(
    title: str,
    inputs: CapitalMainlineInputs,
    frame: pd.DataFrame,
) -> list[str]:
    return [
        f"# AlphaAgent {title}",
        "",
        "## Current state",
        "",
        f"- 研究版本：`{STUDY_VERSION}`。",
        f"- 区间：`{inputs.coverage.get('start')}..{inputs.coverage.get('end')}`；正式候选 `{len(frame)}` 笔。",
        "- 母池固定为 `limit-up-history-v15` 的 `decision=eligible`、有涨停价入场且 D+1 收盘已闭合候选。",
        "- 首板 D 日只连接 D-1 概念状态；D 日收盘周期、最终龙头和 D+1 结果不进入特征。",
        "",
    ]


def _daily_equity(frame: pd.DataFrame) -> tuple[float | None, float | None]:
    if frame.empty:
        return None, None
    returns = pd.to_numeric(frame["return_pct"], errors="coerce")
    daily = returns.groupby(frame["trade_date"]).mean().sort_index()
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    for value in daily:
        equity *= 1.0 + max(float(value), -99.0) / 100.0
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, (equity / peak - 1.0) * 100.0)
    return round((equity - 1.0) * 100.0, 4), round(maximum_drawdown, 4)


def _maximum_consecutive_losses(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    ordered = frame.sort_values(
        ["trade_date", "signal_time", "pool_rank", "vt_symbol"]
    )
    longest = 0
    current = 0
    for value in pd.to_numeric(ordered["return_pct"], errors="coerce"):
        current = current + 1 if value <= 0 else 0
        longest = max(longest, current)
    return longest


def _wilson_interval(wins: int, count: int) -> tuple[float | None, float | None]:
    if count <= 0:
        return None, None
    z = 1.959963984540054
    ratio = wins / count
    denominator = 1.0 + z * z / count
    center = (ratio + z * z / (2.0 * count)) / denominator
    margin = z * sqrt(
        ratio * (1.0 - ratio) / count + z * z / (4.0 * count * count)
    ) / denominator
    return round((center - margin) * 100.0, 4), round((center + margin) * 100.0, 4)


def _group_frame(frame: pd.DataFrame, field: str) -> dict[date, pd.DataFrame]:
    if frame.empty:
        return {}
    return {
        _as_date(key): values
        for key, values in frame.groupby(field, sort=False)
        if _as_date(key) is not None
    }


def _records_by_date(frame: pd.DataFrame) -> dict[date, dict[str, object]]:
    if frame.empty:
        return {}
    return {
        parsed: row
        for row in frame.to_dict("records")
        if (parsed := _as_date(row.get("trade_date"))) is not None
    }


def _roles_by_identity(
    frame: pd.DataFrame,
) -> dict[tuple[date, str], list[dict[str, object]]]:
    result: dict[tuple[date, str], list[dict[str, object]]] = {}
    if frame.empty:
        return result
    for identity, values in frame.groupby(["trade_date", "vt_symbol"], sort=False):
        trade_date = _as_date(identity[0])
        if trade_date is not None:
            result[(trade_date, str(identity[1]))] = values.to_dict("records")
    return result


def _events_by_identity(
    frame: pd.DataFrame,
) -> dict[tuple[date, str], dict[str, object]]:
    result: dict[tuple[date, str], dict[str, object]] = {}
    if frame.empty:
        return result
    for row in frame.to_dict("records"):
        trade_date = _as_date(row.get("trade_date"))
        if trade_date is not None:
            result[(trade_date, str(row.get("vt_symbol") or ""))] = row
    return result


def _numeric_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return pd.to_numeric(
        frame.get(field, pd.Series(np.nan, index=frame.index)), errors="coerce"
    )


def _string_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return frame.get(field, pd.Series("", index=frame.index)).fillna("").astype(str)


def _boolean_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return frame.get(field, pd.Series(False, index=frame.index)).fillna(False).astype(bool)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(str(item) for item in value)
    return ()


def _first_number(*values: object) -> float | None:
    return next((number for value in values if (number := _number(value)) is not None), None)


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _integer(value: object, default: int = 0) -> int:
    number = _number(value)
    return int(number) if number is not None else default


def _as_date(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 4) if denominator else None


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--study",
        choices=("fund-ablation", "candidate-counterfactual"),
        required=True,
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    inputs = load_capital_mainline_inputs(arguments.start, arguments.end)
    bundle = build_research_bundle(inputs, start=arguments.start, end=arguments.end)
    frame = build_candidate_feature_frame(inputs, bundle)
    if arguments.study == "fund-ablation":
        report = render_fund_ablation_report(inputs, frame)
    else:
        report = render_candidate_counterfactual_report(inputs, frame)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
