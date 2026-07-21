"""Drawdown attribution and causal exit research for limit-up replay."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from statistics import mean

from alphaagent.server.services.limit_up import cash_backtest, causal_exit_research

DIAGNOSTICS_VERSION = "limit-up-drawdown-diagnostics-v1"


def build_drawdown_diagnostics(
    *,
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    baseline_account: Mapping[str, object],
    auction_evidence: Sequence[Mapping[str, object]],
    post_auction_prices: Sequence[Mapping[str, object]],
    config: cash_backtest.CashBacktestConfig,
    design_start: date,
    validation_start: date,
    freeze_date: date,
) -> dict[str, object]:
    """Build one reproducible diagnosis without changing the frozen strategy."""

    account_diagnosis = analyze_account_drawdown(
        baseline_account,
        validation_start=validation_start,
        freeze_date=freeze_date,
    )
    calibration = _stock_gene_calibration(
        orders,
        design_start=design_start,
        validation_start=validation_start,
        freeze_date=freeze_date,
    )
    recommendation_regime = analyze_recommendation_regime(
        orders,
        design_start=design_start,
        validation_start=validation_start,
        freeze_date=freeze_date,
    )
    exit_research = causal_exit_research.build_causal_exit_research(
        orders=orders,
        bars=bars,
        trade_dates=trade_dates,
        baseline_account=baseline_account,
        auction_evidence=auction_evidence,
        post_auction_prices=post_auction_prices,
        config=config,
    )
    return {
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "status": "ready" if orders else "insufficient_data",
        "scope_explanation": (
            "账户回撤按两仓真实到达顺序计算；全量推荐曲线不受持仓上限约束，"
            "两者不能混为同一资金曲线。"
        ),
        **account_diagnosis,
        "recommendation_regime": recommendation_regime,
        "stock_gene_calibration": calibration,
        "causes": _diagnostic_causes(
            account_diagnosis,
            recommendation_regime,
            calibration,
        ),
        "exit_research": exit_research,
    }


def analyze_account_drawdown(
    account: Mapping[str, object],
    *,
    validation_start: date,
    freeze_date: date,
) -> dict[str, object]:
    """Analyze clustered losses using only the completed account replay."""

    trades = _mapping_rows(account.get("executed_trades"))
    skipped = _mapping_rows(account.get("skipped_orders"))
    equity_curve = _mapping_rows(account.get("equity_curve"))
    return {
        "longest_losing_streak": _longest_losing_streak(trades),
        "maximum_drawdown_episode": _maximum_drawdown_episode(
            equity_curve,
            trades,
        ),
        "execution_filter": _execution_filter_comparison(
            trades,
            skipped,
            validation_start=validation_start,
            freeze_date=freeze_date,
        ),
        "board_outcome_attribution": _board_outcome_attribution(trades),
    }


def analyze_recommendation_regime(
    orders: Sequence[Mapping[str, object]],
    *,
    design_start: date,
    validation_start: date,
    freeze_date: date,
) -> dict[str, object]:
    """Compare unconstrained recommendation quality across frozen time splits."""

    design = _orders_between(
        orders,
        start=design_start,
        end=validation_start,
        end_inclusive=False,
    )
    validation = _orders_between(
        orders,
        start=validation_start,
        end=freeze_date,
    )
    design_metrics = _outcome_return_metrics(design)
    validation_metrics = _outcome_return_metrics(validation)
    return {
        "design_sample": design_metrics,
        "time_validation": validation_metrics,
        "win_rate_delta_pct_points": _difference(
            validation_metrics.get("win_rate"),
            design_metrics.get("win_rate"),
        ),
        "average_return_delta_pct_points": _difference(
            validation_metrics.get("average_return_pct"),
            design_metrics.get("average_return_pct"),
        ),
    }


def _longest_losing_streak(
    trades: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    ordered = sorted(trades, key=_trade_sort_key)
    current: list[Mapping[str, object]] = []
    longest: list[Mapping[str, object]] = []
    for trade in ordered:
        if (_number(trade.get("return_pct")) or 0.0) < 0:
            current.append(trade)
            if len(current) > len(longest):
                longest = list(current)
        else:
            current = []
    if not longest:
        return {
            "count": 0,
            "start_date": None,
            "end_date": None,
            "first_entry_date": None,
            "compound_return_pct": 0.0,
            "trades": [],
        }
    growth = 1.0
    for trade in longest:
        growth *= 1 + float(trade["return_pct"]) / 100
    return {
        "count": len(longest),
        "start_date": _exit_date_text(longest[0]),
        "end_date": _exit_date_text(longest[-1]),
        "first_entry_date": _entry_date_text(longest[0]),
        "compound_return_pct": round((growth - 1) * 100, 4),
        "trades": [_compact_trade(trade) for trade in longest],
    }


def _maximum_drawdown_episode(
    equity_curve: Sequence[Mapping[str, object]],
    trades: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    rows = [
        row
        for row in sorted(equity_curve, key=lambda item: _row_date_text(item))
        if _number(row.get("total_equity")) is not None
    ]
    if not rows:
        return {
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
            "drawdown_pct": 0.0,
            "duration_trade_days": 0,
            "recovery_trade_days": None,
            "principal_losses": [],
        }

    peak_index = 0
    peak_equity = float(rows[0]["total_equity"])
    trough_index = 0
    episode_peak_index = 0
    maximum_drawdown = 0.0
    for index, row in enumerate(rows):
        equity = float(row["total_equity"])
        if equity >= peak_equity:
            peak_equity = equity
            peak_index = index
        drawdown = (equity / peak_equity - 1) * 100 if peak_equity else 0.0
        if drawdown < maximum_drawdown:
            maximum_drawdown = drawdown
            trough_index = index
            episode_peak_index = peak_index

    recovery_index = next(
        (
            index
            for index in range(trough_index + 1, len(rows))
            if float(rows[index]["total_equity"])
            >= float(rows[episode_peak_index]["total_equity"])
        ),
        None,
    )
    peak_date = _row_date_text(rows[episode_peak_index])
    trough_date = _row_date_text(rows[trough_index])
    losses = [
        trade
        for trade in trades
        if (_number(trade.get("return_pct")) or 0.0) < 0
        and peak_date < _exit_date_text(trade) <= trough_date
    ]
    losses.sort(key=lambda trade: float(trade.get("return_pct") or 0.0))
    return {
        "peak_date": peak_date,
        "trough_date": trough_date,
        "recovery_date": (
            _row_date_text(rows[recovery_index])
            if recovery_index is not None
            else None
        ),
        "drawdown_pct": round(maximum_drawdown, 4),
        "duration_trade_days": trough_index - episode_peak_index,
        "recovery_trade_days": (
            recovery_index - trough_index if recovery_index is not None else None
        ),
        "principal_losses": [_compact_trade(trade) for trade in losses[:5]],
    }


def _execution_filter_comparison(
    trades: Sequence[Mapping[str, object]],
    skipped: Sequence[Mapping[str, object]],
    *,
    validation_start: date,
    freeze_date: date,
) -> dict[str, object]:
    validation_trades = [
        trade
        for trade in trades
        if validation_start <= (_entry_date(trade) or date.min) <= freeze_date
    ]
    validation_skipped = [
        order
        for order in skipped
        if validation_start <= (_trade_date(order) or date.min) <= freeze_date
    ]
    months = [
        value[:7]
        for value in [
            *(_entry_date_text(trade) for trade in trades),
            *(_trade_date_text(order) for order in skipped),
        ]
        if len(value) >= 7
    ]
    latest_month = max(months, default=None)
    latest_trades = [
        trade
        for trade in trades
        if latest_month and _entry_date_text(trade).startswith(latest_month)
    ]
    latest_skipped = [
        order
        for order in skipped
        if latest_month and _trade_date_text(order).startswith(latest_month)
    ]
    return {
        "all": {
            "executed": _return_metrics(trades, "return_pct"),
            "skipped": _return_metrics(skipped, "d1_return_pct"),
        },
        "time_validation": {
            "start": validation_start.isoformat(),
            "end": freeze_date.isoformat(),
            "executed": _return_metrics(validation_trades, "return_pct"),
            "skipped": _return_metrics(validation_skipped, "d1_return_pct"),
        },
        "latest_entry_month": {
            "month": latest_month,
            "executed": _return_metrics(latest_trades, "return_pct"),
            "skipped": _return_metrics(latest_skipped, "d1_return_pct"),
        },
    }


def _board_outcome_attribution(
    trades: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for trade in trades:
        grouped[str(trade.get("d_board_status") or "unknown")].append(trade)
    groups = []
    for status in ("sealed", "failed", "no_limit", "unknown"):
        rows = grouped.get(status, [])
        if not rows:
            continue
        metrics = _return_metrics(rows, "return_pct")
        groups.append(
            {
                "status": status,
                **metrics,
                "hard_loss_count": sum(
                    (_number(row.get("return_pct")) or 0.0) <= -5
                    for row in rows
                ),
            }
        )
    hard_losses = [
        trade
        for trade in trades
        if (_number(trade.get("return_pct")) or 0.0) <= -5
    ]
    failed_hard_losses = [
        trade
        for trade in hard_losses
        if str(trade.get("d_board_status") or "") == "failed"
    ]
    return {
        "actionability": "outcome_only_not_entry_filter",
        "note": "最终封板或炸板只能用于收盘后归因，买入时尚不可知。",
        "groups": groups,
        "hard_loss_count": len(hard_losses),
        "hard_loss_failed_count": len(failed_hard_losses),
        "hard_loss_failed_share_pct": (
            round(len(failed_hard_losses) / len(hard_losses) * 100, 4)
            if hard_losses
            else None
        ),
    }


def _stock_gene_calibration(
    orders: Sequence[Mapping[str, object]],
    *,
    design_start: date,
    validation_start: date,
    freeze_date: date,
) -> dict[str, object]:
    first_board = [
        order
        for order in orders
        if str(order.get("lane") or "") == "first_board"
        and _number(order.get("stock_gene_combined_win_rate")) is not None
        and _outcome_number(order, "next_close_return_pct") is not None
    ]
    design = _orders_between(
        first_board,
        start=design_start,
        end=validation_start,
        end_inclusive=False,
    )
    validation = _orders_between(
        first_board,
        start=validation_start,
        end=freeze_date,
    )
    design_rows = _calibration_buckets(design)
    validation_rows = _calibration_buckets(validation)
    return {
        "field": "stock_gene_combined_win_rate",
        "selection_action": "do_not_add_static_threshold",
        "design_sample": design_rows,
        "time_validation": validation_rows,
        "validation_monotonic": _bucket_win_rates_monotonic(validation_rows),
    }


def _calibration_buckets(
    orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    definitions = (
        ("30%-40%", 30.0, 40.0),
        ("40%-50%", 40.0, 50.0),
        (">=50%", 50.0, None),
    )
    result = []
    for label, lower, upper in definitions:
        rows = [
            order
            for order in orders
            if (_number(order.get("stock_gene_combined_win_rate")) or 0.0)
            >= lower
            and (
                upper is None
                or (_number(order.get("stock_gene_combined_win_rate")) or 0.0)
                < upper
            )
        ]
        returns = [
            value
            for order in rows
            if (value := _outcome_number(order, "next_close_return_pct"))
            is not None
        ]
        result.append(
            {
                "bucket": label,
                "count": len(returns),
                "win_rate": (
                    round(sum(value > 0 for value in returns) / len(returns) * 100, 4)
                    if returns
                    else None
                ),
                "average_return_pct": (
                    round(mean(returns), 4) if returns else None
                ),
            }
        )
    return result


def _diagnostic_causes(
    account_diagnosis: Mapping[str, object],
    recommendation_regime: Mapping[str, object],
    calibration: Mapping[str, object],
) -> list[dict[str, object]]:
    causes: list[dict[str, object]] = []
    design = recommendation_regime.get("design_sample")
    validation_quality = recommendation_regime.get("time_validation")
    design = design if isinstance(design, Mapping) else {}
    validation_quality = (
        validation_quality if isinstance(validation_quality, Mapping) else {}
    )
    if _less(validation_quality.get("win_rate"), design.get("win_rate")):
        causes.append(
            {
                "code": "recommendation_regime_decay",
                "finding": (
                    "全量推荐胜率从设计段 "
                    f"{_percent_text(design.get('win_rate'))} 降至时间验证段 "
                    f"{_percent_text(validation_quality.get('win_rate'))}。"
                ),
                "implication": (
                    "推荐质量存在时变衰减；连续亏损首先是市场阶段问题，不能只靠提高"
                    "一个静态分数阈值解决。"
                ),
            }
        )
    comparison = account_diagnosis.get("execution_filter")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    validation = comparison.get("time_validation")
    validation = validation if isinstance(validation, Mapping) else {}
    executed = validation.get("executed")
    skipped = validation.get("skipped")
    executed = executed if isinstance(executed, Mapping) else {}
    skipped = skipped if isinstance(skipped, Mapping) else {}
    if _less(skipped.get("average_return_pct"), executed.get("average_return_pct")):
        causes.append(
            {
                "code": "late_arrival_regime_decay",
                "finding": "验证段后排未成交推荐显著弱于两仓实际成交。",
                "implication": "两仓和真实到达顺序正在隔离退潮期后排票，不应把全量推荐曲线当成账户回撤。",
            }
        )

    attribution = account_diagnosis.get("board_outcome_attribution")
    attribution = attribution if isinstance(attribution, Mapping) else {}
    share = _number(attribution.get("hard_loss_failed_share_pct"))
    if share is not None and share >= 50:
        causes.append(
            {
                "code": "failed_board_loss_concentration",
                "finding": f"硬亏中有 {share:.2f}% 来自最终炸板。",
                "implication": "这是事后归因，只能指导可交易时点的盘口特征研究，不能直接按最终封板过滤。",
            }
        )
    if calibration.get("validation_monotonic") is False:
        causes.append(
            {
                "code": "stock_gene_rate_not_calibrated",
                "finding": "同股联合率在时间验证段没有随数值升高而改善。",
                "implication": "继续提高静态联合率门槛会产生过拟合，暂不改正式入场阈值。",
            }
        )
    return causes


def _return_metrics(
    rows: Sequence[Mapping[str, object]],
    field: str,
) -> dict[str, object]:
    values = [
        value
        for row in rows
        if (value := _number(row.get(field))) is not None
    ]
    return {
        "count": len(values),
        "win_count": sum(value > 0 for value in values),
        "win_rate": (
            round(sum(value > 0 for value in values) / len(values) * 100, 4)
            if values
            else None
        ),
        "average_return_pct": round(mean(values), 4) if values else None,
    }


def _outcome_return_metrics(
    orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    rows = [
        {"return_pct": value}
        for order in orders
        if (value := _outcome_number(order, "next_close_return_pct")) is not None
    ]
    return _return_metrics(rows, "return_pct")


def _compact_trade(trade: Mapping[str, object]) -> dict[str, object]:
    return {
        field: trade.get(field)
        for field in (
            "vt_symbol",
            "name",
            "lane",
            "entry_date",
            "buy_date",
            "exit_date",
            "sell_date",
            "return_pct",
            "net_pnl",
            "d_board_status",
        )
    }


def _orders_between(
    orders: Sequence[Mapping[str, object]],
    *,
    start: date,
    end: date,
    end_inclusive: bool = True,
) -> list[Mapping[str, object]]:
    return [
        order
        for order in orders
        if (parsed := _order_date(order)) is not None
        and parsed >= start
        and (parsed <= end if end_inclusive else parsed < end)
    ]


def _bucket_win_rates_monotonic(rows: Sequence[Mapping[str, object]]) -> bool | None:
    rates = [
        rate
        for row in rows
        if (rate := _number(row.get("win_rate"))) is not None
    ]
    if len(rates) < 2:
        return None
    return all(left <= right for left, right in zip(rates, rates[1:]))


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _outcome_number(order: Mapping[str, object], field: str) -> float | None:
    outcome = order.get("outcome")
    return _number(outcome.get(field)) if isinstance(outcome, Mapping) else None


def _trade_sort_key(trade: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        _exit_date_text(trade),
        str(trade.get("sell_time") or ""),
        str(trade.get("vt_symbol") or ""),
    )


def _row_date_text(row: Mapping[str, object]) -> str:
    return str(row.get("result_date") or row.get("trade_date") or "")[:10]


def _entry_date_text(row: Mapping[str, object]) -> str:
    return str(
        row.get("entry_date")
        or row.get("buy_date")
        or row.get("signal_date")
        or ""
    )[:10]


def _exit_date_text(row: Mapping[str, object]) -> str:
    return str(
        row.get("exit_date")
        or row.get("sell_date")
        or row.get("result_date")
        or ""
    )[:10]


def _trade_date_text(row: Mapping[str, object]) -> str:
    return str(row.get("trade_date") or row.get("entry_date") or "")[:10]


def _order_date_text(row: Mapping[str, object]) -> str:
    return str(
        row.get("entry_date")
        or row.get("signal_date")
        or row.get("trade_date")
        or ""
    )[:10]


def _entry_date(row: Mapping[str, object]) -> date | None:
    return _date(_entry_date_text(row))


def _trade_date(row: Mapping[str, object]) -> date | None:
    return _date(_trade_date_text(row))


def _order_date(row: Mapping[str, object]) -> date | None:
    return _date(_order_date_text(row))


def _date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _less(left: object, right: object) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return bool(
        left_number is not None
        and right_number is not None
        and left_number < right_number
    )


def _difference(left: object, right: object) -> float | None:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return None
    return round(left_number - right_number, 4)


def _percent_text(value: object) -> str:
    number = _number(value)
    return f"{number:.2f}%" if number is not None else "--"


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
