"""Read-only factor audit helpers for persisted quant candidates."""

from __future__ import annotations

from datetime import date
from statistics import median
from typing import Any

from alphaagent.market.boards import stock_board_payload
from alphaagent.server.services.quant.factors import Bar
from alphaagent.server.services.quant.screening_payloads import normalize_quant_evidence


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
        "method": "只读审计：用候选信号日可见特征分组，并用固定持有后验衡量胜率/MFE/MAE；机会成本字段不参与评分、买卖或仓位。",
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
        "replacement_quality_delta": 0.0,
        "note": "这里是候选后验机会成本基线；具体实验的 removed/added/replacement delta 必须在实验对比报告中按真实组合路径计算。",
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
    portfolio_full_threshold: int = 10,
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
        "missed_candidate_opportunity_cost": missed_candidate_opportunity_cost_rows(rows),
        "portfolio_opportunity_summary": candidate_portfolio_opportunity_summary(
            rows,
            portfolio_full_threshold=portfolio_full_threshold,
        ),
        "by_status": _candidate_execution_status_buckets(rows),
        "by_not_filled_reason": _candidate_not_filled_reason_buckets(rows),
        "by_not_filled_subreason": _candidate_not_filled_subreason_buckets(rows),
        "items": rows[:100],
    }


def candidate_portfolio_opportunity_summary(
    rows: list[dict[str, Any]],
    *,
    portfolio_full_threshold: int = 10,
) -> dict[str, Any]:
    """Summarize missed candidates against the real portfolio snapshot."""

    full_threshold = max(int(portfolio_full_threshold or 10), 1)
    missed_new_symbol_rows = [
        row
        for row in rows
        if not row.get("filled") and not _candidate_same_symbol_held(row)
    ]
    full_portfolio_missed_rows = [
        row
        for row in missed_new_symbol_rows
        if _candidate_held_count(row) >= full_threshold
    ]
    return {
        "method": "只读归因：把候选 top-N 与信号日真实持仓快照对照，区分已持有同股的重复信号和满仓错过的新标的；后验收益只用于审计。",
        "portfolio_full_threshold": full_threshold,
        "new_symbol_missed": _candidate_portfolio_bucket_metrics(
            "new_symbol_missed",
            missed_new_symbol_rows,
            "opportunity_type",
            portfolio_full_threshold=full_threshold,
        ),
        "full_portfolio_missed": _candidate_portfolio_bucket_metrics(
            "new_symbol_missed_full_portfolio",
            full_portfolio_missed_rows,
            "opportunity_type",
            portfolio_full_threshold=full_threshold,
        ),
        "by_opportunity_type": _candidate_portfolio_group_buckets(
            rows,
            "opportunity_type",
            lambda row: _candidate_opportunity_type(row, portfolio_full_threshold=full_threshold),
            portfolio_full_threshold=full_threshold,
        ),
        "by_delta_vs_weakest_held": _candidate_portfolio_group_buckets(
            [row for row in missed_new_symbol_rows if _delta_vs_weakest_held(row) is not None],
            "delta_bucket",
            lambda row: _delta_bucket(_delta_vs_weakest_held(row)),
            portfolio_full_threshold=full_threshold,
        ),
        "top_replacement_opportunities": _top_replacement_opportunities(
            missed_new_symbol_rows,
            limit=20,
        ),
        "not_used_for_signal_score": True,
    }


def missed_candidate_opportunity_cost_rows(rows: list[dict[str, Any]], *, limit: int = 50) -> list[dict[str, Any]]:
    """Return audit-only opportunity cost rows for missed candidates."""

    result: list[dict[str, Any]] = []
    for row in rows:
        if row.get("filled"):
            continue
        held_rows = row.get("held_positions") if isinstance(row.get("held_positions"), list) else []
        missed_score = _float_or_none(row.get("score"))
        if missed_score is None:
            continue
        for held in held_rows:
            if not isinstance(held, dict):
                continue
            if _same_symbol(row.get("vt_symbol"), held.get("vt_symbol")):
                continue
            held_score = _position_entry_score(held)
            held_return = _float_or_none(held.get("floating_pnl_pct"))
            score_gap = missed_score - held_score if held_score is not None else None
            result.append(
                {
                    "signal_date": row.get("signal_date"),
                    "execute_date": row.get("execute_date"),
                    "missed_symbol": row.get("vt_symbol"),
                    "missed_rank": row.get("rank"),
                    "missed_score": missed_score,
                    "missed_return_20d": row.get("missed_return_20d"),
                    "missed_mfe_20d": row.get("missed_mfe_20d"),
                    "missed_mae_20d": row.get("missed_mae_20d"),
                    "held_symbol": held.get("vt_symbol"),
                    "held_entry_score": held_score,
                    "held_unrealized_return_pct": held_return,
                    "held_days": _int_or_none(held.get("holding_days")),
                    "held_support_state": _position_support_state(held),
                    "rotation_score_gap": round(score_gap, 4) if score_gap is not None else None,
                    "replacement_quality_delta": _quality_delta(row.get("missed_return_20d"), held_return),
                    "not_used_for_signal_score": True,
                }
            )
    result.sort(
        key=lambda item: (
            -(item.get("replacement_quality_delta") if item.get("replacement_quality_delta") is not None else -999.0),
            -(item.get("rotation_score_gap") if item.get("rotation_score_gap") is not None else -999.0),
            str(item.get("signal_date") or ""),
            str(item.get("missed_symbol") or ""),
        )
    )
    return result[: max(int(limit or 50), 1)]


def _candidate_portfolio_group_buckets(
    rows: list[dict[str, Any]],
    bucket_key: str,
    bucket_fn,
    *,
    portfolio_full_threshold: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(bucket_fn(row) or "unknown"), []).append(row)
    result = [
        _candidate_portfolio_bucket_metrics(
            bucket,
            bucket_rows,
            bucket_key,
            portfolio_full_threshold=portfolio_full_threshold,
        )
        for bucket, bucket_rows in groups.items()
    ]
    result.sort(
        key=lambda item: (
            -int(item.get("sample_count") or 0),
            -_sort_float(item.get("average_return_20d")),
            str(item.get(bucket_key) or ""),
        )
    )
    return result


def _candidate_portfolio_bucket_metrics(
    bucket: str,
    rows: list[dict[str, Any]],
    bucket_key: str,
    *,
    portfolio_full_threshold: int,
) -> dict[str, Any]:
    returns = [_candidate_audit_return(row) for row in rows]
    returns = [value for value in returns if value is not None]
    deltas = [_delta_vs_weakest_held(row) for row in rows]
    deltas = [value for value in deltas if value is not None]
    return {
        bucket_key: bucket,
        "sample_count": len(rows),
        "filled_count": sum(1 for row in rows if row.get("filled")),
        "missed_count": sum(1 for row in rows if not row.get("filled")),
        "same_symbol_holding_count": sum(1 for row in rows if _candidate_same_symbol_held(row)),
        "full_portfolio_count": sum(1 for row in rows if _candidate_held_count(row) >= portfolio_full_threshold),
        "positive_20d_count": sum(1 for value in returns if value > 0),
        "win_rate": _ratio_pct(sum(1 for value in returns if value > 0), len(returns)),
        "average_return_20d": round(sum(returns) / len(returns), 4) if returns else None,
        "median_return_20d": round(median(returns), 4) if returns else None,
        "average_delta_vs_weakest_held": round(sum(deltas) / len(deltas), 4) if deltas else None,
        "not_used_for_signal_score": True,
    }


def _top_replacement_opportunities(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        delta = _delta_vs_weakest_held(row)
        weakest = _weakest_non_same_holding(row)
        if delta is None or weakest is None:
            continue
        candidates.append(
            {
                "signal_date": row.get("signal_date"),
                "execute_date": row.get("execute_date"),
                "missed_symbol": row.get("vt_symbol"),
                "missed_name": row.get("name"),
                "missed_rank": row.get("rank"),
                "missed_score": row.get("score"),
                "missed_return_20d": row.get("missed_return_20d"),
                "missed_mfe_20d": row.get("missed_mfe_20d"),
                "missed_mae_20d": row.get("missed_mae_20d"),
                "held_symbol": weakest.get("vt_symbol"),
                "held_unrealized_return_pct": _float_or_none(weakest.get("floating_pnl_pct")),
                "held_days": _int_or_none(weakest.get("holding_days")),
                "replacement_quality_delta": delta,
                "not_filled_subreason": row.get("not_filled_subreason"),
                "not_used_for_signal_score": True,
            }
        )
    candidates.sort(
        key=lambda item: (
            -_sort_float(item.get("replacement_quality_delta")),
            -_sort_float(item.get("missed_return_20d")),
            str(item.get("signal_date") or ""),
            str(item.get("missed_symbol") or ""),
        )
    )
    return candidates[: max(int(limit or 20), 1)]


def _candidate_audit_return(row: dict[str, Any]) -> float | None:
    return _float_or_none(row.get("fixed_return_20d") if row.get("filled") else row.get("missed_return_20d"))


def _candidate_opportunity_type(row: dict[str, Any], *, portfolio_full_threshold: int) -> str:
    if row.get("filled"):
        return "filled"
    if _candidate_same_symbol_held(row):
        return "repeat_same_symbol_holding"
    if _candidate_held_count(row) >= portfolio_full_threshold:
        return "new_symbol_missed_full_portfolio"
    if _candidate_held_count(row) > 0:
        return "new_symbol_missed_with_open_slots"
    return "new_symbol_missed_without_position_snapshot"


def _delta_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 0:
        return "<0"
    if value < 5:
        return "0-5"
    if value < 10:
        return "5-10"
    if value < 20:
        return "10-20"
    return "20+"


def _delta_vs_weakest_held(row: dict[str, Any]) -> float | None:
    missed_return = _float_or_none(row.get("missed_return_20d"))
    weakest = _weakest_non_same_holding(row)
    held_return = _float_or_none((weakest or {}).get("floating_pnl_pct"))
    if missed_return is None or held_return is None:
        return None
    return round(missed_return - held_return, 4)


def _weakest_non_same_holding(row: dict[str, Any]) -> dict[str, Any] | None:
    holdings = [
        holding
        for holding in _candidate_held_positions(row)
        if not _same_symbol(row.get("vt_symbol"), holding.get("vt_symbol"))
    ]
    if not holdings:
        return None
    return min(
        holdings,
        key=lambda holding: (
            _float_or_none(holding.get("floating_pnl_pct"))
            if _float_or_none(holding.get("floating_pnl_pct")) is not None
            else 10**18,
            str(holding.get("vt_symbol") or ""),
        ),
    )


def _candidate_same_symbol_held(row: dict[str, Any]) -> bool:
    return any(_same_symbol(row.get("vt_symbol"), holding.get("vt_symbol")) for holding in _candidate_held_positions(row))


def _candidate_held_count(row: dict[str, Any]) -> int:
    return len(_candidate_held_positions(row))


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
        "uses_future_for_label_only": False,
        "not_used_for_signal_score": True,
    }
    if persisted_action:
        payload["persisted_action"] = persisted_action
        payload["action_mismatch_resolved"] = persisted_action != action
    payload.update(stock_board_payload(vt_symbol, (stock or {}).get("exchange") or row.get("exchange")))
    return payload


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
        else _candidate_plan_gap_payload("planned_not_ordered", "候选进入理论计划但没有真实下单")
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
        "held_positions": _candidate_held_positions(candidate),
        "uses_future_for_label_only": bool(outcome.get("uses_future_for_label_only", True)),
        "not_used_for_signal_score": True,
    }


def _candidate_held_positions(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    held = candidate.get("held_positions")
    if not isinstance(held, list):
        return []
    rows = [dict(row) for row in held if isinstance(row, dict)]
    rows.sort(key=lambda item: (_float_or_none(item.get("floating_pnl_pct")) or 0.0, _position_entry_score(item) or 0.0, str(item.get("vt_symbol") or "")))
    return rows


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


def _position_entry_score(position: dict[str, Any]) -> float | None:
    raw = position.get("raw") if isinstance(position.get("raw"), dict) else {}
    for key in ("entry_total_score", "total_score", "score"):
        value = _float_or_none(raw.get(key) if raw else position.get(key))
        if value is not None:
            return value
    return None


def _position_support_state(position: dict[str, Any]) -> str:
    raw = position.get("raw") if isinstance(position.get("raw"), dict) else {}
    close_price = _float_or_none(position.get("close_price"))
    support = _float_or_none(raw.get("support_price")) if raw else None
    ma10 = _float_or_none(raw.get("ma10")) if raw else None
    if close_price is None:
        return "unknown"
    if support is not None and close_price < support * 0.99:
        return "weak"
    if ma10 is not None and close_price < ma10 * 0.99:
        return "weak"
    if support is not None or ma10 is not None:
        return "holding_support"
    return "unknown"


def _quality_delta(missed_return: Any, held_return: Any) -> float | None:
    missed = _float_or_none(missed_return)
    held = _float_or_none(held_return)
    if missed is None or held is None:
        return None
    return round(missed - held, 4)


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
