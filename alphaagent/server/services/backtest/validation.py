"""Validation-grid helpers for AlphaAgent backtest reports."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
from itertools import product
from statistics import mean
from typing import Any

from alphaagent.server.services.backtest.schemas import BacktestParams


def validation_param_variants(base_params: BacktestParams, max_variants: int, *, same_grid_params) -> list[BacktestParams]:
    min_scores = [64.0, 68.0, 72.0]
    stop_losses = [0.05, 0.07, 0.09]
    take_profits = [0.14, 0.18, 0.22]
    strict_values = [True, False]
    variants = []
    for min_score, stop_loss, take_profit, strict_entry in product(min_scores, stop_losses, take_profits, strict_values):
        variants.append(
            replace(
                base_params,
                min_entry_score=min_score,
                stop_loss_pct=stop_loss,
                take_profit_pct=take_profit,
                strict_entry=strict_entry,
                persist=False,
            )
        )
    max_count = max(min(max_variants, len(variants)), 1)
    base_index = next((index for index, params in enumerate(variants) if same_grid_params(params, base_params)), None)
    if base_index is None or base_index < max_count:
        return variants[:max_count]
    selected = variants[: max_count - 1]
    selected.append(variants[base_index])
    return selected


def validation_row(
    variant_id: int,
    params: BacktestParams,
    base_params: BacktestParams,
    metrics: dict[str, Any],
    in_sample: dict[str, Any] | None,
    out_sample: dict[str, Any] | None,
    sample_benchmark_curve: list[dict[str, Any]],
    high_friction: dict[str, Any] | None,
    *,
    nav_return_pct,
    same_grid_params,
) -> dict[str, Any]:
    strategy_return = metrics.get("total_return_pct")
    sample_return = nav_return_pct(sample_benchmark_curve)
    return {
        "variant_id": variant_id,
        "is_base_params": same_grid_params(params, base_params),
        "min_entry_score": params.min_entry_score,
        "stop_loss_pct": params.stop_loss_pct,
        "take_profit_pct": params.take_profit_pct,
        "strict_entry": params.strict_entry,
        "final_equity": metrics.get("final_equity"),
        "total_return_pct": strategy_return,
        "annual_return_pct": metrics.get("annual_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "trade_count": metrics.get("trade_count"),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": metrics.get("profit_factor"),
        "sharpe": metrics.get("sharpe"),
        "in_sample_return_pct": (in_sample or {}).get("return_pct"),
        "out_sample_return_pct": (out_sample or {}).get("return_pct"),
        "out_sample_excess_pct": (out_sample or {}).get("excess_return_pct"),
        "sample_equal_weight_return_pct": sample_return,
        "sample_equal_weight_excess_pct": (
            float(strategy_return) - float(sample_return)
            if strategy_return is not None and sample_return is not None
            else None
        ),
        "high_friction_return_pct": (high_friction or {}).get("total_return_pct"),
    }


def validation_grid_summary(rows: list[dict[str, Any]], *, ratio_pct, median, rank_for_variant) -> dict[str, Any]:
    returns = numeric_values(rows, "total_return_pct")
    out_returns = numeric_values(rows, "out_sample_return_pct")
    excess_returns = numeric_values(rows, "sample_equal_weight_excess_pct")
    high_friction_returns = numeric_values(rows, "high_friction_return_pct")
    base_row = next((row for row in rows if row.get("is_base_params")), None)
    ranked_total = sorted(rows, key=lambda row: (float(row.get("total_return_pct") or -1e9), -abs(float(row.get("max_drawdown_pct") or 0))), reverse=True)
    ranked_out = sorted(rows, key=lambda row: (float(row.get("out_sample_return_pct") or -1e9), -abs(float(row.get("max_drawdown_pct") or 0))), reverse=True)

    return {
        "variant_count": len(rows),
        "positive_count": len([value for value in returns if value > 0]),
        "positive_ratio": ratio_pct(len([value for value in returns if value > 0]), len(returns)),
        "out_sample_positive_count": len([value for value in out_returns if value > 0]),
        "out_sample_positive_ratio": ratio_pct(len([value for value in out_returns if value > 0]), len(out_returns)),
        "sample_excess_positive_count": len([value for value in excess_returns if value > 0]),
        "sample_excess_positive_ratio": ratio_pct(len([value for value in excess_returns if value > 0]), len(excess_returns)),
        "high_friction_positive_count": len([value for value in high_friction_returns if value > 0]),
        "high_friction_positive_ratio": ratio_pct(len([value for value in high_friction_returns if value > 0]), len(high_friction_returns)),
        "return_avg_pct": mean(returns) if returns else None,
        "return_median_pct": median(returns) if returns else None,
        "return_min_pct": min(returns) if returns else None,
        "return_max_pct": max(returns) if returns else None,
        "out_sample_return_median_pct": median(out_returns) if out_returns else None,
        "base_variant_id": base_row.get("variant_id") if base_row else None,
        "base_total_return_pct": base_row.get("total_return_pct") if base_row else None,
        "base_out_sample_return_pct": base_row.get("out_sample_return_pct") if base_row else None,
        "base_total_rank": rank_for_variant(ranked_total, base_row),
        "base_out_sample_rank": rank_for_variant(ranked_out, base_row),
        "best_total_variant_id": ranked_total[0]["variant_id"] if ranked_total else None,
        "best_out_sample_variant_id": ranked_out[0]["variant_id"] if ranked_out else None,
    }


def validation_grid_diagnostics(summary: dict[str, Any]) -> list[dict[str, Any]]:
    positive_ratio = summary.get("positive_ratio")
    out_ratio = summary.get("out_sample_positive_ratio")
    excess_ratio = summary.get("sample_excess_positive_ratio")
    friction_ratio = summary.get("high_friction_positive_ratio")
    base_out_rank = summary.get("base_out_sample_rank")
    variant_count = int(summary.get("variant_count") or 0)

    return [
        {
            "id": "grid_positive_ratio",
            "label": "参数组合盈利占比",
            "status": "pass" if positive_ratio is not None and positive_ratio >= 60 else "warning",
            "value": positive_ratio,
            "value_type": "pct",
            "message": "多数参数组合为正收益" if positive_ratio is not None and positive_ratio >= 60 else "盈利依赖少数组合，参数敏感性偏高。",
        },
        {
            "id": "grid_out_sample_positive_ratio",
            "label": "样本外盈利占比",
            "status": "pass" if out_ratio is not None and out_ratio >= 50 else "fail",
            "value": out_ratio,
            "value_type": "pct",
            "message": "样本外多数参数为正收益" if out_ratio is not None and out_ratio >= 50 else "样本外稳定性不足，不能认为策略已抗过拟合。",
        },
        {
            "id": "grid_sample_excess_ratio",
            "label": "跑赢样本等权占比",
            "status": "pass" if excess_ratio is not None and excess_ratio >= 50 else "fail",
            "value": excess_ratio,
            "value_type": "pct",
            "message": "多数参数跑赢样本等权" if excess_ratio is not None and excess_ratio >= 50 else "多数参数未跑赢样本等权，选股优势仍不足。",
        },
        {
            "id": "grid_high_friction_ratio",
            "label": "高摩擦正收益占比",
            "status": "pass" if friction_ratio is not None and friction_ratio >= 60 else "warning",
            "value": friction_ratio,
            "value_type": "pct",
            "message": "多数参数在更高交易成本下仍为正" if friction_ratio is not None and friction_ratio >= 60 else "交易成本压力下收益容易被吃掉。",
        },
        {
            "id": "base_out_sample_rank",
            "label": "当前参数样本外排名",
            "status": "pass" if base_out_rank and variant_count and base_out_rank <= max(1, int(variant_count * 0.33)) else "warning",
            "value": base_out_rank,
            "value_type": "count",
            "message": "当前参数处于样本外排名前列" if base_out_rank and variant_count and base_out_rank <= max(1, int(variant_count * 0.33)) else "当前参数不是样本外最稳组合，需谨慎使用默认值。",
        },
    ]


def walk_forward_grid_analysis(
    variant_runs: list[dict[str, Any]],
    benchmark_curve: list[dict[str, Any]],
    *,
    as_date,
    period_summary,
    train_days: int = 60,
    test_days: int = 20,
    step_days: int = 20,
) -> dict[str, Any]:
    if not variant_runs:
        return {"status": "insufficient_data", "folds": [], "diagnostics": []}
    dates = [
        as_date(row.get("trade_date"))
        for row in sorted(variant_runs[0].get("equity") or [], key=lambda item: item["trade_date"])
    ]
    dates = [item for item in dates if item is not None]
    if len(dates) < train_days + test_days:
        return {
            "status": "insufficient_data",
            "method": "rolling_train_select_then_test",
            "folds": [],
            "diagnostics": [],
            "limitations": [f"交易日不足，至少需要 {train_days + test_days} 个交易日。"],
        }

    folds = []
    max_start = len(dates) - train_days - test_days
    for fold_index, start_index in enumerate(range(0, max_start + 1, step_days), start=1):
        train_start = dates[start_index]
        train_end = dates[start_index + train_days - 1]
        test_start = train_end
        test_end = dates[start_index + train_days + test_days - 1]
        ranked = []
        for variant in variant_runs:
            train_summary = variant_period_summary(
                f"fold_{fold_index}_train",
                "训练窗口",
                variant,
                train_start,
                train_end,
                benchmark_curve,
                as_date=as_date,
                period_summary=period_summary,
            )
            test_summary = variant_period_summary(
                f"fold_{fold_index}_test",
                "测试窗口",
                variant,
                test_start,
                test_end,
                benchmark_curve,
                as_date=as_date,
                period_summary=period_summary,
                exclude_start_trade_date=True,
            )
            if train_summary and test_summary:
                ranked.append((variant, train_summary, test_summary))
        if not ranked:
            continue
        selected, train_summary, test_summary = max(
            ranked,
            key=lambda item: (
                float(item[1].get("return_pct") or -1e9),
                float(item[1].get("excess_return_pct") or -1e9),
                -abs(float(item[1].get("max_drawdown_pct") or 0)),
            ),
        )
        params: BacktestParams = selected["params"]
        folds.append(
            {
                "id": f"fold_{fold_index}",
                "train_start_date": train_start.isoformat(),
                "train_end_date": train_end.isoformat(),
                "test_start_date": test_start.isoformat(),
                "test_end_date": test_end.isoformat(),
                "train_days": train_summary["days"],
                "test_days": test_summary["days"],
                "selected_variant_id": selected["variant_id"],
                "min_entry_score": params.min_entry_score,
                "stop_loss_pct": params.stop_loss_pct,
                "take_profit_pct": params.take_profit_pct,
                "strict_entry": params.strict_entry,
                "train_return_pct": train_summary["return_pct"],
                "train_excess_return_pct": train_summary.get("excess_return_pct"),
                "train_max_drawdown_pct": train_summary["max_drawdown_pct"],
                "train_trade_count": train_summary["trade_count"],
                "test_return_pct": test_summary["return_pct"],
                "test_benchmark_return_pct": test_summary.get("benchmark_return_pct"),
                "test_excess_return_pct": test_summary.get("excess_return_pct"),
                "test_max_drawdown_pct": test_summary["max_drawdown_pct"],
                "test_trade_count": test_summary["trade_count"],
                "test_win_rate": test_summary["win_rate"],
                "test_pnl": test_summary["pnl"],
            }
        )

    summary = walk_forward_summary(folds)
    return {
        "status": "ready" if folds else "empty",
        "method": "rolling_train_select_then_test",
        "train_days": train_days,
        "test_days": test_days,
        "step_days": step_days,
        "folds": folds,
        "summary": summary,
        "diagnostics": walk_forward_diagnostics(summary),
        "limitations": [
            "每个折叠只在训练窗口按收益/超额/回撤选择参数，再在后续窗口测试；没有使用未来窗口选择参数。",
            "当前样本只有约数月日线，折叠数量有限，不能代表完整牛熊周期。",
        ],
    }


def variant_period_summary(
    period_id: str,
    label: str,
    variant: dict[str, Any],
    start_date: date,
    end_date: date,
    benchmark_curve: list[dict[str, Any]],
    *,
    as_date,
    period_summary,
    exclude_start_trade_date: bool = False,
) -> dict[str, Any] | None:
    rows = [
        row for row in variant.get("equity") or []
        if start_date <= as_date(row.get("trade_date")) <= end_date
    ]
    if len(rows) < 2:
        return None
    return period_summary(
        period_id,
        label,
        rows,
        variant.get("closed_trades") or [],
        benchmark_curve,
        exclude_start_trade_date=exclude_start_trade_date,
    )


def walk_forward_summary(folds: list[dict[str, Any]], *, ratio_pct=None, median=None) -> dict[str, Any]:
    ratio = ratio_pct or _default_ratio_pct
    median_fn = median or _default_median
    test_returns = numeric_values(folds, "test_return_pct")
    test_excess = numeric_values(folds, "test_excess_return_pct")
    selected_counts: dict[int, int] = defaultdict(int)
    for fold in folds:
        selected_counts[int(fold["selected_variant_id"])] += 1
    most_selected_variant_id = None
    if selected_counts:
        most_selected_variant_id = max(selected_counts.items(), key=lambda item: (item[1], -item[0]))[0]
    return {
        "fold_count": len(folds),
        "positive_test_count": len([value for value in test_returns if value > 0]),
        "positive_test_ratio": ratio(len([value for value in test_returns if value > 0]), len(test_returns)),
        "excess_positive_count": len([value for value in test_excess if value > 0]),
        "excess_positive_ratio": ratio(len([value for value in test_excess if value > 0]), len(test_excess)),
        "test_return_avg_pct": mean(test_returns) if test_returns else None,
        "test_return_median_pct": median_fn(test_returns) if test_returns else None,
        "test_return_min_pct": min(test_returns) if test_returns else None,
        "test_return_max_pct": max(test_returns) if test_returns else None,
        "test_excess_avg_pct": mean(test_excess) if test_excess else None,
        "most_selected_variant_id": most_selected_variant_id,
        "selected_variant_counts": dict(sorted(selected_counts.items())),
    }


def walk_forward_diagnostics(summary: dict[str, Any]) -> list[dict[str, Any]]:
    fold_count = int(summary.get("fold_count") or 0)
    positive_ratio = summary.get("positive_test_ratio")
    excess_ratio = summary.get("excess_positive_ratio")
    excess_avg = summary.get("test_excess_avg_pct")
    return [
        {
            "id": "walk_forward_fold_count",
            "label": "滚动折叠数量",
            "status": "pass" if fold_count >= 3 else "warning",
            "value": fold_count,
            "value_type": "count",
            "message": "折叠数量可用于初步判断" if fold_count >= 3 else "折叠数量不足，只能作烟测。",
        },
        {
            "id": "walk_forward_positive_ratio",
            "label": "测试窗口盈利占比",
            "status": "pass" if positive_ratio is not None and positive_ratio >= 50 else "fail",
            "value": positive_ratio,
            "value_type": "pct",
            "message": "多数未来测试窗口为正收益" if positive_ratio is not None and positive_ratio >= 50 else "未来测试窗口盈利稳定性不足。",
        },
        {
            "id": "walk_forward_excess_ratio",
            "label": "测试窗口超额占比",
            "status": "pass" if excess_ratio is not None and excess_ratio >= 50 else "fail",
            "value": excess_ratio,
            "value_type": "pct",
            "message": "多数未来测试窗口跑赢样本等权" if excess_ratio is not None and excess_ratio >= 50 else "多数未来测试窗口未跑赢样本等权。",
        },
        {
            "id": "walk_forward_avg_excess",
            "label": "测试窗口平均超额",
            "status": "pass" if excess_avg is not None and excess_avg > 0 else "fail",
            "value": excess_avg,
            "value_type": "pct",
            "message": "未来测试窗口平均超额为正" if excess_avg is not None and excess_avg > 0 else "未来测试窗口平均超额为负。",
        },
    ]


def top_validation_variants(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            float(row.get("out_sample_return_pct") if row.get("out_sample_return_pct") is not None else -1e9),
            float(row.get("total_return_pct") if row.get("total_return_pct") is not None else -1e9),
            -abs(float(row.get("max_drawdown_pct") or 0)),
        ),
        reverse=True,
    )
    return ordered[:limit]


def numeric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    values = []
    for row in rows:
        value = row.get(key)
        if value is not None:
            values.append(float(value))
    return values


def rank_for_variant(ordered_rows: list[dict[str, Any]], target: dict[str, Any] | None) -> int | None:
    if not target:
        return None
    target_id = target.get("variant_id")
    for index, row in enumerate(ordered_rows, start=1):
        if row.get("variant_id") == target_id:
            return index
    return None


def same_grid_params(params: BacktestParams, base_params: BacktestParams) -> bool:
    return (
        abs(params.min_entry_score - base_params.min_entry_score) < 1e-9
        and abs(params.stop_loss_pct - base_params.stop_loss_pct) < 1e-9
        and abs(params.take_profit_pct - base_params.take_profit_pct) < 1e-9
        and params.strict_entry == base_params.strict_entry
    )


def _default_ratio_pct(numerator: Any, denominator: Any) -> float | None:
    if not denominator:
        return None
    return float(numerator) / float(denominator) * 100


def _default_median(values: list[int | float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return float((ordered[middle - 1] + ordered[middle]) / 2)
