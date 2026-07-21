"""Causal validation for the 3% and 5% first-board radar contracts."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from statistics import mean, median
from zoneinfo import ZoneInfo

from sqlalchemy import select, tuple_

from alphaagent.market.cache import TTLCache
from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.execution import cash_ledger
from alphaagent.server.services.limit_up import (
    cash_backtest,
    radar_observation_repository,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.radar_contract import (
    PRODUCTION_RADAR_CONTRACT,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
VALIDATION_VERSION = "limit-up-radar-validation-v1"
RESEARCH_PREPARE_STATE = "research_prepare"
RESEARCH_ACTION_STATE = "research_action"
RESEARCH_EXECUTION_EFFECT = "none_research_only"
CONTRACT_ACTION_FIELDS = {
    "formal_5pct": "formal_action",
    "early_3pct_same_rules": "early_action",
}
ENTRY_DELAY_SECONDS = 20
MAX_ENTRY_DELAY_SECONDS = 60
REFERENCE_POSITION_CASH = 50_000.0
FULL_SESSION_MINUTE_SLOTS = frozenset(
    {
        f"{minute // 60:02d}:{minute % 60:02d}"
        for minute in range(9 * 60 + 31, 11 * 60 + 31)
    }
    | {
        f"{minute // 60:02d}:{minute % 60:02d}"
        for minute in range(13 * 60 + 1, 15 * 60 + 1)
    }
)
FULL_SESSION_MINUTE_COUNT = len(FULL_SESSION_MINUTE_SLOTS)
FAST_PATH_MAX_5_TO_LIMIT_MINUTES = 2
COVERAGE_GATE = {
    "complete_trade_days": 60,
    "closed_early_recommendations": 300,
    "minimum_signal_days": 40,
    "minute_pair_coverage_pct": 95.0,
    "valid_frame_ratio_pct": 98.0,
    "scan_gap_p90_seconds_max": 20.0,
}
RELIABILITY_GATE = {
    "win_rate_pct_min": 60.0,
    "average_net_return_pct_min": 1.0,
    "profit_factor_min": 1.5,
    "max_drawdown_pct_min": -15.0,
    "double_cost_profit_factor_min": 1.2,
    "positive_chronological_blocks_min": 4,
    "chronological_block_count": 5,
    "max_single_date_profit_share_pct": 15.0,
}
COMPARISON_GATE = {
    "max_win_rate_regression_pp": 2.0,
    "max_average_return_regression_pp": 0.20,
    "minimum_fast_path_caught_two_minutes_early_pct": 50.0,
    "minimum_queue_unknown_reduction_pct": 20.0,
}
_REPORT_CACHE = TTLCache(max_items=2)


def build_read_only_research_event(
    row: Mapping[str, object],
    *,
    state: str,
    prepare_score_field: str,
    action_score_field: str,
) -> dict[str, object]:
    """Project a scored row without creating an executable recommendation."""

    if state not in {RESEARCH_PREPARE_STATE, RESEARCH_ACTION_STATE}:
        raise ValueError(f"unsupported research state: {state}")
    captured_at = _as_datetime(row.get("captured_at"))
    signal_date = _as_date(row.get("signal_date") or row.get("trade_date"))
    return {
        "research_state": state,
        "vt_symbol": str(row.get("vt_symbol") or ""),
        "signal_date": signal_date.isoformat() if signal_date is not None else None,
        "signal_time": str(row.get("signal_time") or ""),
        "captured_at": captured_at.isoformat() if captured_at is not None else None,
        "prepare_score": _number(row.get(prepare_score_field)),
        "action_score": _number(row.get(action_score_field)),
        "execution_effect": RESEARCH_EXECUTION_EFFECT,
        "actionable": False,
    }


def first_signal(
    rows: Sequence[Mapping[str, object]],
    action_field: str,
) -> dict[str, object] | None:
    """Return the first decision that passed, without looking at later ranks."""

    for row in sorted(rows, key=_observation_sort_key):
        if str(row.get(action_field) or "pass") == "buy_now":
            return dict(row)
    return None


def first_delayed_quote(
    quotes: Sequence[Mapping[str, object]],
    signal_at: datetime,
    *,
    delay_seconds: int = ENTRY_DELAY_SECONDS,
    max_delay_seconds: int = MAX_ENTRY_DELAY_SECONDS,
) -> dict[str, object] | None:
    """Return the first valid saved quote in the causal fill window."""

    signal_time = _as_datetime(signal_at)
    if signal_time is None:
        return None
    signal_window = _entry_window_index(signal_time)
    if signal_window is None:
        return None
    for quote in sorted(quotes, key=_observation_sort_key):
        quote_time = _as_datetime(quote.get("captured_at"))
        price = _number(quote.get("last_price"))
        if quote_time is None or price is None or price <= 0:
            continue
        elapsed = (quote_time - signal_time).total_seconds()
        if elapsed < delay_seconds:
            continue
        if elapsed > max_delay_seconds:
            break
        if _entry_window_index(quote_time) != signal_window:
            continue
        return dict(quote)
    return None


def build_radar_validation_report(
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    minute_bars: Sequence[Mapping[str, object]],
    *,
    trade_calendar: Sequence[date | str] | None = None,
) -> dict[str, object]:
    """Compare the frozen 5% and 3% contracts on the same saved frames."""

    observation_rows = [dict(row) for row in observations]
    frame_rows = [dict(row) for row in frames] or _frames_from_observations(
        observation_rows
    )
    bar_rows = [dict(row) for row in daily_bars]
    calendar = _trade_calendar(bar_rows, trade_calendar)
    minute_rows = [dict(row) for row in minute_bars]
    coverage = build_validation_coverage(
        frame_rows,
        observation_rows,
        minute_rows,
    )
    complete_dates = [
        parsed
        for value in coverage.get("complete_day_dates") or []
        if (parsed := _as_date(value)) is not None
    ]
    evaluation_dates = complete_dates[: COVERAGE_GATE["complete_trade_days"]]
    evaluation_date_set = set(evaluation_dates)
    evaluation_observations = _rows_for_dates(
        observation_rows,
        evaluation_date_set,
    )
    evaluation_minutes = _rows_for_dates(minute_rows, evaluation_date_set)
    evaluation_scope = _evaluation_scope_coverage(
        frame_rows,
        evaluation_observations,
        evaluation_minutes,
        evaluation_dates,
    )
    evaluation_day_dates = [value.isoformat() for value in evaluation_dates]
    coverage.update(
        {
            "evaluation_trade_days": len(evaluation_dates),
            "evaluation_day_dates": evaluation_day_dates,
            "evaluation_cohort_frozen": (
                len(complete_dates) >= COVERAGE_GATE["complete_trade_days"]
            ),
            "evaluation_cohort_id": _evaluation_cohort_id(
                evaluation_day_dates
            ),
            "excluded_complete_day_count": max(
                len(complete_dates) - len(evaluation_dates),
                0,
            ),
            "evaluation_scope": evaluation_scope,
        }
    )
    grouped = _group_observations(evaluation_observations)
    contracts: dict[str, dict[str, object]] = {}
    raw_signals: dict[str, list[dict[str, object]]] = {}

    for contract, action_field in CONTRACT_ACTION_FIELDS.items():
        signals = _extract_first_signals(grouped, action_field, contract)
        orders = _settle_signals(signals, grouped, bar_rows, calendar)
        raw_signals[contract] = signals
        contracts[contract] = {
            "signals": signals,
            "orders": orders,
            "all_recommendations": _recommendation_metrics(signals, orders),
            "two_position_account": _two_position_account(
                orders,
                bar_rows,
                calendar,
            ),
        }

    reaction_time = build_reaction_time_report(
        evaluation_observations,
        evaluation_minutes,
    )
    comparison = _contract_comparison(contracts)
    early_orders = contracts["early_3pct_same_rules"]["orders"]
    chronological_blocks = _chronological_blocks(
        [row for row in early_orders if row.get("status") == "closed"],
        block_count=5,
    )
    acceptance = evaluate_radar_acceptance(
        coverage=evaluation_scope,
        early_metrics=contracts["early_3pct_same_rules"]["all_recommendations"],
        formal_metrics=contracts["formal_5pct"]["all_recommendations"],
        comparison=comparison,
        reaction_time=reaction_time,
        chronological_blocks=chronological_blocks,
    )
    acceptance["evaluation_cohort_id"] = coverage["evaluation_cohort_id"]
    acceptance["evaluation_day_dates"] = evaluation_day_dates
    status = str(acceptance["status"])
    return {
        "validation_version": VALIDATION_VERSION,
        "status": status,
        "contracts": contracts,
        "signals": raw_signals,
        "coverage": coverage,
        "reaction_time": reaction_time,
        "comparison": comparison,
        "chronological_blocks": chronological_blocks,
        "acceptance": acceptance,
        "limitations": [
            "信号只取同股同日第一次真实通过，不使用日终Top1或后来排名。",
            "买价只使用同一买入窗口内决策20至60秒后的首条已保存报价；缺失即剔除。",
            "买点后跌回3%以下仍只跟踪该股至60秒用于成交计价，不重新参与推荐。",
            "报价已到涨停价时缺少L2排队成交证据，标记queue_unknown_without_l2且不计为成交。",
            "卖价只使用下一官方交易日收盘价；缺失或非正价格不替代、不插值。",
            "完整分钟路径只认09:31至11:30和13:01至15:00的240个去重分钟槽位。",
            "分钟线用于反应时间，不证明涨停队列中的实际成交。",
            "验收只使用按日期排序的首批60个完整交易日；后续完整日不改变首轮队列。",
        ],
    }


def evaluate_radar_acceptance(
    *,
    coverage: Mapping[str, object],
    early_metrics: Mapping[str, object],
    formal_metrics: Mapping[str, object],
    comparison: Mapping[str, object],
    reaction_time: Mapping[str, object],
    chronological_blocks: Sequence[Mapping[str, object]],
    production_contract: str | None = None,
) -> dict[str, object]:
    """Apply frozen fail-closed gates without a compensating composite score."""

    gates: list[dict[str, object]] = []

    def add(key: str, passed: bool, current: object, required: str) -> None:
        gates.append(
            {
                "key": key,
                "passed": bool(passed),
                "current": current,
                "required": required,
            }
        )

    complete_days = _number(coverage.get("complete_trade_days"))
    closed_count = _number(early_metrics.get("closed_count"))
    signal_days = _number(
        early_metrics.get("days_with_at_least_one_recommendation")
    )
    minute_coverage = _number(coverage.get("minute_pair_coverage_pct"))
    valid_frame_ratio = _number(coverage.get("valid_frame_ratio_pct"))
    scan_gap_p90 = _number(coverage.get("scan_gap_p90_seconds"))
    add(
        "complete_trade_days",
        _at_least(complete_days, COVERAGE_GATE["complete_trade_days"]),
        complete_days,
        f">= {COVERAGE_GATE['complete_trade_days']}",
    )
    add(
        "closed_early_recommendations",
        _at_least(
            closed_count,
            COVERAGE_GATE["closed_early_recommendations"],
        ),
        closed_count,
        f">= {COVERAGE_GATE['closed_early_recommendations']}",
    )
    add(
        "minimum_signal_days",
        _at_least(signal_days, COVERAGE_GATE["minimum_signal_days"]),
        signal_days,
        f">= {COVERAGE_GATE['minimum_signal_days']}",
    )
    add(
        "minute_pair_coverage_pct",
        _at_least(
            minute_coverage,
            COVERAGE_GATE["minute_pair_coverage_pct"],
        ),
        minute_coverage,
        f">= {COVERAGE_GATE['minute_pair_coverage_pct']}%",
    )
    add(
        "valid_frame_ratio_pct",
        _at_least(valid_frame_ratio, COVERAGE_GATE["valid_frame_ratio_pct"]),
        valid_frame_ratio,
        f">= {COVERAGE_GATE['valid_frame_ratio_pct']}%",
    )
    add(
        "scan_gap_p90_seconds",
        _at_most(scan_gap_p90, COVERAGE_GATE["scan_gap_p90_seconds_max"]),
        scan_gap_p90,
        f"<= {COVERAGE_GATE['scan_gap_p90_seconds_max']}s",
    )

    early_pending = _number(early_metrics.get("awaiting_d1_close_count"))
    formal_pending = _number(formal_metrics.get("awaiting_d1_close_count"))
    pending_settlements = (
        early_pending + formal_pending
        if early_pending is not None and formal_pending is not None
        else None
    )
    add(
        "pending_d1_settlements",
        _at_most(pending_settlements, 0),
        pending_settlements,
        "= 0",
    )

    win_rate = _number(early_metrics.get("win_rate_pct"))
    average_return = _number(early_metrics.get("average_net_return_pct"))
    profit_factor = _number(early_metrics.get("profit_factor"))
    loss_count = _number(early_metrics.get("loss_count"))
    max_drawdown = _number(early_metrics.get("max_drawdown_pct"))
    double_profit_factor = _number(
        early_metrics.get("double_cost_profit_factor")
    )
    double_loss_count = _number(early_metrics.get("double_cost_loss_count"))
    max_date_share = _number(
        early_metrics.get("max_single_date_profit_share_pct")
    )
    add(
        "win_rate_pct",
        _at_least(win_rate, RELIABILITY_GATE["win_rate_pct_min"]),
        win_rate,
        f">= {RELIABILITY_GATE['win_rate_pct_min']}%",
    )
    add(
        "average_net_return_pct",
        _at_least(
            average_return,
            RELIABILITY_GATE["average_net_return_pct_min"],
        ),
        average_return,
        f">= {RELIABILITY_GATE['average_net_return_pct_min']}%",
    )
    add(
        "profit_factor",
        _profit_factor_passes(
            profit_factor,
            loss_count,
            RELIABILITY_GATE["profit_factor_min"],
            closed_count,
        ),
        profit_factor,
        f">= {RELIABILITY_GATE['profit_factor_min']}",
    )
    add(
        "max_drawdown_pct",
        _at_least(
            max_drawdown,
            RELIABILITY_GATE["max_drawdown_pct_min"],
        ),
        max_drawdown,
        f">= {RELIABILITY_GATE['max_drawdown_pct_min']}%",
    )
    add(
        "double_cost_profit_factor",
        _profit_factor_passes(
            double_profit_factor,
            double_loss_count,
            RELIABILITY_GATE["double_cost_profit_factor_min"],
            closed_count,
        ),
        double_profit_factor,
        f">= {RELIABILITY_GATE['double_cost_profit_factor_min']}",
    )
    add(
        "max_single_date_profit_share_pct",
        _at_most(
            max_date_share,
            RELIABILITY_GATE["max_single_date_profit_share_pct"],
        ),
        max_date_share,
        f"<= {RELIABILITY_GATE['max_single_date_profit_share_pct']}%",
    )

    expected_blocks = int(RELIABILITY_GATE["chronological_block_count"])
    positive_blocks = sum(
        bool(block.get("positive"))
        and (_number(block.get("average_net_return_pct")) or 0) > 0
        for block in chronological_blocks
    )
    sizes_pass = len(chronological_blocks) == expected_blocks and all(
        _at_least(_number(block.get("closed_count")), 40)
        for block in chronological_blocks
    )
    block_profit_factors_pass = (
        len(chronological_blocks) == expected_blocks
        and all(_block_profit_factor_passes(block) for block in chronological_blocks)
    )
    add(
        "chronological_block_count",
        len(chronological_blocks) == expected_blocks,
        len(chronological_blocks),
        f"= {expected_blocks}",
    )
    add(
        "chronological_block_size",
        sizes_pass,
        min(
            (int(block.get("closed_count") or 0) for block in chronological_blocks),
            default=0,
        ),
        ">= 40 each",
    )
    add(
        "positive_chronological_blocks",
        positive_blocks
        >= int(RELIABILITY_GATE["positive_chronological_blocks_min"]),
        positive_blocks,
        f">= {RELIABILITY_GATE['positive_chronological_blocks_min']}",
    )
    add(
        "chronological_block_profit_factor",
        block_profit_factors_pass,
        [block.get("profit_factor") for block in chronological_blocks],
        ">= 1.0 each",
    )

    win_delta = _number(comparison.get("early_minus_formal_win_rate_pp"))
    if win_delta is None:
        win_delta = _difference(
            early_metrics.get("win_rate_pct"), formal_metrics.get("win_rate_pct")
        )
    average_delta = _number(
        comparison.get("early_minus_formal_average_return_pp")
    )
    if average_delta is None:
        average_delta = _difference(
            early_metrics.get("average_net_return_pct"),
            formal_metrics.get("average_net_return_pct"),
        )
    queue_reduction = _number(comparison.get("queue_unknown_reduction_pct"))
    fast_path_caught = _number(
        reaction_time.get("fast_path_caught_two_minutes_early_pct")
    )
    add(
        "win_rate_regression_pp",
        _at_least(
            win_delta,
            -COMPARISON_GATE["max_win_rate_regression_pp"],
        ),
        win_delta,
        f">= -{COMPARISON_GATE['max_win_rate_regression_pp']}pp",
    )
    add(
        "average_return_regression_pp",
        _at_least(
            average_delta,
            -COMPARISON_GATE["max_average_return_regression_pp"],
        ),
        average_delta,
        f">= -{COMPARISON_GATE['max_average_return_regression_pp']}pp",
    )
    add(
        "fast_path_caught_two_minutes_early_pct",
        _at_least(
            fast_path_caught,
            COMPARISON_GATE["minimum_fast_path_caught_two_minutes_early_pct"],
        ),
        fast_path_caught,
        f">= {COMPARISON_GATE['minimum_fast_path_caught_two_minutes_early_pct']}%",
    )
    add(
        "queue_unknown_reduction_pct",
        _at_least(
            queue_reduction,
            COMPARISON_GATE["minimum_queue_unknown_reduction_pct"],
        ),
        queue_reduction,
        f">= {COMPARISON_GATE['minimum_queue_unknown_reduction_pct']}%",
    )

    failed = [str(gate["key"]) for gate in gates if not gate["passed"]]
    complete_day_count = int(complete_days or 0)
    if complete_day_count < 20:
        status = "collecting"
    elif complete_day_count < COVERAGE_GATE["complete_trade_days"]:
        status = "process_ready"
    elif pending_settlements is not None and pending_settlements > 0:
        status = "ready_for_review"
    else:
        status = "accepted" if not failed else "rejected"
    accepted = status == "accepted"
    recommended_contract = (
        "early_3pct_same_rules" if accepted else "formal_5pct"
    )
    active_contract = production_contract or _production_radar_contract()
    if active_contract not in CONTRACT_ACTION_FIELDS:
        raise ValueError(f"Unsupported production radar contract: {active_contract}")
    production_mismatch = active_contract != recommended_contract
    return {
        "status": status,
        "eligible_for_activation": accepted,
        "recommended_contract": recommended_contract,
        "production_contract": active_contract,
        "selected_contract": active_contract,
        "activation_required": accepted and production_mismatch,
        "production_contract_mismatch": production_mismatch,
        "failed_gate_keys": failed,
        "gates": gates,
    }


def build_reaction_time_report(
    observations: Sequence[Mapping[str, object]],
    minute_bars: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    observed = _observed_pair_context(observations)
    grouped_bars: dict[tuple[str, date], list[dict[str, object]]] = defaultdict(list)
    for raw in minute_bars:
        if str(raw.get("interval") or "1m") != "1m":
            continue
        pair = _symbol_date_pair(raw)
        if pair is not None:
            grouped_bars[pair].append(dict(raw))

    paths: list[dict[str, object]] = []
    for pair in sorted(observed, key=lambda item: (item[1], item[0])):
        context = observed[pair]
        previous_close = _number(context.get("previous_close"))
        limit_price = _number(context.get("limit_price"))
        bars = sorted(grouped_bars.get(pair, []), key=_minute_sort_key)
        if previous_close is None or previous_close <= 0 or not bars:
            continue
        limit_price = limit_price or previous_close * 1.10
        index_3 = _first_touch_index(bars, previous_close * 1.03)
        index_5 = _first_touch_index(bars, previous_close * 1.05)
        index_limit = _first_touch_index(bars, limit_price)
        lead_3 = _lead_minutes(index_3, index_limit)
        lead_5 = _lead_minutes(index_5, index_limit)
        pre_range = _previous_range_pct(bars, index_limit, previous_close)
        fast_path = (
            lead_5 is not None
            and lead_5 <= FAST_PATH_MAX_5_TO_LIMIT_MINUTES
        )
        paths.append(
            {
                "trade_date": pair[1].isoformat(),
                "vt_symbol": pair[0],
                "first_3pct_at": _bar_time_at(bars, index_3),
                "first_5pct_at": _bar_time_at(bars, index_5),
                "first_limit_touch_at": _bar_time_at(bars, index_limit),
                "lead_minutes_3pct_to_limit": lead_3,
                "lead_minutes_5pct_to_limit": lead_5,
                "previous_30m_range_pct": pre_range,
                "fast_path": fast_path,
                "caught_at_least_two_minutes_early": (
                    lead_3 is not None and lead_3 >= 2
                ),
            }
        )

    touched = [row for row in paths if row["first_limit_touch_at"] is not None]
    caught = [
        row
        for row in touched
        if row["caught_at_least_two_minutes_early"] is True
    ]
    fast = [row for row in touched if row["fast_path"] is True]
    fast_caught = [
        row
        for row in fast
        if row["caught_at_least_two_minutes_early"] is True
    ]
    return {
        "fast_path_definition": (
            "first_5pct_to_limit_touch_lte_2_trading_minutes"
        ),
        "path_count": len(paths),
        "limit_touch_count": len(touched),
        "caught_at_least_two_minutes_early_count": len(caught),
        "caught_at_least_two_minutes_early_pct": _ratio_pct(
            len(caught), len(touched)
        ),
        "fast_path_count": len(fast),
        "fast_path_caught_two_minutes_early_count": len(fast_caught),
        "fast_path_caught_two_minutes_early_pct": _ratio_pct(
            len(fast_caught), len(fast)
        ),
        "paths": paths,
    }


def build_validation_coverage(
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
    minute_bars: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    frame_rows = [dict(row) for row in frames]
    observations_by_day: dict[date, set[tuple[str, date]]] = defaultdict(set)
    for row in observations:
        pair = _symbol_date_pair(row)
        if pair is not None:
            observations_by_day[pair[1]].add(pair)
    minute_slots = _minute_slots_by_pair(minute_bars)

    frames_by_day: dict[date, list[dict[str, object]]] = defaultdict(list)
    for frame in frame_rows:
        frame_date = _as_date(frame.get("trade_date"))
        if frame_date is not None:
            frames_by_day[frame_date].append(frame)

    valid_count = sum(_valid_frame(frame) for frame in frame_rows)
    observed_pairs = set().union(*observations_by_day.values()) if observations_by_day else set()
    complete_pairs = {
        pair
        for pair in observed_pairs
        if _has_full_session_minute_path(minute_slots.get(pair, set()))
    }
    complete_days: list[str] = []
    daily_rows: list[dict[str, object]] = []
    for trade_date in sorted(frames_by_day):
        day_frames = frames_by_day[trade_date]
        valid_frames = [frame for frame in day_frames if _valid_frame(frame)]
        valid_ratio = len(valid_frames) / len(day_frames) if day_frames else 0.0
        window_indexes = {
            index
            for frame in valid_frames
            if (index := _entry_window_index(frame.get("captured_at"))) is not None
        }
        day_pairs = observations_by_day.get(trade_date, set())
        day_complete_pairs = {
            pair
            for pair in day_pairs
            if _has_full_session_minute_path(minute_slots.get(pair, set()))
        }
        day_scan_gap_p90 = _nearest_rank_percentile(
            _scan_gaps_seconds(day_frames),
            0.90,
        )
        minute_coverage = (
            len(day_complete_pairs) / len(day_pairs) if day_pairs else 1.0
        )
        complete = (
            bool(day_frames)
            and valid_ratio >= 0.98
            and window_indexes == set(range(len(scheduled_execution.ENTRY_WINDOWS)))
            and minute_coverage >= 0.95
            and day_scan_gap_p90 is not None
            and day_scan_gap_p90
            <= COVERAGE_GATE["scan_gap_p90_seconds_max"]
        )
        if complete:
            complete_days.append(trade_date.isoformat())
        daily_rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "frame_count": len(day_frames),
                "valid_frame_ratio_pct": round(valid_ratio * 100, 4),
                "observed_pair_count": len(day_pairs),
                "complete_minute_pair_count": len(day_complete_pairs),
                "minute_pair_coverage_pct": round(minute_coverage * 100, 4),
                "scan_gap_p90_seconds": day_scan_gap_p90,
                "both_entry_windows_observed": window_indexes
                == set(range(len(scheduled_execution.ENTRY_WINDOWS))),
                "complete": complete,
            }
        )

    scan_gaps = _scan_gaps_seconds(frame_rows)
    return {
        "date_start": min(frames_by_day).isoformat() if frames_by_day else None,
        "date_end": max(frames_by_day).isoformat() if frames_by_day else None,
        "observed_trade_days": len(frames_by_day),
        "complete_trade_days": len(complete_days),
        "complete_day_dates": complete_days,
        "frame_count": len(frame_rows),
        "valid_frame_count": valid_count,
        "valid_frame_ratio_pct": _ratio_pct(valid_count, len(frame_rows)),
        "observed_minute_pair_count": len(observed_pairs),
        "complete_minute_pair_count": len(complete_pairs),
        "minute_pair_coverage_pct": _ratio_pct(
            len(complete_pairs), len(observed_pairs)
        ),
        "scan_gap_p90_seconds": _nearest_rank_percentile(scan_gaps, 0.90),
        "daily": daily_rows,
    }


def _evaluation_scope_coverage(
    frames: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
    minute_bars: Sequence[Mapping[str, object]],
    evaluation_dates: Sequence[date],
) -> dict[str, object]:
    date_set = set(evaluation_dates)
    scoped_frames = [
        dict(frame)
        for frame in frames
        if _as_date(frame.get("trade_date")) in date_set
    ]
    valid_count = sum(_valid_frame(frame) for frame in scoped_frames)
    observed_pairs = {
        pair
        for row in observations
        if (pair := _symbol_date_pair(row)) is not None
    }
    minute_slots = _minute_slots_by_pair(minute_bars)
    complete_pairs = {
        pair
        for pair in observed_pairs
        if _has_full_session_minute_path(minute_slots.get(pair, set()))
    }
    scan_gaps = _scan_gaps_seconds(scoped_frames)
    return {
        "date_start": evaluation_dates[0].isoformat() if evaluation_dates else None,
        "date_end": evaluation_dates[-1].isoformat() if evaluation_dates else None,
        "complete_trade_days": len(evaluation_dates),
        "frame_count": len(scoped_frames),
        "valid_frame_count": valid_count,
        "valid_frame_ratio_pct": _ratio_pct(valid_count, len(scoped_frames)),
        "observed_minute_pair_count": len(observed_pairs),
        "complete_minute_pair_count": len(complete_pairs),
        "minute_pair_coverage_pct": _ratio_pct(
            len(complete_pairs),
            len(observed_pairs),
        ),
        "scan_gap_p90_seconds": _nearest_rank_percentile(scan_gaps, 0.90),
    }


def _rows_for_dates(
    rows: Sequence[Mapping[str, object]],
    trade_dates: set[date],
) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in rows
        if (pair := _symbol_date_pair(row)) is not None and pair[1] in trade_dates
    ]


def _evaluation_cohort_id(trade_dates: Sequence[str]) -> str | None:
    if not trade_dates:
        return None
    payload = f"{VALIDATION_VERSION}:{','.join(trade_dates)}"
    return f"sha256:{sha256(payload.encode('ascii')).hexdigest()}"


def get_radar_validation() -> dict[str, object]:
    """Load saved evidence and build the report without fetching or writing data."""

    return _REPORT_CACHE.get_or_set(
        "current",
        60,
        _load_radar_validation,
    )


def _load_radar_validation() -> dict[str, object]:
    """Load one uncached report from persisted point-in-time evidence."""

    frame_table = schema.limit_up_radar_frames
    with session_scope() as session:
        bounds = session.execute(
            select(
                frame_table.c.trade_date.label("date_start"),
                frame_table.c.trade_date.label("date_end"),
            )
            .order_by(frame_table.c.trade_date)
            .limit(1)
        ).mappings().first()
        end_value = session.execute(
            select(frame_table.c.trade_date)
            .order_by(frame_table.c.trade_date.desc())
            .limit(1)
        ).scalar_one_or_none()
    if not bounds or end_value is None:
        return build_radar_validation_report([], [], [], [])

    start = _as_date(bounds["date_start"])
    end = _as_date(end_value)
    if start is None or end is None:
        return build_radar_validation_report([], [], [], [])
    frames = _load_frames(start, end)
    observations = radar_observation_repository.load_observations(start, end)
    symbols = sorted(
        {
            str(row.get("vt_symbol") or "")
            for row in observations
            if row.get("vt_symbol")
        }
    )
    if not symbols:
        return build_radar_validation_report(frames, observations, [], [])
    daily_bars, calendar, minute_bars = _load_market_evidence(
        symbols,
        observations,
        start,
        end,
    )
    return build_radar_validation_report(
        frames,
        observations,
        daily_bars,
        minute_bars,
        trade_calendar=calendar,
    )


def _extract_first_signals(
    grouped: Mapping[tuple[str, date], Sequence[Mapping[str, object]]],
    action_field: str,
    contract: str,
) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    for pair in sorted(grouped, key=lambda item: (item[1], item[0])):
        selected = first_signal(grouped[pair], action_field)
        if selected is None:
            continue
        captured_at = _as_datetime(selected.get("captured_at"))
        if captured_at is None:
            continue
        signals.append(
            {
                "contract": contract,
                "signal_date": pair[1].isoformat(),
                "captured_at": captured_at.isoformat(),
                "signal_time": captured_at.strftime("%H:%M:%S"),
                "vt_symbol": pair[0],
                "name": str(selected.get("name") or pair[0]),
                "last_price": _number(selected.get("last_price")),
                "previous_close": _number(selected.get("previous_close")),
                "limit_price": _number(selected.get("limit_price")),
                "board_lane": str(selected.get("board_lane") or "first_board"),
                "entry_quality_score": _number(
                    selected.get("entry_quality_score")
                ),
                "support_score": _number(selected.get("support_score")),
            }
        )
    return sorted(signals, key=_signal_sort_key)


def _settle_signals(
    signals: Sequence[Mapping[str, object]],
    grouped: Mapping[tuple[str, date], Sequence[Mapping[str, object]]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[date],
) -> list[dict[str, object]]:
    daily_index = {
        pair: dict(row)
        for row in daily_bars
        if (pair := _symbol_date_pair(row)) is not None
    }
    orders: list[dict[str, object]] = []
    for raw_signal in signals:
        signal = dict(raw_signal)
        signal_date = _as_date(signal.get("signal_date"))
        signal_at = _as_datetime(signal.get("captured_at"))
        symbol = str(signal.get("vt_symbol") or "")
        if signal_date is None or signal_at is None or not symbol:
            continue
        order = {**signal, "status": "entry_quote_missing"}
        fill_quote = first_delayed_quote(
            grouped.get((symbol, signal_date), []),
            signal_at,
        )
        if fill_quote is None:
            orders.append(order)
            continue
        fill_at = _as_datetime(fill_quote.get("captured_at"))
        entry_price = _number(fill_quote.get("last_price"))
        limit_price = _number(signal.get("limit_price"))
        order.update(
            entry_quote_at=fill_at.isoformat() if fill_at else None,
            entry_price_raw=entry_price,
        )
        if entry_price is None or entry_price <= 0:
            orders.append(order)
            continue
        if limit_price is not None and entry_price >= limit_price - 1e-9:
            order["status"] = "queue_unknown_without_l2"
            orders.append(order)
            continue
        result_date = _next_trade_date(calendar, signal_date)
        order["result_date"] = result_date.isoformat() if result_date else None
        if result_date is None:
            order["status"] = "awaiting_d1_close"
            orders.append(order)
            continue
        exit_bar = daily_index.get((symbol, result_date))
        exit_price = _number((exit_bar or {}).get("close_price"))
        if exit_price is None or exit_price <= 0:
            order["status"] = "d1_close_missing"
            orders.append(order)
            continue
        normal = _execution_outcome(
            entry_price,
            exit_price,
            limit_price=limit_price,
            cost_multiplier=1.0,
        )
        stress = _execution_outcome(
            entry_price,
            exit_price,
            limit_price=limit_price,
            cost_multiplier=2.0,
        )
        if normal is None or stress is None:
            order["status"] = "entry_below_one_lot"
            orders.append(order)
            continue
        order.update(
            status="closed",
            exit_price_raw=exit_price,
            net_return_pct=normal["net_return_pct"],
            double_cost_net_return_pct=stress["net_return_pct"],
            executed_entry_price=normal["entry_price"],
            executed_exit_price=normal["exit_price"],
        )
        orders.append(order)
    return orders


def _execution_outcome(
    entry_price: float,
    exit_price: float,
    *,
    limit_price: float | None,
    cost_multiplier: float,
) -> dict[str, float] | None:
    config = cash_backtest.CashBacktestConfig(
        max_positions=2,
        commission_rate=0.0003 * cost_multiplier,
        minimum_commission=5.0 * cost_multiplier,
        stamp_tax_rate=0.0005 * cost_multiplier,
        transfer_fee_rate=0.00001 * cost_multiplier,
        slippage_bps=10.0 * cost_multiplier,
    )
    buy = cash_ledger.calculate_buy_execution(
        raw_price=entry_price,
        cash=REFERENCE_POSITION_CASH,
        target_cash=REFERENCE_POSITION_CASH,
        commission_rate=config.commission_rate,
        slippage_bps=config.slippage_bps,
        lot_size=config.lot_size,
        minimum_commission=config.minimum_commission,
        transfer_fee_rate=config.transfer_fee_rate,
        max_price=limit_price,
    )
    if buy.volume <= 0:
        return None
    sell = cash_ledger.calculate_sell_execution(
        raw_price=exit_price,
        volume=buy.volume,
        cost_price=buy.price,
        commission_rate=config.commission_rate,
        stamp_tax_rate=config.stamp_tax_rate,
        slippage_bps=config.slippage_bps,
        minimum_commission=config.minimum_commission,
        transfer_fee_rate=config.transfer_fee_rate,
    )
    cash_cost = buy.amount + buy.fee
    net_pnl = sell.cash_delta - cash_cost
    return {
        "entry_price": round(buy.price, 6),
        "exit_price": round(sell.price, 6),
        "net_return_pct": round(net_pnl / cash_cost * 100, 4),
    }


def _recommendation_metrics(
    signals: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    closed = [row for row in orders if row.get("status") == "closed"]
    returns = [float(row["net_return_pct"]) for row in closed]
    stress_returns = [
        float(row["double_cost_net_return_pct"]) for row in closed
    ]
    daily_results, compound, drawdown = _daily_equal_weight_equity(closed)
    contribution, max_share = _profit_contribution_by_date(closed)
    status_counts = Counter(str(row.get("status") or "unknown") for row in orders)
    return {
        "signal_count": len(signals),
        "closed_count": len(closed),
        "win_count": sum(value > 0 for value in returns),
        "loss_count": sum(value < 0 for value in returns),
        "win_rate_pct": _ratio_pct(sum(value > 0 for value in returns), len(returns)),
        "average_net_return_pct": round(mean(returns), 4) if returns else None,
        "median_net_return_pct": round(median(returns), 4) if returns else None,
        "profit_factor": _profit_factor(returns),
        "daily_equal_weight_compound_return_pct": compound,
        "max_drawdown_pct": drawdown,
        "double_cost_average_net_return_pct": (
            round(mean(stress_returns), 4) if stress_returns else None
        ),
        "double_cost_profit_factor": _profit_factor(stress_returns),
        "double_cost_loss_count": sum(value < 0 for value in stress_returns),
        "queue_unknown_count": status_counts["queue_unknown_without_l2"],
        "entry_quote_missing_count": status_counts["entry_quote_missing"],
        "d1_close_missing_count": status_counts["d1_close_missing"],
        "awaiting_d1_close_count": status_counts["awaiting_d1_close"],
        "days_with_at_least_one_recommendation": len(
            {str(row.get("signal_date") or "") for row in signals}
        ),
        "status_counts": dict(status_counts),
        "daily_results": daily_results,
        "profit_contribution_by_date": contribution,
        "max_single_date_profit_share_pct": max_share,
    }


def _two_position_account(
    orders: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    calendar: Sequence[date],
) -> dict[str, object]:
    signals = []
    for order in orders:
        if order.get("status") != "closed":
            continue
        entry_at = _as_datetime(order.get("entry_quote_at"))
        signals.append(
            {
                "vt_symbol": order.get("vt_symbol"),
                "name": order.get("name"),
                "lane": "first_board",
                "entry_date": order.get("signal_date"),
                "result_date": order.get("result_date"),
                "buy_time": entry_at.strftime("%H:%M:%S") if entry_at else None,
                "entry_price": order.get("entry_price_raw"),
                "limit_price": order.get("limit_price"),
                "rank_score": order.get("entry_quality_score"),
            }
        )
    return cash_backtest.simulate_limit_up_account(
        signals,
        daily_bars,
        calendar,
        "next_close",
        config=cash_backtest.CashBacktestConfig(max_positions=2),
    )


def _contract_comparison(
    contracts: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    formal = contracts["formal_5pct"]["all_recommendations"]
    early = contracts["early_3pct_same_rules"]["all_recommendations"]
    formal = formal if isinstance(formal, Mapping) else {}
    early = early if isinstance(early, Mapping) else {}
    formal_signals = int(formal.get("signal_count") or 0)
    early_signals = int(early.get("signal_count") or 0)
    formal_queue_rate = (
        int(formal.get("queue_unknown_count") or 0) / formal_signals
        if formal_signals
        else None
    )
    early_queue_rate = (
        int(early.get("queue_unknown_count") or 0) / early_signals
        if early_signals
        else None
    )
    queue_reduction = (
        (formal_queue_rate - early_queue_rate) / formal_queue_rate * 100
        if formal_queue_rate not in (None, 0) and early_queue_rate is not None
        else None
    )
    return {
        "early_minus_formal_win_rate_pp": _difference(
            early.get("win_rate_pct"), formal.get("win_rate_pct")
        ),
        "early_minus_formal_average_return_pp": _difference(
            early.get("average_net_return_pct"),
            formal.get("average_net_return_pct"),
        ),
        "queue_unknown_reduction_pct": (
            round(queue_reduction, 4) if queue_reduction is not None else None
        ),
    }


def _chronological_blocks(
    closed_orders: Sequence[Mapping[str, object]],
    *,
    block_count: int,
) -> list[dict[str, object]]:
    ordered = sorted(closed_orders, key=_signal_sort_key)
    if not ordered:
        return []
    count = min(max(block_count, 1), len(ordered))
    quotient, remainder = divmod(len(ordered), count)
    blocks: list[dict[str, object]] = []
    offset = 0
    for index in range(count):
        size = quotient + (1 if index < remainder else 0)
        rows = ordered[offset : offset + size]
        offset += size
        returns = [float(row["net_return_pct"]) for row in rows]
        blocks.append(
            {
                "block": index + 1,
                "date_start": str(rows[0].get("signal_date") or ""),
                "date_end": str(rows[-1].get("signal_date") or ""),
                "closed_count": len(rows),
                "average_net_return_pct": round(mean(returns), 4),
                "profit_factor": _profit_factor(returns),
                "positive": mean(returns) > 0,
            }
        )
    return blocks


def _daily_equal_weight_equity(
    closed_orders: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], float, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in closed_orders:
        grouped[str(row.get("result_date") or "")].append(
            float(row["net_return_pct"])
        )
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    results: list[dict[str, object]] = []
    for result_date in sorted(grouped):
        daily_return = mean(grouped[result_date])
        equity *= 1 + daily_return / 100
        peak = max(peak, equity)
        drawdown = (equity / peak - 1) * 100
        max_drawdown = min(max_drawdown, drawdown)
        results.append(
            {
                "result_date": result_date,
                "trade_count": len(grouped[result_date]),
                "daily_return_pct": round(daily_return, 4),
                "equity": round(equity, 6),
                "drawdown_pct": round(drawdown, 4),
            }
        )
    return results, round((equity - 1) * 100, 4), round(max_drawdown, 4)


def _profit_contribution_by_date(
    closed_orders: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], float | None]:
    grouped: dict[str, float] = defaultdict(float)
    for row in closed_orders:
        grouped[str(row.get("signal_date") or "")] += float(
            row["net_return_pct"]
        )
    positive_total = sum(max(value, 0.0) for value in grouped.values())
    rows = [
        {
            "signal_date": signal_date,
            "net_return_sum_pct": round(value, 4),
            "positive_profit_share_pct": (
                round(max(value, 0.0) / positive_total * 100, 4)
                if positive_total
                else None
            ),
        }
        for signal_date, value in sorted(grouped.items())
    ]
    shares = [
        float(row["positive_profit_share_pct"])
        for row in rows
        if row["positive_profit_share_pct"] is not None
    ]
    return rows, max(shares, default=None)


def _group_observations(
    observations: Sequence[Mapping[str, object]],
) -> dict[tuple[str, date], list[dict[str, object]]]:
    grouped: dict[tuple[str, date], list[dict[str, object]]] = defaultdict(list)
    for raw in observations:
        pair = _symbol_date_pair(raw)
        if pair is not None:
            grouped[pair].append(dict(raw))
    for rows in grouped.values():
        rows.sort(key=_observation_sort_key)
    return dict(grouped)


def _minute_slots_by_pair(
    minute_bars: Sequence[Mapping[str, object]],
) -> dict[tuple[str, date], set[str]]:
    slots: dict[tuple[str, date], set[str]] = defaultdict(set)
    for row in minute_bars:
        if str(row.get("interval") or "1m") != "1m":
            continue
        pair = _symbol_date_pair(row)
        bar_at = _as_datetime(row.get("bar_time"))
        if pair is None or bar_at is None or bar_at.date() != pair[1]:
            continue
        slots[pair].add(bar_at.strftime("%H:%M"))
    return dict(slots)


def _has_full_session_minute_path(slots: set[str]) -> bool:
    return FULL_SESSION_MINUTE_SLOTS.issubset(slots)


def _observed_pair_context(
    observations: Sequence[Mapping[str, object]],
) -> dict[tuple[str, date], dict[str, object]]:
    result: dict[tuple[str, date], dict[str, object]] = {}
    for row in sorted(observations, key=_observation_sort_key):
        pair = _symbol_date_pair(row)
        if pair is not None and pair not in result:
            result[pair] = dict(row)
    return result


def _frames_from_observations(
    observations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for row in observations:
        captured_at = _as_datetime(row.get("captured_at"))
        if captured_at is None:
            continue
        key = captured_at.isoformat()
        result.setdefault(
            key,
            {
                "trade_date": row.get("trade_date") or captured_at.date(),
                "captured_at": key,
                "source_trade_date": row.get("source_trade_date"),
                "quality_status": row.get("quality_status"),
                "is_stale": row.get("is_stale"),
                "quote_coverage_ratio": row.get("quote_coverage_ratio"),
                "scan_duration_ms": row.get("scan_duration_ms"),
            },
        )
    return [result[key] for key in sorted(result)]


def _valid_frame(frame: Mapping[str, object]) -> bool:
    trade_date = _as_date(frame.get("trade_date"))
    source_date = _as_date(frame.get("source_trade_date"))
    coverage = _number(frame.get("quote_coverage_ratio"))
    if coverage is not None and coverage > 1:
        coverage /= 100
    return (
        trade_date is not None
        and source_date == trade_date
        and frame.get("is_stale") is False
        and str(frame.get("quality_status") or "") == "ready"
        and coverage is not None
        and coverage >= 0.90
    )


def _scan_gaps_seconds(frames: Sequence[Mapping[str, object]]) -> list[float]:
    grouped: dict[tuple[date, int], list[datetime]] = defaultdict(list)
    for frame in frames:
        captured_at = _as_datetime(frame.get("captured_at"))
        window = _entry_window_index(captured_at)
        if captured_at is not None and window is not None:
            grouped[(captured_at.date(), window)].append(captured_at)
    gaps: list[float] = []
    for (trade_date, window_index), times in grouped.items():
        ordered = sorted(set(times))
        start_text, end_text = scheduled_execution.ENTRY_WINDOWS[window_index]
        window_start = datetime.combine(
            trade_date,
            time.fromisoformat(start_text),
            tzinfo=SHANGHAI,
        )
        window_end = datetime.combine(
            trade_date,
            time.fromisoformat(end_text),
            tzinfo=SHANGHAI,
        )
        # Window edges expose a stopped or late-starting scanner even when the
        # few frames that were saved happen to be close together.
        gaps.append(max((ordered[0] - window_start).total_seconds(), 0.0))
        gaps.extend(
            (current - previous).total_seconds()
            for previous, current in zip(ordered, ordered[1:])
        )
        gaps.append(max((window_end - ordered[-1]).total_seconds(), 0.0))
    return gaps


def _entry_window_index(value: object) -> int | None:
    captured_at = _as_datetime(value)
    if captured_at is None:
        return None
    time_text = captured_at.strftime("%H:%M:%S")
    for index, (start, end) in enumerate(scheduled_execution.ENTRY_WINDOWS):
        if start <= time_text < end:
            return index
    return None


def _first_touch_index(
    bars: Sequence[Mapping[str, object]],
    threshold: float,
) -> int | None:
    for index, bar in enumerate(bars):
        values = [
            _number(bar.get(field))
            for field in ("open_price", "high_price", "close_price")
        ]
        if any(value is not None and value >= threshold - 1e-9 for value in values):
            return index
    return None


def _previous_range_pct(
    bars: Sequence[Mapping[str, object]],
    touch_index: int | None,
    previous_close: float,
) -> float | None:
    if touch_index is None or touch_index <= 0 or previous_close <= 0:
        return None
    window = bars[max(0, touch_index - 30) : touch_index]
    highs = [_number(row.get("high_price")) for row in window]
    lows = [_number(row.get("low_price")) for row in window]
    valid_highs = [value for value in highs if value is not None]
    valid_lows = [value for value in lows if value is not None]
    if not valid_highs or not valid_lows:
        return None
    return round((max(valid_highs) - min(valid_lows)) / previous_close * 100, 4)


def _bar_time_at(
    bars: Sequence[Mapping[str, object]],
    index: int | None,
) -> str | None:
    if index is None:
        return None
    value = _as_datetime(bars[index].get("bar_time"))
    return value.isoformat() if value else None


def _lead_minutes(start: int | None, end: int | None) -> int | None:
    if start is None or end is None or start > end:
        return None
    return end - start


def _trade_calendar(
    daily_bars: Sequence[Mapping[str, object]],
    supplied: Sequence[date | str] | None,
) -> list[date]:
    values = {_as_date(value) for value in supplied or []}
    values.update(_as_date(row.get("trade_date")) for row in daily_bars)
    return sorted(value for value in values if value is not None)


def _next_trade_date(calendar: Sequence[date], current: date) -> date | None:
    return next((value for value in calendar if value > current), None)


def _symbol_date_pair(row: Mapping[str, object]) -> tuple[str, date] | None:
    symbol = str(row.get("vt_symbol") or "").strip()
    trade_date = _as_date(row.get("trade_date"))
    if not symbol or trade_date is None:
        captured_at = _as_datetime(row.get("captured_at"))
        trade_date = captured_at.date() if captured_at is not None else None
    return (symbol, trade_date) if symbol and trade_date is not None else None


def _observation_sort_key(row: Mapping[str, object]) -> tuple[datetime, str]:
    captured_at = _as_datetime(row.get("captured_at")) or datetime.min.replace(
        tzinfo=SHANGHAI
    )
    return captured_at, str(row.get("vt_symbol") or "")


def _minute_sort_key(row: Mapping[str, object]) -> datetime:
    return _as_datetime(row.get("bar_time")) or datetime.min.replace(tzinfo=SHANGHAI)


def _signal_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("signal_date") or ""),
        str(row.get("captured_at") or row.get("entry_quote_at") or ""),
        str(row.get("vt_symbol") or ""),
    )


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _ratio_pct(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    return round(gains / losses, 4) if losses else None


def _difference(left: object, right: object) -> float | None:
    left_value = _number(left)
    right_value = _number(right)
    if left_value is None or right_value is None:
        return None
    return round(left_value - right_value, 4)


def _at_least(value: float | None, minimum: float) -> bool:
    return value is not None and value >= minimum


def _production_radar_contract() -> str:
    return PRODUCTION_RADAR_CONTRACT


def _at_most(value: float | None, maximum: float) -> bool:
    return value is not None and value <= maximum


def _profit_factor_passes(
    value: float | None,
    loss_count: float | None,
    minimum: float,
    closed_count: float | None,
) -> bool:
    if value is not None:
        return value >= minimum
    return (
        closed_count is not None
        and closed_count > 0
        and loss_count is not None
        and loss_count == 0
    )


def _block_profit_factor_passes(block: Mapping[str, object]) -> bool:
    value = _number(block.get("profit_factor"))
    if value is not None:
        return value >= 1.0
    return bool(block.get("positive"))


def _nearest_rank_percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, int(len(ordered) * percentile + 0.999999))
    return round(ordered[min(rank, len(ordered)) - 1], 4)


def _load_frames(start: date, end: date) -> list[dict[str, object]]:
    table = schema.limit_up_radar_frames
    with session_scope() as session:
        rows = session.execute(
            select(table)
            .where(table.c.trade_date.between(start, end))
            .order_by(table.c.captured_at)
        ).mappings().all()
    return [dict(row) for row in rows]


def _load_market_evidence(
    symbols: Sequence[str],
    observations: Sequence[Mapping[str, object]],
    start: date,
    end: date,
) -> tuple[list[dict[str, object]], list[date], list[dict[str, object]]]:
    daily = schema.stock_daily_bars
    minute = schema.stock_minute_bars
    pairs = sorted(
        {
            pair
            for row in observations
            if (pair := _symbol_date_pair(row)) is not None
        }
    )
    daily_end = end + timedelta(days=14)
    with session_scope() as session:
        daily_rows = session.execute(
            select(
                daily.c.vt_symbol,
                daily.c.trade_date,
                daily.c.open_price,
                daily.c.close_price,
                daily.c.high_price,
                daily.c.low_price,
            ).where(
                daily.c.vt_symbol.in_(symbols),
                daily.c.trade_date.between(start, daily_end),
            )
        ).mappings().all()
        calendar = list(
            session.execute(
                select(daily.c.trade_date)
                .where(daily.c.trade_date.between(start, daily_end))
                .distinct()
                .order_by(daily.c.trade_date)
            ).scalars().all()
        )
        minute_rows = (
            session.execute(
                select(
                    minute.c.vt_symbol,
                    minute.c.trade_date,
                    minute.c.bar_time,
                    minute.c.interval,
                    minute.c.open_price,
                    minute.c.close_price,
                    minute.c.high_price,
                    minute.c.low_price,
                ).where(
                    minute.c.interval == "1m",
                    tuple_(minute.c.vt_symbol, minute.c.trade_date).in_(pairs),
                )
            ).mappings().all()
            if pairs
            else []
        )
    return (
        [dict(row) for row in daily_rows],
        calendar,
        [dict(row) for row in minute_rows],
    )
