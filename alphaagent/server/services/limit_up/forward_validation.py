"""Forward ledger for formal recommendations saved during live trading."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.domain import main_board_limit_price
from alphaagent.server.services.limit_up.entry_backtest import (
    ENTRY_MODE_LABELS,
    ENTRY_MODES,
    EXIT_MODES,
    build_limit_up_entry_backtest,
)
from alphaagent.server.services.limit_up.live_policy import session_stage
from alphaagent.server.services.limit_up import regime_shadow
from alphaagent.server.services.limit_up.live_repository import (
    list_daily_trade_dates,
    load_daily_bars_for_symbols,
    load_snapshots_between,
)
from alphaagent.server.services.limit_up.versions import (
    LIVE_STRATEGY_VERSION as STRATEGY_VERSION,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
VALIDATION_VERSION = "limit-up-forward-validation-v2"
REPORT_MODE = "saved_actionable_recommendation_forward_validation"
FORMAL_ENTRY_MODE = "sweep"
FORMAL_EXIT_MODE = "next_close"
PROCESS_CHECK_DAYS = 20
STRATEGY_REVIEW_DAYS = 60
ACTIVE_SESSION_STAGES = {"auction", "morning", "afternoon", "tail", "close_auction"}
PENDING_ORDER_STATUSES = {"awaiting_entry_bar", "entry_bar_missing", "awaiting_exit_bar"}
EXCLUSION_LABELS = {
    "invalid_trade_date": "交易日期无效",
    "invalid_captured_at": "采集时间无效",
    "mode_not_live_snapshot": "不是实时保存快照",
    "stale_snapshot": "快照已过期",
    "non_trading_day": "不在已验证交易日",
    "captured_date_mismatch": "采集日与交易日不一致",
    "invalid_session_stage": "不在有效交易阶段",
    "session_stage_mismatch": "保存阶段与采集时间不一致",
}


def get_forward_validation(
    start: date | None,
    end: date | None,
    *,
    current_date: date | None = None,
) -> dict[str, object]:
    """Load saved snapshots and close them with subsequently available daily bars."""

    today = current_date or datetime.now(SHANGHAI).date()
    snapshots = load_snapshots_between(
        start,
        end,
        strategy_version=STRATEGY_VERSION,
    )
    trade_calendar = list_daily_trade_dates()
    eligible, _ = _audit_snapshots(snapshots, trade_calendar, today)
    symbols = _snapshot_symbols(eligible)
    observed_dates = [_date_value(row.get("trade_date")) for row in eligible]
    valid_dates = [item for item in observed_dates if item is not None]
    bars: list[dict[str, object]] = []
    if symbols and valid_dates:
        bars = load_daily_bars_for_symbols(
            symbols,
            min(valid_dates) - timedelta(days=14),
            max(valid_dates) + timedelta(days=21),
        )
    dataset = {
        "daily_bars": bars,
        "trade_calendar": sorted({*trade_calendar, *[item.isoformat() for item in valid_dates]}),
        "coverage": {},
    }
    return build_forward_validation_report(
        dataset,
        snapshots,
        trade_calendar=trade_calendar,
        entry_mode=FORMAL_ENTRY_MODE,
        exit_mode=FORMAL_EXIT_MODE,
        current_date=today,
    )


def build_forward_validation_report(
    dataset: Mapping[str, object],
    snapshots: Sequence[Mapping[str, object]],
    *,
    trade_calendar: Sequence[object],
    entry_mode: str,
    exit_mode: str,
    current_date: date | None = None,
) -> dict[str, object]:
    """Build an auditable report without historical signal backfilling."""

    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"unsupported entry mode: {entry_mode}")
    if exit_mode not in EXIT_MODES:
        raise ValueError(f"unsupported exit mode: {exit_mode}")

    today = current_date or datetime.now(SHANGHAI).date()
    eligible, exclusions = _audit_snapshots(snapshots, trade_calendar, today)
    observed_dates = sorted({str(row.get("trade_date") or "")[:10] for row in eligible})
    effective_calendar = sorted(
        {_date_text(item) for item in trade_calendar if _date_text(item)}
        | set(observed_dates)
    )
    backtest = build_limit_up_entry_backtest(
        {**dict(dataset), "trade_calendar": effective_calendar},
        eligible,
        entry_mode=entry_mode,
        exit_mode=exit_mode,
        historical_proxy_candidates=[],
        strict_signal_source="actionable_recommendations",
        strict_fill_evidence="saved_actionable_recommendation_proxy",
    )
    bars = _rows(dataset.get("daily_bars"))
    bar_index = {
        (str(row.get("vt_symbol") or ""), str(row.get("trade_date") or "")[:10]): row
        for row in bars
        if row.get("vt_symbol") and row.get("trade_date")
    }
    orders = [
        _with_entry_day_outcome(row, bar_index, effective_calendar)
        for row in _rows(backtest.get("orders"))
    ]
    trades = [
        _with_entry_day_outcome(row, bar_index, effective_calendar)
        for row in _rows(backtest.get("trades"))
    ]
    summary = _forward_summary(orders, trades, backtest.get("summary"))
    observed_day_count = len(observed_dates)
    status = (
        "collecting"
        if observed_day_count == 0
        else "observing"
        if observed_day_count < STRATEGY_REVIEW_DAYS
        else "ready_for_review"
    )
    result_status = _result_status(observed_day_count, summary)
    exclusion_counts = Counter(exclusions)
    regime_failure_shadow = _regime_failure_shadow_summary(orders, trades)

    return {
        "status": status,
        "result_status": result_status,
        "mode": REPORT_MODE,
        "validation_version": VALIDATION_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "entry_mode": entry_mode,
        "entry_mode_label": ENTRY_MODE_LABELS[entry_mode],
        "exit_mode": exit_mode,
        "simulation_eligible": False,
        "observation_scope": (
            "saved_actionable_recommendations_only_no_historical_backfill"
        ),
        "summary": summary,
        "regime_failure_shadow": regime_failure_shadow,
        "progress": {
            "process_check": _milestone(observed_day_count, PROCESS_CHECK_DAYS),
            "strategy_review": _milestone(observed_day_count, STRATEGY_REVIEW_DAYS),
        },
        "coverage": {
            "raw_snapshot_count": len(snapshots),
            "eligible_snapshot_count": len(eligible),
            "excluded_snapshot_count": len(snapshots) - len(eligible),
            "excluded_by_reason": [
                {
                    "code": code,
                    "label": EXCLUSION_LABELS[code],
                    "count": count,
                }
                for code, count in sorted(exclusion_counts.items())
            ],
            "observed_trade_days": observed_day_count,
            "observed_dates": observed_dates,
            "observed_start": observed_dates[0] if observed_dates else None,
            "observed_end": observed_dates[-1] if observed_dates else None,
            "historical_proxy_snapshot_count": 0,
            "signal_source": "recommendations.actionable_recommendations",
            "execution_confidence": "proxy_without_l2",
        },
        "observation_days": _observation_days(eligible, orders, trades),
        "daily_results": list(backtest.get("daily_results") or []),
        "orders": orders[-200:],
        "trades": trades[-200:],
        "limitations": [
            "只统计系统当时真实保存且非过期的正式可买列表，不把观察池或研究动作计为交易。",
            "当前没有Tick/L2队列证据，闭合交易仍是价格代理，simulation_eligible固定为false。",
            "20个交易日只做流程检查；满60个交易日后才重新评估收益稳定性和数据中断风险。",
            "风格失效影子只记录严格D-1输入，不改变正式推荐、仓位或退出。",
        ],
    }


def _regime_failure_shadow_summary(
    orders: Sequence[Mapping[str, object]],
    trades: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    order_shadows = _captured_regime_shadows(orders)
    trade_shadows = _captured_regime_shadows(trades)
    eligible = [row for row in order_shadows if row.get("status") == "ready"]
    risk_orders = [row for row in eligible if row.get("risk_flag") is True]
    closed_risk = [
        row
        for row in trade_shadows
        if row.get("status") == "ready" and row.get("risk_flag") is True
    ]
    status = (
        "no_captured_input"
        if not order_shadows
        else "collecting"
        if eligible
        else "blocked_by_input"
    )
    return {
        "policy_version": regime_shadow.POLICY_VERSION,
        "status": status,
        "execution_effect": "none_research_only",
        "plan_count": len(order_shadows),
        "eligible_plan_count": len(eligible),
        "risk_plan_count": len(risk_orders),
        "closed_risk_count": len(closed_risk),
        "minimum_closed_risk_count": 30,
    }


def _captured_regime_shadows(
    rows: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    result = []
    for row in rows:
        shadow = row.get("regime_failure_shadow")
        if (
            isinstance(shadow, Mapping)
            and shadow.get("policy_version") == regime_shadow.POLICY_VERSION
        ):
            result.append(shadow)
    return result


def _audit_snapshots(
    snapshots: Sequence[Mapping[str, object]],
    trade_calendar: Sequence[object],
    current_date: date,
) -> tuple[list[dict[str, object]], list[str]]:
    calendar = {_date_text(item) for item in trade_calendar if _date_text(item)}
    eligible: list[dict[str, object]] = []
    exclusions: list[str] = []
    for raw in sorted(snapshots, key=_snapshot_sort_key):
        snapshot = dict(raw)
        reason = _snapshot_exclusion(snapshot, calendar, current_date)
        if reason:
            exclusions.append(reason)
        else:
            eligible.append(snapshot)
    return eligible, exclusions


def _snapshot_exclusion(
    snapshot: Mapping[str, object],
    trade_calendar: set[str],
    current_date: date,
) -> str | None:
    trade_date = _date_value(snapshot.get("trade_date"))
    if trade_date is None:
        return "invalid_trade_date"
    if str(snapshot.get("mode") or "") != "live_snapshot":
        return "mode_not_live_snapshot"
    quality = snapshot.get("data_quality")
    if not isinstance(quality, Mapping) or quality.get("is_stale") is not False:
        return "stale_snapshot"
    if trade_date.weekday() >= 5:
        return "non_trading_day"
    captured_at = _datetime_value(snapshot.get("captured_at"))
    if captured_at is None:
        return "invalid_captured_at"
    if captured_at.date() != trade_date:
        return "captured_date_mismatch"
    actual_stage = session_stage(captured_at)
    if actual_stage not in ACTIVE_SESSION_STAGES:
        return "invalid_session_stage"
    declared_stage = str(snapshot.get("session_stage") or "")
    if declared_stage and declared_stage != actual_stage:
        return "session_stage_mismatch"
    if trade_date.isoformat() not in trade_calendar and trade_date != current_date:
        return "non_trading_day"
    return None


def _forward_summary(
    orders: list[dict[str, object]],
    trades: list[dict[str, object]],
    backtest_summary: object,
) -> dict[str, object]:
    source = dict(backtest_summary) if isinstance(backtest_summary, Mapping) else {}
    pending_count = sum(str(row.get("status") or "") in PENDING_ORDER_STATUSES for row in orders)
    closed_trade_count = len(trades)
    rejected_count = max(0, len(orders) - pending_count - closed_trade_count)
    seal_outcomes = [
        bool(row["entry_day_final_sealed"])
        for row in orders
        if row.get("entry_day_final_sealed") is not None
    ]
    has_closed_trades = closed_trade_count > 0
    nullable_metrics = {
        key: source.get(key) if has_closed_trades else None
        for key in (
            "win_rate",
            "average_return_pct",
            "median_return_pct",
            "total_return_pct",
            "max_drawdown_pct",
            "hard_loss_rate",
            "profit_factor",
        )
    }
    return {
        "plan_count": len(orders),
        "closed_plan_count": len(orders) - pending_count,
        "pending_plan_count": pending_count,
        "rejected_plan_count": rejected_count,
        "closed_trade_count": closed_trade_count,
        "win_count": int(source.get("win_count") or 0),
        "hard_loss_count": int(source.get("hard_loss_count") or 0),
        "entry_day_seal_rate": (
            round(sum(seal_outcomes) / len(seal_outcomes) * 100, 4)
            if seal_outcomes
            else None
        ),
        **nullable_metrics,
    }


def _with_entry_day_outcome(
    row: Mapping[str, object],
    bar_index: Mapping[tuple[str, str], Mapping[str, object]],
    calendar: list[str],
) -> dict[str, object]:
    result = dict(row)
    symbol = str(result.get("vt_symbol") or "")
    entry_date = str(result.get("entry_date") or "")[:10]
    entry_bar = bar_index.get((symbol, entry_date))
    previous_date = _calendar_offset(calendar, entry_date, -1)
    previous_bar = bar_index.get((symbol, previous_date or ""))
    result["entry_day_final_sealed"] = _closed_at_limit(entry_bar, previous_bar)
    return result


def _closed_at_limit(
    entry_bar: Mapping[str, object] | None,
    previous_bar: Mapping[str, object] | None,
) -> bool | None:
    if entry_bar is None or previous_bar is None:
        return None
    close_price = _number(entry_bar.get("close_price"))
    previous_close = _number(previous_bar.get("close_price"))
    if close_price is None or previous_close is None or previous_close <= 0:
        return None
    limit_price = main_board_limit_price(previous_close)
    return close_price >= limit_price - 0.011


def _observation_days(
    snapshots: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
    trades: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[str(snapshot.get("trade_date") or "")[:10]].append(snapshot)
    result = []
    for trade_date in sorted(grouped):
        day_snapshots = grouped[trade_date]
        day_orders = [row for row in orders if str(row.get("plan_date") or "")[:10] == trade_date]
        day_trades = [row for row in trades if str(row.get("signal_date") or "")[:10] == trade_date]
        returns = [_number(row.get("return_pct")) for row in day_trades]
        valid_returns = [value for value in returns if value is not None]
        captured_times = sorted(str(row.get("captured_at") or "") for row in day_snapshots)
        return_value = round(mean(valid_returns), 4) if valid_returns else None
        result.append(
            {
                "trade_date": trade_date,
                "snapshot_count": len(day_snapshots),
                "first_captured_at": captured_times[0] if captured_times else None,
                "last_captured_at": captured_times[-1] if captured_times else None,
                "plan_count": len(day_orders),
                "pending_plan_count": sum(
                    str(row.get("status") or "") in PENDING_ORDER_STATUSES
                    for row in day_orders
                ),
                "closed_trade_count": len(day_trades),
                "win_rate": (
                    round(sum(value > 0 for value in valid_returns) / len(valid_returns) * 100, 4)
                    if valid_returns
                    else None
                ),
                "average_return_pct": return_value,
            }
        )
    return result


def _result_status(observed_days: int, summary: Mapping[str, object]) -> str:
    if observed_days == 0:
        return "no_eligible_snapshots"
    if int(summary.get("plan_count") or 0) == 0:
        return "no_saved_plans"
    if int(summary.get("closed_trade_count") or 0) > 0:
        return "closed_results_available"
    if int(summary.get("pending_plan_count") or 0) > 0:
        return "awaiting_d1"
    return "no_executable_proxy"


def _milestone(observed_days: int, target_days: int) -> dict[str, object]:
    return {
        "target_days": target_days,
        "observed_days": observed_days,
        "remaining_days": max(0, target_days - observed_days),
        "progress_pct": round(min(observed_days / target_days, 1.0) * 100, 2),
        "status": "complete" if observed_days >= target_days else "collecting",
    }


def _snapshot_symbols(snapshots: Sequence[Mapping[str, object]]) -> list[str]:
    symbols: set[str] = set()
    for snapshot in snapshots:
        for row in snapshot.get("candidates") or []:
            if isinstance(row, Mapping) and row.get("vt_symbol"):
                symbols.add(str(row["vt_symbol"]))
        recommendations = snapshot.get("recommendations")
        recommendations = recommendations if isinstance(recommendations, Mapping) else {}
        lanes = recommendations.get("lanes")
        lanes = lanes if isinstance(lanes, Mapping) else {}
        for lane in lanes.values():
            if not isinstance(lane, Sequence) or isinstance(lane, (str, bytes)):
                continue
            for row in lane:
                if isinstance(row, Mapping) and row.get("vt_symbol"):
                    symbols.add(str(row["vt_symbol"]))
    return sorted(symbols)


def _snapshot_sort_key(snapshot: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(snapshot.get("trade_date") or "")[:10],
        str(snapshot.get("captured_at") or ""),
    )


def _calendar_offset(calendar: list[str], base: str, offset: int) -> str | None:
    if base not in calendar:
        return None
    index = calendar.index(base) + offset
    return calendar[index] if 0 <= index < len(calendar) else None


def _rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _date_text(value: object) -> str | None:
    parsed = _date_value(value)
    return parsed.isoformat() if parsed else None


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
