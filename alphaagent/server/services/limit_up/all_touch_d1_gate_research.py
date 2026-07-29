"""Counterfactual study of an all-touch D+1 first-board quality gate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from alphaagent.server.services.limit_up import (
    core_quality,
    first_board_stock_gene_research,
    history_repository,
    history_service,
    quality_no_trade_reverse,
    quality_opportunity_reverse,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    monthly_summaries,
    performance_summary,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


STUDY_VERSION = "limit-up-all-touch-d1-gate-v1"
MINIMUM_D1_SAMPLES = 5
SEAL_RATE_THRESHOLDS = (40.0, 50.0, 60.0)
D1_WIN_RATE_THRESHOLDS = (50.0, 55.0, 60.0)
TIME_SLICES = (
    ("2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("2026_01_02", date(2026, 1, 1), date(2026, 2, 28)),
    ("2026_03_07", date(2026, 3, 1), date(2026, 7, 31)),
)


def all_touch_profitability_gate(
    candidate: Mapping[str, object],
    *,
    minimum_seal_rate: float,
    minimum_d1_win_rate: float,
    minimum_d1_samples: int = MINIMUM_D1_SAMPLES,
) -> dict[str, object]:
    """Evaluate separate seal and all-touch D+1 requirements."""

    lane = str(candidate.get("lane") or candidate.get("board_lane") or "")
    applies = lane == "first_board"
    sample_count = _integer(candidate.get("stock_all_touch_d1_sample_count"))
    seal_rate = _number(candidate.get("stock_gene_seal_rate"))
    d1_win_rate = _number(candidate.get("stock_all_touch_d1_win_rate"))
    passed = True
    reason = "not_first_board"
    if applies and sample_count < minimum_d1_samples:
        passed = False
        reason = "all_touch_d1_samples_below_minimum"
    elif applies and seal_rate is None:
        passed = False
        reason = "seal_rate_unavailable"
    elif applies and seal_rate < minimum_seal_rate:
        passed = False
        reason = "seal_rate_below_minimum"
    elif applies and d1_win_rate is None:
        passed = False
        reason = "all_touch_d1_win_rate_unavailable"
    elif applies and d1_win_rate < minimum_d1_win_rate:
        passed = False
        reason = "all_touch_d1_win_rate_below_minimum"
    elif applies:
        reason = "qualified"
    return {
        "all_touch_profitability_gate_passed": passed,
        "all_touch_profitability_gate_reason": reason,
        "all_touch_profitability_minimum_d1_samples": minimum_d1_samples,
        "all_touch_profitability_minimum_seal_rate": minimum_seal_rate,
        "all_touch_profitability_minimum_d1_win_rate": minimum_d1_win_rate,
    }


def select_ab_orders(
    orders: Sequence[Mapping[str, object]],
    *,
    minimum_seal_rate: float | None = None,
    minimum_d1_win_rate: float | None = None,
) -> list[dict[str, object]]:
    """Select A+B only, optionally replacing the first-board profitability gate."""

    use_all_touch = minimum_seal_rate is not None or minimum_d1_win_rate is not None
    if use_all_touch and (
        minimum_seal_rate is None or minimum_d1_win_rate is None
    ):
        raise ValueError("both all-touch thresholds are required")
    selected: list[dict[str, object]] = []
    for raw_order in sorted(orders, key=_order_sort_key):
        order = dict(raw_order)
        if use_all_touch:
            order = _with_all_touch_profitability_fields(
                order,
                minimum_seal_rate=float(minimum_seal_rate),
                minimum_d1_win_rate=float(minimum_d1_win_rate),
            )
        decision = core_quality.public_quality_gate(
            order,
            c_already_selected=True,
            trigger_observed=True,
        )
        order.update(decision)
        if decision.get("public_quality_actionable") is not True:
            continue
        effective_time = decision.get("quality_entry_effective_time")
        if effective_time:
            order["buy_time"] = effective_time
            order["signal_time"] = effective_time
            order["signal_kind"] = decision.get("quality_entry_effective_kind")
        selected.append(order)
    return selected


def evaluate_threshold_grid(
    frame: pd.DataFrame,
    orders: Sequence[Mapping[str, object]],
    *,
    current_abc_orders: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Compare the current gates with every preregistered threshold pair."""

    current_ab = select_ab_orders(orders)
    current_ab_frame = _selected_frame(frame, current_ab)
    current_abc_frame = _selected_frame(frame, current_abc_orders)
    variants: dict[str, object] = {}
    for seal_rate in SEAL_RATE_THRESHOLDS:
        for d1_win_rate in D1_WIN_RATE_THRESHOLDS:
            selected = select_ab_orders(
                orders,
                minimum_seal_rate=seal_rate,
                minimum_d1_win_rate=d1_win_rate,
            )
            selected_frame = _selected_frame(frame, selected)
            selected_ids = _frame_identities(selected_frame)
            current_ids = _frame_identities(current_ab_frame)
            name = f"seal_{int(seal_rate)}_d1_{int(d1_win_rate)}"
            variants[name] = {
                "minimum_seal_rate_pct": seal_rate,
                "minimum_all_touch_d1_win_rate_pct": d1_win_rate,
                **_summary_bundle(selected_frame, baseline_count=len(frame)),
                "added_vs_current_ab": performance_summary(
                    frame.loc[_identity_mask(frame, selected_ids - current_ids)],
                    baseline_count=len(frame),
                ),
                "removed_vs_current_ab": performance_summary(
                    frame.loc[_identity_mask(frame, current_ids - selected_ids)],
                    baseline_count=len(frame),
                ),
            }
    return {
        "study_version": STUDY_VERSION,
        "status": "historical_counterfactual_only",
        "thresholds": {
            "minimum_d1_samples": MINIMUM_D1_SAMPLES,
            "seal_rate_pct": list(SEAL_RATE_THRESHOLDS),
            "all_touch_d1_win_rate_pct": list(D1_WIN_RATE_THRESHOLDS),
        },
        "current_ab": _summary_bundle(current_ab_frame, baseline_count=len(frame)),
        "current_abc": _summary_bundle(current_abc_frame, baseline_count=len(frame)),
        "variants": variants,
    }


def _with_all_touch_profitability_fields(
    candidate: Mapping[str, object],
    *,
    minimum_seal_rate: float,
    minimum_d1_win_rate: float,
) -> dict[str, object]:
    order = dict(candidate)
    gate = all_touch_profitability_gate(
        order,
        minimum_seal_rate=minimum_seal_rate,
        minimum_d1_win_rate=minimum_d1_win_rate,
    )
    if str(order.get("lane") or order.get("board_lane") or "") == "first_board":
        order.update(
            {
                "sealed_only_stock_d1_sample_count": order.get("stock_d1_sample_count"),
                "sealed_only_stock_d1_win_rate": order.get("stock_d1_win_rate"),
                "sealed_only_stock_d1_average_return_pct": order.get(
                    "stock_d1_average_return_pct"
                ),
                "sealed_only_stock_gene_combined_win_rate": order.get(
                    "stock_gene_combined_win_rate"
                ),
                "stock_d1_sample_count": order.get(
                    "stock_all_touch_d1_sample_count"
                ),
                "stock_d1_win_rate": order.get("stock_all_touch_d1_win_rate"),
                "stock_d1_average_return_pct": order.get(
                    "stock_all_touch_d1_average_return_pct"
                ),
                # The formal function still expects this legacy field. The
                # counterfactual gate above is the actual admission decision.
                "stock_gene_combined_win_rate": (
                    scheduled_execution.FIRST_BOARD_MIN_COMBINED_RATE
                    if gate["all_touch_profitability_gate_passed"] is True
                    else 0.0
                ),
            }
        )
    order.update(gate)
    return order


def _summary_bundle(
    frame: pd.DataFrame,
    *,
    baseline_count: int,
) -> dict[str, object]:
    return {
        "full": performance_summary(frame, baseline_count=baseline_count),
        "time_slices": {
            name: performance_summary(
                frame.loc[
                    pd.to_datetime(frame["trade_date"]).dt.date.between(start, end)
                ],
                baseline_count=baseline_count,
            )
            for name, start, end in TIME_SLICES
        }
        if not frame.empty
        else {},
        "monthly": monthly_summaries(frame),
        "trade_day_count": int(frame["trade_date"].nunique()) if not frame.empty else 0,
    }


def _selected_frame(
    frame: pd.DataFrame,
    orders: Sequence[Mapping[str, object]],
) -> pd.DataFrame:
    identities = {
        identity for order in orders if (identity := _identity(order)) is not None
    }
    return frame.loc[_identity_mask(frame, identities)].copy()


def _frame_identities(frame: pd.DataFrame) -> set[tuple[date, str]]:
    return {
        identity
        for row in frame.to_dict("records")
        if (identity := _identity(row)) is not None
    }


def _identity_mask(
    frame: pd.DataFrame,
    identities: set[tuple[date, str]],
) -> pd.Series:
    if frame.empty or not identities:
        return pd.Series(False, index=frame.index)
    return pd.Series(
        [_identity(row) in identities for row in frame.to_dict("records")],
        index=frame.index,
    )


def _identity(candidate: Mapping[str, object]) -> tuple[date, str] | None:
    trade_date = _as_date(
        candidate.get("trade_date")
        or candidate.get("signal_date")
        or candidate.get("entry_date")
    )
    symbol = str(candidate.get("vt_symbol") or "")
    return (trade_date, symbol) if trade_date is not None and symbol else None


def _order_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    identity = _identity(candidate)
    return (
        identity[0] if identity else date.max,
        str(candidate.get("signal_time") or candidate.get("buy_time") or "99:99:99"),
        str(candidate.get("vt_symbol") or ""),
    )


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def render_markdown(result: Mapping[str, object]) -> str:
    """Render the compact evidence table used for durable project memory."""

    lines = [
        "# 全触板 D+1 盈利门反事实回放",
        "",
        "## Current state",
        "",
        "- 本报告只替换 A+B 首板同股盈利门；正式 A+B+C 和实时推荐未改。",
        "- 全触板 D+1 样本包含最终炸板，且只使用信号日前已经产生 D+1 结果的样本。",
        "- 所有阈值均已查看历史结果，只能用于反事实比较，不能冒充盲测。",
        "",
        "| 方案 | 闭合 | 胜率 | 均值 | 日等权复利 | 回撤 | 交易日 | 3-7月胜率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = {
        "当前A+B": result.get("current_ab", {}),
        "当前A+B+C": result.get("current_abc", {}),
        **dict(result.get("variants") or {}),
    }
    for name, raw in rows.items():
        payload = dict(raw or {})
        full = dict(payload.get("full") or {})
        validation = dict(dict(payload.get("time_slices") or {}).get("2026_03_07") or {})
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(full.get("closed_count", 0)),
                    _pct(full.get("win_rate_pct")),
                    _signed_pct(full.get("average_return_pct")),
                    _signed_pct(full.get("daily_equal_weight_compounded_pct")),
                    _signed_pct(full.get("maximum_drawdown_pct")),
                    str(payload.get("trade_day_count", 0)),
                    _pct(validation.get("win_rate_pct")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Added and removed evidence",
            "",
            "| 方案 | 新增 | 新增胜率 | 新增均值 | 新增复利 | 被删除 | 删除组均值 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, raw in dict(result.get("variants") or {}).items():
        payload = dict(raw or {})
        added = dict(payload.get("added_vs_current_ab") or {})
        removed = dict(payload.get("removed_vs_current_ab") or {})
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(added.get("closed_count", 0)),
                    _pct(added.get("win_rate_pct")),
                    _signed_pct(added.get("average_return_pct")),
                    _signed_pct(added.get("daily_equal_weight_compounded_pct")),
                    str(removed.get("closed_count", 0)),
                    _signed_pct(removed.get("average_return_pct")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "- 本回放只生成反事实证据；任何组合未同时改善数量、复利和回撤时，正式门保持不变。",
            "- 全触板 D+1 字段只作诊断，不接入实时推荐或板前概率。",
            "",
            "## Evidence boundary",
            "",
            f"- 核心门前闭合样本：`{result.get('closed_candidate_count', 0)}`。",
            "- 是否替换正式门必须同时检查全量、2026年3-7月、月度稳定性、新增/删除样本和自然前向。",
            "",
        ]
    )
    return "\n".join(lines)


def _pct(value: object) -> str:
    number = _number(value)
    return f"{number:.2f}%" if number is not None else "-"


def _signed_pct(value: object) -> str:
    number = _number(value)
    return f"{number:+.2f}%" if number is not None else "-"


def main(argv: Sequence[str] | None = None) -> None:
    """Run the read-only counterfactual against the persisted history ledger."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        arguments.end,
        compact=False,
    )
    orders = scheduled_execution.extract_scheduled_orders(days)
    orders = first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders(
        days, orders
    )
    orders = (
        first_board_stock_gene_research.attach_prior_all_touch_d1_evidence_to_orders(
            days, orders
        )
    )
    current_abc_inputs = history_service._attach_historical_c_quality_evidence(orders)
    current_abc_orders, current_abc_audit = (
        core_quality.filter_core_quality_qualified_orders(current_abc_inputs)
    )
    symbols = sorted({str(order.get("vt_symbol") or "") for order in orders})
    bars = history_repository.load_account_daily_bars(
        symbols,
        arguments.start,
        arguments.end,
    )
    closed_trades = quality_no_trade_reverse.build_official_closed_trade_evidence(
        orders,
        bars,
        start=arguments.start,
        end=arguments.end,
    )
    frame = quality_opportunity_reverse.build_opportunity_reverse_frame(
        orders,
        closed_trades,
    )
    result = evaluate_threshold_grid(
        frame,
        orders,
        current_abc_orders=current_abc_orders,
    )
    result.update(
        {
            "start": arguments.start.isoformat(),
            "end": arguments.end.isoformat(),
            "closed_candidate_count": int(len(frame)),
            "current_abc_audit": current_abc_audit,
        }
    )
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
