"""Data-quality summary for persisted backtests."""

from __future__ import annotations

from typing import Any, Callable


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
