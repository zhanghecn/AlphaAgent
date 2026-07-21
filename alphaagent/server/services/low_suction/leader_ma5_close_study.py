"""Daily-close research proxy for the frozen leader MA5 cohort."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

import pandas as pd

from .leader_ma5_cash import (
    INITIAL_CASH,
    simulate_capacity_comparison,
    simulate_structural_cash_account,
)
from .research_protocol import fingerprint_frame


STUDY_VERSION = "leader-ma5-close-proxy-v1"
EXECUTION_ASSUMPTION = "same_close_research_proxy"
RESEARCH_STATUS = "historical_same_close_proxy_not_formal_validation"
PORTFOLIO_CAPACITY = 4
TIME_BLOCK_IDS = tuple(f"block_{number}" for number in range(1, 6))

CANDIDATE_COLUMNS = (
    "signal_id",
    "vt_symbol",
    "sector_id",
    "signal_date",
    "exit_date",
    "causal_rank",
    "reference_peak_price",
)
CASE_COLUMNS = (
    "signal_id",
    "signal_date",
    "vt_symbol",
    "stock_name",
    "sector_id",
    "concept_name",
    "time_block",
    "causal_rank",
    "reference_peak_price",
    "executable_exit_reason",
)


def build_close_proxy_trades(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Use the final signal-day close as the fixed historical entry proxy."""

    _require_columns(candidates, CANDIDATE_COLUMNS, "close-proxy candidate")
    _require_columns(
        daily_bars,
        ("vt_symbol", "trade_date", "close_price"),
        "close-proxy daily bar",
    )
    candidate_frame = candidates.loc[:, list(CANDIDATE_COLUMNS)].copy()
    candidate_frame["signal_id"] = candidate_frame["signal_id"].astype(str)
    if candidate_frame["signal_id"].duplicated().any():
        raise ValueError("close-proxy candidate signal IDs must be unique")
    candidate_frame["vt_symbol"] = candidate_frame["vt_symbol"].astype(str)
    candidate_frame["signal_date"] = pd.to_datetime(
        candidate_frame["signal_date"],
        errors="raise",
    ).dt.date
    candidate_frame["exit_date"] = pd.to_datetime(
        candidate_frame["exit_date"],
        errors="raise",
    ).dt.date
    candidate_frame["causal_rank"] = pd.to_numeric(
        candidate_frame["causal_rank"],
        errors="raise",
    ).astype(int)
    candidate_frame["reference_peak_price"] = pd.to_numeric(
        candidate_frame["reference_peak_price"],
        errors="raise",
    )

    close_frame = daily_bars.loc[
        :, ["vt_symbol", "trade_date", "close_price"]
    ].copy()
    close_frame["vt_symbol"] = close_frame["vt_symbol"].astype(str)
    close_frame["signal_date"] = pd.to_datetime(
        close_frame.pop("trade_date"),
        errors="raise",
    ).dt.date
    close_frame["entry_price_raw_override"] = pd.to_numeric(
        close_frame.pop("close_price"),
        errors="raise",
    )
    if close_frame.duplicated(["vt_symbol", "signal_date"]).any():
        raise ValueError("close-proxy daily bar identities must be unique")

    merged = candidate_frame.merge(
        close_frame,
        on=["vt_symbol", "signal_date"],
        how="left",
        validate="many_to_one",
    )
    missing = merged["entry_price_raw_override"].isna()
    if missing.any():
        identities = ", ".join(merged.loc[missing, "signal_id"].astype(str))
        raise ValueError(f"missing signal-day close for: {identities}")
    invalid_price = merged["entry_price_raw_override"].le(0)
    if invalid_price.any():
        raise ValueError("signal-day close prices must be positive")
    not_below_peak = merged["entry_price_raw_override"].ge(
        merged["reference_peak_price"]
    )
    if not_below_peak.any():
        raise ValueError("signal-day close must remain below the reference peak")

    merged["entry_date"] = merged["signal_date"]
    merged["exit_price_mode"] = "close"
    columns = (
        "signal_id",
        "vt_symbol",
        "sector_id",
        "entry_date",
        "exit_date",
        "causal_rank",
        "entry_price_raw_override",
        "exit_price_mode",
    )
    return merged.loc[:, list(columns)].sort_values(
        ["entry_date", "causal_rank", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_close_study_report(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> dict[str, Any]:
    """Build the complete daily-only report from already-loaded frames."""

    _require_columns(candidates, CASE_COLUMNS, "close-proxy case candidate")
    trades = build_close_proxy_trades(candidates, daily_bars)
    capacity_comparison = simulate_capacity_comparison(trades, daily_bars)
    four_position = simulate_structural_cash_account(
        trades,
        daily_bars,
        capacity=PORTFOLIO_CAPACITY,
    )
    trade_ledger = pd.DataFrame.from_records(four_position["trade_ledger"])
    time_blocks = summarize_close_trade_segments(candidates, trade_ledger)
    cases = _build_case_ledger(candidates, trade_ledger)

    return {
        "study_version": STUDY_VERSION,
        "research_status": RESEARCH_STATUS,
        "formal_strategy": False,
        "formal_metrics": None,
        "contract": {
            "universe": "frozen main-board main-rise concept causal Top3 proxy",
            "candidate_count": int(len(candidates)),
            "pullback": (
                "first stabilized MA5 reclaim after two confirmed higher highs "
                "and a visible 5 percent pullback"
            ),
            "recognition_gate": "strong_days_ge_9_5pct >= 1",
            "bar_interval": "1d",
            "fund_cycle_used": False,
            "minute_bars_used": False,
            "observation": "signal confirmed from the completed D daily bar",
            "entry": "signal_day_close",
            "entry_execution_assumption": EXECUTION_ASSUMPTION,
            "point_in_time_executable": False,
            "holding_style": "multi_session_structural",
            "exit": {
                "take_profit": "reference_peak_rebreak",
                "defensive": "two_closes_below_ma20",
                "execution": "structural_trigger_day_close",
            },
            "portfolio": {
                "initial_cash": INITIAL_CASH,
                "capacity": PORTFOLIO_CAPACITY,
                "position_target": (
                    "current equity / 4, 100-share lots, no leverage"
                ),
                "concept_limit": 1,
            },
        },
        "coverage": {
            "candidate_rows": int(len(candidates)),
            "daily_close_entry_rows": int(len(trades)),
            "four_position_closed_rows": int(four_position["closed_trades"]),
            "minute_rows_read": 0,
            "fund_cycle_rows_read": 0,
        },
        "capacity_comparison": capacity_comparison,
        "four_position_performance": four_position,
        "time_block_segments": time_blocks,
        "individual_case_ledger": cases,
        "qualification": _qualification(four_position, time_blocks),
        "input_fingerprints": _input_fingerprints(
            candidates=candidates,
            daily_bars=daily_bars,
            trades=trades,
            trade_ledger=trade_ledger,
        ),
        "boundaries": [
            "all 35 historical candidates and all five time blocks were already viewed",
            (
                "same_close_research_proxy uses the completed D close both to confirm "
                "the signal and to price the entry"
            ),
            (
                "the same-close convention is not a point-in-time executable fill and "
                "must not be presented as broker execution"
            ),
            "current concept memberships remain a survivorship proxy",
            "causal Top3 did not pass the prior absolute historical identity gate",
            "minute bars, fund cycles, GOLD/SILVER and volume do not select candidates",
            "formal win rate, return and compounding remain null",
        ],
        "reproduce": (
            "docker compose run --rm --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api "
            "python -m alphaagent.server.services.low_suction.cli "
            "v2-leader-ma5-close-study --format markdown"
        ),
    }


def run_leader_ma5_close_study() -> dict[str, Any]:
    """Load the frozen cohort and daily bars, then run the fixed study."""

    from .leader_ma5_scheme_study import (
        _load_scheme_daily_bars,
        load_frozen_scheme_candidates,
    )

    candidates = load_frozen_scheme_candidates()
    daily_bars = _load_scheme_daily_bars(candidates)
    return build_close_study_report(candidates, daily_bars)


def summarize_close_trade_segments(
    candidates: pd.DataFrame,
    trade_ledger: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Summarize the fixed pooled cohort and five existing time blocks."""

    _require_columns(
        candidates,
        ("signal_id", "time_block"),
        "close-proxy segment candidate",
    )
    _require_columns(
        trade_ledger,
        ("signal_id", "status", "net_return_pct"),
        "close-proxy trade ledger",
    )
    blocks = candidates.loc[:, ["signal_id", "time_block"]].copy()
    blocks["signal_id"] = blocks["signal_id"].astype(str)
    if blocks["signal_id"].duplicated().any():
        raise ValueError("close-proxy segment signal IDs must be unique")
    ledger = trade_ledger.loc[:, ["signal_id", "status", "net_return_pct"]].copy()
    ledger["signal_id"] = ledger["signal_id"].astype(str)
    if ledger["signal_id"].duplicated().any():
        raise ValueError("close-proxy ledger signal IDs must be unique")
    panel = ledger.merge(blocks, on="signal_id", how="left", validate="one_to_one")
    if panel["time_block"].isna().any():
        raise ValueError("close-proxy ledger contains unknown signal IDs")

    result = {"all": _summarize_returns(panel)}
    result.update(
        {
            block_id: _summarize_returns(
                panel.loc[panel["time_block"].eq(block_id)]
            )
            for block_id in TIME_BLOCK_IDS
        }
    )
    return result


def render_leader_ma5_close_json(report: Mapping[str, Any]) -> str:
    """Render one deterministic JSON artifact."""

    return json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    ) + "\n"


def render_leader_ma5_close_markdown(report: Mapping[str, Any]) -> str:
    """Render the same report as a compact human-auditable ledger."""

    contract = _mapping(report.get("contract"), "contract")
    coverage = _mapping(report.get("coverage"), "coverage")
    four_position = _mapping(
        report.get("four_position_performance"),
        "four-position performance",
    )
    lines = [
        "# AlphaAgent Leader MA5 Daily-close Low-suction Study",
        "",
        f"Research status: `{report['research_status']}`.",
        "Formal strategy/metrics: `false/null`.",
        "",
        "## Contract",
        "",
        f"- Bar interval: `{contract['bar_interval']}`.",
        f"- Recognition: `{contract['recognition_gate']}`.",
        f"- Entry: `{contract['entry']}`.",
        f"- Entry assumption: `{contract['entry_execution_assumption']}`.",
        f"- Exit: `{contract['exit']['execution']}` after the fixed structural trigger.",
        f"- Fund-cycle rows read: `{coverage['fund_cycle_rows_read']}`.",
        f"- Minute rows read: `{coverage['minute_rows_read']}`.",
        "- This is not a point-in-time executable fill.",
        "",
        "## Coverage",
        "",
        f"- Frozen candidates: `{coverage['candidate_rows']}`.",
        f"- Daily-close entries: `{coverage['daily_close_entry_rows']}`.",
        f"- Closed four-position trades: `{coverage['four_position_closed_rows']}`.",
        "",
        "## Fixed-capacity Cash Accounts",
        "",
        "| Capacity | Accepted | Skipped | Final equity | Compound | Drawdown | Win | Fees |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    comparison = _mapping(report.get("capacity_comparison"), "capacity comparison")
    for capacity in range(1, 5):
        metrics = _mapping(comparison.get(f"capacity_{capacity}"), "capacity result")
        lines.append(
            f"| `{capacity}` | {metrics['accepted_entries']} | {metrics['skipped_entries']} "
            f"| {metrics['final_equity']:.2f} | {metrics['compound_return_pct']:.4f}% "
            f"| {metrics['maximum_drawdown_pct']:.4f}% | "
            f"{_percent(metrics['cash_win_rate_pct'])} | {metrics['total_fees']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Four-position Result",
            "",
            f"- Closed/winning: `{four_position['closed_trades']}/"
            f"{four_position['winning_trades']}`.",
            f"- Win rate: `{four_position['cash_win_rate_pct']:.4f}%`.",
            f"- Compound return: `{four_position['compound_return_pct']:.4f}%`.",
            f"- Maximum drawdown: `{four_position['maximum_drawdown_pct']:.4f}%`.",
            "",
            "## Time-block Stability",
            "",
            "| Block | Signals | Closed | Win | Mean | PF |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    segments = _mapping(report.get("time_block_segments"), "time-block segments")
    for block_id in ("all", *TIME_BLOCK_IDS):
        metrics = _mapping(segments.get(block_id), "time-block result")
        lines.append(
            f"| `{block_id}` | {metrics['signals']} | {metrics['closed_trades']} "
            f"| {_percent(metrics['win_rate_pct'])} "
            f"| {_percent(metrics['mean_net_return_pct'])} "
            f"| {_decimal(metrics['profit_factor'])} |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Date | Stock | Concept | Rank | Entry close | Exit close | Net |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for case in report.get("individual_case_ledger", []):
        row = _mapping(case, "case")
        lines.append(
            f"| {row['signal_date']} | {row['stock_name']} `{row['vt_symbol']}` "
            f"| {row['concept_name']} | {row['causal_rank']} "
            f"| {row['entry_price_raw']:.2f} | {row['exit_price_raw']:.2f} "
            f"| {row['net_return_pct']:.4f}% |"
        )
    lines.extend(["", "## Boundaries", ""])
    lines.extend(f"- {boundary}" for boundary in report.get("boundaries", []))
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report["reproduce"]),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _build_case_ledger(
    candidates: pd.DataFrame,
    trade_ledger: pd.DataFrame,
) -> list[dict[str, Any]]:
    candidate_frame = candidates.loc[:, list(CASE_COLUMNS)].copy()
    candidate_frame["signal_id"] = candidate_frame["signal_id"].astype(str)
    ledger = trade_ledger.copy()
    ledger["signal_id"] = ledger["signal_id"].astype(str)
    panel = candidate_frame.merge(
        ledger,
        on="signal_id",
        how="left",
        validate="one_to_one",
        suffixes=("", "_cash"),
    )
    if panel["status"].isna().any():
        raise ValueError("close-proxy case is missing from the cash ledger")
    rows = []
    for row in panel.sort_values(
        ["signal_date", "causal_rank", "signal_id"],
        kind="stable",
    ).to_dict("records"):
        rows.append(
            {
                "signal_id": str(row["signal_id"]),
                "signal_date": pd.Timestamp(row["signal_date"]).date(),
                "vt_symbol": str(row["vt_symbol"]),
                "stock_name": str(row["stock_name"]),
                "sector_id": str(row["sector_id"]),
                "concept_name": str(row["concept_name"]),
                "time_block": str(row["time_block"]),
                "causal_rank": int(row["causal_rank"]),
                "reference_peak_price": float(row["reference_peak_price"]),
                "exit_trigger_reason": str(row["executable_exit_reason"]),
                "entry_date": row["entry_date"],
                "entry_price_raw": _required_number(row["entry_price_raw"]),
                "entry_price": _required_number(row["entry_price"]),
                "planned_exit_date": row["planned_exit_date"],
                "actual_exit_date": row["actual_exit_date"],
                "exit_price_raw": _required_number(row["exit_price_raw"]),
                "exit_price": _required_number(row["exit_price"]),
                "status": str(row["status"]),
                "total_fees": _required_number(row["total_fees"]),
                "net_return_pct": _required_number(row["net_return_pct"]),
            }
        )
    return rows


def _summarize_returns(frame: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(frame["net_return_pct"], errors="coerce")
    closed = returns.loc[frame["status"].eq("closed") & returns.notna()]
    losses = abs(float(closed.loc[closed.lt(0)].sum()))
    return {
        "signals": int(len(frame)),
        "closed_trades": int(len(closed)),
        "win_rate_pct": float(closed.gt(0).mean() * 100.0) if len(closed) else None,
        "mean_net_return_pct": float(closed.mean()) if len(closed) else None,
        "profit_factor": (
            float(closed.loc[closed.gt(0)].sum()) / losses if losses > 0 else None
        ),
    }


def _qualification(
    performance: Mapping[str, Any],
    segments: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    material_blocks = [
        metrics
        for block_id, metrics in segments.items()
        if block_id != "all" and int(metrics["closed_trades"]) >= 3
    ]
    checks = {
        "win_rate_strictly_above_60": float(performance["cash_win_rate_pct"]) > 60,
        "compound_return_strictly_above_60": (
            float(performance["compound_return_pct"]) > 60
        ),
        "maximum_drawdown_not_below_minus_10": (
            float(performance["maximum_drawdown_pct"]) >= -10
        ),
        "all_observed_blocks_win_rate_strictly_above_60": all(
            metrics["win_rate_pct"] is not None
            and float(metrics["win_rate_pct"]) > 60
            for metrics in material_blocks
        ),
    }
    return {
        "qualified": False,
        "checks": checks,
        "decision": "historical_proxy_only_forward_validation_required",
    }


def _input_fingerprints(**frames: pd.DataFrame) -> dict[str, Any]:
    identities = {
        "candidates": ("signal_id",),
        "daily_bars": ("vt_symbol", "trade_date"),
        "trades": ("signal_id",),
        "trade_ledger": ("signal_id",),
    }
    return {
        label: fingerprint_frame(
            frame,
            identity_columns=identities[label],
        ).as_dict()
        for label, frame in frames.items()
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_number(value: object) -> float:
    if value is None or pd.isna(value):
        raise ValueError("closed close-proxy trade metric is missing")
    return float(value)


def _percent(value: object) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _decimal(value: object) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value).date().isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
