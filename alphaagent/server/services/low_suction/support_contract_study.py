"""Independent comparison of exact-support and deep-reclaim pullbacks."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from .causal_leader_pullback import (
    ALGORITHM_VERSION,
    EXACT_REQUIRED_SUPPORT,
    MINIMUM_REQUIRED_SUPPORT,
    ROUND_TRIP_COST_PCT,
    summarize_trade_metrics,
)
from .causal_leader_pullback_study import (
    CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
    ReplayResult,
    build_causal_stock_features,
    build_concept_campaign_ledger,
    build_dynamic_leader_paths,
    build_named_case_audit,
    load_causal_leader_pullback_inputs,
    replay_dynamic_leader_paths,
    select_non_overlapping_trades,
    simulate_four_slot_cash,
)
from .dynamic_concept_campaign import MEMBERSHIP_EVIDENCE_LEVEL


STUDY_VERSION = "low-suction-support-contract-study-v1"
POLICY_VERSION = "causal-leader-pullback-support-contract-v4"
DEEP_RECLAIM_VARIANT = "cross_regime_deep_reclaim"
EXACT_SUPPORT_VARIANT = "cross_regime_exact_ma5_ma10"
VARIANTS = (DEEP_RECLAIM_VARIANT, EXACT_SUPPORT_VARIANT)
SUPPORT_MODE_BY_VARIANT = {
    DEEP_RECLAIM_VARIANT: MINIMUM_REQUIRED_SUPPORT,
    EXACT_SUPPORT_VARIANT: EXACT_REQUIRED_SUPPORT,
}

MIN_CLOSED_TRADES = 100
MIN_BLOCK_TRADES = 15
MIN_STABLE_BLOCKS = 3
MIN_PHASE_TRADES = 30
MIN_QUALIFIED_PHASES = 2
MIN_WIN_RATE_PCT = 60.0
MIN_PROFIT_FACTOR = 1.20
MIN_CASH_COMPOUND_PCT = 60.0
MIN_CASH_DRAWDOWN_PCT = -10.0


def replay_support_contracts(
    leader_paths: pd.DataFrame,
    market_timing: pd.DataFrame,
) -> dict[str, ReplayResult]:
    """Run each support contract through its own campaign state machine."""

    return {
        variant: replay_dynamic_leader_paths(
            leader_paths,
            market_timing,
            support_match_mode=support_mode,
        )
        for variant, support_mode in SUPPORT_MODE_BY_VARIANT.items()
    }


def collect_selected_policy_evidence(
    replays: Mapping[str, ReplayResult],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collect the phase-routed output of each independent replay."""

    signal_parts: list[pd.DataFrame] = []
    trade_parts: list[pd.DataFrame] = []
    for variant in VARIANTS:
        replay = replays[variant]
        selected_signals = _selected_signals(replay.signals).assign(variant=variant)
        signal_parts.append(selected_signals)
        selected_trades = _selected_trades(replay.trades).assign(variant=variant)
        trade_parts.append(_attach_signal_context(selected_trades, selected_signals))

    signals = _concat(signal_parts)
    raw_trades = _concat(trade_parts)
    return signals, select_non_overlapping_trades(raw_trades)


def build_support_named_case_audit(
    leader_paths: pd.DataFrame,
    replays: Mapping[str, ReplayResult],
    selected_signals: pd.DataFrame,
    selected_trades: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Keep compact stock-by-stock wave evidence for both support contracts."""

    rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        replay = replays[variant]
        audit = build_named_case_audit(
            leader_paths,
            _variant_rows(selected_signals, variant),
            _variant_rows(selected_trades, variant),
            replay.waves,
            replay.daily_ledger,
        )
        rows.extend({"variant": variant, **dict(item)} for item in audit)
    return rows


def _selected_signals(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty or CROSS_REGIME_SUPPORT_RECLAIM_VARIANT not in signals:
        return signals.iloc[0:0].copy()
    selected = signals[CROSS_REGIME_SUPPORT_RECLAIM_VARIANT].astype(bool)
    return signals.loc[selected].copy()


def _selected_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "variant" not in trades:
        return trades.iloc[0:0].copy()
    return trades.loc[
        trades["variant"].astype(str).eq(CROSS_REGIME_SUPPORT_RECLAIM_VARIANT)
    ].copy()


def _attach_signal_context(
    trades: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    context_columns = [
        column
        for column in (
            "variant",
            "signal_id",
            "stock_name",
            "concept_name",
            "signal_date",
            "required_support",
            "signal_daily_return_pct",
            "support_test_session_gap",
            "reference_peak_price",
            "signal_close",
            "active_direction",
            "danger_state",
            "market_phase",
        )
        if column in signals
    ]
    context = signals.loc[:, context_columns].copy()
    identity = ["variant", "signal_id"]
    if context.duplicated(identity).any():
        raise ValueError("selected signal identities must be unique")
    duplicate_context = [
        column for column in context_columns if column in trades and column not in identity
    ]
    return trades.drop(columns=duplicate_context).merge(
        context,
        on=identity,
        how="left",
        validate="many_to_one",
        sort=False,
    )


def evaluate_support_contract(
    variant: str,
    trades: pd.DataFrame,
    cash_result: Mapping[str, Any],
    *,
    strict_membership_rows: int,
) -> dict[str, Any]:
    """Evaluate fixed historical-proxy and formal evidence gates."""

    selected = _variant_rows(trades, variant)
    overall = _metric_summary(selected)
    failed: list[str] = []
    if int(overall["closed_trades"]) < MIN_CLOSED_TRADES:
        failed.append("closed_trades<100")
    if float(overall["win_rate_pct"] or 0.0) <= MIN_WIN_RATE_PCT:
        failed.append("win_rate<=60pct")
    if float(overall["mean_net_return_pct"] or 0.0) <= 0.0:
        failed.append("mean_return<=0")
    if float(overall["profit_factor"] or 0.0) < MIN_PROFIT_FACTOR:
        failed.append("profit_factor<1.2")

    block_metrics = _single_variant_group_metrics(selected, "time_block")
    stable_blocks = sum(
        int(row["closed_trades"]) >= MIN_BLOCK_TRADES
        and float(row["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
        and float(row["mean_net_return_pct"] or 0.0) > 0.0
        for row in block_metrics
    )
    if stable_blocks < MIN_STABLE_BLOCKS:
        failed.append("stable_time_blocks<3")

    if float(cash_result.get("compound_return_pct") or 0.0) <= MIN_CASH_COMPOUND_PCT:
        failed.append("cash_compound<=60pct")
    cash_drawdown = _finite_or_none(cash_result.get("maximum_drawdown_pct"))
    if (cash_drawdown if cash_drawdown is not None else -100.0) < MIN_CASH_DRAWDOWN_PCT:
        failed.append("cash_drawdown<-10pct")

    phase_metrics = _single_variant_group_metrics(selected, "market_phase")
    qualified_phases = sorted(
        str(row["group"])
        for row in phase_metrics
        if int(row["closed_trades"]) >= MIN_PHASE_TRADES
        and float(row["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
        and float(row["compound_return_pct"] or 0.0) > 0.0
    )
    if len(qualified_phases) < MIN_QUALIFIED_PHASES:
        failed.append("qualified_market_phases<2")

    formal_blockers = ["same_close_execution_is_research_proxy"]
    if strict_membership_rows == 0:
        formal_blockers.insert(0, "strict_historical_membership_missing")
    historical_passed = not failed
    return {
        "variant": variant,
        "status": (
            "historical_proxy_gate_passed_formal_blocked"
            if historical_passed
            else "historical_proxy_gate_failed"
        ),
        "historical_proxy_gate_passed": historical_passed,
        "stable_time_blocks": int(stable_blocks),
        "qualified_market_phases": qualified_phases,
        "wilson_95_lower_win_rate_pct": _wilson_lower_bound_pct(
            int(overall["winning_trades"]), int(overall["closed_trades"])
        ),
        "failed_gates": failed,
        "formal_blockers": formal_blockers,
    }


def build_support_contract_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
    selected_signals: pd.DataFrame,
    selected_trades: pd.DataFrame,
    cash_results: Mapping[str, Mapping[str, Any]],
    named_case_audit: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the concise v4 comparison without promoting proxy metrics."""

    trades = selected_trades.copy()
    if not trades.empty:
        trades["support_path"] = (
            trades.get("required_support", pd.Series(index=trades.index, dtype=str))
            .fillna("unknown")
            .astype(str)
            + "->"
            + trades.get("support_line", pd.Series(index=trades.index, dtype=str))
            .fillna("unknown")
            .astype(str)
        )
        trades["calendar_year"] = pd.to_datetime(
            trades["entry_date"], errors="coerce"
        ).dt.year.astype("Int64").astype(str)
        trades["symbol_group"] = _named_group(trades, "vt_symbol", "stock_name")
        trades["concept_group"] = _named_group(trades, "sector_id", "concept_name")

    strict_rows = int(coverage.get("strict_historical_membership_rows") or 0)
    qualification = {
        variant: evaluate_support_contract(
            variant,
            trades,
            cash_results.get(variant, {}),
            strict_membership_rows=strict_rows,
        )
        for variant in VARIANTS
    }
    report = {
        "study_version": STUDY_VERSION,
        "signal_algorithm_version": ALGORITHM_VERSION,
        "policy_version": POLICY_VERSION,
        "research_status": "historical_proxy_support_contracts_compared",
        "formal_strategy": False,
        "formal_metrics": None,
        "contract": {
            "universe": "dynamic concept Top3; eligible SSE/SZSE main board; no ST",
            "main_rise": "same causal concept campaign and daily dynamic leader rank as v3",
            "confirmation": (
                "GOLD/NORMAL strong reclaim; rotation trades directly; warming also "
                "holds the tested support tolerance"
            ),
            "entry": "D completed close same_close_research_proxy",
            "exit": "D+1 non-profit exit; otherwise higher high or structural exit",
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "variants": {
                DEEP_RECLAIM_VARIANT: (
                    "minimum required depth: wave 1 tests at least MA5 and later waves "
                    "test at least MA10; a deeper MA10/MA20 test controls confirmation"
                ),
                EXACT_SUPPORT_VARIANT: (
                    "exact required depth: wave 1 deepest tested support must be MA5 and "
                    "later-wave deepest tested support must be MA10"
                ),
            },
            "market_policy": {
                "rotation": "trade strong reclaim",
                "warming": "trade strong reclaim only when confirmation low holds support floor",
                "uptrend": "cash_insufficient_sample",
                "retreat_or_danger_or_unknown": "cash",
            },
        },
        "data_quality": {
            "membership_evidence": MEMBERSHIP_EVIDENCE_LEVEL,
            "strict_historical_membership": strict_rows > 0,
            "same_close_execution": "research proxy, not guaranteed executable fill",
            "minutes_used": False,
            "fund_flow_used": False,
            "old_v3_artifact_modified": False,
        },
        "coverage": {
            **dict(coverage),
            "policy_confirmations": {
                variant: int(len(_variant_rows(selected_signals, variant)))
                for variant in VARIANTS
            },
            "selected_trades": {
                variant: int(len(_variant_rows(trades, variant)))
                for variant in VARIANTS
            },
        },
        "qualification": qualification,
        "overall_metrics": [
            {"variant": variant, **_metric_summary(_variant_rows(trades, variant))}
            for variant in VARIANTS
        ],
        "cash_results": dict(cash_results),
        "time_block_metrics": _group_metrics(trades, "time_block"),
        "market_phase_metrics": _group_metrics(trades, "market_phase"),
        "support_path_metrics": _group_metrics(trades, "support_path"),
        "year_metrics": _group_metrics(trades, "calendar_year"),
        "symbol_metrics": _group_metrics(trades, "symbol_group"),
        "concept_metrics": _group_metrics(trades, "concept_group"),
        "named_case_audit": [dict(item) for item in named_case_audit],
        "selected_signal_ledger": _records(selected_signals),
        "selected_trade_ledger": _records(trades),
        "fingerprints": dict(fingerprints),
        "boundaries": [
            "The exact-support result is produced by an independent state-machine replay, not a post-hoc trade filter.",
            "The deep-reclaim contract permits MA10/MA20 after the minimum required support and is not an exact MA5/MA10 rule.",
            "Current concept memberships are replayed backward and retain survivorship bias.",
            "D close simultaneously confirms and prices the signal, so the result remains a same-close research proxy.",
            "All five chronological blocks have already been viewed and are not a fresh holdout.",
        ],
        "reproduce": (
            "docker compose --profile research run --rm -T --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace "
            "-e PYTHONPATH=/workspace:/app/third_party/akshare "
            "alphaagent-research python -m alphaagent.server.services.low_suction.cli "
            "v4-support-contract-study --format json"
        ),
    }
    return _json_safe(report)


def run_support_contract_study() -> dict[str, Any]:
    """Run the two support contracts from one immutable raw-input load."""

    from .research_protocol import fingerprint_frame

    inputs = load_causal_leader_pullback_inputs()
    coverage = dict(inputs.coverage)
    fingerprints: dict[str, Mapping[str, Any]] = dict(inputs.fingerprints)
    stock_features = build_causal_stock_features(inputs.stock_bars)
    campaigns, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    leader_paths, rank_coverage = build_dynamic_leader_paths(
        campaign_paths,
        inputs.memberships,
        stock_features,
    )
    replays = replay_support_contracts(leader_paths, inputs.market_timing)
    selected_signals, selected_trades = collect_selected_policy_evidence(replays)
    named_case_audit = build_support_named_case_audit(
        leader_paths,
        replays,
        selected_signals,
        selected_trades,
    )
    cash_results = {
        variant: simulate_four_slot_cash(
            _variant_rows(selected_trades, variant),
            stock_features,
        )
        for variant in VARIANTS
    }
    coverage.update(rank_coverage)
    coverage.update(
        {
            "concept_campaigns": int(len(campaigns)),
            "leader_path_rows": int(len(leader_paths)),
            "state_machine_candidate_signals": {
                variant: int(len(replays[variant].signals)) for variant in VARIANTS
            },
        }
    )
    for variant in VARIANTS:
        fingerprints[f"{variant}_state_machine_signals"] = fingerprint_frame(
            replays[variant].signals,
            identity_columns=("signal_id",),
        ).as_dict()
    fingerprints["v4_selected_signals"] = fingerprint_frame(
        selected_signals,
        identity_columns=("variant", "signal_id"),
    ).as_dict()
    fingerprints["v4_selected_trades"] = fingerprint_frame(
        selected_trades,
        identity_columns=("variant", "signal_id"),
    ).as_dict()
    return build_support_contract_report(
        coverage=coverage,
        fingerprints=fingerprints,
        selected_signals=selected_signals,
        selected_trades=selected_trades,
        cash_results=cash_results,
        named_case_audit=named_case_audit,
    )


def render_support_contract_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_support_contract_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# AlphaAgent 低吸支撑合同 v4 对照",
        "",
        f"版本：`{report.get('policy_version')}`；正式策略：`false`。",
        "",
        "## 两种独立规则",
        "",
    ]
    variants = _mapping(_mapping(report.get("contract")).get("variants"))
    for variant in VARIANTS:
        lines.append(f"- `{variant}`：{variants.get(variant)}")
    lines.extend(["", "## 总体与四仓", "", _metric_table(report), ""])
    lines.extend(["## 五个时间块", "", _group_table(report, "time_block_metrics"), ""])
    lines.extend(["## 行情阶段", "", _group_table(report, "market_phase_metrics"), ""])
    lines.extend(["## 支撑路径", "", _group_table(report, "support_path_metrics"), ""])
    lines.extend(["## 年份", "", _group_table(report, "year_metrics"), ""])
    lines.extend(["## 主要个股贡献", "", _top_group_table(report, "symbol_metrics"), ""])
    lines.extend(["## 主要概念贡献", "", _top_group_table(report, "concept_metrics"), ""])
    lines.extend(["## 参考个股波段", "", _named_case_table(report), ""])
    lines.extend(["### 参考个股逐浪", "", _named_wave_table(report), ""])
    lines.extend(["### 参考个股已选成交", "", _named_trade_table(report), ""])
    lines.extend(["## 资格结论", ""])
    for variant, decision in _mapping(report.get("qualification")).items():
        item = _mapping(decision)
        lines.append(
            f"- `{variant}`：历史代理门=`{item.get('historical_proxy_gate_passed')}`；"
            f"失败门=`{', '.join(item.get('failed_gates') or []) or 'none'}`；"
            f"正式阻断=`{', '.join(item.get('formal_blockers') or []) or 'none'}`。"
        )
    lines.extend(["", "## 边界", ""])
    lines.extend(f"- {value}" for value in report.get("boundaries") or [])
    lines.extend(["", "## Reproduce", "", "```bash", str(report.get("reproduce") or ""), "```"])
    return "\n".join(lines).rstrip() + "\n"


def _metric_table(report: Mapping[str, Any]) -> str:
    cash = _mapping(report.get("cash_results"))
    rows = ["| 规则 | 成交 | 胜率 | 均值 | PF | 四仓复利 | 四仓回撤 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for item in report.get("overall_metrics") or []:
        metric = _mapping(item)
        account = _mapping(cash.get(str(metric.get("variant"))))
        rows.append(
            "| {variant} | {trades} | {win} | {mean} | {pf} | {compound} | {drawdown} |".format(
                variant=metric.get("variant"),
                trades=metric.get("closed_trades", 0),
                win=_pct(metric.get("win_rate_pct")),
                mean=_pct(metric.get("mean_net_return_pct"), signed=True),
                pf=_number(metric.get("profit_factor")),
                compound=_pct(account.get("compound_return_pct"), signed=True),
                drawdown=_pct(account.get("maximum_drawdown_pct")),
            )
        )
    return "\n".join(rows)


def _group_table(report: Mapping[str, Any], key: str) -> str:
    rows = ["| 规则 | 分组 | 成交 | 胜率 | 均值 | PF |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for item in report.get(key) or []:
        metric = _mapping(item)
        rows.append(
            "| {variant} | {group} | {trades} | {win} | {mean} | {pf} |".format(
                variant=metric.get("variant"),
                group=metric.get("group"),
                trades=metric.get("closed_trades", 0),
                win=_pct(metric.get("win_rate_pct")),
                mean=_pct(metric.get("mean_net_return_pct"), signed=True),
                pf=_number(metric.get("profit_factor")),
            )
        )
    return "\n".join(rows)


def _top_group_table(
    report: Mapping[str, Any],
    key: str,
    *,
    limit: int = 10,
) -> str:
    items = sorted(
        (_mapping(item) for item in report.get(key) or []),
        key=lambda item: (
            -int(item.get("closed_trades") or 0),
            str(item.get("variant") or ""),
            str(item.get("group") or ""),
        ),
    )[:limit]
    return _group_table({key: items}, key)


def _named_case_table(report: Mapping[str, Any]) -> str:
    rows = [
        "| 规则 | 个股 | 龙头区间 | 波段 | 信号 | 成交 |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for raw in report.get("named_case_audit") or []:
        item = _mapping(raw)
        rows.append(
            "| {variant} | {name} `{symbol}` | {start}..{end} | {waves} | {signals} | {trades} |".format(
                variant=item.get("variant"),
                name=item.get("stock_name"),
                symbol=item.get("vt_symbol"),
                start=item.get("first_top3_date") or "-",
                end=item.get("last_top3_date") or "-",
                waves=item.get("waves", 0),
                signals=item.get("signals", 0),
                trades=item.get("executed_trades", 0),
            )
        )
    return "\n".join(rows)


def _named_wave_table(report: Mapping[str, Any]) -> str:
    rows = [
        "| 规则 | 个股 | 浪次 | 区间 | 最深支撑 | 新高 | 终态 |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for raw in report.get("named_case_audit") or []:
        case = _mapping(raw)
        for wave_raw in case.get("wave_rows") or []:
            wave = _mapping(wave_raw)
            rows.append(
                "| {variant} | {name} | {wave} | {start}..{end} | {support} | {higher} | {state} |".format(
                    variant=case.get("variant"),
                    name=case.get("stock_name"),
                    wave=wave.get("wave_number"),
                    start=wave.get("wave_start_date") or "-",
                    end=wave.get("wave_end_date") or "-",
                    support=wave.get("deepest_tested_support") or "-",
                    higher=wave.get("higher_high_confirmed"),
                    state=wave.get("terminal_state") or "-",
                )
            )
    return "\n".join(rows)


def _named_trade_table(report: Mapping[str, Any]) -> str:
    rows = [
        "| 规则 | 个股 | 买入 | 支撑 | 卖出 | 原因 | 净收益 |",
        "| --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for raw in report.get("named_case_audit") or []:
        case = _mapping(raw)
        for trade_raw in case.get("trade_rows") or []:
            trade = _mapping(trade_raw)
            rows.append(
                "| {variant} | {name} | {entry} | {required}->{support} | {exit} | {reason} | {net} |".format(
                    variant=case.get("variant"),
                    name=case.get("stock_name"),
                    entry=trade.get("entry_date") or "-",
                    required=trade.get("required_support") or "-",
                    support=trade.get("support_line") or "-",
                    exit=trade.get("exit_date") or "-",
                    reason=trade.get("exit_reason") or "-",
                    net=_pct(trade.get("net_return_pct"), signed=True),
                )
            )
    return "\n".join(rows)


def _metric_summary(trades: pd.DataFrame) -> dict[str, Any]:
    source = summarize_trade_metrics(trades)
    return {
        "closed_trades": int(source.get("closed_trades") or 0),
        "winning_trades": int(source.get("positive_trades") or 0),
        "win_rate_pct": _finite_or_none(source.get("positive_rate_pct")),
        "mean_net_return_pct": _finite_or_none(source.get("mean_net_return_pct")),
        "median_net_return_pct": _finite_or_none(source.get("median_net_return_pct")),
        "profit_factor": _finite_or_none(source.get("profit_factor")),
        "compound_return_pct": _finite_or_none(source.get("compound_return_pct")),
        "maximum_drawdown_pct": _finite_or_none(source.get("maximum_drawdown_pct")),
    }


def _group_metrics(trades: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if trades.empty or "variant" not in trades or column not in trades:
        return []
    rows: list[dict[str, Any]] = []
    for (variant, group), frame in trades.groupby(
        ["variant", column], sort=True, dropna=False
    ):
        rows.append(
            {
                "variant": str(variant),
                "group": "missing" if pd.isna(group) else str(group),
                **_metric_summary(frame),
            }
        )
    return rows


def _single_variant_group_metrics(
    trades: pd.DataFrame,
    column: str,
) -> list[dict[str, Any]]:
    if trades.empty or column not in trades:
        return []
    return [
        {
            "group": "missing" if pd.isna(group) else str(group),
            **_metric_summary(frame),
        }
        for group, frame in trades.groupby(column, sort=True, dropna=False)
    ]


def _variant_rows(frame: pd.DataFrame, variant: str) -> pd.DataFrame:
    if frame.empty or "variant" not in frame:
        return frame.iloc[0:0].copy()
    return frame.loc[frame["variant"].astype(str).eq(variant)].copy()


def _named_group(frame: pd.DataFrame, identity: str, name: str) -> pd.Series:
    identities = frame.get(identity, pd.Series(index=frame.index, dtype=str))
    names = frame.get(name, pd.Series(index=frame.index, dtype=str))
    labels = names.fillna("").astype(str).str.strip()
    return identities.fillna("unknown").astype(str) + labels.map(
        lambda label: f"|{label}" if label else ""
    )


def _concat(parts: Sequence[pd.DataFrame]) -> pd.DataFrame:
    nonempty = [part for part in parts if not part.empty]
    return pd.concat(nonempty, ignore_index=True, sort=False) if nonempty else pd.DataFrame()


def _wilson_lower_bound_pct(wins: int, total: int) -> float | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = wins / total
    denominator = 1.0 + z * z / total
    centre = proportion + z * z / (2.0 * total)
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    )
    return (centre - margin) / denominator * 100.0


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return _json_safe(frame.to_dict("records"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date, np.datetime64)):
        if pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()
    if value is pd.NA or value is pd.NaT or value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _pct(value: Any, *, signed: bool = False) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "-"
    return f"{number:+.2f}%" if signed else f"{number:.2f}%"


def _number(value: Any) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.3f}"
