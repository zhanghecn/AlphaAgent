"""Research leader-to-follower mappings without leaking realized outcomes."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import date
from hashlib import sha256
from math import isfinite
from pathlib import Path

import pandas as pd

from alphaagent.server.services.limit_up.capital_mainline_contract import (
    CapitalRole,
    validate_asof_fields,
)
from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    build_candidate_feature_frame,
    monthly_summaries,
    performance_summary,
)
from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CapitalMainlineInputs,
    load_capital_mainline_inputs,
)
from alphaagent.server.services.limit_up.capital_mainline_research import (
    build_dynamic_concept_panel,
    build_event_ledger,
    build_membership_contexts,
    build_research_bundle,
    discover_concept_cycles,
    discover_market_cycles,
)


STUDY_VERSION = "limit-up-leader-follower-factor-v1"
FROZEN_FACTOR_NAME = "concept_turnover_capacity_ge_080_v1"
FROZEN_DISCOVERY_SHA256 = (
    "3b62d4cda6eaa1d8589b05f76ee92354c5cf3f6d82ec83823f96adab79609e52"
)
FROZEN_TURNOVER_THRESHOLD = 0.80
DISCOVERY_START = date(2026, 3, 1)
DISCOVERY_END = date(2026, 7, 24)
VALIDATION_START = date(2023, 3, 28)
FORWARD_START = date(2026, 7, 27)
MINIMUM_FORWARD_TRADE_DAYS = 60
MINIMUM_FORWARD_CLOSED_CANDIDATES = 30
MINIMUM_FORWARD_MARKET_CYCLES = 2
FOLLOWER_ROLES = (
    CapitalRole.LEADER_2.value,
    CapitalRole.LEADER_3.value,
)


def validate_leader_follower_feature_names(names: Sequence[str]) -> None:
    validate_asof_fields(names)


def build_leader_confirmation_events(
    bundle: Mapping[str, pd.DataFrame],
    trade_dates: Sequence[date],
) -> pd.DataFrame:
    event_links = bundle.get("event_links", pd.DataFrame())
    event_ledger = bundle.get("event_ledger", pd.DataFrame())
    cycles = bundle.get("concept_cycles", pd.DataFrame())
    if event_links.empty or event_ledger.empty or cycles.empty:
        return pd.DataFrame()

    ordered_dates = tuple(sorted({_as_date(value) for value in trade_dates if _as_date(value)}))
    next_date = {
        value: ordered_dates[index + 1]
        for index, value in enumerate(ordered_dates[:-1])
    }
    event_lookup = {
        (_as_date(row.get("trade_date")), str(row.get("vt_symbol") or "")): row
        for row in event_ledger.to_dict("records")
    }
    cycle_lookup = {
        (_as_date(row.get("trade_date")), str(row.get("concept_cycle_id") or "")): row
        for row in cycles.to_dict("records")
    }
    cycle_by_sector = {
        (_as_date(row.get("trade_date")), str(row.get("sector_id") or "")): row
        for row in cycles.to_dict("records")
    }
    confirmed_rows: list[dict[str, object]] = []
    for role in event_links.to_dict("records"):
        if (
            not bool(role.get("is_limit_up"))
            or int(_number(role.get("limit_up_streak")) or 0) != 1
        ):
            continue
        ignition_date = _as_date(role.get("trade_date"))
        confirmation_date = next_date.get(ignition_date)
        ignition_cycle = cycle_by_sector.get(
            (ignition_date, str(role.get("sector_id") or "")), {}
        )
        if str(ignition_cycle.get("concept_phase") or "") != "ignition_candidate":
            continue
        cycle_id = str(ignition_cycle.get("concept_cycle_id") or "")
        leader_symbol = str(role.get("vt_symbol") or "")
        if not ignition_date or not confirmation_date:
            continue
        confirmation_event = event_lookup.get((confirmation_date, leader_symbol), {})
        if (
            not bool(confirmation_event.get("is_limit_up"))
            or int(_number(confirmation_event.get("limit_up_streak")) or 0) < 2
        ):
            continue
        confirmation_cycle = cycle_by_sector.get(
            (confirmation_date, str(role.get("sector_id") or "")), {}
        )
        if str(confirmation_cycle.get("concept_cycle_id") or "") != cycle_id:
            continue
        confirmed_rows.append(
            {
                **role,
                "market_cycle_id": ignition_cycle.get("market_cycle_id"),
                "concept_cycle_id": cycle_id,
                "role_order": 1,
                "confirmation_date": confirmation_date,
            }
        )
    if not confirmed_rows:
        return pd.DataFrame()

    records: list[dict[str, object]] = []
    confirmed = pd.DataFrame.from_records(confirmed_rows)
    for (ignition_date, cycle_id), group in confirmed.groupby(
        ["trade_date", "concept_cycle_id"], sort=False
    ):
        ordered = group.assign(
            _turnover=pd.to_numeric(group.get("turnover"), errors="coerce").fillna(0.0)
        ).sort_values(["_turnover", "vt_symbol"], ascending=[False, True])
        role = ordered.iloc[0].to_dict()
        ignition_date = _as_date(ignition_date)
        confirmation_date = _as_date(role.get("confirmation_date"))
        first_usable_date = next_date.get(confirmation_date)
        if not ignition_date or not confirmation_date or not first_usable_date:
            continue
        cycle_id = str(cycle_id)
        ignition_cycle = cycle_lookup.get((ignition_date, cycle_id), {})
        confirmation_cycle = cycle_lookup.get((confirmation_date, cycle_id), {})
        if not ignition_cycle or not confirmation_cycle:
            continue
        leader_symbols = tuple(ordered["vt_symbol"].astype(str))
        leader_names = tuple(ordered["name"].fillna(ordered["vt_symbol"]).astype(str))
        leader_symbol = leader_symbols[0]
        confirmation_events = [
            event_lookup.get((confirmation_date, symbol), {})
            for symbol in leader_symbols
        ]
        records.append(
            {
                "leader_event_id": f"{cycle_id}:{ignition_date}",
                "market_cycle_id": role.get("market_cycle_id"),
                "concept_cycle_id": cycle_id,
                "sector_id": str(role.get("sector_id") or ""),
                "sector_name": str(role.get("sector_name") or ""),
                "leader_symbol": leader_symbol,
                "leader_name": str(role.get("name") or leader_symbol),
                "leader_symbols": leader_symbols,
                "leader_names": leader_names,
                "co_leader_count": len(leader_symbols),
                "ignition_date": ignition_date,
                "confirmation_date": confirmation_date,
                "first_usable_date": first_usable_date,
                "leader_board_height": max(
                    int(_number(event.get("limit_up_streak")) or 0)
                    for event in confirmation_events
                ),
                "ignition_index_strength": _number(
                    ignition_cycle.get("index_strength")
                ),
                "confirmation_index_strength": _number(
                    confirmation_cycle.get("index_strength")
                ),
                "index_strength_delta": _difference(
                    confirmation_cycle.get("index_strength"),
                    ignition_cycle.get("index_strength"),
                ),
                "ignition_turnover_strength": _number(
                    ignition_cycle.get("turnover_strength")
                ),
                "confirmation_turnover_strength": _number(
                    confirmation_cycle.get("turnover_strength")
                ),
                "turnover_strength_delta": _difference(
                    confirmation_cycle.get("turnover_strength"),
                    ignition_cycle.get("turnover_strength"),
                ),
                "ignition_ladder_strength": _number(
                    ignition_cycle.get("ladder_strength")
                ),
                "confirmation_ladder_strength": _number(
                    confirmation_cycle.get("ladder_strength")
                ),
                "ladder_strength_delta": _difference(
                    confirmation_cycle.get("ladder_strength"),
                    ignition_cycle.get("ladder_strength"),
                ),
                "ignition_unique_follower_ratio": _number(
                    ignition_cycle.get("unique_follower_ratio")
                ),
                "confirmation_unique_follower_ratio": _number(
                    confirmation_cycle.get("unique_follower_ratio")
                ),
                "unique_follower_delta": _difference(
                    confirmation_cycle.get("unique_follower_ratio"),
                    ignition_cycle.get("unique_follower_ratio"),
                ),
                "confirmation_phase": str(
                    confirmation_cycle.get("concept_phase") or "unavailable"
                ),
                "confirmation_capital_state": str(
                    confirmation_cycle.get("capital_state") or "unavailable"
                ),
                "membership_evidence_level": str(
                    confirmation_cycle.get("membership_evidence_level")
                    or role.get("membership_evidence_level")
                    or "unavailable"
                ),
            }
        )
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values(
        ["confirmation_date", "concept_cycle_id", "leader_symbol"]
    ).reset_index(drop=True)


def build_lightweight_research_bundle(
    inputs: CapitalMainlineInputs,
    *,
    start: date,
    end: date,
) -> dict[str, pd.DataFrame]:
    contexts = build_membership_contexts(inputs)
    event_ledger = build_event_ledger(inputs)
    concept_panel, event_links = build_dynamic_concept_panel(
        inputs,
        event_ledger=event_ledger,
        membership_contexts=contexts,
        start=start,
        end=end,
    )
    market_cycles = discover_market_cycles(inputs)
    concept_cycles = discover_concept_cycles(concept_panel, market_cycles)
    return {
        "concept_panel": concept_panel,
        "market_cycles": market_cycles,
        "concept_cycles": concept_cycles,
        "event_ledger": event_ledger,
        "event_links": event_links,
        "roles": pd.DataFrame(),
    }


def build_realized_follower_mappings(
    inputs: CapitalMainlineInputs,
    bundle: Mapping[str, pd.DataFrame],
    leader_events: pd.DataFrame,
    *,
    maximum_delay_sessions: int = 3,
) -> pd.DataFrame:
    roles = bundle.get("roles", pd.DataFrame())
    if leader_events.empty or roles.empty:
        return pd.DataFrame()
    trade_dates = tuple(sorted({_as_date(value) for value in inputs.trade_dates if _as_date(value)}))
    positions = {value: index for index, value in enumerate(trade_dates)}
    bars = pd.DataFrame.from_records(inputs.stock_bars)
    if not bars.empty:
        bars["trade_date"] = bars["trade_date"].map(_as_date)
        bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bar_lookup = {
        (_as_date(row.get("trade_date")), str(row.get("vt_symbol") or "")): row
        for row in bars.to_dict("records")
    }
    records: list[dict[str, object]] = []
    for leader in leader_events.to_dict("records"):
        confirmation_date = _as_date(leader.get("confirmation_date"))
        confirmation_position = positions.get(confirmation_date)
        if confirmation_position is None:
            continue
        allowed_dates = set(
            trade_dates[
                confirmation_position : confirmation_position
                + maximum_delay_sessions
                + 1
            ]
        )
        leader_symbols = set(_strings(leader.get("leader_symbols"))) or {
            str(leader.get("leader_symbol") or "")
        }
        same_cycle = roles.loc[
            roles["concept_cycle_id"].astype(str).eq(
                str(leader.get("concept_cycle_id") or "")
            )
            & roles["trade_date"].map(_as_date).isin(allowed_dates)
            & ~roles["vt_symbol"].astype(str).isin(leader_symbols)
        ].copy()
        if same_cycle.empty:
            continue
        same_cycle["mapped_role"] = same_cycle["role_asof"].map(
            _mapped_follower_role
        )
        same_cycle = same_cycle.loc[same_cycle["mapped_role"].notna()].sort_values(
            ["trade_date", "role_order", "vt_symbol"]
        )
        for follower_symbol, rows in same_cycle.groupby("vt_symbol", sort=False):
            row = rows.iloc[0].to_dict()
            follower_date = _as_date(row.get("trade_date"))
            follower_position = positions.get(follower_date)
            if follower_position is None:
                continue
            response_bar = bar_lookup.get((follower_date, str(follower_symbol)), {})
            response_close = _number(response_bar.get("close_price"))
            confirmation_bar = bar_lookup.get(
                (confirmation_date, str(follower_symbol)), {}
            )
            records.append(
                {
                    **dict(leader),
                    "follower_symbol": str(follower_symbol),
                    "follower_name": str(row.get("name") or follower_symbol),
                    "mapped_role": row.get("mapped_role"),
                    "follower_first_date": follower_date,
                    "delay_sessions": follower_position - confirmation_position,
                    "follower_board_height": int(
                        _number(row.get("limit_up_streak")) or 0
                    ),
                    "response_day_change_pct": _number(
                        response_bar.get("change_pct")
                    ),
                    "confirmation_to_response_pct": _close_return(
                        _number(confirmation_bar.get("close_price")),
                        response_close,
                    ),
                    "forward_1d_close_return_pct": _forward_close_return(
                        str(follower_symbol),
                        follower_position,
                        1,
                        trade_dates,
                        bar_lookup,
                        response_close,
                    ),
                    "forward_3d_close_return_pct": _forward_close_return(
                        str(follower_symbol),
                        follower_position,
                        3,
                        trade_dates,
                        bar_lookup,
                        response_close,
                    ),
                    "forward_5d_close_return_pct": _forward_close_return(
                        str(follower_symbol),
                        follower_position,
                        5,
                        trade_dates,
                        bar_lookup,
                        response_close,
                    ),
                }
            )
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values(
        ["confirmation_date", "concept_cycle_id", "delay_sessions", "mapped_role", "follower_symbol"]
    ).reset_index(drop=True)


def attach_leader_follower_features(
    candidate_frame: pd.DataFrame,
    leader_events: pd.DataFrame,
    *,
    leader_event_coverage_start: date | None = None,
    observed_event_coverage_start: date | None = None,
) -> pd.DataFrame:
    if candidate_frame.empty:
        return candidate_frame.copy()
    events = leader_events.to_dict("records") if not leader_events.empty else []
    records: list[dict[str, object]] = []
    for candidate in candidate_frame.to_dict("records"):
        trade_date = _as_date(candidate.get("trade_date"))
        prior_trade_date = _as_date(candidate.get("prior_trade_date"))
        cycle_id = str(candidate.get("prior_concept_cycle_id") or "")
        sector_id = str(candidate.get("prior_sector_id") or "")
        coverage_available = bool(
            prior_trade_date
            and (
                leader_event_coverage_start is None
                or prior_trade_date >= leader_event_coverage_start
            )
        )
        if not coverage_available:
            event_evidence_level = "unavailable"
        elif (
            observed_event_coverage_start is not None
            and prior_trade_date >= observed_event_coverage_start
        ):
            event_evidence_level = "observed_limit_pool"
        elif leader_event_coverage_start is not None:
            event_evidence_level = "daily_close_reconstructed_proxy"
        else:
            event_evidence_level = "coverage_assumed_available"
        matched = [
            event
            for event in events
            if _as_date(event.get("first_usable_date")) is not None
            and _as_date(event.get("first_usable_date")) <= trade_date
            and (
                (cycle_id and str(event.get("concept_cycle_id") or "") == cycle_id)
                or (
                    not cycle_id
                    and sector_id
                    and str(event.get("sector_id") or "") == sector_id
                )
            )
        ]
        matched.sort(
            key=lambda event: (
                _as_date(event.get("confirmation_date")) or date.min,
                str(event.get("leader_symbol") or ""),
            ),
            reverse=True,
        )
        latest = matched[0] if matched else {}
        follower_role = _mapped_follower_role(candidate.get("prior_roles_asof"))
        confirmation_date = _as_date(latest.get("confirmation_date"))
        records.append(
            {
                **candidate,
                "prior_leader_event_coverage_available": coverage_available,
                "prior_leader_event_evidence_level": event_evidence_level,
                "prior_has_confirmed_leader": bool(latest),
                "prior_confirmed_leader_count": len(matched),
                "prior_leader_symbol": latest.get("leader_symbol"),
                "prior_leader_name": latest.get("leader_name"),
                "prior_leader_confirmation_date": confirmation_date,
                "prior_leader_age_days": (
                    (trade_date - confirmation_date).days
                    if trade_date and confirmation_date
                    else None
                ),
                "prior_leader_board_height": latest.get("leader_board_height"),
                "prior_leader_index_strength": latest.get(
                    "confirmation_index_strength"
                ),
                "prior_leader_index_strength_delta": latest.get(
                    "index_strength_delta"
                ),
                "prior_leader_turnover_strength": latest.get(
                    "confirmation_turnover_strength"
                ),
                "prior_leader_turnover_strength_delta": latest.get(
                    "turnover_strength_delta"
                ),
                "prior_leader_ladder_strength": latest.get(
                    "confirmation_ladder_strength"
                ),
                "prior_leader_ladder_strength_delta": latest.get(
                    "ladder_strength_delta"
                ),
                "prior_leader_unique_follower_delta": latest.get(
                    "unique_follower_delta"
                ),
                "prior_leader_phase": latest.get("confirmation_phase"),
                "prior_leader_capital_state": latest.get(
                    "confirmation_capital_state"
                ),
                "prior_leader_non_divergent": bool(latest)
                and str(latest.get("confirmation_phase") or "")
                not in {"divergence", "ebb"}
                and str(latest.get("confirmation_capital_state") or "")
                != "divergent",
                "prior_follower_role": follower_role,
                "prior_follower_role_rank": (
                    2
                    if follower_role == CapitalRole.LEADER_2.value
                    else 3
                    if follower_role == CapitalRole.LEADER_3.value
                    else None
                ),
                "prior_leader_membership_evidence_level": latest.get(
                    "membership_evidence_level"
                ),
            }
        )
    result = pd.DataFrame.from_records(records)
    validate_leader_follower_feature_names(
        [column for column in result if column.startswith("prior_leader")]
    )
    return result.sort_values(
        ["trade_date", "signal_time", "pool_rank", "vt_symbol"]
    ).reset_index(drop=True)


def evaluate_leader_follower_factors(
    frame: pd.DataFrame,
) -> dict[str, dict[str, object]]:
    masks = leader_follower_factor_masks(frame)
    baseline_count = int(
        pd.to_numeric(frame.get("return_pct"), errors="coerce").notna().sum()
    )
    trade_dates = pd.to_datetime(frame["trade_date"])
    discovery = trade_dates.dt.date <= date(2026, 5, 31)
    holdout = trade_dates.dt.date >= date(2026, 6, 1)
    results: dict[str, dict[str, object]] = {}
    for name, mask in masks.items():
        selected = frame.loc[mask.fillna(False)]
        results[name] = {
            "full": performance_summary(selected, baseline_count=baseline_count),
            "discovery_mar_may": performance_summary(
                selected.loc[selected.index.intersection(frame.index[discovery])]
            ),
            "holdout_jun_jul": performance_summary(
                selected.loc[selected.index.intersection(frame.index[holdout])]
            ),
            "monthly": monthly_summaries(selected),
        }
    return results


def frozen_early_turnover_mask(frame: pd.DataFrame) -> pd.Series:
    coverage = frame.get(
        "prior_leader_event_coverage_available",
        pd.Series(True, index=frame.index, dtype=bool),
    ).fillna(False).astype(bool)
    return (
        coverage
        & _numeric_series(frame, "prior_turnover_strength").ge(
            FROZEN_TURNOVER_THRESHOLD
        )
        & ~_boolean_series(frame, "prior_has_confirmed_leader")
    )


def frozen_turnover_capacity_mask(frame: pd.DataFrame) -> pd.Series:
    return _numeric_series(frame, "prior_turnover_strength").ge(
        FROZEN_TURNOVER_THRESHOLD
    )


def leader_follower_factor_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    confirmed = _boolean_series(frame, "prior_has_confirmed_leader")
    index_strength = _numeric_series(frame, "prior_leader_index_strength")
    index_delta = _numeric_series(frame, "prior_leader_index_strength_delta")
    turnover = _numeric_series(frame, "prior_leader_turnover_strength")
    ladder = _numeric_series(frame, "prior_leader_ladder_strength")
    ladder_delta = _numeric_series(frame, "prior_leader_ladder_strength_delta")
    non_divergent = _boolean_series(frame, "prior_leader_non_divergent")
    follower = _string_series(frame, "prior_follower_role").isin(FOLLOWER_ROLES)
    capacity = frame.get(
        "prior_roles_asof",
        pd.Series([[] for _ in range(len(frame))], index=frame.index),
    ).map(lambda values: CapitalRole.CAPACITY_CORE.value in set(_strings(values)))
    current_turnover = _numeric_series(frame, "prior_turnover_strength")
    index_response = index_strength.ge(0.80) & index_delta.ge(0.0)
    turnover_response = turnover.ge(0.80)
    diffusion_response = ladder.ge(0.60) & ladder_delta.ge(0.0)
    phase = _string_series(frame, "prior_leader_phase")
    masks = {
        "formal_baseline": pd.Series(True, index=frame.index),
        "confirmed_leader": confirmed,
        "confirmed_leader_index_response": confirmed & index_response,
        "confirmed_leader_turnover_response": confirmed & turnover_response,
        "confirmed_leader_diffusion_response": confirmed & diffusion_response,
        "confirmed_leader_non_divergent": confirmed & non_divergent,
        "confirmed_leader_mapped_leader_2_3": confirmed & follower,
        "confirmed_leader_capacity_core": confirmed & capacity,
        "confirmed_leader_index_turnover": (
            confirmed & index_response & turnover_response
        ),
        "confirmed_leader_turnover_follower": (
            confirmed & turnover_response & follower
        ),
        "turnover_ge_080": current_turnover.ge(0.80),
        "turnover_ge_080_with_confirmed_leader": (
            current_turnover.ge(0.80) & confirmed
        ),
        "turnover_ge_080_with_confirmed_follower": (
            current_turnover.ge(0.80) & confirmed & follower
        ),
        "discovery_early_turnover_ge_080": (
            frozen_early_turnover_mask(frame)
        ),
        "confirmed_leader_divergent": confirmed & ~non_divergent,
        "confirmed_leader_without_mapped_follower": confirmed & ~follower,
        "confirmed_leader_active_phase": confirmed
        & phase.isin(
            {
                "confirmation",
                "diffusion",
                "acceleration",
                "reflux",
            }
        ),
    }
    for threshold in (0.60, 0.70, 0.80, 0.90):
        suffix = f"{int(threshold * 100):02d}"
        masks[f"confirmed_index_ge_{suffix}"] = (
            confirmed & index_strength.ge(threshold)
        )
        masks[f"confirmed_index_delta_nonnegative_ge_{suffix}"] = (
            confirmed & index_strength.ge(threshold) & index_delta.ge(0.0)
        )
        masks[f"confirmed_turnover_ge_{suffix}"] = (
            confirmed & turnover.ge(threshold)
        )
        masks[f"confirmed_ladder_ge_{suffix}"] = (
            confirmed & ladder.ge(threshold)
        )
        masks[f"confirmed_ladder_delta_nonnegative_ge_{suffix}"] = (
            confirmed & ladder.ge(threshold) & ladder_delta.ge(0.0)
        )
        masks[f"confirmed_index_turnover_ge_{suffix}"] = (
            confirmed
            & index_strength.ge(threshold)
            & index_delta.ge(0.0)
            & turnover.ge(threshold)
        )
        masks[f"confirmed_turnover_follower_ge_{suffix}"] = (
            confirmed & turnover.ge(threshold) & follower
        )
        masks[f"current_turnover_follower_ge_{suffix}"] = (
            current_turnover.ge(threshold) & confirmed & follower
        )
        if threshold != 0.80:
            masks[f"discovery_current_turnover_without_confirmed_ge_{suffix}"] = (
                current_turnover.ge(threshold) & ~confirmed
            )
    return masks


def discovery_report_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def validate_frozen_discovery_report(path: Path) -> str:
    digest = discovery_report_sha256(path)
    if digest != FROZEN_DISCOVERY_SHA256:
        raise ValueError(
            "frozen discovery report SHA256 mismatch: "
            f"expected {FROZEN_DISCOVERY_SHA256}, got {digest}"
        )
    return digest


def evaluate_frozen_validation(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        raise ValueError("frozen validation requires formal candidate rows")
    dates = pd.to_datetime(frame["trade_date"]).dt.date
    frozen_mask = frozen_turnover_capacity_mask(frame)
    independent_mask = dates < DISCOVERY_START
    discovery_mask = dates.between(DISCOVERY_START, DISCOVERY_END)

    full = _validation_cohort(frame, frozen_mask)
    independent = _validation_cohort(frame.loc[independent_mask], frozen_mask.loc[independent_mask])
    discovery = _validation_cohort(frame.loc[discovery_mask], frozen_mask.loc[discovery_mask])
    time_blocks: dict[str, dict[str, object]] = {}
    expanding: dict[str, dict[str, object]] = {}
    for block_id, block_start, block_end in _validation_time_blocks():
        block_mask = dates.between(block_start, block_end)
        time_blocks[block_id] = {
            "start": block_start.isoformat(),
            "end": block_end.isoformat(),
            **_validation_cohort(
                frame.loc[block_mask],
                frozen_mask.loc[block_mask],
            ),
        }
        if block_end < DISCOVERY_START:
            cumulative_mask = dates.between(VALIDATION_START, block_end)
            expanding[block_id] = {
                "start": VALIDATION_START.isoformat(),
                "end": block_end.isoformat(),
                **_validation_cohort(
                    frame.loc[cumulative_mask],
                    frozen_mask.loc[cumulative_mask],
                ),
            }

    evidence: dict[str, dict[str, object]] = {}
    evidence_values = _string_series(
        frame,
        "prior_leader_event_evidence_level",
    ).replace("", "unavailable")
    for level in sorted(evidence_values.unique()):
        evidence_mask = evidence_values.eq(level)
        evidence[str(level)] = _validation_cohort(
            frame.loc[evidence_mask], frozen_mask.loc[evidence_mask]
        )

    selected = frame.loc[frozen_mask]
    independent_frozen = independent["frozen"]
    closed_count = int(independent_frozen["closed_count"])
    win_rate = _number(independent_frozen.get("win_rate_pct"))
    average_return = _number(independent_frozen.get("average_return_pct"))
    covered_months = len(
        {
            str(value)[:7]
            for value in frame.loc[independent_mask & frozen_mask, "trade_date"]
        }
    )
    failures = []
    if closed_count < 30:
        failures.append("independent_closed_candidates<30")
    if win_rate is None or win_rate < 60.0:
        failures.append("independent_win_rate<60pct")
    if average_return is None or average_return <= 0.0:
        failures.append("independent_average_return<=0")
    if covered_months < 3:
        failures.append("independent_covered_months<3")
    proxy_passed = not failures
    return {
        "contract": {
            "factor_name": FROZEN_FACTOR_NAME,
            "turnover_threshold": FROZEN_TURNOVER_THRESHOLD,
            "requires_no_confirmed_leader": False,
            "discovery_start": DISCOVERY_START.isoformat(),
            "discovery_end": DISCOVERY_END.isoformat(),
            "validation_start": VALIDATION_START.isoformat(),
            "policy": "frozen_rule_rejection_only_no_refit",
        },
        "full_806": full,
        "independent_pre_discovery": independent,
        "discovery_reference": discovery,
        "time_blocks": time_blocks,
        "expanding": expanding,
        "evidence": evidence,
        "monthly": monthly_summaries(selected),
        "qualification": {
            "historical_proxy_gate_passed": proxy_passed,
            "decision": (
                "historical_proxy_passed_forward_required"
                if proxy_passed
                else "historical_proxy_rejected"
            ),
            "failures": failures,
            "independent_covered_months": covered_months,
            "production_approved": False,
        },
    }


def render_frozen_validation_report(
    inputs: CapitalMainlineInputs,
    leader_events: pd.DataFrame,
    candidate_frame: pd.DataFrame,
    *,
    discovery_digest: str,
) -> str:
    result = evaluate_frozen_validation(candidate_frame)
    coverage = inputs.coverage
    event_coverage = coverage.get("event_coverage") or {}
    qualification = result["qualification"]
    lines = [
        "# AlphaAgent 龙头跟随冻结因子 806 日历史验证",
        "",
        "## Current state",
        "",
        f"- 冻结因子：`{FROZEN_FACTOR_NAME}`，规则固定为 `prior_turnover_strength >= {FROZEN_TURNOVER_THRESHOLD:.2f}`。",
        f"- 发现报告 SHA256：`{discovery_digest}`；验证策略：`frozen_rule_rejection_only_no_refit`。",
        f"- 区间：`{coverage.get('start')}..{coverage.get('end')}`；交易日 `{len(inputs.trade_dates)}`；正式确认龙事件 `{len(leader_events)}`。",
        f"- 正式涨停池原始事件从 `{event_coverage.get('observed_event_start') or '-'}` 开始；此前用日线收盘重建 `{event_coverage.get('reconstructed_event_count') or 0}` 条主板封板代理。",
        "- 3-7 月是已查看发现样本；最终历史判断只读取 2026-03-01 之前的独立区间。",
        "- 历史概念成员仍是当前成员幸存者代理，因此即使数值过门也不能批准生产。",
        "",
        "## Frozen result",
        "",
        "| 区间 | 母池闭合 | 因子闭合 | 保留率 | 胜率 | 均值 | 复利 | 最大回撤 | 硬亏率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("完整806日（含发现期）", "full_806"),
        ("独立历史（发现期前）", "independent_pre_discovery"),
        ("3-7月发现期复核", "discovery_reference"),
    ):
        cohort = result[key]
        lines.append(_validation_report_row(label, cohort))
    lines.extend(
        [
            "",
            "## Chronological blocks",
            "",
            "| 时间块 | 区间 | 母池闭合 | 因子闭合 | 胜率 | 均值 | 最大回撤 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for block_id, cohort in result["time_blocks"].items():
        baseline = cohort["baseline"]
        frozen = cohort["frozen"]
        lines.append(
            f"| {block_id} | {cohort['start']}..{cohort['end']} | {baseline['closed_count']} | {frozen['closed_count']} | {_fmt(frozen['win_rate_pct'])}% | {_signed(frozen['average_return_pct'])} | {_signed(frozen['maximum_drawdown_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## Expanding audit",
            "",
            "固定规则没有训练或调参；下表只展示独立历史随时间扩展后的累计稳定性。",
            "",
            "| 截止时间块 | 因子闭合 | 胜率 | 均值 | 复利 | 最大回撤 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for block_id, cohort in result["expanding"].items():
        frozen = cohort["frozen"]
        lines.append(
            f"| {block_id} | {frozen['closed_count']} | {_fmt(frozen['win_rate_pct'])}% | {_signed(frozen['average_return_pct'])} | {_signed(frozen['daily_equal_weight_compounded_pct'])} | {_signed(frozen['maximum_drawdown_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## Evidence cohorts",
            "",
            "| 龙头事件证据 | 母池闭合 | 因子闭合 | 胜率 | 均值 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for level, cohort in result["evidence"].items():
        lines.append(
            f"| {level} | {cohort['baseline']['closed_count']} | {cohort['frozen']['closed_count']} | {_fmt(cohort['frozen']['win_rate_pct'])}% | {_signed(cohort['frozen']['average_return_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## Qualification",
            "",
            f"- 历史代理门：`{'passed' if qualification['historical_proxy_gate_passed'] else 'failed'}`；决定：`{qualification['decision']}`。",
            f"- 独立历史覆盖月份：`{qualification['independent_covered_months']}`；失败项：`{', '.join(qualification['failures']) or '无'}`。",
            "- `production_approved=False`：806 日中早期涨停事件为日线重建、概念成员为幸存者代理，且自然前向尚未完成。",
            "- 本报告不得反向修改阈值、增加条件或删除亏损样本；如未过门，冻结因子直接否决。",
            "",
        ]
    )
    return "\n".join(lines)


def render_frozen_forward_report(
    validation: Mapping[str, object],
    *,
    discovery_digest: str,
) -> str:
    qualification = validation.get("qualification") or {}
    return "\n".join(
        [
            "# AlphaAgent 龙头跟随冻结因子自然前向账本",
            "",
            "## Current state",
            "",
            f"- 因子：`{FROZEN_FACTOR_NAME}`；发现报告 SHA256：`{discovery_digest}`。",
            f"- 冻结规则：`prior_turnover_strength >= {FROZEN_TURNOVER_THRESHOLD:.2f}`。",
            f"- 最早未见交易日：`{FORWARD_START}`；状态：`not_started_waiting_for_unseen_sessions`。",
            f"- 历史代理决定：`{qualification.get('decision') or 'unavailable'}`；历史结果不能写入前向特征。",
            "",
            "## Qualification contract",
            "",
            f"- 至少 `{MINIMUM_FORWARD_TRADE_DAYS}` 个新交易日。",
            f"- 至少 `{MINIMUM_FORWARD_CLOSED_CANDIDATES}` 笔闭合全量正式候选。",
            f"- 至少 `{MINIMUM_FORWARD_MARKET_CYCLES}` 个市场情绪周期。",
            "- 全量胜率 `>=60%`，平均收益为正，且风险不相对母池恶化。",
            "- 只使用当时保存的完整概念成员、概念成交额和真实涨停事件；缺失失败关闭。",
            "",
            "## Ledger",
            "",
            "| 交易日 | 候选 | 概念 | 成交额强度 | 已确认龙 | D+1收益 | 证据状态 |",
            "|---|---|---|---:|---|---:|---|",
            "| - | 尚无未见样本 | - | - | - | - | awaiting_forward_data |",
            "",
            "## Boundary",
            "",
            "- 只有自然前向与历史代理均过门，才允许另写生产接入计划；本账本不修改正式策略、页面或下单。",
            "",
        ]
    )


def _validation_cohort(
    frame: pd.DataFrame,
    frozen_mask: pd.Series,
) -> dict[str, dict[str, object]]:
    baseline_count = int(
        pd.to_numeric(frame.get("return_pct"), errors="coerce").notna().sum()
    )
    return {
        "baseline": performance_summary(frame),
        "frozen": performance_summary(
            frame.loc[frozen_mask.fillna(False)],
            baseline_count=baseline_count,
        ),
    }


def _validation_time_blocks() -> tuple[tuple[str, date, date], ...]:
    return (
        ("2023_partial", VALIDATION_START, date(2023, 12, 31)),
        ("2024", date(2024, 1, 1), date(2024, 12, 31)),
        ("2025", date(2025, 1, 1), date(2025, 12, 31)),
        ("2026_pre_discovery", date(2026, 1, 1), date(2026, 2, 28)),
        ("2026_discovery", DISCOVERY_START, DISCOVERY_END),
    )


def _validation_report_row(label: str, cohort: Mapping[str, object]) -> str:
    baseline = cohort["baseline"]
    frozen = cohort["frozen"]
    return (
        f"| {label} | {baseline['closed_count']} | {frozen['closed_count']} | "
        f"{_fmt(frozen['retention_pct'])}% | {_fmt(frozen['win_rate_pct'])}% | "
        f"{_signed(frozen['average_return_pct'])} | "
        f"{_signed(frozen['daily_equal_weight_compounded_pct'])} | "
        f"{_signed(frozen['maximum_drawdown_pct'])} | "
        f"{_fmt(frozen['hard_loss_rate_pct'])}% |"
    )


def render_leader_follower_report(
    inputs: CapitalMainlineInputs,
    leader_events: pd.DataFrame,
    mappings: pd.DataFrame,
    candidate_frame: pd.DataFrame,
) -> str:
    results = evaluate_leader_follower_factors(candidate_frame)
    baseline = results["formal_baseline"]["full"]
    primary_mappings = _primary_mapping_edges(mappings)
    lines = [
        "# AlphaAgent 2026 年 3-7 月龙头到龙二龙三映射因子发现",
        "",
        "## Current state",
        "",
        f"- 研究版本：`{STUDY_VERSION}`。",
        f"- 区间：`{inputs.coverage.get('start')}..{inputs.coverage.get('end')}`；交易日 `{len(inputs.trade_dates)}`。",
        f"- 确认龙事件：`{len(leader_events)}`；同概念原始映射边：`{len(mappings)}`；按点时证据选主概念后唯一映射：`{len(primary_mappings)}`。",
        f"- 正式全量信号：`{len(candidate_frame)}` 笔；正式独立账户可闭合 `{baseline['closed_count']}` 笔，胜率 `{_fmt(baseline['win_rate_pct'])}%`。",
        "- 龙头在一进二确认日收盘后才成立，最早从下一交易日进入正式候选特征。",
        "- 事后龙二龙三涨幅只用于发现规律，不进入候选点时特征。",
        "- 3-6 月成员为当前成员幸存者代理；严格点时成员结果单列证据等级。",
        "",
        "## Factor inventory",
        "",
        "| 因子族 | 点时字段 | 研究问题 |",
        "|---|---|---|",
        "| 龙头确认 | prior_has_confirmed_leader / board_height / age | 首板一进二后是否形成可延续的引导龙 |",
        "| 概念指数 | index_strength / index_strength_delta | 龙头确认时同概念指数是否同步增强 |",
        "| 资金承载 | turnover_strength / turnover_strength_delta | 概念成交额是否相对 20 日基线扩张 |",
        "| 梯队扩散 | ladder_strength / ladder_strength_delta / unique_follower_delta | 排除龙头后是否出现独立扩散 |",
        "| 跟随角色 | prior_follower_role / capacity_core | 候选是否已经成为龙二、龙三或容量核心 |",
        "| 周期风险 | phase / capital_state / non_divergent | 确认后是否仍处扩散而非分歧退潮 |",
        "| 组合映射 | confirmed + index/turnover/ladder/follower | 哪些共同成立时全量打板质量提高 |",
        "",
        "## Realized leader-to-follower mapping",
        "",
        "下表是事后标签，用于回答哪个确认龙映射了同概念龙二龙三及其后续涨幅。",
        "",
        "| 确认日 | 龙头 | 概念 | 指数增量 | 成交额增量 | 梯队增量 | 龙二龙三及首次响应后 1/3/5 日涨幅 | 证据 |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    mappings_by_event = (
        {
            str(event_id): rows
            for event_id, rows in mappings.groupby("leader_event_id", sort=False)
        }
        if not mappings.empty
        else {}
    )
    for event in leader_events.to_dict("records"):
        event_mappings = mappings_by_event.get(
            str(event.get("leader_event_id") or ""), pd.DataFrame()
        )
        followers = "、".join(
            f"{row.follower_name}({row.mapped_role}, 延迟{int(row.delay_sessions)}日, "
            f"{_signed(row.forward_1d_close_return_pct)}/{_signed(row.forward_3d_close_return_pct)}/{_signed(row.forward_5d_close_return_pct)})"
            for row in event_mappings.itertuples()
        ) or "无龙二龙三映射"
        leader_label = "、".join(_strings(event.get("leader_names"))) or str(
            event.get("leader_name") or "-"
        )
        lines.append(
            f"| {event.get('confirmation_date')} | {leader_label} | {event.get('sector_name')} | "
            f"{_fmt(event.get('index_strength_delta'))} | {_fmt(event.get('turnover_strength_delta'))} | "
            f"{_fmt(event.get('ladder_strength_delta'))} | {followers} | {event.get('membership_evidence_level')} |"
        )

    lines.extend(
        [
            "",
            "## Mapping return summary",
            "",
            "同一龙头与跟随股同时属于多个概念时，只保留确认时指数/成交额/梯队证据最强的主概念边，避免重复计算同一涨幅。",
            "",
            "| 分组 | 映射数 | 响应日平均涨幅 | 后1日平均 | 后3日平均 | 后5日平均 | 后1日上涨率 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    if not primary_mappings.empty:
        grouping = _mapping_cohorts(primary_mappings)
        for label, rows in grouping:
            lines.append(
                f"| {label} | {len(rows)} | {_mean(rows, 'response_day_change_pct')}% | "
                f"{_mean(rows, 'forward_1d_close_return_pct')}% | {_mean(rows, 'forward_3d_close_return_pct')}% | "
                f"{_mean(rows, 'forward_5d_close_return_pct')}% | {_positive_rate(rows, 'forward_1d_close_return_pct')}% |"
            )

    lines.extend(
        [
            "",
            "## Strongest realized leader mappings",
            "",
            "此表按事后映射表现描述哪些龙头带出了跟随者，不能直接作为历史买点。",
            "",
            "| 确认日 | 龙头 | 概念 | 唯一映射 | 后1日均值 | 后1日上涨率 | 后3日均值 |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in _strongest_mapping_events(primary_mappings)[:30]:
        lines.append(
            f"| {row['confirmation_date']} | {row['leader_name']} | {row['sector_name']} | "
            f"{row['mapping_count']} | {_fmt(row['forward_1d_mean'])}% | "
            f"{_fmt(row['forward_1d_win_rate'])}% | {_fmt(row['forward_3d_mean'])}% |"
        )

    lines.extend(
        [
            "",
            "## Formal candidate factor ablation",
            "",
            "所有数字均为规则保留后的全量正式推荐，不读取两仓结果。",
            "",
            "| 因子 | 闭合 | 保留率 | 全期胜率 | 均值 | 复利 | 回撤 | 硬亏 | 连亏 | 3-5月笔数/胜率 | 6-7月笔数/胜率 | 月份>=5笔 | 状态 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|",
        ]
    )
    eligible: list[str] = []
    for name, result in results.items():
        full = result["full"]
        discovery = result["discovery_mar_may"]
        holdout = result["holdout_jun_jul"]
        months = result["monthly"]
        months_with_five = sum(
            int(summary.get("closed_count") or 0) >= 5
            for summary in months.values()
        )
        status = _factor_status(full, discovery, holdout, months_with_five)
        if status == "candidate_for_806d_validation":
            eligible.append(name)
        lines.append(
            f"| {name} | {full['closed_count']} | {_fmt(full['retention_pct'])}% | "
            f"{_fmt(full['win_rate_pct'])}% | {_fmt(full['average_return_pct'])}% | "
            f"{_fmt(full['daily_equal_weight_compounded_pct'])}% | {_fmt(full['maximum_drawdown_pct'])}% | "
            f"{_fmt(full['hard_loss_rate_pct'])}% | {full['maximum_consecutive_losses']} | "
            f"{discovery['closed_count']}/{_fmt(discovery['win_rate_pct'])}% | "
            f"{holdout['closed_count']}/{_fmt(holdout['win_rate_pct'])}% | {months_with_five} | {status} |"
        )

    early_turnover = results["discovery_early_turnover_ge_080"]["full"]
    confirmed_turnover = results[
        "turnover_ge_080_with_confirmed_leader"
    ]["full"]
    confirmed_all = results["confirmed_leader"]["full"]
    confirmed_divergent = results["confirmed_leader_divergent"]["full"]
    mapping_cohorts = dict(_mapping_cohorts(primary_mappings))
    non_divergent_mappings = mapping_cohorts.get(
        "confirmed_non_divergent", pd.DataFrame()
    )
    divergent_mappings = mapping_cohorts.get(
        "confirmed_divergent", pd.DataFrame()
    )
    point_in_time_mappings = mapping_cohorts.get("point_in_time", pd.DataFrame())
    lines.extend(
        [
            "",
            "## Discovery conclusion",
            "",
            f"- 龙头身份不是正向因子：确认龙存在组 `{confirmed_all['closed_count']}` 笔、胜率 `{_fmt(confirmed_all['win_rate_pct'])}%`；确认龙已经分歧组 `{confirmed_divergent['closed_count']}` 笔、仅 `{_fmt(confirmed_divergent['win_rate_pct'])}%`。",
            f"- 资金承载存在明显阶段差：概念成交额强度 `>=0.80` 且确认龙尚未出现为 `{early_turnover['closed_count']}` 笔、胜率 `{_fmt(early_turnover['win_rate_pct'])}%`；确认龙已经出现后为 `{confirmed_turnover['closed_count']}` 笔、胜率 `{_fmt(confirmed_turnover['win_rate_pct'])}%`。",
            f"- 事后唯一龙二龙三映射的后1日上涨率：非分歧 `{_positive_rate(non_divergent_mappings, 'forward_1d_close_return_pct')}%`，分歧 `{_positive_rate(divergent_mappings, 'forward_1d_close_return_pct')}%`；映射更适合识别退潮风险，尚未形成 `>=60%` 的正向打板门。",
            f"- 严格点时成员映射只有 `{len(point_in_time_mappings)}` 条，后1日上涨率 `{_positive_rate(point_in_time_mappings, 'forward_1d_close_return_pct')}%`，且七月后段存在右删失，不能据此批准生产使用。",
            f"- 达到全期 `>=60%`、至少 30 笔、至少 3 个有效月份且 6-7 月不低于 60% 的待验证因子：`{len(eligible)}` 个。",
            *(
                [f"- `{name}`" for name in eligible]
                if eligible
                else ["- 当前没有因子满足进入完整 806 日验证的最低发现门。"]
            ),
            "- `candidate_for_806d_validation` 不是策略通过，只表示定义可以冻结后进入下一阶段。",
            f"- 主验证仅冻结 `{FROZEN_FACTOR_NAME}`：`prior_turnover_strength >= {FROZEN_TURNOVER_THRESHOLD:.2f}`；它对应预注册的 `turnover_ge_080`。无确认龙的 0.60/0.70 阈值保留为探索结果，不替代主验证。",
            "- 任何仅因事后龙二龙三涨幅成立、但在点时正式候选中没有增量的规律，不进入 806 日质量规则。",
            "",
        ]
    )
    return "\n".join(lines)


def _factor_status(
    full: Mapping[str, object],
    discovery: Mapping[str, object],
    holdout: Mapping[str, object],
    months_with_five: int,
) -> str:
    count = int(_number(full.get("closed_count")) or 0)
    full_rate = _number(full.get("win_rate_pct"))
    holdout_count = int(_number(holdout.get("closed_count")) or 0)
    holdout_rate = _number(holdout.get("win_rate_pct"))
    if count < 30 or months_with_five < 3:
        return "small_sample"
    if (
        full_rate is not None
        and full_rate >= 60.0
        and holdout_count >= 10
        and holdout_rate is not None
        and holdout_rate >= 60.0
    ):
        return "candidate_for_806d_validation"
    discovery_rate = _number(discovery.get("win_rate_pct"))
    if (
        discovery_rate is not None
        and holdout_rate is not None
        and (discovery_rate - 50.0) * (holdout_rate - 50.0) < 0
    ):
        return "time_split_reversal"
    return "below_60_or_unstable"


def _primary_mapping_edges(mappings: pd.DataFrame) -> pd.DataFrame:
    if mappings.empty:
        return mappings.copy()
    ranked = mappings.copy()
    ranked["_concept_evidence_score"] = (
        pd.to_numeric(
            ranked.get("confirmation_index_strength"), errors="coerce"
        ).fillna(0.0)
        + pd.to_numeric(
            ranked.get("confirmation_turnover_strength"), errors="coerce"
        ).fillna(0.0)
        + pd.to_numeric(
            ranked.get("confirmation_ladder_strength"), errors="coerce"
        ).fillna(0.0)
    )
    ranked = ranked.sort_values(
        [
            "confirmation_date",
            "leader_symbol",
            "follower_symbol",
            "follower_first_date",
            "_concept_evidence_score",
            "concept_cycle_id",
        ],
        ascending=[True, True, True, True, False, True],
    )
    return ranked.drop_duplicates(
        [
            "confirmation_date",
            "leader_symbol",
            "follower_symbol",
            "follower_first_date",
        ],
        keep="first",
    ).drop(columns="_concept_evidence_score").reset_index(drop=True)


def _mapping_cohorts(
    mappings: pd.DataFrame,
) -> list[tuple[str, pd.DataFrame]]:
    index_delta = _numeric_series(mappings, "index_strength_delta")
    turnover_delta = _numeric_series(mappings, "turnover_strength_delta")
    ladder_delta = _numeric_series(mappings, "ladder_strength_delta")
    phase = _string_series(mappings, "confirmation_phase")
    capital = _string_series(mappings, "confirmation_capital_state")
    cohorts: list[tuple[str, pd.DataFrame]] = [("all_unique_mappings", mappings)]
    for role, rows in mappings.groupby("mapped_role", sort=True):
        cohorts.append((str(role), rows))
    for delay, rows in mappings.groupby("delay_sessions", sort=True):
        cohorts.append((f"delay_{int(delay)}_sessions", rows))
    masks = {
        "index_delta_nonnegative": index_delta.ge(0.0),
        "index_delta_negative": index_delta.lt(0.0),
        "turnover_delta_nonnegative": turnover_delta.ge(0.0),
        "turnover_delta_negative": turnover_delta.lt(0.0),
        "ladder_delta_nonnegative": ladder_delta.ge(0.0),
        "ladder_delta_negative": ladder_delta.lt(0.0),
        "index_turnover_ladder_aligned": (
            index_delta.ge(0.0)
            & turnover_delta.ge(0.0)
            & ladder_delta.ge(0.0)
        ),
        "confirmed_non_divergent": (
            ~phase.isin({"divergence", "ebb"}) & ~capital.eq("divergent")
        ),
        "confirmed_divergent": (
            phase.isin({"divergence", "ebb"}) | capital.eq("divergent")
        ),
    }
    for label, mask in masks.items():
        cohorts.append((label, mappings.loc[mask.fillna(False)]))
    for evidence, rows in mappings.groupby(
        "membership_evidence_level", sort=True
    ):
        cohorts.append((str(evidence), rows))
    return cohorts


def _strongest_mapping_events(
    mappings: pd.DataFrame,
) -> list[dict[str, object]]:
    if mappings.empty:
        return []
    records: list[dict[str, object]] = []
    for _, rows in mappings.groupby("leader_event_id", sort=False):
        one_day = pd.to_numeric(
            rows.get("forward_1d_close_return_pct"), errors="coerce"
        ).dropna()
        three_day = pd.to_numeric(
            rows.get("forward_3d_close_return_pct"), errors="coerce"
        ).dropna()
        first = rows.iloc[0]
        records.append(
            {
                "confirmation_date": first.get("confirmation_date"),
                "leader_name": "、".join(_strings(first.get("leader_names")))
                or first.get("leader_name"),
                "sector_name": first.get("sector_name"),
                "mapping_count": len(rows),
                "forward_1d_mean": (
                    float(one_day.mean()) if not one_day.empty else None
                ),
                "forward_1d_win_rate": (
                    float(one_day.gt(0).mean() * 100.0)
                    if not one_day.empty
                    else None
                ),
                "forward_3d_mean": (
                    float(three_day.mean()) if not three_day.empty else None
                ),
            }
        )
    return sorted(
        records,
        key=lambda row: (
            int(row["mapping_count"]),
            _number(row["forward_1d_win_rate"]) or -1.0,
            _number(row["forward_3d_mean"]) or -999.0,
        ),
        reverse=True,
    )


def _mapped_follower_role(value: object) -> str | None:
    roles = set(_strings(value))
    if CapitalRole.LEADER_2.value in roles:
        return CapitalRole.LEADER_2.value
    if CapitalRole.LEADER_3.value in roles:
        return CapitalRole.LEADER_3.value
    return None


def _forward_close_return(
    symbol: str,
    position: int,
    horizon: int,
    trade_dates: Sequence[date],
    bar_lookup: Mapping[tuple[date | None, str], Mapping[str, object]],
    start_close: float | None,
) -> float | None:
    target_position = position + horizon
    if target_position >= len(trade_dates):
        return None
    target = bar_lookup.get((trade_dates[target_position], symbol), {})
    return _close_return(start_close, _number(target.get("close_price")))


def _close_return(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return round((end / start - 1.0) * 100.0, 4)


def _difference(left: object, right: object) -> float | None:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return None
    return round(left_number - right_number, 6)


def _mean(frame: pd.DataFrame, field: str) -> str:
    values = pd.to_numeric(frame.get(field), errors="coerce").dropna()
    return f"{float(values.mean()):.4f}" if not values.empty else "-"


def _positive_rate(frame: pd.DataFrame, field: str) -> str:
    values = pd.to_numeric(frame.get(field), errors="coerce").dropna()
    return f"{float(values.gt(0).mean() * 100.0):.4f}" if not values.empty else "-"


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _signed(value: object) -> str:
    number = _number(value)
    return f"{number:+.2f}%" if number is not None else "-"


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(str(item) for item in value)
    return ()


def _numeric_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return pd.to_numeric(
        frame.get(field, pd.Series(float("nan"), index=frame.index)),
        errors="coerce",
    )


def _string_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return frame.get(field, pd.Series("", index=frame.index)).fillna("").astype(str)


def _boolean_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return frame.get(field, pd.Series(False, index=frame.index)).fillna(False).astype(bool)


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _as_date(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("discovery", "validation"),
        default="discovery",
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--discovery-report",
        type=Path,
        default=Path(
            "memory/06_backtests/limit_up_leader_follower_factor_formal_discovery_2026_03_07.md"
        ),
    )
    parser.add_argument("--forward-output", type=Path)
    arguments = parser.parse_args(argv)
    validation_mode = arguments.mode == "validation"
    discovery_digest = (
        validate_frozen_discovery_report(arguments.discovery_report)
        if validation_mode
        else None
    )
    inputs = load_capital_mainline_inputs(
        arguments.start,
        arguments.end,
        include_prior_formal_evidence=True,
        include_stock_bars=not validation_mode,
        reconstruct_missing_limit_up_events=validation_mode,
    )
    bundle = (
        build_lightweight_research_bundle(
            inputs,
            start=arguments.start,
            end=arguments.end,
        )
        if validation_mode
        else build_research_bundle(
            inputs,
            start=arguments.start,
            end=arguments.end,
        )
    )
    candidates = build_candidate_feature_frame(
        inputs,
        bundle,
        candidate_scope="formal_recommendations",
    )
    leader_events = build_leader_confirmation_events(bundle, inputs.trade_dates)
    event_coverage = inputs.coverage.get("event_coverage") or {}
    candidate_frame = attach_leader_follower_features(
        candidates,
        leader_events,
        leader_event_coverage_start=(
            arguments.start if validation_mode else None
        ),
        observed_event_coverage_start=(
            _as_date(event_coverage.get("observed_event_start"))
            if validation_mode
            else None
        ),
    )
    if validation_mode:
        report = render_frozen_validation_report(
            inputs,
            leader_events,
            candidate_frame,
            discovery_digest=str(discovery_digest),
        )
    else:
        mappings = build_realized_follower_mappings(inputs, bundle, leader_events)
        report = render_leader_follower_report(
            inputs,
            leader_events,
            mappings,
            candidate_frame,
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8")
    if validation_mode and arguments.forward_output is not None:
        arguments.forward_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.forward_output.write_text(
            render_frozen_forward_report(
                evaluate_frozen_validation(candidate_frame),
                discovery_digest=str(discovery_digest),
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
