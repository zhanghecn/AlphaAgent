"""Frozen 5-minute recovery study after the first daily divergence."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .event_recognition_5m_study import (
    FROZEN_RULES,
    build_event_5m_state_panel,
    build_event_5m_study_report,
    execute_event_5m_transitions,
    extract_frozen_transitions,
    summarize_event_5m_outcomes,
)
from .first_divergence import load_first_divergence_inputs
from .first_divergence_minutes import (
    INTERVAL,
    load_first_divergence_5m_manifest,
)
from .research_protocol import fingerprint_frame

STUDY_EVIDENCE_LEVEL = "event_recognition_first_divergence_5m_falsification"


def build_first_divergence_transitions(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Reuse the frozen event-study state transitions unchanged."""

    panel = build_event_5m_state_panel(candidates, minute_bars)
    transitions = extract_frozen_transitions(panel)
    transitions["evidence_level"] = STUDY_EVIDENCE_LEVEL
    return transitions


def load_first_divergence_5m_study_data(
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    inputs = load_first_divergence_inputs()
    manifest = load_first_divergence_5m_manifest(inputs.candidates)
    incomplete = manifest.loc[manifest["status"].ne("complete")]
    if not incomplete.empty:
        raise ValueError(
            "first-divergence 5m manifest must be complete before state research"
        )
    candidates = inputs.candidates
    if candidates.empty:
        return pd.DataFrame(), inputs.stock_bars, {
            "coverage": _empty_coverage(inputs.discovery_end),
            "trading_dates": inputs.trading_dates,
            "minute_fingerprint": fingerprint_frame(
                pd.DataFrame(columns=["vt_symbol", "bar_time", "interval"]),
                identity_columns=("vt_symbol", "bar_time", "interval"),
            ).as_dict(),
        }

    symbols = tuple(sorted(candidates["vt_symbol"].astype(str).unique()))
    dates = tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique()))
    statement = (
        select(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
            schema.stock_minute_bars.c.interval,
            schema.stock_minute_bars.c.open_price,
            schema.stock_minute_bars.c.high_price,
            schema.stock_minute_bars.c.low_price,
            schema.stock_minute_bars.c.close_price,
            schema.stock_minute_bars.c.volume,
            schema.stock_minute_bars.c.turnover,
            schema.stock_minute_bars.c.source,
        )
        .where(
            schema.stock_minute_bars.c.vt_symbol.in_(symbols),
            schema.stock_minute_bars.c.trade_date.between(dates[0], dates[-1]),
            schema.stock_minute_bars.c.interval == INTERVAL,
        )
        .order_by(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
        )
    )
    loaded_bars = pd.read_sql(statement, get_engine(), parse_dates=["bar_time"])
    minute_bars = _filter_candidate_pairs(candidates, loaded_bars)
    transitions = build_first_divergence_transitions(candidates, minute_bars)
    minute_fingerprint = fingerprint_frame(
        minute_bars,
        identity_columns=("vt_symbol", "bar_time", "interval"),
    ).as_dict()
    coverage = {
        "candidate_pairs": int(len(candidates)),
        "complete_pairs": int(manifest["status"].eq("complete").sum()),
        "candidate_symbols": int(candidates["vt_symbol"].nunique()),
        "candidate_dates": int(candidates["entry_date"].nunique()),
        "minute_rows": int(len(minute_bars)),
        "transition_rows": int(len(transitions)),
        "transition_counts": {
            str(rule): int(count)
            for rule, count in transitions["rule"].value_counts().sort_index().items()
        },
        "discovery_end": inputs.discovery_end.isoformat(),
        "current_membership_rows_read": 0,
    }
    return transitions, inputs.stock_bars, {
        "coverage": coverage,
        "trading_dates": inputs.trading_dates,
        "minute_fingerprint": minute_fingerprint,
    }


def run_first_divergence_5m_study() -> dict[str, Any]:
    transitions, daily_bars, metadata = load_first_divergence_5m_study_data()
    normal = execute_event_5m_transitions(
        transitions,
        daily_bars,
        trading_dates=metadata["trading_dates"],
    )
    stressed = execute_event_5m_transitions(
        transitions,
        daily_bars,
        trading_dates=metadata["trading_dates"],
        cost_multiplier=2.0,
    )
    rule_metrics, block_metrics, regime_metrics = summarize_event_5m_outcomes(
        normal,
        stressed,
    )
    return build_first_divergence_5m_report(
        coverage=metadata["coverage"],
        rule_metrics=rule_metrics,
        block_metrics=block_metrics,
        regime_metrics=regime_metrics,
        minute_fingerprint=metadata["minute_fingerprint"],
    )


def build_first_divergence_5m_report(
    *,
    coverage: dict[str, Any],
    rule_metrics: pd.DataFrame,
    block_metrics: pd.DataFrame,
    regime_metrics: pd.DataFrame,
    minute_fingerprint: dict[str, Any] | str,
) -> dict[str, Any]:
    base = build_event_5m_study_report(
        coverage=coverage,
        rule_metrics=rule_metrics,
        block_metrics=block_metrics,
        regime_metrics=regime_metrics,
        minute_fingerprint=minute_fingerprint,
    )
    conclusion = {
        "worth_strict_retest": "worth_strict_retest",
        "event_5m_direction_only": "first_divergence_5m_direction_only",
        "no_event_5m_recovery_edge": "no_first_divergence_5m_edge",
    }[base["overall_conclusion"]]
    return {
        **base,
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": conclusion,
        "cohort": "first_negative_close_within_same_breakout_cycle",
        "frozen_rules": list(FROZEN_RULES),
        "frozen_parent_execution": "event_recognition_5m_state_study",
        "limitations": [
            "event-recognition candidates are not strict membership Top3",
            "first divergence is selected only inside the V2 discovery period",
            "five-minute bars cannot reconstruct tick queue priority",
            "formal cash compounding and outer holdout remain locked",
        ],
    }


def render_first_divergence_5m_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_first_divergence_5m_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# Low-suction First-divergence 5m Study",
        "",
        f"- Conclusion: `{report['overall_conclusion']}`",
        "- Formal metrics: `null`",
        "- Holdout values read: `false`",
        f"- Candidate/complete pairs: `{coverage.get('candidate_pairs', 0)}/"
        f"{coverage.get('complete_pairs', 0)}`",
        f"- Minute/transition rows: `{coverage.get('minute_rows', 0)}/"
        f"{coverage.get('transition_rows', 0)}`",
        "",
        "| Rule | Signals | Closed | Win | Mean | Median | PF | Tail 5% | Positive blocks | Double-cost mean | Retest |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["rule_metrics"]:
        lines.append(
            f"| `{row['rule']}` | {row['signals']} | {row['closed_trades']} | "
            f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
            f"{_pct(row['median_net_return_pct'])} | {_number(row['profit_factor'])} | "
            f"{_pct(row['tail_5pct'])} | {row['positive_blocks']}/5 | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} | "
            f"{'yes' if row['qualified_for_strict_retest'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Time Blocks",
            "",
            "| Rule | Block | Days | Closed | Win | Mean | PF | Positive |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["block_metrics"]:
        lines.append(
            f"| `{row['rule']}` | {row['block']} | {row['source_days']} | "
            f"{row['closed_trades']} | {_pct(row['win_rate_pct'])} | "
            f"{_pct(row['mean_net_return_pct'])} | {_number(row['profit_factor'])} | "
            f"{'yes' if row['positive_block'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Regimes",
            "",
            "| Rule | Regime | Days | Closed | Win | Mean | PF | Double-cost mean |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["regime_diagnostics"]:
        lines.append(
            f"| `{row['rule']}` | `{row['regime_key']}` | {row['source_days']} | "
            f"{row['closed_trades']} | {_pct(row['win_rate_pct'])} | "
            f"{_pct(row['mean_net_return_pct'])} | {_number(row['profit_factor'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} |"
        )
    lines.extend(
        [
            "",
            "事件认可关系不是完整历史成员 Top3；本报告只能否定或提名严格复测。",
            "",
        ]
    )
    return "\n".join(lines)


def _filter_candidate_pairs(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    pairs = candidates.loc[:, ["vt_symbol", "entry_date"]].copy()
    pairs["trade_date"] = pd.to_datetime(pairs.pop("entry_date")).dt.date
    pairs = pairs.drop_duplicates(["vt_symbol", "trade_date"])
    bars = minute_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    return bars.merge(
        pairs,
        on=["vt_symbol", "trade_date"],
        how="inner",
        validate="many_to_one",
    ).sort_values(["vt_symbol", "bar_time"], kind="stable")


def _empty_coverage(discovery_end: Any) -> dict[str, Any]:
    return {
        "candidate_pairs": 0,
        "complete_pairs": 0,
        "candidate_symbols": 0,
        "candidate_dates": 0,
        "minute_rows": 0,
        "transition_rows": 0,
        "transition_counts": {},
        "discovery_end": discovery_end.isoformat(),
        "current_membership_rows_read": 0,
    }


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _number(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"
