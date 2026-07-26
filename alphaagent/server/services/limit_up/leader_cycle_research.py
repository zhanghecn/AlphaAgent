"""Daily and intraday leader-cycle research with point-in-time coverage gates."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.concept_resonance import is_execution_concept
from alphaagent.server.services.limit_up.leader_cycle_contract import (
    FACTOR_FIELD_CONTRACTS,
    CyclePhase,
    LeaderRole,
    assign_ex_post_roles,
    reject_future_feature_names,
)
from alphaagent.server.services.limit_up.leader_cycle_repository import (
    MINIMUM_MEMBER_COVERAGE_RATIO,
    PROPAGATION_HORIZONS_MINUTES,
    CoverageRow,
    evaluate_propagation_coverage,
    load_intraday_propagation_inputs,
    load_leader_cycle_inputs,
    load_market_trade_dates,
)
from alphaagent.server.services.limit_up.sector_warmup import group_concepts
from alphaagent.server.services.limit_up.sentiment import calculate_effective_board_streaks


SHANGHAI = ZoneInfo("Asia/Shanghai")
CO_IGNITION_WINDOW_SECONDS = 60
MINIMUM_PROPAGATION_EVENT_COUNT = 30
PROPAGATION_METRICS = (
    "rise_count",
    "strong_3_count",
    "strong_5_count",
    "strong_7_count",
    "near_limit_count",
    "touched_count",
    "sealed_count",
    "failed_count",
    "median_change_pct",
    "turnover",
    "main_net_inflow",
)
COUNT_METRICS = frozenset(PROPAGATION_METRICS[:8])


def build_daily_cycle_ledger(payload: Mapping[str, object]) -> list[dict[str, object]]:
    daily_bars = _dict_rows(payload.get("daily_bars"))
    events = _dict_rows(payload.get("events"))
    if not daily_bars:
        return []
    trade_dates = sorted(
        {_date_value(row.get("trade_date")) for row in daily_bars} - {None}
    )
    market_trade_dates = set(trade_dates)
    daily_by_identity = {
        (str(row.get("vt_symbol") or ""), _date_value(row.get("trade_date"))): row
        for row in daily_bars
    }
    event_flags = [
        {
            "vt_symbol": str(event.get("vt_symbol") or ""),
            "trade_date": _date_value(event.get("trade_date")),
            "is_limit_up": bool(event.get("is_sealed")),
            "event": event,
        }
        for event in events
        if event.get("vt_symbol")
        and _date_value(event.get("trade_date")) in market_trade_dates
    ]
    streak_rows = calculate_effective_board_streaks(event_flags, trade_dates)
    event_rows_by_date: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in streak_rows:
        event_rows_by_date[row["trade_date"]].append(row)

    sentiment_by_date = {
        _date_value(row.get("date")): row
        for row in _dict_rows(payload.get("sentiment"))
    }
    membership_contexts = _membership_contexts(payload, trade_dates)
    fund_by_date = _latest_fund_flows(_dict_rows(payload.get("fund_flows")))
    concept_first_seen: dict[str, date] = {}
    active_main_group_id: str | None = None
    active_previous_count: int | None = None
    active_previous_stage: str | None = None
    active_propagation_days = 0
    leadership_tenure: dict[str, int] = defaultdict(int)
    previous_leaders: set[str] = set()
    recent_main_groups: list[str] = []
    ledger: list[dict[str, object]] = []

    for trade_date in trade_dates:
        day_event_rows = event_rows_by_date.get(trade_date, [])
        sealed_rows = [row for row in day_event_rows if row["is_limit_up"]]
        failed_touch_rows = [
            row
            for row in day_event_rows
            if not row["is_limit_up"]
            and isinstance(row.get("event"), Mapping)
            and row["event"].get("first_limit_time")
        ]
        maximum_height = max(
            (int(row.get("limit_up_streak") or 0) for row in sealed_rows),
            default=0,
        )
        leaders = [
            row for row in sealed_rows if int(row.get("limit_up_streak") or 0) == maximum_height
        ]
        context = membership_contexts[trade_date]
        groups = context["groups"]
        group_counts = _sealed_group_counts(sealed_rows, groups)
        main_group = _select_main_group(
            group_counts,
            groups,
            fund_by_date.get(trade_date, {}),
        )
        main_group_id = str((main_group or {}).get("group_id") or "") or None
        main_count = group_counts.get(main_group_id or "", 0)
        fund_main_group = _select_fund_main_group(
            groups,
            fund_by_date.get(trade_date, {}),
        )
        fund_main_group_id = str((fund_main_group or {}).get("group_id") or "") or None
        theme_stage = None
        cycle_id = None
        propagation_days: int | None = None
        if main_group_id:
            if main_group_id != active_main_group_id:
                active_main_group_id = main_group_id
                active_previous_count = None
                active_previous_stage = None
                active_propagation_days = 0
                concept_first_seen[main_group_id] = trade_date
            first_seen = concept_first_seen[main_group_id]
            theme_stage = _next_descriptive_stage(
                active_previous_stage,
                active_previous_count,
                main_count,
            )
            active_previous_count = main_count
            active_previous_stage = theme_stage
            cycle_id = f"{main_group_id}:{first_seen.isoformat()}"
            if context["evidence_level"] == "point_in_time_complete":
                if main_count > 1:
                    active_propagation_days += 1
                propagation_days = active_propagation_days
            recent_main_groups.append(main_group_id)
            recent_main_groups = recent_main_groups[-5:]
        else:
            active_main_group_id = None
            active_previous_count = None
            active_previous_stage = None
            active_propagation_days = 0

        leader_symbols = {str(row.get("vt_symbol") or "") for row in leaders}
        for symbol in list(leadership_tenure):
            if symbol not in leader_symbols:
                leadership_tenure[symbol] = 0
        for symbol in leader_symbols:
            leadership_tenure[symbol] = leadership_tenure[symbol] + 1 if symbol in previous_leaders else 1
        previous_leaders = leader_symbols

        role_inputs = []
        for row in sealed_rows:
            symbol = str(row.get("vt_symbol") or "")
            event = row.get("event") if isinstance(row.get("event"), Mapping) else {}
            group = _group_for_symbol(groups, symbol)
            group_id = str((group or {}).get("group_id") or "")
            response_rank = _response_rank(sealed_rows, group, symbol)
            propagation_known = context["evidence_level"] == "point_in_time_complete"
            propagation_confirmed = (
                group_counts.get(group_id, 0) > 1 if group_id else None
            )
            role_inputs.append(
                {
                    "vt_symbol": symbol,
                    "board_height": int(row.get("limit_up_streak") or 0),
                    "highest_group_days": leadership_tenure.get(symbol, 0),
                    "propagation_confirmed": propagation_confirmed,
                    "ignition_contribution": bool(
                        group_id
                        and response_rank == 1
                        and propagation_known
                        and propagation_confirmed is True
                    ),
                    "capacity_core": _is_capacity_core(event, sealed_rows, group),
                    "response_rank": response_rank,
                    "started_after_confirmation": bool(
                        group_id
                        and group_id in concept_first_seen
                        and concept_first_seen[group_id] < trade_date
                        and int(row.get("limit_up_streak") or 0) == 1
                    ),
                }
            )
        assignments = {
            assignment.vt_symbol: assignment.roles
            for assignment in assign_ex_post_roles(role_inputs)
        }
        leader_payload = [
            {
                "vt_symbol": symbol,
                "name": str(
                    daily_by_identity.get((symbol, trade_date), {}).get("name")
                    or (
                        row.get("event")
                        if isinstance(row.get("event"), Mapping)
                        else {}
                    ).get("name")
                    or symbol
                ),
                "board_spell_days": int(row.get("limit_up_streak") or 0),
                "leadership_tenure_days": leadership_tenure.get(symbol, 0),
                "roles": sorted(role.value for role in assignments.get(symbol, ())),
            }
            for row in leaders
            if (symbol := str(row.get("vt_symbol") or ""))
        ]
        point = sentiment_by_date.get(trade_date, {})
        ledger.append(
            {
                "trade_date": trade_date,
                "market_phase": point.get("phase"),
                "sentiment_score": point.get("score"),
                "maximum_board_height": maximum_height,
                "height_change": maximum_height - int(ledger[-1]["maximum_board_height"]) if ledger else None,
                "highest_board_group": leader_payload,
                "promotion_ladder": point.get("promotion_ladder") or {},
                "main_theme": main_group,
                "main_theme_sealed_count": main_count,
                "instant_fund_main_attack": fund_main_group,
                "fund_height_divergence": (
                    main_group_id != fund_main_group_id
                    if main_group_id is not None and fund_main_group_id is not None
                    else None
                ),
                "five_day_warm_groups": dict(Counter(recent_main_groups)),
                "theme_stage": theme_stage,
                "cycle_id": cycle_id,
                "theme_propagation_days": propagation_days,
                "membership_evidence_level": context["evidence_level"],
                "membership_snapshot_date": context["snapshot_date"],
                "role_groups": [
                    {
                        "vt_symbol": str(row.get("vt_symbol") or ""),
                        "name": str(
                            daily_by_identity.get(
                                (str(row.get("vt_symbol") or ""), trade_date),
                                {},
                            ).get("name")
                            or (
                                row.get("event")
                                if isinstance(row.get("event"), Mapping)
                                else {}
                            ).get("name")
                            or row.get("vt_symbol")
                            or ""
                        ),
                        "roles": sorted(
                            role.value
                            for role in assignments.get(str(row.get("vt_symbol") or ""), ())
                        ),
                        "board_spell_days": int(row.get("limit_up_streak") or 0),
                        "leadership_tenure_days": leadership_tenure.get(
                            str(row.get("vt_symbol") or ""),
                            0,
                        ),
                    }
                    for row in sealed_rows
                ],
                "failed_touch_group": [
                    {
                        "vt_symbol": str(row.get("vt_symbol") or ""),
                        "name": str(
                            (
                                row.get("event")
                                if isinstance(row.get("event"), Mapping)
                                else {}
                            ).get("name")
                            or row.get("vt_symbol")
                            or ""
                        ),
                        "first_limit_time": (
                            row.get("event")
                            if isinstance(row.get("event"), Mapping)
                            else {}
                        ).get("first_limit_time"),
                        "opened_board_count": (
                            row.get("event")
                            if isinstance(row.get("event"), Mapping)
                            else {}
                        ).get("open_times"),
                        "board_spell_days": 0,
                    }
                    for row in failed_touch_rows
                ],
                "theme_cycle_end_date": None,
            }
        )
    for index, row in enumerate(ledger[:-1]):
        if row.get("cycle_id") and row.get("cycle_id") != ledger[index + 1].get("cycle_id"):
            row["theme_cycle_end_date"] = row["trade_date"]
    return ledger


def build_ignition_events(payload: Mapping[str, object]) -> list[dict[str, object]]:
    events = _dict_rows(payload.get("events"))
    memberships = _dict_rows(payload.get("memberships"))
    complete_snapshot_dates = sorted(
        {
            parsed
            for row in _dict_rows(payload.get("membership_scopes"))
            if row.get("scope_type") == "concept"
            and row.get("complete") is True
            and (parsed := _date_value(row.get("snapshot_date"))) is not None
        }
    )
    memberships_by_date_symbol: dict[
        tuple[date, str],
        list[dict[str, object]],
    ] = defaultdict(list)
    members_by_date_sector: dict[tuple[date, str], set[str]] = defaultdict(set)
    for row in memberships:
        snapshot_date = _date_value(row.get("snapshot_date"))
        if snapshot_date in complete_snapshot_dates:
            symbol = str(row.get("vt_symbol") or "")
            sector_id = str(row.get("sector_id") or "")
            sector_type = str(row.get("sector_type") or "concept").lower()
            if symbol:
                memberships_by_date_symbol[(snapshot_date, symbol)].append(row)
            if symbol and sector_id and sector_type in {"concept", "theme"}:
                members_by_date_sector[(snapshot_date, sector_id)].add(symbol)
    prior_date_by_trade_date: dict[date, date | None] = {}
    raw: list[dict[str, object]] = []
    for event in events:
        trade_date = _date_value(event.get("trade_date"))
        first_time = _time_value(event.get("first_limit_time"))
        if trade_date is None or first_time is None:
            continue
        if trade_date not in prior_date_by_trade_date:
            prior_date = max(
                (snapshot_date for snapshot_date in complete_snapshot_dates if snapshot_date < trade_date),
                default=None,
            )
            prior_date_by_trade_date[trade_date] = prior_date
        prior_date = prior_date_by_trade_date[trade_date]
        symbol = str(event.get("vt_symbol") or "")
        symbol_rows = [
            row
            for row in memberships_by_date_symbol.get((prior_date, symbol), [])
            if str(row.get("sector_type") or "concept").lower() in {"concept", "theme"}
        ]
        for row in symbol_rows:
            concept_name = str(row.get("sector_name") or row.get("sector_id") or "")
            if not is_execution_concept(concept_name):
                continue
            sector_id = str(row.get("sector_id") or "")
            member_symbols = sorted(
                members_by_date_sector.get((prior_date, sector_id), set())
            )
            raw.append(
                {
                    "trade_date": trade_date,
                    "ignition_at": datetime.combine(trade_date, first_time),
                    "vt_symbol": symbol,
                    "name": event.get("name"),
                    "concept_group_id": sector_id,
                    "concept_group_name": concept_name,
                    "sector_ids": [sector_id],
                    "member_symbols": member_symbols,
                    "membership_snapshot_date": prior_date,
                }
            )
    clusters: list[list[dict[str, object]]] = []
    for event in sorted(
        raw,
        key=lambda row: (
            row["trade_date"],
            str(row["concept_group_id"]),
            row["ignition_at"],
            str(row["vt_symbol"]),
        ),
    ):
        if (
            clusters
            and clusters[-1][0]["trade_date"] == event["trade_date"]
            and clusters[-1][0]["concept_group_id"] == event["concept_group_id"]
            and (event["ignition_at"] - clusters[-1][-1]["ignition_at"]).total_seconds()
            <= CO_IGNITION_WINDOW_SECONDS
        ):
            clusters[-1].append(event)
        else:
            clusters.append([event])
    return [
        {
            **cluster[0],
            "ignition_cluster_id": (
                f"{cluster[0]['trade_date']}:{cluster[0]['concept_group_id']}:"
                f"{cluster[0]['ignition_at'].strftime('%H%M%S')}"
            ),
            "ignition_symbols": sorted({str(row["vt_symbol"]) for row in cluster}),
            "co_ignition": len(cluster) > 1,
            "event_count": len(cluster),
        }
        for cluster in clusters
    ]


def match_market_controls(
    event: Mapping[str, object],
    payload: Mapping[str, object],
) -> dict[str, object] | None:
    minute_rows = _dict_rows(payload.get("minute_bars"))
    ignition_at = _datetime_value(event.get("ignition_at"))
    theme_members = {str(value) for value in event.get("member_symbols", ())}
    if ignition_at is None:
        return None
    required = _required_times(ignition_at)
    cached_index = payload.get("_minute_row_index")
    index = (
        cached_index
        if isinstance(cached_index, Mapping)
        else _minute_row_index(minute_rows)
    )
    cached_symbols = payload.get("_minute_symbols")
    minute_symbols = (
        {str(value) for value in cached_symbols}
        if isinstance(cached_symbols, Sequence)
        and not isinstance(cached_symbols, (str, bytes))
        else {symbol for symbol, _ in index}
    )
    control_symbols = sorted(
        {
            symbol
            for symbol in minute_symbols
            if symbol not in theme_members and all((symbol, target) in index for target in required)
        }
    )
    if not control_symbols:
        return None
    return {
        "ignition_cluster_id": event.get("ignition_cluster_id"),
        "control_symbols": control_symbols,
        "control_available": True,
        "matching_basis": "same_trade_date_complete_minute_path",
    }


def build_propagation_panel(
    events: Sequence[Mapping[str, object]],
    payload: Mapping[str, object],
) -> list[dict[str, object]]:
    minute_index = _minute_row_index(_dict_rows(payload.get("minute_bars")))
    rows: list[dict[str, object]] = []
    for event in events:
        ignition_at = _datetime_value(event.get("ignition_at"))
        if ignition_at is None:
            continue
        ignition_symbol = str(event.get("vt_symbol") or "")
        ignition_symbols = ({ignition_symbol} if ignition_symbol else set()) | {
            str(value) for value in event.get("ignition_symbols", ()) if str(value)
        }
        members = {
            str(value) for value in event.get("member_symbols", ())
        } - ignition_symbols
        if not members:
            continue
        controls = {str(value) for value in event.get("control_symbols", ())}
        baseline_at = ignition_at.replace(second=0, microsecond=0) - timedelta(minutes=1)
        for horizon in PROPAGATION_HORIZONS_MINUTES:
            target_at = ignition_at.replace(second=0, microsecond=0) + timedelta(minutes=horizon)
            theme_baseline = _snapshot_metrics(members, baseline_at, minute_index)
            theme_target = _snapshot_metrics(members, target_at, minute_index)
            control_baseline = _snapshot_metrics(controls, baseline_at, minute_index)
            control_target = _snapshot_metrics(controls, target_at, minute_index)
            for metric in PROPAGATION_METRICS:
                raw_delta = _metric_delta(theme_baseline, theme_target, metric)
                control_delta = _metric_delta(control_baseline, control_target, metric)
                if metric in COUNT_METRICS:
                    control_delta = control_delta * len(members) / max(len(controls), 1)
                rows.append(
                    {
                        "trade_date": event.get("trade_date"),
                        "ignition_cluster_id": event.get("ignition_cluster_id"),
                        "concept_group_id": event.get("concept_group_id"),
                        "horizon_minutes": horizon,
                        "metric": metric,
                        "raw_theme_delta_ex_leader": round(raw_delta, 6),
                        "matched_market_delta": round(control_delta, 6),
                        "incremental_propagation": round(raw_delta - control_delta, 6),
                        "member_coverage_ratio": event.get("member_coverage_ratio"),
                        "known_at": target_at,
                    }
                )
    return rows


def summarize_propagation(panel: Sequence[Mapping[str, object]]) -> dict[str, object]:
    grouped: dict[tuple[int, str], list[float]] = defaultdict(list)
    for row in panel:
        value = _number(row.get("incremental_propagation"))
        if value is not None:
            grouped[(int(row.get("horizon_minutes") or 0), str(row.get("metric") or ""))].append(value)
    return {
        "row_count": len(panel),
        "by_horizon_metric": [
            {
                "horizon_minutes": key[0],
                "metric": key[1],
                "event_count": len(values),
                "median_incremental_propagation": round(median(values), 6),
            }
            for key, values in sorted(grouped.items())
        ],
    }


def build_point_in_time_factor_row(
    observation: Mapping[str, object],
    *,
    decision_at: datetime,
) -> dict[str, object]:
    """Project E/L/P/R/H fields without converting unknown evidence to zero."""

    reject_future_feature_names(observation.keys())
    result: dict[str, object] = {"decision_at": decision_at}
    default_known_at = _datetime_value(observation.get("known_at"))
    for contract in FACTOR_FIELD_CONTRACTS:
        raw = observation.get(contract.name)
        if isinstance(raw, Mapping):
            value = raw.get("value")
            known_at = _datetime_value(raw.get("known_at"))
            source = str(raw.get("source") or contract.source)
        else:
            value = raw
            known_at = _datetime_value(observation.get(f"{contract.name}_known_at")) or default_known_at
            source = str(observation.get(f"{contract.name}_source") or contract.source)
        if known_at is not None and known_at > decision_at:
            raise ValueError(f"feature {contract.name} is not known at decision time")
        result[contract.name] = value
        result[f"{contract.name}_missing"] = value is None
        result[f"{contract.name}_known_at"] = known_at
        result[f"{contract.name}_source"] = source
    return result


def build_switch_risk_features(
    current: Mapping[str, object],
    previous: Mapping[str, object] | None,
) -> dict[str, object]:
    """Keep switch mechanisms separate so missing evidence remains auditable."""

    previous = previous or {}
    previous_propagation = _number(previous.get("theme_propagation_strength"))
    current_propagation = _number(current.get("theme_propagation_strength"))
    propagation_decay = (
        previous_propagation - current_propagation
        if previous_propagation is not None and current_propagation is not None
        else None
    )
    old_capacity = str(previous.get("capacity_core_symbol") or "") or None
    new_capacity = str(current.get("capacity_core_symbol") or "") or None
    capacity_migration = (
        old_capacity != new_capacity
        if old_capacity is not None and new_capacity is not None
        else None
    )
    height_theme = str(current.get("highest_board_theme_id") or "") or None
    fund_theme = str(current.get("fund_main_theme_id") or "") or None
    fund_height_divergence = (
        height_theme != fund_theme
        if height_theme is not None and fund_theme is not None
        else None
    )
    return {
        "old_leader_failed": current.get("old_leader_failed"),
        "old_theme_propagation_decay": propagation_decay,
        "fund_height_divergence": fund_height_divergence,
        "new_theme_co_ignition": current.get("new_theme_co_ignition"),
        "capacity_core_migration": capacity_migration,
        "reflux_recovery": (
            str(current.get("theme_stage") or "") == CyclePhase.REFLUX.value
            if current.get("theme_stage") is not None
            else None
        ),
    }


def render_daily_report(
    ledger: Sequence[Mapping[str, object]],
    coverage: Sequence[CoverageRow],
    supply_capabilities: Mapping[str, object] | None = None,
) -> str:
    lines = [
        "# AlphaAgent 2026年3-7月涨停龙头周期账本",
        "",
        "## Current state",
        "",
        f"- 日级账本交易日：`{len(ledger)}`。",
        "- 日级角色允许使用盘后标签；分钟因果仅见独立分钟传播报告。",
        "- 缺少历史点时成员的日期标记为 `current_membership_descriptive_only`。",
        "",
        "## Coverage",
        "",
        "| 数据 | 开始 | 结束 | 交易日 | 股票日 | 帧/行 | 证据级别 |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for row in coverage:
        lines.append(
            f"| {row.dataset} | {_date_text(row.first_date)} | {_date_text(row.last_date)} | "
            f"{row.trade_day_count} | {row.symbol_day_count} | {row.frame_count}/{row.row_count} | "
            f"{row.evidence_level} |"
        )
    lines.extend(_supply_capability_lines(supply_capabilities or {}))
    for month in (7, 6, 5, 4, 3):
        month_rows = [row for row in ledger if _date_value(row.get("trade_date")).month == month]
        cycle_summaries = _summarize_cycles(month_rows)
        role_summaries = _summarize_role_tenures(month_rows)
        divergence_rows = [row for row in month_rows if row.get("fund_height_divergence") is True]
        lines.extend(
            [
                "",
                f"## 2026-{month:02d}",
                "",
                f"- 交易日：`{len(month_rows)}`；周期片段：`{len(cycle_summaries)}`；"
                f"资金主攻与高度主线脱钩日：`{len(divergence_rows)}`。",
                "",
                "### Cycle summary",
                "",
                "| 周期 | 题材 | 点火 | 确认 | 峰值 | 首次分歧 | 回流 | 结束 | 传播交易日 | 证据 |",
                "|---|---|---|---|---|---|---|---|---:|---|",
            ]
        )
        for cycle in cycle_summaries:
            lines.append(
                f"| {cycle['cycle_id']} | {cycle['theme_name']} | {cycle['ignition_date']} | "
                f"{cycle['confirmation_date']} | {cycle['peak_date']}({cycle['peak_count']}) | "
                f"{cycle['divergence_date']} | {cycle['reflux_date']} | {cycle['end_date']} | "
                f"{cycle['propagation_days']} | {cycle['evidence_level']} |"
            )
        if not cycle_summaries:
            lines.append("| 无 | 无明确主线 | - | - | - | - | - | - | - | unavailable |")
        lines.extend(
            [
                "",
                "### Daily switches",
                "",
                "| 日期 | 情绪 | 最高板 | 高度组 | 高度主线 | 资金主攻 | 阶段 | 脱钩 | 成员证据 |",
                "|---|---|---:|---|---|---|---|---|---|",
            ]
        )
        for row in month_rows:
            leaders = "、".join(
                f"{leader.get('name')}({leader.get('board_spell_days')}板)"
                for leader in row.get("highest_board_group", ())
            ) or "无"
            theme = row.get("main_theme")
            theme_name = theme.get("group_name") if isinstance(theme, Mapping) else "无明确主线"
            fund_theme = row.get("instant_fund_main_attack")
            fund_theme_name = (
                fund_theme.get("group_name")
                if isinstance(fund_theme, Mapping)
                else "无盘中资金证据"
            )
            lines.append(
                f"| {_date_text(row.get('trade_date'))} | {row.get('market_phase') or '未知'} | "
                f"{row.get('maximum_board_height') or 0} | {leaders} | {theme_name} | "
                f"{fund_theme_name} | {row.get('theme_stage') or 'unavailable'} | "
                f"{_bool_text(row.get('fund_height_divergence'))} | "
                f"{row.get('membership_evidence_level')} |"
            )
        lines.extend(
            [
                "",
                "### Role tenure",
                "",
                "| 股票 | 角色 | 首日 | 末日 | 角色交易日 | 最高有效板 | 最长最高板任期 |",
                "|---|---|---|---|---:|---:|---:|",
            ]
        )
        for role in role_summaries:
            lines.append(
                f"| {role['name']} | {role['roles']} | {role['first_date']} | "
                f"{role['last_date']} | {role['role_days']} | {role['maximum_board_height']} | "
                f"{role['maximum_leadership_tenure']} |"
            )
        if not role_summaries:
            lines.append("| 无 | - | - | - | 0 | 0 | 0 |")
        evidence_counts = Counter(str(row.get("membership_evidence_level") or "unavailable") for row in month_rows)
        lines.extend(
            [
                "",
                "### Data limits",
                "",
                f"- 成员证据分布：`{dict(sorted(evidence_counts.items()))}`。",
                "- `current_membership_descriptive_only` 只用于日级题材描述，不支持分钟因果。",
                "- 脱钩仅在高度主线和独立资金主攻都有观测时判定，未知不按一致处理。",
            ]
        )
    lines.extend(_golden_case_lines(ledger))
    lines.extend(
        [
            "",
            "## Open risks/next work",
            "",
            "- 3-6月无历史点时题材成员，题材名称与角色只作描述，不能声称分钟因果。",
            "- 空间高度、容量主线和题材传播是三个独立时钟，报告未用其中一个填充另一个。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_intraday_report(
    coverage: Mapping[str, object],
    panel: Sequence[Mapping[str, object]],
) -> str:
    summary = summarize_propagation(panel)
    accepted_count = int(coverage.get("accepted_count") or 0)
    research_status = (
        "research_only"
        if accepted_count >= MINIMUM_PROPAGATION_EVENT_COUNT
        else "research_only/insufficient_point_in_time_coverage"
    )
    lines = [
        "# AlphaAgent 2026年7月龙头分钟传播验证",
        "",
        "## Coverage and exclusions",
        "",
        f"- 接受事件：`{accepted_count}`。",
        f"- 排除事件：`{coverage.get('excluded_count', 0)}`。",
        f"- 最低成员覆盖率：`{MINIMUM_MEMBER_COVERAGE_RATIO:.0%}`。",
        f"- 最低机制样本门：`{MINIMUM_PROPAGATION_EVENT_COUNT}` 个合格传播事件。",
        f"- 研究状态：`{research_status}`。",
        "",
        "| 事件 | 题材 | 覆盖成员/成员 | 成员覆盖 | 结果/排除原因 |",
        "|---|---|---:|---:|---|",
    ]
    for event in [
        *_dict_rows(coverage.get("accepted_events")),
        *_dict_rows(coverage.get("excluded_events")),
    ]:
        reasons = "、".join(event.get("exclusion_reasons") or ()) or "accepted"
        lines.append(
            f"| {event.get('ignition_cluster_id')} | {event.get('concept_group_name')} | "
            f"{event.get('covered_member_count', 0)}/{event.get('member_count', 0)} | "
            f"{_pct(event.get('member_coverage_ratio'))} | {reasons} |"
        )
    reason_counts = Counter(
        reason
        for event in _dict_rows(coverage.get("excluded_events"))
        for reason in event.get("exclusion_reasons", ())
    )
    lines.extend(
        [
            "",
            "### Exclusion summary",
            "",
            "| 原因 | 事件数 |",
            "|---|---:|",
        ]
    )
    for reason, count in sorted(reason_counts.items()):
        lines.append(f"| {reason} | {count} |")
    if not reason_counts:
        lines.append("| 无 | 0 |")
    lines.extend(
        [
            "",
            "## Incremental propagation",
            "",
            f"- 面板行数：`{summary['row_count']}`。每行均排除点火股票并扣除匹配市场变化。",
            "",
            "| 窗口 | 指标 | 事件数 | 中位增量传播 |",
            "|---:|---|---:|---:|",
        ]
    )
    for row in summary["by_horizon_metric"]:
        lines.append(
            f"| {row['horizon_minutes']}m | {row['metric']} | {row['event_count']} | "
            f"{row['median_incremental_propagation']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- 覆盖不完整的成员没有按零收益或未跟风处理，而是整项排除。",
            f"- 接受事件少于{MINIMUM_PROPAGATION_EVENT_COUNT}时，本报告只完成传播工程和排除审计，不构成“股票先动、板块后扩散”的可靠正例验证。",
            "- 即使存在接受事件，本报告也只是已查看历史上的机制研究，不替代Task 8的独立前向模型门。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_coverage_report(payload: Mapping[str, object]) -> str:
    rows = payload.get("coverage")
    coverage = [row for row in rows or () if isinstance(row, CoverageRow)]
    lines = [
        "# Leader-cycle coverage",
        "",
        "| dataset | first | last | days | symbols | symbol-days | frames | rows | evidence |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in coverage:
        lines.append(
            f"| {row.dataset} | {_date_text(row.first_date)} | {_date_text(row.last_date)} | "
            f"{row.trade_day_count} | {row.symbol_count} | {row.symbol_day_count} | "
            f"{row.frame_count} | {row.row_count} | {row.evidence_level} |"
        )
    lines.extend(
        _supply_capability_lines(
            payload.get("supply_capabilities")
            if isinstance(payload.get("supply_capabilities"), Mapping)
            else {}
        )
    )
    return "\n".join(lines) + "\n"


def _supply_capability_lines(capabilities: Mapping[str, object]) -> list[str]:
    lines = [
        "",
        "## Data supply capabilities",
        "",
        "| capability | status | reason |",
        "|---|---|---|",
    ]
    for name, raw in sorted(capabilities.items()):
        value = raw if isinstance(raw, Mapping) else {}
        lines.append(
            f"| {name} | {value.get('status') or 'unavailable'} | "
            f"{value.get('reason') or '-'} |"
        )
    if not capabilities:
        lines.append("| unavailable | unavailable | no capability audit supplied |")
    return lines


def _membership_contexts(
    payload: Mapping[str, object],
    trade_dates: Sequence[date],
) -> dict[date, dict[str, object]]:
    snapshots = _dict_rows(payload.get("memberships"))
    scopes = _dict_rows(payload.get("membership_scopes"))
    current = _dict_rows(payload.get("current_memberships"))
    complete_dates = {
        _date_value(row.get("snapshot_date"))
        for row in scopes
        if row.get("scope_type") == "concept" and row.get("complete") is True
    }
    snapshots_by_date: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in snapshots:
        snapshot_date = _date_value(row.get("snapshot_date"))
        if snapshot_date is not None:
            snapshots_by_date[snapshot_date].append(row)
    ordered_complete_dates = sorted(complete_dates)
    result: dict[date, dict[str, object]] = {}
    group_cache: dict[tuple[str, date | None], list[dict[str, object]]] = {}
    for trade_date in trade_dates:
        prior_dates = [
            snapshot_date
            for snapshot_date in ordered_complete_dates
            if snapshot_date is not None and snapshot_date < trade_date
        ]
        snapshot_date = prior_dates[-1] if prior_dates else None
        if snapshot_date:
            rows = snapshots_by_date[snapshot_date]
            evidence = "point_in_time_complete"
        else:
            rows = current
            evidence = "current_membership_descriptive_only"
        cache_key = (evidence, snapshot_date)
        if cache_key not in group_cache:
            execution_rows = [
                row
                for row in rows
                if is_execution_concept(
                    str(row.get("sector_name") or row.get("sector_id") or "")
                )
            ]
            group_cache[cache_key] = group_concepts(execution_rows)
        groups = group_cache[cache_key]
        result[trade_date] = {
            "snapshot_date": snapshot_date,
            "evidence_level": evidence,
            "groups": groups,
        }
    return result


def _sealed_group_counts(
    sealed_rows: Sequence[Mapping[str, object]],
    groups: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    sealed_symbols = {str(row.get("vt_symbol") or "") for row in sealed_rows}
    return {
        str(group.get("group_id") or ""): len(
            sealed_symbols & {str(symbol) for symbol in group.get("member_symbols", ())}
        )
        for group in groups
    }


def _select_main_group(
    counts: Mapping[str, int],
    groups: Sequence[Mapping[str, object]],
    fund_flows: Mapping[str, Mapping[str, object]],
) -> dict[str, object] | None:
    candidates = [group for group in groups if counts.get(str(group.get("group_id") or ""), 0)]
    if not candidates:
        return None
    return dict(
        max(
            candidates,
            key=lambda group: (
                counts.get(str(group.get("group_id") or ""), 0),
                max(
                    (
                        _number(fund_flows.get(str(sector_id), {}).get("main_net_inflow"))
                        or float("-inf")
                        for sector_id in group.get("sector_ids", ())
                    ),
                    default=float("-inf"),
                ),
                str(group.get("group_id") or ""),
            ),
        )
    )


def _select_fund_main_group(
    groups: Sequence[Mapping[str, object]],
    fund_flows: Mapping[str, Mapping[str, object]],
) -> dict[str, object] | None:
    if not fund_flows:
        return None
    candidates = [
        group
        for group in groups
        if any(str(sector_id) in fund_flows for sector_id in group.get("sector_ids", ()))
    ]
    if not candidates:
        return None

    def score(group: Mapping[str, object]) -> tuple[float, str]:
        values = [
            _number(fund_flows.get(str(sector_id), {}).get("main_net_inflow"))
            for sector_id in group.get("sector_ids", ())
        ]
        valid = [value for value in values if value is not None]
        return (max(valid, default=float("-inf")), str(group.get("group_id") or ""))

    return dict(max(candidates, key=score))


def _latest_fund_flows(
    rows: Sequence[Mapping[str, object]],
) -> dict[date, dict[str, dict[str, object]]]:
    result: dict[date, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in sorted(rows, key=lambda value: _datetime_value(value.get("captured_at")) or datetime.min):
        trade_date = _date_value(row.get("trade_date"))
        sector_id = str(row.get("sector_id") or "")
        if trade_date and sector_id:
            result[trade_date][sector_id] = dict(row)
    return result


def _next_descriptive_stage(
    previous_stage: str | None,
    previous_count: int | None,
    current_count: int,
) -> str:
    if previous_stage is None:
        return CyclePhase.IGNITION.value
    if previous_stage == CyclePhase.IGNITION:
        return CyclePhase.CONFIRMATION.value
    if (
        previous_stage == CyclePhase.DIVERGENCE.value
        and previous_count is not None
        and current_count > previous_count
    ):
        return CyclePhase.REFLUX.value
    if previous_stage in {CyclePhase.CONFIRMATION, CyclePhase.REFLUX}:
        return CyclePhase.DIFFUSION.value
    if previous_count is not None and current_count > previous_count:
        return CyclePhase.ACCELERATION.value
    return CyclePhase.DIVERGENCE.value


def _group_for_symbol(
    groups: Sequence[Mapping[str, object]],
    symbol: str,
) -> Mapping[str, object] | None:
    candidates = [group for group in groups if symbol in group.get("member_symbols", ())]
    return max(candidates, key=lambda group: int(group.get("member_count") or 0), default=None)


def _response_rank(
    rows: Sequence[Mapping[str, object]],
    group: Mapping[str, object] | None,
    symbol: str,
) -> int:
    if not group:
        return 0
    members = set(group.get("member_symbols", ()))
    ordered = sorted(
        [
            row
            for row in rows
            if str(row.get("vt_symbol") or "") in members
        ],
        key=lambda row: (
            str(
                (row.get("event") if isinstance(row.get("event"), Mapping) else {}).get(
                    "first_limit_time"
                )
                or "99:99:99"
            ),
            str(row.get("vt_symbol") or ""),
        ),
    )
    return next(
        (index for index, row in enumerate(ordered, start=1) if row.get("vt_symbol") == symbol),
        0,
    )


def _is_capacity_core(
    event: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
    group: Mapping[str, object] | None,
) -> bool:
    if not group:
        return False
    members = set(group.get("member_symbols", ()))
    turnovers = sorted(
        [
            _number(
                (row.get("event") if isinstance(row.get("event"), Mapping) else {}).get("turnover")
            )
            or 0.0
            for row in rows
            if str(row.get("vt_symbol") or "") in members
        ],
        reverse=True,
    )
    turnover = _number(event.get("turnover")) or 0.0
    return bool(turnovers and turnover >= turnovers[max(len(turnovers) // 3 - 1, 0)])


def _summarize_cycles(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        cycle_id = str(row.get("cycle_id") or "")
        if cycle_id:
            grouped[cycle_id].append(row)
    summaries: list[dict[str, object]] = []
    for cycle_id, cycle_rows in sorted(grouped.items()):
        ordered = sorted(cycle_rows, key=lambda row: _date_value(row.get("trade_date")) or date.min)
        peak = max(
            ordered,
            key=lambda row: (
                int(row.get("main_theme_sealed_count") or 0),
                -(_date_value(row.get("trade_date")) or date.max).toordinal(),
            ),
        )
        theme = ordered[0].get("main_theme")
        evidence = sorted(
            {str(row.get("membership_evidence_level") or "unavailable") for row in ordered}
        )
        summaries.append(
            {
                "cycle_id": cycle_id,
                "theme_name": (
                    str(theme.get("group_name") or "未命名题材")
                    if isinstance(theme, Mapping)
                    else "未命名题材"
                ),
                "ignition_date": _date_text(ordered[0].get("trade_date")),
                "confirmation_date": _first_stage_date(
                    ordered,
                    {CyclePhase.CONFIRMATION.value, CyclePhase.DIFFUSION.value},
                ),
                "peak_date": _date_text(peak.get("trade_date")),
                "peak_count": int(peak.get("main_theme_sealed_count") or 0),
                "divergence_date": _first_stage_date(
                    ordered,
                    {CyclePhase.DIVERGENCE.value},
                ),
                "reflux_date": _first_stage_date(
                    ordered,
                    {CyclePhase.REFLUX.value},
                ),
                "end_date": next(
                    (
                        _date_text(row.get("theme_cycle_end_date"))
                        for row in reversed(ordered)
                        if row.get("theme_cycle_end_date") is not None
                    ),
                    "open",
                ),
                "propagation_days": next(
                    (
                        int(row.get("theme_propagation_days") or 0)
                        for row in reversed(ordered)
                        if row.get("theme_propagation_days") is not None
                    ),
                    "-",
                ),
                "evidence_level": "/".join(evidence),
            }
        )
    return summaries


def _summarize_role_tenures(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        for role in row.get("role_groups", ()):
            if not isinstance(role, Mapping):
                continue
            symbol = str(role.get("vt_symbol") or "")
            if symbol:
                grouped[(symbol, str(role.get("name") or symbol))].append(
                    {**dict(role), "trade_date": row.get("trade_date")}
                )
    summaries = []
    for (_, name), role_rows in grouped.items():
        ordered = sorted(role_rows, key=lambda row: _date_value(row.get("trade_date")) or date.min)
        summaries.append(
            {
                "name": name,
                "roles": "/".join(
                    sorted(
                        {
                            str(value)
                            for row in ordered
                            for value in row.get("roles", ())
                            if str(value)
                        }
                    )
                ),
                "first_date": _date_text(ordered[0].get("trade_date")),
                "last_date": _date_text(ordered[-1].get("trade_date")),
                "role_days": len(ordered),
                "maximum_board_height": max(
                    (int(row.get("board_spell_days") or 0) for row in ordered),
                    default=0,
                ),
                "maximum_leadership_tenure": max(
                    (int(row.get("leadership_tenure_days") or 0) for row in ordered),
                    default=0,
                ),
            }
        )
    return sorted(
        summaries,
        key=lambda row: (
            -int(row["maximum_board_height"]),
            -int(row["role_days"]),
            str(row["name"]),
        ),
    )


def _first_stage_date(
    rows: Sequence[Mapping[str, object]],
    stages: set[str],
) -> str:
    return next(
        (
            _date_text(row.get("trade_date"))
            for row in rows
            if str(row.get("theme_stage") or "") in stages
        ),
        "-",
    )


def _snapshot_metrics(
    symbols: set[str],
    moment: datetime,
    index: Mapping[tuple[str, datetime], Mapping[str, object]],
) -> dict[str, float]:
    rows = [index[(symbol, moment)] for symbol in symbols if (symbol, moment) in index]
    changes = [_change_pct(row) for row in rows]
    valid_changes = [value for value in changes if value is not None]
    return {
        "rise_count": float(sum(value > 0 for value in valid_changes)),
        "strong_3_count": float(sum(value >= 3 for value in valid_changes)),
        "strong_5_count": float(sum(value >= 5 for value in valid_changes)),
        "strong_7_count": float(sum(value >= 7 for value in valid_changes)),
        "near_limit_count": float(sum(value >= 9 for value in valid_changes)),
        "touched_count": float(sum(bool(row.get("touched")) or (_high_change(row) or -99) >= 9.5 for row in rows)),
        "sealed_count": float(sum(bool(row.get("sealed")) or (_change_pct(row) or -99) >= 9.5 for row in rows)),
        "failed_count": float(sum(bool(row.get("failed")) for row in rows)),
        "median_change_pct": float(median(valid_changes)) if valid_changes else 0.0,
        "turnover": sum(_number(row.get("turnover")) or 0.0 for row in rows),
        "main_net_inflow": sum(_number(row.get("main_net_inflow")) or 0.0 for row in rows),
    }


def _metric_delta(
    baseline: Mapping[str, float],
    target: Mapping[str, float],
    metric: str,
) -> float:
    return float(target.get(metric, 0.0)) - float(baseline.get(metric, 0.0))


def _minute_row_index(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, datetime], dict[str, object]]:
    result: dict[tuple[str, datetime], dict[str, object]] = {}
    for row in rows:
        moment = _datetime_value(row.get("bar_time"))
        symbol = str(row.get("vt_symbol") or "")
        if moment and symbol:
            result[(symbol, moment.replace(second=0, microsecond=0))] = dict(row)
    return result


def _required_times(ignition_at: datetime) -> tuple[datetime, ...]:
    anchor = ignition_at.replace(second=0, microsecond=0)
    return (anchor - timedelta(minutes=1),) + tuple(
        anchor + timedelta(minutes=horizon) for horizon in PROPAGATION_HORIZONS_MINUTES
    )


def _change_pct(row: Mapping[str, object]) -> float | None:
    value = _number(row.get("change_pct"))
    if value is not None:
        return value
    close = _number(row.get("close_price"))
    previous = _number(row.get("previous_close"))
    return (close / previous - 1) * 100 if close is not None and previous else None


def _high_change(row: Mapping[str, object]) -> float | None:
    high = _number(row.get("high_price"))
    previous = _number(row.get("previous_close"))
    return (high / previous - 1) * 100 if high is not None and previous else _change_pct(row)


def _golden_case_lines(ledger: Sequence[Mapping[str, object]]) -> list[str]:
    names = defaultdict(list)
    july_ledger = [
        row
        for row in ledger
        if (trade_date := _date_value(row.get("trade_date"))) is not None
        and trade_date.year == 2026
        and trade_date.month == 7
    ]
    for row in july_ledger:
        for role in row.get("role_groups", ()):
            if isinstance(role, Mapping):
                names[str(role.get("name") or "")].append(row)
    expected = ("恒尚节能", "哈药股份", "立新能源")
    lines = ["", "## July golden cases", ""]
    for name in expected:
        rows = names.get(name, [])
        failed_rows = [
            row
            for row in july_ledger
            if any(
                isinstance(item, Mapping) and item.get("name") == name
                for item in row.get("failed_touch_group", ())
            )
        ]
        if not rows:
            if not failed_rows:
                lines.append(f"- {name}：`not_observed_in_loaded_rows`。")
                continue
            failed_dates = sorted(
                {_date_text(row.get("trade_date")) for row in failed_rows}
            )
            lines.append(
                f"- {name}：仅观察到触板未封日 `{'/'.join(failed_dates)}`，无有效封板任期。"
            )
            continue
        first = _date_text(rows[0].get("trade_date"))
        last = _date_text(rows[-1].get("trade_date"))
        observations = [
            {**dict(item), "trade_date": row.get("trade_date")}
            for row in rows
            for item in row.get("role_groups", ())
            if isinstance(item, Mapping) and item.get("name") == name
        ]
        roles = sorted(
            {
                role
                for row in rows
                for item in row.get("role_groups", ())
                if isinstance(item, Mapping) and item.get("name") == name
                for role in item.get("roles", ())
            }
        )
        dates = sorted({_date_text(row.get("trade_date")) for row in rows})
        failed_dates = sorted(
            {_date_text(row.get("trade_date")) for row in failed_rows}
        )
        maximum_board = max(
            (int(item.get("board_spell_days") or 0) for item in observations),
            default=0,
        )
        maximum_tenure = max(
            (int(item.get("leadership_tenure_days") or 0) for item in observations),
            default=0,
        )
        evidence = sorted(
            {str(row.get("membership_evidence_level") or "unavailable") for row in rows}
        )
        paths = " -> ".join(
            f"{_date_text(row.get('trade_date'))}:{row.get('theme_stage') or 'unavailable'}"
            for row in rows
        )
        board_path = " -> ".join(
            f"{_date_text(item.get('trade_date'))}:{int(item.get('board_spell_days') or 0)}板"
            for item in observations
        )
        lines.append(
            f"- {name}：`{first}` 至 `{last}`，实际封板日 `{'/'.join(dates)}`，"
            f"最高有效 `{maximum_board}` 板，最长最高板任期 `{maximum_tenure}` 日，"
            f"角色 `{'/'.join(roles) or 'ordinary'}`，成员证据 `{'/'.join(evidence)}`；"
            f"有效板路径 `{board_path}`；市场主线阶段 `{paths}`；"
            f"触板未封日 `{'/'.join(failed_dates) or '无'}`。"
        )
    july_seven_to_nine = [
        row
        for row in july_ledger
        if _date_value(row.get("trade_date"))
        in {date(2026, 7, 7), date(2026, 7, 8), date(2026, 7, 9)}
    ]
    for row in july_seven_to_nine:
        leaders = "/".join(
            str(item.get("name") or item.get("vt_symbol") or "")
            for item in row.get("highest_board_group", ())
        ) or "无"
        fund = row.get("instant_fund_main_attack")
        fund_name = (
            str(fund.get("group_name") or "无")
            if isinstance(fund, Mapping)
            else "无盘中资金证据"
        )
        lines.append(
            f"- {_date_text(row.get('trade_date'))}：最高板 `{leaders}`；资金主攻 `{fund_name}`；"
            f"两条线独立保存，未强行指定统一龙头。"
        )
    return lines


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(SHANGHAI).replace(tzinfo=None) if parsed.tzinfo else parsed


def _time_value(value: object) -> time | None:
    try:
        return time.fromisoformat(str(value or "")[:8])
    except ValueError:
        return None


def _date_text(value: object) -> str:
    parsed = _date_value(value)
    return parsed.isoformat() if parsed else "-"


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _pct(value: object) -> str:
    number = _number(value)
    return f"{number * 100:.2f}%" if number is not None else "-"


def _bool_text(value: object) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return "未知"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("daily", "intraday"), default="daily")
    parser.add_argument("--coverage-only", action="store_true")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)

    if arguments.coverage_only or arguments.mode == "daily":
        payload = load_leader_cycle_inputs(
            arguments.start,
            arguments.end,
            compact=True,
        )
        if arguments.coverage_only:
            report = render_coverage_report(payload)
        else:
            report = render_daily_report(
                build_daily_cycle_ledger(payload),
                payload.get("coverage") or (),
                payload.get("supply_capabilities")
                if isinstance(payload.get("supply_capabilities"), Mapping)
                else {},
            )
    else:
        dates = load_market_trade_dates(arguments.start, arguments.end)
        payload = load_intraday_propagation_inputs(dates)
        events = build_ignition_events(payload)
        preliminary = evaluate_propagation_coverage(
            {
                **payload,
                "events": [{**event, "control_available": True} for event in events],
            }
        )
        control_candidate_ids = {
            event.get("ignition_cluster_id")
            for event in preliminary["accepted_events"]
        }
        minute_index = _minute_row_index(_dict_rows(payload.get("minute_bars")))
        control_payload = {
            **payload,
            "_minute_row_index": minute_index,
            "_minute_symbols": sorted({symbol for symbol, _ in minute_index}),
        }
        controls = [
            control
            for event in events
            if event.get("ignition_cluster_id") in control_candidate_ids
            and (control := match_market_controls(event, control_payload))
        ]
        control_by_event = {control["ignition_cluster_id"]: control for control in controls}
        events_with_controls = [
            {**event, **control_by_event.get(event["ignition_cluster_id"], {})}
            for event in events
        ]
        coverage = evaluate_propagation_coverage(
            {**payload, "events": events_with_controls, "market_controls": controls}
        )
        accepted = [
            {**event, **control_by_event.get(event["ignition_cluster_id"], {})}
            for event in coverage["accepted_events"]
        ]
        report = render_intraday_report(
            coverage,
            build_propagation_panel(accepted, payload),
        )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
