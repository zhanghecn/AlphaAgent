"""Daily-only historical proxy for limit-up quality coverage research."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up import cash_backtest
from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    monthly_summaries,
    performance_summary,
)
from alphaagent.server.services.limit_up.history_engine import build_daily_feature_frame
from alphaagent.server.services.limit_up.history_repository import (
    load_reliable_history_frame,
)
from alphaagent.server.services.limit_up.lane_repository import (
    FinancialIndex,
    build_financial_index,
    financial_risk_as_of,
    financial_snapshot_as_of,
)
from alphaagent.server.services.limit_up.quality_reconstruction import (
    MAXIMUM_PRIOR_LIMIT_COUNT_126,
    MINIMUM_PRIOR_INDUSTRY_TURNOVER_RATIO_5D,
    MINIMUM_PRIOR_LIMIT_COUNT_126,
    quality_rule_masks,
)


STUDY_VERSION = "limit-up-daily-proxy-quality-v1"
PROXY_CONTRACT = "daily-touch-limit-price-next-close-v1"
REAL_EVENT_COVERAGE_START = date(2025, 6, 27)
DISCOVERY_START = date(2026, 3, 1)
LOOKBACK_SESSIONS = 140
STOCK_HISTORY_WINDOW_SESSIONS = 252
MINIMUM_STOCK_D1_SAMPLES = 5
MINIMUM_STOCK_COMBINED_RATE = 30.0
FIRST_BOARD_MINIMUM_TOUCH_COUNT = 6
FIRST_BOARD_MINIMUM_NET_PROFIT_YOY = 10.0


def build_daily_proxy_frame(
    feature_frame: pd.DataFrame,
    financial_index: FinancialIndex,
    *,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Build daily-touch candidates without inventing an intraday timestamp."""

    if feature_frame.empty:
        return pd.DataFrame()
    frame = feature_frame.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    signal_rows = frame.loc[
        frame["trade_date"].dt.date.between(start, end)
        & frame["touched"].fillna(False).astype(bool)
        & frame["prev_close"].gt(0)
        & frame["limit_price"].gt(0)
    ]
    records: list[dict[str, object]] = []
    for row in signal_rows.to_dict("records"):
        lane = _daily_proxy_lane(row)
        if lane is None:
            continue
        trade_date = _as_date(row.get("trade_date"))
        if trade_date is None:
            continue
        financial_snapshot = financial_snapshot_as_of(
            financial_index,
            str(row.get("vt_symbol") or ""),
            trade_date,
        )
        financial_risk = financial_risk_as_of(
            financial_index,
            str(row.get("vt_symbol") or ""),
            trade_date,
        )
        reasons = daily_structural_rejection_reasons(
            row,
            lane=lane,
            financial_snapshot=financial_snapshot,
            financial_risk=financial_risk,
        )
        entry_price = _number(row.get("limit_price"))
        exit_price = _number(row.get("next_close_price"))
        outcome = (
            cash_backtest.calculate_round_trip_outcome(
                entry_price,
                exit_price,
                limit_price=entry_price,
            )
            if entry_price is not None and exit_price is not None
            else None
        )
        records.append(
            {
                **row,
                "trade_date": trade_date,
                "result_date": _as_date(row.get("next_trade_date")),
                "lane": lane,
                "entry_price": entry_price,
                "return_pct": _number((outcome or {}).get("net_return_pct")),
                "outcome_sealed": bool(row.get("sealed")),
                "financial_snapshot": financial_snapshot,
                "financial_risk": financial_risk,
                "daily_structural_eligible": not reasons,
                "daily_structural_rejection_reasons": reasons,
                "signal_time": None,
                "execution_confidence": "daily_touch_proxy_without_time_or_queue",
                "candidate_scope": "daily_close_proxy",
                "proxy_contract": PROXY_CONTRACT,
            }
        )
    if not records:
        return pd.DataFrame()
    result = pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "lane", "vt_symbol"], kind="stable"
    )
    market_trade_dates = sorted(
        value
        for value in pd.to_datetime(feature_frame["trade_date"], errors="coerce")
        .dt.date.dropna()
        .unique()
        if start <= value <= end
    )
    return attach_causal_stock_profitability(
        result.reset_index(drop=True),
        trade_dates=market_trade_dates,
    )


def daily_structural_rejection_reasons(
    candidate: Mapping[str, object],
    *,
    lane: str,
    financial_snapshot: Mapping[str, object] | None,
    financial_risk: Mapping[str, object],
) -> list[str]:
    """Apply only gates reproducible from D open and D-1 daily evidence."""

    reasons: list[str] = []
    if bool(financial_risk.get("blocked")):
        reasons.append("fundamental_risk")
    if lane == "first_board":
        reasons.extend(_first_board_rejection_reasons(candidate, financial_snapshot))
    else:
        reasons.extend(_two_to_three_rejection_reasons(candidate, financial_snapshot))
    return list(dict.fromkeys(reasons))


def attach_causal_stock_profitability(
    frame: pd.DataFrame,
    *,
    trade_dates: Sequence[date] | None = None,
) -> pd.DataFrame:
    """Attach the existing stock-history gate using only matured prior outcomes."""

    if frame.empty:
        return frame.copy()
    result = frame.sort_values(["trade_date", "lane", "vt_symbol"], kind="stable").copy()
    candidate_dates = sorted(pd.to_datetime(result["trade_date"]).dt.date.unique())
    calendar = sorted(set(trade_dates or candidate_dates))
    missing_dates = set(candidate_dates) - set(calendar)
    if missing_dates:
        raise ValueError("candidate trade dates are missing from the market calendar")
    day_index = {trade_date: index for index, trade_date in enumerate(calendar)}
    pending: dict[date, list[dict[str, object]]] = defaultdict(list)
    history: dict[str, list[dict[str, object]]] = defaultdict(list)
    updates: dict[int, dict[str, object]] = {}

    for trade_date in candidate_dates:
        for result_date in sorted(value for value in pending if value < trade_date):
            for event in pending.pop(result_date):
                history[str(event["vt_symbol"])].append(event)
        current_index = day_index[trade_date]
        dated = result.loc[pd.to_datetime(result["trade_date"]).dt.date.eq(trade_date)]
        for row_index, row in dated.iterrows():
            lane = str(row.get("lane") or "")
            if lane != "first_board":
                updates[row_index] = {
                    "stock_d1_sample_count": None,
                    "stock_d1_win_rate": None,
                    "stock_gene_combined_win_rate": None,
                    "profitability_gate_passed": True,
                    "profitability_gate_reason": "not_first_board",
                }
                continue
            prior_events = [
                event
                for event in history.get(str(row.get("vt_symbol") or ""), [])
                if int(event["signal_day_index"])
                >= current_index - STOCK_HISTORY_WINDOW_SESSIONS
            ]
            sample_count = len(prior_events)
            win_rate = (
                sum(bool(event["won"]) for event in prior_events) / sample_count * 100
                if sample_count
                else None
            )
            seal_rate = _number(row.get("prior_seal_success_rate_126"))
            combined_rate = (
                seal_rate * win_rate if seal_rate is not None and win_rate is not None else None
            )
            if sample_count < MINIMUM_STOCK_D1_SAMPLES:
                passed = False
                reason = f"same_stock_d1_samples_below_{MINIMUM_STOCK_D1_SAMPLES}"
            elif combined_rate is None or combined_rate < MINIMUM_STOCK_COMBINED_RATE:
                passed = False
                reason = f"same_stock_joint_rate_below_{MINIMUM_STOCK_COMBINED_RATE:g}"
            else:
                passed = True
                reason = "qualified"
            updates[row_index] = {
                "stock_d1_sample_count": sample_count,
                "stock_d1_win_rate": _rounded(win_rate),
                "stock_gene_combined_win_rate": _rounded(combined_rate),
                "profitability_gate_passed": passed,
                "profitability_gate_reason": reason,
            }

        for row in dated.to_dict("records"):
            result_date = _as_date(row.get("result_date"))
            return_pct = _number(row.get("return_pct"))
            if (
                str(row.get("lane") or "") == "first_board"
                and bool(row.get("daily_structural_eligible"))
                and bool(row.get("outcome_sealed"))
                and result_date is not None
                and return_pct is not None
            ):
                pending[result_date].append(
                    {
                        "vt_symbol": str(row.get("vt_symbol") or ""),
                        "signal_day_index": current_index,
                        "won": return_pct > 0,
                    }
                )

    for row_index, values in updates.items():
        for field, value in values.items():
            result.at[row_index, field] = value
    return result.reset_index(drop=True)


def evaluate_daily_proxy(frame: pd.DataFrame) -> dict[str, object]:
    """Report each pool and its incremental complement independently."""

    if frame.empty:
        return {}
    normalized = frame.copy()
    if "signal_time" not in normalized:
        normalized["signal_time"] = "daily_proxy"
    else:
        normalized["signal_time"] = normalized["signal_time"].fillna("daily_proxy")
    if "pool_rank" not in normalized:
        normalized["pool_rank"] = 0
    structural_mask = normalized["daily_structural_eligible"].fillna(False).astype(bool)
    profitability_mask = normalized["profitability_gate_passed"].fillna(False).astype(bool)
    pools = {
        "daily_structural": structural_mask,
        "daily_structural_and_stock_profitability": structural_mask & profitability_mask,
    }
    evaluations: dict[str, object] = {}
    for pool_name, pool_mask in pools.items():
        pool = normalized.loc[pool_mask].copy()
        masks = quality_rule_masks(pool)
        core_mask = masks["recognition_and_industry_expansion"].fillna(False)
        selected = pool.loc[core_mask]
        complement = pool.loc[~core_mask]
        before_real_events = pd.to_datetime(pool["trade_date"]).dt.date < REAL_EVENT_COVERAGE_START
        before_discovery = pd.to_datetime(pool["trade_date"]).dt.date < DISCOVERY_START
        evaluations[pool_name] = {
            "baseline": performance_summary(pool, baseline_count=len(pool)),
            "core": performance_summary(selected, baseline_count=len(pool)),
            "incremental_complement": performance_summary(
                complement, baseline_count=len(pool)
            ),
            "recognition_only": performance_summary(
                pool.loc[masks["recognition_2_to_6"].fillna(False)],
                baseline_count=len(pool),
            ),
            "industry_expansion_only": performance_summary(
                pool.loc[masks["industry_turnover_expansion"].fillna(False)],
                baseline_count=len(pool),
            ),
            "core_before_real_event_coverage": performance_summary(
                pool.loc[core_mask & before_real_events], baseline_count=len(pool)
            ),
            "core_before_discovery": performance_summary(
                pool.loc[core_mask & before_discovery], baseline_count=len(pool)
            ),
            "core_observed_event_period": performance_summary(
                pool.loc[core_mask & ~before_real_events], baseline_count=len(pool)
            ),
            "core_monthly": monthly_summaries(selected),
            "core_by_year": {
                str(year): performance_summary(rows, baseline_count=len(pool))
                for year, rows in selected.groupby(
                    pd.to_datetime(selected["trade_date"]).dt.year, sort=True
                )
            },
            "core_by_lane": {
                str(lane): performance_summary(rows, baseline_count=len(pool))
                for lane, rows in selected.groupby("lane", sort=True)
            },
        }
    return {"study_version": STUDY_VERSION, "pools": evaluations}


def render_daily_proxy_report(
    frame: pd.DataFrame,
    evaluation: Mapping[str, object],
    coverage: Mapping[str, object],
    *,
    start: date,
    end: date,
) -> str:
    pools = _mapping(evaluation.get("pools"))
    lines = [
        "# AlphaAgent 打板质量 806 日日线代理扩容验证",
        "",
        "## Current state",
        "",
        f"- 研究版本：`{STUDY_VERSION}`；代理合同：`{PROXY_CONTRACT}`。",
        f"- 行情区间：`{start}..{end}`；可靠交易日 `{coverage.get('reliable_trade_days')}`；载入回看起点 `{coverage.get('load_start')}`。",
        f"- 真实涨停事件从 `{REAL_EVENT_COVERAGE_START}` 开始；此前不伪造触板时间，只用日线最高价触板代理。",
        "- 入场价为涨停价、退出为 D+1 官方收盘并使用正式费用；不模拟排队成交率。",
        "- 股票名、概念名和月份不进入规则；财报严格取信号日前已公告报告。",
        f"- 原质量规则保持为 `{MINIMUM_PRIOR_LIMIT_COUNT_126}-{MAXIMUM_PRIOR_LIMIT_COUNT_126}` 次半年涨停且 D-1 行业量能/5日 `>= {MINIMUM_PRIOR_INDUSTRY_TURNOVER_RATIO_5D:.1f}`。",
        f"- 日线触板候选 `{len(frame)}` 个；结果只用于检验规律是否跨历史成立，不替代正式可成交账本。",
        "",
        "## Pool results",
        "",
        "| 母池 | 母池闭合 | 核心规则闭合 | 保留率 | 核心胜率 | 核心均值 | 核心回撤 | 未选组胜率 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "daily_structural": "D-1结构质量池",
        "daily_structural_and_stock_profitability": "结构池+同股历史盈利门",
    }
    for name, label in labels.items():
        result = _mapping(pools.get(name))
        baseline = _mapping(result.get("baseline"))
        core = _mapping(result.get("core"))
        complement = _mapping(result.get("incremental_complement"))
        lines.append(
            f"| {label} | {int(baseline.get('closed_count') or 0)} | {int(core.get('closed_count') or 0)} | "
            f"{_fmt(core.get('retention_pct'))}% | {_fmt(core.get('win_rate_pct'))}% | "
            f"{_signed(core.get('average_return_pct'))}% | {_signed(core.get('maximum_drawdown_pct'))}% | "
            f"{_fmt(complement.get('win_rate_pct'))}% |"
        )

    for name, label in labels.items():
        result = _mapping(pools.get(name))
        lines.extend(
            [
                "",
                f"## {label}",
                "",
                "| 分段 | 闭合 | 胜率 | 平均净收益 | 最大回撤 | 硬亏率 |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for key, segment_label in (
            ("baseline", "母池"),
            ("core", "2-6次+行业量能扩张"),
            ("incremental_complement", "核心规则以外"),
            ("core_before_real_event_coverage", "核心规则：真实事件覆盖前"),
            ("core_before_discovery", "核心规则：2026-03发现期前"),
            ("core_observed_event_period", "核心规则：真实事件覆盖期"),
        ):
            summary = _mapping(result.get(key))
            lines.append(_summary_row(segment_label, summary))
        lines.extend(
            [
                "",
                "### Year and lane",
                "",
                "| 分组 | 闭合 | 胜率 | 平均净收益 |",
                "|---|---:|---:|---:|",
            ]
        )
        for year, summary in _mapping(result.get("core_by_year")).items():
            lines.append(_short_summary_row(f"年份 {year}", _mapping(summary)))
        for lane, summary in _mapping(result.get("core_by_lane")).items():
            lines.append(_short_summary_row(f"lane {lane}", _mapping(summary)))

    lines.extend(
        [
            "",
            "## Decision boundary",
            "",
            "- 只有核心规则在真实事件覆盖前的独立日线历史也达到 60%，才说明它不是近一年 41 笔样本偶然。",
            "- 只有放宽后新增组自身达到 60%，才允许扩容；不得用原强组拉高合并胜率。",
            "- 日线代理通过后，真实交易仍要求盘中首次触板或回封、正式窗口和失败关闭；日线结果不证明成交。",
            "- 2026-07-27 起自然前向继续作为生产晋级的唯一未见验证。",
            "",
        ]
    )
    return "\n".join(lines)


def load_daily_proxy_inputs(
    *,
    start: date,
    end: date,
) -> tuple[pd.DataFrame, FinancialIndex, dict[str, object]]:
    frame, coverage = load_reliable_history_frame(
        evaluation_start=start,
        evaluation_end=end,
        lookback_sessions=LOOKBACK_SESSIONS,
    )
    with session_scope() as session:
        report_rows = [
            dict(row)
            for row in session.execute(select(schema.stock_financial_reports)).mappings()
        ]
    return build_daily_feature_frame(frame, copy_frame=False), build_financial_index(
        report_rows
    ), coverage


def _daily_proxy_lane(candidate: Mapping[str, object]) -> str | None:
    prior_streak = _integer(candidate.get("prior_streak"))
    recent_limits = _integer(candidate.get("prior_limit_count_5"))
    if prior_streak >= 3:
        return None
    if prior_streak == 2 or (prior_streak == 0 and recent_limits == 2):
        return "two_to_three"
    if prior_streak == 0:
        return "first_board"
    return None


def _first_board_rejection_reasons(
    candidate: Mapping[str, object],
    financial_snapshot: Mapping[str, object] | None,
) -> list[str]:
    reasons: list[str] = []
    limit_count = _integer(candidate.get("prior_limit_count_126"))
    touch_count = _integer(candidate.get("prior_touch_count_126"))
    if limit_count < 1:
        reasons.append("limit_up_gene_missing")
    if touch_count < FIRST_BOARD_MINIMUM_TOUCH_COUNT:
        reasons.append("first_board_touch_gene_weak")
    short_cycle_return = _short_cycle_return_board(candidate)
    if _integer(candidate.get("prior_limit_count_5")) > 0 and not short_cycle_return:
        reasons.append("not_first_board_after_cooling")
    position = _number(candidate.get("prior_position_120"))
    pullback = _number(candidate.get("pullback_from_prior_limit_pct"))
    days_since = _number(candidate.get("trade_days_since_prior_limit"))
    low_position = position is not None and position <= 0.55
    cooled = (
        pullback is not None
        and pullback <= -8
        and days_since is not None
        and days_since >= 5
    )
    if not (low_position or cooled or short_cycle_return):
        reasons.append("low_position_missing")
    seal_rate = _number(candidate.get("prior_seal_success_rate_126"))
    if seal_rate is None or seal_rate < 0.35:
        reasons.append("historical_seal_gene_weak")
    if _number(candidate.get("prior_industry_heat_score")) is None:
        reasons.append("industry_heat_unavailable")
    net_profit_yoy = _number((financial_snapshot or {}).get("net_profit_yoy"))
    if net_profit_yoy is None:
        reasons.append("financial_report_unavailable")
    elif net_profit_yoy < FIRST_BOARD_MINIMUM_NET_PROFIT_YOY:
        reasons.append("first_board_profit_growth_weak")
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    if failed_rate is None or failed_rate < 0.35:
        reasons.append("first_board_repair_setup_missing")
    return reasons


def _two_to_three_rejection_reasons(
    candidate: Mapping[str, object],
    financial_snapshot: Mapping[str, object] | None,
) -> list[str]:
    reasons: list[str] = []
    gap = _number(candidate.get("auction_gap_pct"))
    turnover = _number(candidate.get("prior_turnover_rate"))
    amount = _number(candidate.get("prior_amount_ratio_5d"))
    if gap is None or not 1 <= gap <= 6:
        reasons.append("auction_gap_out_of_range")
    if turnover is not None and not 3 <= turnover <= 28:
        reasons.append("prior_turnover_extreme")
    if amount is not None and not 0.7 <= amount <= 4:
        reasons.append("prior_volume_structure_extreme")
    phase = str(candidate.get("prior_market_phase") or "unknown")
    if phase in {"retreat", "ice", "decline"}:
        reasons.append("market_retreat")
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    if failed_rate is not None and failed_rate > 0.45:
        reasons.append("market_failed_rate_high")
    heat = _number(candidate.get("prior_industry_heat_score"))
    if heat is not None and heat < 50:
        reasons.append("industry_not_hot")
    heat_rank = _integer_or_none(candidate.get("prior_industry_heat_rank"))
    industry_count = _integer_or_none(candidate.get("prior_industry_count"))
    if heat_rank is not None and industry_count and heat_rank > max(
        8, round(industry_count * 0.3)
    ):
        reasons.append("industry_not_front")
    leader_rank = _integer_or_none(candidate.get("prior_industry_leader_rank"))
    if leader_rank is None or leader_rank > 2:
        reasons.append("stock_not_industry_top2")
    amplitude = _number(candidate.get("prior_amplitude_pct"))
    prior_low = _number(candidate.get("prior_low_change_pct"))
    weak_to_strong = bool(
        (amplitude is not None and amplitude >= 6)
        or (prior_low is not None and prior_low < 0)
    ) and gap is not None and gap >= 1.5
    daily_consensus = bool(
        _integer(candidate.get("prior_streak")) >= 2
        and prior_low is not None
        and prior_low >= 0
        and gap is not None
        and 1 <= gap <= 5
    )
    if not (weak_to_strong or daily_consensus):
        reasons.append("third_board_daily_setup_unconfirmed")
    promotion = _number(candidate.get("prior_market_two_to_three_rate"))
    if promotion is not None and promotion < 0.12:
        reasons.append("two_to_three_market_success_low")
    risks = (
        int(not (gap is not None and 2 <= gap < 5))
        + int(not (turnover is not None and 10 <= turnover < 20))
        + int(not (amount is not None and 1.2 <= amount < 2))
        + int(financial_snapshot is None)
        + int(not (prior_low is not None and prior_low >= 0))
        + int(not (failed_rate is not None and failed_rate < 0.35))
    )
    if risks >= 4:
        reasons.append("two_to_three_risk_stack")
    return reasons


def _short_cycle_return_board(candidate: Mapping[str, object]) -> bool:
    days_since = _number(candidate.get("trade_days_since_prior_limit"))
    pullback = _number(candidate.get("pullback_from_prior_limit_pct"))
    prior_change = _number(candidate.get("prior_change_pct"))
    gap = _number(candidate.get("auction_gap_pct"))
    return bool(
        _integer(candidate.get("prior_streak")) == 0
        and _integer(candidate.get("prior_limit_count_5")) == 1
        and days_since is not None
        and 2 <= days_since <= 4
        and pullback is not None
        and pullback <= -8
        and prior_change is not None
        and prior_change < 0
        and gap is not None
        and 1 <= gap <= 7
    )


def _summary_row(label: str, summary: Mapping[str, object]) -> str:
    return (
        f"| {label} | {int(summary.get('closed_count') or 0)} | "
        f"{_fmt(summary.get('win_rate_pct'))}% | {_signed(summary.get('average_return_pct'))}% | "
        f"{_signed(summary.get('maximum_drawdown_pct'))}% | {_fmt(summary.get('hard_loss_rate_pct'))}% |"
    )


def _short_summary_row(label: str, summary: Mapping[str, object]) -> str:
    return (
        f"| {label} | {int(summary.get('closed_count') or 0)} | "
        f"{_fmt(summary.get('win_rate_pct'))}% | {_signed(summary.get('average_return_pct'))}% |"
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_date(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and pd.notna(number) else None


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _integer_or_none(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _rounded(value: object) -> float | None:
    number = _number(value)
    return round(number, 4) if number is not None else None


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _signed(value: object) -> str:
    number = _number(value)
    return f"{number:+.4f}" if number is not None else "-"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    features, financials, coverage = load_daily_proxy_inputs(
        start=arguments.start,
        end=arguments.end,
    )
    frame = build_daily_proxy_frame(
        features,
        financials,
        start=arguments.start,
        end=arguments.end,
    )
    evaluation = evaluate_daily_proxy(frame)
    report = render_daily_proxy_report(
        frame,
        evaluation,
        coverage,
        start=arguments.start,
        end=arguments.end,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
