"""Read-only factor audit helpers for persisted quant candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any

from alphaagent.market.boards import stock_board_payload
from alphaagent.server.services.backtest import data_quality
from alphaagent.server.services.backtest.schemas import Position
from alphaagent.server.services.backtest.tail_entry_next_day_label import build_tail_entry_next_day_label
from alphaagent.server.services.quant.factors import Bar
from alphaagent.server.services.quant.screening_payloads import normalize_quant_evidence


@dataclass(frozen=True)
class CandidateCluster:
    """A merged run of consecutive executable BUY candidates for one symbol."""

    vt_symbol: str
    rows: tuple[dict[str, Any], ...]
    cluster_start_date: date
    cluster_end_date: date
    entry_row: dict[str, Any]


@dataclass(frozen=True)
class IndependentTradeResult:
    """Theoretical one-symbol trade result used only by candidate-quality reports."""

    status: str
    cluster: CandidateCluster
    entry_signal_date: date
    entry_execute_date: date | None
    entry_price: float | None
    exit_signal_date: date | None
    exit_execute_date: date | None
    exit_price: float | None
    return_pct: float | None
    max_drawdown_pct: float | None
    max_runup_pct: float | None
    holding_days: int | None
    exit_reason: str | None
    window: tuple[Bar, ...] = ()
    labels: dict[str, Any] = field(default_factory=dict)


def rank_bucket(rank: int | None) -> str:
    if rank is None or rank <= 0:
        return "outside_top_100"
    if rank <= 10:
        return "top_10"
    if rank <= 20:
        return "top_20"
    if rank <= 100:
        return "top_100"
    return "outside_top_100"


def ma_convergence_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < 3:
        return "<3"
    if numeric <= 6:
        return "3-6"
    if numeric <= 10:
        return "6-10"
    return ">10"


def low_suction_days_bucket(days: int | float | None) -> str:
    numeric = _float_or_none(days) or 0.0
    if numeric <= 0:
        return "0"
    if numeric <= 2:
        return "1-2"
    if numeric <= 5:
        return "3-5"
    if numeric <= 10:
        return "6-10"
    return "10+"


def volume_bucket(volume_ratio: float | None) -> str:
    numeric = _float_or_none(volume_ratio)
    if numeric is None:
        return "unknown"
    if numeric < 0.8:
        return "shrinking"
    if numeric < 1.6:
        return "normal"
    if numeric < 2.0:
        return "moderate_expansion"
    if numeric < 3.0:
        return "double_volume"
    return "explosive"


def close_location_bucket(value: float | None) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric < 0.4:
        return "low"
    if numeric <= 0.75:
        return "middle"
    return "high"


def market_regime_bucket(value: str | None) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def fund_flow_bucket(value: str | None) -> str:
    text = str(value or "").strip()
    return text or "insufficient_data"


def launch_quality_bucket(value: str | None) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def warning_level_bucket(value: str | None) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def support_stop_context_bucket(value: str | None) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def factor_audit_summary(rows: list[dict[str, Any]], *, exclude_strong_market: bool = False) -> dict[str, Any]:
    audited_rows = _exclude_strong_market_rows(rows) if exclude_strong_market else rows
    return {
        "status": "ready" if audited_rows else "empty",
        "summary": _bucket_metrics("all", audited_rows),
        "by_setup": _group_metrics(audited_rows, lambda row: str(row.get("setup_primary") or row.get("entry_family") or "unknown")),
        "by_entry_family_conflict": _group_metrics(audited_rows, lambda row: "conflict" if row.get("entry_family_conflict") else "clean"),
        "by_low_position_reclaim_type": _group_metrics(audited_rows, lambda row: str(row.get("low_position_reclaim_type") or "none")),
        "by_rank_bucket": _group_metrics(audited_rows, lambda row: str(row.get("rank_bucket") or "unknown")),
        "by_market_regime": _group_metrics(audited_rows, lambda row: market_regime_bucket(row.get("dynamic_market_regime"))),
        "by_market_warning_level": _group_metrics(audited_rows, lambda row: warning_level_bucket(row.get("market_warning_level"))),
        "by_fund_flow_state": _group_metrics(audited_rows, lambda row: fund_flow_bucket(row.get("fund_flow_state"))),
        "by_factor_bucket": {
            "ma_convergence": _group_metrics(audited_rows, lambda row: ma_convergence_bucket(row.get("ma_convergence_pct"))),
            "low_suction_days": _group_metrics(audited_rows, lambda row: low_suction_days_bucket(row.get("low_suction_days"))),
            "volume": _group_metrics(audited_rows, lambda row: volume_bucket(row.get("volume_ratio_5d_20d"))),
            "close_location": _group_metrics(audited_rows, lambda row: close_location_bucket(row.get("close_location_in_range"))),
            "fund_flow": _group_metrics(audited_rows, lambda row: fund_flow_bucket(row.get("fund_flow_state"))),
            "launch_quality": _group_metrics(audited_rows, lambda row: launch_quality_bucket(row.get("low_suction_launch_quality_bucket") or row.get("low_suction_launch_quality_label"))),
            "support_stop_context": _group_metrics(audited_rows, lambda row: support_stop_context_bucket(row.get("support_stop_context"))),
        },
        "factor_interaction_opportunity_cost": factor_interaction_opportunity_cost_summary(audited_rows),
        "success_paths": [],
        "failure_paths": [],
        "coverage": {
            "candidate_count": len(audited_rows),
            "original_candidate_count": len(rows),
            "excluded_strong_market_count": len(rows) - len(audited_rows),
            "outcome_count": sum(1 for row in audited_rows if isinstance(row.get("outcome"), dict)),
        },
    }


def factor_interaction_opportunity_cost_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return read-only factor interaction and opportunity-cost buckets."""

    return {
        "method": "只读审计：用候选信号日可见特征分组，并用固定持有后验衡量胜率/MFE/MAE；后验字段不参与评分或买卖。",
        "entry_family_rank": _interaction_bucket_rows(rows, ("entry_family", "rank_bucket")),
        "entry_family_market": _interaction_bucket_rows(rows, ("entry_family", "dynamic_market_regime")),
        "launch_quality_market": _interaction_bucket_rows(rows, ("low_suction_launch_quality_bucket", "dynamic_market_regime")),
        "low_suction_days_first_lift": _interaction_bucket_rows(rows, ("low_suction_days_bucket", "first_effective_lift_bucket")),
        "reclaim_support_ma": _interaction_bucket_rows(rows, ("low_position_reclaim_type", "support_ma_bucket")),
        "risk_market_warning": _interaction_bucket_rows(rows, ("risk_penalty_bucket", "market_warning_level")),
        "opportunity_cost": opportunity_cost_summary(rows),
        "not_used_for_signal_score": True,
    }


def opportunity_cost_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [_outcome_return(row) for row in rows]
    returns = [value for value in returns if value is not None]
    winners = [value for value in returns if value > 5.0]
    losers = [value for value in returns if value < -3.0]
    return {
        "removed_winner_count": len(winners),
        "removed_winner_return_sum": round(sum(winners), 4) if winners else 0.0,
        "avoided_loser_count": len(losers),
        "avoided_loser_return_sum": round(sum(losers), 4) if losers else 0.0,
        "added_loser_count": 0,
        "added_loser_return_sum": 0.0,
        "net_opportunity_delta": 0.0,
        "note": "这里是候选后验机会成本基线；后验统计只用于审计，不参与评分或买卖。",
    }


def _interaction_bucket_rows(rows: list[dict[str, Any]], keys: tuple[str, str]) -> list[dict[str, Any]]:
    prepared = [_with_interaction_derived_fields(row) for row in rows]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in prepared:
        left = str(row.get(keys[0]) or "unknown")
        right = str(row.get(keys[1]) or "unknown")
        groups.setdefault((left, right), []).append(row)

    result: list[dict[str, Any]] = []
    for (left, right), bucket_rows in groups.items():
        item = {
            keys[0]: None if left == "unknown" else left,
            keys[1]: None if right == "unknown" else right,
            "factor_group": f"{keys[0]}+{keys[1]}",
            "factor_value": f"{left}|{right}",
            **_bucket_metrics(f"{left}|{right}", bucket_rows),
        }
        result.append(item)
    result.sort(
        key=lambda item: (
            -int(item.get("sample_count") or 0),
            -_sort_float(item.get("average_return")),
            str(item.get("factor_value") or ""),
        )
    )
    return result


def _with_interaction_derived_fields(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["entry_family"] = item.get("entry_family") or item.get("setup_primary") or "unknown"
    item["rank_bucket"] = item.get("rank_bucket") or rank_bucket(_int_or_none(item.get("rank")))
    item["dynamic_market_regime"] = market_regime_bucket(item.get("dynamic_market_regime"))
    item["low_suction_launch_quality_bucket"] = launch_quality_bucket(
        item.get("low_suction_launch_quality_bucket") or item.get("low_suction_launch_quality_label")
    )
    item["low_suction_days_bucket"] = low_suction_days_bucket(item.get("low_suction_days"))
    item["first_effective_lift_bucket"] = "first_effective_lift" if item.get("first_effective_lift") or item.get("launch_confirmed") else "no_first_lift"
    item["support_ma_bucket"] = _support_ma_bucket(item)
    item["risk_penalty_bucket"] = _risk_penalty_bucket(item.get("risk_penalty"))
    item["market_warning_level"] = warning_level_bucket(item.get("market_warning_level"))
    return item


def _support_ma_bucket(row: dict[str, Any]) -> str:
    for key, label in (
        ("support_ma", "ma_support"),
        ("reclaim_source", "reclaim_source"),
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    distances = {
        "ma5": abs(_float_or_none(row.get("ma5_distance_pct")) or 999.0),
        "ma10": abs(_float_or_none(row.get("ma10_distance_pct")) or 999.0),
        "ma20": abs(_float_or_none(row.get("ma20_distance_pct")) or 999.0),
        "ma30": abs(_float_or_none(row.get("ma30_distance_pct")) or 999.0),
    }
    support, distance = min(distances.items(), key=lambda item: item[1])
    return support if distance < 999.0 else "unknown"


def _risk_penalty_bucket(value: Any) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric <= 0:
        return "none"
    if numeric < 5:
        return "low"
    if numeric < 12:
        return "medium"
    return "high"


def candidate_execution_attribution_summary(
    candidates: list[dict[str, Any]],
    *,
    signal_events: list[dict[str, Any]] | None = None,
    orders: list[dict[str, Any]] | None = None,
    trades: list[dict[str, Any]] | None = None,
    cache_coverage: dict[str, Any] | None = None,
    max_execution_rank: int = 20,
) -> dict[str, Any]:
    """Summarize how top candidates flowed into real portfolio execution.

    This is read-only attribution. Fixed-horizon outcomes and missed-candidate
    returns stay in the audit payload and must not feed signal scoring.
    """

    top_limit = max(int(max_execution_rank or 20), 1)
    signal_keys = _candidate_signal_keys(signal_events or [])
    order_keys = _candidate_order_keys(orders or [])
    trade_keys = _candidate_trade_keys(trades or [])
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        rank = _int_or_none(candidate.get("rank"))
        if rank is None or rank <= 0 or rank > top_limit:
            continue
        action = str(candidate.get("entry_action") or candidate.get("action") or "").upper()
        if action and action != "BUY":
            continue
        key = _candidate_key(candidate)
        item = _candidate_execution_attribution_row(
            candidate,
            key=key,
            planned=key in signal_keys,
            order=order_keys.get(key),
            trade=trade_keys.get(key),
            signal_events=signal_events or [],
            orders=orders or [],
            cache_coverage=cache_coverage,
            max_execution_rank=top_limit,
        )
        rows.append(item)
    return {
        "method": "只读归因：按候选信号日、同回测计划、订单和成交映射 top20 候选；后验收益只用于审计，不参与买卖。",
        "max_execution_rank": top_limit,
        "candidate_count": len(rows),
        "filled_count": sum(1 for row in rows if row.get("filled")),
        "missed_count": sum(1 for row in rows if not row.get("filled")),
        "top20_missed_quality": _top_missed_quality(rows),
        "by_status": _candidate_execution_status_buckets(rows),
        "by_not_filled_reason": _candidate_not_filled_reason_buckets(rows),
        "by_not_filled_subreason": _candidate_not_filled_subreason_buckets(rows),
        "items": rows[:100],
    }


def _candidate_audit_return(row: dict[str, Any]) -> float | None:
    return _float_or_none(row.get("fixed_return_20d") if row.get("filled") else row.get("missed_return_20d"))


def _same_symbol(left: Any, right: Any) -> bool:
    return bool(str(left or "").strip().upper()) and str(left or "").strip().upper() == str(right or "").strip().upper()


def classify_candidate_plan_gap(
    candidate: dict[str, object],
    *,
    signal_events: list[dict[str, object]],
    orders: list[dict[str, object]],
    cache_coverage: dict[str, object] | None = None,
) -> dict[str, object]:
    """Classify why a visible candidate did not become a plan/order.

    This is audit-only explanation. It deliberately uses candidate, signal and
    order metadata already produced by the replay; it must not feed scoring.
    """

    coverage = cache_coverage if isinstance(cache_coverage, dict) else {}
    theoretical = candidate.get("theoretical_position") if isinstance(candidate.get("theoretical_position"), dict) else {}
    if theoretical.get("is_holding") or theoretical.get("held") or candidate.get("target_theoretical_held_on_signal_date"):
        return _candidate_plan_gap_payload(
            "already_theoretical_holding",
            "候选存在，但理论计划层已持有同股或没有重复写 BUY",
        )
    symbol = str(candidate.get("vt_symbol") or "").upper()
    signal_date = _date_or_none(candidate.get("candidate_trade_date") or candidate.get("trade_date") or candidate.get("signal_date"))
    inferred_theoretical = _candidate_theoretical_position(symbol, signal_date, signal_events)
    if inferred_theoretical.get("held"):
        entry_date = inferred_theoretical.get("entry_date")
        entry_text = f"自 {entry_date} 起" if entry_date else "此前"
        return _candidate_plan_gap_payload(
            "already_theoretical_holding",
            f"候选存在，但理论计划层{entry_text}已持有同股或没有重复写 BUY",
        )

    action = str(candidate.get("entry_action") or candidate.get("action") or "").upper()
    if bool(candidate.get("action_mismatch_resolved")) and action != "BUY":
        return _candidate_plan_gap_payload(
            "action_mismatch_resolved_to_watch",
            "候选旧缓存曾是 BUY，但当前证据已修正为 WATCH",
        )

    candidate_date = signal_date
    signal_dates = [_date_or_none(row.get("signal_date") or row.get("trade_date")) for row in signal_events]
    signal_dates = [item for item in signal_dates if item is not None]
    if candidate_date and signal_dates and (candidate_date < min(signal_dates) or candidate_date > max(signal_dates)):
        return _candidate_plan_gap_payload(
            "date_outside_replay_window",
            "候选日期不在该回测已记录的理论信号范围内",
        )

    candidate_count = _int_or_none(coverage.get("candidate_count"))
    signal_count = _int_or_none(coverage.get("signal_count") or coverage.get("signal_event_count"))
    if (candidate_count is not None and candidate_count < 20) or (candidate_count and signal_count == 0):
        return _candidate_plan_gap_payload(
            "candidate_cache_sparse_or_missing",
            "候选缓存或理论信号缓存不足，不能把缺失计划解释为策略明确拒绝",
        )

    if symbol and signal_date:
        ordered = any(
            str(row.get("vt_symbol") or "").upper() == symbol
            and _order_signal_date(dict(row)) == signal_date
            for row in orders
        )
        if ordered:
            return _candidate_plan_gap_payload(
                "planned_but_order_missing",
                "候选有相关订单记录但没有成交，需要核查订单状态和执行约束",
            )

    rank = _int_or_none(candidate.get("execution_pool_rank") or candidate.get("rank"))
    if rank is not None and rank > 20:
        return _candidate_plan_gap_payload(
            "execution_pool_filtered",
            "候选排名低于组合执行池范围，因此没有进入真实买入计划",
        )

    if not signal_events:
        return _candidate_plan_gap_payload(
            "signal_event_missing",
            "该回测没有找到对应理论信号事件，需要核查信号计划生成链路",
        )

    return _candidate_plan_gap_payload(
        "unknown_plan_gap",
        "候选存在但没有进入理论计划，原因需要结合 candidate-trace 继续核查",
    )


def _candidate_theoretical_position(
    symbol: str,
    signal_date: date | None,
    signal_events: list[dict[str, object]],
) -> dict[str, object]:
    if not symbol or signal_date is None:
        return {"held": False, "entry_date": None}
    events = [
        row
        for row in signal_events
        if str(row.get("vt_symbol") or "").upper() == symbol
        and (_date_or_none(row.get("signal_date") or row.get("trade_date") or row.get("execute_date")) or date.max) <= signal_date
    ]
    events.sort(
        key=lambda row: (
            _date_or_none(row.get("signal_date")) or date.min,
            _date_or_none(row.get("trade_date") or row.get("execute_date")) or date.min,
            _int_or_none(row.get("id")) or 0,
        )
    )
    held = False
    entry_date = None
    for row in events:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        status = str(raw.get("status") or row.get("plan_status") or "filled")
        if status not in {"", "filled", "planned"}:
            continue
        side = str(row.get("side") or "").upper()
        event_date = _date_or_none(row.get("trade_date") or row.get("execute_date") or row.get("signal_date"))
        if side == "BUY":
            held = True
            entry_date = _date_to_iso(event_date)
        elif side == "SELL":
            held = False
            entry_date = None
    return {"held": held, "entry_date": entry_date}


def strategy_timeline_rows(
    *,
    recommendations: list[dict[str, Any]],
    signal_events: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    vt_symbol: str,
) -> list[dict[str, Any]]:
    symbol = str(vt_symbol or "").upper()
    rows: dict[str, dict[str, Any]] = {}
    for recommendation in recommendations:
        if str(recommendation.get("vt_symbol") or "").upper() != symbol:
            continue
        item = _timeline_row(rows, recommendation.get("trade_date"), symbol)
        item["candidate"] = _candidate_timeline_payload(recommendation)
        item["markers"].append("candidate")

    for signal in signal_events:
        if str(signal.get("vt_symbol") or "").upper() != symbol:
            continue
        item = _timeline_row(rows, signal.get("execute_date") or signal.get("trade_date"), symbol)
        item["plan"] = _plan_timeline_payload(signal)
        item["markers"].append("planned")

    for order in orders:
        if str(order.get("vt_symbol") or "").upper() != symbol:
            continue
        item = _timeline_row(rows, order.get("trade_date"), symbol)
        item["execution"] = _execution_timeline_payload(order)
        item["markers"].append("buy" if str(order.get("side") or "").upper() == "BUY" else "sell")

    for trade in trades:
        if str(trade.get("vt_symbol") or "").upper() != symbol:
            continue
        item = _timeline_row(rows, trade.get("trade_date"), symbol)
        if str(trade.get("side") or "").upper() == "SELL":
            item["sell"] = _sell_timeline_payload(trade)
            item["markers"].append("sell")
        else:
            item["execution"] = _trade_execution_payload(trade)
            item["markers"].append("buy")

    return _timeline_display_rows([_dedupe_timeline_markers(row) for _, row in sorted(rows.items())])


def strategy_lifecycle_segments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build compact lifecycle segments from merged strategy timeline rows."""

    segments: list[dict[str, Any]] = []
    pending_buildup: dict[str, Any] | None = None
    for row in rows:
        cluster = row.get("cluster") if isinstance(row.get("cluster"), dict) else None
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        if cluster and cluster.get("type") == "buildup_cluster":
            pending_buildup = {
                "vt_symbol": row.get("vt_symbol"),
                "cluster_start_date": cluster.get("cluster_start_date"),
                "cluster_end_date": cluster.get("cluster_end_date"),
                "key_signal_date": None,
                "cluster_type": "low_suction_buildup",
                "buildup_days": cluster.get("cluster_size"),
                "support_hold_days": None,
                "first_effective_lift": False,
                "launch_confirmed": False,
                "launch_quality_bucket": None,
                "key_signal_rank": None,
                "key_signal_score": None,
                "key_signal_action": "WATCH",
            }
            continue

        display_markers = set(row.get("display_markers") or [])
        is_buy_signal = "BUY_SIGNAL" in display_markers or "BUY_FILLED" in display_markers
        if is_buy_signal and pending_buildup is not None:
            segment = dict(pending_buildup)
            segment.update(
                {
                    "key_signal_date": row.get("date"),
                    "first_effective_lift": bool(candidate.get("first_effective_lift") or candidate.get("low_suction_launch_confirmed")),
                    "launch_confirmed": bool(candidate.get("low_suction_launch_confirmed") or candidate.get("first_effective_lift")),
                    "launch_quality_bucket": candidate.get("low_suction_launch_quality_bucket"),
                    "key_signal_rank": candidate.get("rank"),
                    "key_signal_score": candidate.get("score"),
                    "key_signal_action": candidate.get("action"),
                }
            )
            segments.append(segment)
            pending_buildup = None
            continue

        if pending_buildup is not None:
            segments.append(pending_buildup)
            pending_buildup = None

        if is_buy_signal:
            reason = candidate.get("reason") if isinstance(candidate.get("reason"), dict) else {}
            setup = str(reason.get("entry_setup") or reason.get("setup_type") or candidate.get("entry_family_label") or "")
            low_days = _float_or_none(candidate.get("low_suction_days")) or _float_or_none(reason.get("low_suction_days")) or 0.0
            cluster_type = "dragon_low_suction_overlap" if low_days >= 3 and "dragon" in setup else "dragon_pullback" if "dragon" in setup else "first_effective_lift"
            segments.append(
                {
                    "vt_symbol": row.get("vt_symbol"),
                    "cluster_start_date": row.get("date"),
                    "cluster_end_date": row.get("date"),
                    "key_signal_date": row.get("date"),
                    "cluster_type": cluster_type,
                    "buildup_days": low_days,
                    "support_hold_days": None,
                    "first_effective_lift": bool(candidate.get("first_effective_lift") or candidate.get("low_suction_launch_confirmed")),
                    "launch_confirmed": bool(candidate.get("low_suction_launch_confirmed") or candidate.get("first_effective_lift")),
                    "launch_quality_bucket": candidate.get("low_suction_launch_quality_bucket"),
                    "key_signal_rank": candidate.get("rank"),
                    "key_signal_score": candidate.get("score"),
                    "key_signal_action": candidate.get("action"),
                }
            )
    if pending_buildup is not None:
        segments.append(pending_buildup)
    return segments


def candidate_feature_rows(
    rows: list[dict[str, Any]],
    stocks: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    stock_map = stocks or {}
    return [
        candidate_feature_row(row, stock=stock_map.get(str(row.get("vt_symbol") or "")))
        for row in rows
    ]


def candidate_feature_row(row: dict[str, Any], *, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    vt_symbol = str(row.get("vt_symbol") or "")
    trade_date = row.get("trade_date")
    evidence = _candidate_evidence(row)
    rank = _int_or_none(row.get("rank"))
    persisted_action = str(row.get("action") or "").upper() or None
    action = str(evidence.get("action") or persisted_action or "").upper() or None
    payload = {
        "trade_date": _date_to_iso(trade_date),
        "vt_symbol": vt_symbol,
        "name": (stock or {}).get("name") or row.get("name") or row.get("stock_name"),
        "industry": (stock or {}).get("industry") or row.get("industry"),
        "concepts": (stock or {}).get("concepts") or row.get("concepts"),
        "setup_primary": evidence.get("entry_family") or "unknown",
        "entry_family": evidence.get("entry_family") or "unknown",
        "entry_family_label": evidence.get("entry_family_label") or "未归类",
        "entry_family_conflict": bool(evidence.get("entry_family_conflict")),
        "entry_family_notes": list(evidence.get("entry_family_notes") or []),
        "low_position_reclaim_type": evidence.get("low_position_reclaim_type") or "none",
        "low_position_reclaim_label": evidence.get("low_position_reclaim_label") or "非低位承接",
        "entry_action": action,
        "raw_entry_signal": bool(evidence.get("raw_entry_signal", row.get("entry_signal", False))),
        "executable_entry_signal": bool(evidence.get("executable_entry_signal", action == "BUY")),
        "total_score": _float_or_none(row.get("total_score", evidence.get("total_score"))),
        "rank": rank,
        "rank_bucket": rank_bucket(rank),
        "dragon_entry_score": _setup_score(evidence, "dragon_pullback"),
        "low_reclaim_entry_score": _setup_score(evidence, "low_position_reclaim", "stealth_low_suction"),
        "shared_quality_score": _float_or_none(evidence.get("shared_quality_score")),
        "risk_penalty": _float_or_none(evidence.get("risk_penalty")),
        "low_suction_days": _float_or_none(evidence.get("low_suction_days")),
        "support_hold_days": _float_or_none(evidence.get("support_hold_days")),
        "low_suction_stage_label": evidence.get("low_suction_stage_label"),
        "low_suction_launch_quality_bucket": evidence.get("low_suction_launch_quality_bucket"),
        "low_suction_launch_quality_label": evidence.get("low_suction_launch_quality_label"),
        "first_effective_lift": bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed")),
        "launch_confirmed": bool(evidence.get("low_suction_launch_confirmed")),
        "ma_convergence_pct": _float_or_none(evidence.get("ma_convergence_pct")),
        "ma5_distance_pct": _float_or_none(evidence.get("ma5_distance_pct")),
        "ma10_distance_pct": _float_or_none(evidence.get("ma10_distance_pct")),
        "ma20_distance_pct": _float_or_none(evidence.get("ma20_distance_pct")),
        "ma30_distance_pct": _float_or_none(evidence.get("ma30_distance_pct")),
        "ma5_slope_pct": _float_or_none(evidence.get("ma5_slope_pct")),
        "ma10_slope_pct": _float_or_none(evidence.get("ma10_slope_pct")),
        "ma20_slope_pct": _float_or_none(evidence.get("ma20_slope_pct")),
        "ma30_slope_pct": _float_or_none(evidence.get("ma30_slope_pct")),
        "volume_ratio_5d_20d": _float_or_none(evidence.get("volume_ratio_5d_20d")),
        "turnover_percentile_60d": _float_or_none(evidence.get("turnover_percentile_60d")),
        "turnover": _float_or_none(evidence.get("turnover")),
        "amount": _float_or_none(evidence.get("amount") or evidence.get("turnover20")),
        "liquidity_score": _float_or_none(row.get("liquidity_score", evidence.get("liquidity_score"))),
        "close_location_in_range": _float_or_none(evidence.get("close_location_in_range")),
        "body_pct": _float_or_none(evidence.get("body_pct")),
        "upper_shadow_pct": _float_or_none(evidence.get("upper_shadow_pct")),
        "lower_shadow_pct": _float_or_none(evidence.get("lower_shadow_pct")),
        "gap_up_pct": _float_or_none(evidence.get("gap_up_pct")),
        "recent_limit_up_20d": bool(evidence.get("recent_limit_up_20d")),
        "near_limit_up_count_20d": _float_or_none(evidence.get("near_limit_up_count_20d")),
        "large_bull_count_20d": _float_or_none(evidence.get("large_bull_count_20d")),
        "consecutive_bull_closes": _float_or_none(evidence.get("consecutive_bull_closes")),
        "persistent_volume_expansion": bool(evidence.get("persistent_volume_expansion")),
        "drawdown_from_pivot_pct": _float_or_none(evidence.get("drawdown_from_pivot_pct")),
        "max_drawdown_60d": _float_or_none(evidence.get("max_drawdown_60d")),
        "overhead_pressure_pct": _float_or_none(evidence.get("overhead_pressure_pct")),
        "high_level_sideways_distribution_risk": bool(evidence.get("high_level_sideways_distribution_risk")),
        "volume_stall_risk": bool(evidence.get("volume_stall_risk")),
        "key_support_break_risk": bool(evidence.get("key_support_break_risk")),
        "spiky_churn_risk": bool(evidence.get("spiky_churn_risk")),
        "illiquid_forgotten_risk": bool(evidence.get("illiquid_forgotten_risk")),
        "weekly_top_fractal_risk": bool(evidence.get("weekly_top_fractal_risk")),
        "dynamic_market_regime": evidence.get("dynamic_market_regime"),
        "market_warning_level": evidence.get("market_warning_level"),
        "fund_flow_state": evidence.get("fund_flow_state"),
        "fund_flow_streak_days": _float_or_none(evidence.get("fund_flow_streak_days")),
        "recovery_state": evidence.get("recovery_state"),
        "dominant_theme": evidence.get("dominant_theme"),
        "theme_strength": _float_or_none(evidence.get("theme_strength")),
        "fund_flow_source": evidence.get("fund_flow_source"),
        "as_of_date": _date_to_iso(trade_date),
        "feature_window_end": _date_to_iso(trade_date),
        "reason": evidence,
        "uses_future_for_label_only": False,
        "not_used_for_signal_score": True,
    }
    if persisted_action:
        payload["persisted_action"] = persisted_action
        payload["action_mismatch_resolved"] = persisted_action != action
    payload.update(stock_board_payload(vt_symbol, (stock or {}).get("exchange") or row.get("exchange")))
    return payload


def build_candidate_clusters(
    rows: list[dict[str, Any]],
    *,
    max_gap_trading_days: int = 2,
) -> list[CandidateCluster]:
    """Merge consecutive executable BUY candidates by symbol.

    ``max_gap_trading_days`` is measured in the candidate stream's own trading
    dates. This avoids calendar-weekend surprises while still splitting stale
    repeated signals when a symbol disappears from the BUY list for multiple
    sessions.
    """

    buy_rows = [dict(row) for row in rows if _is_executable_buy_candidate(row)]
    if not buy_rows:
        return []

    trade_dates = sorted({day for row in buy_rows if (day := _date_or_none(row.get("trade_date") or row.get("signal_date")))})
    date_index = {day: index for index, day in enumerate(trade_dates)}
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in buy_rows:
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        trade_date = _date_or_none(row.get("trade_date") or row.get("signal_date"))
        if not symbol or trade_date is None:
            continue
        item = dict(row)
        item["_cluster_trade_date"] = trade_date
        by_symbol.setdefault(symbol, []).append(item)

    clusters: list[CandidateCluster] = []
    for symbol, symbol_rows in sorted(by_symbol.items()):
        symbol_rows.sort(key=lambda row: (_date_or_none(row.get("_cluster_trade_date")) or date.min, _int_or_none(row.get("rank")) or 10**9))
        current: list[dict[str, Any]] = []
        last_date: date | None = None
        for row in symbol_rows:
            trade_date = _date_or_none(row.get("_cluster_trade_date"))
            if trade_date is None:
                continue
            if current and last_date is not None and _candidate_trading_day_gap(last_date, trade_date, date_index) > max_gap_trading_days:
                clusters.append(_candidate_cluster(symbol, current))
                current = []
            current.append(row)
            last_date = trade_date
        if current:
            clusters.append(_candidate_cluster(symbol, current))

    clusters.sort(
        key=lambda cluster: (
            _date_or_none(cluster.entry_row.get("trade_date") or cluster.entry_row.get("signal_date")) or date.min,
            cluster.vt_symbol,
        )
    )
    return clusters


def build_daily_candidate_clusters(rows: list[dict[str, Any]]) -> list[CandidateCluster]:
    """Build one independent trade unit for each visible daily BUY candidate."""

    clusters: list[CandidateCluster] = []
    for row in rows:
        if not _is_executable_buy_candidate(row):
            continue
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        trade_date = _date_or_none(row.get("trade_date") or row.get("signal_date"))
        if not symbol or trade_date is None:
            continue
        item = dict(row)
        item["trade_date"] = trade_date
        item["vt_symbol"] = symbol
        clusters.append(
            CandidateCluster(
                vt_symbol=symbol,
                rows=(item,),
                cluster_start_date=trade_date,
                cluster_end_date=trade_date,
                entry_row=item,
            )
        )
    clusters.sort(
        key=lambda cluster: (
            cluster.cluster_start_date,
            _int_or_none(cluster.entry_row.get("rank")) or 10**9,
            cluster.vt_symbol,
        )
    )
    return clusters


def simulate_independent_candidate_trade(
    cluster: CandidateCluster,
    bars: list[Bar],
    *,
    params: Any,
    sell_reason_fn,
    limit_up_open_fn=None,
    limit_down_open_fn=None,
    buy_signal_dates: set[date] | None = None,
) -> IndependentTradeResult:
    """Simulate one theoretical trade for a candidate cluster.

    The entry is D+1 open. Exit signals are evaluated at daily close using the
    same sell reason function as the portfolio backtest, then executed at the
    next trading day's open. It does not read portfolio execution constraints.
    """

    sorted_bars = sorted(bars, key=lambda bar: bar.trade_date)
    current_buy_signal_dates = buy_signal_dates or set()
    signal_date = _date_or_none(cluster.entry_row.get("trade_date") or cluster.entry_row.get("signal_date")) or cluster.cluster_start_date
    entry_index = next((index for index, bar in enumerate(sorted_bars) if bar.trade_date > signal_date), None)
    if entry_index is None:
        return _independent_trade_missing(cluster, signal_date, "no_execute_bar")

    entry_bar = sorted_bars[entry_index]
    if limit_up_open_fn is not None and limit_up_open_fn(entry_bar):
        return _independent_trade_missing(cluster, signal_date, "limit_up_open_blocked", execute_date=entry_bar.trade_date)

    entry_price = float(entry_bar.open_price)
    position = _candidate_independent_position(cluster, entry_bar, entry_price)

    for index in range(entry_index, len(sorted_bars)):
        bar = sorted_bars[index]
        position.visible_holding_bars += 1
        position.last_price = bar.close_price
        position.highest_price = max(position.highest_price, bar.high_price)
        position.lowest_price = min(position.lowest_price if position.lowest_price is not None else bar.low_price, bar.low_price)
        sell_reason = sell_reason_fn(
            position,
            bar,
            bar.trade_date,
            params,
            current_buy_signal=bar.trade_date in current_buy_signal_dates,
        )
        if not sell_reason or bar.trade_date <= position.entry_date:
            continue
        if index >= len(sorted_bars) - 1:
            return _independent_trade_open_result(cluster, signal_date, entry_bar.trade_date, entry_price, sorted_bars[entry_index:])
        exit_bar = sorted_bars[index + 1]
        if limit_down_open_fn is not None and limit_down_open_fn(exit_bar):
            continue
        return _independent_trade_closed_result(
            cluster,
            signal_date=signal_date,
            entry_execute_date=entry_bar.trade_date,
            entry_price=entry_price,
            exit_signal_date=bar.trade_date,
            exit_execute_date=exit_bar.trade_date,
            exit_price=float(exit_bar.open_price),
            exit_reason=str(sell_reason),
            window=sorted_bars[entry_index:index + 2],
        )

    return _independent_trade_open_result(cluster, signal_date, entry_bar.trade_date, entry_price, sorted_bars[entry_index:])


def simulate_tail_entry_next_day_candidate_trade(
    cluster: CandidateCluster,
    bars: list[Bar],
) -> IndependentTradeResult:
    """Label one daily candidate as D-close entry and D+1-close outcome."""

    sorted_bars = sorted(bars, key=lambda bar: bar.trade_date)
    signal_date = _date_or_none(cluster.entry_row.get("trade_date") or cluster.entry_row.get("signal_date")) or cluster.cluster_start_date
    evidence = _candidate_evidence(cluster.entry_row)
    labels = build_tail_entry_next_day_label(
        signal_date=signal_date,
        bars=sorted_bars,
        vt_symbol=cluster.vt_symbol,
        name=cluster.entry_row.get("name"),
        evidence=evidence,
    )
    entry_date = _date_or_none(labels.get("tail_entry_date"))
    entry_price = _float_or_none(labels.get("tail_entry_price"))
    d1_date = _date_or_none(labels.get("d1_trade_date"))
    d1_close_price = _float_or_none(labels.get("d1_close_price"))
    status = str(labels.get("status") or "no_execute_bar")
    label_window = _tail_entry_label_window(sorted_bars, signal_date, d1_date)

    if status != "ready":
        return IndependentTradeResult(
            status=status,
            cluster=cluster,
            entry_signal_date=signal_date,
            entry_execute_date=entry_date,
            entry_price=entry_price,
            exit_signal_date=None,
            exit_execute_date=None,
            exit_price=None,
            return_pct=None,
            max_drawdown_pct=None,
            max_runup_pct=None,
            holding_days=None,
            exit_reason=status,
            window=tuple(label_window),
            labels=labels,
        )

    return IndependentTradeResult(
        status="closed",
        cluster=cluster,
        entry_signal_date=signal_date,
        entry_execute_date=entry_date or signal_date,
        entry_price=entry_price,
        exit_signal_date=d1_date,
        exit_execute_date=d1_date,
        exit_price=d1_close_price,
        return_pct=_float_or_none(labels.get("d1_close_return_pct")),
        max_drawdown_pct=_float_or_none(labels.get("d1_low_drawdown_pct")),
        max_runup_pct=_float_or_none(labels.get("d1_high_runup_pct")),
        holding_days=1,
        exit_reason="d1_close_label",
        window=tuple(label_window),
        labels=labels,
    )


def candidate_trade_quality_report_from_results(
    results: list[IndependentTradeResult],
    *,
    rank_limit: int = 20,
    sample_limit: int = 500,
) -> dict[str, Any]:
    """Aggregate independent candidate labels into Top5/Top10/Top20 buckets."""

    rank_cutoff = min(max(int(rank_limit or 20), 1), 20)
    samples = [_candidate_trade_sample(result) for result in results]
    ranked_samples = [item for item in samples if _candidate_effective_rank(item) <= rank_cutoff]
    evaluated = [item for item in ranked_samples if item.get("status") in {"closed", "open"} and _float_or_none(item.get("return_pct")) is not None]
    clean_evaluated = [item for item in evaluated if not item.get("has_price_discontinuity")]
    missing = [item for item in ranked_samples if item.get("status") not in {"closed", "open"}]
    is_tail_entry_report = bool(not evaluated or any(str(item.get("entry_model") or "") == "signal_day_close" for item in evaluated))
    by_rank_bucket = _candidate_trade_group_metrics(evaluated, "rank_bucket", _candidate_trade_rank_bucket_order)
    by_rank_limit = _candidate_trade_rank_limit_metrics(evaluated, rank_cutoff=rank_cutoff)
    by_daily_rank_window = _candidate_trade_group_metrics(evaluated, "daily_rank_window", _candidate_trade_rank_window_order)
    by_score_bucket = _candidate_trade_group_metrics(evaluated, "score_bucket", _candidate_trade_score_bucket_order)
    by_setup_family = _candidate_trade_group_metrics(evaluated, "setup_family")
    by_market_phase = _candidate_trade_group_metrics(evaluated, "market_phase")
    by_timing_window = _candidate_trade_group_metrics(evaluated, "timing_window")
    by_timing_phase = _candidate_trade_group_metrics(evaluated, "timing_phase")
    by_setup_x_timing = _candidate_trade_group_metrics(evaluated, "setup_timing_bucket")
    by_month = _candidate_trade_group_metrics(evaluated, "month")
    by_evaluation_window = _candidate_trade_evaluation_window_metrics(evaluated)
    by_setup_family_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "setup_family", rank_cutoff=rank_cutoff)
    by_market_phase_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "market_phase", rank_cutoff=rank_cutoff)
    by_timing_window_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "timing_window", rank_cutoff=rank_cutoff)
    by_timing_phase_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "timing_phase", rank_cutoff=rank_cutoff)
    by_setup_x_timing_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "setup_timing_bucket", rank_cutoff=rank_cutoff)
    by_month_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "month", rank_cutoff=rank_cutoff)
    by_month_timing_window_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "month_timing_window", rank_cutoff=rank_cutoff)
    by_month_timing_phase_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "month_timing_phase", rank_cutoff=rank_cutoff)
    by_setup_month_timing_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "setup_month_timing_bucket", rank_cutoff=rank_cutoff)
    by_setup_month_timing_phase_rank_limit = _candidate_trade_group_rank_limit_metrics(evaluated, "setup_month_timing_phase_bucket", rank_cutoff=rank_cutoff)
    by_evaluation_window_rank_limit = _candidate_trade_evaluation_window_rank_limit_metrics(evaluated, rank_cutoff=rank_cutoff)
    by_d1_outcome = _candidate_trade_d1_outcome_metrics(evaluated, sample_limit=sample_limit)
    by_exit_reason = _candidate_trade_group_metrics(evaluated, "exit_reason")
    daily_summaries = _candidate_trade_daily_summaries(ranked_samples, rank_cutoff=rank_cutoff)
    yearly_summaries = _candidate_trade_yearly_summaries(evaluated, rank_cutoff=rank_cutoff)
    summary = _candidate_trade_metric_summary(evaluated)
    summary["annual_return_pct"] = None if is_tail_entry_report else _candidate_trade_average_holding_annualized_return_pct(evaluated)
    summary["annualized_return_method"] = "not_primary_next_day_label" if is_tail_entry_report else "average_trade_return_by_average_holding_days"
    summary["signal_day_compound_annual_return_pct"] = _candidate_trade_signal_day_compound_annualized_return_pct(evaluated)
    sorted_by_return = sorted(evaluated, key=lambda item: (_sort_float(item.get("return_pct")), str(item.get("entry_signal_date") or ""), str(item.get("vt_symbol") or "")))
    sample_cutoff = min(max(int(sample_limit or 500), 1), 1000)
    return {
        "status": "ready" if ranked_samples else "empty",
        "method": "候选质量只读评估：全历史每个交易日只看每日Top5/Top10/Top20，D日BUY候选按D日收盘价买入，D+1收盘收益作为主胜率和主收益；D+2/D+3只作为是否格局的辅助标签。",
        "entry_selection": "daily_candidate",
        "entry_model": "signal_day_close" if is_tail_entry_report else "legacy_next_open",
        "primary_metric": "d1_close_return_pct" if is_tail_entry_report else "sell_exit_return_pct",
        "rank_limit": rank_cutoff,
        "sample_limit": sample_cutoff,
        "summary": summary,
        "by_rank_bucket": by_rank_bucket,
        "by_rank_limit": by_rank_limit,
        "by_daily_rank_window": by_daily_rank_window,
        "by_score_bucket": by_score_bucket,
        "by_setup_family": by_setup_family,
        "by_market_phase": by_market_phase,
        "by_timing_window": by_timing_window,
        "by_timing_phase": by_timing_phase,
        "by_setup_x_timing": by_setup_x_timing,
        "by_month": by_month,
        "by_evaluation_window": by_evaluation_window,
        "by_setup_family_rank_limit": by_setup_family_rank_limit,
        "by_market_phase_rank_limit": by_market_phase_rank_limit,
        "by_timing_window_rank_limit": by_timing_window_rank_limit,
        "by_timing_phase_rank_limit": by_timing_phase_rank_limit,
        "by_setup_x_timing_rank_limit": by_setup_x_timing_rank_limit,
        "by_month_rank_limit": by_month_rank_limit,
        "by_month_timing_window_rank_limit": by_month_timing_window_rank_limit,
        "by_month_timing_phase_rank_limit": by_month_timing_phase_rank_limit,
        "by_setup_month_timing_rank_limit": by_setup_month_timing_rank_limit,
        "by_setup_month_timing_phase_rank_limit": by_setup_month_timing_phase_rank_limit,
        "by_evaluation_window_rank_limit": by_evaluation_window_rank_limit,
        "by_d1_outcome": by_d1_outcome,
        "by_exit_reason": by_exit_reason,
        "data_quality": _candidate_trade_data_quality_summary(evaluated),
        "summary_without_price_discontinuity": _candidate_trade_metric_summary(clean_evaluated),
        "by_exit_reason_without_price_discontinuity": _candidate_trade_group_metrics(clean_evaluated, "exit_reason"),
        "bucket_audit": candidate_trade_bucket_audit_from_results(results, rank_limit=rank_cutoff, sample_limit=sample_cutoff),
        "volume_audit": candidate_trade_volume_audit_from_results(results, rank_limit=rank_cutoff, sample_limit=sample_cutoff),
        "yearly": yearly_summaries,
        "daily_summaries": daily_summaries,
        "best_samples": list(reversed(sorted_by_return[-10:])),
        "worst_samples": sorted_by_return[:10],
        "items": sorted(ranked_samples, key=lambda item: (str(item.get("entry_signal_date") or ""), str(item.get("vt_symbol") or "")))[:sample_cutoff],
        "coverage": {
            "sample_count": len(results),
            "rank_limited_sample_count": len(ranked_samples),
            "daily_candidate_trade_count": len(results),
            # Backward-compatible aliases for older frontend clients.
            "cluster_count": len(results),
            "rank_limited_cluster_count": len(ranked_samples),
            "evaluated_count": len(evaluated),
            "missing_count": len(missing),
            "no_execute_bar_count": sum(1 for item in missing if item.get("status") == "no_execute_bar"),
            "limit_up_open_blocked_count": sum(1 for item in missing if item.get("status") == "limit_up_open_blocked"),
        },
        "uses_future_for_label_only": True,
        "not_used_for_signal_score": True,
        "note": "这是候选本身质量评估，不是组合收益；Top5/Top10/Top20 表示全历史每个信号日排名前 N 的独立候选汇总。主口径只问 D 日收盘买入后 D+1 收盘是否上涨，D+2/D+3 是否值得格局只作为后验标签，不进入 D 日信号评分。",
    }


def candidate_trade_bucket_audit_from_results(
    results: list[IndependentTradeResult],
    *,
    rank_limit: int = 20,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Classify candidate-quality samples into read-only loss and winner buckets."""

    rank_cutoff = min(max(int(rank_limit or 20), 1), 200)
    sample_cutoff = min(max(int(sample_limit or 20), 1), 100)
    samples = [_candidate_trade_sample(result) for result in results]
    evaluated = [
        item
        for item in samples
        if _candidate_effective_rank(item) <= rank_cutoff
        and item.get("status") in {"closed", "open"}
        and _float_or_none(item.get("return_pct")) is not None
    ]
    return {
        "status": "ready" if evaluated else "empty",
        "method": "只读审计：复用候选质量样本，把每日候选独立交易按亏损路径、赢家路径和信号日可见结构分桶；后验收益/MFE/MAE只用于归因，不参与评分或买卖。",
        "entry_selection": "daily_candidate",
        "rank_limit": rank_cutoff,
        "sample_limit": sample_cutoff,
        "summary": _candidate_trade_metric_summary(evaluated),
        "path_buckets": _candidate_trade_path_buckets(evaluated),
        "loss_buckets": _candidate_trade_multi_buckets(
            evaluated,
            _candidate_loss_bucket_keys,
            sample_limit=sample_cutoff,
            reverse=False,
        ),
        "winner_buckets": _candidate_trade_multi_buckets(
            evaluated,
            _candidate_winner_bucket_keys,
            sample_limit=sample_cutoff,
            reverse=True,
        ),
        "coverage": {
            "sample_count": len(evaluated),
            "loss_sample_count": sum(1 for item in evaluated if (_float_or_none(item.get("return_pct")) or 0.0) < 0),
            "winner_sample_count": sum(1 for item in evaluated if (_float_or_none(item.get("return_pct")) or 0.0) > 0),
            "mfe8_giveback_count": sum(1 for item in evaluated if _candidate_is_mfe_giveback(item)),
            "pure_loss_count": sum(1 for item in evaluated if _candidate_is_pure_loss(item)),
            "right_tail_count": sum(1 for item in evaluated if _candidate_is_right_tail(item)),
        },
        "uses_future_for_label_only": True,
        "not_used_for_signal_score": True,
    }


def candidate_trade_volume_audit_from_results(
    results: list[IndependentTradeResult],
    *,
    rank_limit: int = 20,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Audit whether visible volume/preparation factors explain candidate losses."""

    rank_cutoff = min(max(int(rank_limit or 20), 1), 200)
    sample_cutoff = min(max(int(sample_limit or 20), 1), 100)
    samples = [_candidate_trade_sample(result) for result in results]
    evaluated = [
        item
        for item in samples
        if _candidate_effective_rank(item) <= rank_cutoff
        and item.get("status") in {"closed", "open"}
        and _float_or_none(item.get("return_pct")) is not None
    ]
    losers = [item for item in evaluated if (_float_or_none(item.get("return_pct")) or 0.0) < 0]
    return {
        "status": "ready" if evaluated else "empty",
        "method": "只读审计：用信号日可见的成交量、近端活跃、低吸天数和 fresh lift 结构分桶，解释买后亏损是否来自量能/洗盘准备不足；后验收益/MFE/MAE只用于归因，不参与评分或买卖。",
        "entry_selection": "daily_candidate",
        "rank_limit": rank_cutoff,
        "sample_limit": sample_cutoff,
        "summary": _candidate_trade_metric_summary(evaluated),
        "by_volume_ratio": _candidate_trade_labeled_group_metrics(evaluated, "volume_bucket", _candidate_volume_ratio_bucket),
        "by_active_volume": _candidate_trade_labeled_group_metrics(evaluated, "active_volume_bucket", _candidate_active_volume_bucket),
        "by_preparation": _candidate_trade_labeled_group_metrics(evaluated, "preparation_bucket", _candidate_preparation_bucket),
        "loss_by_volume_ratio": _candidate_trade_labeled_group_metrics(losers, "volume_bucket", _candidate_volume_ratio_bucket),
        "loss_by_preparation": _candidate_trade_labeled_group_metrics(losers, "preparation_bucket", _candidate_preparation_bucket),
        "loss_path_by_preparation": _candidate_loss_path_preparation_buckets(evaluated, sample_limit=sample_cutoff),
        "coverage": {
            "sample_count": len(evaluated),
            "loss_sample_count": len(losers),
            "volume_ratio_missing_count": sum(1 for item in evaluated if _candidate_evidence_float(item, "volume_ratio_5d_20d") is None),
            "volume_stall_count": sum(1 for item in evaluated if _candidate_volume_stall(_candidate_sample_evidence(item))),
            "no_recent_active_bar_count": sum(1 for item in evaluated if _candidate_active_volume_bucket(item) == "no_recent_active_bar"),
            "prepared_shrink_lift_count": sum(1 for item in evaluated if _candidate_preparation_bucket(item) == "prepared_shrink_lift"),
        },
        "uses_future_for_label_only": True,
        "not_used_for_signal_score": True,
    }


def fixed_horizon_outcome_row(
    *,
    signal_date: date,
    bars: list[Bar],
    horizons: tuple[int, ...] = (3, 5, 10, 20),
) -> dict[str, Any]:
    sorted_bars = sorted(bars, key=lambda bar: bar.trade_date)
    execute_index = next((index for index, bar in enumerate(sorted_bars) if bar.trade_date > signal_date), None)
    if execute_index is None:
        return {
            "status": "no_execute_bar",
            "signal_date": signal_date,
            "execute_date": None,
            "execute_open_price": None,
            "uses_future_for_label_only": True,
            "not_used_for_signal_score": True,
        }

    execute_bar = sorted_bars[execute_index]
    execute_price = float(execute_bar.open_price)
    payload: dict[str, Any] = {
        "status": "ready",
        "signal_date": signal_date,
        "execute_date": execute_bar.trade_date,
        "execute_open_price": round(execute_price, 4),
        "uses_future_for_label_only": True,
        "not_used_for_signal_score": True,
    }
    first_profit_index: int | None = None
    first_loss_index: int | None = None
    for horizon in horizons:
        close_index = min(execute_index + horizon, len(sorted_bars) - 1)
        window = sorted_bars[execute_index: close_index + 1]
        if not window:
            continue
        close_bar = sorted_bars[close_index]
        max_high = max(float(bar.high_price) for bar in window)
        min_low = min(float(bar.low_price) for bar in window)
        close_return = _pct_return(float(close_bar.close_price), execute_price)
        mfe = _pct_return(max_high, execute_price)
        mae = _pct_return(min_low, execute_price)
        suffix = f"{horizon}d"
        payload[f"return_{suffix}"] = close_return
        payload[f"mfe_{suffix}"] = mfe
        payload[f"mae_{suffix}"] = mae
        first_profit_index = _first_threshold_index(window, execute_price, threshold_pct=5.0, high_side=True, current=first_profit_index)
        first_loss_index = _first_threshold_index(window, execute_price, threshold_pct=-3.0, high_side=False, current=first_loss_index)

    max_mfe = max((_float_or_none(value) or 0.0) for key, value in payload.items() if key.startswith("mfe_"))
    min_mae = min((_float_or_none(value) or 0.0) for key, value in payload.items() if key.startswith("mae_"))
    payload["hit_profit_5_pct"] = max_mfe >= 5.0
    payload["hit_profit_8_pct"] = max_mfe >= 8.0
    payload["hit_profit_10_pct"] = max_mfe >= 10.0
    payload["hit_loss_3_pct"] = min_mae <= -3.0
    payload["hit_loss_5_pct"] = min_mae <= -5.0
    payload["hit_loss_7_pct"] = min_mae <= -7.0
    payload["first_hit"] = _first_hit(first_profit_index, first_loss_index)
    payload["failed_launch"] = not bool(payload.get("hit_profit_5_pct")) and bool(payload.get("hit_loss_3_pct"))
    payload["support_stop_like"] = bool(payload.get("hit_loss_5_pct") or payload.get("hit_loss_7_pct"))
    return payload


def current_strategy_trade_outcome_map(
    trades: list[dict[str, Any]],
    *,
    candidate_signal_dates_by_symbol: dict[str, list[date]] | None = None,
) -> dict[tuple[str, date], dict[str, Any]]:
    """Map candidate signal dates to real portfolio trade outcomes."""

    open_buys: dict[str, list[dict[str, Any]]] = {}
    outcomes: dict[tuple[str, date], dict[str, Any]] = {}
    signal_dates = candidate_signal_dates_by_symbol or {}
    for trade in sorted(trades, key=lambda row: (_date_or_none(row.get("trade_date")) or date.min, _int_or_none(row.get("id")) or 0)):
        symbol = str(trade.get("vt_symbol") or "").upper()
        if not symbol:
            continue
        side = str(trade.get("side") or "").upper()
        if side == "BUY":
            open_buys.setdefault(symbol, []).append(trade)
            continue
        if side != "SELL" or not open_buys.get(symbol):
            continue
        buy = open_buys[symbol].pop(0)
        for signal_date in _signal_dates_for_buy_trade(buy, signal_dates.get(symbol, [])):
            outcomes[(symbol, signal_date)] = _current_strategy_trade_payload(buy, trade)

    for symbol, buys in open_buys.items():
        for buy in buys:
            for signal_date in _signal_dates_for_buy_trade(buy, signal_dates.get(symbol, [])):
                outcomes[(symbol, signal_date)] = _current_strategy_trade_payload(buy, None)
    return outcomes


def _candidate_evidence(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("reason") if isinstance(row.get("reason"), dict) else row.get("evidence")
    if not isinstance(raw, dict):
        raw = {}
    return normalize_quant_evidence(dict(raw))


def _timeline_row(rows: dict[str, dict[str, Any]], value: Any, vt_symbol: str) -> dict[str, Any]:
    key = _date_to_iso(value) or "unknown"
    if key not in rows:
        rows[key] = {"date": key, "vt_symbol": vt_symbol, "markers": []}
    return rows[key]


def _candidate_timeline_payload(row: dict[str, Any]) -> dict[str, Any]:
    reason = _candidate_evidence(row)
    return {
        "date": _date_to_iso(row.get("trade_date")),
        "action": reason.get("action") or row.get("action"),
        "rank": _int_or_none(row.get("rank")),
        "score": _float_or_none(row.get("total_score")),
        "entry_family_label": reason.get("entry_family_label"),
        "low_position_reclaim_label": reason.get("low_position_reclaim_label"),
        "low_suction_days": _float_or_none(reason.get("low_suction_days")),
        "low_suction_launch_confirmed": bool(reason.get("low_suction_launch_confirmed")),
        "first_effective_lift": bool(reason.get("first_effective_lift") or reason.get("low_suction_launch_confirmed")),
        "low_suction_launch_quality_bucket": reason.get("low_suction_launch_quality_bucket"),
        "low_suction_stage_label": reason.get("low_suction_stage_label"),
        "reason": reason,
    }


def _plan_timeline_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "planned",
        "signal_date": _date_to_iso(row.get("signal_date")),
        "execute_date": _date_to_iso(row.get("execute_date") or row.get("trade_date")),
        "side": row.get("side"),
        "score": _float_or_none(row.get("score")),
        "reason": row.get("reason"),
        "raw": row.get("raw") if isinstance(row.get("raw"), dict) else {},
    }


def _execution_timeline_payload(row: dict[str, Any]) -> dict[str, Any]:
    raw_status = str(row.get("status") or "").lower()
    side = str(row.get("side") or "").upper()
    status = "planned_not_ordered" if raw_status in {"rejected", "cancelled", "blocked"} and side == "BUY" else raw_status or "ordered"
    return {
        "status": status,
        "side": side,
        "price": _float_or_none(row.get("price")),
        "reason_code": row.get("reason"),
        "raw_status": row.get("status"),
        "raw": row.get("raw") if isinstance(row.get("raw"), dict) else {},
    }


def _trade_execution_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "filled",
        "side": row.get("side"),
        "price": _float_or_none(row.get("price")),
        "volume": _int_or_none(row.get("volume")),
        "reason": row.get("reason"),
        "raw": row.get("raw") if isinstance(row.get("raw"), dict) else {},
    }


def _sell_timeline_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "sold",
        "price": _float_or_none(row.get("price")),
        "volume": _int_or_none(row.get("volume")),
        "reason": row.get("reason"),
        "pnl": _float_or_none(row.get("pnl")),
        "raw": row.get("raw") if isinstance(row.get("raw"), dict) else {},
    }


def _dedupe_timeline_markers(row: dict[str, Any]) -> dict[str, Any]:
    seen: set[str] = set()
    markers: list[str] = []
    for marker in row.get("markers") or []:
        if marker not in seen:
            seen.add(marker)
            markers.append(marker)
    row["markers"] = markers
    return row


def _timeline_display_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    buildup_cluster: list[dict[str, Any]] = []

    def flush_cluster() -> None:
        nonlocal buildup_cluster
        if not buildup_cluster:
            return
        result.append(_timeline_buildup_cluster_row(buildup_cluster))
        buildup_cluster = []

    for row in rows:
        if _is_buildup_only_timeline_row(row):
            buildup_cluster.append(row)
            continue
        flush_cluster()
        result.append(_with_timeline_display_markers(row))
    flush_cluster()
    return result


def _with_timeline_display_markers(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    display_markers: list[str] = []
    execution = item.get("execution") if isinstance(item.get("execution"), dict) else {}
    sell = item.get("sell") if isinstance(item.get("sell"), dict) else {}
    candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
    if candidate:
        action = str(candidate.get("action") or "").upper()
        display_markers.append("BUY_SIGNAL" if action == "BUY" and _is_key_timeline_candidate(candidate) else "BUY_REJECTED")
    if execution:
        status = str(execution.get("status") or "").lower()
        side = str(execution.get("side") or "").upper()
        if status == "filled" and side == "BUY":
            display_markers.append("BUY_FILLED")
        elif status in {"planned_not_ordered", "rejected"} and side == "BUY":
            display_markers.append("BUY_REJECTED")
    if sell:
        display_markers.append("SELL_FILLED")
    item["display_markers"] = _dedupe_list(display_markers)
    return item


def _is_executable_buy_candidate(row: dict[str, Any]) -> bool:
    feature = candidate_feature_row(row) if not row.get("entry_action") else row
    action = str(feature.get("entry_action") or feature.get("action") or "").upper()
    return action == "BUY" or bool(feature.get("executable_entry_signal") and action in {"", "BUY"})


def _candidate_trading_day_gap(left: date, right: date, date_index: dict[date, int]) -> int:
    left_index = date_index.get(left)
    right_index = date_index.get(right)
    if left_index is None or right_index is None:
        return max((right - left).days, 0)
    return max(right_index - left_index, 0)


def _candidate_cluster(symbol: str, rows: list[dict[str, Any]]) -> CandidateCluster:
    dates = [_date_or_none(row.get("_cluster_trade_date") or row.get("trade_date") or row.get("signal_date")) for row in rows]
    valid_dates = [day for day in dates if day is not None]
    cleaned_rows = []
    for row in rows:
        item = dict(row)
        item.pop("_cluster_trade_date", None)
        cleaned_rows.append(item)
    return CandidateCluster(
        vt_symbol=symbol,
        rows=tuple(cleaned_rows),
        cluster_start_date=min(valid_dates),
        cluster_end_date=max(valid_dates),
        entry_row=_select_first_visible_candidate_entry(cleaned_rows),
    )


def _select_first_visible_candidate_entry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return min(
        rows,
        key=lambda row: (
            _date_or_none(row.get("trade_date") or row.get("signal_date")) or date.max,
            _int_or_none(row.get("rank")) or 10**9,
            str(row.get("vt_symbol") or ""),
        ),
    )


def _select_candidate_cluster_preferred_entry_for_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def key(row: dict[str, Any]) -> tuple[int, float, date]:
        evidence = _candidate_evidence(row)
        launch_confirmed = bool(
            row.get("launch_confirmed")
            or row.get("first_effective_lift")
            or evidence.get("low_suction_launch_confirmed")
            or evidence.get("first_effective_lift")
        )
        return (
            1 if launch_confirmed else 0,
            _float_or_none(row.get("total_score") or row.get("score") or evidence.get("total_score")) or -10**9,
            _date_or_none(row.get("trade_date") or row.get("signal_date")) or date.min,
        )

    return max(rows, key=key)


def _candidate_independent_position(cluster: CandidateCluster, entry_bar: Bar, entry_price: float) -> Position:
    evidence = _candidate_evidence(cluster.entry_row)
    return Position(
        vt_symbol=cluster.vt_symbol,
        name=cluster.entry_row.get("name"),
        volume=100,
        cost_price=entry_price,
        entry_date=entry_bar.trade_date,
        highest_price=float(entry_bar.high_price),
        lowest_price=float(entry_bar.low_price),
        reason={**evidence, "execution": {"mode": "candidate_quality_next_open", "price_source": "stock_daily_bars.open_price"}},
        last_price=float(entry_bar.close_price),
    )


def _independent_trade_missing(
    cluster: CandidateCluster,
    signal_date: date,
    status: str,
    *,
    execute_date: date | None = None,
) -> IndependentTradeResult:
    return IndependentTradeResult(
        status=status,
        cluster=cluster,
        entry_signal_date=signal_date,
        entry_execute_date=execute_date,
        entry_price=None,
        exit_signal_date=None,
        exit_execute_date=None,
        exit_price=None,
        return_pct=None,
        max_drawdown_pct=None,
        max_runup_pct=None,
        holding_days=None,
        exit_reason=status,
        window=(),
    )


def _independent_trade_closed_result(
    cluster: CandidateCluster,
    *,
    signal_date: date,
    entry_execute_date: date,
    entry_price: float,
    exit_signal_date: date,
    exit_execute_date: date,
    exit_price: float,
    exit_reason: str,
    window: list[Bar],
) -> IndependentTradeResult:
    return IndependentTradeResult(
        status="closed",
        cluster=cluster,
        entry_signal_date=signal_date,
        entry_execute_date=entry_execute_date,
        entry_price=round(entry_price, 4),
        exit_signal_date=exit_signal_date,
        exit_execute_date=exit_execute_date,
        exit_price=round(exit_price, 4),
        return_pct=_pct_return(exit_price, entry_price),
        max_drawdown_pct=_window_mae(window, entry_price),
        max_runup_pct=_window_mfe(window, entry_price),
        holding_days=max(len(window) - 1, 0),
        exit_reason=exit_reason,
        window=tuple(window),
    )


def _independent_trade_open_result(
    cluster: CandidateCluster,
    signal_date: date,
    entry_execute_date: date,
    entry_price: float,
    window: list[Bar],
) -> IndependentTradeResult:
    last_bar = window[-1] if window else None
    exit_price = float(last_bar.close_price) if last_bar else None
    return IndependentTradeResult(
        status="open",
        cluster=cluster,
        entry_signal_date=signal_date,
        entry_execute_date=entry_execute_date,
        entry_price=round(entry_price, 4),
        exit_signal_date=None,
        exit_execute_date=None,
        exit_price=round(exit_price, 4) if exit_price is not None else None,
        return_pct=_pct_return(exit_price, entry_price) if exit_price is not None else None,
        max_drawdown_pct=_window_mae(window, entry_price),
        max_runup_pct=_window_mfe(window, entry_price),
        holding_days=max(len(window) - 1, 0) if window else 0,
        exit_reason="open",
        window=tuple(window),
    )


def _tail_entry_label_window(sorted_bars: list[Bar], signal_date: date, d1_date: date | None) -> list[Bar]:
    if d1_date is None:
        return [bar for bar in sorted_bars if bar.trade_date == signal_date]
    result = [bar for bar in sorted_bars if signal_date <= bar.trade_date <= d1_date]
    d1_index = next((index for index, bar in enumerate(sorted_bars) if bar.trade_date == d1_date), None)
    if d1_index is None:
        return result
    return sorted_bars[max(0, d1_index - 1): min(len(sorted_bars), d1_index + 3)]


def _candidate_trade_sample(result: IndependentTradeResult) -> dict[str, Any]:
    cluster = result.cluster
    entry = cluster.entry_row
    evidence = _candidate_evidence(entry)
    preferred_entry = _select_candidate_cluster_preferred_entry_for_audit(list(cluster.rows))
    preferred_evidence = _candidate_evidence(preferred_entry)
    rank = _int_or_none(entry.get("rank"))
    execution = entry.get("candidate_execution") if isinstance(entry.get("candidate_execution"), dict) else {}
    execution_rank = _int_or_none(execution.get("execution_candidate_rank"))
    effective_rank = execution_rank or rank
    score = _float_or_none(entry.get("total_score") or entry.get("score") or evidence.get("total_score"))
    setup_family = _candidate_setup_family(entry, evidence)
    market_phase = _candidate_market_phase(entry, evidence)
    timing_window = _candidate_timing_window(entry, evidence)
    timing_phase = f"{timing_window}::{market_phase}"
    setup_timing_bucket = f"{setup_family}::{timing_window}"
    month = result.entry_signal_date.strftime("%Y-%m")
    month_timing_window = f"{month}::{timing_window}"
    month_timing_phase = f"{month}::{timing_window}::{market_phase}"
    setup_month_timing_bucket = f"{setup_family}::{month}::{timing_window}"
    setup_month_timing_phase_bucket = f"{setup_family}::{month}::{timing_window}::{market_phase}"
    price_discontinuity = data_quality.candidate_price_discontinuity(
        list(result.window),
        vt_symbol=cluster.vt_symbol,
        signal_date=result.entry_signal_date,
        entry_execute_date=result.entry_execute_date,
        exit_execute_date=result.exit_execute_date,
    )
    payload = {
        "status": result.status,
        "vt_symbol": cluster.vt_symbol,
        "name": entry.get("name"),
        "rank": rank,
        "raw_rank": rank,
        "execution_candidate_rank": execution_rank,
        "effective_rank": effective_rank,
        "score": score,
        "rank_bucket": _candidate_trade_rank_bucket(effective_rank),
        "daily_rank_window": _candidate_trade_rank_window(effective_rank),
        "score_bucket": _candidate_trade_score_bucket(score),
        "setup_family": setup_family,
        "setup_family_label": _candidate_setup_family_label(setup_family),
        "market_phase": market_phase,
        "market_phase_label": _candidate_market_phase_label(market_phase),
        "timing_window": timing_window,
        "timing_window_label": _candidate_timing_window_label(timing_window),
        "timing_phase": timing_phase,
        "timing_phase_label": _candidate_timing_phase_label(timing_phase),
        "setup_timing_bucket": setup_timing_bucket,
        "setup_timing_label": _candidate_setup_timing_label(setup_timing_bucket),
        "month": month,
        "month_label": month,
        "month_timing_window": month_timing_window,
        "month_timing_window_label": _candidate_month_timing_window_label(month_timing_window),
        "month_timing_phase": month_timing_phase,
        "month_timing_phase_label": _candidate_month_timing_phase_label(month_timing_phase),
        "setup_month_timing_bucket": setup_month_timing_bucket,
        "setup_month_timing_label": _candidate_setup_month_timing_label(setup_month_timing_bucket),
        "setup_month_timing_phase_bucket": setup_month_timing_phase_bucket,
        "setup_month_timing_phase_label": _candidate_setup_month_timing_phase_label(setup_month_timing_phase_bucket),
        "entry_signal_date": _date_to_iso(result.entry_signal_date),
        "entry_execute_date": _date_to_iso(result.entry_execute_date),
        "entry_price": result.entry_price,
        "exit_signal_date": _date_to_iso(result.exit_signal_date),
        "exit_execute_date": _date_to_iso(result.exit_execute_date),
        "exit_price": result.exit_price,
        "return_pct": result.return_pct,
        "max_drawdown_pct": result.max_drawdown_pct,
        "max_runup_pct": result.max_runup_pct,
        "holding_days": result.holding_days,
        "exit_reason": result.exit_reason,
        "has_price_discontinuity": bool(price_discontinuity),
        "first_price_discontinuity_date": _date_to_iso(price_discontinuity.get("trade_date")) if price_discontinuity else None,
        "first_price_discontinuity_open_gap_pct": price_discontinuity.get("open_gap_pct") if price_discontinuity else None,
        "first_price_discontinuity_close_gap_pct": price_discontinuity.get("close_gap_pct") if price_discontinuity else None,
        "first_price_discontinuity_change_pct": price_discontinuity.get("change_pct") if price_discontinuity else None,
        "cluster_start_date": _date_to_iso(cluster.cluster_start_date),
        "cluster_end_date": _date_to_iso(cluster.cluster_end_date),
        "cluster_size": len(cluster.rows),
        "entry_selection": "daily_candidate",
        "cluster_preferred_entry_signal_date_for_audit": _date_to_iso(preferred_entry.get("trade_date") or preferred_entry.get("signal_date")),
        "cluster_preferred_entry_score_for_audit": _float_or_none(
            preferred_entry.get("total_score")
            or preferred_entry.get("score")
            or preferred_evidence.get("total_score")
        ),
        "cluster_preferred_entry_not_used_for_trade": preferred_entry is not entry,
        "entry_reason": {**{key: value for key, value in entry.items() if key not in {"outcome", "reason"}}, **evidence},
        "uses_future_for_label_only": True,
        "not_used_for_signal_score": True,
    }
    for key, value in (result.labels or {}).items():
        if key in {"status", "entry_signal_date", "entry_selection"}:
            continue
        payload[key] = value
    payload.update(stock_board_payload(cluster.vt_symbol, entry.get("exchange")))
    return payload


def _candidate_effective_rank(row: dict[str, Any]) -> int:
    return _int_or_none(row.get("effective_rank") or row.get("execution_candidate_rank") or row.get("rank")) or 10**9


def _candidate_trade_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    order: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or "unknown"), []).append(row)
    result = []
    for bucket, bucket_rows in groups.items():
        result.append({key: bucket, "label": _candidate_trade_bucket_label(key, bucket), **_candidate_trade_metric_summary(bucket_rows)})
    result.sort(key=lambda item: ((order or {}).get(str(item.get(key) or ""), 10**6), -int(item.get("sample_count") or 0), str(item.get(key) or "")))
    return result


def _candidate_trade_group_rank_limit_metrics(
    rows: list[dict[str, Any]],
    key: str,
    *,
    rank_cutoff: int,
    order: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or "unknown"), []).append(row)

    result = []
    for bucket, bucket_rows in groups.items():
        result.append(
            {
                key: bucket,
                "label": _candidate_trade_bucket_label(key, bucket),
                **_candidate_trade_topn_summaries(bucket_rows, rank_cutoff=rank_cutoff),
            }
        )
    result.sort(key=lambda item: _candidate_trade_group_rank_limit_sort_key(item, key, order))
    return result


def _candidate_trade_rank_limit_metrics(rows: list[dict[str, Any]], *, rank_cutoff: int) -> list[dict[str, Any]]:
    result = []
    for limit in (5, 10, 20):
        if limit > rank_cutoff:
            continue
        bucket_rows = [row for row in rows if _candidate_effective_rank(row) <= limit]
        if not bucket_rows:
            continue
        result.append(
            {
                "rank_limit": limit,
                "label": f"每日Top{limit}",
                **_candidate_trade_metric_summary(bucket_rows),
            }
        )
    return result


def _candidate_trade_evaluation_window_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for key, label, start, end in _candidate_trade_evaluation_window_definitions(rows):
        bucket_rows = _candidate_trade_rows_in_date_window(rows, start, end)
        if not bucket_rows:
            continue
        result.append(
            {
                "evaluation_window": key,
                "label": label,
                **_candidate_trade_metric_summary(bucket_rows),
            }
        )
    return result


def _candidate_trade_evaluation_window_rank_limit_metrics(rows: list[dict[str, Any]], *, rank_cutoff: int) -> list[dict[str, Any]]:
    result = []
    for key, label, start, end in _candidate_trade_evaluation_window_definitions(rows):
        bucket_rows = _candidate_trade_rows_in_date_window(rows, start, end)
        if not bucket_rows:
            continue
        result.append(
            {
                "evaluation_window": key,
                "label": label,
                **_candidate_trade_topn_summaries(bucket_rows, rank_cutoff=rank_cutoff),
            }
        )
    return result


def _candidate_trade_evaluation_window_definitions(rows: list[dict[str, Any]]) -> list[tuple[str, str, date | None, date | None]]:
    if not rows:
        return []
    signal_dates = [day for row in rows if (day := _date_or_none(row.get("entry_signal_date"))) is not None]
    if not signal_dates:
        return []
    latest = max(signal_dates)
    return [
        ("full_sample", "全样本", None, None),
        ("recent_3_months", "最近3个月", latest - timedelta(days=93), latest),
        ("recent_6_months", "最近6个月", latest - timedelta(days=186), latest),
        ("silver_pressure_2026_03_13_03_24", "银手指压力 2026-03-13..03-24", date(2026, 3, 13), date(2026, 3, 24)),
        ("june_repair_2026_06_09_07_03", "6月底部修复 2026-06-09..07-03", date(2026, 6, 9), date(2026, 7, 3)),
    ]


def _candidate_trade_rows_in_date_window(
    rows: list[dict[str, Any]],
    start: date | None,
    end: date | None,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if (day := _date_or_none(row.get("entry_signal_date"))) is not None
        and (start is None or day >= start)
        and (end is None or day <= end)
    ]


def _candidate_trade_topn_summaries(rows: list[dict[str, Any]], *, rank_cutoff: int) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for limit in (5, 10, 20):
        if limit > rank_cutoff:
            continue
        limit_rows = [row for row in rows if _candidate_effective_rank(row) <= limit]
        summaries[f"top{limit}"] = _candidate_trade_metric_summary(limit_rows)
    return summaries


def _candidate_trade_group_rank_limit_sort_key(
    item: dict[str, Any],
    key: str,
    order: dict[str, int] | None,
) -> tuple[Any, ...]:
    bucket = str(item.get(key) or "")
    if key == "month":
        return (bucket,)
    if key in {
        "month_timing_window",
        "month_timing_phase",
        "setup_month_timing_bucket",
        "setup_month_timing_phase_bucket",
    }:
        return _candidate_trade_month_composite_sort_key(bucket, key)
    top20 = item.get("top20") if isinstance(item.get("top20"), dict) else {}
    top10 = item.get("top10") if isinstance(item.get("top10"), dict) else {}
    sample_count = int((top20 or top10 or {}).get("sample_count") or 0)
    return ((order or {}).get(bucket, 10**6), -sample_count, bucket)


def _candidate_trade_month_composite_sort_key(bucket: str, key: str) -> tuple[Any, ...]:
    parts = bucket.split("::")
    if key == "month_timing_window":
        month, timing, phase, setup = _part(parts, 0), _part(parts, 1), "", ""
    elif key == "month_timing_phase":
        month, timing, phase, setup = _part(parts, 0), _part(parts, 1), _part(parts, 2), ""
    elif key == "setup_month_timing_bucket":
        setup, month, timing, phase = _part(parts, 0), _part(parts, 1), _part(parts, 2), ""
    else:
        setup, month, timing, phase = _part(parts, 0), _part(parts, 1), _part(parts, 2), _part(parts, 3)
    return (
        month or "9999-99",
        _candidate_timing_window_order.get(timing, 10**6),
        _candidate_market_phase_order.get(phase, 10**6),
        _candidate_setup_family_order.get(setup, 10**6),
        bucket,
    )


def _part(parts: list[str], index: int) -> str:
    return parts[index] if index < len(parts) else ""


def _candidate_trade_d1_outcome_metrics(rows: list[dict[str, Any]], *, sample_limit: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for key in _candidate_d1_outcome_keys(row):
            groups.setdefault(key, []).append(row)
    result = []
    for key, bucket_rows in groups.items():
        reverse = key not in {"d1_big_drop", "d1_low_open_or_low_close", "d1_deep_intraday_drawdown"}
        result.append(
            {
                "d1_outcome": key,
                "label": _candidate_d1_outcome_label(key),
                **_candidate_trade_metric_summary(bucket_rows),
                "examples": _candidate_bucket_examples(
                    bucket_rows,
                    limit=min(max(int(sample_limit or 20), 1), 20),
                    reverse=reverse,
                ),
                "uses_future_for_label_only": True,
                "not_used_for_signal_score": True,
            }
        )
    result.sort(
        key=lambda item: (
            _candidate_d1_outcome_order(str(item.get("d1_outcome") or "")),
            -int(item.get("sample_count") or 0),
        )
    )
    return result


def _candidate_trade_daily_summaries(rows: list[dict[str, Any]], *, rank_cutoff: int, limit: int = 60) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        signal_date = str(row.get("entry_signal_date") or "")
        if signal_date:
            by_date.setdefault(signal_date, []).append(row)

    summaries = []
    for signal_date, date_rows in by_date.items():
        evaluated = [
            row
            for row in date_rows
            if row.get("status") in {"closed", "open"} and _float_or_none(row.get("return_pct")) is not None
        ]
        if not evaluated:
            continue
        top5_rows = [row for row in evaluated if _candidate_effective_rank(row) <= 5]
        top10_rows = [row for row in evaluated if _candidate_effective_rank(row) <= 10]
        top20_rows = [row for row in evaluated if _candidate_effective_rank(row) <= 20]
        topn_rows = [row for row in evaluated if _candidate_effective_rank(row) <= rank_cutoff]
        summaries.append(
            {
                "entry_signal_date": signal_date,
                "candidate_count": len(date_rows),
                "evaluated_count": len(evaluated),
                "missing_count": len(date_rows) - len(evaluated),
                "top5": _candidate_trade_metric_summary(top5_rows),
                "top10": _candidate_trade_metric_summary(top10_rows),
                "top20": _candidate_trade_metric_summary(top20_rows),
                "topn": _candidate_trade_metric_summary(topn_rows),
                "best_candidate": _candidate_trade_daily_extreme(evaluated, reverse=True),
                "worst_candidate": _candidate_trade_daily_extreme(evaluated, reverse=False),
            }
        )
    summaries.sort(key=lambda item: str(item.get("entry_signal_date") or ""), reverse=True)
    return summaries[: max(int(limit or 60), 1)]


def _candidate_trade_yearly_summaries(rows: list[dict[str, Any]], *, rank_cutoff: int) -> list[dict[str, Any]]:
    by_year: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if _candidate_effective_rank(row) > rank_cutoff:
            continue
        signal_date = _date_or_none(row.get("entry_signal_date"))
        if signal_date is None:
            continue
        if row.get("status") not in {"closed", "open"} or _float_or_none(row.get("return_pct")) is None:
            continue
        by_year.setdefault(str(signal_date.year), []).append(row)
    return [
        {
            "year": year,
            "label": f"{year}年",
            **_candidate_trade_metric_summary(year_rows),
            "annual_return_pct": _candidate_trade_average_holding_annualized_return_pct(year_rows),
            "signal_day_compound_annual_return_pct": _candidate_trade_signal_day_compound_annualized_return_pct(year_rows),
        }
        for year, year_rows in sorted(by_year.items())
    ]


def _candidate_trade_path_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _candidate_trade_group_metrics(
        [
            {
                **row,
                "path_bucket": _candidate_path_bucket(row),
            }
            for row in rows
        ],
        "path_bucket",
        {
            "right_tail_winner": 10,
            "steady_winner": 20,
            "mfe_giveback": 30,
            "ordinary_loss": 40,
            "pure_loss": 50,
            "deep_drawdown_loss": 60,
            "flat": 70,
        },
    )


def _candidate_trade_multi_buckets(
    rows: list[dict[str, Any]],
    key_fn,
    *,
    sample_limit: int,
    reverse: bool,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for key in key_fn(row):
            groups.setdefault(key, []).append(row)
    result = []
    for key, bucket_rows in groups.items():
        if not bucket_rows:
            continue
        result.append(
            {
                "bucket": key,
                "label": _candidate_audit_bucket_label(key),
                **_candidate_trade_metric_summary(bucket_rows),
                "examples": _candidate_bucket_examples(bucket_rows, limit=sample_limit, reverse=reverse),
                "not_used_for_signal_score": True,
                "uses_future_for_label_only": True,
            }
        )
    result.sort(
        key=lambda item: (
            _candidate_audit_bucket_order(str(item.get("bucket") or "")),
            -int(item.get("sample_count") or 0),
            _sort_float(item.get("average_return_pct")),
        )
    )
    return result


def _candidate_trade_labeled_group_metrics(
    rows: list[dict[str, Any]],
    key: str,
    bucket_fn,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(bucket_fn(row) or "unknown"), []).append(row)
    result = [
        {
            key: bucket,
            "label": _candidate_volume_bucket_label(bucket),
            **_candidate_trade_metric_summary(bucket_rows),
            "loss_sample_count": sum(1 for item in bucket_rows if (_float_or_none(item.get("return_pct")) or 0.0) < 0),
            "pure_loss_count": sum(1 for item in bucket_rows if _candidate_is_pure_loss(item)),
            "deep_drawdown_loss_count": sum(1 for item in bucket_rows if (_float_or_none(item.get("return_pct")) or 0.0) < 0 and (_float_or_none(item.get("max_drawdown_pct")) or 0.0) <= -8.0),
            "mfe_giveback_count": sum(1 for item in bucket_rows if _candidate_is_mfe_giveback(item)),
            "right_tail_count": sum(1 for item in bucket_rows if _candidate_is_right_tail(item)),
            "uses_future_for_label_only": True,
            "not_used_for_signal_score": True,
        }
        for bucket, bucket_rows in groups.items()
    ]
    result.sort(
        key=lambda item: (
            _candidate_volume_bucket_order(str(item.get(key) or "")),
            -int(item.get("sample_count") or 0),
            _sort_float(item.get("average_return_pct")),
        )
    )
    return result


def _candidate_loss_path_preparation_buckets(
    rows: list[dict[str, Any]],
    *,
    sample_limit: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        path = _candidate_volume_loss_path(row)
        preparation = _candidate_preparation_bucket(row)
        groups.setdefault(f"{path}::{preparation}", []).append(row)
    result = []
    for key, bucket_rows in groups.items():
        path, preparation = key.split("::", 1)
        result.append(
            {
                "loss_path": path,
                "loss_path_label": _candidate_volume_bucket_label(path),
                "preparation_bucket": preparation,
                "preparation_label": _candidate_volume_bucket_label(preparation),
                **_candidate_trade_metric_summary(bucket_rows),
                "examples": _candidate_volume_bucket_examples(bucket_rows, limit=sample_limit, reverse=path == "winner_or_flat"),
                "uses_future_for_label_only": True,
                "not_used_for_signal_score": True,
            }
        )
    result.sort(
        key=lambda item: (
            _candidate_volume_bucket_order(str(item.get("loss_path") or "")),
            _candidate_volume_bucket_order(str(item.get("preparation_bucket") or "")),
            -int(item.get("sample_count") or 0),
        )
    )
    return result


def _candidate_volume_loss_path(row: dict[str, Any]) -> str:
    return_pct = _float_or_none(row.get("return_pct")) or 0.0
    if return_pct >= 0:
        return "winner_or_flat"
    mfe = _float_or_none(row.get("max_runup_pct")) or 0.0
    mae = _float_or_none(row.get("max_drawdown_pct")) or 0.0
    if mfe >= 8.0:
        return "loss_mfe_giveback"
    if mae <= -8.0:
        return "loss_deep_drawdown"
    if mfe < 3.0:
        return "loss_no_mfe"
    return "ordinary_loss"


def _candidate_volume_ratio_bucket(row: dict[str, Any]) -> str:
    ratio = _candidate_evidence_float(row, "volume_ratio_5d_20d")
    if ratio is None:
        return "volume_missing"
    if ratio < 0.55:
        return "extreme_shrink"
    if ratio < 0.85:
        return "shrinking_volume"
    if ratio <= 1.15:
        return "balanced_volume"
    if ratio <= 1.55:
        return "mild_volume_expansion"
    if ratio <= 2.20:
        return "heavy_volume_expansion"
    return "extreme_volume_expansion"


def _candidate_active_volume_bucket(row: dict[str, Any]) -> str:
    evidence = _candidate_sample_evidence(row)
    large_bull_count = _float_or_none(evidence.get("large_bull_count_20d")) or 0.0
    if bool(evidence.get("recent_limit_up_20d")):
        return "recent_limit_up"
    if large_bull_count >= 3.0:
        return "large_bull_ge3"
    if large_bull_count >= 1.0:
        return "large_bull_1_2"
    return "no_recent_active_bar"


def _candidate_preparation_bucket(row: dict[str, Any]) -> str:
    evidence = _candidate_sample_evidence(row)
    low_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    fresh_lift = bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed"))
    if _candidate_volume_stall(evidence):
        return "volume_stall_distribution"
    if low_days >= 3 and fresh_lift and volume_ratio is not None and 0.55 <= volume_ratio <= 1.20:
        return "prepared_shrink_lift"
    if low_days >= 3 and not fresh_lift:
        return "low_suction_no_fresh_lift"
    if low_days >= 3 and fresh_lift:
        return "prepared_lift_bad_volume"
    if _candidate_active_volume_bucket(row) != "no_recent_active_bar" and volume_ratio is not None and 0.85 <= volume_ratio <= 1.55:
        return "active_balanced_volume"
    if _candidate_active_volume_bucket(row) != "no_recent_active_bar":
        return "active_bad_volume"
    return "no_active_no_lift"


def _candidate_sample_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("entry_reason") if isinstance(row.get("entry_reason"), dict) else {}


def _candidate_evidence_float(row: dict[str, Any], key: str) -> float | None:
    return _float_or_none(_candidate_sample_evidence(row).get(key))


def _candidate_volume_bucket_examples(rows: list[dict[str, Any]], *, limit: int, reverse: bool) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            _sort_float(row.get("return_pct")),
            _sort_float(row.get("max_runup_pct")),
            -_candidate_effective_rank(row),
            str(row.get("entry_signal_date") or ""),
            str(row.get("vt_symbol") or ""),
        ),
        reverse=reverse,
    )
    result = []
    for row in ordered[: max(int(limit or 20), 1)]:
        evidence = _candidate_sample_evidence(row)
        result.append(
            {
                "vt_symbol": row.get("vt_symbol"),
                "name": row.get("name"),
                "entry_signal_date": row.get("entry_signal_date"),
                "rank": row.get("rank"),
                "effective_rank": row.get("effective_rank"),
                "score": row.get("score"),
                "return_pct": row.get("return_pct"),
                "max_drawdown_pct": row.get("max_drawdown_pct"),
                "max_runup_pct": row.get("max_runup_pct"),
                "volume_ratio_5d_20d": _float_or_none(evidence.get("volume_ratio_5d_20d")),
                "low_suction_days": _float_or_none(evidence.get("low_suction_days")),
                "first_effective_lift": bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed")),
                "recent_limit_up_20d": bool(evidence.get("recent_limit_up_20d")),
                "large_bull_count_20d": _float_or_none(evidence.get("large_bull_count_20d")),
                "volume_stall_risk": bool(evidence.get("volume_stall_risk") or evidence.get("high_position_volume_stall_risk")),
            }
        )
    return result


def _candidate_loss_bucket_keys(row: dict[str, Any]) -> list[str]:
    return_pct = _float_or_none(row.get("return_pct")) or 0.0
    if return_pct >= 0:
        return []
    evidence = row.get("entry_reason") if isinstance(row.get("entry_reason"), dict) else {}
    keys = [_candidate_path_bucket(row)]
    if abs(_float_or_none(row.get("max_runup_pct")) or 0.0) < 3.0:
        keys.append("loss_no_mfe")
    if (_float_or_none(row.get("max_drawdown_pct")) or 0.0) <= -8.0:
        keys.append("loss_deep_drawdown")
    if (_float_or_none(row.get("max_runup_pct")) or 0.0) >= 8.0:
        keys.append("loss_mfe_giveback")
    if _candidate_high_level_risk(evidence):
        keys.append("visible_high_level_risk")
    if _candidate_ma5_overextended(evidence):
        keys.append("ma5_overextended")
    if _candidate_volume_stall(evidence):
        keys.append("volume_stall")
    if _candidate_low_suction_without_lift(evidence):
        keys.append("low_suction_without_fresh_lift")
    if _candidate_weak_market(evidence):
        keys.append("weak_market_context")
    if _candidate_low_liquidity(evidence, row):
        keys.append("low_liquidity_loss")
    return _dedupe_list(keys)


def _candidate_winner_bucket_keys(row: dict[str, Any]) -> list[str]:
    return_pct = _float_or_none(row.get("return_pct")) or 0.0
    if return_pct <= 0:
        return []
    evidence = row.get("entry_reason") if isinstance(row.get("entry_reason"), dict) else {}
    keys = [_candidate_path_bucket(row)]
    if (_float_or_none(row.get("max_runup_pct")) or 0.0) >= 15.0:
        keys.append("right_tail_mfe15")
    if _candidate_low_suction_mature_lift(evidence):
        keys.append("mature_low_suction_lift")
    if _candidate_strong_trend_ma_pullback(evidence):
        keys.append("strong_trend_ma_pullback")
    if _candidate_high_level_support_divergence(evidence):
        keys.append("high_level_support_divergence")
    if _candidate_low_liquidity(evidence, row):
        keys.append("low_liquidity_winner")
    if _candidate_recent_limit_activity(evidence):
        keys.append("recent_limit_or_large_bull")
    return _dedupe_list(keys)


def _candidate_path_bucket(row: dict[str, Any]) -> str:
    return_pct = _float_or_none(row.get("return_pct")) or 0.0
    mfe = _float_or_none(row.get("max_runup_pct")) or 0.0
    mae = _float_or_none(row.get("max_drawdown_pct")) or 0.0
    if return_pct >= 8.0 or (return_pct > 0 and mfe >= 15.0):
        return "right_tail_winner"
    if return_pct > 0:
        return "steady_winner"
    if mfe >= 8.0:
        return "mfe_giveback"
    if mae <= -8.0:
        return "deep_drawdown_loss"
    if abs(mfe) < 3.0:
        return "pure_loss"
    if return_pct < 0:
        return "ordinary_loss"
    return "flat"


def _candidate_bucket_examples(rows: list[dict[str, Any]], *, limit: int, reverse: bool) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            _sort_float(row.get("return_pct")),
            _sort_float(row.get("max_runup_pct")),
            -_candidate_effective_rank(row),
            str(row.get("entry_signal_date") or ""),
            str(row.get("vt_symbol") or ""),
        ),
        reverse=reverse,
    )
    return [
        {
            "vt_symbol": row.get("vt_symbol"),
            "name": row.get("name"),
            "entry_signal_date": row.get("entry_signal_date"),
            "entry_execute_date": row.get("entry_execute_date"),
            "rank": row.get("rank"),
            "effective_rank": row.get("effective_rank"),
            "score": row.get("score"),
            "return_pct": row.get("return_pct"),
            "max_drawdown_pct": row.get("max_drawdown_pct"),
            "max_runup_pct": row.get("max_runup_pct"),
            "d1_open_return_pct": row.get("d1_open_return_pct"),
            "d1_high_runup_pct": row.get("d1_high_runup_pct"),
            "d1_low_drawdown_pct": row.get("d1_low_drawdown_pct"),
            "d1_close_return_pct": row.get("d1_close_return_pct"),
            "d1_quality_success": row.get("d1_quality_success"),
            "d1_near_limit_up": row.get("d1_near_limit_up"),
            "d1_limit_up": row.get("d1_limit_up"),
            "d1_big_drop": row.get("d1_big_drop"),
            "d2_close_return_pct": row.get("d2_close_return_pct"),
            "d3_close_return_pct": row.get("d3_close_return_pct"),
            "d2_d3_best_runup_pct": row.get("d2_d3_best_runup_pct"),
            "hold_to_d3_worthwhile": row.get("hold_to_d3_worthwhile"),
            "take_profit_next_day": row.get("take_profit_next_day"),
            "holding_days": row.get("holding_days"),
            "exit_reason": row.get("exit_reason"),
            "setup_family": row.get("setup_family"),
            "setup_family_label": row.get("setup_family_label"),
            "market_phase": row.get("market_phase"),
            "market_phase_label": row.get("market_phase_label"),
            "timing_window": row.get("timing_window"),
            "timing_window_label": row.get("timing_window_label"),
        }
        for row in ordered[: max(int(limit or 20), 1)]
    ]


def _candidate_is_pure_loss(row: dict[str, Any]) -> bool:
    return (_float_or_none(row.get("return_pct")) or 0.0) < 0 and (_float_or_none(row.get("max_runup_pct")) or 0.0) < 3.0


def _candidate_is_mfe_giveback(row: dict[str, Any]) -> bool:
    return (_float_or_none(row.get("return_pct")) or 0.0) < 0 and (_float_or_none(row.get("max_runup_pct")) or 0.0) >= 8.0


def _candidate_is_right_tail(row: dict[str, Any]) -> bool:
    return (_float_or_none(row.get("return_pct")) or 0.0) >= 8.0 or (_float_or_none(row.get("max_runup_pct")) or 0.0) >= 15.0


def _candidate_high_level_risk(evidence: dict[str, Any]) -> bool:
    return bool(
        evidence.get("high_level_sideways_distribution_risk")
        or evidence.get("distribution_risk")
        or evidence.get("deep_trend_ma10_dislocation_observe")
    )


def _candidate_ma5_overextended(evidence: dict[str, Any]) -> bool:
    distance = _float_or_none(evidence.get("ma5_distance_pct"))
    return distance is not None and distance >= 6.0


def _candidate_volume_stall(evidence: dict[str, Any]) -> bool:
    return bool(evidence.get("volume_stall_risk") or evidence.get("high_position_volume_stall_risk"))


def _candidate_low_suction_without_lift(evidence: dict[str, Any]) -> bool:
    low_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    return low_days >= 3 and not bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed"))


def _candidate_weak_market(evidence: dict[str, Any]) -> bool:
    warning = _float_or_none(evidence.get("market_warning_level")) or 0.0
    regime = str(evidence.get("dynamic_market_regime") or "")
    return warning >= 3 or regime in {"risk_off", "weak_breadth", "false_bull"}


def _candidate_low_liquidity(evidence: dict[str, Any], row: dict[str, Any]) -> bool:
    score = _float_or_none(row.get("liquidity_score") or evidence.get("liquidity_score"))
    return score is not None and score < 25.0


def _candidate_low_suction_mature_lift(evidence: dict[str, Any]) -> bool:
    low_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    return low_days >= 3 and bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed"))


def _candidate_strong_trend_ma_pullback(evidence: dict[str, Any]) -> bool:
    profile = str(evidence.get("research_entry_profile") or evidence.get("entry_profile") or "")
    tags = " ".join(str(item) for item in evidence.get("research_entry_tags") or evidence.get("entry_tags") or [])
    return "strong_trend" in profile or "strong_trend" in tags or "ma_pullback" in profile or "ma_pullback" in tags


def _candidate_high_level_support_divergence(evidence: dict[str, Any]) -> bool:
    profile = str(evidence.get("research_entry_profile") or evidence.get("entry_profile") or "")
    tags = " ".join(str(item) for item in evidence.get("research_entry_tags") or evidence.get("entry_tags") or [])
    return "support_divergence" in profile or "support_divergence" in tags or bool(evidence.get("high_level_support_divergence"))


def _candidate_recent_limit_activity(evidence: dict[str, Any]) -> bool:
    return bool(evidence.get("recent_limit_up_20d")) or (_float_or_none(evidence.get("large_bull_count_20d")) or 0.0) >= 1


def _candidate_audit_bucket_label(bucket: str) -> str:
    labels = {
        "right_tail_winner": "右尾大赢家",
        "steady_winner": "普通盈利",
        "mfe_giveback": "冲高回落",
        "ordinary_loss": "普通亏损",
        "pure_loss": "买后纯亏",
        "deep_drawdown_loss": "深回撤亏损",
        "flat": "基本持平",
        "loss_no_mfe": "无明显冲高亏损",
        "loss_deep_drawdown": "亏损且深回撤",
        "loss_mfe_giveback": "亏损但曾大幅冲高",
        "visible_high_level_risk": "信号日高位/分歧风险",
        "ma5_overextended": "MA5 偏离过大",
        "volume_stall": "放量滞涨/量能风险",
        "low_suction_without_fresh_lift": "低吸无 fresh lift",
        "weak_market_context": "弱行情上下文",
        "low_liquidity_loss": "低流动性亏损",
        "right_tail_mfe15": "MFE >= 15%",
        "mature_low_suction_lift": "成熟低吸启动",
        "strong_trend_ma_pullback": "强趋势均线回踩",
        "high_level_support_divergence": "高位支撑分歧",
        "low_liquidity_winner": "低流动性赢家",
        "recent_limit_or_large_bull": "近端涨停/大阳活跃",
    }
    return labels.get(bucket, bucket)


def _candidate_audit_bucket_order(bucket: str) -> int:
    order = {
        "pure_loss": 10,
        "loss_no_mfe": 20,
        "deep_drawdown_loss": 30,
        "loss_deep_drawdown": 40,
        "mfe_giveback": 50,
        "loss_mfe_giveback": 60,
        "ordinary_loss": 70,
        "visible_high_level_risk": 80,
        "ma5_overextended": 90,
        "volume_stall": 100,
        "low_suction_without_fresh_lift": 110,
        "weak_market_context": 120,
        "low_liquidity_loss": 130,
        "right_tail_winner": 10,
        "right_tail_mfe15": 20,
        "steady_winner": 30,
        "mature_low_suction_lift": 40,
        "strong_trend_ma_pullback": 50,
        "high_level_support_divergence": 60,
        "low_liquidity_winner": 70,
        "recent_limit_or_large_bull": 80,
    }
    return order.get(bucket, 1000)


def _candidate_volume_bucket_label(bucket: str) -> str:
    labels = {
        "volume_missing": "量能缺失",
        "extreme_shrink": "极度缩量",
        "shrinking_volume": "缩量承接",
        "balanced_volume": "量能均衡",
        "mild_volume_expansion": "温和放量",
        "heavy_volume_expansion": "明显放量",
        "extreme_volume_expansion": "极端放量",
        "recent_limit_up": "近端涨停活跃",
        "large_bull_ge3": "近20日大阳>=3",
        "large_bull_1_2": "近20日大阳1-2",
        "no_recent_active_bar": "缺少近端活跃痕迹",
        "volume_stall_distribution": "放量滞涨/疑似派发",
        "prepared_shrink_lift": "缩量洗盘后 fresh lift",
        "low_suction_no_fresh_lift": "低吸蓄势但无 fresh lift",
        "prepared_lift_bad_volume": "有 lift 但量能不理想",
        "active_balanced_volume": "活跃痕迹+量能均衡",
        "active_bad_volume": "活跃痕迹+量能异常",
        "no_active_no_lift": "无活跃痕迹且无 lift",
        "winner_or_flat": "盈利/持平",
        "loss_mfe_giveback": "冲高回落亏损",
        "loss_deep_drawdown": "深回撤亏损",
        "loss_no_mfe": "无冲高亏损",
        "ordinary_loss": "普通亏损",
    }
    return labels.get(bucket, bucket)


def _candidate_volume_bucket_order(bucket: str) -> int:
    order = {
        "extreme_shrink": 10,
        "shrinking_volume": 20,
        "balanced_volume": 30,
        "mild_volume_expansion": 40,
        "heavy_volume_expansion": 50,
        "extreme_volume_expansion": 60,
        "volume_missing": 90,
        "recent_limit_up": 100,
        "large_bull_ge3": 110,
        "large_bull_1_2": 120,
        "no_recent_active_bar": 130,
        "prepared_shrink_lift": 200,
        "active_balanced_volume": 210,
        "active_bad_volume": 220,
        "low_suction_no_fresh_lift": 230,
        "prepared_lift_bad_volume": 240,
        "volume_stall_distribution": 250,
        "no_active_no_lift": 260,
        "loss_deep_drawdown": 300,
        "loss_mfe_giveback": 310,
        "loss_no_mfe": 320,
        "ordinary_loss": 330,
        "winner_or_flat": 400,
    }
    return order.get(bucket, 1000)


def _candidate_trade_daily_extreme(rows: list[dict[str, Any]], *, reverse: bool) -> dict[str, Any] | None:
    if not rows:
        return None
    row = sorted(
        rows,
        key=lambda item: (
            _sort_float(item.get("return_pct")),
            -_candidate_effective_rank(item),
            str(item.get("vt_symbol") or ""),
        ),
        reverse=reverse,
    )[0]
    return {
        "vt_symbol": row.get("vt_symbol"),
        "name": row.get("name"),
        "rank": row.get("rank"),
        "effective_rank": row.get("effective_rank"),
        "score": row.get("score"),
        "return_pct": row.get("return_pct"),
        "d1_close_return_pct": row.get("d1_close_return_pct"),
        "d1_quality_success": row.get("d1_quality_success"),
        "d1_near_limit_up": row.get("d1_near_limit_up"),
        "d1_limit_up": row.get("d1_limit_up"),
        "d1_big_drop": row.get("d1_big_drop"),
        "exit_reason": row.get("exit_reason"),
    }


def _candidate_trade_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _float_or_none(row.get("return_pct"))) is not None]
    drawdowns = [value for row in rows if (value := _float_or_none(row.get("max_drawdown_pct"))) is not None]
    runups = [value for row in rows if (value := _float_or_none(row.get("max_runup_pct"))) is not None]
    holding_days = [value for row in rows if (value := _float_or_none(row.get("holding_days"))) is not None]
    d2_returns = [value for row in rows if (value := _float_or_none(row.get("d2_close_return_pct"))) is not None]
    d3_returns = [value for row in rows if (value := _float_or_none(row.get("d3_close_return_pct"))) is not None]
    d2_d3_runups = [value for row in rows if (value := _float_or_none(row.get("d2_d3_best_runup_pct"))) is not None]
    quality_rows = [row for row in rows if isinstance(row.get("d1_quality_success"), bool)]
    hold_rows = [row for row in rows if isinstance(row.get("hold_to_d3_worthwhile"), bool)]
    take_profit_rows = [row for row in rows if isinstance(row.get("take_profit_next_day"), bool)]
    wins = [value for value in returns if value > 0]
    quality_wins = [row for row in quality_rows if bool(row.get("d1_quality_success"))]
    hold_wins = [row for row in hold_rows if bool(row.get("hold_to_d3_worthwhile"))]
    take_profit = [row for row in take_profit_rows if bool(row.get("take_profit_next_day"))]
    limit_up_rows = [row for row in rows if bool(row.get("d1_limit_up"))]
    near_limit_rows = [row for row in rows if bool(row.get("d1_near_limit_up"))]
    big_drop_rows = [row for row in rows if bool(row.get("d1_big_drop"))]
    return {
        "sample_count": len(rows),
        "evaluated_count": len(returns),
        "win_count": len(wins),
        "win_rate": _ratio_pct(len(wins), len(returns)),
        "quality_win_count": len(quality_wins),
        "quality_win_rate": _ratio_pct(len(quality_wins), len(quality_rows)),
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "median_return_pct": round(median(returns), 4) if returns else None,
        "average_max_drawdown_pct": round(sum(drawdowns) / len(drawdowns), 4) if drawdowns else None,
        "average_max_runup_pct": round(sum(runups) / len(runups), 4) if runups else None,
        "average_holding_days": round(sum(holding_days) / len(holding_days), 4) if holding_days else None,
        "d1_limit_up_count": len(limit_up_rows),
        "d1_limit_up_rate": _ratio_pct(len(limit_up_rows), len(returns)),
        "d1_near_limit_up_count": len(near_limit_rows),
        "d1_near_limit_up_rate": _ratio_pct(len(near_limit_rows), len(returns)),
        "d1_big_drop_count": len(big_drop_rows),
        "d1_big_drop_rate": _ratio_pct(len(big_drop_rows), len(returns)),
        "average_d2_close_return_pct": round(sum(d2_returns) / len(d2_returns), 4) if d2_returns else None,
        "average_d3_close_return_pct": round(sum(d3_returns) / len(d3_returns), 4) if d3_returns else None,
        "average_d2_d3_best_runup_pct": round(sum(d2_d3_runups) / len(d2_d3_runups), 4) if d2_d3_runups else None,
        "hold_to_d3_worthwhile_count": len(hold_wins),
        "hold_to_d3_worthwhile_rate": _ratio_pct(len(hold_wins), len(hold_rows)),
        "take_profit_next_day_count": len(take_profit),
        "take_profit_next_day_rate": _ratio_pct(len(take_profit), len(take_profit_rows)),
    }


def _candidate_trade_data_quality_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    discontinuity_rows = [row for row in rows if row.get("has_price_discontinuity")]
    return {
        "sample_count": len(rows),
        "price_discontinuity_count": len(discontinuity_rows),
        "price_discontinuity_rate": _ratio(len(discontinuity_rows), len(rows)),
        "price_discontinuity_quality": _candidate_trade_metric_summary(discontinuity_rows),
        "worst_price_discontinuity_samples": _candidate_trade_worst_price_discontinuity_samples(discontinuity_rows),
    }


def _candidate_trade_worst_price_discontinuity_samples(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            _sort_float(row.get("return_pct")),
            _sort_float(row.get("first_price_discontinuity_open_gap_pct")),
            str(row.get("entry_signal_date") or ""),
            str(row.get("vt_symbol") or ""),
        ),
    )
    return [
        {
            "entry_signal_date": row.get("entry_signal_date"),
            "entry_execute_date": row.get("entry_execute_date"),
            "vt_symbol": row.get("vt_symbol"),
            "name": row.get("name"),
            "rank": row.get("rank"),
            "return_pct": row.get("return_pct"),
            "max_drawdown_pct": row.get("max_drawdown_pct"),
            "max_runup_pct": row.get("max_runup_pct"),
            "exit_reason": row.get("exit_reason"),
            "first_price_discontinuity_date": row.get("first_price_discontinuity_date"),
            "first_price_discontinuity_open_gap_pct": row.get("first_price_discontinuity_open_gap_pct"),
            "first_price_discontinuity_close_gap_pct": row.get("first_price_discontinuity_close_gap_pct"),
        }
        for row in sorted_rows[:limit]
    ]


def _candidate_trade_average_holding_annualized_return_pct(rows: list[dict[str, Any]]) -> float | None:
    returns = [value for row in rows if (value := _float_or_none(row.get("return_pct"))) is not None]
    holding_days = [value for row in rows if (value := _float_or_none(row.get("holding_days"))) is not None and value > 0]
    if not returns or not holding_days:
        return None
    average_return = sum(returns) / len(returns)
    average_holding_days = sum(holding_days) / len(holding_days)
    if average_holding_days <= 0 or 1 + average_return / 100 <= 0:
        return None
    return round(((1 + average_return / 100) ** (252 / average_holding_days) - 1) * 100, 4)


def _candidate_trade_signal_day_compound_annualized_return_pct(rows: list[dict[str, Any]]) -> float | None:
    by_date: dict[str, list[float]] = {}
    for row in rows:
        signal_date = str(row.get("entry_signal_date") or "")
        value = _float_or_none(row.get("return_pct"))
        if not signal_date or value is None:
            continue
        by_date.setdefault(signal_date, []).append(value)
    if not by_date:
        return None
    equity = 1.0
    for signal_date in sorted(by_date):
        values = by_date[signal_date]
        if not values:
            continue
        equity *= 1 + (sum(values) / len(values)) / 100
    days = len(by_date)
    if days <= 0 or equity <= 0:
        return None
    return round((equity ** (252 / days) - 1) * 100, 4)


def _candidate_trade_rank_bucket(rank: int | None) -> str:
    if rank is None or rank <= 0:
        return "outside_top_100"
    if rank <= 10:
        return "top_10"
    if rank <= 20:
        return "top_20"
    if rank <= 50:
        return "top_50"
    if rank <= 100:
        return "top_100"
    return "outside_top_100"


def _candidate_trade_rank_window(rank: int | None) -> str:
    if rank is None or rank <= 0:
        return "outside_top_100"
    if rank <= 10:
        return "rank_1_10"
    if rank <= 20:
        return "rank_11_20"
    if rank <= 50:
        return "rank_21_50"
    if rank <= 100:
        return "rank_51_100"
    return "outside_top_100"


def _candidate_trade_score_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score < 75:
        return "<75"
    if score < 80:
        return "75-80"
    if score < 90:
        return "80-90"
    if score < 95:
        return "90-95"
    return "95+"


def _candidate_setup_family(row: dict[str, Any], evidence: dict[str, Any]) -> str:
    setup = str(
        row.get("setup_family")
        or evidence.get("setup_family")
        or evidence.get("entry_setup")
        or evidence.get("setup_type")
        or row.get("entry_family")
        or row.get("setup_primary")
        or evidence.get("entry_family")
        or ""
    )
    subtype = str(
        evidence.get("oversold_rebound_candidate_subtype")
        or evidence.get("oversold_rebound_subtype")
        or evidence.get("rebound_subtype")
        or ""
    )
    if setup in {"bottom_reclaim", "secondary_breakout_confirm", "oversold_rebound_start", "retreat_momentum_source"}:
        return setup
    if bool(evidence.get("bottom_reclaim")) or subtype == "bottom_reclaim":
        return "bottom_reclaim"
    if bool(evidence.get("secondary_breakout_confirm")) or subtype == "secondary_breakout_confirm":
        return "secondary_breakout_confirm"
    if bool(evidence.get("oversold_rebound_start")) or subtype in {"oversold_rebound_start", "oversold_rebound"}:
        return "oversold_rebound_start"
    if bool(evidence.get("retreat_momentum_source")) or setup == "silver_retreat_momentum_source":
        return "retreat_momentum_source"
    low_days = _float_or_none(row.get("low_suction_days") or evidence.get("low_suction_days")) or 0.0
    launch_confirmed = bool(row.get("launch_confirmed") or evidence.get("low_suction_launch_confirmed") or row.get("first_effective_lift") or evidence.get("first_effective_lift"))
    if setup in {"dragon_low_suction_overlap"}:
        return "dragon_low_suction_overlap"
    if setup == "dragon_pullback" and low_days >= 3:
        return "dragon_low_suction_overlap"
    if setup in {"stealth_low_suction", "low_position_reclaim", "low_suction_first_lift", "low_suction_buildup"} or low_days >= 3:
        return "low_suction_first_lift" if launch_confirmed else "low_suction_buildup"
    if setup == "dragon_pullback":
        return "dragon_pullback"
    return setup or "other"


def _candidate_market_phase(row: dict[str, Any], evidence: dict[str, Any]) -> str:
    phase = str(row.get("market_phase") or evidence.get("market_phase") or "").strip()
    if phase:
        return phase
    regime = str(row.get("dynamic_market_regime") or evidence.get("dynamic_market_regime") or "").strip()
    warning = _float_or_none(row.get("market_warning_level") or evidence.get("market_warning_level"))
    recovery = str(row.get("recovery_state") or evidence.get("recovery_state") or "").strip()
    if regime in {"strong_broad", "narrow_mainline_bull", "mainline_active", "mainline_pullback"}:
        return "uptrend"
    if warning is not None and warning >= 3:
        return "retreat"
    if regime in {"risk_off", "weak_breadth", "false_bull"}:
        return "retreat"
    if recovery in {"warming", "recovering"} or regime in {"warming", "recovery"}:
        return "warming"
    if regime:
        return "rotation"
    return "unknown"


def _candidate_timing_window(row: dict[str, Any], evidence: dict[str, Any]) -> str:
    value = str(row.get("timing_window") or evidence.get("timing_window") or "").strip()
    if value:
        return value
    direction = str(row.get("nearest_timing_direction") or evidence.get("nearest_timing_direction") or "").upper()
    days = _float_or_none(row.get("nearest_timing_days") or evidence.get("nearest_timing_days"))
    if direction == "GOLD":
        if days is not None and days <= 5:
            return "after_gold_0_5"
        if days is not None and days <= 20:
            return "after_gold_6_20"
        return "after_gold_late"
    if direction == "SILVER":
        if days is not None and days <= 5:
            return "after_silver_0_5"
        if days is not None and days <= 20:
            return "after_silver_6_20"
        return "after_silver_late"
    return "no_recent_timing"


def _candidate_setup_family_label(value: str) -> str:
    labels = {
        "low_suction_first_lift": "低吸首启",
        "dragon_pullback": "龙回头",
        "low_suction_buildup": "低吸蓄势",
        "dragon_low_suction_overlap": "重叠信号",
        "bottom_reclaim": "超跌反弹-底部收复",
        "secondary_breakout_confirm": "超跌反弹-二次确认",
        "oversold_rebound_start": "超跌反弹-启动",
        "retreat_momentum_source": "退潮高低切",
        "other": "其他",
        "unknown": "其他",
    }
    return labels.get(str(value or "unknown"), str(value or "其他"))


def _candidate_market_phase_label(value: str) -> str:
    labels = {
        "uptrend": "主升",
        "rotation": "震荡",
        "retreat": "退潮",
        "warming": "回暖",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _candidate_trade_bucket_label(key: str, bucket: str) -> str:
    if key == "rank_bucket":
        return _candidate_trade_rank_bucket_label(bucket)
    if key == "daily_rank_window":
        return _candidate_trade_rank_window_label(bucket)
    if key == "setup_family":
        return _candidate_setup_family_label(bucket)
    if key == "market_phase":
        return _candidate_market_phase_label(bucket)
    if key == "timing_window":
        return _candidate_timing_window_label(bucket)
    if key == "timing_phase":
        return _candidate_timing_phase_label(bucket)
    if key == "setup_timing_bucket":
        return _candidate_setup_timing_label(bucket)
    if key == "month":
        return bucket
    if key == "month_timing_window":
        return _candidate_month_timing_window_label(bucket)
    if key == "month_timing_phase":
        return _candidate_month_timing_phase_label(bucket)
    if key == "setup_month_timing_bucket":
        return _candidate_setup_month_timing_label(bucket)
    if key == "setup_month_timing_phase_bucket":
        return _candidate_setup_month_timing_phase_label(bucket)
    if key == "evaluation_window":
        return _candidate_evaluation_window_label(bucket)
    if key == "d1_outcome":
        return _candidate_d1_outcome_label(bucket)
    if key == "exit_reason":
        return bucket
    return bucket


def _candidate_trade_rank_bucket_label(bucket: str) -> str:
    labels = {
        "top_10": "排名1-10",
        "top_20": "排名11-20",
        "top_50": "排名21-50",
        "top_100": "排名51-100",
        "outside_top_100": "100名外",
    }
    return labels.get(bucket, bucket)


def _candidate_timing_window_label(value: str) -> str:
    labels = {
        "after_gold_0_5": "金手指后0-5日",
        "after_gold_6_20": "金手指后6-20日",
        "after_gold_late": "金手指后20日+",
        "after_silver_0_5": "银手指后0-5日",
        "after_silver_6_20": "银手指后6-20日",
        "after_silver_late": "银手指后20日+",
        "no_recent_timing": "无近期金银手指",
        "unknown": "未知",
    }
    return labels.get(str(value or "unknown"), str(value or "未知"))


def _candidate_timing_phase_label(value: str) -> str:
    timing, _, phase = str(value or "").partition("::")
    timing_label = _candidate_timing_window_label(timing)
    phase_label = _candidate_market_phase_label(phase or "unknown")
    return f"{timing_label} / {phase_label}"


def _candidate_setup_timing_label(value: str) -> str:
    setup, _, timing = str(value or "").partition("::")
    setup_label = _candidate_setup_family_label(setup or "unknown")
    timing_label = _candidate_timing_window_label(timing or "unknown")
    return f"{setup_label} / {timing_label}"


def _candidate_month_timing_window_label(value: str) -> str:
    parts = str(value or "").split("::")
    month = _part(parts, 0) or "未知月份"
    timing = _part(parts, 1) or "unknown"
    return f"{month} / {_candidate_timing_window_label(timing)}"


def _candidate_month_timing_phase_label(value: str) -> str:
    parts = str(value or "").split("::")
    month = _part(parts, 0) or "未知月份"
    timing = _part(parts, 1) or "unknown"
    phase = _part(parts, 2) or "unknown"
    return f"{month} / {_candidate_timing_window_label(timing)} / {_candidate_market_phase_label(phase)}"


def _candidate_setup_month_timing_label(value: str) -> str:
    parts = str(value or "").split("::")
    setup = _part(parts, 0) or "unknown"
    month = _part(parts, 1) or "未知月份"
    timing = _part(parts, 2) or "unknown"
    return f"{month} / {_candidate_setup_family_label(setup)} / {_candidate_timing_window_label(timing)}"


def _candidate_setup_month_timing_phase_label(value: str) -> str:
    parts = str(value or "").split("::")
    setup = _part(parts, 0) or "unknown"
    month = _part(parts, 1) or "未知月份"
    timing = _part(parts, 2) or "unknown"
    phase = _part(parts, 3) or "unknown"
    return f"{month} / {_candidate_setup_family_label(setup)} / {_candidate_timing_window_label(timing)} / {_candidate_market_phase_label(phase)}"


def _candidate_evaluation_window_label(value: str) -> str:
    labels = {
        "full_sample": "全样本",
        "recent_3_months": "最近3个月",
        "recent_6_months": "最近6个月",
        "silver_pressure_2026_03_13_03_24": "银手指压力 2026-03-13..03-24",
        "june_repair_2026_06_09_07_03": "6月底部修复 2026-06-09..07-03",
    }
    return labels.get(str(value or ""), str(value or "未知区间"))


def _candidate_d1_outcome_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    return_pct = _float_or_none(row.get("return_pct")) or 0.0
    if bool(row.get("d1_limit_up")):
        keys.append("d1_limit_up")
    if bool(row.get("d1_near_limit_up")):
        keys.append("d1_near_limit_up")
    if return_pct >= 5.0:
        keys.append("d1_close_ge5")
    if bool(row.get("d1_big_drop")):
        keys.append("d1_big_drop")
    if bool(row.get("d1_low_open")) or bool(row.get("d1_low_close")):
        keys.append("d1_low_open_or_low_close")
    if (_float_or_none(row.get("d1_low_drawdown_pct")) or 0.0) <= -5.0:
        keys.append("d1_deep_intraday_drawdown")
    if not keys:
        keys.append("d1_ordinary")
    return _dedupe_list(keys)


def _candidate_d1_outcome_label(value: str) -> str:
    labels = {
        "d1_limit_up": "D+1涨停/封板代理",
        "d1_near_limit_up": "D+1接近涨停",
        "d1_close_ge5": "D+1收盘涨幅>=5%",
        "d1_big_drop": "D+1大跌",
        "d1_low_open_or_low_close": "D+1低开/低收",
        "d1_deep_intraday_drawdown": "D+1盘中深回撤",
        "d1_ordinary": "D+1普通波动",
    }
    return labels.get(str(value or ""), str(value or "未归类"))


def _candidate_d1_outcome_order(value: str) -> int:
    order = {
        "d1_limit_up": 10,
        "d1_near_limit_up": 20,
        "d1_close_ge5": 30,
        "d1_big_drop": 40,
        "d1_low_open_or_low_close": 50,
        "d1_deep_intraday_drawdown": 60,
        "d1_ordinary": 100,
    }
    return order.get(str(value or ""), 1000)


def _candidate_trade_rank_window_label(bucket: str) -> str:
    labels = {
        "rank_1_10": "排名1-10",
        "rank_11_20": "排名11-20",
        "rank_21_50": "排名21-50",
        "rank_51_100": "排名51-100",
        "outside_top_100": "100名外",
    }
    return labels.get(bucket, bucket)


def _window_mfe(window: list[Bar], base: float) -> float | None:
    if not window:
        return None
    return _pct_return(max(float(bar.high_price) for bar in window), base)


def _window_mae(window: list[Bar], base: float) -> float | None:
    if not window:
        return None
    return _pct_return(min(float(bar.low_price) for bar in window), base)


_candidate_trade_rank_bucket_order = {
    "top_10": 10,
    "top_20": 20,
    "top_50": 50,
    "top_100": 100,
    "outside_top_100": 1000,
}


_candidate_trade_rank_window_order = {
    "rank_1_10": 10,
    "rank_11_20": 20,
    "rank_21_50": 50,
    "rank_51_100": 100,
    "outside_top_100": 1000,
}


_candidate_trade_score_bucket_order = {
    "<75": 0,
    "75-80": 10,
    "80-90": 20,
    "90-95": 30,
    "95+": 40,
    "unknown": 1000,
}


_candidate_timing_window_order = {
    "after_gold_0_5": 10,
    "after_gold_6_20": 20,
    "after_gold_late": 30,
    "after_silver_0_5": 40,
    "after_silver_6_20": 50,
    "after_silver_late": 60,
    "no_recent_timing": 900,
    "unknown": 1000,
}


_candidate_market_phase_order = {
    "uptrend": 10,
    "rotation": 20,
    "retreat": 30,
    "warming": 40,
    "unknown": 1000,
}


_candidate_setup_family_order = {
    "dragon_pullback": 10,
    "low_suction_first_lift": 20,
    "low_suction_buildup": 30,
    "oversold_rebound_start": 40,
    "bottom_reclaim": 50,
    "secondary_breakout_confirm": 60,
    "retreat_momentum_source": 70,
    "dragon_low_suction_overlap": 80,
    "other": 900,
    "unknown": 1000,
}


def _timeline_buildup_cluster_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    last = rows[-1]
    cluster_dates = [str(row.get("date") or "") for row in rows if row.get("date")]
    return {
        "date": last.get("date"),
        "vt_symbol": last.get("vt_symbol"),
        "markers": ["buildup_cluster"],
        "display_markers": ["BUY_REJECTED"],
        "cluster": {
            "type": "buildup_cluster",
            "cluster_start_date": first.get("date"),
            "cluster_end_date": last.get("date"),
            "cluster_size": len(rows),
            "cluster_dates": cluster_dates,
            "rows": rows,
        },
        "candidate": {
            "date": last.get("date"),
            "action": "WATCH",
            "entry_family_label": "低吸蓄势观察",
            "low_suction_days": _float_or_none(((last.get("candidate") or {}) if isinstance(last.get("candidate"), dict) else {}).get("low_suction_days")),
            "reason": {"cluster_type": "buildup_cluster", "cluster_size": len(rows)},
        },
    }


def _is_buildup_only_timeline_row(row: dict[str, Any]) -> bool:
    if row.get("execution") or row.get("sell") or row.get("plan"):
        return False
    candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else None
    if not candidate:
        return False
    action = str(candidate.get("action") or "").upper()
    if action == "BUY" and _is_key_timeline_candidate(candidate):
        return False
    reason = candidate.get("reason") if isinstance(candidate.get("reason"), dict) else {}
    setup = str(reason.get("entry_setup") or reason.get("setup_type") or reason.get("entry_family") or "")
    low_days = _float_or_none(reason.get("low_suction_days") or candidate.get("low_suction_days")) or 0.0
    launch_confirmed = bool(reason.get("low_suction_launch_confirmed") or candidate.get("low_suction_launch_confirmed"))
    return low_days >= 3 and not launch_confirmed and setup in {"stealth_low_suction", "low_position_reclaim", "dragon_pullback"}


def _is_key_timeline_candidate(candidate: dict[str, Any]) -> bool:
    if bool(candidate.get("first_effective_lift")):
        return True
    reason = candidate.get("reason") if isinstance(candidate.get("reason"), dict) else {}
    if bool(reason.get("low_suction_launch_confirmed")):
        return True
    low_days = _float_or_none(reason.get("low_suction_days") or candidate.get("low_suction_days")) or 0.0
    if low_days < 3:
        return True
    bucket = str(reason.get("low_suction_launch_quality_bucket") or candidate.get("low_suction_launch_quality_bucket") or "")
    return bucket in {"balanced_first_lift", "other_confirmed_launch", "not_low_suction"}


def _dedupe_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _group_metrics(rows: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(key_fn(row)), []).append(row)
    return [_bucket_metrics(bucket, groups[bucket]) for bucket in sorted(groups)]


def _bucket_metrics(bucket: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [_outcome_return(row) for row in rows]
    returns = [value for value in returns if value is not None]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    positive_sum = sum(wins)
    negative_sum = abs(sum(losses))
    return {
        "bucket": bucket,
        "sample_count": len(rows),
        "win_rate": _ratio_pct(len(wins), len(returns)),
        "average_return": round(sum(returns) / len(returns), 4) if returns else None,
        "median_return": round(median(returns), 4) if returns else None,
        "profit_factor": round(positive_sum / negative_sum, 4) if negative_sum else (None if not positive_sum else 999.0),
        "mfe_8_pct_hit_ratio": _ratio_pct(
            sum(1 for row in rows if (_outcome_float(row, "mfe_20d") or _outcome_float(row, "mfe_10d") or _outcome_float(row, "mfe_5d") or 0.0) >= 8.0),
            len(rows),
        ),
        "mae_5_pct_loss_ratio": _ratio_pct(
            sum(1 for row in rows if (_outcome_float(row, "mae_20d") or _outcome_float(row, "mae_10d") or _outcome_float(row, "mae_5d") or 0.0) <= -5.0),
            len(rows),
        ),
        "failed_launch_ratio": _ratio_pct(sum(1 for row in rows if bool((row.get("outcome") or {}).get("failed_launch"))), len(rows)),
        "support_stop_like_ratio": _ratio_pct(sum(1 for row in rows if bool((row.get("outcome") or {}).get("support_stop_like"))), len(rows)),
    }


def _exclude_strong_market_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not _is_strong_market_row(row)]


def _is_strong_market_row(row: dict[str, Any]) -> bool:
    regime = str(row.get("dynamic_market_regime") or "").lower()
    warning = str(row.get("market_warning_level") or "").lower()
    theme_state = str(row.get("theme_state") or row.get("dominant_theme_state") or "").lower()
    theme_strength = _float_or_none(row.get("theme_strength")) or 0.0
    return (
        regime in {"strong_broad", "narrow_theme", "strong_theme", "theme_bull"}
        or warning in {"strong", "hot", "overheated"}
        or theme_state in {"strong", "hot", "mainline_active"}
        or theme_strength >= 80.0
    )


def _candidate_signal_keys(signal_events: list[dict[str, Any]]) -> set[tuple[str, date]]:
    result: set[tuple[str, date]] = set()
    for row in signal_events:
        if str(row.get("side") or "").upper() != "BUY":
            continue
        symbol = str(row.get("vt_symbol") or "").upper()
        signal_date = _date_or_none(row.get("signal_date") or row.get("trade_date"))
        if symbol and signal_date:
            result.add((symbol, signal_date))
    return result


def _candidate_order_keys(orders: list[dict[str, Any]]) -> dict[tuple[str, date], dict[str, Any]]:
    result: dict[tuple[str, date], dict[str, Any]] = {}
    for row in orders:
        if str(row.get("side") or "").upper() != "BUY":
            continue
        symbol = str(row.get("vt_symbol") or "").upper()
        signal_date = _order_signal_date(row)
        if symbol and signal_date:
            result.setdefault((symbol, signal_date), row)
    return result


def _candidate_trade_keys(trades: list[dict[str, Any]]) -> dict[tuple[str, date], dict[str, Any]]:
    result: dict[tuple[str, date], dict[str, Any]] = {}
    for row in trades:
        if str(row.get("side") or "").upper() != "BUY":
            continue
        symbol = str(row.get("vt_symbol") or "").upper()
        signal_date = _buy_trade_signal_date(row)
        if symbol and signal_date:
            result.setdefault((symbol, signal_date), row)
    return result


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, date | None]:
    return (
        str(candidate.get("vt_symbol") or "").upper(),
        _date_or_none(candidate.get("trade_date") or candidate.get("signal_date")),
    )


def _candidate_execution_attribution_row(
    candidate: dict[str, Any],
    *,
    key: tuple[str, date | None],
    planned: bool,
    order: dict[str, Any] | None,
    trade: dict[str, Any] | None,
    signal_events: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    cache_coverage: dict[str, Any] | None,
    max_execution_rank: int,
) -> dict[str, Any]:
    outcome = candidate.get("outcome") if isinstance(candidate.get("outcome"), dict) else {}
    filled = trade is not None
    ordered = order is not None
    not_filled_reason = None if filled else _candidate_not_filled_reason(candidate, planned=planned, order=order, max_execution_rank=max_execution_rank)
    plan_gap = (
        classify_candidate_plan_gap(
            candidate,
            signal_events=signal_events,
            orders=orders,
            cache_coverage=cache_coverage,
        )
        if not filled and not planned
        else _candidate_plan_gap_payload("planned_not_ordered", "候选进入理论计划但没有组合订单")
        if not filled and planned and order is None
        else _candidate_plan_gap_payload("ordered_not_filled", "候选已下单但没有成交")
        if not filled and order is not None
        else None
    )
    fixed_return = _first_available_float(outcome, "return_20d", "return_10d", "return_5d", "return_3d")
    fixed_mfe = _first_available_float(outcome, "mfe_20d", "mfe_10d", "mfe_5d", "mfe_3d")
    fixed_mae = _first_available_float(outcome, "mae_20d", "mae_10d", "mae_5d", "mae_3d")
    return {
        "signal_date": _date_to_iso(key[1]),
        "execute_date": _date_to_iso(outcome.get("execute_date") or (order or trade or {}).get("trade_date")),
        "vt_symbol": key[0],
        "name": candidate.get("name"),
        "rank": _int_or_none(candidate.get("rank")),
        "score": _float_or_none(candidate.get("total_score")),
        "entry_family": candidate.get("entry_family"),
        "entry_family_label": candidate.get("entry_family_label"),
        "planned": planned,
        "ordered": ordered,
        "filled": filled,
        "execution_status": "filled" if filled else "ordered_not_filled" if ordered else "planned_not_ordered" if planned else "candidate_not_planned",
        "not_filled_reason": not_filled_reason,
        "not_filled_subreason": (plan_gap or {}).get("subreason"),
        "not_filled_label": (plan_gap or {}).get("label"),
        "order_status": (order or {}).get("status"),
        "order_reason": (order or {}).get("reason"),
        "trade_price": _float_or_none((trade or {}).get("price")),
        "fixed_return_20d": fixed_return,
        "missed_return_20d": None if filled else fixed_return,
        "missed_mfe_20d": None if filled else fixed_mfe,
        "missed_mae_20d": None if filled else fixed_mae,
        "uses_future_for_label_only": bool(outcome.get("uses_future_for_label_only", True)),
        "not_used_for_signal_score": True,
    }


def _candidate_not_filled_reason(
    candidate: dict[str, Any],
    *,
    planned: bool,
    order: dict[str, Any] | None,
    max_execution_rank: int,
) -> str:
    if order is not None:
        status = str(order.get("status") or "").lower()
        reason = str(order.get("reason") or "").strip()
        if status == "rejected" and reason:
            return reason
        return "ordered_not_filled"
    rank = _int_or_none(candidate.get("rank"))
    if rank is not None and rank > max_execution_rank:
        return "outside_execution_top20"
    if planned:
        return "planned_not_ordered"
    return "candidate_not_planned"


def _candidate_plan_gap_payload(subreason: str, label: str) -> dict[str, object]:
    return {
        "reason": "candidate_not_planned",
        "subreason": subreason,
        "label": label,
        "not_used_for_signal_score": True,
    }


def _top_missed_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missed = [row for row in rows if not row.get("filled")]
    returns = [_float_or_none(row.get("missed_return_20d")) for row in missed]
    returns = [value for value in returns if value is not None]
    mfes = [_float_or_none(row.get("missed_mfe_20d")) for row in missed]
    mfes = [value for value in mfes if value is not None]
    maes = [_float_or_none(row.get("missed_mae_20d")) for row in missed]
    maes = [value for value in maes if value is not None]
    return {
        "missed_count": len(missed),
        "missed_positive_20d_count": sum(1 for value in returns if value > 0),
        "missed_avg_return_20d": round(sum(returns) / len(returns), 4) if returns else None,
        "missed_avg_mfe_20d": round(sum(mfes) / len(mfes), 4) if mfes else None,
        "missed_avg_mae_20d": round(sum(maes) / len(maes), 4) if maes else None,
        "by_reason": _candidate_not_filled_reason_buckets(missed),
    }


def _candidate_execution_status_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _candidate_group_buckets(rows, "execution_status")


def _candidate_not_filled_reason_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _candidate_group_buckets(rows, "not_filled_reason")


def _candidate_not_filled_subreason_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _candidate_group_buckets(rows, "not_filled_subreason")


def _candidate_group_buckets(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key) or "none"), []).append(row)
    result = []
    for bucket, bucket_rows in groups.items():
        returns = [_float_or_none(row.get("missed_return_20d") if not row.get("filled") else row.get("fixed_return_20d")) for row in bucket_rows]
        returns = [value for value in returns if value is not None]
        result.append(
            {
                key: bucket,
                "sample_count": len(bucket_rows),
                "filled_count": sum(1 for row in bucket_rows if row.get("filled")),
                "missed_count": sum(1 for row in bucket_rows if not row.get("filled")),
                "positive_20d_count": sum(1 for value in returns if value > 0),
                "win_rate": _ratio_pct(sum(1 for value in returns if value > 0), len(returns)),
                "average_return_20d": round(sum(returns) / len(returns), 4) if returns else None,
            }
        )
    result.sort(key=lambda item: (-int(item.get("sample_count") or 0), str(item.get(key) or "")))
    return result


def _outcome_return(row: dict[str, Any]) -> float | None:
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    for key in ("return_20d", "return_10d", "return_5d", "return_3d"):
        value = _float_or_none(outcome.get(key))
        if value is not None:
            return value
    return None


def _outcome_float(row: dict[str, Any], key: str) -> float | None:
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
    return _float_or_none(outcome.get(key))


def _ratio_pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 4)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _setup_score(evidence: dict[str, Any], *keys: str) -> float | None:
    scores = evidence.get("setup_scores")
    if not isinstance(scores, dict):
        return None
    for key in keys:
        value = _float_or_none(scores.get(key))
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sort_float(value: Any, *, default: float = -10**18) -> float:
    numeric = _float_or_none(value)
    return numeric if numeric is not None else default


def _date_to_iso(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if value in (None, ""):
        return None
    return str(value)


def _pct_return(price: float, base: float) -> float | None:
    if not base:
        return None
    return round((price / base - 1.0) * 100.0, 4)


def _first_threshold_index(
    window: list[Bar],
    execute_price: float,
    *,
    threshold_pct: float,
    high_side: bool,
    current: int | None,
) -> int | None:
    if current is not None:
        return current
    for index, bar in enumerate(window):
        price = float(bar.high_price if high_side else bar.low_price)
        value = _pct_return(price, execute_price)
        if value is None:
            continue
        if high_side and value >= threshold_pct:
            return index
        if not high_side and value <= threshold_pct:
            return index
    return None


def _first_hit(first_profit_index: int | None, first_loss_index: int | None) -> str:
    if first_profit_index is None and first_loss_index is None:
        return "none"
    if first_profit_index is None:
        return "loss"
    if first_loss_index is None:
        return "profit"
    return "profit" if first_profit_index < first_loss_index else "loss"


def _signal_dates_for_buy_trade(buy: dict[str, Any], candidate_signal_dates: list[date]) -> list[date]:
    explicit = _buy_trade_signal_date(buy)
    if explicit is not None:
        return [explicit]
    fallback = _nearest_prior_candidate_date(_date_or_none(buy.get("trade_date")), candidate_signal_dates)
    return [fallback] if fallback is not None else []


def _buy_trade_signal_date(buy: dict[str, Any]) -> date | None:
    raw = buy.get("raw") if isinstance(buy.get("raw"), dict) else {}
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    for value in (execution.get("signal_date"), raw.get("signal_date")):
        parsed = _date_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _order_signal_date(order: dict[str, Any]) -> date | None:
    raw = order.get("raw") if isinstance(order.get("raw"), dict) else {}
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    for value in (execution.get("signal_date"), raw.get("signal_date")):
        parsed = _date_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _nearest_prior_candidate_date(trade_date: date | None, candidate_signal_dates: list[date]) -> date | None:
    if trade_date is None or not candidate_signal_dates:
        return None
    prior_dates = [item for item in candidate_signal_dates if item < trade_date]
    if not prior_dates:
        return None
    return max(prior_dates)


def _current_strategy_trade_payload(buy: dict[str, Any], sell: dict[str, Any] | None) -> dict[str, Any]:
    buy_price = _float_or_none(buy.get("price"))
    sell_price = _float_or_none((sell or {}).get("price"))
    return {
        "current_strategy_entry_date": _date_or_none(buy.get("trade_date")),
        "current_strategy_exit_date": _date_or_none((sell or {}).get("trade_date")),
        "current_strategy_return_pct": _pct_return(sell_price, buy_price) if buy_price is not None and sell_price is not None else None,
        "current_strategy_exit_reason": (sell or {}).get("reason"),
    }


def _first_available_float(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _float_or_none(payload.get(key))
        if value is not None:
            return value
    return None


def _date_or_none(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
