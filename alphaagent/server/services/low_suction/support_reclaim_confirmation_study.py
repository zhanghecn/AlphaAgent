"""Sequential V7 study for support followed by a weak-to-strong close."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.research_runtime import require_research_runtime

from .causal_leader_pullback import MINIMUM_REQUIRED_SUPPORT
from .causal_leader_pullback_study import (
    build_causal_stock_features,
    build_concept_campaign_ledger,
    build_dynamic_leader_paths,
    build_named_case_audit,
    load_causal_leader_pullback_inputs,
    prepare_dynamic_leader_paths,
    simulate_four_slot_cash,
)
from .dynamic_concept_campaign import MEMBERSHIP_EVIDENCE_LEVEL
from .support_day_entry import (
    DEVELOPMENT_BLOCKS,
    DOUBLE_ROUND_TRIP_COST_PCT,
    ROUND_TRIP_COST_PCT,
    RULE_EXACT_HOLD,
    apply_pre_registered_rules,
    build_support_day_events,
    execute_d1_close_trades,
    filter_common_rule_universe,
    reprice_d1_close_trades,
    summarize_d1_trades,
)
from .support_day_study import (
    ENVIRONMENT_COLUMNS,
    apply_frozen_environment_policy,
    freeze_development_environments,
)
from .support_quality import (
    MIN_PROFIT_FACTOR,
    MIN_WIN_RATE_PCT,
    evaluate_sequential_late_blocks,
)
from .support_reclaim_confirmation import (
    NON_LIMIT_RETURN_CEILING_PCT,
    assign_frozen_time_blocks,
    build_support_reclaim_confirmations,
    freeze_common_block_boundaries,
    freeze_development_confirmation_rule,
)


STUDY_VERSION = "low-suction-support-reclaim-confirmation-study-v1"
POLICY_VERSION = "causal-leader-support-reclaim-confirmation-v7"
MIN_TOTAL_TRADES = 100
MIN_CASH_COMPOUND_PCT = 60.0
MIN_CASH_DRAWDOWN_PCT = -10.0
MIN_MATERIAL_ENVIRONMENT_TRADES = 30
MIN_MATERIAL_ENVIRONMENT_DAYS = 20
_REBUILT_NAMED_CASE_FIELDS = frozenset(
    {
        "signals",
        "executed_trades",
        "signal_rows",
        "trade_rows",
        "v7_counts",
        "v7_confirmation_rows",
        "v7_visible_trade_rows",
    }
)


@dataclass(frozen=True)
class ConfirmationValidation:
    environment_freeze: Mapping[str, Any]
    block_4: Mapping[str, Any]
    block_5: Mapping[str, Any] | None
    late_validation_passed: bool
    qualification: Mapping[str, Any]
    four_slot_cash: Mapping[str, Any]
    double_cost_four_slot_cash: Mapping[str, Any]
    material_environment_metrics: tuple[Mapping[str, Any], ...]
    visible_trades: pd.DataFrame


def evaluate_selected_confirmation_rule(
    selected_trades: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    coverage: Mapping[str, Any],
) -> ConfirmationValidation:
    """Route environments and expose late blocks in strict sequence."""

    environment_freeze = freeze_development_environments(selected_trades)
    routed = apply_frozen_environment_policy(
        selected_trades,
        _mapping(environment_freeze.get("policy_by_environment")),
    )
    late = evaluate_sequential_late_blocks(routed)
    visible_blocks = set(DEVELOPMENT_BLOCKS) | {"block_4"}
    if bool(_mapping(late.get("block_4")).get("passed")):
        visible_blocks.add("block_5")
    visible = _sort_trades(routed.loc[routed["time_block"].isin(visible_blocks)])
    if not bool(late["late_validation_passed"]):
        failed_block = "block_4" if late["block_5"] is None else "block_5"
        return ConfirmationValidation(
            environment_freeze=environment_freeze,
            block_4=_mapping(late["block_4"]),
            block_5=(
                _mapping(late["block_5"])
                if late["block_5"] is not None
                else None
            ),
            late_validation_passed=False,
            qualification=_unvalidated_qualification(failed_block, coverage),
            four_slot_cash={},
            double_cost_four_slot_cash={},
            material_environment_metrics=(),
            visible_trades=visible,
        )

    double_cost = reprice_d1_close_trades(
        routed,
        round_trip_cost_pct=DOUBLE_ROUND_TRIP_COST_PCT,
    )
    cash = simulate_four_slot_cash(routed, stock_bars)
    double_cost_cash = simulate_four_slot_cash(double_cost, stock_bars)
    environment_metrics = tuple(_material_environment_metrics(routed, stock_bars))
    qualification = _evaluate_final_rule(
        routed,
        cash_result=cash,
        double_cost_cash_result=double_cost_cash,
        environment_metrics=environment_metrics,
        coverage=coverage,
    )
    return ConfirmationValidation(
        environment_freeze=environment_freeze,
        block_4=_mapping(late["block_4"]),
        block_5=_mapping(late["block_5"]),
        late_validation_passed=True,
        qualification=qualification,
        four_slot_cash=cash,
        double_cost_four_slot_cash=double_cost_cash,
        material_environment_metrics=environment_metrics,
        visible_trades=_sort_trades(routed),
    )


def build_development_diagnostics(trades: pd.DataFrame) -> dict[str, Any]:
    """Describe visible development winners and losers without selecting V7."""

    development = trades.loc[
        trades.get("time_block", pd.Series(dtype=str)).isin(DEVELOPMENT_BLOCKS)
    ].copy()
    if development.empty:
        return {
            "visible_blocks": sorted(DEVELOPMENT_BLOCKS),
            "closed_trades": 0,
            "groups": [],
        }
    enriched = _with_diagnostic_groups(development)
    dimensions = {
        "support_line": "required_support",
        "confirmation_delay": "confirmation_delay_group",
        "signal_return": "signal_return_group",
        "volume_ratio": "volume_ratio_group",
        "dynamic_rank": "dynamic_rank_group",
    }
    groups = []
    for dimension, column in dimensions.items():
        for group, rows in enriched.groupby(column, sort=True, dropna=False):
            groups.append(
                {
                    "dimension": dimension,
                    "group": str(group),
                    **summarize_d1_trades(rows),
                }
            )
    return {
        "visible_blocks": sorted(DEVELOPMENT_BLOCKS),
        "closed_trades": int(
            development.loc[development["exit_date"].notna(), "signal_id"].nunique()
        ),
        "groups": groups,
    }


def build_support_reclaim_confirmation_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
    block_boundaries: Mapping[str, object],
    exact_support_events: pd.DataFrame,
    confirmation_events: pd.DataFrame,
    executed_trades: pd.DataFrame,
    development_freeze: Mapping[str, Any],
    validation: ConfirmationValidation | None,
    named_case_audit: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build an evidence report without serializing unopened outcomes."""

    selected_rule = development_freeze.get("selected_rule")
    development = executed_trades.loc[
        executed_trades.get("time_block", pd.Series(dtype=str)).isin(
            DEVELOPMENT_BLOCKS
        )
    ].copy()
    if selected_rule is None:
        qualification = _no_nomination_qualification(coverage)
        environment_freeze: Mapping[str, Any] = {}
        block_4 = None
        block_5 = None
        visible = pd.DataFrame()
        cash: Mapping[str, Any] = {}
        double_cash: Mapping[str, Any] = {}
        environment_metrics: Sequence[Mapping[str, Any]] = ()
    else:
        if validation is None:
            raise ValueError("selected V7 rule requires sequential validation")
        qualification = validation.qualification
        environment_freeze = validation.environment_freeze
        block_4 = validation.block_4
        block_5 = validation.block_5
        visible = validation.visible_trades
        cash = validation.four_slot_cash
        double_cash = validation.double_cost_four_slot_cash
        environment_metrics = validation.material_environment_metrics

    report = {
        "study_version": STUDY_VERSION,
        "policy_version": POLICY_VERSION,
        "research_status": _research_status(selected_rule, validation),
        "formal_strategy": bool(qualification.get("formal_strategy")),
        "formal_metrics": qualification.get("formal_metrics"),
        "selected_rule": selected_rule,
        "contract": {
            "support_anchor": "frozen_v5_support_day_exact_hold",
            "first_wave_support": "ma5",
            "later_wave_support": "ma10",
            "anchor_replacement": "latest_exact_support_before_confirmation",
            "confirmation": (
                "first later close above support-day high and previous close, "
                "below the visible record high, with daily return below 8%"
            ),
            "non_limit_return_ceiling_pct": NON_LIMIT_RETURN_CEILING_PCT,
            "entry": "confirmation_day_close",
            "exit": "next_symbol_session_close",
            "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            "double_round_trip_cost_pct": DOUBLE_ROUND_TRIP_COST_PCT,
            "entry_execution_assumption": "same_close_research_proxy",
            "membership_evidence_level": MEMBERSHIP_EVIDENCE_LEVEL,
            "development_blocks": sorted(DEVELOPMENT_BLOCKS),
            "environment_columns": list(ENVIRONMENT_COLUMNS),
            "gold_silver_can_change_entry": False,
        },
        "block_boundaries": {
            key: pd.Timestamp(value).date().isoformat()
            for key, value in block_boundaries.items()
        },
        "coverage": dict(coverage),
        "fingerprints": dict(fingerprints),
        "development_freeze": dict(development_freeze),
        "development_diagnostics": build_development_diagnostics(development),
        "environment_freeze": dict(environment_freeze),
        "block_4": block_4,
        "block_5": block_5,
        "qualification": dict(qualification),
        "overall_metrics": qualification.get("overall_metrics"),
        "four_slot_cash": dict(cash),
        "double_cost_four_slot_cash": dict(double_cash),
        "material_environment_metrics": [dict(row) for row in environment_metrics],
        "development_trade_ledger": _records(_sort_trades(development)),
        "selected_trade_ledger": _records(_sort_trades(visible)),
        "named_case_audit": _augment_named_cases(
            named_case_audit,
            exact_support_events,
            confirmation_events,
            visible,
        ),
        "boundaries": [
            "The V5 common support-event calendar is frozen before V7 confirmations are selected.",
            "Only blocks 1-3 can nominate the sole V7 entry rule and environment table.",
            "Block 5 outcomes and trade rows remain absent unless block 4 passes.",
            "GOLD/SILVER and market phase can route cash only after the entry rule passes development.",
            "Development diagnostics are attribution and cannot alter the V7 contract.",
            "Current membership and the completed D close remain historical research proxies.",
        ],
        "reproduce": (
            "docker compose --profile research run --rm -T --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace "
            "-e PYTHONPATH=/workspace:/app/third_party/akshare "
            "alphaagent-research python -m "
            "alphaagent.server.services.low_suction.cli "
            "v7-support-reclaim-confirmation-study --format json"
        ),
    }
    return _json_safe(report)


def run_support_reclaim_confirmation_study() -> dict[str, Any]:
    """Run one database load and one pre-registered V7 replay."""

    from .research_protocol import fingerprint_frame

    require_research_runtime()
    inputs = load_causal_leader_pullback_inputs()
    stock_features = build_causal_stock_features(inputs.stock_bars)
    campaigns, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    leader_paths, rank_coverage = build_dynamic_leader_paths(
        campaign_paths,
        inputs.memberships,
        stock_features,
    )
    prepared = prepare_dynamic_leader_paths(
        leader_paths,
        inputs.market_timing,
        support_match_mode=MINIMUM_REQUIRED_SUPPORT,
    )
    raw_support = build_support_day_events(
        leader_paths,
        prepared.campaigns.daily_ledger,
        inputs.market_timing,
    )
    common_support = filter_common_rule_universe(raw_support)
    block_boundaries = freeze_common_block_boundaries(common_support["signal_date"])
    exact_support = apply_pre_registered_rules(common_support)
    exact_support = exact_support.loc[
        exact_support["rule_id"].eq(RULE_EXACT_HOLD)
    ].reset_index(drop=True)
    confirmations = build_support_reclaim_confirmations(
        exact_support,
        leader_paths,
        prepared.campaigns.daily_ledger,
        inputs.market_timing,
    )
    confirmations = assign_frozen_time_blocks(confirmations, block_boundaries)
    executed = execute_d1_close_trades(confirmations, stock_features)
    double_cost = reprice_d1_close_trades(
        executed,
        round_trip_cost_pct=DOUBLE_ROUND_TRIP_COST_PCT,
    )
    development = executed.loc[executed["time_block"].isin(DEVELOPMENT_BLOCKS)]
    development_cash = simulate_four_slot_cash(development, stock_features)
    development_freeze = freeze_development_confirmation_rule(
        executed,
        double_cost,
        development_cash,
    )
    validation = None
    if development_freeze["selected_rule"] is not None:
        validation = evaluate_selected_confirmation_rule(
            executed,
            stock_features,
            coverage=inputs.coverage,
        )
    visible = validation.visible_trades if validation is not None else pd.DataFrame()
    named_cases = build_named_case_audit(
        leader_paths,
        confirmations,
        visible,
        prepared.waves,
        prepared.campaigns.daily_ledger,
    )

    coverage = {
        **dict(inputs.coverage),
        **dict(rank_coverage),
        "concept_campaigns": int(len(campaigns)),
        "leader_path_rows": int(len(leader_paths)),
        "state_machine_daily_rows": int(len(prepared.campaigns.daily_ledger)),
        "raw_support_day_events": int(len(raw_support)),
        "common_support_day_events": int(len(common_support)),
        "exact_support_events": int(len(exact_support)),
        "support_reclaim_confirmations": int(len(confirmations)),
        "development_confirmation_trades": int(len(development)),
        "preclose_execution_rows": 0,
    }
    fingerprints: dict[str, Mapping[str, Any]] = dict(inputs.fingerprints)
    _add_fingerprint(
        fingerprints,
        "v7_common_support_events",
        common_support,
        ("signal_id",),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v7_exact_support_anchors",
        exact_support,
        ("signal_id",),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v7_confirmation_events",
        confirmations,
        ("signal_id",),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v7_d1_execution",
        executed,
        ("signal_id",),
        fingerprint_frame,
    )
    boundary_frame = pd.DataFrame(
        [
            {"time_block": block, "end_date": endpoint}
            for block, endpoint in block_boundaries.items()
        ]
    )
    _add_fingerprint(
        fingerprints,
        "v7_block_boundaries",
        boundary_frame,
        ("time_block",),
        fingerprint_frame,
    )
    _add_fingerprint(
        fingerprints,
        "v7_visible_selected_trades",
        visible,
        ("signal_id",),
        fingerprint_frame,
    )
    return build_support_reclaim_confirmation_report(
        coverage=coverage,
        fingerprints=fingerprints,
        block_boundaries=block_boundaries,
        exact_support_events=exact_support,
        confirmation_events=confirmations,
        executed_trades=executed,
        development_freeze=development_freeze,
        validation=validation,
        named_case_audit=named_cases,
    )


def render_support_reclaim_confirmation_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_support_reclaim_confirmation_markdown(
    report: Mapping[str, Any],
) -> str:
    freeze = _mapping(report.get("development_freeze"))
    development = _mapping(freeze.get("development_metrics"))
    qualification = _mapping(report.get("qualification"))
    lines = [
        "# AlphaAgent 主升龙头支撑后首次弱转强 V7",
        "",
        f"规则版本：`{report.get('policy_version')}`  ",
        f"研究状态：`{report.get('research_status')}`  ",
        f"开发期规则：`{report.get('selected_rule') or 'none'}`  ",
        f"历史代理门：`{qualification.get('historical_proxy_gate_passed', False)}`  ",
        f"正式策略：`{str(report.get('formal_strategy', False)).lower()}`",
        "",
        "## 固定入场合同",
        "",
        "- 精确 MA5/MA10 支撑日不买；只保留同 campaign、同 wave 的最新有效支撑锚。",
        "- 首次收盘越过支撑日最高价和前收、仍低于可见前高、当日涨幅小于 8% 时买入。",
        "- D 收盘买入代理，D+1 收盘卖出；金银和市场阶段不能改变入场条件。",
        "",
        "## 开发期",
        "",
        f"- 成交：`{development.get('closed_trades', 0)}`",
        f"- 胜率：`{_pct(development.get('win_rate_pct'))}`",
        f"- 均值：`{_pct(development.get('mean_net_return_pct'), signed=True)}`",
        f"- PF：`{_number(development.get('profit_factor'))}`",
        f"- 稳定块：`{freeze.get('development_stable_blocks', 0)}`",
        f"- 四仓复利：`{_pct(freeze.get('development_cash_compound_pct'), signed=True)}`",
        f"- 失败门：`{', '.join(freeze.get('failed_gates') or []) or 'none'}`",
        "",
        "## 顺序样本外",
        "",
        _block_line("block 4", report.get("block_4")),
        _block_line("block 5", report.get("block_5")),
        "",
        "## 最终资格",
        "",
        f"- 失败门：`{', '.join(qualification.get('failed_gates') or []) or 'none'}`",
        f"- 正式阻断：`{', '.join(qualification.get('formal_blockers') or []) or 'none'}`",
        "",
        "## 参考龙头",
        "",
    ]
    for case in report.get("named_case_audit") or []:
        row = _mapping(case)
        counts = _mapping(row.get("v7_counts"))
        lines.append(
            f"- {row.get('stock_name')} `{row.get('vt_symbol')}`：精确支撑 "
            f"`{counts.get('exact_support_events', 0)}`，首次弱转强 "
            f"`{counts.get('confirmation_events', 0)}`，可见成交 "
            f"`{counts.get('visible_trades', 0)}`。"
        )
    lines.extend(["", "## 开发期归因", ""])
    diagnostics = _mapping(report.get("development_diagnostics"))
    lines.append(
        f"- 只读取 `{', '.join(diagnostics.get('visible_blocks') or [])}`，闭合 "
        f"`{diagnostics.get('closed_trades', 0)}` 笔；所有分组仅供下一独立假设。"
    )
    lines.extend(["", "## 研究边界", ""])
    lines.extend(f"- {value}" for value in report.get("boundaries") or [])
    lines.extend(
        ["", "## Reproduce", "", "```bash", str(report.get("reproduce") or ""), "```", ""]
    )
    return "\n".join(lines)


def _with_diagnostic_groups(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    delay = pd.to_numeric(result["confirmation_delay_sessions"], errors="coerce")
    signal_return = pd.to_numeric(result["daily_return_pct"], errors="coerce")
    volume = pd.to_numeric(result["volume_ratio_prior5"], errors="coerce")
    rank = pd.to_numeric(result["dynamic_rank"], errors="coerce")
    result["confirmation_delay_group"] = np.select(
        [delay.eq(1), delay.eq(2)], ["1", "2"], default="3+"
    )
    result["signal_return_group"] = np.select(
        [signal_return.lt(2.0), signal_return.lt(5.0)],
        ["<2%", "2-5%"],
        default="5-8%",
    )
    result["volume_ratio_group"] = np.select(
        [volume.lt(0.8), volume.lt(1.5)],
        ["<0.8", "0.8-1.5"],
        default=">=1.5",
    )
    result["dynamic_rank_group"] = np.where(rank.eq(1), "1", "2-3")
    return result


def _evaluate_final_rule(
    trades: pd.DataFrame,
    *,
    cash_result: Mapping[str, Any],
    double_cost_cash_result: Mapping[str, Any],
    environment_metrics: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    overall = summarize_d1_trades(trades)
    failed = []
    if int(overall["closed_trades"]) < MIN_TOTAL_TRADES:
        failed.append("closed_trades<100")
    if float(overall["win_rate_pct"] or 0.0) <= MIN_WIN_RATE_PCT:
        failed.append("win_rate<=60pct")
    if float(overall["mean_net_return_pct"] or 0.0) <= 0.0:
        failed.append("mean_return<=0")
    if float(overall["profit_factor"] or 0.0) < MIN_PROFIT_FACTOR:
        failed.append("profit_factor<1.2")
    if float(cash_result.get("compound_return_pct") or 0.0) <= MIN_CASH_COMPOUND_PCT:
        failed.append("cash_compound<=60pct")
    drawdown = _finite_or_none(cash_result.get("maximum_drawdown_pct"))
    if drawdown is None or drawdown < MIN_CASH_DRAWDOWN_PCT:
        failed.append("cash_drawdown<-10pct")
    if float(double_cost_cash_result.get("compound_return_pct") or 0.0) <= 0.0:
        failed.append("double_cost_compound<=0")
    qualified_environments = [
        str(row["environment_key"])
        for row in environment_metrics
        if bool(row.get("qualified_material_environment"))
    ]
    if len(qualified_environments) < 2:
        failed.append("qualified_material_environments<2")
    blockers = _formal_blockers(coverage, required_preclose_rows=int(overall["closed_trades"]))
    historical_passed = not failed
    formal_strategy = historical_passed and not blockers
    return {
        "historical_proxy_gate_passed": historical_passed,
        "formal_strategy": formal_strategy,
        "formal_metrics": (
            {
                "d1": overall,
                "four_slot_cash": dict(cash_result),
                "material_environments": [dict(row) for row in environment_metrics],
            }
            if formal_strategy
            else None
        ),
        "overall_metrics": overall,
        "qualified_material_environments": qualified_environments,
        "failed_gates": failed,
        "formal_blockers": blockers,
    }


def _material_environment_metrics(
    trades: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> list[dict[str, Any]]:
    keyed = _with_environment_key(trades)
    rows = []
    for environment, group in keyed.groupby("environment_key", sort=True):
        summary = summarize_d1_trades(group)
        cash = simulate_four_slot_cash(group, stock_bars)
        trade_days = int(
            pd.to_datetime(group["entry_date"], errors="coerce")
            .dropna()
            .dt.normalize()
            .nunique()
        )
        drawdown = _finite_or_none(cash.get("maximum_drawdown_pct"))
        qualified = bool(
            int(summary["closed_trades"]) >= MIN_MATERIAL_ENVIRONMENT_TRADES
            and trade_days >= MIN_MATERIAL_ENVIRONMENT_DAYS
            and float(summary["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
            and float(cash.get("compound_return_pct") or 0.0) > 0.0
            and drawdown is not None
            and drawdown >= MIN_CASH_DRAWDOWN_PCT
        )
        rows.append(
            {
                "environment_key": str(environment),
                "trade_days": trade_days,
                **summary,
                "four_slot_cash": dict(cash),
                "qualified_material_environment": qualified,
            }
        )
    return rows


def _augment_named_cases(
    base_cases: Sequence[Mapping[str, Any]],
    exact_support_events: pd.DataFrame,
    confirmation_events: pd.DataFrame,
    visible_trades: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows = []
    for case in base_cases:
        symbol = str(case.get("vt_symbol"))
        support = _symbol_rows(exact_support_events, symbol)
        confirmations = _symbol_rows(confirmation_events, symbol)
        trades = _symbol_rows(visible_trades, symbol)
        safe_case = {
            str(key): value
            for key, value in case.items()
            if key not in _REBUILT_NAMED_CASE_FIELDS
        }
        rows.append(
            {
                **safe_case,
                "signals": int(len(confirmations)),
                "executed_trades": int(len(trades)),
                "signal_rows": _records(confirmations),
                "trade_rows": _records(trades),
                "v7_counts": {
                    "exact_support_events": int(len(support)),
                    "confirmation_events": int(len(confirmations)),
                    "visible_trades": int(len(trades)),
                },
                "v7_confirmation_rows": _records(confirmations),
                "v7_visible_trade_rows": _records(trades),
            }
        )
    return rows


def _symbol_rows(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty or "vt_symbol" not in frame:
        return pd.DataFrame()
    return frame.loc[frame["vt_symbol"].astype(str).eq(symbol)].copy()


def _no_nomination_qualification(coverage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "historical_proxy_gate_passed": False,
        "formal_strategy": False,
        "formal_metrics": None,
        "overall_metrics": None,
        "qualified_material_environments": [],
        "failed_gates": ["no_development_confirmation_rule"],
        "formal_blockers": _formal_blockers(coverage, required_preclose_rows=1),
    }


def _unvalidated_qualification(
    failed_block: str,
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "historical_proxy_gate_passed": False,
        "formal_strategy": False,
        "formal_metrics": None,
        "overall_metrics": None,
        "qualified_material_environments": [],
        "failed_gates": [f"{failed_block}_failed"],
        "formal_blockers": _formal_blockers(coverage, required_preclose_rows=1),
    }


def _formal_blockers(
    coverage: Mapping[str, Any],
    *,
    required_preclose_rows: int,
) -> list[str]:
    blockers = []
    if int(coverage.get("strict_historical_membership_rows") or 0) <= 0:
        blockers.append("strict_historical_membership_missing")
    if int(coverage.get("preclose_execution_rows") or 0) < required_preclose_rows:
        blockers.append("executable_preclose_price_missing")
    return blockers


def _research_status(
    selected_rule: object,
    validation: ConfirmationValidation | None,
) -> str:
    if selected_rule is None:
        return "no_development_confirmation_rule"
    if validation is None:
        raise ValueError("selected V7 rule requires validation evidence")
    if not bool(validation.block_4.get("passed")):
        return "block_4_failed"
    if validation.block_5 is None or not bool(validation.block_5.get("passed")):
        return "block_5_failed"
    if bool(validation.qualification.get("historical_proxy_gate_passed")):
        return "historical_proxy_confirmation_rule_passed"
    return "historical_proxy_final_gates_failed"


def _with_environment_key(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["environment_key"] = result[list(ENVIRONMENT_COLUMNS)].astype(str).agg(
        "|".join,
        axis=1,
    )
    return result


def _sort_trades(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    columns = [
        column
        for column in ("entry_date", "dynamic_rank", "signal_id")
        if column in frame
    ]
    return frame.sort_values(columns, kind="stable").reset_index(drop=True)


def _add_fingerprint(
    target: dict[str, Mapping[str, Any]],
    name: str,
    frame: pd.DataFrame,
    identity: Sequence[str],
    fingerprint_frame: Any,
) -> None:
    if frame.empty or any(column not in frame for column in identity):
        return
    target[name] = fingerprint_frame(
        frame,
        identity_columns=tuple(identity),
    ).as_dict()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_safe(row) for row in frame.to_dict("records")]


def _block_line(label: str, value: object) -> str:
    if not isinstance(value, Mapping):
        return f"- {label}：`未读取`"
    return (
        f"- {label}：成交 `{value.get('closed_trades', 0)}`，"
        f"胜率 `{_pct(value.get('win_rate_pct'))}`，"
        f"均值 `{_pct(value.get('mean_net_return_pct'), signed=True)}`，"
        f"PF `{_number(value.get('profit_factor'))}`，"
        f"通过 `{value.get('passed', False)}`"
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct(value: object, *, signed: bool = False) -> str:
    number = _finite_or_none(value)
    if number is None:
        return "-"
    return f"{number:+.4f}%" if signed else f"{number:.4f}%"


def _number(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.4f}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is pd.NaT or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
