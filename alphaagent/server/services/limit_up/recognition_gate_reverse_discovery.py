"""Read-only reverse audit for the prior-limit-count recognition gate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from alphaagent.server.services.limit_up import (
    first_board_stock_gene_research,
    history_repository,
    quality_no_trade_reverse,
    quality_opportunity_reverse,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


def run_research(*, start: date, end: date) -> dict[str, object]:
    """Load frozen history and return a non-actionable frequency-gate audit."""

    days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end,
        compact=False,
    )
    orders = scheduled_execution.extract_scheduled_orders(days)
    enriched_orders = (
        first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders(
            days, orders
        )
    )
    symbols = sorted(
        {
            str(order.get("vt_symbol") or "")
            for order in enriched_orders
            if str(order.get("vt_symbol") or "")
        }
    )
    bars = history_repository.load_account_daily_bars(symbols, start, end)
    closed_trades = quality_no_trade_reverse.build_official_closed_trade_evidence(
        enriched_orders,
        bars,
        start=start,
        end=end,
    )
    frame = quality_opportunity_reverse.build_opportunity_reverse_frame(
        enriched_orders,
        closed_trades,
    )
    result = quality_opportunity_reverse.evaluate_frequency_gate_reverse(frame)
    return {
        **result,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "history_day_count": len(days),
        "scheduled_order_count": len(enriched_orders),
        "closed_candidate_count": len(frame),
    }


def render_markdown(result: Mapping[str, object]) -> str:
    """Render batch comparisons and the full reverse-discovery winner ledger."""

    high_return_pct = _number(result.get("high_return_pct"))
    high_return_8_pct = _number(result.get("high_return_sensitivity_pct"))
    lines = [
        "# Recognition Gate Reverse Daily Winner Audit",
        "",
        "## Boundary",
        "",
        f"- 状态：`{str(result.get('status') or 'unavailable')}`。",
        (
            "- 本报告只审计 A+B 基座识别门：反事实母池只移除了 "
            "`prior_limit_count_126` 的 `2-6` 门，"
            "保留同股盈利门、原始涨停价入场和 D+1 官方收盘。"
        ),
        "- 现有 C 救援和正式 `limit-up-core-abc-v2` 成绩不在本报告中重算或替代。",
        (
            f"- 高收益标签为 D+1 净收益 >= {_pct(high_return_pct)}；"
            f">= {_pct(high_return_8_pct)} 仅作敏感性核查。"
        ),
        "- 每日赢家按 D+1 结果排序，仅用于反向发现，不构成可交易规则或正式放行条件。",
        "",
        "## Coverage",
        "",
        f"- 历史帧：{_integer(result.get('history_day_count'))} 日；"
        f"调度候选：{_integer(result.get('scheduled_order_count'))} 笔；"
        f"闭合候选：{_integer(result.get('closed_candidate_count'))} 笔。",
        f"- 结算范围：`{str(result.get('start') or '-')}` 至 `{str(result.get('end') or '-')}`。",
    ]
    batches = _mapping(result.get("time_batches"))
    if batches:
        lines.extend(
            [
                "",
                "## Batch Comparison",
                "",
                "| 批次 | 原门闭合/胜率/均值 | 去门全池闭合/胜率/均值 | 新增闭合/胜率/均值 | 原门捕获每日最高赢家 |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for label, value in batches.items():
            batch = _mapping(value)
            original = _mapping(batch.get("original_gate"))
            removed_pool = _mapping(batch.get("removed_gate_pool"))
            increment = _mapping(batch.get("removed_gate_increment"))
            capture = _mapping(batch.get("daily_top_winner_capture"))
            lines.append(
                "| "
                f"{label} | {_summary_text(original)} | {_summary_text(removed_pool)} | "
                f"{_summary_text(increment)} | "
                f"{_integer(capture.get('captured_day_count'))}/"
                f"{_integer(capture.get('high_return_day_count'))} "
                f"({_pct(capture.get('capture_rate_pct'))}) |"
            )
        for label, value in batches.items():
            batch = _mapping(value)
            buckets = _mapping(batch.get("count_buckets"))
            lines.extend(
                [
                    "",
                    f"### {label} Count Buckets",
                    "",
                    "| 半年触板桶 | 状态 | 闭合 | 胜率 | >=5%命中 | >=8%命中 | 均值 | 硬亏率 | 每日最高赢家 |",
                    "|---|---|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for group in ("<=1", "2-3", "4-6", "7-9", "10+", "missing"):
                summary = _mapping(buckets.get(group))
                lines.append(
                    "| "
                    f"{group} | {str(summary.get('status') or 'INSUFFICIENT')} | "
                    f"{_integer(summary.get('closed_count'))} | "
                    f"{_pct(summary.get('positive_rate_pct'))} | "
                    f"{_integer(summary.get('high_return_count'))}/"
                    f"{_pct(summary.get('high_return_rate_pct'))} | "
                    f"{_integer(summary.get('high_return_8_count'))}/"
                    f"{_pct(summary.get('high_return_8_rate_pct'))} | "
                    f"{_signed_pct(summary.get('average_return_pct'))} | "
                    f"{_pct(summary.get('hard_loss_rate_pct'))} | "
                    f"{_integer(summary.get('daily_top_high_return_count'))} |"
                )
    winners = result.get("daily_high_return_winners")
    if isinstance(winners, Sequence) and not isinstance(winners, (str, bytes)):
        lines.extend(
            [
                "",
                "## Daily High-Return Winners",
                "",
                "| 日期 | 日内排名 | 股票 | D+1净收益 | 次数桶 | 原门通过 | 半年触板 | 原门拒绝原因 |",
                "|---|---:|---|---:|---|---|---:|---|",
            ]
        )
        for item in winners:
            row = _mapping(item)
            lines.append(
                "| "
                f"{str(row.get('trade_date') or '-')} | "
                f"{_integer(row.get('daily_high_return_rank'))} | "
                f"{str(row.get('name') or row.get('vt_symbol') or '-')} | "
                f"{_signed_pct(row.get('return_pct'))} | "
                f"{str(row.get('frequency_group') or '-')} | "
                f"{'是' if row.get('frequency_gate_passed') is True else '否'} | "
                f"{_integer(row.get('prior_limit_count_126'))} | "
                f"{str(row.get('recognition_gate_reason') or '-')} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    """Run the read-only audit against the persisted history ledger."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    result = run_research(start=arguments.start, end=arguments.end)
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _pct(value: object) -> str:
    number = _number(value)
    return f"{number:.2f}%" if number is not None else "-"


def _signed_pct(value: object) -> str:
    number = _number(value)
    return f"{number:+.2f}%" if number is not None else "-"


def _summary_text(summary: Mapping[str, object]) -> str:
    return (
        f"{_integer(summary.get('closed_count'))}/"
        f"{_pct(summary.get('win_rate_pct'))}/"
        f"{_signed_pct(summary.get('average_return_pct'))}"
    )


if __name__ == "__main__":
    main()
