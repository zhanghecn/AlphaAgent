"""Daily dynamic-concept, capital-cycle and leader-ladder research."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.limit_up import sentiment
from alphaagent.server.services.limit_up.capital_mainline_contract import (
    CapitalRole,
    ConceptCyclePhase,
    EvidenceLevel,
    MarketCyclePhase,
)
from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CapitalMainlineInputs,
    flow_is_known_for_next_session,
    fund_flow_known_at,
    load_capital_mainline_inputs,
    membership_rows_for_date,
)
from alphaagent.server.services.limit_up.concept_resonance import is_execution_concept
from alphaagent.server.services.limit_up.domain import is_eligible_main_board


STUDY_VERSION = "limit-up-capital-mainline-v1"
IGNITION_PERCENTILE = 0.80
CONFIRMATION_PERCENTILE = 0.65
ACCELERATION_PERCENTILE = 0.80
DIVERGENCE_PERCENTILE = 0.55
PRIMARY_ATTRIBUTION_MARGIN = 0.04


@dataclass(frozen=True, slots=True)
class MembershipContext:
    evidence_level: EvidenceLevel
    snapshot_date: date | None
    by_symbol: dict[str, tuple[str, ...]]
    by_sector: dict[str, frozenset[str]]
    member_counts: dict[str, int]
    sector_names: dict[str, str]


def build_research_bundle(
    inputs: CapitalMainlineInputs,
    *,
    start: date,
    end: date,
) -> dict[str, pd.DataFrame]:
    membership_contexts = build_membership_contexts(inputs)
    event_ledger = build_event_ledger(inputs)
    concept_panel, event_links = build_dynamic_concept_panel(
        inputs,
        event_ledger=event_ledger,
        membership_contexts=membership_contexts,
        start=start,
        end=end,
    )
    market_cycles = discover_market_cycles(inputs)
    concept_cycles = discover_concept_cycles(concept_panel, market_cycles)
    roles = rank_cycle_roles(
        concept_panel,
        concept_cycles,
        event_links,
        event_ledger,
    )
    return {
        "concept_panel": concept_panel,
        "market_cycles": market_cycles,
        "concept_cycles": concept_cycles,
        "event_ledger": event_ledger,
        "event_links": event_links,
        "roles": roles,
    }


def build_membership_contexts(
    inputs: CapitalMainlineInputs,
) -> dict[date, MembershipContext]:
    contexts: dict[date, MembershipContext] = {}
    cached: dict[tuple[EvidenceLevel, date | None], MembershipContext] = {}
    for trade_date in inputs.trade_dates:
        rows, evidence, snapshot_date = membership_rows_for_date(inputs, trade_date)
        cache_key = (evidence, snapshot_date)
        if cache_key not in cached:
            by_symbol: dict[str, list[str]] = defaultdict(list)
            by_sector: dict[str, set[str]] = defaultdict(set)
            sector_names: dict[str, str] = {}
            for row in rows:
                sector_id = str(row.get("sector_id") or "")
                sector_name = str(row.get("sector_name") or sector_id)
                symbol = str(row.get("vt_symbol") or "").upper()
                if (
                    not sector_id
                    or not symbol
                    or not is_execution_concept(sector_name)
                ):
                    continue
                by_symbol[symbol].append(sector_id)
                by_sector[sector_id].add(symbol)
                sector_names[sector_id] = sector_name
            cached[cache_key] = MembershipContext(
                evidence_level=evidence,
                snapshot_date=snapshot_date,
                by_symbol={
                    symbol: tuple(sorted(set(sector_ids)))
                    for symbol, sector_ids in by_symbol.items()
                },
                by_sector={
                    sector_id: frozenset(symbols)
                    for sector_id, symbols in by_sector.items()
                },
                member_counts={
                    str(row.get("sector_id") or ""): int(
                        _number(row.get("member_count")) or 0
                    )
                    for row in inputs.membership_counts
                    if (
                        _date_value(row.get("snapshot_date")) == snapshot_date
                        if snapshot_date is not None
                        else row.get("snapshot_date") is None
                    )
                },
                sector_names=sector_names,
            )
        contexts[trade_date] = cached[cache_key]
    return contexts


def build_event_ledger(inputs: CapitalMainlineInputs) -> pd.DataFrame:
    rows = [
        {
            **dict(event),
            "vt_symbol": str(event.get("vt_symbol") or "").upper(),
            "trade_date": _date_value(event.get("trade_date")),
            "is_limit_up": bool(event.get("is_sealed")),
        }
        for event in inputs.limit_up_events
        if is_eligible_main_board(
            str(event.get("vt_symbol") or ""),
            str(event.get("name") or ""),
        )
        and _date_value(event.get("trade_date")) in set(inputs.trade_dates)
    ]
    if not rows:
        return pd.DataFrame()
    calculated = sentiment.calculate_effective_board_streaks(rows, inputs.trade_dates)
    sealed_dates: dict[str, set[date]] = defaultdict(set)
    for row in calculated:
        if bool(row["is_limit_up"]):
            sealed_dates[str(row["vt_symbol"])].add(row["trade_date"])
    date_positions = {value: index for index, value in enumerate(inputs.trade_dates)}
    records: list[dict[str, object]] = []
    for row in calculated:
        trade_date = row["trade_date"]
        symbol = str(row["vt_symbol"])
        streak = int(row.get("limit_up_streak") or 0)
        position = date_positions[trade_date]
        five_dates = inputs.trade_dates[max(0, position - 4) : position + 1]
        sealed_in_five = sum(value in sealed_dates[symbol] for value in five_dates)
        previous_date = inputs.trade_dates[position - 1] if position else None
        if bool(row["is_limit_up"]) and streak == 3:
            board_pattern = CapitalRole.CONTINUOUS_TWO_TO_THREE.value
        elif (
            bool(row["is_limit_up"])
            and previous_date is not None
            and previous_date not in sealed_dates[symbol]
            and sealed_in_five == 3
        ):
            board_pattern = CapitalRole.SHORT_CYCLE_REBOARD_THREE.value
        elif bool(row["is_limit_up"]) and streak == 1:
            board_pattern = CapitalRole.IGNITION_CANDIDATE.value
        elif bool(row["is_limit_up"]) and streak >= 4:
            board_pattern = "higher_board_continuation"
        else:
            board_pattern = "failed_touch"
        records.append(
            {
                **row,
                "board_pattern": board_pattern,
                "sealed_in_five": sealed_in_five,
            }
        )
    frame = pd.DataFrame.from_records(records)
    return frame.sort_values(["trade_date", "vt_symbol"]).reset_index(drop=True)


def build_dynamic_concept_panel(
    inputs: CapitalMainlineInputs,
    *,
    event_ledger: pd.DataFrame,
    membership_contexts: Mapping[date, MembershipContext],
    start: date,
    end: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = pd.DataFrame.from_records(inputs.concept_bars)
    if bars.empty:
        return pd.DataFrame(), pd.DataFrame()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    bars = bars.loc[
        bars["sector_name"].map(is_execution_concept)
        & bars["close_price"].gt(0)
    ].copy()
    bars = bars.sort_values(["sector_id", "trade_date"]).reset_index(drop=True)
    grouped = bars.groupby("sector_id", sort=False)
    for sessions in (1, 3, 5, 10):
        bars[f"return_{sessions}d_pct"] = (
            grouped["close_price"].pct_change(sessions, fill_method=None) * 100.0
        )
    bars["turnover_mean_5"] = grouped["turnover"].transform(
        lambda values: values.rolling(5, min_periods=3).mean()
    )
    bars["turnover_mean_prev20"] = grouped["turnover"].transform(
        lambda values: values.shift(5).rolling(20, min_periods=10).mean()
    )
    bars["turnover_expansion_5_20"] = (
        bars["turnover_mean_5"] / bars["turnover_mean_prev20"]
    )
    bars["turnover_expansion_1_20"] = (
        bars["turnover"]
        / grouped["turnover"].transform(
            lambda values: values.shift(1).rolling(20, min_periods=10).median()
        )
    )
    for field in (
        "return_1d_pct",
        "return_3d_pct",
        "return_5d_pct",
        "return_10d_pct",
        "turnover_expansion_1_20",
        "turnover_expansion_5_20",
    ):
        bars[f"{field}_pctile"] = bars.groupby("trade_date")[field].rank(
            pct=True,
            method="average",
        )
    bars["market_median_return_1d_pct"] = bars.groupby("trade_date")[
        "return_1d_pct"
    ].transform("median")
    bars["excess_return_1d_pct"] = (
        bars["return_1d_pct"] - bars["market_median_return_1d_pct"]
    )
    bars["index_strength"] = bars[
        [
            "return_1d_pct_pctile",
            "return_3d_pct_pctile",
            "return_5d_pct_pctile",
            "return_10d_pct_pctile",
        ]
    ].mean(axis=1, skipna=True)
    bars["turnover_strength"] = bars[
        ["turnover_expansion_1_20_pctile", "turnover_expansion_5_20_pctile"]
    ].mean(axis=1, skipna=True)

    event_links = _build_event_links(event_ledger, membership_contexts)
    ladder = _concept_ladder_metrics(event_links, membership_contexts)
    panel = bars.merge(ladder, on=["trade_date", "sector_id"], how="left")
    panel = _merge_fund_flows(panel, inputs)
    numeric_defaults = {
        "eligible_member_count": np.nan,
        "sealed_count": 0.0,
        "first_board_count": 0.0,
        "one_to_two_count": 0.0,
        "two_to_three_count": 0.0,
        "reboard_three_count": 0.0,
        "unique_sealed_credit": 0.0,
        "unique_follower_count": 0.0,
    }
    for field, value in numeric_defaults.items():
        panel[field] = panel[field].fillna(value)
    panel["sealed_ratio"] = panel["sealed_count"] / panel[
        "eligible_member_count"
    ].replace(0, np.nan)
    panel["first_board_ratio"] = panel["first_board_count"] / panel[
        "eligible_member_count"
    ].replace(0, np.nan)
    panel["unique_follower_ratio"] = panel["unique_follower_count"] / panel[
        "eligible_member_count"
    ].replace(0, np.nan)
    for field in (
        "sealed_ratio",
        "first_board_ratio",
        "one_to_two_count",
        "two_to_three_count",
        "unique_sealed_credit",
        "unique_follower_ratio",
    ):
        panel[f"{field}_pctile"] = panel.groupby("trade_date")[field].rank(
            pct=True,
            method="average",
        )
    panel["ladder_strength"] = panel[
        [
            "sealed_ratio_pctile",
            "first_board_ratio_pctile",
            "one_to_two_count_pctile",
            "two_to_three_count_pctile",
            "unique_sealed_credit_pctile",
        ]
    ].mean(axis=1, skipna=True)
    panel["base_mainline_score"] = (
        panel["index_strength"].fillna(0.0) * 0.40
        + panel["turnover_strength"].fillna(0.0) * 0.20
        + panel["ladder_strength"].fillna(0.0) * 0.40
    )
    has_flow = panel["flow_known_next_session"].fillna(False).astype(bool)
    panel["mainline_score"] = panel["base_mainline_score"]
    panel.loc[has_flow, "mainline_score"] = (
        panel.loc[has_flow, "index_strength"].fillna(0.0) * 0.30
        + panel.loc[has_flow, "turnover_strength"].fillna(0.0) * 0.15
        + panel.loc[has_flow, "ladder_strength"].fillna(0.0) * 0.35
        + panel.loc[has_flow, "flow_strength"].fillna(0.0) * 0.20
    )
    panel.loc[panel["capital_state"].eq("divergent"), "mainline_score"] -= 0.10
    panel["mainline_score"] = panel["mainline_score"].clip(0.0, 1.0)
    panel["mainline_percentile"] = panel.groupby("trade_date")[
        "mainline_score"
    ].rank(pct=True, method="average")
    panel["mainline_rank"] = panel.groupby("trade_date")["mainline_score"].rank(
        ascending=False,
        method="min",
    )
    panel = panel.loc[
        panel["trade_date"].between(start, end)
    ].sort_values(["trade_date", "mainline_rank", "sector_id"])
    return panel.reset_index(drop=True), event_links


def discover_market_cycles(inputs: CapitalMainlineInputs) -> pd.DataFrame:
    points = pd.DataFrame.from_records(inputs.sentiment_points)
    if points.empty:
        return pd.DataFrame()
    date_field = "date" if "date" in points else "trade_date"
    points["trade_date"] = pd.to_datetime(points[date_field]).dt.date
    points = points.sort_values("trade_date").reset_index(drop=True)
    points["sentiment_score"] = pd.to_numeric(
        points.get("score"), errors="coerce"
    ).fillna(0.0)
    points["score_change"] = points["sentiment_score"].diff()
    cycle_number = 1
    cycle_start = points.iloc[0]["trade_date"]
    previous_phase: MarketCyclePhase | None = None
    records: list[dict[str, object]] = []
    for row in points.to_dict("records"):
        score = float(row.get("sentiment_score") or 0.0)
        delta = _number(row.get("score_change")) or 0.0
        raw_phase = str(row.get("phase") or "").lower()
        if raw_phase == "ice" or score < 30:
            phase = MarketCyclePhase.ICE
        elif previous_phase in {MarketCyclePhase.ICE, MarketCyclePhase.EBB} and delta >= 4:
            phase = MarketCyclePhase.REPAIR
        elif previous_phase is MarketCyclePhase.DIVERGENCE and delta >= 4:
            phase = MarketCyclePhase.REFLUX
        elif delta <= -6 or raw_phase == "divergence":
            phase = MarketCyclePhase.DIVERGENCE
        elif score >= 70 and delta >= 0:
            phase = MarketCyclePhase.ACCELERATION
        elif score >= 50:
            phase = MarketCyclePhase.LAUNCH
        elif delta < 0 or raw_phase == "ebb":
            phase = MarketCyclePhase.EBB
        else:
            phase = MarketCyclePhase.REPAIR
        if (
            previous_phase in {MarketCyclePhase.ICE, MarketCyclePhase.EBB}
            and phase in {MarketCyclePhase.REPAIR, MarketCyclePhase.LAUNCH}
            and records
        ):
            cycle_number += 1
            cycle_start = row["trade_date"]
        cycle_id = f"MC-{cycle_number:03d}:{cycle_start.isoformat()}"
        records.append(
            {
                **row,
                "market_cycle_id": cycle_id,
                "market_phase": phase.value,
            }
        )
        previous_phase = phase
    return pd.DataFrame.from_records(records)


def discover_concept_cycles(
    panel: pd.DataFrame,
    market_cycles: pd.DataFrame,
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    market_by_date = (
        market_cycles.set_index("trade_date")["market_cycle_id"].to_dict()
        if not market_cycles.empty
        else {}
    )
    records: list[dict[str, object]] = []
    for sector_id, values in panel.groupby("sector_id", sort=True):
        active = False
        cycle_number = 0
        cycle_id = ""
        cycle_start: date | None = None
        previous_phase: ConceptCyclePhase | None = None
        previous_score: float | None = None
        low_days = 0
        running_peak = 0.0
        for row in values.sort_values("trade_date").to_dict("records"):
            score = _number(row.get("mainline_percentile")) or 0.0
            first_boards = int(_number(row.get("first_board_count")) or 0)
            sealed_count = int(_number(row.get("sealed_count")) or 0)
            one_to_two = int(_number(row.get("one_to_two_count")) or 0)
            two_to_three = int(_number(row.get("two_to_three_count")) or 0)
            ignition = (
                score >= IGNITION_PERCENTILE
                and first_boards >= 1
                and (_number(row.get("index_strength")) or 0.0) >= 0.55
            )
            if not active:
                if not ignition:
                    continue
                active = True
                cycle_number += 1
                cycle_start = row["trade_date"]
                cycle_id = f"{sector_id}:{cycle_start.isoformat()}:{cycle_number}"
                phase = ConceptCyclePhase.IGNITION
                low_days = 0
                running_peak = score
            else:
                running_peak = max(running_peak, score)
                low_days = low_days + 1 if score < DIVERGENCE_PERCENTILE else 0
                capital_state = str(row.get("capital_state") or "")
                if low_days >= 2:
                    phase = ConceptCyclePhase.EBB
                elif (
                    previous_phase in {ConceptCyclePhase.DIVERGENCE, ConceptCyclePhase.EBB}
                    and score >= 0.70
                    and first_boards >= 1
                ):
                    phase = ConceptCyclePhase.REFLUX
                elif capital_state == "divergent" or score < DIVERGENCE_PERCENTILE:
                    phase = ConceptCyclePhase.DIVERGENCE
                elif (
                    score >= ACCELERATION_PERCENTILE
                    and (two_to_three >= 1 or (previous_score is not None and score > previous_score + 0.08))
                ):
                    phase = ConceptCyclePhase.ACCELERATION
                elif one_to_two >= 1 or sealed_count >= 2:
                    phase = (
                        ConceptCyclePhase.CONFIRMATION
                        if previous_phase is ConceptCyclePhase.IGNITION
                        else ConceptCyclePhase.DIFFUSION
                    )
                elif score >= CONFIRMATION_PERCENTILE:
                    phase = ConceptCyclePhase.DIFFUSION
                else:
                    phase = ConceptCyclePhase.DIVERGENCE
            records.append(
                {
                    **row,
                    "market_cycle_id": market_by_date.get(row["trade_date"]),
                    "concept_cycle_id": cycle_id,
                    "concept_cycle_start": cycle_start,
                    "concept_phase": phase.value,
                    "running_peak_percentile": running_peak,
                }
            )
            previous_phase = phase
            previous_score = score
            if phase is ConceptCyclePhase.EBB:
                active = False
                previous_phase = None
                previous_score = None
                low_days = 0
    return pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "mainline_rank", "sector_id"]
    ).reset_index(drop=True)


def select_primary_concept(
    candidates: Sequence[Mapping[str, object]],
    *,
    margin: float = PRIMARY_ATTRIBUTION_MARGIN,
) -> str | None:
    if not candidates:
        return None
    scored = sorted(
        (
            (
                _primary_concept_score(candidate),
                str(candidate.get("sector_id") or ""),
            )
            for candidate in candidates
            if candidate.get("sector_id")
        ),
        reverse=True,
    )
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < margin:
        return None
    return scored[0][1]


def pairwise_aliases(
    members_by_sector: Mapping[str, set[str] | frozenset[str]],
    return_history: pd.DataFrame,
    *,
    min_jaccard: float = 0.35,
    min_correlation: float = 0.80,
) -> list[tuple[str, str]]:
    aliases: list[tuple[str, str]] = []
    sector_ids = sorted(members_by_sector)
    for left_index, left_id in enumerate(sector_ids):
        left = set(members_by_sector[left_id])
        for right_id in sector_ids[left_index + 1 :]:
            right = set(members_by_sector[right_id])
            union = left | right
            if not union or len(left & right) < 5:
                continue
            if len(left & right) / len(union) < min_jaccard:
                continue
            correlation = _pair_return_correlation(return_history, left_id, right_id)
            if correlation is not None and correlation >= min_correlation:
                aliases.append((left_id, right_id))
    return aliases


def rank_cycle_roles(
    concept_panel: pd.DataFrame,
    concept_cycles: pd.DataFrame,
    event_links: pd.DataFrame,
    event_ledger: pd.DataFrame,
) -> pd.DataFrame:
    if concept_cycles.empty or event_links.empty:
        return pd.DataFrame()
    cycle_columns = [
        "trade_date",
        "sector_id",
        "sector_name",
        "market_cycle_id",
        "concept_cycle_id",
        "concept_cycle_start",
        "concept_phase",
        "mainline_score",
        "mainline_percentile",
        "index_strength",
        "ladder_strength",
        "flow_strength",
        "capital_state",
        "membership_evidence_level",
        "membership_snapshot_date",
        "sealed_count",
        "unique_follower_ratio",
    ]
    available = [column for column in cycle_columns if column in concept_cycles]
    joined = event_links.merge(
        concept_cycles[available],
        on=["trade_date", "sector_id"],
        how="inner",
        suffixes=("", "_cycle"),
    )
    if joined.empty:
        return joined
    primary_by_identity: dict[tuple[date, str], str | None] = {}
    for identity, rows in joined.groupby(["trade_date", "vt_symbol"], sort=False):
        primary_by_identity[identity] = select_primary_concept(rows.to_dict("records"))
    joined["primary_sector_id"] = [
        primary_by_identity[(row.trade_date, row.vt_symbol)]
        for row in joined.itertuples()
    ]
    joined["primary_attribution"] = np.where(
        joined["primary_sector_id"].isna(),
        "multi_theme_unresolved",
        np.where(
            joined["primary_sector_id"].eq(joined["sector_id"]),
            "primary",
            "secondary",
        ),
    )
    joined["turnover_value"] = pd.to_numeric(joined["turnover"], errors="coerce")
    joined["capacity_rank"] = joined.groupby(
        ["trade_date", "concept_cycle_id"]
    )["turnover_value"].rank(ascending=False, method="min")
    role_order = (
        joined.assign(
            _streak=pd.to_numeric(
                joined["limit_up_streak"], errors="coerce"
            ).fillna(0),
            _turnover=pd.to_numeric(joined["turnover"], errors="coerce").fillna(0),
        )
        .sort_values(
            [
                "trade_date",
                "concept_cycle_id",
                "_streak",
                "_turnover",
                "vt_symbol",
            ],
            ascending=[True, True, False, False, True],
        )
        .groupby(["trade_date", "concept_cycle_id"], sort=False)
        .cumcount()
        .add(1)
    )
    joined["role_order"] = role_order.reindex(joined.index).astype(int)
    next_streak = {
        (str(row.vt_symbol), row.trade_date): int(row.limit_up_streak)
        for row in event_ledger.itertuples()
        if bool(row.is_limit_up)
    }
    trade_dates = sorted(event_ledger["trade_date"].unique())
    next_date = {
        value: trade_dates[index + 1]
        for index, value in enumerate(trade_dates[:-1])
    }
    records: list[dict[str, object]] = []
    for row in joined.to_dict("records"):
        roles_asof: set[str] = set()
        roles_realized: set[str] = set()
        streak = int(_number(row.get("limit_up_streak")) or 0)
        order = int(_number(row.get("role_order")) or 0)
        phase = str(row.get("concept_phase") or "")
        if streak == 1 and phase == ConceptCyclePhase.IGNITION.value:
            roles_asof.add(CapitalRole.IGNITION_CANDIDATE.value)
        if order == 2:
            roles_asof.add(CapitalRole.LEADER_2.value)
        elif order == 3:
            roles_asof.add(CapitalRole.LEADER_3.value)
        if int(_number(row.get("capacity_rank")) or 0) == 1:
            roles_asof.add(CapitalRole.CAPACITY_CORE.value)
        if (
            streak == 1
            and row.get("trade_date") > row.get("concept_cycle_start")
            and phase not in {ConceptCyclePhase.IGNITION.value, ConceptCyclePhase.WATCH.value}
        ):
            roles_asof.add(CapitalRole.REPLENISHMENT.value)
        if row.get("board_pattern") == CapitalRole.CONTINUOUS_TWO_TO_THREE.value:
            roles_realized.add(CapitalRole.CONTINUOUS_TWO_TO_THREE.value)
        if row.get("board_pattern") == CapitalRole.SHORT_CYCLE_REBOARD_THREE.value:
            roles_realized.add(CapitalRole.SHORT_CYCLE_REBOARD_THREE.value)
        following_date = next_date.get(row.get("trade_date"))
        if (
            CapitalRole.IGNITION_CANDIDATE.value in roles_asof
            and following_date is not None
            and next_streak.get((str(row.get("vt_symbol")), following_date)) == 2
        ):
            roles_realized.add(CapitalRole.CONFIRMED_IGNITION_LEADER.value)
        if not roles_asof:
            roles_asof.add(CapitalRole.ORDINARY_FOLLOWER.value)
        records.append(
            {
                **row,
                "role_asof": sorted(roles_asof),
                "role_realized": sorted(roles_realized),
            }
        )
    roles = pd.DataFrame.from_records(records)
    global_max = roles.groupby("trade_date")["limit_up_streak"].transform("max")
    independent = roles["limit_up_streak"].eq(global_max) & roles[
        "sealed_count"
    ].le(1)
    for index in roles.index[independent]:
        values = set(roles.at[index, "role_realized"])
        values.add(CapitalRole.INDEPENDENT_SPACE_LEADER.value)
        roles.at[index, "role_realized"] = sorted(values)
    return roles.sort_values(
        ["trade_date", "concept_cycle_id", "role_order", "vt_symbol"]
    ).reset_index(drop=True)


def render_coverage_report(inputs: CapitalMainlineInputs) -> str:
    coverage = inputs.coverage
    lines = [
        "# 日级资金主线研究覆盖审计",
        "",
        f"- 研究版本：`{STUDY_VERSION}`。",
        f"- 区间：`{coverage.get('start')}..{coverage.get('end')}`。",
        f"- 交易日：`{coverage.get('trade_days')}`。",
        f"- 官方概念指数：`{coverage.get('concept_bars_rows')}` 行、`{coverage.get('concepts')}` 个概念。",
        f"- 概念资金：`{coverage.get('sector_fund_flows_rows')}` 行。",
        f"- 个股资金：`{coverage.get('stock_fund_flows_rows')}` 行。",
        f"- 涨停事件：`{coverage.get('limit_up_events_rows')}` 行。",
        f"- 完整成员日期：`{', '.join(coverage.get('complete_membership_dates') or []) or '无'}`。",
        f"- 分钟数据读取：`{coverage.get('minute_rows_read')}` 行。",
        "",
    ]
    return "\n".join(lines)


def render_cycle_report(
    inputs: CapitalMainlineInputs,
    bundle: Mapping[str, pd.DataFrame],
) -> str:
    panel = bundle["concept_panel"]
    market = bundle["market_cycles"]
    cycles = bundle["concept_cycles"]
    roles = bundle["roles"]
    report_cycles = (
        cycles.loc[cycles["mainline_rank"].le(3)].copy()
        if not cycles.empty
        else cycles
    )
    report_cycle_ids = set(report_cycles.get("concept_cycle_id", ()))
    report_cycles = (
        cycles.loc[cycles["concept_cycle_id"].isin(report_cycle_ids)]
        if report_cycle_ids
        else cycles.iloc[0:0]
    )
    lines = [
        "# AlphaAgent 2026 年 3-7 月日级资金主线与动态概念龙头周期",
        "",
        "## Current state",
        "",
        f"- 研究版本：`{STUDY_VERSION}`。",
        f"- 市场交易日：`{len(inputs.trade_dates)}`；市场周期：`{market['market_cycle_id'].nunique() if not market.empty else 0}`；概念周期：`{cycles['concept_cycle_id'].nunique() if not cycles.empty else 0}`。",
        f"- 主表只列曾进入当日动态 Top3 的主线周期：`{report_cycles['concept_cycle_id'].nunique() if not report_cycles.empty else 0}`；全量概念周期仍用于候选反事实。",
        "- 本研究未读取分钟表；同日多只首板保留并列，不伪造先后顺序。",
        "- 3-6 月个股概念归属为当前成员幸存者代理；严格点时归属仅使用决策日前完整快照。",
        "",
        "## Coverage",
        "",
        render_coverage_report(inputs).replace("# 日级资金主线研究覆盖审计\n\n", ""),
        "## Market cycles",
        "",
        "| 市场周期 | 开始 | 结束 | 交易日 | 起始阶段 | 末阶段 |",
        "|---|---|---|---:|---|---|",
    ]
    if not market.empty:
        for cycle_id, rows in market.groupby("market_cycle_id", sort=False):
            ordered = rows.sort_values("trade_date")
            lines.append(
                f"| {cycle_id} | {ordered.iloc[0]['trade_date']} | {ordered.iloc[-1]['trade_date']} | {len(ordered)} | {ordered.iloc[0]['market_phase']} | {ordered.iloc[-1]['market_phase']} |"
            )
    lines.extend(
        [
            "",
            "## Concept cycles and leader ladders",
            "",
            "| 概念周期 | 市场周期 | 概念 | 开始 | 结束 | 阶段路径 | 资金证据 | 点火候选 | 确认龙 | 龙二 | 龙三 | 二进三/反包 | 容量核心/补涨 | 成员证据 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    roles_by_cycle = (
        {
            str(cycle_id): rows
            for cycle_id, rows in roles.groupby("concept_cycle_id", sort=False)
        }
        if not roles.empty
        else {}
    )
    if not report_cycles.empty:
        for cycle_id, rows in report_cycles.groupby("concept_cycle_id", sort=False):
            ordered = rows.sort_values("trade_date")
            cycle_roles = roles_by_cycle.get(str(cycle_id), pd.DataFrame())
            start_date = ordered.iloc[0]["trade_date"]
            ignition = _role_names(cycle_roles, CapitalRole.IGNITION_CANDIDATE.value)
            confirmed = _role_names(cycle_roles, CapitalRole.CONFIRMED_IGNITION_LEADER.value, realized=True)
            leader_2 = _role_names(cycle_roles, CapitalRole.LEADER_2.value)
            leader_3 = _role_names(cycle_roles, CapitalRole.LEADER_3.value)
            board_paths = sorted(
                set(
                    _role_names(cycle_roles, CapitalRole.CONTINUOUS_TWO_TO_THREE.value, realized=True)
                    + _role_names(cycle_roles, CapitalRole.SHORT_CYCLE_REBOARD_THREE.value, realized=True)
                )
            )
            capacity_and_replenishment = sorted(
                set(
                    _role_names(cycle_roles, CapitalRole.CAPACITY_CORE.value)
                    + _role_names(cycle_roles, CapitalRole.REPLENISHMENT.value)
                )
            )
            capital = "/".join(_ordered_unique_strings(ordered["capital_state"]))
            evidence = "/".join(
                _ordered_unique_strings(ordered["membership_evidence_level"])
            )
            phases = " -> ".join(
                _ordered_unique_strings(ordered["concept_phase"])
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(cycle_id),
                        str(ordered.iloc[0].get("market_cycle_id") or "-"),
                        str(ordered.iloc[0]["sector_name"]),
                        str(start_date),
                        str(ordered.iloc[-1]["trade_date"]),
                        phases,
                        capital,
                        "、".join(ignition) or "-",
                        "、".join(confirmed) or "-",
                        "、".join(leader_2) or "-",
                        "、".join(leader_3) or "-",
                        "、".join(board_paths) or "-",
                        "、".join(capacity_and_replenishment) or "-",
                        evidence,
                    ]
                )
                + " |"
            )
    independent = _independent_space_rows(roles)
    lines.extend(
        [
            "",
            "## Independent space leaders",
            "",
            "这些股票达到市场空间高度，但所在概念当日封板扩散不足，不能自动当作题材点火龙。",
            "",
            "| 日期 | 股票 | 板位 | 概念 | 概念周期 | 成员证据 |",
            "|---|---|---:|---|---|---|",
        ]
    )
    for row in independent:
        lines.append(
            f"| {row.get('trade_date')} | {row.get('name') or row.get('vt_symbol')} | "
            f"{int(_number(row.get('limit_up_streak')) or 0)} | {row.get('sector_name') or '-'} | "
            f"{row.get('concept_cycle_id') or '-'} | {row.get('membership_evidence_level') or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Daily dynamic mainlines",
            "",
            "| 日期 | 市场周期/阶段 | 主线 Top3 | 资金状态 |",
            "|---|---|---|---|",
        ]
    )
    market_lookup = (
        market.set_index("trade_date")[["market_cycle_id", "market_phase"]].to_dict("index")
        if not market.empty
        else {}
    )
    for trade_date, rows in panel.groupby("trade_date", sort=True):
        top = rows.loc[
            rows["first_board_count"].gt(0)
        ].nsmallest(3, "mainline_rank")
        concepts = "、".join(
            f"{row.sector_name}({float(row.mainline_score):.3f})"
            for row in top.itertuples()
        ) or "无可信主线"
        capitals = "、".join(
            f"{row.sector_name}:{row.capital_state}"
            for row in top.itertuples()
        ) or "-"
        context = market_lookup.get(trade_date, {})
        lines.append(
            f"| {trade_date} | {context.get('market_cycle_id', '-')}/{context.get('market_phase', '-')} | {concepts} | {capitals} |"
        )
    lines.extend(
        [
            "",
            "## Evidence boundary",
            "",
            "- 官方概念指数是严格日级证据；日终资金只有通过来源更新时间门后才能用于下一交易日。",
            "- 3-6 月个股概念成员是幸存者代理，不能据此正式宣称历史选股胜率。",
            "- 点火龙的后续一进二和扩散属于 realized 标签，不进入点火当日盘中 as-of 特征。",
            "",
        ]
    )
    return "\n".join(lines)


def _build_event_links(
    event_ledger: pd.DataFrame,
    contexts: Mapping[date, MembershipContext],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    if event_ledger.empty:
        return pd.DataFrame()
    for row in event_ledger.to_dict("records"):
        if not bool(row.get("is_limit_up")):
            continue
        trade_date = row["trade_date"]
        context = contexts.get(trade_date)
        if context is None:
            continue
        sector_ids = context.by_symbol.get(str(row["vt_symbol"]), ())
        eligible = [
            sector_id
            for sector_id in sector_ids
            if sector_id in context.by_sector
        ]
        credit = 1.0 / len(eligible) if eligible else 0.0
        for sector_id in eligible:
            records.append(
                {
                    **row,
                    "sector_id": sector_id,
                    "sector_name": context.sector_names.get(sector_id, sector_id),
                    "membership_evidence_level": context.evidence_level.value,
                    "membership_snapshot_date": context.snapshot_date,
                    "fractional_sealed_credit": credit,
                }
            )
    return pd.DataFrame.from_records(records)


def _concept_ladder_metrics(
    links: pd.DataFrame,
    contexts: Mapping[date, MembershipContext],
) -> pd.DataFrame:
    if links.empty:
        return pd.DataFrame()
    records: list[dict[str, object]] = []
    for (trade_date, sector_id), rows in links.groupby(
        ["trade_date", "sector_id"], sort=True
    ):
        context = contexts[trade_date]
        sealed_count = int(len(rows))
        records.append(
            {
                "trade_date": trade_date,
                "sector_id": sector_id,
                "eligible_member_count": context.member_counts.get(
                    sector_id,
                    len(context.by_sector.get(sector_id, ())),
                ),
                "sealed_count": sealed_count,
                "first_board_count": int(rows["limit_up_streak"].eq(1).sum()),
                "one_to_two_count": int(rows["limit_up_streak"].eq(2).sum()),
                "two_to_three_count": int(
                    rows["board_pattern"].eq(
                        CapitalRole.CONTINUOUS_TWO_TO_THREE.value
                    ).sum()
                ),
                "reboard_three_count": int(
                    rows["board_pattern"].eq(
                        CapitalRole.SHORT_CYCLE_REBOARD_THREE.value
                    ).sum()
                ),
                "unique_sealed_credit": float(rows["fractional_sealed_credit"].sum()),
                "unique_follower_count": max(sealed_count - 1, 0),
                "membership_evidence_level": context.evidence_level.value,
                "membership_snapshot_date": context.snapshot_date,
            }
        )
    return pd.DataFrame.from_records(records)


def _merge_fund_flows(
    panel: pd.DataFrame,
    inputs: CapitalMainlineInputs,
) -> pd.DataFrame:
    flows = pd.DataFrame.from_records(inputs.sector_fund_flows)
    if flows.empty:
        result = panel.copy()
        for field in (
            "main_net_inflow",
            "main_net_inflow_ratio",
            "flow_rank",
            "flow_rank_change_1d",
            "flow_strength",
        ):
            result[field] = np.nan
        result["flow_known_next_session"] = False
        result["capital_state"] = "turnover_proxy_only"
        return result
    flows = flows.loc[flows["period"].eq("即时")].copy()
    flows["trade_date"] = pd.to_datetime(flows["trade_date"]).dt.date
    next_dates = {
        value: inputs.trade_dates[index + 1]
        for index, value in enumerate(inputs.trade_dates[:-1])
    }
    flows["fund_known_at"] = flows.apply(
        lambda row: fund_flow_known_at(row.to_dict()),
        axis=1,
    )
    flows["flow_known_next_session"] = flows.apply(
        lambda row: (
            flow_is_known_for_next_session(
                row.to_dict(),
                next_dates[row["trade_date"]],
            )
            if row["trade_date"] in next_dates
            else False
        ),
        axis=1,
    )
    flows = flows.rename(columns={"rank": "flow_rank"})
    flows["flow_rank_change_1d"] = flows.sort_values(
        ["sector_id", "trade_date"]
    ).groupby("sector_id")["flow_rank"].diff().mul(-1)
    flows["flow_amount_pctile"] = flows.groupby("trade_date")[
        "main_net_inflow"
    ].rank(pct=True, method="average")
    flows["flow_ratio_pctile"] = flows.groupby("trade_date")[
        "main_net_inflow_ratio"
    ].rank(pct=True, method="average")
    flows["flow_rank_pctile"] = flows.groupby("trade_date")["flow_rank"].rank(
        pct=True,
        method="average",
        ascending=False,
    )
    flows["flow_strength"] = flows[
        ["flow_amount_pctile", "flow_ratio_pctile", "flow_rank_pctile"]
    ].mean(axis=1, skipna=True)
    selected = flows[
        [
            "trade_date",
            "sector_id",
            "main_net_inflow",
            "main_net_inflow_ratio",
            "flow_rank",
            "flow_rank_change_1d",
            "flow_strength",
            "fund_known_at",
            "flow_known_next_session",
        ]
    ]
    result = panel.merge(selected, on=["trade_date", "sector_id"], how="left")
    known = result["flow_known_next_session"].fillna(False).astype(bool)
    confirmed = (
        known
        & result["main_net_inflow"].gt(0)
        & result["main_net_inflow_ratio"].gt(0)
        & result["flow_strength"].ge(0.70)
    )
    divergent = (
        known
        & (
            result["main_net_inflow"].lt(0)
            | result["main_net_inflow_ratio"].lt(0)
            | result["flow_rank_change_1d"].lt(-100)
        )
    )
    result["capital_state"] = np.select(
        [confirmed, divergent, known, result["turnover"].notna()],
        [
            "real_flow_confirmed",
            "divergent",
            "real_flow_observed",
            "turnover_proxy_only",
        ],
        default="unavailable",
    )
    return result


def _primary_concept_score(candidate: Mapping[str, object]) -> float:
    return (
        (_number(candidate.get("mainline_score")) or 0.0) * 0.45
        + (_number(candidate.get("ladder_strength")) or 0.0) * 0.25
        + (_number(candidate.get("flow_strength")) or 0.0) * 0.20
        + (_number(candidate.get("index_strength")) or 0.0) * 0.10
    )


def _pair_return_correlation(
    history: pd.DataFrame,
    left_id: str,
    right_id: str,
) -> float | None:
    if history.empty:
        return None
    field = "return_1d_pct" if "return_1d_pct" in history else "value"
    values = history.loc[
        history["sector_id"].isin([left_id, right_id]),
        ["trade_date", "sector_id", field],
    ].pivot(index="trade_date", columns="sector_id", values=field)
    if left_id not in values or right_id not in values:
        return None
    paired = values[[left_id, right_id]].dropna()
    return float(paired[left_id].corr(paired[right_id])) if len(paired) >= 5 else None


def _role_names(
    roles: pd.DataFrame,
    role: str,
    *,
    realized: bool = False,
) -> list[str]:
    if roles.empty:
        return []
    field = "role_realized" if realized else "role_asof"
    selected = roles.loc[
        roles[field].map(lambda values: role in values if isinstance(values, list) else False)
    ]
    return sorted(
        {
            f"{row.get('trade_date')}:{row.get('name') or row.get('vt_symbol')}({int(_number(row.get('limit_up_streak')) or 0)}板)"
            for row in selected.to_dict("records")
        }
    )


def _independent_space_rows(roles: pd.DataFrame) -> list[dict[str, object]]:
    if roles.empty:
        return []
    selected = roles.loc[
        roles["role_realized"].map(
            lambda values: (
                CapitalRole.INDEPENDENT_SPACE_LEADER.value in values
                if isinstance(values, list)
                else False
            )
        )
    ].copy()
    if selected.empty:
        return []
    selected["_streak"] = pd.to_numeric(
        selected["limit_up_streak"], errors="coerce"
    ).fillna(0)
    return (
        selected.sort_values(
            ["_streak", "trade_date", "vt_symbol"],
            ascending=[False, True, True],
        )
        .drop_duplicates(["trade_date", "vt_symbol"])
        .head(30)
        .to_dict("records")
    )


def _ordered_unique_strings(values: Sequence[object]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value)
            for value in values
            if str(value).strip().lower() not in {"", "nan", "none", "nat"}
        )
    )


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _date_value(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--coverage-only", action="store_true")
    arguments = parser.parse_args(argv)
    inputs = load_capital_mainline_inputs(
        arguments.start,
        arguments.end,
        include_formal_candidates=False,
    )
    if arguments.coverage_only:
        report = render_coverage_report(inputs)
    else:
        bundle = build_research_bundle(
            inputs,
            start=arguments.start,
            end=arguments.end,
        )
        report = render_cycle_report(inputs, bundle)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
