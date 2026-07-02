"""Data-quality helpers and summaries for persisted backtests."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from alphaagent.market.boards import stock_board


ReportLoader = Callable[[int, int], dict[str, Any]]
CoverageLoader = Callable[[int], dict[str, Any]]


def backtest_data_quality(
    backtest_id: int,
    *,
    report_loader: ReportLoader,
    coverage_loader: CoverageLoader,
) -> dict[str, Any]:
    """Build a compact data-quality dashboard from existing report evidence."""

    report = report_loader(backtest_id, 1)
    if report.get("status") != "ready":
        return report
    coverage = coverage_loader(backtest_id)
    execution_quality = report.get("execution_quality") or {}
    data_as_of_audit = report.get("data_as_of_audit") or {}
    data_quality = report.get("data_quality") or {}
    sample = report.get("sample") or {}
    financial_rows = int((data_quality.get("stock_financial_reports") or {}).get("count") or 0)
    sample_symbol_count = int(sample.get("symbol_count") or 0)
    sample_coverage_pct = sample.get("coverage_pct")

    checks = [
        _check(
            "minute_1430_coverage",
            "14:30分钟覆盖",
            "pass" if coverage.get("status") == "ready" else "warning",
            coverage.get("minute_1430_count"),
            coverage.get("next_action"),
        ),
        _check(
            "daily_close_proxy",
            "收盘代理",
            "pass" if int(execution_quality.get("daily_close_proxy_count") or 0) == 0 else "warning",
            execution_quality.get("daily_close_proxy_count"),
            "没有使用收盘代理。" if int(execution_quality.get("daily_close_proxy_count") or 0) == 0 else "存在收盘代理成交，不能按纯真实 14:30 解读。",
        ),
        _check(
            "minute_gap_rejections",
            "缺快照拒单",
            "pass" if int(execution_quality.get("minute_gap_rejected_count") or 0) == 0 else "warning",
            execution_quality.get("minute_gap_rejected_count"),
            "缺 14:30 快照的拒单为 0。" if int(execution_quality.get("minute_gap_rejected_count") or 0) == 0 else "需要按回测 ID 补齐缺口后重跑。",
        ),
        _check(
            "financial_visibility",
            "财报历史可见性",
            "pass" if financial_rows > 0 else "warning",
            financial_rows,
            "财报按 publish_date <= trade_date 过滤。" if financial_rows > 0 else "本地可用于历史当日评分的财报不足。",
        ),
        _check(
            "sample_coverage",
            "样本覆盖",
            "pass" if sample_symbol_count > 0 else "warning",
            sample_symbol_count,
            f"本次样本覆盖 {sample_symbol_count} 只股票，覆盖率 {sample_coverage_pct if sample_coverage_pct is not None else '--'}%。",
        ),
    ]
    return {
        "status": _overall_status(coverage.get("status"), checks),
        "backtest_id": backtest_id,
        "strategy_id": report.get("strategy_id"),
        "strategy_version": report.get("strategy_version"),
        "start_date": report.get("start_date"),
        "end_date": report.get("end_date"),
        "execution_model": coverage.get("execution_model"),
        "minute_coverage": coverage,
        "data_as_of_audit": data_as_of_audit,
        "sample": sample,
        "checks": checks,
        "next_action": _next_action(coverage, checks),
    }


def _check(identifier: str, label: str, status: str, value: Any, message: str | None) -> dict[str, Any]:
    return {"id": identifier, "label": label, "status": status, "value": value, "message": message}


def _overall_status(coverage_status: Any, checks: list[dict[str, Any]]) -> str:
    if coverage_status == "ready" and all(item["status"] == "pass" for item in checks[:3]):
        return "ready"
    if coverage_status == "missing_snapshots":
        return "missing_snapshots"
    if coverage_status == "mixed_proxy":
        return "mixed_proxy"
    if any(item["status"] == "warning" for item in checks):
        return "warning"
    return "ready"


def _next_action(coverage: dict[str, Any], checks: list[dict[str, Any]]) -> str:
    if coverage.get("next_action"):
        return str(coverage["next_action"])
    warning = next((item for item in checks if item["status"] == "warning" and item.get("message")), None)
    if warning:
        return str(warning["message"])
    return "数据质量检查通过；仍需结合多年全 A、walk-forward 和参数敏感性验证。"


def candidate_price_discontinuity(
    bars: list[Any],
    *,
    vt_symbol: str,
    signal_date: date,
    entry_execute_date: date | None,
    exit_execute_date: date | None,
) -> dict[str, Any] | None:
    """Return the first probable unadjusted-price discontinuity in a trade path."""

    if entry_execute_date is None:
        return None
    sorted_bars = sorted(bars, key=lambda bar: _bar_date(bar) or date.min)
    upper = exit_execute_date or (_bar_date(sorted_bars[-1]) if sorted_bars else entry_execute_date)
    if upper is None:
        upper = entry_execute_date
    first_index = next(
        (index for index, bar in enumerate(sorted_bars) if (_bar_date(bar) or date.min) >= entry_execute_date),
        None,
    )
    if first_index is None:
        return None
    for index in range(max(first_index, 1), len(sorted_bars)):
        bar = sorted_bars[index]
        trade_date = _bar_date(bar)
        if trade_date is None:
            continue
        if trade_date > upper:
            break
        previous = sorted_bars[index - 1]
        previous_date = _bar_date(previous)
        if previous_date is not None and previous_date < signal_date:
            continue
        discontinuity = bar_price_discontinuity(previous, bar, vt_symbol=vt_symbol)
        if discontinuity:
            return discontinuity
    return None


def bar_price_discontinuity(previous: Any, current: Any, *, vt_symbol: str, threshold: float | None = None) -> dict[str, Any] | None:
    """Detect a price gap too large to be a normal board-limit move."""

    previous_close = _bar_number(previous, "close_price")
    open_price = _bar_number(current, "open_price")
    close_price = _bar_number(current, "close_price")
    if previous_close is None or open_price is None or close_price is None:
        return None
    open_gap = _pct_return(open_price, previous_close)
    close_gap = _pct_return(close_price, previous_close)
    if open_gap is None or close_gap is None:
        return None
    board_threshold = threshold if threshold is not None else price_discontinuity_threshold(vt_symbol)
    change_pct = _bar_number(current, "change_pct")
    if max(abs(open_gap), abs(close_gap)) < board_threshold:
        return None
    if (
        change_pct is not None
        and abs(change_pct) >= board_threshold - 0.5
        and abs(change_pct) <= normal_daily_change_limit(vt_symbol) + 0.5
    ):
        return None
    return {
        "trade_date": _bar_date(current),
        "open_gap_pct": round(open_gap, 4),
        "close_gap_pct": round(close_gap, 4),
        "change_pct": change_pct,
        "previous_close": previous_close,
        "open_price": open_price,
        "close_price": close_price,
    }


def price_discontinuity_threshold(vt_symbol: str) -> float:
    board = stock_board(vt_symbol)
    if board == "bse":
        return 32.0
    if board in {"star", "chinext"}:
        return 22.0
    return 12.0


def normal_daily_change_limit(vt_symbol: str) -> float:
    board = stock_board(vt_symbol)
    if board == "bse":
        return 30.0
    if board in {"star", "chinext"}:
        return 20.0
    return 10.0


def _bar_date(bar: Any) -> date | None:
    value = _bar_value(bar, "trade_date")
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return None


def _bar_number(bar: Any, key: str) -> float | None:
    value = _bar_value(bar, key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bar_value(bar: Any, key: str) -> Any:
    if isinstance(bar, dict):
        return bar.get(key)
    return getattr(bar, key, None)


def _pct_return(price: float, base: float) -> float | None:
    if base <= 0:
        return None
    return (float(price) / float(base) - 1.0) * 100.0
