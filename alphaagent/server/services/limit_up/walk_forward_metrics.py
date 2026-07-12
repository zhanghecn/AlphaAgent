"""Performance and acceptance metrics for limit-up walk-forward reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from math import isfinite, prod
from statistics import mean
from typing import Mapping, Sequence


def probability_calibration_summary(
    rows: Sequence[Mapping[str, object]],
    *,
    entry_mode: str,
) -> dict[str, object]:
    model_names = ["seal", "profit"]
    if entry_mode == "sweep":
        model_names.insert(0, "fill")
    result: dict[str, object] = {}
    for model_name in model_names:
        observations: list[tuple[int, float, float, object]] = []
        for row in rows:
            if (
                model_name == "profit"
                and entry_mode != "tail"
                and row.get("fill_proxy") is False
            ):
                continue
            label = _probability_label(row, model_name)
            raw = _number(row.get(f"raw_{model_name}_probability"))
            calibrated = _number(row.get(f"{model_name}_probability"))
            if label is None or raw is None or calibrated is None:
                continue
            observations.append((label, raw, calibrated, row.get("window_sequence")))
        if not observations:
            continue
        labels = [label for label, _, _, _ in observations]
        raw_probabilities = [raw for _, raw, _, _ in observations]
        calibrated_probabilities = [value for _, _, value, _ in observations]
        result[model_name] = {
            "window_count": len({sequence for _, _, _, sequence in observations}),
            "sample_count": len(observations),
            "raw_brier": _rounded(
                mean(
                    (probability - label) ** 2
                    for label, probability in zip(
                        labels,
                        raw_probabilities,
                        strict=True,
                    )
                )
            ),
            "calibrated_brier": _rounded(
                mean(
                    (probability - label) ** 2
                    for label, probability in zip(labels, calibrated_probabilities, strict=True)
                )
            ),
            "auc": _binary_auc(labels, calibrated_probabilities),
        }
    return result


def performance_summary(
    rows: Sequence[Mapping[str, object]],
    *,
    entry_mode: str,
    extra_cost_pct: float = 0.0,
) -> dict[str, object]:
    closed = [
        row
        for row in rows
        if row.get("fill_proxy") is not False
        and _number(row.get("realized_return_pct")) is not None
    ]
    returns = [float(row["realized_return_pct"]) - extra_cost_pct for row in closed]
    daily: dict[str, list[float]] = defaultdict(list)
    for row, return_pct in zip(closed, returns, strict=True):
        daily[str(row.get("signal_date") or "")].append(return_pct)
    daily_returns = [(trade_date, mean(values)) for trade_date, values in sorted(daily.items())]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for _, return_pct in daily_returns:
        equity *= 1 + return_pct / 100
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    quarters: dict[str, list[float]] = defaultdict(list)
    for trade_date, return_pct in daily_returns:
        parsed = date.fromisoformat(trade_date)
        quarters[f"{parsed.year}-Q{(parsed.month - 1) // 3 + 1}"].append(return_pct)
    positive_quarters = sum(
        prod(1 + value / 100 for value in values) > 1
        for values in quarters.values()
    )
    return {
        "signal_count": len(rows),
        "filled_count": len(closed),
        "execution_scope": "observational_tail" if entry_mode == "tail" else "daily_proxy",
        "win_rate": _rounded(sum(value > 0 for value in returns) / len(returns) * 100)
        if returns
        else None,
        "average_return_pct": _rounded(mean(returns)) if returns else None,
        "total_return_pct": _rounded((equity - 1) * 100),
        "max_drawdown_pct": _rounded(max_drawdown * 100),
        "profit_factor": _rounded(gains / losses) if losses else (999.0 if gains else None),
        "hard_loss_rate": _rounded(sum(value <= -5 for value in returns) / len(returns) * 100)
        if returns
        else None,
        "positive_quarter_rate": _rounded(positive_quarters / len(quarters) * 100)
        if quarters
        else None,
        "quarter_count": len(quarters),
        "concentration": _profit_concentration(closed, returns),
    }


def acceptance_gates(
    phases: Mapping[str, Mapping[str, object]],
    stress: Mapping[str, object],
    calibration: Mapping[str, object],
    coverage: Mapping[str, object],
) -> list[dict[str, object]]:
    expanding = phases.get("expanding_oos") or {}
    holdout = phases.get("locked_holdout") or {}
    stressed_holdout = stress.get("locked_holdout")
    stressed_holdout = stressed_holdout if isinstance(stressed_holdout, Mapping) else {}
    concentration = expanding.get("concentration")
    concentration = concentration if isinstance(concentration, Mapping) else {}
    maximum_concentration = max(
        (
            value
            for value in (
                _number(concentration.get("max_stock_pct")),
                _number(concentration.get("max_industry_pct")),
                _number(concentration.get("max_month_pct")),
            )
            if value is not None
        ),
        default=100.0,
    )
    profit_calibration = calibration.get("profit")
    profit_calibration = profit_calibration if isinstance(profit_calibration, Mapping) else {}
    raw_brier = _number(profit_calibration.get("raw_brier"))
    calibrated_brier = _number(profit_calibration.get("calibrated_brier"))
    membership_ready = not bool(coverage.get("industry_membership_survivorship_risk", True))
    expanding_trades = int(_number(expanding.get("filled_count")) or 0)
    definitions = [
        ("oos_trades", "样本外可成交交易不少于300笔", _number(expanding.get("filled_count")), 300.0, lambda value: value >= 300),
        ("holdout_return", "锁定留出复利为正", _number(holdout.get("total_return_pct")), 0.0, lambda value: value > 0),
        ("profit_factor", "样本外利润因子大于1.25", _number(expanding.get("profit_factor")), 1.25, lambda value: value > 1.25),
        ("drawdown", "样本外最大回撤小于15%", _number(expanding.get("max_drawdown_pct")), -15.0, lambda value: expanding_trades > 0 and value > -15),
        ("stress_return", "双倍成本下留出收益为正", _number(stressed_holdout.get("total_return_pct")), 0.0, lambda value: value > 0),
        ("positive_quarters", "样本外正收益季度不少于60%", _number(expanding.get("positive_quarter_rate")), 60.0, lambda value: value >= 60),
        ("concentration", "单股/行业/月度利润贡献不超过35%", maximum_concentration, 35.0, lambda value: value <= 35),
        ("calibration", "盈利概率校准不劣于原始概率", calibrated_brier, raw_brier, lambda value: raw_brier is not None and value <= raw_brier),
        ("point_in_time_membership", "历史行业成员具备点时版本", float(membership_ready), 1.0, lambda value: bool(value)),
        ("execution_evidence", "成交证据达到非代理口径", 0.0, 1.0, lambda value: bool(value)),
    ]
    return [
        {
            "code": code,
            "label": label,
            "value": _rounded(value),
            "target": _rounded(target),
            "passed": value is not None and bool(predicate(value)),
        }
        for code, label, value, target, predicate in definitions
    ]


def rejection_summary(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        for reason in row.get("rejection_reasons") or []:
            counts[str(reason)] += 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _profit_concentration(
    rows: Sequence[Mapping[str, object]],
    returns: Sequence[float],
) -> dict[str, float | None]:
    gross_profit = sum(max(value, 0.0) for value in returns)
    if gross_profit <= 0:
        return {"max_stock_pct": None, "max_industry_pct": None, "max_month_pct": None}
    stock: dict[str, float] = defaultdict(float)
    industry: dict[str, float] = defaultdict(float)
    month: dict[str, float] = defaultdict(float)
    for row, value in zip(rows, returns, strict=True):
        profit = max(value, 0.0)
        stock[str(row.get("vt_symbol") or "unknown")] += profit
        industry[str(row.get("industry_name") or "unknown")] += profit
        month[str(row.get("signal_date") or "")[:7]] += profit
    return {
        "max_stock_pct": _rounded(max(stock.values()) / gross_profit * 100),
        "max_industry_pct": _rounded(max(industry.values()) / gross_profit * 100),
        "max_month_pct": _rounded(max(month.values()) / gross_profit * 100),
    }


def _probability_label(row: Mapping[str, object], model_name: str) -> int | None:
    if model_name == "fill":
        value = row.get("fill_proxy")
        return int(value) if isinstance(value, bool) else None
    if model_name == "seal":
        value = row.get("sealed")
        return int(value) if isinstance(value, bool) else None
    realized = _number(row.get("realized_return_pct"))
    return int(realized > 0) if realized is not None else None


def _binary_auc(labels: Sequence[int], probabilities: Sequence[float]) -> float | None:
    positive = sum(labels)
    negative = len(labels) - positive
    if not positive or not negative:
        return None
    ordered = sorted(zip(probabilities, labels, strict=True), key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2
        rank_sum += average_rank * sum(label for _, label in ordered[index:end])
        index = end
    return _rounded((rank_sum - positive * (positive + 1) / 2) / (positive * negative))


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _rounded(value: object, digits: int = 4) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None
