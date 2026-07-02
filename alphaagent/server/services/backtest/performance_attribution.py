"""Read-only attribution for current vs historical backtest performance."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Callable

from sqlalchemy import and_, desc, select, text


SessionScope = Callable[[], Any]


def backtest_performance_attribution_report(
    *,
    schema: Any,
    session_scope: SessionScope,
    is_database_configured: Callable[[], bool],
    ensure_schema: Callable[[], None],
    reason_label: Callable[[Any], str | None],
    current_schema_version: str,
    backtest_id: int,
    reference_backtest_id: int | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Compare one backtest against the best comparable historical run."""

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    ensure_schema()

    with session_scope() as session:
        current_run = _load_run(session, schema, backtest_id)
        if not current_run:
            return {"status": "not_found", "id": backtest_id}

        reference_run = _load_reference_run(
            session,
            schema,
            current_run,
            reference_backtest_id=reference_backtest_id,
        )
        if not reference_run:
            return {
                "status": "empty_reference",
                "backtest_id": backtest_id,
                "message": "没有找到同策略、同区间、同核心组合参数的历史回测可用于对比。",
            }

        current_trades = _load_trades(session, schema, backtest_id)
        reference_trades = _load_trades(session, schema, int(reference_run["id"]))
        current_schema = _load_signal_schema_summary(session, backtest_id)
        reference_schema = _load_signal_schema_summary(session, int(reference_run["id"]))
        current_monthly = _load_monthly_returns(session, schema, backtest_id)
        reference_monthly = _load_monthly_returns(session, schema, int(reference_run["id"]))

    limit = min(max(int(sample_limit or 20), 1), 100)
    current_summary = _run_summary(current_run, current_trades)
    reference_summary = _run_summary(reference_run, reference_trades)
    exit_rows = _exit_reason_attribution(current_trades, reference_trades, reason_label)
    trade_deltas = _paired_trade_deltas(current_trades, reference_trades, limit=limit)
    constraint_comparison = _constraint_comparison(current_run, reference_run)
    monthly_rows = _monthly_attribution(current_monthly, reference_monthly)

    return {
        "status": "ready",
        "backtest_id": backtest_id,
        "reference_backtest_id": int(reference_run["id"]),
        "reference_selection": {
            "mode": "explicit" if reference_backtest_id else "best_comparable_historical_run",
            "same_strategy": current_run.get("strategy_id") == reference_run.get("strategy_id"),
            "same_strategy_version": current_run.get("strategy_version") == reference_run.get("strategy_version"),
            "same_date_range": current_run.get("start_date") == reference_run.get("start_date")
            and current_run.get("end_date") == reference_run.get("end_date"),
        },
        "current": current_summary,
        "reference": reference_summary,
        "delta": _summary_delta(current_summary, reference_summary),
        "constraint_comparison": constraint_comparison,
        "signal_schema": {
            "current_required_version": current_schema_version,
            "current": current_schema,
            "reference": reference_schema,
            "same_schema_lineage": _same_schema_lineage(current_schema, reference_schema),
        },
        "by_exit_reason": exit_rows,
        "monthly": monthly_rows,
        "trade_deltas": trade_deltas,
        "interpretation": _interpretation(
            current_summary=current_summary,
            reference_summary=reference_summary,
            constraint_comparison=constraint_comparison,
            current_schema=current_schema,
            reference_schema=reference_schema,
            exit_rows=exit_rows,
            current_schema_version=current_schema_version,
        ),
        "note": "只读归因报告；用于解释收益/胜率差异，不改变默认买卖或评分规则。",
    }


def _load_run(session: Any, schema: Any, backtest_id: int) -> dict[str, Any] | None:
    row = session.execute(select(schema.backtest_runs).where(schema.backtest_runs.c.id == int(backtest_id))).mappings().first()
    return dict(row) if row else None


def _load_reference_run(
    session: Any,
    schema: Any,
    current_run: dict[str, Any],
    *,
    reference_backtest_id: int | None,
) -> dict[str, Any] | None:
    if reference_backtest_id:
        return _load_run(session, schema, int(reference_backtest_id))

    query = (
        select(schema.backtest_runs)
        .where(
            and_(
                schema.backtest_runs.c.id != int(current_run["id"]),
                schema.backtest_runs.c.status == "succeeded",
                schema.backtest_runs.c.strategy_id == current_run["strategy_id"],
                schema.backtest_runs.c.strategy_version == current_run["strategy_version"],
                schema.backtest_runs.c.start_date == current_run["start_date"],
                schema.backtest_runs.c.end_date == current_run["end_date"],
            )
        )
        .order_by(desc(schema.backtest_runs.c.final_equity / schema.backtest_runs.c.initial_cash), desc(schema.backtest_runs.c.id))
        .limit(200)
    )
    candidates = [dict(row) for row in session.execute(query).mappings().all()]
    for row in candidates:
        if _same_core_portfolio_params(current_run, row):
            return row
    return candidates[0] if candidates else None


def _load_trades(session: Any, schema: Any, backtest_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        select(schema.backtest_trades)
        .where(schema.backtest_trades.c.backtest_id == int(backtest_id))
        .order_by(schema.backtest_trades.c.trade_date, schema.backtest_trades.c.id)
    ).mappings().all()
    return [dict(row) for row in rows]


def _load_signal_schema_summary(session: Any, backtest_id: int) -> dict[str, Any]:
    rows = session.execute(
        text(
            """
            select
              side,
              count(*) as event_count,
              count(*) filter (where raw ? 'evidence') as raw_evidence_count,
              count(*) filter (where raw->'evidence' ? 'signal_evidence_schema_version') as nested_schema_count,
              count(*) filter (where raw ? 'signal_evidence_schema_version') as top_schema_count,
              min(signal_date) as min_signal_date,
              max(signal_date) as max_signal_date
            from backtest_signal_events
            where backtest_id = :backtest_id
            group by side
            """
        ),
        {"backtest_id": int(backtest_id)},
    ).mappings().all()
    versions = session.execute(
        text(
            """
            select raw->'evidence'->>'signal_evidence_schema_version' as version, count(*) as count
            from backtest_signal_events
            where backtest_id = :backtest_id
              and side = 'BUY'
              and raw->'evidence' ? 'signal_evidence_schema_version'
            group by version
            order by count desc, version
            """
        ),
        {"backtest_id": int(backtest_id)},
    ).mappings().all()
    by_side = {str(row["side"]): _plain_mapping(dict(row)) for row in rows}
    buy = by_side.get("BUY", {})
    buy_count = int(buy.get("event_count") or 0)
    nested_count = int(buy.get("nested_schema_count") or 0)
    return {
        "by_side": by_side,
        "buy_event_count": buy_count,
        "buy_with_schema_count": nested_count,
        "buy_schema_coverage": nested_count / buy_count if buy_count else None,
        "schema_versions": [_plain_mapping(dict(row)) for row in versions],
        "is_current_schema_lineage": bool(buy_count and nested_count / buy_count >= 0.9),
    }


def _load_monthly_returns(session: Any, schema: Any, backtest_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        select(schema.backtest_daily_equity)
        .where(schema.backtest_daily_equity.c.backtest_id == int(backtest_id))
        .order_by(schema.backtest_daily_equity.c.trade_date)
    ).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        trade_date = _as_date(row.get("trade_date"))
        if not trade_date:
            continue
        grouped[f"{trade_date.year:04d}-{trade_date.month:02d}"].append(row)
    result = []
    for month, month_rows in sorted(grouped.items()):
        first = month_rows[0]
        last = month_rows[-1]
        start_equity = _safe_float(first.get("total_equity"))
        end_equity = _safe_float(last.get("total_equity"))
        result.append(
            {
                "month": month,
                "return_pct": _pct_change(end_equity, start_equity),
                "start_equity": start_equity,
                "end_equity": end_equity,
            }
        )
    return result


def _run_summary(run: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = _json_dict(run.get("metrics"))
    params = _json_dict(run.get("params"))
    trade_summary = _trade_metric_summary([row for row in trades if row.get("side") == "SELL"])
    return {
        "id": int(run["id"]),
        "strategy_id": run.get("strategy_id"),
        "strategy_version": run.get("strategy_version"),
        "start_date": _iso_date(run.get("start_date")),
        "end_date": _iso_date(run.get("end_date")),
        "initial_cash": _safe_float(run.get("initial_cash")),
        "final_equity": _safe_float(run.get("final_equity")),
        "total_return_pct": _metric(metrics, "total_return_pct", _run_return_pct(run)),
        "max_drawdown_pct": _metric(metrics, "max_drawdown_pct"),
        "win_rate": _metric(metrics, "win_rate", trade_summary["win_rate"]),
        "profit_factor": _metric(metrics, "profit_factor", trade_summary["profit_factor"]),
        "buy_count": int(_metric(metrics, "buy_count", len([row for row in trades if row.get("side") == "BUY"])) or 0),
        "sell_count": int(_metric(metrics, "sell_count", trade_summary["trade_count"]) or 0),
        "open_trade_count": int(_metric(metrics, "open_trade_count", 0) or 0),
        "average_win": _metric(metrics, "average_win", trade_summary["average_win"]),
        "average_loss": _metric(metrics, "average_loss", trade_summary["average_loss"]),
        "trade_summary": trade_summary,
        "params": {
            "candidate_limit": _param_number(params, "candidate_limit"),
            "max_positions": _param_number(params, "max_positions"),
            "max_position_pct": _param_number(params, "max_position_pct"),
            "min_entry_score": _param_number(params, "min_entry_score"),
            "execution_model": params.get("execution_model") or "legacy_next_open",
        },
    }


def _trade_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnl_values = [_safe_float(row.get("pnl")) or 0.0 for row in rows]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value <= 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    return {
        "trade_count": len(pnl_values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(pnl_values) if pnl_values else None,
        "average_win": sum(wins) / len(wins) if wins else None,
        "average_loss": sum(losses) / len(losses) if losses else None,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "profit_factor": gross_win / abs(gross_loss) if gross_loss else None,
        "net_pnl": sum(pnl_values),
    }


def _exit_reason_attribution(
    current_trades: list[dict[str, Any]],
    reference_trades: list[dict[str, Any]],
    reason_label: Callable[[Any], str | None],
) -> list[dict[str, Any]]:
    current = _reason_metrics(current_trades)
    reference = _reason_metrics(reference_trades)
    reasons = sorted(set(current) | set(reference))
    rows = []
    for reason in reasons:
        current_row = current.get(reason, _trade_metric_summary([]))
        reference_row = reference.get(reason, _trade_metric_summary([]))
        rows.append(
            {
                "exit_reason": None if reason == "unknown" else reason,
                "exit_reason_label": reason_label(reason) or reason,
                "current": current_row,
                "reference": reference_row,
                "delta": _trade_summary_delta(current_row, reference_row),
            }
        )
    rows.sort(key=lambda item: abs(_safe_float(item["delta"].get("net_pnl")) or 0.0), reverse=True)
    return rows


def _reason_metrics(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        if row.get("side") != "SELL":
            continue
        grouped[str(row.get("reason") or "unknown")].append(row)
    return {reason: _trade_metric_summary(rows) for reason, rows in grouped.items()}


def _paired_trade_deltas(
    current_trades: list[dict[str, Any]],
    reference_trades: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    current = _sell_trade_index(current_trades)
    reference = _sell_trade_index(reference_trades)
    rows = []
    for key in sorted(set(current) | set(reference)):
        current_row = current.get(key)
        reference_row = reference.get(key)
        current_pnl = _safe_float(current_row.get("pnl")) if current_row else None
        reference_pnl = _safe_float(reference_row.get("pnl")) if reference_row else None
        rows.append(
            {
                "vt_symbol": (current_row or reference_row or {}).get("vt_symbol"),
                "trade_date": _iso_date((current_row or reference_row or {}).get("trade_date")),
                "current_reason": current_row.get("reason") if current_row else None,
                "current_pnl": current_pnl,
                "reference_reason": reference_row.get("reason") if reference_row else None,
                "reference_pnl": reference_pnl,
                "delta_pnl": (current_pnl or 0.0) - (reference_pnl or 0.0),
            }
        )
    return {
        "largest_negative": sorted(rows, key=lambda item: item["delta_pnl"])[:limit],
        "largest_positive": sorted(rows, key=lambda item: item["delta_pnl"], reverse=True)[:limit],
        "missing_reference_winners": [
            row for row in sorted(rows, key=lambda item: item["delta_pnl"])
            if row["reference_pnl"] and row["reference_pnl"] > 0 and row["current_pnl"] is None
        ][:limit],
        "added_current_losers": [
            row for row in sorted(rows, key=lambda item: item["delta_pnl"])
            if row["current_pnl"] is not None and row["current_pnl"] <= 0 and row["reference_pnl"] is None
        ][:limit],
    }


def _sell_trade_index(trades: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in trades:
        if row.get("side") != "SELL":
            continue
        key = (str(row.get("vt_symbol") or ""), _iso_date(row.get("trade_date")) or "")
        result.setdefault(key, row)
    return result


def _constraint_comparison(current_run: dict[str, Any], reference_run: dict[str, Any]) -> dict[str, Any]:
    current = _json_dict(current_run.get("params"))
    reference = _json_dict(reference_run.get("params"))
    keys = ["candidate_limit", "max_positions", "max_position_pct", "min_entry_score", "execution_model"]
    rows = []
    for key in keys:
        current_value = current.get(key)
        reference_value = reference.get(key)
        if key == "execution_model":
            current_value = current_value or "legacy_next_open"
            reference_value = reference_value or "legacy_next_open"
        rows.append(
            {
                "key": key,
                "current": current_value,
                "reference": reference_value,
                "same": _normal_value(current_value) == _normal_value(reference_value),
            }
        )
    return {
        "core_params": rows,
        "same_max_positions": _same_param(current, reference, "max_positions"),
        "same_candidate_limit": _same_param(current, reference, "candidate_limit"),
        "same_position_sizing": _same_param(current, reference, "max_position_pct"),
        "same_core_portfolio_params": _same_core_portfolio_params(current_run, reference_run),
    }


def _monthly_attribution(current_rows: list[dict[str, Any]], reference_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current = {row["month"]: row for row in current_rows}
    reference = {row["month"]: row for row in reference_rows}
    rows = []
    for month in sorted(set(current) | set(reference)):
        current_return = _safe_float((current.get(month) or {}).get("return_pct"))
        reference_return = _safe_float((reference.get(month) or {}).get("return_pct"))
        rows.append(
            {
                "month": month,
                "current_return_pct": current_return,
                "reference_return_pct": reference_return,
                "delta_return_pct": _subtract(current_return, reference_return),
            }
        )
    rows.sort(key=lambda item: abs(_safe_float(item.get("delta_return_pct")) or 0.0), reverse=True)
    return rows


def _summary_delta(current: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "total_return_pct",
        "max_drawdown_pct",
        "win_rate",
        "profit_factor",
        "average_win",
        "average_loss",
        "buy_count",
        "sell_count",
    ]
    result = {key: _subtract(_safe_float(current.get(key)), _safe_float(reference.get(key))) for key in keys}
    result.update(_trade_summary_delta(current["trade_summary"], reference["trade_summary"]))
    return result


def _trade_summary_delta(current: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    keys = ["trade_count", "win_count", "loss_count", "win_rate", "average_win", "average_loss", "gross_win", "gross_loss", "profit_factor", "net_pnl"]
    return {key: _subtract(_safe_float(current.get(key)), _safe_float(reference.get(key))) for key in keys}


def _interpretation(
    *,
    current_summary: dict[str, Any],
    reference_summary: dict[str, Any],
    constraint_comparison: dict[str, Any],
    current_schema: dict[str, Any],
    reference_schema: dict[str, Any],
    exit_rows: list[dict[str, Any]],
    current_schema_version: str,
) -> dict[str, Any]:
    notes = []
    next_tests = []
    return_delta = _subtract(_safe_float(current_summary.get("total_return_pct")), _safe_float(reference_summary.get("total_return_pct")))
    if return_delta is not None:
        notes.append(f"当前收益比历史参照低 {abs(return_delta):.2f} 个百分点。")
    if constraint_comparison.get("same_max_positions") and constraint_comparison.get("same_candidate_limit"):
        notes.append("两组核心执行参数相同：候选执行排名和基础组合参数一致，收益下降应继续看候选质量、卖点和行情分桶。")
    if not _same_schema_lineage(current_schema, reference_schema):
        coverage = _safe_float(current_schema.get("buy_schema_coverage")) or 0.0
        notes.append(
            f"历史参照 BUY 候选缺少当前 evidence schema；当前 schema 覆盖约 {coverage * 100:.1f}%，版本要求 {current_schema_version}。旧高收益属于旧候选语义。"
        )
    gross_win_delta = _subtract(
        _safe_float(current_summary["trade_summary"].get("gross_win")),
        _safe_float(reference_summary["trade_summary"].get("gross_win")),
    )
    gross_loss_delta = _subtract(
        _safe_float(current_summary["trade_summary"].get("gross_loss")),
        _safe_float(reference_summary["trade_summary"].get("gross_loss")),
    )
    if gross_win_delta is not None and gross_loss_delta is not None:
        notes.append(f"毛盈利减少约 {gross_win_delta:,.0f}，毛亏损变化约 {gross_loss_delta:,.0f}；主因是赢家贡献变少，而不是单笔亏损明显扩大。")
    trend_row = next((row for row in exit_rows if row.get("exit_reason") == "trend_trailing_stop"), None)
    if trend_row:
        current_trend = trend_row["current"]
        reference_trend = trend_row["reference"]
        delta = trend_row["delta"]
        notes.append(
            "趋势赢家减少："
            f"趋势跟踪止盈 {int(reference_trend.get('trade_count') or 0)} -> {int(current_trend.get('trade_count') or 0)} 笔，"
            f"贡献变化 {(_safe_float(delta.get('net_pnl')) or 0.0):,.0f}。"
        )
        next_tests.append("先复核趋势赢家减少的卖点路径：用候选独立交易和逐笔退出原因拆分赢家丢失来源。")
    support_row = next((row for row in exit_rows if row.get("exit_reason") == "support_stop"), None)
    if support_row:
        next_tests.append("再测支撑止损后的独立候选质量：按卖点前后分别统计候选收益和回撤。")
    next_tests.append("按 行情阶段 x setup 只读矩阵筛掉负期望桶，再做默认关闭实验；不要直接追求更高买入频率。")
    return {"notes": notes, "next_tests": next_tests}


def _same_core_portfolio_params(left_run: dict[str, Any], right_run: dict[str, Any]) -> bool:
    left = _json_dict(left_run.get("params"))
    right = _json_dict(right_run.get("params"))
    keys = ["candidate_limit", "max_positions", "max_position_pct", "min_entry_score", "stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "time_stop_days"]
    return all(_same_param(left, right, key) for key in keys) and not _has_single_symbol(left) and not _has_single_symbol(right)


def _same_schema_lineage(current_schema: dict[str, Any], reference_schema: dict[str, Any]) -> bool:
    current_versions = {str(row.get("version")) for row in current_schema.get("schema_versions") or [] if row.get("version")}
    reference_versions = {str(row.get("version")) for row in reference_schema.get("schema_versions") or [] if row.get("version")}
    return bool(current_versions and current_versions == reference_versions)


def _same_param(left: dict[str, Any], right: dict[str, Any], key: str) -> bool:
    return _normal_value(left.get(key)) == _normal_value(right.get(key))


def _has_single_symbol(params: dict[str, Any]) -> bool:
    symbols = params.get("symbols")
    return isinstance(symbols, list) and len([item for item in symbols if item]) == 1


def _json_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _metric(metrics: dict[str, Any], key: str, fallback: Any = None) -> Any:
    value = metrics.get(key)
    return fallback if value is None else value


def _run_return_pct(run: dict[str, Any]) -> float | None:
    return _pct_change(_safe_float(run.get("final_equity")), _safe_float(run.get("initial_cash")))


def _pct_change(end_value: float | None, start_value: float | None) -> float | None:
    if end_value is None or not start_value:
        return None
    return (end_value / start_value - 1) * 100


def _param_number(params: dict[str, Any], key: str) -> float | None:
    return _safe_float(params.get(key))


def _param_bool(params: dict[str, Any], key: str, default: bool) -> bool:
    value = params.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normal_value(value: Any) -> Any:
    parsed = _safe_float(value)
    if parsed is not None:
        return round(parsed, 8)
    if value is None:
        return None
    return str(value)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return None


def _iso_date(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


def _plain_mapping(row: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in row.items():
        result[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return result
