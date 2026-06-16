"""Report helpers for AlphaAgent backtests."""

from __future__ import annotations

import csv
import io
from datetime import date
from statistics import mean
from typing import Any, Callable


def extended_metrics(
    metrics: dict[str, Any],
    closed_trades: list[dict[str, Any]],
    all_trades: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    equity: list[dict[str, Any]],
    *,
    order_execution_model: Callable[[dict[str, Any]], str],
    order_execution: Callable[[dict[str, Any]], dict[str, Any]],
    trade_execution_mode_counts: Callable[[list[dict[str, Any]]], dict[str, int]],
    median: Callable[[list[int | float]], float],
) -> dict[str, Any]:
    sell_trades = [trade for trade in all_trades if trade.get("side") == "SELL"]
    buy_trades = [trade for trade in all_trades if trade.get("side") == "BUY"]
    holding_days = [int(trade["holding_days"]) for trade in closed_trades if trade.get("holding_days") is not None]
    traded_amount = sum(float(trade.get("amount") or 0) for trade in all_trades)
    initial_cash = float(metrics.get("initial_cash") or 0)
    rejected_orders = [order for order in orders if order.get("status") == "rejected"]
    tail_entry_rejected = [
        order
        for order in rejected_orders
        if str(order.get("reason") or "") == "tail_entry_not_triggered"
    ]
    tail_exit_rejected = [order for order in rejected_orders if str(order.get("reason") or "") == "tail_exit_not_triggered"]
    strict_1430_rejected = [order for order in rejected_orders if order_execution_model(order) == "strict_1430"]
    minute_gap_rejected = [
        order
        for order in rejected_orders
        if order_execution_model(order) == "strict_1430"
        and (
            str(order.get("reason") or "") == "missing_1430_snapshot"
            or str(order_execution(order).get("reason") or "") == "missing_1430_snapshot"
            or str(order_execution(order).get("price_source") or "") == ""
        )
    ]
    limit_up_blocked_buys = [order for order in rejected_orders if str(order.get("reason") or "") == "limit_up_tail_unfilled"]
    limit_down_blocked_sells = [
        order
        for order in rejected_orders
        if str(order.get("reason") or "") in {"limit_down_open_blocked", "limit_down_tail_blocked"}
    ]
    exposure = [float(row.get("market_value") or 0) / float(row.get("total_equity") or 1) for row in equity if row.get("total_equity")]
    execution_modes = trade_execution_mode_counts(buy_trades)

    return {
        "total_trade_rows": len(all_trades),
        "buy_count": len(buy_trades),
        "sell_count": len(sell_trades),
        "closed_trade_count": len(closed_trades),
        "open_trade_count": max(len(buy_trades) - len(sell_trades), 0),
        "average_holding_days": mean(holding_days) if holding_days else 0,
        "median_holding_days": median(holding_days),
        "turnover_pct": traded_amount / initial_cash * 100 if initial_cash else None,
        "traded_amount": traded_amount,
        "average_exposure_pct": mean(exposure) * 100 if exposure else 0,
        "max_position_count": max((int(row.get("position_count") or 0) for row in equity), default=0),
        "rejected_order_count": len(rejected_orders),
        "tail_entry_rejected_count": len(tail_entry_rejected),
        "tail_exit_rejected_count": len(tail_exit_rejected),
        "strict_1430_rejected_count": len(strict_1430_rejected),
        "minute_gap_rejected_count": len(minute_gap_rejected),
        "limit_up_blocked_buy_count": len(limit_up_blocked_buys),
        "limit_down_blocked_sell_count": len(limit_down_blocked_sells),
        "filled_order_count": len([order for order in orders if order.get("status") == "filled"]),
        "execution_modes": execution_modes,
    }


def execution_quality_report(
    metrics: dict[str, Any],
    extended_metrics: dict[str, Any],
    data_quality: dict[str, Any],
    sample: dict[str, Any],
    *,
    ratio_pct: Callable[[Any, Any], float | None],
) -> dict[str, Any]:
    execution_modes = extended_metrics.get("execution_modes") or {}
    buy_count = int(extended_metrics.get("buy_count") or 0)
    tail_entry_rejected_count = int(extended_metrics.get("tail_entry_rejected_count") or 0)
    tail_exit_rejected_count = int(extended_metrics.get("tail_exit_rejected_count") or 0)
    strict_1430_rejected_count = int(
        extended_metrics.get("strict_1430_rejected_count")
        or extended_metrics.get("strict_tail_rejected_count")
        or 0
    )
    minute_gap_rejected_count = int(extended_metrics.get("minute_gap_rejected_count") or 0)
    strict_1430_attempt_count = buy_count + strict_1430_rejected_count
    minute_1430_count = int(metrics.get("minute_1430_count") or execution_modes.get("minute_1430") or 0)
    daily_close_proxy_count = int(metrics.get("daily_close_proxy_count") or execution_modes.get("daily_close_proxy") or 0)
    legacy_open_fallback_count = int(metrics.get("daily_open_fallback_count") or execution_modes.get("daily_next_open_fallback") or 0)
    limit_up_blocked_buy_count = int(extended_metrics.get("limit_up_blocked_buy_count") or 0)
    limit_down_blocked_sell_count = int(extended_metrics.get("limit_down_blocked_sell_count") or 0)
    minute_bar_count = int((data_quality.get("stock_minute_bars") or {}).get("count") or 0)
    daily_bar_count = int((data_quality.get("stock_daily_bars") or {}).get("count") or 0)
    financial_count = int((data_quality.get("stock_financial_reports") or {}).get("count") or 0)
    coverage_pct = sample.get("coverage_pct")

    diagnostics = [
        {
            "id": "minute_1430_coverage",
            "label": "14:30真实成交覆盖",
            "status": "pass" if buy_count > 0 and minute_1430_count / buy_count >= 0.8 else "warning",
            "value": ratio_pct(minute_1430_count, buy_count),
            "value_type": "pct",
            "message": (
                "大多数买入由 14:30 分钟快照真实成交。"
                if buy_count > 0 and minute_1430_count / buy_count >= 0.8
                else "当前买入包含较多日线收盘代理，不能宣称是纯分钟真实回测。"
            ),
        },
        {
            "id": "daily_close_proxy_rate",
            "label": "日线收盘代理占比",
            "status": "pass" if buy_count == 0 or daily_close_proxy_count / buy_count <= 0.5 else "warning",
            "value": ratio_pct(daily_close_proxy_count, buy_count),
            "value_type": "pct",
            "message": (
                "日线收盘代理占比较低。"
                if buy_count == 0 or daily_close_proxy_count / buy_count <= 0.5
                else "多数买入使用执行日收盘代理尾盘成交，收益应按混合回测解读。"
            ),
        },
        {
            "id": "strict_tail_rejected_orders",
            "label": "严格14:30拒单",
            "status": "pass" if strict_1430_rejected_count == 0 else "warning",
            "value": strict_1430_rejected_count,
            "value_type": "count",
            "message": (
                "严格分钟尾盘没有因为缺口或未触发而拒单。"
                if strict_1430_rejected_count == 0
                else (
                    "存在缺 14:30 快照的严格拒单，需要先补齐对应交易日分钟线。"
                    if minute_gap_rejected_count > 0
                    else "严格模式仍有候选因尾盘条件未触发而拒单；这是策略条件约束，不是分钟数据缺口。"
                )
            ),
        },
        {
            "id": "tail_entry_rejected_orders",
            "label": "尾盘入场未触发",
            "status": "pass" if tail_entry_rejected_count == 0 else "warning",
            "value": tail_entry_rejected_count,
            "value_type": "count",
            "message": (
                "尾盘入场条件均已触发。"
                if tail_entry_rejected_count == 0
                else "部分候选在执行日尾盘价格偏离 MA5 或被严格模式拒绝，这属于策略条件未满足，不等同于缺数据。"
            ),
        },
        {
            "id": "minute_gap_rejected_orders",
            "label": "缺14:30快照",
            "status": "pass" if minute_gap_rejected_count == 0 else "warning",
            "value": minute_gap_rejected_count,
            "value_type": "count",
            "message": (
                "严格 14:30 模式没有发现缺失快照。"
                if minute_gap_rejected_count == 0
                else "存在缺 14:30 快照的严格拒单，应先通过数据同步补齐对应执行日分钟线。"
            ),
        },
        {
            "id": "legacy_open_fallback_rate",
            "label": "旧版开盘回退占比",
            "status": "pass" if legacy_open_fallback_count == 0 else "warning",
            "value": ratio_pct(legacy_open_fallback_count, buy_count),
            "value_type": "pct",
            "message": (
                "当前不是旧版 D+1 开盘回退模型。"
                if legacy_open_fallback_count == 0
                else "仍存在旧版 D+1 开盘回退成交，请只作为兼容对比解读。"
            ),
        },
        {
            "id": "daily_sample_coverage",
            "label": "股票池日线覆盖",
            "status": "pass" if coverage_pct is not None and float(coverage_pct) >= 80 else "warning",
            "value": coverage_pct,
            "value_type": "pct",
            "message": (
                "日线样本接近全股票池覆盖。"
                if coverage_pct is not None and float(coverage_pct) >= 80
                else "当前回测样本不是全 A，只能代表本地已同步股票池。"
            ),
        },
        {
            "id": "financial_data_presence",
            "label": "财报数据覆盖",
            "status": "pass" if financial_count > 0 else "warning",
            "value": financial_count,
            "value_type": "count",
            "message": "财报数据已参与披露日约束评分。" if financial_count > 0 else "财报数据缺失，现金流改善只能降级处理。",
        },
    ]

    return {
        "status": "warning" if any(item["status"] != "pass" for item in diagnostics) else "pass",
        "buy_count": buy_count,
        "strict_1430_attempt_count": strict_1430_attempt_count,
        "strict_1430_rejected_count": strict_1430_rejected_count,
        "strict_1430_rejected_ratio": ratio_pct(strict_1430_rejected_count, strict_1430_attempt_count),
        "strict_tail_attempt_count": strict_1430_attempt_count,
        "strict_tail_rejected_count": strict_1430_rejected_count,
        "strict_tail_rejected_ratio": ratio_pct(strict_1430_rejected_count, strict_1430_attempt_count),
        "tail_entry_rejected_count": tail_entry_rejected_count,
        "tail_exit_rejected_count": tail_exit_rejected_count,
        "minute_gap_rejected_count": minute_gap_rejected_count,
        "minute_1430_count": minute_1430_count,
        "daily_close_proxy_count": daily_close_proxy_count,
        "legacy_open_fallback_count": legacy_open_fallback_count,
        "limit_up_blocked_buy_count": limit_up_blocked_buy_count,
        "limit_down_blocked_sell_count": limit_down_blocked_sell_count,
        "minute_1430_ratio": ratio_pct(minute_1430_count, buy_count),
        "daily_close_proxy_ratio": ratio_pct(daily_close_proxy_count, buy_count),
        "minute_tail_entry_count": minute_1430_count,
        "minute_tail_entry_ratio": ratio_pct(minute_1430_count, buy_count),
        "daily_open_fallback_count": legacy_open_fallback_count,
        "daily_open_fallback_ratio": ratio_pct(legacy_open_fallback_count, buy_count),
        "minute_bar_count": minute_bar_count,
        "daily_bar_count": daily_bar_count,
        "financial_report_count": financial_count,
        "diagnostics": diagnostics,
    }


def validation_grid_csv_content(grid: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    _write_section(writer, "参数网格摘要")
    writer.writerow(["回测ID", grid["backtest_id"]])
    writer.writerow(["策略", grid["strategy"]])
    writer.writerow(["版本", grid["strategy_version"]])
    writer.writerow(["区间", f"{grid['start_date']} 至 {grid['end_date']}"])
    writer.writerow(["方法", grid["method"]])
    writer.writerow(["组合数量", grid["variant_count"]])
    writer.writerow([])

    _write_dict_rows(writer, "参数空间", [grid.get("param_space") or {}])
    _write_dict_rows(writer, "汇总", [grid.get("summary") or {}])
    _write_dict_rows(writer, "诊断", grid.get("diagnostics") or [])
    walk_forward = grid.get("walk_forward") or {}
    _write_dict_rows(writer, "Walk Forward 汇总", [walk_forward.get("summary") or {}] if walk_forward.get("summary") else [])
    _write_dict_rows(writer, "Walk Forward 诊断", walk_forward.get("diagnostics") or [])
    _write_dict_rows(writer, "Walk Forward 折叠", walk_forward.get("folds") or [])
    _write_dict_rows(writer, "样本外Top组合", grid.get("top_variants") or [])
    _write_dict_rows(writer, "全部参数组合", grid.get("rows") or [])

    _write_section(writer, "限制")
    writer.writerow(["说明"])
    for item in grid.get("limitations") or []:
        writer.writerow([item])

    return "\ufeff" + buffer.getvalue()


def report_csv_content(report: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    _write_section(writer, "回测摘要")
    writer.writerow(["回测ID", report["backtest_id"]])
    writer.writerow(["策略", report["strategy_id"]])
    writer.writerow(["版本", report["strategy_version"]])
    writer.writerow(["区间", f"{report['start_date']} 至 {report['end_date']}"])
    writer.writerow(["执行模型", report["assumptions"].get("execution")])
    writer.writerow([])

    _write_section(writer, "核心指标")
    writer.writerow(["指标", "数值"])
    for row in report.get("summary_rows") or []:
        writer.writerow([row["label"], row.get("value")])
    writer.writerow([])

    _write_section(writer, "样本覆盖")
    writer.writerow(["字段", "数值"])
    for key, value in (report.get("sample") or {}).items():
        writer.writerow([key, value])
    writer.writerow([])

    _write_dict_rows(writer, "扩展交易指标", [report.get("extended_metrics") or {}])
    execution_quality = report.get("execution_quality") or {}
    _write_dict_rows(
        writer,
        "成交真实性检查",
        [{key: value for key, value in execution_quality.items() if key != "diagnostics"}] if execution_quality else [],
    )
    _write_dict_rows(writer, "成交真实性诊断", execution_quality.get("diagnostics") or [])
    data_as_of_audit = report.get("data_as_of_audit") or {}
    _write_dict_rows(writer, "反未来函数审计", data_as_of_audit.get("diagnostics") or [])
    _write_dict_rows(writer, "基准对比", (report.get("benchmark") or {}).get("benchmarks") or [])
    _write_dict_rows(writer, "样本内样本外", (report.get("period_analysis") or {}).get("periods") or [])
    _write_dict_rows(writer, "市场环境分段", (report.get("regime_analysis") or {}).get("periods") or [])
    robustness = report.get("robustness_checks") or {}
    _write_dict_rows(writer, "年度分段", robustness.get("yearly_periods") or [])
    _write_dict_rows(writer, "成本压力测试", robustness.get("cost_stress") or [])
    random_baseline = robustness.get("random_baseline") or {}
    _write_dict_rows(writer, "随机样本基准摘要", [{key: value for key, value in random_baseline.items() if key != "runs"}] if random_baseline else [])
    _write_dict_rows(writer, "随机样本基准明细", random_baseline.get("runs") or [])
    _write_dict_rows(writer, "反过拟合诊断", robustness.get("diagnostics") or [])
    _write_dict_rows(writer, "月度收益", report.get("monthly_returns") or [])
    _write_dict_rows(writer, "个股贡献", report.get("symbol_performance") or [])
    _write_dict_rows(writer, "最差交易", report.get("worst_trades") or [])
    _write_dict_rows(writer, "交易明细", report.get("trades") or [])
    _write_dict_rows(writer, "已闭仓交易", report.get("closed_trades") or [])

    order_stats = report.get("order_stats") or {}
    order_rows = [
        {"type": "status", "name": key, "count": value}
        for key, value in (order_stats.get("by_status") or {}).items()
    ]
    order_rows.extend(
        {"type": "reason", "name": key, "count": value}
        for key, value in (order_stats.get("by_reason") or {}).items()
    )
    _write_dict_rows(writer, "订单统计", order_rows)
    _write_dict_rows(writer, "未成交示例", order_stats.get("rejected_examples") or [])

    data_quality = report.get("data_quality") or {}
    data_quality_rows = [
        {"table": key, "count": value.get("count")}
        for key, value in data_quality.items()
        if isinstance(value, dict)
    ]
    _write_dict_rows(writer, "数据质量", data_quality_rows)

    _write_section(writer, "限制")
    writer.writerow(["说明"])
    for item in [*(data_quality.get("limitations") or []), *(report.get("limitations") or [])]:
        writer.writerow([item])

    return "\ufeff" + buffer.getvalue()


def minute_gap_csv_content(
    orders: list[dict[str, Any]],
    *,
    as_date: Callable[[Any], date | None],
) -> tuple[str, int]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["trade_date", "vt_symbol", "reference_date", "window", "ma5", "minute_bar_count", "missing_reason"])
    gap_count = 0
    seen: set[tuple[str, date]] = set()
    for order in orders:
        trade_date = as_date(order.get("trade_date"))
        vt_symbol = str(order.get("vt_symbol") or "").strip().upper()
        raw = order.get("raw") or {}
        if not trade_date or not vt_symbol or not isinstance(raw, dict):
            continue
        execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else raw
        if not isinstance(execution, dict):
            continue
        mode = str(execution.get("mode") or "")
        if mode not in {"strict_1430_required", "strict_1430_required_sell", "minute_tail_ma5_required"}:
            continue
        if execution.get("price_source"):
            continue
        key = (vt_symbol, trade_date)
        if key in seen:
            continue
        seen.add(key)
        writer.writerow(
            [
                trade_date.isoformat(),
                vt_symbol,
                execution.get("reference_date") or "",
                execution.get("window") or "",
                execution.get("ma5") if execution.get("ma5") is not None else "",
                execution.get("minute_bar_count") if execution.get("minute_bar_count") is not None else "",
                execution.get("reason") or "tail_entry_not_triggered",
            ]
        )
        gap_count += 1
    return "\ufeff" + buffer.getvalue(), gap_count


def _write_section(writer: csv.writer, title: str) -> None:
    writer.writerow([f"## {title}"])


def _write_dict_rows(writer: csv.writer, title: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    writer.writerow([])
    _write_section(writer, title)
    keys = _ordered_csv_keys(rows)
    writer.writerow(keys)
    for row in rows:
        writer.writerow([_csv_value(row.get(key)) for key in keys])
    writer.writerow([])


def _ordered_csv_keys(rows: list[dict[str, Any]]) -> list[str]:
    keys = []
    for row in rows:
        for key in row:
            if key not in keys and key != "windows":
                keys.append(key)
    return keys


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return str(value)
    return value
