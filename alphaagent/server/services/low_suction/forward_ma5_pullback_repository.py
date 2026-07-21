"""Persistence and orchestration for the strict forward MA5 shadow ledger."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, insert, or_, select, update

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff

from .forward_leader_identity import FORWARD_LEADER_RANKING_VERSION
from .forward_leader_identity_repository import load_forward_leader_ledger_report
from .forward_ma5_pullback import (
    FORWARD_MA5_CONTRACT_VERSION,
    ForwardMa5Capture,
    ForwardMa5Inputs,
    build_forward_ma5_capture,
    evaluate_forward_ma5_outcomes,
)
from .leader_identity import LeaderIdentityMode

MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3_000
STOCK_HISTORY_BUFFER_DAYS = 120
MIN_SELECTION_BOUND_SESSIONS = 60
STOCK_BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "change_pct",
    "source",
)


class ForwardMa5LedgerImmutableError(RuntimeError):
    """Raised when complete forward evidence would be rewritten."""


@dataclass(frozen=True)
class ForwardMa5SaveResult:
    status: str
    rows_written: int
    scopes_written: int
    input_fingerprint: str


def save_forward_ma5_capture(capture: ForwardMa5Capture) -> ForwardMa5SaveResult:
    """Freeze a complete capture once; blocked scopes may later recover."""

    _validate_capture(capture)
    engine = get_engine()
    schema.ensure_schema_once(engine)
    candidates = schema.low_suction_forward_ma5_candidates
    scopes = schema.low_suction_forward_ma5_scopes
    with session_scope() as session:
        existing = session.execute(
            select(
                scopes.c.identity_mode,
                scopes.c.complete,
                scopes.c.input_fingerprint,
            ).where(
                scopes.c.contract_version == capture.contract_version,
                scopes.c.signal_trade_date == capture.signal_trade_date,
            )
        ).mappings().all()
        decision = _existing_capture_decision(existing, capture)
        if decision is not None:
            return ForwardMa5SaveResult(
                status=decision,
                rows_written=0,
                scopes_written=0,
                input_fingerprint=capture.input_fingerprint,
            )
        if existing:
            session.execute(
                delete(candidates).where(
                    candidates.c.contract_version == capture.contract_version,
                    candidates.c.signal_trade_date == capture.signal_trade_date,
                )
            )
            session.execute(
                delete(scopes).where(
                    scopes.c.contract_version == capture.contract_version,
                    scopes.c.signal_trade_date == capture.signal_trade_date,
                )
            )
        if capture.rows:
            session.execute(insert(candidates), [asdict(row) for row in capture.rows])
        session.execute(insert(scopes), [asdict(scope) for scope in capture.scopes])
    return ForwardMa5SaveResult(
        status="frozen" if capture.complete else "blocked",
        rows_written=len(capture.rows),
        scopes_written=len(capture.scopes),
        input_fingerprint=capture.input_fingerprint,
    )


def save_forward_ma5_outcomes(outcomes: pd.DataFrame) -> dict[str, int]:
    """Insert new outcome states and advance only nonterminal existing rows."""

    if outcomes.empty:
        return {"inserted": 0, "updated": 0, "terminal_preserved": 0}
    required = {
        "contract_version",
        "signal_trade_date",
        "identity_mode",
        "vt_symbol",
        "candidate_input_fingerprint",
        "terminal",
        "status",
    }
    _require_columns(outcomes, required, "forward MA5 outcome")
    engine = get_engine()
    schema.ensure_schema_once(engine)
    table = schema.low_suction_forward_ma5_outcomes
    counts = {"inserted": 0, "updated": 0, "terminal_preserved": 0}
    with session_scope() as session:
        for raw in outcomes.to_dict("records"):
            values = _outcome_values(raw)
            identity = _outcome_identity_predicate(table, values)
            existing_rows = session.execute(select(table).where(identity)).mappings().all()
            if len(existing_rows) > 1:
                raise ForwardMa5LedgerImmutableError(
                    "forward MA5 outcome identity is duplicated"
                )
            if not existing_rows:
                session.execute(insert(table).values(**values))
                counts["inserted"] += 1
                continue
            existing = existing_rows[0]
            if str(existing.get("candidate_input_fingerprint") or "") != str(
                values["candidate_input_fingerprint"]
            ):
                raise ForwardMa5LedgerImmutableError(
                    "forward MA5 outcome candidate fingerprint changed"
                )
            if bool(existing.get("terminal")):
                counts["terminal_preserved"] += 1
                continue
            session.execute(update(table).where(identity).values(**values))
            counts["updated"] += 1
    return counts


def load_forward_ma5_inputs(
    source_trade_date: date,
    signal_trade_date: date,
    *,
    attempted_at: datetime,
) -> ForwardMa5Inputs:
    """Load one exact S->D pair and diagnostics observed no later than attempted_at."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    statements = _capture_statements(
        source_trade_date=source_trade_date,
        signal_trade_date=signal_trade_date,
        attempted_at=attempted_at,
    )
    with session_scope() as session:
        loaded = {
            name: session.execute(statement).mappings().all()
            for name, statement in statements.items()
        }
        completed_dates = tuple(
            session.execute(
                _completed_dates_statement(
                    signal_trade_date,
                    start=signal_trade_date - timedelta(days=STOCK_HISTORY_BUFFER_DAYS),
                )
            ).scalars()
        )

    rank_history = pd.DataFrame(loaded["rank_history"])
    scopes_ready = _loaded_scope_rows_are_complete(
        loaded["prior_scopes"],
        loaded["signal_scopes"],
    )
    symbols = sorted(
        set(
            rank_history.loc[
                rank_history.get("target_trade_date", pd.Series(dtype=object)).eq(
                    signal_trade_date
                )
                & rank_history.get("is_top3", pd.Series(dtype=bool)).astype(bool),
                "vt_symbol",
            ].astype(str)
        )
        if scopes_ready and not rank_history.empty and "vt_symbol" in rank_history
        else set()
    )
    stock_start = signal_trade_date - timedelta(days=STOCK_HISTORY_BUFFER_DAYS)
    with session_scope() as session:
        stock_rows = session.execute(
            _stock_bars_statement(
                symbols,
                start=stock_start,
                end=signal_trade_date,
            )
        ).mappings().all()

    selected_mode, _selection_status = _identity_selection(signal_trade_date)
    return ForwardMa5Inputs(
        source_trade_date=source_trade_date,
        signal_trade_date=signal_trade_date,
        attempted_at=attempted_at,
        prior_scopes=pd.DataFrame(loaded["prior_scopes"]),
        signal_scopes=pd.DataFrame(loaded["signal_scopes"]),
        rank_history=rank_history,
        stock_bars=pd.DataFrame(stock_rows, columns=STOCK_BAR_COLUMNS),
        stock_fund_flows=pd.DataFrame(loaded["stock_fund_flows"]),
        sector_fund_flow_snapshots=pd.DataFrame(loaded["sector_fund_flows"]),
        market_timing_rows=_timing_frame(loaded["market_timing_panel"], signal_trade_date),
        completed_dates=completed_dates,
        selected_mode=selected_mode,
    )


def settle_forward_ma5_outcomes(*, as_of_date: date) -> dict[str, int]:
    """Advance every saved signal through the latest completed daily session."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    candidates = schema.low_suction_forward_ma5_candidates
    with session_scope() as session:
        candidate_rows = session.execute(
            select(candidates)
            .where(
                candidates.c.contract_version == FORWARD_MA5_CONTRACT_VERSION,
                candidates.c.signal_eligible.is_(True),
                candidates.c.signal_trade_date <= as_of_date,
            )
            .order_by(
                candidates.c.signal_trade_date,
                candidates.c.identity_mode,
                candidates.c.vt_symbol,
            )
        ).mappings().all()
        if not candidate_rows:
            return {
                "evaluated": 0,
                "inserted": 0,
                "updated": 0,
                "terminal_preserved": 0,
            }
        start = min(row["spell_anchor_date"] for row in candidate_rows) - timedelta(
            days=STOCK_HISTORY_BUFFER_DAYS
        )
        completed_dates = tuple(
            session.execute(
                _completed_dates_statement(as_of_date, start=start)
            ).scalars()
        )
        symbols = sorted({str(row["vt_symbol"]) for row in candidate_rows})
        stock_rows = session.execute(
            _stock_bars_statement(symbols, start=start, end=as_of_date)
        ).mappings().all()
    outcomes = evaluate_forward_ma5_outcomes(
        pd.DataFrame(candidate_rows),
        pd.DataFrame(stock_rows, columns=STOCK_BAR_COLUMNS),
        completed_dates=completed_dates,
    )
    saved = save_forward_ma5_outcomes(outcomes)
    return {"evaluated": int(len(outcomes)), **saved}


def advance_forward_ma5_shadow(
    *,
    as_of_date: date,
    attempted_at: datetime,
) -> dict[str, object]:
    """Freeze all available S->D pairs, then advance their later outcomes."""

    pairs = _eligible_source_pairs(as_of_date)
    captures = []
    blocking_reasons: set[str] = set()
    for source_date, signal_date in pairs:
        inputs = load_forward_ma5_inputs(
            source_date,
            signal_date,
            attempted_at=attempted_at,
        )
        capture = build_forward_ma5_capture(inputs)
        saved = save_forward_ma5_capture(capture)
        captures.append(
            {
                "source_trade_date": source_date.isoformat(),
                "signal_trade_date": signal_date.isoformat(),
                "complete": capture.complete,
                "status": saved.status,
                "rows_written": saved.rows_written,
                "scopes_written": saved.scopes_written,
                "candidate_rows": len(capture.rows),
                "signal_rows": sum(row.signal_eligible for row in capture.rows),
                "input_fingerprint": capture.input_fingerprint,
            }
        )
        blocking_reasons.update(
            str(scope.raw.get("blocking_reason"))
            for scope in capture.scopes
            if scope.raw.get("blocking_reason")
        )
    outcome_result = settle_forward_ma5_outcomes(as_of_date=as_of_date)
    return {
        "contract_version": FORWARD_MA5_CONTRACT_VERSION,
        "as_of_date": as_of_date.isoformat(),
        "source_pairs": len(pairs),
        "captures": captures,
        "blocking_reasons": sorted(blocking_reasons),
        "outcomes": outcome_result,
        "recommendations_created": 0,
        "orders_created": 0,
        "formal_metrics": None,
    }


def load_forward_ma5_shadow_report(
    *,
    as_of_date: date | None = None,
) -> dict[str, object]:
    """Load a deterministic read-only coverage and descriptive shadow report."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    cutoff = as_of_date or completed_daily_bar_cutoff()
    scopes_table = schema.low_suction_forward_ma5_scopes
    candidates_table = schema.low_suction_forward_ma5_candidates
    outcomes_table = schema.low_suction_forward_ma5_outcomes
    with session_scope() as session:
        scope_rows = session.execute(
            select(scopes_table)
            .where(scopes_table.c.contract_version == FORWARD_MA5_CONTRACT_VERSION)
            .order_by(scopes_table.c.signal_trade_date, scopes_table.c.identity_mode)
        ).mappings().all()
        candidate_rows = session.execute(
            select(candidates_table)
            .where(
                candidates_table.c.contract_version == FORWARD_MA5_CONTRACT_VERSION,
                candidates_table.c.signal_trade_date <= cutoff,
            )
            .order_by(
                candidates_table.c.signal_trade_date,
                candidates_table.c.identity_mode,
                candidates_table.c.vt_symbol,
            )
        ).mappings().all()
        outcome_rows = session.execute(
            select(outcomes_table)
            .where(
                outcomes_table.c.contract_version == FORWARD_MA5_CONTRACT_VERSION,
                outcomes_table.c.signal_trade_date <= cutoff,
            )
            .order_by(
                outcomes_table.c.signal_trade_date,
                outcomes_table.c.identity_mode,
                outcomes_table.c.vt_symbol,
            )
        ).mappings().all()
    selected_mode, selection_status = _identity_selection(cutoff)
    return build_forward_ma5_shadow_report(
        pd.DataFrame(scope_rows),
        pd.DataFrame(candidate_rows),
        pd.DataFrame(outcome_rows),
        selected_mode=selected_mode,
        selection_status=selection_status,
        as_of_date=cutoff,
    )


def build_forward_ma5_shadow_report(
    scopes: pd.DataFrame,
    candidates: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    selected_mode: str | None,
    selection_status: str,
    as_of_date: date,
) -> dict[str, object]:
    complete_dates = _scope_dates(scopes, complete=True)
    blocked_dates = _scope_dates(scopes, complete=False)
    signals = (
        candidates.loc[candidates["signal_eligible"].astype(bool)].copy()
        if not candidates.empty and "signal_eligible" in candidates
        else pd.DataFrame()
    )
    closed = (
        outcomes.loc[outcomes["status"].eq("closed")].copy()
        if not outcomes.empty and "status" in outcomes
        else pd.DataFrame()
    )
    net = (
        pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
        if not closed.empty
        else pd.Series(dtype=float)
    )
    blocking_reasons = sorted(
        {
            str(raw.get("blocking_reason"))
            for raw in scopes.get("raw", pd.Series(dtype=object))
            if isinstance(raw, Mapping) and raw.get("blocking_reason")
        }
    )
    return {
        "contract_version": FORWARD_MA5_CONTRACT_VERSION,
        "research_status": (
            "blocked_by_strict_forward_inputs"
            if blocked_dates and not complete_dates
            else "accumulating_forward_ma5_shadow"
        ),
        "as_of_date": as_of_date.isoformat(),
        "selection_status": selection_status,
        "selected_mode": selected_mode,
        "coverage": {
            "scope_rows": int(len(scopes)),
            "complete_signal_sessions": len(complete_dates),
            "blocked_signal_sessions": len(blocked_dates),
            "candidate_rows": int(len(candidates)),
            "signal_rows": int(len(signals)),
            "outcome_rows": int(len(outcomes)),
            "closed_outcomes": int(len(closed)),
            "open_outcomes": int(
                outcomes.get("status", pd.Series(dtype=str)).eq("open").sum()
            ),
            "awaiting_entry_outcomes": int(
                outcomes.get("status", pd.Series(dtype=str)).eq("awaiting_entry").sum()
            ),
            "right_censored_outcomes": int(
                outcomes.get("status", pd.Series(dtype=str)).eq("right_censored").sum()
            ),
        },
        "blocking_reasons": blocking_reasons,
        "identity_mode_summary": _mode_summary(candidates, outcomes),
        "descriptive_closed_shadow": {
            "closed": int(len(net)),
            "positive_share_pct": (
                float(net.gt(0).mean() * 100.0) if not net.empty else None
            ),
            "mean_net_return_pct": float(net.mean()) if not net.empty else None,
        },
        "diagnostic_coverage": {
            "stock_fund_flow_rows": _notna_count(candidates, "stock_fund_flow_known_at"),
            "sector_fund_flow_rows": _notna_count(candidates, "sector_fund_flow_known_at"),
            "market_timing_rows": _notna_count(candidates, "market_timing_known_at"),
            "diagnostics_used_for_signal": False,
        },
        "input_fingerprints": sorted(
            set(scopes.get("input_fingerprint", pd.Series(dtype=str)).dropna().astype(str))
        ),
        "formal_metrics": {
            "top3_mode": None,
            "win_rate_pct": None,
            "average_net_return_pct": None,
            "compounded_return_pct": None,
            "profit_factor": None,
            "maximum_drawdown_pct": None,
        },
        "boundaries": [
            "strict forward only; no proxy-history backfill",
            "all three identity modes remain isolated until the 60-session gate",
            "fund flow and market timing are diagnostics, never signal inputs",
            "descriptive closed shadow is not formal low-suction performance",
        ],
    }


def render_forward_ma5_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_forward_ma5_markdown(report: Mapping[str, Any]) -> str:
    coverage = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
    formal = report.get("formal_metrics")
    lines = [
        "# AlphaAgent 多浪龙头 MA5 前向影子账本",
        "",
        f"研究状态：`{report.get('research_status')}`；截至 `{report.get('as_of_date')}`。",
        f"身份选择：`{report.get('selection_status')}`；selected_mode："
        f"`{report.get('selected_mode') or 'null'}`。",
        "正式 Top3、胜率、收益、复利、利润因子和回撤：`null`。",
        "",
        "## Coverage",
        "",
        f"- 完整/阻断信号日：`{coverage.get('complete_signal_sessions', 0)}` / "
        f"`{coverage.get('blocked_signal_sessions', 0)}`。",
        f"- 候选/信号：`{coverage.get('candidate_rows', 0)}` / "
        f"`{coverage.get('signal_rows', 0)}`。",
        f"- 结果/闭合/删失：`{coverage.get('outcome_rows', 0)}` / "
        f"`{coverage.get('closed_outcomes', 0)}` / "
        f"`{coverage.get('right_censored_outcomes', 0)}`。",
        "",
        "## Blocking Reasons",
        "",
    ]
    reasons = report.get("blocking_reasons")
    if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes)) and reasons:
        lines.extend(f"- `{reason}`" for reason in reasons)
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "## Identity Modes",
            "",
            "| Mode | Candidates | Signals | Outcomes | Closed |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("identity_mode_summary", []):
        lines.append(
            f"| `{row.get('identity_mode')}` | {row.get('candidate_rows', 0)} | "
            f"{row.get('signal_rows', 0)} | {row.get('outcome_rows', 0)} | "
            f"{row.get('closed_outcomes', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "本账本只积累自然发生的严格前向证据，不回填当前成员代理历史。",
            "资金流、金银方向和危险状态只做诊断，不改变 MA5 触发。",
            "身份模式冻结并开始新的未见绩效块以前，任何描述性闭合结果都不是正式胜率。",
            "",
        ]
    )
    if formal is not None:
        lines.append("formal_metrics: `null`")
        lines.append("")
    return "\n".join(lines)


def _identity_selection(as_of_date: date) -> tuple[str | None, str]:
    """Avoid the full identity evaluation until its 60-session gate can open."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    scopes = schema.low_suction_forward_leader_rank_snapshot_scopes
    with session_scope() as session:
        rows = session.execute(
            select(
                scopes.c.source_trade_date,
                scopes.c.identity_mode,
                scopes.c.complete,
                scopes.c.target_trade_date,
            ).where(
                scopes.c.ranking_version == FORWARD_LEADER_RANKING_VERSION,
                scopes.c.source_trade_date <= as_of_date,
            )
        ).mappings().all()
    frame = pd.DataFrame(rows)
    if frame.empty:
        return None, "accumulating_forward_identity"
    complete = frame.loc[
        frame["complete"].astype(bool) & frame["target_trade_date"].notna()
    ]
    bound_sessions = int(
        complete.groupby("source_trade_date")["identity_mode"]
        .nunique()
        .eq(len(LeaderIdentityMode))
        .sum()
    )
    if bound_sessions < MIN_SELECTION_BOUND_SESSIONS:
        return None, "accumulating_forward_identity"
    report = load_forward_leader_ledger_report(as_of_date=as_of_date)
    return (
        _optional_text(report.get("selected_mode")),
        str(report.get("selection_status") or "unknown"),
    )


def _loaded_scope_rows_are_complete(
    prior_rows: Sequence[Mapping[str, Any]],
    signal_rows: Sequence[Mapping[str, Any]],
) -> bool:
    expected_modes = {mode.value for mode in LeaderIdentityMode}
    for rows in (prior_rows, signal_rows):
        if len(rows) != len(expected_modes):
            return False
        if {str(row.get("identity_mode") or "") for row in rows} != expected_modes:
            return False
        if not all(bool(row.get("complete")) for row in rows):
            return False
    return True


def _eligible_source_pairs(as_of_date: date) -> tuple[tuple[date, date], ...]:
    engine = get_engine()
    schema.ensure_schema_once(engine)
    scopes = schema.low_suction_forward_leader_rank_snapshot_scopes
    ma5_scopes = schema.low_suction_forward_ma5_scopes
    with session_scope() as session:
        rows = session.execute(
            select(
                scopes.c.source_trade_date,
                scopes.c.target_trade_date,
                func.count(func.distinct(scopes.c.identity_mode)).label("mode_count"),
                func.bool_and(scopes.c.complete).label("all_complete"),
            )
            .where(
                scopes.c.ranking_version == FORWARD_LEADER_RANKING_VERSION,
                scopes.c.target_trade_date.is_not(None),
                scopes.c.target_trade_date <= as_of_date,
            )
            .group_by(scopes.c.source_trade_date, scopes.c.target_trade_date)
            .order_by(scopes.c.target_trade_date)
        ).mappings().all()
        frozen_rows = session.execute(
            select(
                ma5_scopes.c.signal_trade_date,
                func.count(func.distinct(ma5_scopes.c.identity_mode)).label(
                    "mode_count"
                ),
                func.bool_and(ma5_scopes.c.complete).label("all_complete"),
            )
            .where(
                ma5_scopes.c.contract_version == FORWARD_MA5_CONTRACT_VERSION,
                ma5_scopes.c.signal_trade_date <= as_of_date,
            )
            .group_by(ma5_scopes.c.signal_trade_date)
        ).mappings().all()
    expected = len(LeaderIdentityMode)
    complete_signal_dates = {
        row["signal_trade_date"]
        for row in frozen_rows
        if int(row.get("mode_count") or 0) == expected
        and bool(row.get("all_complete"))
    }
    return tuple(
        (row["source_trade_date"], row["target_trade_date"])
        for row in rows
        if int(row["mode_count"] or 0) == expected
        and bool(row["all_complete"])
        and row["target_trade_date"] not in complete_signal_dates
    )


def _capture_statements(
    *,
    source_trade_date: date,
    signal_trade_date: date,
    attempted_at: datetime,
) -> dict[str, object]:
    scopes = schema.low_suction_forward_leader_rank_snapshot_scopes
    ranks = schema.low_suction_forward_leader_rank_snapshots
    return {
        "prior_scopes": select(scopes).where(
            scopes.c.source_trade_date == source_trade_date,
            scopes.c.ranking_version == FORWARD_LEADER_RANKING_VERSION,
        ),
        "signal_scopes": select(scopes).where(
            scopes.c.source_trade_date == signal_trade_date,
            scopes.c.ranking_version == FORWARD_LEADER_RANKING_VERSION,
        ),
        "rank_history": select(ranks).where(
            ranks.c.ranking_version == FORWARD_LEADER_RANKING_VERSION,
            ranks.c.source_trade_date <= signal_trade_date,
            ranks.c.is_top3.is_(True),
            or_(
                ranks.c.target_trade_date <= signal_trade_date,
                ranks.c.source_trade_date == signal_trade_date,
            ),
        ),
        "stock_fund_flows": select(schema.stock_fund_flows).where(
            schema.stock_fund_flows.c.trade_date == signal_trade_date.isoformat(),
            schema.stock_fund_flows.c.period == "即时",
            schema.stock_fund_flows.c.updated_at <= attempted_at,
        ),
        "sector_fund_flows": select(schema.sector_fund_flow_snapshots).where(
            schema.sector_fund_flow_snapshots.c.trade_date == signal_trade_date,
            schema.sector_fund_flow_snapshots.c.period == "即时",
            schema.sector_fund_flow_snapshots.c.captured_at <= attempted_at,
            schema.sector_fund_flow_snapshots.c.is_stale.is_(False),
        ),
        "market_timing_panel": select(
            schema.market_timing_panel.c.panel,
            schema.market_timing_panel.c.computed_at,
        ).where(schema.market_timing_panel.c.computed_at <= attempted_at),
    }


def _completed_dates_statement(cutoff: date, *, start: date | None = None):
    statement = (
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date <= cutoff)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
            >= MIN_COMPLETE_DAILY_SYMBOL_COUNT
        )
        .order_by(schema.stock_daily_bars.c.trade_date)
    )
    if start is not None:
        statement = statement.where(schema.stock_daily_bars.c.trade_date >= start)
    return statement


def _stock_bars_statement(symbols: Sequence[str], *, start: date, end: date):
    return (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover,
            schema.stock_daily_bars.c.change_pct,
            schema.stock_daily_bars.c.source,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(tuple(symbols)),
            schema.stock_daily_bars.c.trade_date.between(start, end),
        )
        .order_by(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date)
    )


def _timing_frame(rows: Sequence[Mapping[str, Any]], signal_date: date) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    latest = sorted(
        rows,
        key=lambda row: row.get("computed_at") or datetime.min,
    )[-1]
    panel = latest.get("panel") if isinstance(latest.get("panel"), Mapping) else {}
    series = panel.get("timing_series") if isinstance(panel, Mapping) else []
    if not isinstance(series, Sequence):
        return pd.DataFrame()
    matches = [
        row
        for row in series
        if isinstance(row, Mapping) and str(row.get("date")) == signal_date.isoformat()
    ]
    if not matches:
        return pd.DataFrame()
    row = dict(matches[-1])
    row["trade_date"] = signal_date
    row["known_at"] = latest.get("computed_at")
    return pd.DataFrame([row])


def _existing_capture_decision(
    existing: Sequence[Mapping[str, Any]],
    capture: ForwardMa5Capture,
) -> str | None:
    if not existing:
        return None
    expected_modes = {scope.identity_mode for scope in capture.scopes}
    existing_modes = {str(row.get("identity_mode") or "") for row in existing}
    if len(existing) != len(expected_modes) or existing_modes != expected_modes:
        raise ForwardMa5LedgerImmutableError(
            "existing forward MA5 scope set is incomplete"
        )
    completeness = {bool(row.get("complete")) for row in existing}
    if len(completeness) != 1:
        raise ForwardMa5LedgerImmutableError(
            "existing forward MA5 scope completeness is inconsistent"
        )
    was_complete = completeness == {True}
    fingerprints = {str(row.get("input_fingerprint") or "") for row in existing}
    if was_complete and not capture.complete:
        return "complete_preserved"
    if was_complete:
        if fingerprints != {capture.input_fingerprint}:
            raise ForwardMa5LedgerImmutableError(
                "complete forward MA5 fingerprint is immutable"
            )
        return "already_frozen"
    if not capture.complete and fingerprints == {capture.input_fingerprint}:
        return "already_blocked"
    return None


def _validate_capture(capture: ForwardMa5Capture) -> None:
    expected_modes = {mode.value for mode in LeaderIdentityMode}
    modes = {scope.identity_mode for scope in capture.scopes}
    if modes != expected_modes or len(capture.scopes) != len(expected_modes):
        raise ValueError("forward MA5 capture requires all identity modes")
    if capture.contract_version != FORWARD_MA5_CONTRACT_VERSION:
        raise ValueError("forward MA5 contract version mismatch")
    if not capture.input_fingerprint.startswith("sha256:"):
        raise ValueError("forward MA5 fingerprint must use sha256")
    if len({scope.complete for scope in capture.scopes}) != 1:
        raise ValueError("forward MA5 scopes must share completeness")
    if not capture.complete and capture.rows:
        raise ValueError("blocked forward MA5 capture cannot contain candidates")
    identities = [
        (row.signal_trade_date, row.identity_mode, row.vt_symbol)
        for row in capture.rows
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("forward MA5 candidate identity must be unique")
    for scope in capture.scopes:
        mode_rows = [row for row in capture.rows if row.identity_mode == scope.identity_mode]
        if (
            scope.contract_version != capture.contract_version
            or scope.source_trade_date != capture.source_trade_date
            or scope.signal_trade_date != capture.signal_trade_date
            or scope.input_fingerprint != capture.input_fingerprint
            or scope.unique_candidate_count != len(mode_rows)
            or scope.signal_count != sum(row.signal_eligible for row in mode_rows)
        ):
            raise ValueError("forward MA5 scope does not match candidate rows")
    for row in capture.rows:
        if (
            row.contract_version != capture.contract_version
            or row.source_trade_date != capture.source_trade_date
            or row.signal_trade_date != capture.signal_trade_date
            or row.input_fingerprint != capture.input_fingerprint
            or row.identity_mode not in modes
        ):
            raise ValueError("forward MA5 candidate identity mismatch")


def _outcome_values(raw: Mapping[str, Any]) -> dict[str, object]:
    columns = {
        column.name
        for column in schema.low_suction_forward_ma5_outcomes.columns
        if column.name not in {"created_at", "updated_at"}
    }
    values = {
        key: _sql_value(value)
        for key, value in raw.items()
        if key in columns
    }
    values.setdefault("raw", {})
    values.setdefault("entry_proxy", "next_completed_session_open")
    return values


def _outcome_identity_predicate(table, values: Mapping[str, object]):
    return (
        (table.c.contract_version == values["contract_version"])
        & (table.c.signal_trade_date == values["signal_trade_date"])
        & (table.c.identity_mode == values["identity_mode"])
        & (table.c.vt_symbol == values["vt_symbol"])
    )


def _sql_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (float, np.floating)) and not np.isfinite(float(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date() if value.tzinfo is None else value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _scope_dates(scopes: pd.DataFrame, *, complete: bool) -> set[date]:
    if scopes.empty or not {"signal_trade_date", "complete"}.issubset(scopes.columns):
        return set()
    matches = scopes.loc[scopes["complete"].astype(bool).eq(complete)]
    counts = matches.groupby("signal_trade_date")["identity_mode"].nunique()
    return set(counts.loc[counts.eq(len(LeaderIdentityMode))].index)


def _mode_summary(
    candidates: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> list[dict[str, object]]:
    rows = []
    for mode in LeaderIdentityMode:
        candidate_group = (
            candidates.loc[candidates["identity_mode"].eq(mode.value)]
            if not candidates.empty
            else pd.DataFrame()
        )
        outcome_group = (
            outcomes.loc[outcomes["identity_mode"].eq(mode.value)]
            if not outcomes.empty
            else pd.DataFrame()
        )
        rows.append(
            {
                "identity_mode": mode.value,
                "candidate_rows": int(len(candidate_group)),
                "signal_rows": int(
                    candidate_group.get("signal_eligible", pd.Series(dtype=bool))
                    .astype(bool)
                    .sum()
                ),
                "outcome_rows": int(len(outcome_group)),
                "closed_outcomes": int(
                    outcome_group.get("status", pd.Series(dtype=str)).eq("closed").sum()
                ),
            }
        )
    return rows


def _notna_count(frame: pd.DataFrame, column: str) -> int:
    return int(frame[column].notna().sum()) if column in frame else 0


def _optional_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _json_safe(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value
