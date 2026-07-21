"""Compact product evidence derived from the full cross-regime replay."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cross_regime_validation import build_sequential_regime_audit


RESEARCH_VERSION = "cross-regime-support-reclaim-proxy-v1"
POLICY_VERSION = "causal-leader-pullback-cross-regime-v3"
SOURCE_STUDY_VERSION = "causal-leader-pullback-study-v4"
VARIANT = "cross_regime_support_reclaim_confirmation"
TIME_BLOCK_IDS = tuple(f"block_{index}" for index in range(1, 6))
MARKET_PHASE_IDS = ("rotation", "warming")


def build_cross_regime_product_report(
    report: Mapping[str, Any],
    *,
    source_path: str,
    source_sha256: str,
) -> dict[str, Any]:
    """Reduce the full audit ledger to the immutable API evidence payload."""

    _require_version(report, "study_version", SOURCE_STUDY_VERSION)
    _require_version(report, "policy_version", POLICY_VERSION)
    signals = {
        str(row["signal_id"]): row
        for row in _mapping_rows(report.get("candidate_signal_ledger"), "signal")
    }
    trades = [
        row
        for row in _mapping_rows(report.get("trade_ledger"), "trade")
        if row.get("variant") == VARIANT and row.get("net_return_pct") is not None
    ]
    trades.sort(key=lambda row: (str(row.get("entry_date")), str(row.get("signal_id"))))
    overall = _variant_row(report.get("overall_metrics"), "overall metric")
    cash = _mapping(_mapping(report.get("cash_results"), "cash results").get(VARIANT), "cash result")
    decision = _variant_row(report.get("decisions"), "decision")
    phases = _ordered_group_rows(
        report.get("market_phase_metrics"),
        MARKET_PHASE_IDS,
        "group",
    )
    blocks = _ordered_group_rows(
        report.get("time_block_metrics"),
        TIME_BLOCK_IDS,
        "time_block",
    )
    coverage = _mapping(report.get("coverage"), "coverage")
    cases = [_case_row(trade, signals) for trade in trades]
    years = _calendar_year_metrics(trades)
    wilson_lower = _wilson_lower_bound(trades)
    sequential_audit = build_sequential_regime_audit(
        _mapping_rows(report.get("trade_ledger"), "trade"),
        _mapping_rows(report.get("candidate_signal_ledger"), "signal"),
    )
    point_gate_passed = bool(decision.get("historical_proxy_gate_passed"))
    sequential_passed = bool(
        _mapping(
            sequential_audit.get("qualification"),
            "sequential qualification",
        ).get("sequential_cross_regime_passed")
    )
    warnings = _stability_warnings(years, wilson_lower, sequential_audit)
    formal_blockers = _formal_blockers(sequential_passed)

    return {
        "research_version": RESEARCH_VERSION,
        "research_kind": "dynamic_leader_cross_regime_pullback",
        "research_status": _research_status(point_gate_passed, sequential_passed),
        "policy_version": POLICY_VERSION,
        "signal_algorithm_version": str(report.get("algorithm_version") or ""),
        "formal_strategy": False,
        "formal_metrics": None,
        "historical_proxy_gate_passed": point_gate_passed,
        "contract": _product_contract(report),
        "coverage": {
            "concepts": _integer(coverage.get("concepts")),
            "candidate_signals": _integer(coverage.get("candidate_signals")),
            "policy_confirmations": _integer(
                _mapping(report.get("signal_funnel"), "signal funnel").get(
                    "cross_regime_support_reclaim_confirmations"
                )
            ),
            "selected_trades": len(trades),
            "cash_closed_trades": _integer(cash.get("closed_trades")),
            "symbols": len({str(row.get("vt_symbol")) for row in trades}),
            "trade_dates": len({str(row.get("entry_date")) for row in trades}),
        },
        "performance": {
            "initial_cash": _number(cash.get("initial_cash")),
            "final_equity": _number(cash.get("final_equity")),
            "closed_trades": _integer(cash.get("closed_trades")),
            "winning_trades": _integer(cash.get("winning_trades")),
            "win_rate_pct": _number(cash.get("cash_win_rate_pct")),
            "signal_closed_trades": _integer(overall.get("closed_trades")),
            "signal_win_rate_pct": _number(overall.get("positive_rate_pct")),
            "mean_trade_return_pct": _number(overall.get("mean_net_return_pct")),
            "profit_factor": _number(overall.get("profit_factor")),
            "compound_return_pct": _number(cash.get("compound_return_pct")),
            "maximum_drawdown_pct": _number(cash.get("maximum_drawdown_pct")),
            "signal_compound_return_pct": _number(overall.get("compound_return_pct")),
            "signal_maximum_drawdown_pct": _number(
                overall.get("maximum_drawdown_pct")
            ),
            "round_trip_cost_pct": _number(
                _mapping(report.get("contract"), "contract").get(
                    "round_trip_cost_pct"
                )
            ),
        },
        "market_phases": [_metric_row(row, "group") for row in phases],
        "time_blocks": [_metric_row(row, "time_block") for row in blocks],
        "calendar_years": years,
        "cases": cases,
        "sequential_audit": sequential_audit,
        "qualification": {
            "historical_proxy_gate_passed": point_gate_passed,
            "full_history_point_gate_passed": point_gate_passed,
            "sequential_cross_regime_passed": sequential_passed,
            "sequential_failed_gates": list(
                _mapping(
                    sequential_audit.get("qualification"),
                    "sequential qualification",
                ).get("failed_gates")
                or []
            ),
            "stable_time_blocks": _integer(decision.get("stable_time_blocks")),
            "qualified_market_phases": list(
                decision.get("qualified_market_phases") or []
            ),
            "formal_blockers": formal_blockers,
        },
        "stability": {
            "all_five_blocks_above_60pct": all(
                _number(row.get("positive_rate_pct")) > 60.0 for row in blocks
            ),
            "wilson_95_lower_win_rate_pct": wilson_lower,
            "warnings": warnings,
        },
        "boundaries": [
            "107 笔结果来自已查看历史样本，只能作为历史代理规则证据。",
            "D 日最终收盘同时用于确认和买价，不代表可在该价格实盘成交。",
            "历史概念成员仍以当前成分回放，存在幸存者偏差。",
            "分钟线和资金流均未参与信号选择。",
            "退潮、危险、未知及样本不足行情空仓，不用低质量交易凑覆盖。",
        ],
        "evidence_boundary": {
            "same_close_research_proxy": True,
            "strict_historical_membership": False,
            "point_in_time_executable": False,
            "forward_validation_required": True,
        },
        "source_artifact": {
            "path": source_path,
            "sha256": source_sha256,
        },
    }


def render_cross_regime_product_json(report: Mapping[str, Any]) -> str:
    return json.dumps(dict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _product_contract(report: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(report.get("contract"), "contract")
    return {
        "universe": "概念主升期动态 Top3 龙头；仅沪深主板，排除 ST",
        "main_rise": str(source.get("concept_campaign") or ""),
        "leader": str(source.get("leader_rank") or ""),
        "pullback": "第一轮回调测试 MA5；创新高后的第二轮及以后测试 MA10",
        "confirmation": (
            "GOLD/NORMAL 强收复；rotation 直接执行，warming 还须守住支撑 2% 容差"
        ),
        "market_policy": [
            {"phase": "rotation", "action": "strong_reclaim"},
            {"phase": "warming", "action": "strong_reclaim_and_support_floor"},
            {"phase": "uptrend", "action": "cash_insufficient_sample"},
            {"phase": "retreat_or_danger_or_unknown", "action": "cash"},
        ],
        "observation": "D 日收盘后确认的纯日线信号",
        "entry": "D 日收盘价研究代理",
        "entry_assumption": "same_close_research_proxy",
        "execution_boundary": "同收盘成交是历史研究代理，不代表实盘可成交价格",
        "holding_style": "d1_loss_then_structural",
        "exit": {
            "mode": "d1_loss_then_structural",
            "d1_loss": "D+1 扣成本后不盈利则收盘退出",
            "take_profit": "first_higher_high",
            "defensive": "structure_break_or_concept_end",
            "execution": "completed_daily_close",
        },
        "portfolio": {
            "capacity": _integer(
                _mapping(report.get("cash_results"), "cash results")
                .get(VARIANT, {})
                .get("capacity")
            ),
            "position_target": "当前权益四分之一，不加杠杆",
            "concept_limit": 1,
        },
    }


def _case_row(
    trade: Mapping[str, Any],
    signals: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    signal_id = str(trade.get("signal_id") or "")
    signal = signals.get(signal_id)
    if signal is None:
        raise ValueError(f"trade signal is missing: {signal_id}")
    support_price = _number(signal.get("support_price"))
    signal_low = _number(signal.get("signal_low"))
    reference_peak = _number(signal.get("reference_peak_price"))
    signal_close = _number(signal.get("signal_close"))
    return {
        "signal_id": signal_id,
        "signal_date": str(trade.get("entry_date") or ""),
        "vt_symbol": str(trade.get("vt_symbol") or ""),
        "stock_name": str(signal.get("stock_name") or ""),
        "concept_name": str(signal.get("concept_name") or ""),
        "market_phase": str(trade.get("market_phase") or ""),
        "time_block": str(trade.get("time_block") or ""),
        "dynamic_rank": _integer(trade.get("dynamic_rank")),
        "wave_number": _integer(trade.get("wave_number")),
        "support_line": str(trade.get("support_line") or ""),
        "support_test_date": str(trade.get("support_test_date") or ""),
        "signal_low_to_support_pct": (signal_low / support_price - 1.0) * 100.0,
        "signal_daily_return_pct": _number(signal.get("signal_daily_return_pct")),
        "peak_gap_pct": (signal_close / reference_peak - 1.0) * 100.0,
        "entry_price": _number(trade.get("entry_price")),
        "d1_date": str(trade.get("d1_date") or ""),
        "d1_net_return_pct": _number(trade.get("d1_net_return_pct")),
        "exit_date": str(trade.get("exit_date") or ""),
        "exit_price": _number(trade.get("exit_price")),
        "exit_reason": str(trade.get("exit_reason") or ""),
        "net_return_pct": _number(trade.get("net_return_pct")),
    }


def _metric_row(row: Mapping[str, Any], id_column: str) -> dict[str, Any]:
    return {
        "id": str(row.get(id_column) or ""),
        "closed_trades": _integer(row.get("closed_trades")),
        "win_rate_pct": _number(row.get("positive_rate_pct")),
        "mean_net_return_pct": _number(row.get("mean_net_return_pct")),
        "profit_factor": _number(row.get("profit_factor")),
        "compound_return_pct": _number(row.get("compound_return_pct")),
        "maximum_drawdown_pct": _number(row.get("maximum_drawdown_pct")),
    }


def _calendar_year_metrics(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    years = sorted({str(row.get("entry_date"))[:4] for row in trades})
    return [
        {
            "year": year,
            **_return_metrics(
                [row for row in trades if str(row.get("entry_date")).startswith(year)]
            ),
        }
        for year in years
    ]


def _return_metrics(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [_number(row.get("net_return_pct")) for row in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    return {
        "closed_trades": len(values),
        "win_rate_pct": len(wins) / len(values) * 100.0,
        "mean_net_return_pct": sum(values) / len(values),
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "compound_return_pct": (
            math.prod(1.0 + value / 100.0 for value in values) - 1.0
        )
        * 100.0,
    }


def _wilson_lower_bound(trades: Sequence[Mapping[str, Any]]) -> float:
    total = len(trades)
    wins = sum(_number(row.get("net_return_pct")) > 0 for row in trades)
    z = 1.959963984540054
    rate = wins / total
    denominator = 1.0 + z * z / total
    center = (rate + z * z / (2.0 * total)) / denominator
    half_width = (
        z
        * math.sqrt(rate * (1.0 - rate) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return (center - half_width) * 100.0


def _stability_warnings(
    years: Sequence[Mapping[str, Any]],
    wilson_lower: float,
    sequential_audit: Mapping[str, Any],
) -> list[str]:
    warnings = [
        f"107 笔胜率的 95% Wilson 下界为 {wilson_lower:.2f}%，仍低于 60%。"
    ]
    if any(str(row.get("year")) == "2026" for row in years):
        warnings.append("2026 warming 子样本为 24 笔、胜率 58.33%，尚未单独过门。")
    qualification = _mapping(
        sequential_audit.get("qualification"),
        "sequential qualification",
    )
    if not qualification.get("sequential_cross_regime_passed"):
        warnings.append(
            "后两时间块的逐行情顺序验证未通过，不能用全历史点估计宣称已适配各种行情。"
        )
    return warnings


def _research_status(point_gate_passed: bool, sequential_passed: bool) -> str:
    if not point_gate_passed:
        return "historical_proxy_point_gate_failed"
    if not sequential_passed:
        return "historical_proxy_point_gate_passed_sequential_regime_failed"
    return "historical_proxy_sequential_gate_passed_formal_blocked"


def _formal_blockers(sequential_passed: bool) -> list[str]:
    blockers = []
    if not sequential_passed:
        blockers.append("sequential_cross_regime_validation_failed")
    blockers.extend(
        [
            "strict_historical_membership_missing",
            "same_close_execution_is_research_proxy",
        ]
    )
    return blockers


def _ordered_group_rows(
    value: object,
    identifiers: Sequence[str],
    id_column: str,
) -> list[Mapping[str, Any]]:
    rows = [
        row
        for row in _mapping_rows(value, id_column)
        if row.get("variant") == VARIANT
    ]
    by_id = {str(row.get(id_column)): row for row in rows}
    missing = [identifier for identifier in identifiers if identifier not in by_id]
    if missing:
        raise ValueError(f"missing {id_column} rows: {', '.join(missing)}")
    return [by_id[identifier] for identifier in identifiers]


def _variant_row(value: object, label: str) -> Mapping[str, Any]:
    matches = [
        row
        for row in _mapping_rows(value, label)
        if row.get("variant") == VARIANT
    ]
    if len(matches) != 1:
        raise ValueError(f"{label} must contain one cross-regime row")
    return matches[0]


def _require_version(report: Mapping[str, Any], field: str, expected: str) -> None:
    if report.get(field) != expected:
        raise ValueError(f"unexpected {field}: {report.get(field)}")


def _mapping_rows(value: object, label: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} rows must be a list")
    return [_mapping(row, label) for row in value]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _integer(value: object) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError("required integer is missing")
    return int(value)


def _number(value: object) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError("required number is missing")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("required number is not finite")
    return number


def load_json_report(path: Path) -> Mapping[str, Any]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), "source report")
