"""Causally timed D+1 exit research for the frozen limit-up account."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite
from statistics import mean

from alphaagent.server.services.execution import cash_ledger
from alphaagent.server.services.limit_up import cash_backtest

CAUSAL_EXIT_RESEARCH_VERSION = "first-board-causal-exit-research-v1"
WITHDRAWN_POLICY_VERSION = "first-board-auction-take-profit-shadow-v1"
D0_OPEN_BENCHMARK_VERSION = "first-board-d0-open-benchmark-v1"
POST_AUCTION_RESEARCH_VERSION = "first-board-0925-signal-0931-fill-v1"
POST_AUCTION_SIGNAL_THRESHOLDS = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
MIN_POST_AUCTION_COVERAGE_PCT = 95.0


def build_causal_exit_research(
    *,
    orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    baseline_account: Mapping[str, object],
    auction_evidence: Sequence[Mapping[str, object]],
    post_auction_prices: Sequence[Mapping[str, object]],
    config: cash_backtest.CashBacktestConfig,
) -> dict[str, object]:
    """Build causal benchmarks without changing the formal exit policy."""

    benchmark_account = cash_backtest.simulate_limit_up_account(
        attach_d0_first_board_open_benchmark(orders),
        bars,
        trade_dates,
        "dynamic",
        config,
    )
    baseline_summary = _summary(baseline_account)
    benchmark_summary = _summary(benchmark_account)
    post_auction = analyze_post_auction_exit_surface(
        _mapping_rows(baseline_account.get("executed_trades")),
        post_auction_prices,
        config=config,
    )
    return {
        "research_version": CAUSAL_EXIT_RESEARCH_VERSION,
        "status": post_auction["status"],
        "formal_strategy_changed": False,
        "formal_policy": {
            "policy_version": "limit-up-scheduled-v9",
            "mode": "D+1 close",
            "decision_time": "D0 signal time",
            "execution_time": "D+1 15:00",
        },
        "withdrawn_policy": build_withdrawn_policy_audit(),
        "d0_open_benchmark": _d0_open_benchmark_report(
            baseline_summary,
            benchmark_summary,
        ),
        "precommitted_limit_research": (
            analyze_precommitted_auction_limit_readiness(
                _mapping_rows(baseline_account.get("executed_trades")),
                auction_evidence,
            )
        ),
        "post_auction_research": post_auction,
    }


def build_withdrawn_policy_audit() -> dict[str, object]:
    """Return the permanent invalidation record without old performance metrics."""

    return {
        "policy_version": WITHDRAWN_POLICY_VERSION,
        "status": "invalidated_same_price_decision_fill_lookahead",
        "invalidated_on": "2026-07-18",
        "published_metrics_withdrawn": True,
        "published_metrics": None,
        "reason_codes": [
            {
                "code": "final_open_used_as_decision_signal",
                "detail": "09:25 最终开盘价被用于决定是否卖出。",
            },
            {
                "code": "same_open_used_as_fill_price",
                "detail": "决策后又按已经形成的同一个官方开盘价成交。",
            },
            {
                "code": "retrospective_threshold_selection",
                "detail": "2% 阈值来自已查看的历史开盘与收盘结果，不能作为前向证据。",
            },
        ],
    }


def attach_d0_first_board_open_benchmark(
    orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Commit every first-board open exit on D0, before D+1 prices exist."""

    result: list[dict[str, object]] = []
    for source in orders:
        order = dict(source)
        first_board = str(order.get("lane") or "") == "first_board"
        order["dynamic_exit"] = {
            "policy_version": D0_OPEN_BENCHMARK_VERSION,
            "mode": "auction_exit" if first_board else "tail_exit",
            "decision_time": "D0 after close",
            "execution_time": "D+1 opening auction" if first_board else "D+1 close",
            "price_source": (
                "official_daily_open_proxy"
                if first_board
                else "official_daily_close_proxy"
            ),
            "research_only": True,
        }
        result.append(order)
    return result


def analyze_precommitted_auction_limit_readiness(
    trades: Sequence[Mapping[str, object]],
    auction_evidence: Sequence[Mapping[str, object]],
    *,
    minimum_strict_coverage_pct: float = MIN_POST_AUCTION_COVERAGE_PCT,
) -> dict[str, object]:
    """Gate a D0 contingent limit order on strict auction fill evidence."""

    first_board = [
        trade for trade in trades if str(trade.get("lane") or "") == "first_board"
    ]
    required_keys = {_trade_key(trade) for trade in first_board}
    required_keys.discard(("", ""))
    evidence_index = {
        (
            str(row.get("vt_symbol") or ""),
            str(row.get("trade_date") or "")[:10],
        ): row
        for row in auction_evidence
        if row.get("vt_symbol") and row.get("trade_date")
    }
    covered_keys = required_keys & set(evidence_index)
    strict_keys = {
        key
        for key in covered_keys
        if evidence_index[key].get("strict_complete") is True
    }
    unmatched_keys = {
        key
        for key in covered_keys
        if _number(evidence_index[key].get("unmatched_volume")) is not None
    }
    required_count = len(required_keys)
    strict_coverage_pct = (
        round(len(strict_keys) / required_count * 100, 4) if required_count else 0.0
    )
    coverage_passed = bool(
        required_count
        and strict_coverage_pct >= float(minimum_strict_coverage_pct)
        and len(unmatched_keys) == required_count
    )
    return {
        "policy_version": "first-board-d0-contingent-limit-readiness-v1",
        "status": (
            "ready_for_order_replay"
            if coverage_passed
            else "blocked_by_auction_fill_evidence"
        ),
        "rule": (
            "D0 预先提交固定止盈限价单；仅当 D+1 集合竞价真实撮合该订单时退出，"
            "否则撤单并继续持有至收盘。"
        ),
        "decision_time": "D0 after close",
        "selected_threshold_pct": None,
        "coverage": {
            "required_pair_count": required_count,
            "snapshot_covered_pair_count": len(covered_keys),
            "strict_complete_pair_count": len(strict_keys),
            "unmatched_volume_pair_count": len(unmatched_keys),
            "strict_coverage_pct": strict_coverage_pct,
            "minimum_strict_coverage_pct": float(minimum_strict_coverage_pct),
            "coverage_passed": coverage_passed,
        },
        "account_performance": None,
        "account_performance_reason": (
            "缺少竞价未匹配量、委托优先级和严格撮合证据，不能假定预挂单成交。"
        ),
    }


def analyze_post_auction_exit_surface(
    trades: Sequence[Mapping[str, object]],
    post_auction_prices: Sequence[Mapping[str, object]],
    *,
    config: cash_backtest.CashBacktestConfig,
    minimum_coverage_pct: float = MIN_POST_AUCTION_COVERAGE_PCT,
) -> dict[str, object]:
    """Compare later 09:31 fills on covered baseline trades only."""

    first_board = [
        trade for trade in trades if str(trade.get("lane") or "") == "first_board"
    ]
    price_index = _post_auction_price_index(post_auction_prices)
    required_keys = {_trade_key(trade) for trade in first_board}
    required_keys.discard(("", ""))
    covered_keys = required_keys & set(price_index)
    required_count = len(required_keys)
    covered_count = len(covered_keys)
    coverage_pct = (
        round(covered_count / required_count * 100, 4) if required_count else 0.0
    )
    coverage_passed = bool(
        required_count and coverage_pct >= float(minimum_coverage_pct)
    )
    analyzed = [
        row
        for trade in first_board
        if (row := _post_auction_trade(trade, price_index, config)) is not None
    ]
    baseline_metrics = _return_metrics(
        [float(row["close_return_pct"]) for row in analyzed]
    )
    post_auction_metrics = _return_metrics(
        [float(row["post_auction_return_pct"]) for row in analyzed]
    )
    status = (
        "insufficient_data"
        if not required_count
        else (
            "covered_sample_ready_account_replay_pending"
            if coverage_passed
            else "blocked_by_execution_price_coverage"
        )
    )
    return {
        "policy_version": POST_AUCTION_RESEARCH_VERSION,
        "status": status,
        "signal_time": "D+1 09:25 after opening auction",
        "execution_time": "D+1 09:30 continuous auction",
        "execution_price_proxy": "09:31 one-minute bar open",
        "metric_scope": "covered_baseline_trades_signal_diagnostic",
        "selected_threshold_pct": None,
        "coverage": {
            "required_pair_count": required_count,
            "covered_pair_count": covered_count,
            "missing_pair_count": required_count - covered_count,
            "coverage_pct": coverage_pct,
            "minimum_coverage_pct": float(minimum_coverage_pct),
            "coverage_passed": coverage_passed,
        },
        "baseline_covered_sample": baseline_metrics,
        "all_post_auction_exit_sample": post_auction_metrics,
        "threshold_rows": _threshold_rows(analyzed, baseline_metrics),
        "account_performance": None,
        "account_performance_reason": (
            "09:31 成交代理覆盖不足，不能重放完整资金账户。"
            if not coverage_passed
            else "覆盖门通过后仍需实现完整资金账户重放并积累新前向样本。"
        ),
    }


def _d0_open_benchmark_report(
    baseline: Mapping[str, object],
    benchmark: Mapping[str, object],
) -> dict[str, object]:
    return_delta = _difference(
        benchmark.get("total_return_pct"), baseline.get("total_return_pct")
    )
    win_rate_delta = _difference(benchmark.get("win_rate"), baseline.get("win_rate"))
    rejected = (return_delta is not None and return_delta < 0) or (
        win_rate_delta is not None and win_rate_delta < 0
    )
    return {
        "policy_version": D0_OPEN_BENCHMARK_VERSION,
        "status": "rejected_below_frozen_baseline" if rejected else "exploratory",
        "rule": "D0 收盘后无条件决定：首板全部在 D+1 开盘卖出；二进三仍在 D+1 收盘卖出。",
        "decision_time": "D0 after close",
        "price_source": "official_daily_open_proxy",
        "baseline_summary": dict(baseline),
        "summary": dict(benchmark),
        "return_delta_pct_points": return_delta,
        "win_rate_delta_pct_points": win_rate_delta,
    }


def _post_auction_trade(
    trade: Mapping[str, object],
    price_index: Mapping[tuple[str, str], float],
    config: cash_backtest.CashBacktestConfig,
) -> dict[str, float] | None:
    price = price_index.get(_trade_key(trade))
    open_return = _outcome_number(trade, "next_open_return_pct")
    close_return = _number(trade.get("return_pct"))
    buy_price = _number(trade.get("buy_price"))
    buy_amount = _number(trade.get("buy_amount"))
    buy_fee = _number(trade.get("buy_fee"))
    volume = _integer(trade.get("volume"))
    if (
        price is None
        or open_return is None
        or close_return is None
        or buy_price is None
        or buy_amount is None
        or buy_fee is None
        or volume <= 0
    ):
        return None
    cash_cost = buy_amount + buy_fee
    if cash_cost <= 0:
        return None
    sell = cash_ledger.calculate_sell_execution(
        raw_price=price,
        volume=volume,
        cost_price=buy_price,
        commission_rate=config.commission_rate,
        stamp_tax_rate=config.stamp_tax_rate,
        slippage_bps=config.slippage_bps,
        minimum_commission=config.minimum_commission,
        transfer_fee_rate=config.transfer_fee_rate,
    )
    post_return = (sell.cash_delta - cash_cost) / cash_cost * 100
    return {
        "open_signal_return_pct": open_return,
        "post_auction_return_pct": post_return,
        "close_return_pct": close_return,
    }


def _threshold_rows(
    analyzed: Sequence[Mapping[str, float]],
    baseline_metrics: Mapping[str, object],
) -> list[dict[str, object]]:
    baseline_average = _number(baseline_metrics.get("average_return_pct"))
    rows = []
    for threshold in POST_AUCTION_SIGNAL_THRESHOLDS:
        values = [
            float(row["post_auction_return_pct"])
            if float(row["open_signal_return_pct"]) >= threshold
            else float(row["close_return_pct"])
            for row in analyzed
        ]
        metrics = _return_metrics(values)
        rows.append(
            {
                "threshold_pct": threshold,
                "trigger_count": sum(
                    float(row["open_signal_return_pct"]) >= threshold
                    for row in analyzed
                ),
                "sample_count": len(values),
                "win_rate": metrics["win_rate"],
                "average_return_pct": metrics["average_return_pct"],
                "average_return_delta_vs_close_pct_points": _difference(
                    metrics.get("average_return_pct"), baseline_average
                ),
            }
        )
    return rows


def _post_auction_price_index(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for row in rows:
        price = _number(row.get("price_0931"))
        key = (
            str(row.get("vt_symbol") or ""),
            str(row.get("trade_date") or "")[:10],
        )
        if all(key) and price is not None and price > 0:
            result[key] = price
    return result


def _trade_key(trade: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(trade.get("vt_symbol") or ""),
        str(trade.get("exit_date") or trade.get("sell_date") or "")[:10],
    )


def _summary(account: Mapping[str, object]) -> dict[str, object]:
    value = account.get("execution_summary")
    return dict(value) if isinstance(value, Mapping) else {}


def _return_metrics(values: Sequence[float]) -> dict[str, object]:
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


def _outcome_number(row: Mapping[str, object], field: str) -> float | None:
    outcome = row.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    return _number(outcome.get(field))


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _difference(left: object, right: object) -> float | None:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return None
    return round(left_number - right_number, 4)


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _integer(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
