"""Attrition study from dynamic-leader support touches to executed trades."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import pandas as pd
import numpy as np

from .causal_leader_pullback import (
    GOLD_STRONG_RECLAIM_MAX_PEAK_GAP_PCT,
    GOLD_STRONG_RECLAIM_RETURN_PCT,
    SUPPORT_TOLERANCE_PCT,
)


STUDY_VERSION = "leader-pullback-opportunity-funnel-v1"
ROUND_TRIP_COST_PCT = 0.2


def build_support_touch_opportunities(
    daily_ledger: pd.DataFrame,
    leader_paths: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Extract same-day required-support touches without confirmation outcomes."""

    required_daily = {
        "campaign_id", "vt_symbol", "trade_date", "state", "wave_number",
        "required_support", "deepest_tested_support", "latest_support_test_date", "dynamic_rank",
        "dynamic_top3", "structure_intact",
    }
    required_paths = {
        "campaign_id", "sector_id", "concept_name", "vt_symbol", "stock_name",
        "trade_date", "campaign_active", "close_price", "low_price", "ma5", "ma10",
    }
    _require_columns(daily_ledger, required_daily, "daily ledger")
    _require_columns(leader_paths, required_paths, "leader paths")
    daily = daily_ledger.copy()
    paths = leader_paths.copy()
    for frame in (daily, paths):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    daily["latest_support_test_date"] = pd.to_datetime(
        daily["latest_support_test_date"], errors="coerce"
    ).dt.normalize()
    merged = daily.merge(
        paths.loc[:, sorted(required_paths)],
        on=["campaign_id", "vt_symbol", "trade_date"],
        how="left", validate="one_to_one", sort=False,
    )
    required_support_price = pd.Series(
        np.where(merged["required_support"].eq("ma5"), merged["ma5"],
                 np.where(merged["required_support"].eq("ma10"), merged["ma10"], np.nan)),
        index=merged.index,
        dtype=float,
    )
    selected = (
        merged["state"].eq("pullback")
        & merged["campaign_active"].fillna(False).astype(bool)
        & merged["dynamic_top3"].astype(bool)
        & merged["structure_intact"].astype(bool)
        & merged["required_support"].isin(["ma5", "ma10"])
        & merged["deepest_tested_support"].eq(merged["required_support"])
        & merged["latest_support_test_date"].eq(merged["trade_date"])
        & merged["low_price"].le(required_support_price)
    )
    result = merged.loc[selected].copy().sort_values("trade_date", kind="stable")
    result["support_line"] = result["required_support"]
    result["entry_date"] = result["trade_date"]
    result["entry_price"] = pd.to_numeric(result["close_price"], errors="coerce")
    result["opportunity_id"] = (
        result["campaign_id"].astype(str) + ":" + result["vt_symbol"].astype(str)
        + ":" + result["trade_date"].dt.strftime("%Y-%m-%d")
        + ":" + result["support_line"].astype(str)
    )
    if result["opportunity_id"].duplicated().any():
        raise ValueError("support-touch opportunity identities must be unique")
    return attach_d1_returns(result, stock_bars)


def attach_d1_returns(opportunities: pd.DataFrame, stock_bars: pd.DataFrame) -> pd.DataFrame:
    """Attach the next available session close without changing selection."""

    _require_columns(stock_bars, {"vt_symbol", "trade_date", "close_price"}, "stock bars")
    result = opportunities.copy()
    bars = stock_bars.loc[:, ["vt_symbol", "trade_date", "close_price"]].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    bars["d1_date"] = bars.groupby("vt_symbol", sort=False)["trade_date"].shift(-1)
    bars["d1_close"] = bars.groupby("vt_symbol", sort=False)["close_price"].shift(-1)
    lookup = bars.rename(columns={"trade_date": "entry_date"})[
        ["vt_symbol", "entry_date", "d1_date", "d1_close"]
    ]
    result = result.merge(lookup, on=["vt_symbol", "entry_date"], how="left", validate="many_to_one")
    result["d1_net_return_pct"] = (
        (pd.to_numeric(result["d1_close"], errors="coerce") / result["entry_price"] - 1.0)
        * 100.0 - ROUND_TRIP_COST_PCT
    )
    return result


def attach_funnel_attribution(
    opportunities: pd.DataFrame,
    signals: pd.DataFrame,
    raw_trades: pd.DataFrame,
    non_overlapping_trades: pd.DataFrame,
    *,
    allowed_phases: Sequence[str] = ("rotation", "warming"),
    capacity: int = 2,
) -> pd.DataFrame:
    """Assign every support touch one deepest reached stage and terminal reason."""

    result = opportunities.copy()
    confirmations = signals.copy()
    confirmations["support_test_date"] = pd.to_datetime(
        confirmations["support_test_date"], errors="coerce"
    ).dt.normalize()
    confirmations = confirmations.sort_values(["support_test_date", "signal_date", "signal_id"])
    confirmations = confirmations.drop_duplicates(
        ["campaign_id", "vt_symbol", "support_test_date", "required_support"], keep="first"
    )
    result = result.merge(
        confirmations.rename(columns={"support_test_date": "entry_date"})[
            ["campaign_id", "vt_symbol", "entry_date", "required_support", "signal_id",
             "signal_date", "signal_daily_return_pct", "signal_close", "reference_peak_price",
             "market_phase", "active_direction", "danger_state", "signal_low", "support_price"]
        ],
        on=["campaign_id", "vt_symbol", "entry_date", "required_support"],
        how="left", validate="one_to_one",
    )
    result["confirmed"] = result["signal_id"].notna()
    result["strong_reclaim"] = (
        result["confirmed"]
        & pd.to_numeric(result["signal_daily_return_pct"], errors="coerce").ge(GOLD_STRONG_RECLAIM_RETURN_PCT)
        & pd.to_numeric(result["signal_close"], errors="coerce").ge(
            pd.to_numeric(result["reference_peak_price"], errors="coerce")
            * (1.0 - GOLD_STRONG_RECLAIM_MAX_PEAK_GAP_PCT / 100.0)
        )
    )
    phase = result["market_phase"].astype(str)
    timing_allowed = (
        result["active_direction"].astype(str).eq("GOLD")
        & result["danger_state"].astype(str).eq("NORMAL")
    )
    support_held = pd.to_numeric(result["signal_low"], errors="coerce").ge(
        pd.to_numeric(result["support_price"], errors="coerce")
        * (1.0 - SUPPORT_TOLERANCE_PCT / 100.0)
    )
    result["phase_allowed"] = (
        result["strong_reclaim"] & timing_allowed
        & (phase.eq("rotation") | (phase.eq("warming") & support_held))
        & phase.isin(allowed_phases)
    )
    raw_ids = set(raw_trades.get("signal_id", pd.Series(dtype=str)).astype(str))
    kept_ids = set(non_overlapping_trades.get("signal_id", pd.Series(dtype=str)).astype(str))
    result["raw_trade"] = result["signal_id"].astype(str).isin(raw_ids) & result["phase_allowed"]
    result["non_overlapping"] = result["signal_id"].astype(str).isin(kept_ids) & result["raw_trade"]
    accepted_ids = _select_capacity_ids(non_overlapping_trades, capacity=capacity)
    result["two_slot_accepted"] = result["signal_id"].astype(str).isin(accepted_ids) & result["non_overlapping"]
    conditions = [
        (~result["confirmed"], "no_next_day_confirmation"),
        (~result["strong_reclaim"], "missed_by_8pct_reclaim"),
        (~result["phase_allowed"], "missed_by_market_phase"),
        (~result["raw_trade"], "not_executed_by_trade_state"),
        (~result["non_overlapping"], "skipped_by_non_overlap"),
        (~result["two_slot_accepted"], "skipped_by_two_slot_capacity"),
    ]
    result["terminal_reason"] = "two_slot_trade"
    unresolved = pd.Series(True, index=result.index)
    for mask, reason in conditions:
        chosen = unresolved & mask
        result.loc[chosen, "terminal_reason"] = reason
        unresolved &= ~chosen
    trade_outcomes = raw_trades.drop_duplicates("signal_id").loc[:, [
        column for column in ("signal_id", "exit_date", "exit_reason", "net_return_pct")
        if column in raw_trades.columns
    ]]
    return result.merge(trade_outcomes, on="signal_id", how="left", validate="many_to_one")


def summarize_funnel(ledger: pd.DataFrame) -> dict[str, Any]:
    stages = (
        "parent", "confirmed", "strong_reclaim", "phase_allowed",
        "raw_trade", "non_overlapping", "two_slot_accepted",
    )
    summary: dict[str, Any] = {"study_version": STUDY_VERSION, "stages": {}}
    for stage in stages:
        frame = ledger if stage == "parent" else ledger.loc[ledger[stage].astype(bool)]
        returns = pd.to_numeric(frame.get("d1_net_return_pct"), errors="coerce").dropna()
        summary["stages"][stage] = {
            "opportunities": int(len(frame)),
            "symbols": int(frame["vt_symbol"].nunique()),
            "dates": int(frame["entry_date"].nunique()),
            "d1_closed": int(len(returns)),
            "d1_win_rate_pct": float(returns.gt(0).mean() * 100) if len(returns) else None,
            "d1_mean_return_pct": float(returns.mean()) if len(returns) else None,
        }
    summary["terminal_reasons"] = ledger["terminal_reason"].value_counts().sort_index().to_dict()
    return summary


def run_opportunity_funnel_study(
    *, start: date = date(2024, 8, 1), end: date | None = None
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Run one bounded replay and return its compact funnel plus evidence ledger."""

    from .causal_leader_pullback_study import (
        CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
        build_causal_stock_features,
        build_concept_campaign_ledger,
        build_dynamic_leader_paths,
        load_causal_leader_pullback_inputs,
        replay_dynamic_leader_paths,
        select_non_overlapping_trades,
    )

    inputs = load_causal_leader_pullback_inputs()
    features = build_causal_stock_features(inputs.stock_bars)
    _, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    leader_paths, coverage = build_dynamic_leader_paths(
        campaign_paths, inputs.memberships, features
    )
    replay = replay_dynamic_leader_paths(leader_paths, inputs.market_timing)
    opportunities = build_support_touch_opportunities(
        replay.daily_ledger, leader_paths, features
    )
    end_date = pd.Timestamp(end or opportunities["entry_date"].max()).normalize()
    opportunities = opportunities.loc[
        opportunities["entry_date"].between(pd.Timestamp(start), end_date)
    ].reset_index(drop=True)
    raw = replay.trades.loc[
        replay.trades["variant"].eq(CROSS_REGIME_SUPPORT_RECLAIM_VARIANT)
    ].copy()
    selected = select_non_overlapping_trades(raw)
    ledger = attach_funnel_attribution(
        opportunities, replay.signals, raw, selected, capacity=2
    )
    report = summarize_funnel(ledger)
    report.update({
        "period": {"start": str(start), "end": end_date.date().isoformat()},
        "coverage": coverage,
        "months": _month_breakdown(ledger),
        "named_cases": _named_cases(ledger),
        "boundaries": [
            "Current concept memberships are replayed backward and create survivorship bias.",
            "All entries and outcomes use completed daily closes; no minute or fund-flow data is used.",
            "This is reused exploratory history, not untouched forward validation.",
        ],
    })
    return report, ledger


def render_funnel_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# 低吸主升龙头回踩机会漏斗研究",
        "",
        f"- 版本：`{report['study_version']}`",
        f"- 区间：{report['period']['start']} 至 {report['period']['end']}",
        "",
        "## 核心漏斗",
        "",
        "| 层级 | 机会数 | 股票数 | 日期数 | D+1胜率 | D+1均值 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "parent": "动态Top3主升 MA5/MA10 首次回踩",
        "confirmed": "后续确认",
        "strong_reclaim": "8%且接近前高",
        "phase_allowed": "rotation/warming 行情门",
        "raw_trade": "原始策略交易",
        "non_overlapping": "个股非重叠",
        "two_slot_accepted": "两仓成交",
    }
    for key, row in report["stages"].items():
        win = "-" if row["d1_win_rate_pct"] is None else f"{row['d1_win_rate_pct']:.2f}%"
        mean = "-" if row["d1_mean_return_pct"] is None else f"{row['d1_mean_return_pct']:.3f}%"
        lines.append(
            f"| {labels[key]} | {row['opportunities']} | {row['symbols']} | "
            f"{row['dates']} | {win} | {mean} |"
        )
    lines.extend(["", "## 最终去向", ""])
    for reason, count in report["terminal_reasons"].items():
        lines.append(f"- `{reason}`: {count}")
    lines.extend(["", "## 月度母集合与成交", "", "| 月份 | 母集合 | 两仓成交 |", "|---|---:|---:|"])
    for row in report["months"]:
        lines.append(f"| {row['month']} | {row['parent']} | {row['two_slot_trade']} |")
    lines.extend(["", "## 指定个股", ""])
    for row in report["named_cases"]:
        lines.append(
            f"- {row['stock_name']}（{row['vt_symbol']}）：母集合 {row['parent']}，两仓成交 {row['two_slot_trade']}"
        )
    lines.extend(["", "## 边界", ""])
    lines.extend(f"- {item}" for item in report["boundaries"])
    return "\n".join(lines) + "\n"


def _month_breakdown(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    if ledger.empty:
        return []
    frame = ledger.copy()
    frame["month"] = frame["entry_date"].dt.to_period("M").astype(str)
    months = pd.period_range(frame["entry_date"].min(), frame["entry_date"].max(), freq="M")
    return [
        {
            "month": str(month),
            "parent": int(frame["month"].eq(str(month)).sum()),
            "two_slot_trade": int(
                (frame["month"].eq(str(month)) & frame["two_slot_accepted"]).sum()
            ),
        }
        for month in months
    ]


def _named_cases(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    names = {"002384.SZSE": "东山精密", "002636.SZSE": "金安国纪", "600487.SSE": "亨通光电"}
    return [
        {
            "vt_symbol": symbol, "stock_name": name,
            "parent": int(ledger["vt_symbol"].eq(symbol).sum()),
            "two_slot_trade": int(
                (ledger["vt_symbol"].eq(symbol) & ledger["two_slot_accepted"]).sum()
            ),
        }
        for symbol, name in names.items()
    ]


def _select_capacity_ids(trades: pd.DataFrame, *, capacity: int) -> set[str]:
    if trades.empty:
        return set()
    frame = trades.copy()
    for column in ("entry_date", "exit_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    accepted: set[str] = set()
    positions: list[dict[str, Any]] = []
    for trade in frame.sort_values(["entry_date", "dynamic_rank", "signal_id"], kind="stable").to_dict("records"):
        entry = pd.Timestamp(trade["entry_date"])
        positions = [position for position in positions if pd.Timestamp(position["exit_date"]) > entry]
        if len(positions) >= capacity:
            continue
        if any(str(p["sector_id"]) == str(trade["sector_id"]) for p in positions):
            continue
        if any(str(p["vt_symbol"]) == str(trade["vt_symbol"]) for p in positions):
            continue
        accepted.add(str(trade["signal_id"]))
        positions.append(trade)
    return accepted


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")
