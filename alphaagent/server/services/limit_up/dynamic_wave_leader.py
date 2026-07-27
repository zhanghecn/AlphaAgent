"""Research dynamic leaders inside restartable concept-capital waves."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from math import isfinite
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from alphaagent.server.services.limit_up.capital_mainline_contract import (
    validate_asof_fields,
)
from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CapitalMainlineInputs,
)
from alphaagent.server.services.limit_up.capital_mainline_research import (
    MembershipContext,
)


STUDY_VERSION = "limit-up-dynamic-wave-leader-v4"
WAVE_IGNITION_PERCENTILE = 0.80
TREND_IGNITION_INDEX_STRENGTH = 0.80
TREND_IGNITION_TURNOVER_STRENGTH = 0.70
JOINT_WEAKNESS_THRESHOLD = 0.50
JOINT_WEAKNESS_SESSIONS = 2
COOLDOWN_MAINLINE_PERCENTILE = 0.55
SHOCK_RETURN_PCT = -3.0
SHOCK_MAX_INDEX_STRENGTH = 0.75
MINIMUM_ROTATION_WAVE_AGE = 3
LEADER_COMPONENT_TOP_COUNT = 3
MINIMUM_CONFIRMING_COMPONENTS = 2
TURNOVER_CAPACITY_THRESHOLD = 0.80
EARLY_EXPANSION_MAX_SESSIONS = 2
DISCOVERY_SPLIT = date(2026, 5, 31)
HOLDOUT_START = date(2026, 6, 1)
AUDIT_NAMES = ("金安国纪", "亨通光电", "东山精密", "德明利", "深科技")


def segment_concept_waves(concept_panel: pd.DataFrame) -> pd.DataFrame:
    """Split each concept into restartable waves using only same-day evidence."""

    if concept_panel.empty:
        return pd.DataFrame()
    required = {"trade_date", "sector_id", "index_strength", "turnover_strength"}
    missing = sorted(required - set(concept_panel.columns))
    if missing:
        raise ValueError(f"concept wave panel missing fields: {', '.join(missing)}")

    records: list[dict[str, object]] = []
    for sector_id, values in concept_panel.groupby("sector_id", sort=True):
        active = False
        wave_number = 0
        wave_id = ""
        wave_start: date | None = None
        wave_start_reason = ""
        wave_age = 0
        weak_sessions = 0
        previous_cooldown = False
        previous_phase: str | None = None
        expansion_age_sessions = 0
        previous_ladder_strength: float | None = None
        previous_turnover_strength: float | None = None
        previous_first_board_count: int | None = None
        previous_sealed_count: int | None = None
        running_peak_mainline = 0.0
        for row in values.sort_values("trade_date").to_dict("records"):
            trade_date = _as_date(row.get("trade_date"))
            if trade_date is None:
                continue
            index_strength = _number(row.get("index_strength")) or 0.0
            turnover_strength = _number(row.get("turnover_strength")) or 0.0
            ladder_strength = _number(row.get("ladder_strength")) or 0.0
            mainline = _number(row.get("mainline_percentile")) or 0.0
            first_boards = _integer(row.get("first_board_count"))
            sealed_count = _integer(row.get("sealed_count"))
            day_return = _number(row.get("return_1d_pct")) or 0.0
            board_ignition = (
                mainline >= WAVE_IGNITION_PERCENTILE
                and first_boards >= 1
                and index_strength >= 0.55
            )
            trend_ignition = (
                index_strength >= TREND_IGNITION_INDEX_STRENGTH
                and turnover_strength >= TREND_IGNITION_TURNOVER_STRENGTH
                and day_return > 0.0
            )
            weak_components = sum(
                value < JOINT_WEAKNESS_THRESHOLD
                for value in (index_strength, turnover_strength, ladder_strength)
            )
            joint_weakness = weak_components >= 2
            shock_cooldown = (
                day_return <= SHOCK_RETURN_PCT
                and index_strength < SHOCK_MAX_INDEX_STRENGTH
            )
            cooldown = (
                joint_weakness
                or mainline < COOLDOWN_MAINLINE_PERCENTILE
                or shock_cooldown
            )
            rotation_ignition = (
                active
                and wave_age >= MINIMUM_ROTATION_WAVE_AGE
                and running_peak_mainline >= WAVE_IGNITION_PERCENTILE
                and cooldown
                and first_boards >= 1
            )
            reignition = (
                active
                and previous_cooldown
                and (board_ignition or trend_ignition)
            )
            started_new_wave = False
            if not active:
                if not board_ignition and not trend_ignition:
                    continue
                active = True
                wave_number += 1
                wave_start = trade_date
                wave_id = f"{sector_id}:{trade_date.isoformat()}:{wave_number}"
                wave_start_reason = (
                    "board_ladder_ignition"
                    if board_ignition
                    else "index_turnover_trend_ignition"
                )
                wave_age = 0
                weak_sessions = 0
                running_peak_mainline = 0.0
                started_new_wave = True
            elif rotation_ignition or reignition:
                wave_number += 1
                wave_start = trade_date
                wave_id = f"{sector_id}:{trade_date.isoformat()}:{wave_number}"
                if rotation_ignition:
                    wave_start_reason = "board_rotation_ignition"
                elif board_ignition:
                    wave_start_reason = "board_reignition_after_cooldown"
                else:
                    wave_start_reason = "trend_reignition_after_cooldown"
                wave_age = 0
                weak_sessions = 0
                running_peak_mainline = 0.0
                started_new_wave = True

            weak_sessions = (
                0
                if started_new_wave
                else weak_sessions + 1 if joint_weakness else 0
            )
            wave_age += 1
            running_peak_mainline = max(running_peak_mainline, mainline)
            if started_new_wave:
                phase = "ignition"
            elif weak_sessions >= JOINT_WEAKNESS_SESSIONS:
                phase = "ebb"
            elif cooldown:
                phase = "divergence"
            elif index_strength >= 0.80 and turnover_strength >= 0.80:
                phase = "acceleration"
            elif ladder_strength >= 0.65 or sealed_count >= 2:
                phase = "diffusion"
            else:
                phase = "confirmation"
            breadth_present = ladder_strength >= 0.65 or sealed_count >= 2
            in_expansion = (
                phase in {"diffusion", "acceleration"} and breadth_present
            )
            comparable = not started_new_wave and previous_phase is not None
            breadth_rising = comparable and (
                (
                    previous_ladder_strength is not None
                    and ladder_strength > previous_ladder_strength
                )
                or (
                    previous_first_board_count is not None
                    and first_boards > previous_first_board_count
                )
                or (
                    previous_sealed_count is not None
                    and sealed_count > previous_sealed_count
                )
            )
            turnover_rising = (
                comparable
                and previous_turnover_strength is not None
                and turnover_strength >= previous_turnover_strength
            )
            if in_expansion:
                expansion_age_sessions = (
                    expansion_age_sessions + 1
                    if previous_phase in {"diffusion", "acceleration"}
                    else 1
                )
            else:
                expansion_age_sessions = 0
            expansion_onset = in_expansion and expansion_age_sessions == 1
            early_expansion = (
                in_expansion
                and expansion_age_sessions <= EARLY_EXPANSION_MAX_SESSIONS
            )
            records.append(
                {
                    **row,
                    "trade_date": trade_date,
                    "wave_id": wave_id,
                    "wave_start_date": wave_start,
                    "wave_start_reason": wave_start_reason,
                    "wave_age_sessions": wave_age,
                    "wave_phase": phase,
                    "joint_weakness": joint_weakness,
                    "joint_weakness_sessions": weak_sessions,
                    "wave_cooldown": cooldown,
                    "wave_shock_cooldown": shock_cooldown,
                    "wave_previous_phase": previous_phase,
                    "wave_expansion_age_sessions": expansion_age_sessions,
                    "wave_expansion_onset": expansion_onset,
                    "wave_early_expansion": early_expansion,
                    "wave_breadth_rising": breadth_rising,
                    "wave_turnover_rising": turnover_rising,
                    "wave_expansion_impulse": (
                        early_expansion and breadth_rising and turnover_rising
                    ),
                    "wave_ladder_delta_1d": (
                        ladder_strength - previous_ladder_strength
                        if comparable and previous_ladder_strength is not None
                        else None
                    ),
                    "wave_turnover_delta_1d": (
                        turnover_strength - previous_turnover_strength
                        if comparable and previous_turnover_strength is not None
                        else None
                    ),
                    "wave_first_board_delta_1d": (
                        first_boards - previous_first_board_count
                        if comparable and previous_first_board_count is not None
                        else None
                    ),
                    "wave_sealed_delta_1d": (
                        sealed_count - previous_sealed_count
                        if comparable and previous_sealed_count is not None
                        else None
                    ),
                }
            )
            previous_cooldown = cooldown and not started_new_wave
            previous_phase = phase
            previous_ladder_strength = ladder_strength
            previous_turnover_strength = turnover_strength
            previous_first_board_count = first_boards
            previous_sealed_count = sealed_count
            if phase == "ebb":
                active = False
                wave_start = None
                wave_id = ""
                wave_start_reason = ""
                wave_age = 0
                weak_sessions = 0
                previous_cooldown = False
                previous_phase = None
                expansion_age_sessions = 0
                previous_ladder_strength = None
                previous_turnover_strength = None
                previous_first_board_count = None
                previous_sealed_count = None
                running_peak_mainline = 0.0
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "sector_id", "wave_id"]
    ).reset_index(drop=True)


def build_wave_member_features(
    inputs: CapitalMainlineInputs,
    waves: pd.DataFrame,
    membership_contexts: Mapping[date, MembershipContext],
) -> pd.DataFrame:
    """Build expanding member evidence without consulting wave-end outcomes."""

    if waves.empty or not inputs.stock_bars:
        return pd.DataFrame()
    bars = pd.DataFrame.from_records(inputs.stock_bars)
    if bars.empty:
        return pd.DataFrame()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    bars["vt_symbol"] = bars["vt_symbol"].fillna("").astype(str).str.upper()
    bars = bars.sort_values(["vt_symbol", "trade_date"]).reset_index(drop=True)
    grouped = bars.groupby("vt_symbol", sort=False)
    bars["stock_return_3d_pct"] = (
        grouped["close_price"].pct_change(3, fill_method=None) * 100.0
    )
    bars["stock_return_5d_pct"] = (
        grouped["close_price"].pct_change(5, fill_method=None) * 100.0
    )
    bars_by_date = {
        trade_date: rows.set_index("vt_symbol", drop=False)
        for trade_date, rows in bars.groupby("trade_date", sort=False)
    }
    bar_symbols_by_date = {
        trade_date: frozenset(rows.index)
        for trade_date, rows in bars_by_date.items()
    }

    records: list[dict[str, object]] = []
    for wave_id, wave_rows in waves.groupby("wave_id", sort=False):
        ordered_wave = wave_rows.sort_values("trade_date")
        sector_id = str(ordered_wave.iloc[0].get("sector_id") or "")
        base_concept_close: float | None = None
        member_state: dict[str, dict[str, object]] = {}
        for wave_row in ordered_wave.to_dict("records"):
            trade_date = _as_date(wave_row.get("trade_date"))
            if trade_date is None:
                continue
            context = membership_contexts.get(trade_date)
            members = (
                set(context.by_sector.get(sector_id, frozenset()))
                if context is not None
                else set()
            )
            daily_bars = bars_by_date.get(trade_date)
            if daily_bars is None or not members:
                continue
            available = sorted(members & bar_symbols_by_date[trade_date])
            if not available:
                continue
            concept_close = _number(wave_row.get("close_price"))
            if base_concept_close is None and concept_close is not None:
                base_concept_close = concept_close
            concept_wave_return = _return_pct(base_concept_close, concept_close)
            daily_records: list[dict[str, object]] = []
            for symbol in available:
                bar = daily_bars.loc[symbol]
                if isinstance(bar, pd.DataFrame):
                    bar = bar.iloc[-1]
                state = member_state.setdefault(
                    symbol,
                    {
                        "base_close": _number(bar.get("close_price")),
                        "first_strength_date": None,
                        "cumulative_limit_up_count": 0,
                        "effective_board_streak": 0,
                        "positive_session_count": 0,
                    },
                )
                change_pct = _number(bar.get("change_pct")) or 0.0
                return_3d = _number(bar.get("stock_return_3d_pct"))
                is_limit_up = change_pct >= 9.5
                state["cumulative_limit_up_count"] = _integer(
                    state.get("cumulative_limit_up_count")
                ) + int(is_limit_up)
                state["effective_board_streak"] = (
                    _integer(state.get("effective_board_streak")) + 1
                    if is_limit_up
                    else 0
                )
                state["positive_session_count"] = _integer(
                    state.get("positive_session_count")
                ) + int(change_pct > 0.0)
                if (
                    state.get("first_strength_date") is None
                    and (change_pct >= 5.0 or (return_3d is not None and return_3d >= 10.0))
                ):
                    state["first_strength_date"] = trade_date
                stock_wave_return = _return_pct(
                    _number(state.get("base_close")),
                    _number(bar.get("close_price")),
                )
                daily_records.append(
                    {
                        "trade_date": trade_date,
                        "sector_id": sector_id,
                        "sector_name": str(wave_row.get("sector_name") or sector_id),
                        "wave_id": str(wave_id),
                        "wave_start_date": wave_row.get("wave_start_date"),
                        "wave_age_sessions": wave_row.get("wave_age_sessions"),
                        "wave_phase": wave_row.get("wave_phase"),
                        "wave_mainline_percentile": _number(
                            wave_row.get("mainline_percentile")
                        ),
                        "wave_index_strength": _number(
                            wave_row.get("index_strength")
                        ),
                        "wave_turnover_strength": _number(
                            wave_row.get("turnover_strength")
                        ),
                        "wave_ladder_strength": _number(
                            wave_row.get("ladder_strength")
                        ),
                        "wave_previous_phase": wave_row.get(
                            "wave_previous_phase"
                        ),
                        "wave_expansion_age_sessions": _integer(
                            wave_row.get("wave_expansion_age_sessions")
                        ),
                        "wave_expansion_onset": bool(
                            wave_row.get("wave_expansion_onset")
                        ),
                        "wave_early_expansion": bool(
                            wave_row.get("wave_early_expansion")
                        ),
                        "wave_breadth_rising": bool(
                            wave_row.get("wave_breadth_rising")
                        ),
                        "wave_turnover_rising": bool(
                            wave_row.get("wave_turnover_rising")
                        ),
                        "wave_expansion_impulse": bool(
                            wave_row.get("wave_expansion_impulse")
                        ),
                        "wave_ladder_delta_1d": _number(
                            wave_row.get("wave_ladder_delta_1d")
                        ),
                        "wave_turnover_delta_1d": _number(
                            wave_row.get("wave_turnover_delta_1d")
                        ),
                        "wave_first_board_delta_1d": _number(
                            wave_row.get("wave_first_board_delta_1d")
                        ),
                        "wave_sealed_delta_1d": _number(
                            wave_row.get("wave_sealed_delta_1d")
                        ),
                        "vt_symbol": symbol,
                        "name": str(bar.get("name") or symbol),
                        "change_pct": change_pct,
                        "turnover": _number(bar.get("turnover")),
                        "turnover_rate": _number(bar.get("turnover_rate")),
                        "stock_return_3d_pct": return_3d,
                        "stock_return_5d_pct": _number(bar.get("stock_return_5d_pct")),
                        "wave_return_pct": stock_wave_return,
                        "concept_wave_return_pct": concept_wave_return,
                        "relative_wave_return_pct": (
                            stock_wave_return - concept_wave_return
                            if stock_wave_return is not None
                            and concept_wave_return is not None
                            else None
                        ),
                        "first_strength_date": state.get("first_strength_date"),
                        "cumulative_limit_up_count": state.get(
                            "cumulative_limit_up_count"
                        ),
                        "effective_board_streak": state.get(
                            "effective_board_streak"
                        ),
                        "positive_session_count": state.get("positive_session_count"),
                        "available_member_count": len(available),
                        "membership_evidence_level": (
                            context.evidence_level.value
                            if context is not None
                            else "unavailable"
                        ),
                        "member_universe_mode": _stock_bar_universe(inputs),
                    }
                )
            strength_dates = sorted(
                state["first_strength_date"]
                for state in member_state.values()
                if state.get("first_strength_date") is not None
                and state["first_strength_date"] <= trade_date
            )
            for record in daily_records:
                own_date = record.get("first_strength_date")
                record["response_member_count_asof"] = (
                    len(strength_dates) - bisect_right(strength_dates, own_date)
                    if own_date is not None
                    else 0
                )
            records.extend(daily_records)
    if not records:
        return pd.DataFrame()
    result = pd.DataFrame.from_records(records)
    result["turnover_percentile"] = result.groupby(
        ["trade_date", "wave_id"], sort=False
    )["turnover"].rank(pct=True, method="average")
    return result.sort_values(
        ["trade_date", "wave_id", "vt_symbol"]
    ).reset_index(drop=True)


def rank_dynamic_wave_leaders(features: pd.DataFrame) -> pd.DataFrame:
    """Assign dynamic top-three seats from transparent independent components."""

    if features.empty:
        return pd.DataFrame()
    result = features.copy().reset_index(drop=True)
    group_fields = ["trade_date", "wave_id"]
    strength_date = pd.to_datetime(result["first_strength_date"], errors="coerce")
    strength_ordinal = strength_date.map(
        lambda value: value.toordinal() if not pd.isna(value) else np.nan
    )
    result["ignition_component"] = _group_rank(
        result,
        strength_ordinal,
        group_fields,
        ascending=False,
        pct=True,
        method="average",
    )
    trend_parts = [
        _group_percentile(result, field, group_fields)
        for field in (
            "relative_wave_return_pct",
            "stock_return_3d_pct",
            "stock_return_5d_pct",
        )
    ]
    result["trend_component"] = pd.concat(trend_parts, axis=1).mean(
        axis=1, skipna=True
    )
    result["capacity_component"] = pd.to_numeric(
        result.get("turnover_percentile"), errors="coerce"
    )
    board_parts = [
        _group_percentile(result, "cumulative_limit_up_count", group_fields),
        _group_percentile(result, "effective_board_streak", group_fields),
    ]
    result["board_component"] = pd.concat(board_parts, axis=1).mean(
        axis=1, skipna=True
    )
    result["diffusion_component"] = _group_percentile(
        result,
        "response_member_count_asof",
        group_fields,
    )
    component_names = (
        "ignition_component",
        "trend_component",
        "capacity_component",
        "board_component",
        "diffusion_component",
    )
    rank_names: list[str] = []
    for component in component_names:
        rank_name = component.replace("_component", "_component_rank")
        result[rank_name] = _group_rank(
            result,
            pd.to_numeric(result[component], errors="coerce"),
            group_fields,
            ascending=False,
            pct=False,
            method="min",
        )
        rank_names.append(rank_name)
    result["confirming_component_count"] = pd.concat(
        [result[name].le(LEADER_COMPONENT_TOP_COUNT) for name in rank_names],
        axis=1,
    ).sum(axis=1)
    result["leadership_score"] = result[list(component_names)].mean(
        axis=1, skipna=True
    )
    eligible = result["first_strength_date"].notna() & result[
        "confirming_component_count"
    ].ge(MINIMUM_CONFIRMING_COMPONENTS)
    ordered = result.loc[eligible].sort_values(
        [
            *group_fields,
            "leadership_score",
            "trend_component",
            "capacity_component",
            "board_component",
            "vt_symbol",
        ],
        ascending=[True, True, False, False, False, False, True],
    )
    ordered_leader_rank = ordered.groupby(group_fields, sort=False).cumcount() + 1
    top_three = ordered_leader_rank.le(3)
    result["leader_rank"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result.loc[ordered.index[top_three], "leader_rank"] = ordered_leader_rank.loc[
        top_three
    ].to_numpy()
    role_by_component = {
        "ignition_component_rank": "ignition_leader",
        "trend_component_rank": "trend_leader",
        "capacity_component_rank": "capacity_leader",
        "board_component_rank": "board_leader",
        "diffusion_component_rank": "diffusion_leader",
    }
    component_rank_values = {
        role: pd.to_numeric(result[rank_name], errors="coerce").to_numpy()
        for rank_name, role in role_by_component.items()
    }
    result["leader_roles"] = [
        [
            role
            for role, values in component_rank_values.items()
            if not pd.isna(values[index])
            and values[index] <= LEADER_COMPONENT_TOP_COUNT
        ]
        for index in range(len(result))
    ]
    tenure_order = result.sort_values(
        ["wave_id", "vt_symbol", "trade_date"]
    ).copy()
    tenure_order["leadership_tenure_sessions"] = _consecutive_true_counts(
        tenure_order,
        tenure_order["leader_rank"].notna(),
        ["wave_id", "vt_symbol"],
    )
    tenure_order["leader_rank_1_tenure_sessions"] = _consecutive_true_counts(
        tenure_order,
        tenure_order["leader_rank"].eq(1).fillna(False),
        ["wave_id", "vt_symbol"],
    )
    result.loc[
        tenure_order.index, "leadership_tenure_sessions"
    ] = tenure_order["leadership_tenure_sessions"]
    result.loc[
        tenure_order.index, "leader_rank_1_tenure_sessions"
    ] = tenure_order["leader_rank_1_tenure_sessions"]
    return result.sort_values(
        ["trade_date", "wave_id", "leader_rank", "vt_symbol"],
        na_position="last",
    ).reset_index(drop=True)


def build_dynamic_leader_mappings(
    ranks: pd.DataFrame,
    stock_bars: pd.DataFrame,
    trade_dates: Sequence[date],
) -> pd.DataFrame:
    """Create realized labels for dynamic rank transitions inside one wave."""

    if ranks.empty or stock_bars.empty:
        return pd.DataFrame()
    ranked = ranks.loc[
        pd.to_numeric(ranks.get("leader_rank"), errors="coerce").isin([1, 2, 3])
    ].copy()
    if ranked.empty:
        return pd.DataFrame()
    bars = stock_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    close_lookup = {
        (str(row.vt_symbol), row.trade_date): _number(row.close_price)
        for row in bars.itertuples()
    }
    ordered_dates = tuple(sorted({_as_date(value) for value in trade_dates if _as_date(value)}))
    date_position = {value: index for index, value in enumerate(ordered_dates)}
    records: list[dict[str, object]] = []
    for wave_id, wave_rows in ranked.groupby("wave_id", sort=False):
        active_leader: str | None = None
        leader_start: date | None = None
        seen_transitions: set[tuple[str, int]] = set()
        for trade_date, daily in wave_rows.groupby("trade_date", sort=True):
            leaders = daily.loc[pd.to_numeric(daily["leader_rank"], errors="coerce").eq(1)]
            if leaders.empty:
                continue
            leader = leaders.sort_values("leadership_score", ascending=False).iloc[0]
            leader_symbol = str(leader["vt_symbol"])
            if leader_symbol != active_leader:
                active_leader = leader_symbol
                leader_start = _as_date(trade_date)
                seen_transitions = set()
            if leader_start is None:
                continue
            followers = daily.loc[
                pd.to_numeric(daily["leader_rank"], errors="coerce").isin([2, 3])
            ].sort_values(["leader_rank", "vt_symbol"])
            for follower in followers.to_dict("records"):
                follower_symbol = str(follower.get("vt_symbol") or "")
                follower_rank = _integer(follower.get("leader_rank"))
                transition = (follower_symbol, follower_rank)
                if (
                    not follower_symbol
                    or follower_symbol == active_leader
                    or transition in seen_transitions
                ):
                    continue
                seen_transitions.add(transition)
                response_date = _as_date(trade_date)
                response_position = date_position.get(response_date)
                response_close = close_lookup.get((follower_symbol, response_date))
                realized = {
                    f"realized_forward_{horizon}d_close_return_pct": _forward_return(
                        close_lookup,
                        ordered_dates,
                        response_position,
                        follower_symbol,
                        response_close,
                        horizon,
                    )
                    for horizon in (1, 3, 5)
                }
                records.append(
                    {
                        "wave_id": str(wave_id),
                        "sector_id": str(follower.get("sector_id") or ""),
                        "sector_name": str(follower.get("sector_name") or ""),
                        "leader_symbol": active_leader,
                        "leader_first_date": leader_start,
                        "leader_roles": list(leader.get("leader_roles") or ()),
                        "leader_rank_1_tenure_sessions": _optional_integer(
                            leader.get("leader_rank_1_tenure_sessions")
                        ),
                        "follower_symbol": follower_symbol,
                        "follower_name": str(follower.get("name") or follower_symbol),
                        "follower_roles": list(follower.get("leader_roles") or ()),
                        "follower_response_date": response_date,
                        "rank_at_response": follower_rank,
                        "wave_phase": follower.get("wave_phase"),
                        "wave_mainline_percentile": follower.get(
                            "wave_mainline_percentile"
                        ),
                        "delay_sessions": (
                            response_position - date_position[leader_start]
                            if response_position is not None
                            and leader_start in date_position
                            else None
                        ),
                        **realized,
                    }
                )
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values(
        ["leader_first_date", "wave_id", "follower_response_date", "rank_at_response"]
    ).reset_index(drop=True)


def attach_dynamic_wave_features(
    candidate_frame: pd.DataFrame,
    ranks: pd.DataFrame,
    trade_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach only the previous session's dynamic leadership evidence."""

    if candidate_frame.empty:
        return candidate_frame.copy()
    dates = tuple(sorted({_as_date(value) for value in trade_dates if _as_date(value)}))
    previous_date = {
        value: dates[index - 1] if index else None
        for index, value in enumerate(dates)
    }
    rank_rows = ranks.copy()
    if not rank_rows.empty:
        rank_rows["trade_date"] = pd.to_datetime(rank_rows["trade_date"]).dt.date
    by_identity: dict[tuple[date, str, str], dict[str, object]] = {}
    by_symbol_date: dict[tuple[date, str], list[dict[str, object]]] = {}
    wave_leaders: dict[tuple[date, str], dict[str, object]] = {}
    for row in rank_rows.to_dict("records"):
        by_identity[
            (
                row["trade_date"],
                str(row["vt_symbol"]),
                str(row.get("sector_id") or ""),
            )
        ] = row
        by_symbol_date.setdefault(
            (row["trade_date"], str(row["vt_symbol"])), []
        ).append(row)
        if _integer(row.get("leader_rank")) == 1:
            wave_leaders[(row["trade_date"], str(row.get("wave_id") or ""))] = row
    records: list[dict[str, object]] = []
    for candidate in candidate_frame.to_dict("records"):
        trade_date = _as_date(candidate.get("trade_date"))
        prior_date = previous_date.get(trade_date)
        symbol = str(candidate.get("vt_symbol") or "")
        sector_id = str(candidate.get("prior_sector_id") or "")
        exact = (
            by_identity.get((prior_date, symbol, sector_id))
            if prior_date
            else None
        )
        alternatives = (
            by_symbol_date.get((prior_date, symbol), [])
            if prior_date is not None
            else []
        )
        own = (
            max(
                alternatives,
                key=lambda row: _wave_context_priority(
                    row,
                    wave_leaders.get(
                        (prior_date, str(row.get("wave_id") or "")),
                        {},
                    ),
                ),
            )
            if alternatives
            else None
        )
        if own is None:
            match_mode = "unavailable"
        elif exact is None:
            match_mode = "dynamic_propagation_membership"
        elif str(own.get("sector_id") or "") == sector_id:
            match_mode = "dynamic_propagation_exact"
        else:
            match_mode = "dynamic_propagation_override"
        wave_id = str((own or {}).get("wave_id") or "")
        leader = wave_leaders.get((prior_date, wave_id), {}) if prior_date else {}
        own_rank = _optional_integer((own or {}).get("leader_rank"))
        same_wave_member = own is not None
        has_wave_leader = bool(leader)
        record = {
            **candidate,
            "prior_dynamic_trade_date": prior_date,
            "prior_wave_id": wave_id or None,
            "prior_wave_match_mode": match_mode,
            "prior_static_primary_sector_id": sector_id or None,
            "prior_wave_sector_id": (own or {}).get("sector_id"),
            "prior_wave_sector_name": (own or {}).get("sector_name"),
            "prior_wave_phase": (own or {}).get("wave_phase"),
            "prior_wave_mainline_percentile": (own or {}).get(
                "wave_mainline_percentile"
            ),
            "prior_wave_index_strength": (own or {}).get(
                "wave_index_strength"
            ),
            "prior_wave_turnover_strength": (own or {}).get(
                "wave_turnover_strength"
            ),
            "prior_wave_ladder_strength": (own or {}).get(
                "wave_ladder_strength"
            ),
            "prior_wave_previous_phase": (own or {}).get(
                "wave_previous_phase"
            ),
            "prior_wave_expansion_age_sessions": (own or {}).get(
                "wave_expansion_age_sessions"
            ),
            "prior_wave_expansion_onset": bool(
                (own or {}).get("wave_expansion_onset")
            ),
            "prior_wave_early_expansion": bool(
                (own or {}).get("wave_early_expansion")
            ),
            "prior_wave_breadth_rising": bool(
                (own or {}).get("wave_breadth_rising")
            ),
            "prior_wave_turnover_rising": bool(
                (own or {}).get("wave_turnover_rising")
            ),
            "prior_wave_expansion_impulse": bool(
                (own or {}).get("wave_expansion_impulse")
            ),
            "prior_wave_ladder_delta_1d": (own or {}).get(
                "wave_ladder_delta_1d"
            ),
            "prior_wave_turnover_delta_1d": (own or {}).get(
                "wave_turnover_delta_1d"
            ),
            "prior_wave_first_board_delta_1d": (own or {}).get(
                "wave_first_board_delta_1d"
            ),
            "prior_wave_sealed_delta_1d": (own or {}).get(
                "wave_sealed_delta_1d"
            ),
            "prior_dynamic_leader_rank": own_rank,
            "prior_dynamic_leader_roles": list((own or {}).get("leader_roles") or ()),
            "prior_dynamic_leadership_score": (own or {}).get("leadership_score"),
            "prior_dynamic_leadership_tenure": (own or {}).get(
                "leadership_tenure_sessions"
            ),
            "prior_wave_leader_symbol": leader.get("vt_symbol"),
            "prior_wave_leader_roles": list(leader.get("leader_roles") or ()),
            "prior_wave_leader_score": leader.get("leadership_score"),
            "prior_wave_leader_rank_1_tenure": leader.get(
                "leader_rank_1_tenure_sessions"
            ),
            "prior_has_dynamic_wave_leader": has_wave_leader,
            "prior_same_wave_member": same_wave_member,
            "prior_same_wave_follower": (
                same_wave_member and has_wave_leader and own_rank != 1
            ),
            "prior_same_wave_low_position_follower": (
                same_wave_member and has_wave_leader and own_rank is None
            ),
        }
        records.append(record)
    result = pd.DataFrame.from_records(records)
    validate_asof_fields(
        [column for column in result.columns if column.startswith("prior_")]
    )
    return result.sort_values(
        ["trade_date", "vt_symbol"]
    ).reset_index(drop=True)


def evaluate_dynamic_wave_factors(frame: pd.DataFrame) -> dict[str, object]:
    """Evaluate pre-registered dynamic roles on all formal recommendations."""

    from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
        monthly_summaries,
        performance_summary,
    )

    if frame.empty:
        return {}
    baseline_count = int(
        pd.to_numeric(frame.get("return_pct"), errors="coerce").notna().sum()
    )
    ranks = pd.to_numeric(
        frame.get(
            "prior_dynamic_leader_rank",
            pd.Series(np.nan, index=frame.index),
        ),
        errors="coerce",
    )
    role_series = frame.get(
        "prior_dynamic_leader_roles",
        pd.Series([[] for _ in range(len(frame))], index=frame.index),
    )
    role_count = role_series.map(lambda values: len(_string_sequence(values)))

    def has_role(role: str) -> pd.Series:
        return role_series.map(lambda values: role in _string_sequence(values))

    wave_leader_roles = frame.get(
        "prior_wave_leader_roles",
        pd.Series([[] for _ in range(len(frame))], index=frame.index),
    )
    wave_leader_role_count = wave_leader_roles.map(
        lambda values: len(_string_sequence(values))
    )

    def wave_leader_has_role(role: str) -> pd.Series:
        return wave_leader_roles.map(
            lambda values: role in _string_sequence(values)
        )

    phase = frame.get("prior_wave_phase", pd.Series("", index=frame.index)).fillna("")
    wave_leader_present = frame.get(
        "prior_has_dynamic_wave_leader",
        pd.Series(False, index=frame.index),
    ).fillna(False).astype(bool)
    same_wave_follower = frame.get(
        "prior_same_wave_follower",
        pd.Series(False, index=frame.index),
    ).fillna(False).astype(bool)
    low_position_follower = frame.get(
        "prior_same_wave_low_position_follower",
        pd.Series(False, index=frame.index),
    ).fillna(False).astype(bool)
    lane = frame.get("lane", pd.Series("", index=frame.index)).fillna("").astype(str)
    target_board = pd.to_numeric(
        frame.get("target_board", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    first_board = lane.eq("first_board") | target_board.eq(1)
    two_to_three = lane.eq("two_to_three") | target_board.eq(3)
    wave_leader_tenure = pd.to_numeric(
        frame.get(
            "prior_wave_leader_rank_1_tenure",
            pd.Series(np.nan, index=frame.index),
        ),
        errors="coerce",
    )
    wave_trend_leader = wave_leader_has_role("trend_leader")
    wave_capacity_leader = wave_leader_has_role("capacity_leader")
    wave_board_leader = wave_leader_has_role("board_leader")
    reference_turnover_capacity = pd.to_numeric(
        frame.get("prior_turnover_strength", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    ).ge(TURNOVER_CAPACITY_THRESHOLD)
    wave_turnover_capacity = pd.to_numeric(
        frame.get(
            "prior_wave_turnover_strength",
            pd.Series(np.nan, index=frame.index),
        ),
        errors="coerce",
    ).ge(TURNOVER_CAPACITY_THRESHOLD)
    strong_mainline = pd.to_numeric(
        frame.get(
            "prior_wave_mainline_percentile",
            pd.Series(np.nan, index=frame.index),
        ),
        errors="coerce",
    ).ge(WAVE_IGNITION_PERCENTILE)
    diffusion = phase.isin(["diffusion", "acceleration"])
    expansion_onset = frame.get(
        "prior_wave_expansion_onset",
        pd.Series(False, index=frame.index),
    ).fillna(False).astype(bool)
    early_expansion = frame.get(
        "prior_wave_early_expansion",
        pd.Series(False, index=frame.index),
    ).fillna(False).astype(bool)
    expansion_impulse = frame.get(
        "prior_wave_expansion_impulse",
        pd.Series(False, index=frame.index),
    ).fillna(False).astype(bool)
    prior_limit_count_126 = pd.to_numeric(
        frame.get("prior_limit_count_126", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    industry_turnover_expanding = pd.to_numeric(
        frame.get(
            "prior_industry_turnover_ratio_5d",
            pd.Series(np.nan, index=frame.index),
        ),
        errors="coerce",
    ).ge(1.0)
    reconstructed_quality = (
        prior_limit_count_126.between(2, 6) & industry_turnover_expanding
    )
    active_pre_divergence = phase.isin(
        ["ignition", "confirmation", "diffusion", "acceleration"]
    )
    masks = {
        "formal_baseline": pd.Series(True, index=frame.index),
        "wave_leader_present": wave_leader_present,
        "same_wave_follower_under_leader": same_wave_follower,
        "low_position_follower_under_leader": low_position_follower,
        "first_board_low_position_follower": low_position_follower & first_board,
        "two_to_three_low_position_follower": (
            low_position_follower & two_to_three
        ),
        "first_board_same_wave_follower": same_wave_follower & first_board,
        "two_to_three_same_wave_follower": same_wave_follower & two_to_three,
        "trend_leader_low_position_follower": (
            low_position_follower & wave_trend_leader
        ),
        "capacity_leader_low_position_follower": (
            low_position_follower & wave_capacity_leader
        ),
        "board_leader_low_position_follower": (
            low_position_follower & wave_board_leader
        ),
        "trend_capacity_leader_low_position_follower": (
            low_position_follower & wave_trend_leader & wave_capacity_leader
        ),
        "multi_role_wave_leader_low_position_follower": (
            low_position_follower & wave_leader_role_count.ge(2)
        ),
        "leader_tenure_1d_low_position_follower": (
            low_position_follower & wave_leader_tenure.eq(1)
        ),
        "leader_tenure_2d_low_position_follower": (
            low_position_follower & wave_leader_tenure.eq(2)
        ),
        "leader_tenure_3d_low_position_follower": (
            low_position_follower & wave_leader_tenure.eq(3)
        ),
        "leader_tenure_ge_4d_low_position_follower": (
            low_position_follower & wave_leader_tenure.ge(4)
        ),
        "low_position_follower_in_diffusion": (
            low_position_follower & diffusion
        ),
        "low_position_follower_in_divergence": (
            low_position_follower & phase.isin(["divergence", "ebb"])
        ),
        "dynamic_leader_1": ranks.eq(1),
        "dynamic_leader_2_3": ranks.isin([2, 3]),
        "dynamic_top_3": ranks.isin([1, 2, 3]),
        "trend_leader": has_role("trend_leader"),
        "capacity_leader": has_role("capacity_leader"),
        "board_leader": has_role("board_leader"),
        "ignition_leader": has_role("ignition_leader"),
        "multi_role_leader": ranks.isin([1, 2, 3]) & role_count.ge(2),
        "dynamic_followers_in_diffusion": ranks.isin([2, 3])
        & phase.isin(["diffusion", "acceleration"]),
        "dynamic_followers_in_divergence": ranks.isin([2, 3])
        & phase.isin(["divergence", "ebb"]),
        "turnover_capacity_ge_080_reference": reference_turnover_capacity,
        "turnover_capacity_wave_leader_present": (
            wave_turnover_capacity & wave_leader_present
        ),
        "turnover_capacity_low_position_follower": (
            wave_turnover_capacity & low_position_follower
        ),
        "turnover_capacity_first_board_low_position_follower": (
            wave_turnover_capacity & low_position_follower & first_board
        ),
        "turnover_capacity_low_position_follower_in_diffusion": (
            wave_turnover_capacity & low_position_follower & diffusion
        ),
        "mainline_ge_080_low_position_follower": (
            strong_mainline & low_position_follower
        ),
        "mainline_turnover_ge_080_low_position_follower": (
            strong_mainline & wave_turnover_capacity & low_position_follower
        ),
        "wave_expansion_onset": expansion_onset,
        "wave_early_expansion": early_expansion,
        "wave_expansion_impulse": expansion_impulse,
        "quality_reconstruction_core": reconstructed_quality,
        "quality_core_wave_expansion_onset": (
            reconstructed_quality & expansion_onset
        ),
        "quality_core_wave_early_expansion": (
            reconstructed_quality & early_expansion
        ),
        "quality_core_wave_expansion_impulse": (
            reconstructed_quality & expansion_impulse
        ),
        "quality_core_low_position_early_expansion": (
            reconstructed_quality & low_position_follower & early_expansion
        ),
        "quality_core_probable_guide_early_expansion": (
            reconstructed_quality & wave_leader_present & early_expansion
        ),
        "quality_core_active_pre_divergence": (
            reconstructed_quality & active_pre_divergence
        ),
        "quality_core_in_diffusion_or_acceleration": (
            reconstructed_quality & diffusion
        ),
        "quality_core_in_acceleration": (
            reconstructed_quality & phase.eq("acceleration")
        ),
        "quality_core_in_divergence_or_ebb": (
            reconstructed_quality & phase.isin(["divergence", "ebb"])
        ),
    }
    results: dict[str, object] = {}
    for name, mask in masks.items():
        selected = frame.loc[mask.fillna(False)]
        train = selected.loc[pd.to_datetime(selected["trade_date"]).dt.date <= DISCOVERY_SPLIT]
        holdout = selected.loc[pd.to_datetime(selected["trade_date"]).dt.date >= HOLDOUT_START]
        full_summary = performance_summary(selected, baseline_count=baseline_count)
        discovery_summary = performance_summary(train, baseline_count=baseline_count)
        holdout_summary = performance_summary(holdout, baseline_count=baseline_count)
        covered_months = len(
            {
                str(value)[:7]
                for value in selected.loc[
                    pd.to_numeric(selected.get("return_pct"), errors="coerce").notna(),
                    "trade_date",
                ]
            }
        )
        results[name] = {
            "full": full_summary,
            "discovery_3_5": discovery_summary,
            "holdout_6_7": holdout_summary,
            "monthly": monthly_summaries(selected),
            "covered_months": covered_months,
            "status": _factor_status(
                full_summary,
                discovery_summary,
                holdout_summary,
                covered_months,
            ),
        }
    return results


def render_dynamic_wave_report(
    inputs: CapitalMainlineInputs,
    waves: pd.DataFrame,
    ranks: pd.DataFrame,
    mappings: pd.DataFrame,
    candidate_frame: pd.DataFrame,
) -> str:
    results = evaluate_dynamic_wave_factors(candidate_frame)
    expansion_onset = results.get("wave_expansion_onset", {}).get("full", {})
    early_expansion = results.get("wave_early_expansion", {}).get("full", {})
    quality_core = results.get("quality_reconstruction_core", {}).get("full", {})
    quality_early = results.get(
        "quality_core_wave_early_expansion", {}
    ).get("full", {})
    unique_rank_rows = ranks.loc[pd.to_numeric(ranks.get("leader_rank"), errors="coerce").le(3)].copy()
    member_universe = _stock_bar_universe(inputs)
    lines = [
        "# AlphaAgent 2026 年 3-7 月动态资金波段龙头发现",
        "",
        "## Current state",
        "",
        f"- 研究版本：`{STUDY_VERSION}`；区间 `{inputs.coverage.get('start')}..{inputs.coverage.get('end')}`；交易日 `{len(inputs.trade_dates)}`。",
        f"- 动态概念资金波段：`{waves['wave_id'].nunique() if not waves.empty else 0}`；有动态前三席位的波段：`{unique_rank_rows['wave_id'].nunique() if not unique_rank_rows.empty else 0}`。",
        f"- 动态席位日记录：`{len(unique_rank_rows)}`；事后同波段龙二龙三迁移映射：`{len(mappings)}`。",
        "- 波段与席位计算不读取股票或概念名称；命名案例只用于审计输出。",
        f"- 股票日线成员宇宙：`{member_universe}`；3-6 月成员仍为当前成员幸存者代理，因此本报告只能发现机制，不能批准生产。",
        "- 未来 1/3/5 日收益只存在于 `realized_*` 映射标签；正式候选只连接 D-1 动态席位。",
        "- 因子状态同时要求全量、3-5 月和 6-7 月胜率均达到 `60%`；任一时间段反转即标记 `time_split_reversal`。",
        f"- 扩散首日单独为 `{_integer(expansion_onset.get('win_count'))}/{_integer(expansion_onset.get('closed_count'))}={_fmt(expansion_onset.get('win_rate_pct'))}%`；扩散前两日为 "
        f"`{_integer(early_expansion.get('win_count'))}/{_integer(early_expansion.get('closed_count'))}={_fmt(early_expansion.get('win_rate_pct'))}%`，不是独立质量门。",
        f"- 质量重建底座为 `{_integer(quality_core.get('win_count'))}/{_integer(quality_core.get('closed_count'))}={_fmt(quality_core.get('win_rate_pct'))}%`；叠加扩散前两日后为 "
        f"`{_integer(quality_early.get('win_count'))}/{_integer(quality_early.get('closed_count'))}={_fmt(quality_early.get('win_rate_pct'))}%`。后者有历史增量但不足 30 笔，只能作为 A 级优先与自然前向候选。",
        "",
        "## Why the previous algorithm missed technology leaders",
        "",
        "- 旧确认龙必须一板后次日二板，无法表达首板后继续趋势放量的容量龙。",
        "- 旧 PCB 周期横跨 4 月 7 日到 7 月 2 日，多轮科技主升被粘成一个概念周期。",
        "- 旧龙二龙三是单日涨停事件排名；本报告改为波段内逐日累计、允许迁移的动态席位。",
        "- 当前宽概念仍会让同一容量龙重复进入多个波段；命名案例被识别不等于主概念归属和全市场月榜已经无噪声。",
        "",
        "## Named-case audit",
        "",
        "| 股票 | 是否进入动态前三 | 首次成立 | 最后成立 | 全部波段 | 主线强区波段 | 出现席位 | 角色分量 |",
        "|---|---|---|---|---:|---:|---|---|",
    ]
    for name in AUDIT_NAMES:
        rows = unique_rank_rows.loc[unique_rank_rows.get("name", pd.Series("", index=unique_rank_rows.index)).eq(name)]
        if rows.empty:
            lines.append(f"| {name} | 否 | - | - | 0 | 0 | - | - |")
            continue
        dominant_rows = rows.loc[
            pd.to_numeric(
                rows.get("wave_mainline_percentile"), errors="coerce"
            ).ge(WAVE_IGNITION_PERCENTILE)
        ]
        roles = sorted(
            {
                role
                for values in rows["leader_roles"]
                for role in _string_sequence(values)
            }
        )
        rank_values = sorted(
            {int(value) for value in pd.to_numeric(rows["leader_rank"], errors="coerce").dropna()}
        )
        lines.append(
            f"| {name} | 是 | {rows['trade_date'].min()} | {rows['trade_date'].max()} | {rows['wave_id'].nunique()} | {dominant_rows['wave_id'].nunique()} | {','.join(map(str, rank_values))} | {','.join(roles)} |"
        )
    lines.extend(_render_named_case_wave_detail(unique_rank_rows))
    lines.extend(
        [
            "",
            "## Monthly dominant-wave leader sequence",
            "",
            "只保留当日主线分位 `>=0.80` 的概念波段；同一股票同日跨多个概念只保留最高领导力分数，再按月统计龙一日数。这不是永久身份。",
            "",
            "| 月份 | 短线情绪龙一（点火/连板） | 趋势/容量龙一 |",
            "|---|---|---|",
        ]
    )
    if not unique_rank_rows.empty:
        leader_1 = unique_rank_rows.loc[
            pd.to_numeric(unique_rank_rows["leader_rank"], errors="coerce").eq(1)
            & pd.to_numeric(
                unique_rank_rows.get("wave_mainline_percentile"), errors="coerce"
            ).ge(WAVE_IGNITION_PERCENTILE)
        ].copy()
        leader_1["month"] = leader_1["trade_date"].map(lambda value: str(value)[:7])
        leader_1 = leader_1.sort_values("leadership_score", ascending=False).drop_duplicates(
            ["trade_date", "vt_symbol"]
        )
        for month, rows in leader_1.groupby("month", sort=True):
            emotion = _monthly_leader_summary(
                rows,
                {"ignition_leader", "board_leader"},
            )
            trend_capacity = _monthly_leader_summary(
                rows,
                {"trend_leader", "capacity_leader"},
            )
            lines.append(
                f"| {month} | {emotion or '-'} | {trend_capacity or '-'} |"
            )
    lines.extend(_render_wave_ledger(waves, unique_rank_rows))
    lines.extend(
        [
            "",
            "## Dynamic leader-to-follower realized mapping",
            "",
            "| 映射组 | 样本 | 后1日上涨率 | 后3日上涨率 | 后5日上涨率 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for label, selected in _mapping_groups(mappings):
        lines.append(
            f"| {label} | {len(selected)} | {_up_rate(selected, 'realized_forward_1d_close_return_pct')} | {_up_rate(selected, 'realized_forward_3d_close_return_pct')} | {_up_rate(selected, 'realized_forward_5d_close_return_pct')} |"
        )
    lines.extend(
        [
            "",
            "## Formal recommendation factor ablation",
            "",
            "以下全部使用正式独立账户 D+1 收益，不读取两仓结果。",
            "",
            "| 因子 | 闭合 | 保留率 | 胜率 | 均值 | 复利 | 回撤 | 3-5月笔数/胜率 | 6-7月笔数/胜率 | 月份 | 状态 |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|---:|---|",
        ]
    )
    for name, result in results.items():
        full = result["full"]
        train = result["discovery_3_5"]
        holdout = result["holdout_6_7"]
        lines.append(
            f"| {name} | {full['closed_count']} | {_fmt(full['retention_pct'])}% | {_fmt(full['win_rate_pct'])}% | {_signed(full['average_return_pct'])} | {_signed(full['daily_equal_weight_compounded_pct'])} | {_signed(full['maximum_drawdown_pct'])} | {train['closed_count']}/{_fmt(train['win_rate_pct'])}% | {holdout['closed_count']}/{_fmt(holdout['win_rate_pct'])}% | {result['covered_months']} | {result['status']} |"
        )
    lines.extend(_render_quality_expansion_ledger(candidate_frame))
    lines.extend(_render_key_factor_months(results))
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- 动态席位若只在事后映射涨幅有效、但不能提高 D-1 正式候选质量，不进入打板规则。",
            "- 3-7 月与既有 806 日均已查看；本报告只生成下一前向假设，不承担生产晋级。",
            "- 本研究生成器不修改当前 `limit-up-core-abc-v1` 正式合同、页面或下单链。",
            "",
        ]
    )
    return "\n".join(lines)


def _monthly_leader_summary(
    rows: pd.DataFrame,
    accepted_roles: set[str],
) -> str:
    selected = rows.loc[
        rows["leader_roles"].map(
            lambda values: bool(set(_string_sequence(values)) & accepted_roles)
        )
    ]
    if selected.empty:
        return ""
    summary = (
        selected.groupby(["vt_symbol", "name"], sort=False)
        .agg(
            leader_days=("trade_date", "nunique"),
            waves=("wave_id", "nunique"),
            max_score=("leadership_score", "max"),
        )
        .reset_index()
        .sort_values(["leader_days", "max_score"], ascending=False)
        .head(12)
    )
    return "、".join(
        f"{row.name}({int(row.leader_days)}/{int(row.waves)})"
        for row in summary.itertuples()
    )


def _render_key_factor_months(
    results: Mapping[str, Mapping[str, object]],
) -> list[str]:
    lines = [
        "",
        "## Key factor monthly breakdown",
        "",
        "| 因子 | 月份 | 闭合 | 胜率 | 均值 |",
        "|---|---|---:|---:|---:|",
    ]
    names = (
        "first_board_low_position_follower",
        "low_position_follower_in_diffusion",
        "turnover_capacity_ge_080_reference",
        "turnover_capacity_low_position_follower",
        "turnover_capacity_low_position_follower_in_diffusion",
        "mainline_turnover_ge_080_low_position_follower",
        "quality_reconstruction_core",
        "quality_core_wave_early_expansion",
        "quality_core_active_pre_divergence",
        "quality_core_in_divergence_or_ebb",
    )
    appended = False
    for name in names:
        result = results.get(name) or {}
        monthly = result.get("monthly") or {}
        if not isinstance(monthly, Mapping):
            continue
        for month, summary in monthly.items():
            if not isinstance(summary, Mapping):
                continue
            lines.append(
                f"| {name} | {month} | {_integer(summary.get('closed_count'))} | {_fmt(summary.get('win_rate_pct'))}% | {_signed(summary.get('average_return_pct'))} |"
            )
            appended = True
    if not appended:
        lines.append("| - | - | 0 | - | - |")
    return lines


def _render_quality_expansion_ledger(frame: pd.DataFrame) -> list[str]:
    lines = [
        "",
        "## Quality-core expansion timing ledger",
        "",
        "以下股票名和概念名只用于逐笔审计；规则只读取 D-1 数值字段。概率引导者是当日动态席位，不是事后永久龙头。",
        "",
        "| 日期 | 候选 | lane | 动态概念 | D-1阶段 | 扩散年龄 | 扩散脉冲 | 概率引导者 | D+1净收益 |",
        "|---|---|---|---|---|---:|---|---|---:|",
    ]
    if frame.empty:
        lines.append("| - | - | - | - | - | - | - | - | - |")
        return lines
    limit_count = pd.to_numeric(
        frame.get("prior_limit_count_126"), errors="coerce"
    )
    industry_turnover = pd.to_numeric(
        frame.get("prior_industry_turnover_ratio_5d"), errors="coerce"
    )
    selected = frame.loc[
        limit_count.between(2, 6) & industry_turnover.ge(1.0)
    ].sort_values(["trade_date", "signal_time", "pool_rank", "vt_symbol"])
    if selected.empty:
        lines.append("| - | - | - | - | - | - | - | - | - |")
        return lines
    for row in selected.to_dict("records"):
        leader = row.get("prior_wave_leader_symbol") or "-"
        expansion_age = _optional_integer(
            row.get("prior_wave_expansion_age_sessions")
        )
        lines.append(
            f"| {row.get('trade_date')} | {row.get('name')} `{row.get('vt_symbol')}` | {row.get('lane')} | "
            f"{row.get('prior_wave_sector_name') or row.get('prior_wave_sector_id') or '-'} | "
            f"{row.get('prior_wave_phase') or '-'} | {expansion_age if expansion_age is not None else '-'} | "
            f"{'是' if row.get('prior_wave_expansion_impulse') is True else '否'} | {leader} | "
            f"{_signed(row.get('return_pct'))} |"
        )
    return lines


def _render_named_case_wave_detail(ranks: pd.DataFrame) -> list[str]:
    lines = [
        "",
        "## Named-case wave detail",
        "",
        "主线强区指该股票获得动态前三席位时，概念当日主线分位至少为 `0.80`。",
        "",
        "| 股票 | 概念 | 波段 | 首次席位 | 最后席位 | 主线最高分位 | 席位 | 角色 |",
        "|---|---|---|---|---|---:|---|---|",
    ]
    if ranks.empty:
        lines.append("| - | - | - | - | - | - | - | - |")
        return lines
    for name in AUDIT_NAMES:
        named_rows = ranks.loc[
            ranks.get("name", pd.Series("", index=ranks.index)).eq(name)
        ]
        for wave_id, rows in named_rows.groupby("wave_id", sort=False):
            ordered = rows.sort_values("trade_date")
            mainline = pd.to_numeric(
                ordered.get("wave_mainline_percentile"), errors="coerce"
            ).max()
            rank_values = sorted(
                {
                    int(value)
                    for value in pd.to_numeric(
                        ordered["leader_rank"], errors="coerce"
                    ).dropna()
                }
            )
            roles = sorted(
                {
                    role
                    for values in ordered["leader_roles"]
                    for role in _string_sequence(values)
                }
            )
            first = ordered.iloc[0]
            lines.append(
                f"| {name} | {first.get('sector_name') or first.get('sector_id')} | {wave_id} | {ordered['trade_date'].min()} | {ordered['trade_date'].max()} | {_fmt(mainline)} | {','.join(map(str, rank_values)) or '-'} | {','.join(roles) or '-'} |"
            )
    if len(lines) == 7:
        lines.append("| - | - | - | - | - | - | - | - |")
    return lines


def _render_wave_ledger(
    waves: pd.DataFrame,
    ranks: pd.DataFrame,
) -> list[str]:
    lines = [
        "",
        "## Full dynamic wave ledger",
        "",
        "龙一迁移按交易日压缩连续重复；各席位列按占席交易日数排序，保留波段内所有主要任职者。",
        "`open` 只表示该波段最后一条记录不是连续两日共同转弱形成的 `ebb`；它可能已被同概念的新波段替代，不等于研究截止日仍实时活跃。",
        "",
        "| 波段 | 概念 | 开始 | 结束 | 状态 | 点火 | 阶段路径 | 主线最高分位/强区日 | 龙一主要席位 | 龙二主要席位 | 龙三主要席位 | 龙一迁移 | 成员证据 |",
        "|---|---|---|---|---|---|---|---:|---|---|---|---|---|",
    ]
    if waves.empty:
        lines.append("| - | - | - | - | - | - | - | - | - | - | - | - | - |")
        return lines
    seat_summaries, leader_migrations = _wave_seat_summaries(ranks)
    for wave_id, rows in waves.groupby("wave_id", sort=False):
        ordered = rows.sort_values("trade_date")
        first = ordered.iloc[0]
        phases = " -> ".join(
            _ordered_unique(str(value) for value in ordered["wave_phase"])
        )
        mainline = pd.to_numeric(
            ordered.get("mainline_percentile"), errors="coerce"
        )
        evidence = ",".join(
            _ordered_unique(
                str(value)
                for value in ordered.get(
                    "membership_evidence_level",
                    pd.Series("unavailable", index=ordered.index),
                )
            )
        )
        status = "closed" if str(ordered.iloc[-1].get("wave_phase")) == "ebb" else "open"
        lines.append(
            f"| {wave_id} | {first.get('sector_name') or first.get('sector_id')} | {ordered['trade_date'].min()} | {ordered['trade_date'].max()} | {status} | {first.get('wave_start_reason') or '-'} | {phases or '-'} | {_fmt(mainline.max())}/{int(mainline.ge(WAVE_IGNITION_PERCENTILE).sum())} | {seat_summaries.get((str(wave_id), 1), '-')} | {seat_summaries.get((str(wave_id), 2), '-')} | {seat_summaries.get((str(wave_id), 3), '-')} | {leader_migrations.get(str(wave_id), '-')} | {evidence or '-'} |"
        )
    return lines


def _wave_seat_summaries(
    ranks: pd.DataFrame,
) -> tuple[dict[tuple[str, int], str], dict[str, str]]:
    if ranks.empty:
        return {}, {}
    ranked = ranks.loc[
        pd.to_numeric(ranks.get("leader_rank"), errors="coerce").isin([1, 2, 3])
    ].copy()
    if ranked.empty:
        return {}, {}
    ranked["leader_rank"] = pd.to_numeric(
        ranked["leader_rank"], errors="coerce"
    ).astype(int)
    stats = (
        ranked.groupby(
            ["wave_id", "leader_rank", "vt_symbol", "name"],
            sort=False,
        )
        .agg(
            seat_days=("trade_date", "nunique"),
            first_date=("trade_date", "min"),
            max_score=("leadership_score", "max"),
        )
        .reset_index()
    )
    seat_summaries: dict[tuple[str, int], str] = {}
    for (wave_id, rank), rows in stats.groupby(
        ["wave_id", "leader_rank"], sort=False
    ):
        ordered = rows.sort_values(
            ["seat_days", "max_score", "first_date", "vt_symbol"],
            ascending=[False, False, True, True],
        )
        seat_summaries[(str(wave_id), int(rank))] = "、".join(
            f"{row.name}({int(row.seat_days)}日)" for row in ordered.itertuples()
        )
    leader_migrations: dict[str, str] = {}
    leader_rows = ranked.loc[ranked["leader_rank"].eq(1)].sort_values(
        ["wave_id", "trade_date", "vt_symbol"]
    )
    for wave_id, rows in leader_rows.groupby("wave_id", sort=False):
        names = _compress_consecutive(str(value) for value in rows["name"])
        leader_migrations[str(wave_id)] = " -> ".join(names) or "-"
    return seat_summaries, leader_migrations


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _compress_consecutive(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and (not result or value != result[-1]):
            result.append(value)
    return result


def _mapping_groups(mappings: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    if mappings.empty:
        return [("all", mappings), ("rank_2", mappings), ("rank_3", mappings)]
    tenure = pd.to_numeric(
        mappings.get("leader_rank_1_tenure_sessions"), errors="coerce"
    )
    phase = mappings.get("wave_phase", pd.Series("", index=mappings.index)).fillna("")
    mainline = pd.to_numeric(
        mappings.get("wave_mainline_percentile"), errors="coerce"
    )
    leader_roles = mappings.get(
        "leader_roles",
        pd.Series([[] for _ in range(len(mappings))], index=mappings.index),
    )
    trend_capacity = leader_roles.map(
        lambda values: {"trend_leader", "capacity_leader"}.issubset(
            _string_sequence(values)
        )
    )
    return [
        ("all", mappings),
        ("rank_2", mappings.loc[mappings["rank_at_response"].eq(2)]),
        ("rank_3", mappings.loc[mappings["rank_at_response"].eq(3)]),
        ("leader_tenure_1d", mappings.loc[tenure.eq(1)]),
        ("leader_tenure_2d", mappings.loc[tenure.eq(2)]),
        ("leader_tenure_3d", mappings.loc[tenure.eq(3)]),
        ("leader_tenure_ge_4d", mappings.loc[tenure.ge(4)]),
        ("leader_trend_capacity", mappings.loc[trend_capacity]),
        (
            "wave_acceleration_diffusion",
            mappings.loc[phase.isin(["acceleration", "diffusion"])],
        ),
        (
            "wave_divergence_ebb",
            mappings.loc[phase.isin(["divergence", "ebb"])],
        ),
        ("wave_mainline_ge_080", mappings.loc[mainline.ge(0.80)]),
    ]


def _up_rate(frame: pd.DataFrame, field: str) -> str:
    if frame.empty or field not in frame:
        return "-"
    values = pd.to_numeric(frame[field], errors="coerce").dropna()
    if values.empty:
        return "-"
    return f"{values.gt(0).mean() * 100.0:.4f}%"


def _factor_status(
    full: Mapping[str, object],
    discovery: Mapping[str, object],
    holdout: Mapping[str, object],
    covered_months: int,
) -> str:
    closed = _integer(full.get("closed_count"))
    win_rate = _number(full.get("win_rate_pct"))
    discovery_rate = _number(discovery.get("win_rate_pct"))
    holdout_rate = _number(holdout.get("win_rate_pct"))
    if closed < 30 or covered_months < 3:
        return "small_sample"
    split_rates = (discovery_rate, holdout_rate)
    if (
        win_rate is not None
        and win_rate >= 60.0
        and all(rate is not None and rate >= 60.0 for rate in split_rates)
    ):
        return "candidate_for_forward_freeze"
    if win_rate is not None and win_rate >= 60.0:
        return "time_split_reversal"
    return "below_60_or_unstable"


def _string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),) if value not in (None, "") else ()


def _stock_bar_universe(inputs: CapitalMainlineInputs) -> str:
    event_coverage = inputs.coverage.get("event_coverage") or {}
    if not isinstance(event_coverage, Mapping):
        event_coverage = {}
    return str(
        inputs.coverage.get("stock_bar_universe")
        or event_coverage.get("stock_bar_universe")
        or "limit_event_symbols"
    )


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _signed(value: object) -> str:
    number = _number(value)
    return f"{number:+.4f}%" if number is not None else "-"


def _wave_context_priority(
    member: Mapping[str, object],
    leader: Mapping[str, object],
) -> tuple[int, int, int, int, int, float, float, float, float, float, str]:
    phase = str(member.get("wave_phase") or "")
    return (
        int(bool(member.get("wave_expansion_impulse"))),
        int(bool(member.get("wave_early_expansion"))),
        int(bool(member.get("wave_breadth_rising"))),
        int(phase in {"diffusion", "acceleration"}),
        int(bool(leader)),
        _number(member.get("wave_mainline_percentile")) or 0.0,
        _number(member.get("wave_turnover_strength")) or 0.0,
        _number(member.get("wave_ladder_strength")) or 0.0,
        _number(member.get("wave_index_strength")) or 0.0,
        _number(leader.get("leadership_score")) or 0.0,
        str(member.get("sector_id") or ""),
    )


def _group_rank(
    frame: pd.DataFrame,
    values: pd.Series,
    group_fields: Sequence[str],
    *,
    ascending: bool,
    pct: bool,
    method: str,
) -> pd.Series:
    groupers = [frame[field] for field in group_fields]
    return values.groupby(groupers, sort=False, dropna=False).rank(
        ascending=ascending,
        pct=pct,
        method=method,
    )


def _group_percentile(
    frame: pd.DataFrame,
    field: str,
    group_fields: Sequence[str],
) -> pd.Series:
    values = pd.to_numeric(frame.get(field), errors="coerce")
    return _group_rank(
        frame,
        values,
        group_fields,
        ascending=True,
        pct=True,
        method="average",
    )


def _consecutive_true_counts(
    frame: pd.DataFrame,
    active: pd.Series,
    group_fields: Sequence[str],
) -> pd.Series:
    active = active.fillna(False).astype(bool)
    groupers = [frame[field] for field in group_fields]
    inactive_run = (~active).groupby(groupers, sort=False, dropna=False).cumsum()
    counts = active.astype(int).groupby(
        [*groupers, inactive_run],
        sort=False,
        dropna=False,
    ).cumsum()
    return counts.where(active, 0).astype(int)


def _forward_return(
    close_lookup: Mapping[tuple[str, date], float | None],
    trade_dates: Sequence[date],
    response_position: int | None,
    symbol: str,
    response_close: float | None,
    horizon: int,
) -> float | None:
    if response_position is None or response_close is None or response_close <= 0:
        return None
    target_position = response_position + horizon
    if target_position >= len(trade_dates):
        return None
    target_close = close_lookup.get((symbol, trade_dates[target_position]))
    return _return_pct(response_close, target_close)


def _return_pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def _integer(value: object, default: int = 0) -> int:
    number = _number(value)
    return int(number) if number is not None else default


def _optional_integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


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
    from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
        build_candidate_feature_frame,
    )
    from alphaagent.server.services.limit_up.capital_mainline_repository import (
        load_capital_mainline_inputs,
    )
    from alphaagent.server.services.limit_up.capital_mainline_research import (
        build_membership_contexts,
        build_research_bundle,
    )
    from alphaagent.server.services.limit_up.quality_reconstruction import (
        QUALITY_FIELDS,
        build_quality_reconstruction_frame,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    started_at = perf_counter()
    inputs = load_capital_mainline_inputs(
        arguments.start,
        arguments.end,
        include_prior_formal_evidence=True,
        include_stock_bars=True,
        include_all_concept_members=True,
    )
    _print_progress(
        started_at,
        "inputs_loaded",
        stock_bars=len(inputs.stock_bars),
        memberships=len(inputs.memberships) + len(inputs.current_memberships),
    )
    bundle = build_research_bundle(
        inputs,
        start=arguments.start,
        end=arguments.end,
    )
    _print_progress(
        started_at,
        "research_bundle_built",
        concept_days=len(bundle["concept_panel"]),
    )
    waves = segment_concept_waves(bundle["concept_panel"])
    _print_progress(
        started_at,
        "waves_segmented",
        wave_days=len(waves),
        waves=waves["wave_id"].nunique() if not waves.empty else 0,
    )
    features = build_wave_member_features(
        inputs,
        waves,
        build_membership_contexts(inputs),
    )
    _print_progress(started_at, "member_features_built", rows=len(features))
    ranks = rank_dynamic_wave_leaders(features)
    _print_progress(started_at, "leaders_ranked", rows=len(ranks))
    mappings = build_dynamic_leader_mappings(
        ranks,
        pd.DataFrame.from_records(inputs.stock_bars),
        inputs.trade_dates,
    )
    candidates = build_candidate_feature_frame(
        inputs,
        bundle,
        candidate_scope="formal_recommendations",
    )
    quality = build_quality_reconstruction_frame(
        inputs.formal_candidate_days,
        start=arguments.start,
        end=arguments.end,
    )
    candidates = candidates.merge(
        quality[["trade_date", "vt_symbol", *QUALITY_FIELDS]],
        on=["trade_date", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )
    attached = attach_dynamic_wave_features(candidates, ranks, inputs.trade_dates)
    _print_progress(
        started_at,
        "formal_candidates_attached",
        candidates=len(attached),
    )
    report = render_dynamic_wave_report(inputs, waves, ranks, mappings, attached)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8")
    _print_progress(started_at, "report_written", lines=len(report.splitlines()))


def _print_progress(
    started_at: float,
    stage: str,
    **counts: object,
) -> None:
    details = " ".join(f"{name}={value}" for name, value in counts.items())
    print(
        f"[dynamic-wave] stage={stage} elapsed={perf_counter() - started_at:.1f}s {details}".rstrip(),
        flush=True,
    )


if __name__ == "__main__":
    main()
