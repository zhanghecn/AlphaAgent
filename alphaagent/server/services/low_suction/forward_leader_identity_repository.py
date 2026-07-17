"""Database loading and immutable persistence for strict forward Top3 identity."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
import numpy as np
from sqlalchemy import delete, func, insert, select, update

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff

from .baostock_security_source import FORWARD_SECURITY_SOURCE
from .concept_cycles import (
    FROZEN_MAIN_RISE_DEFINITION,
    MARKET_BENCHMARK_SYMBOLS,
    build_cycle_candidates,
    build_market_returns,
    load_cycle_research_calendar,
)
from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE
from .contracts import CONCEPT_SECTOR_TYPES
from .forward_leader_identity import (
    FORWARD_LEADER_RANKING_VERSION,
    ForwardLeaderCapture,
    ForwardLeaderRankRow,
    ForwardLeaderRankScope,
    ForwardLeaderSourceInputs,
)
from .forward_membership import FORWARD_MEMBERSHIP_SOURCE, TRADABLE_SCOPE_TYPE
from .leader_identity import LeaderIdentityMode
from .leader_identity import choose_stable_leader_identity
from .universe import is_main_board_symbol

MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3_000
MIN_STOCK_FEATURE_SESSIONS = 60
MIN_SELECTION_BOUND_SESSIONS = 60
SELECTION_FOLDS = 5
MIN_FOLD_RETENTION_OBSERVATIONS = 100
MIN_FOLD_STRONG_EVENT_OBSERVATIONS = 50
STRONG_EVENT_THRESHOLD_PCT = 5.0
STRONG_EVENT_FUTURE_SESSIONS = 5
NO_STRONG_EVENT_SCORE = STRONG_EVENT_FUTURE_SESSIONS + 1


class ForwardLeaderLedgerImmutableError(RuntimeError):
    """Raised when a caller attempts to mutate an already complete freeze."""


@dataclass(frozen=True)
class ForwardLeaderSaveResult:
    status: str
    rows_written: int
    scopes_written: int
    input_fingerprint: str


def load_forward_leader_source_inputs(
    source_trade_date: date,
    *,
    attempted_at: datetime,
) -> ForwardLeaderSourceInputs:
    """Load exact source-date evidence and only the stock history needed to rank."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    trading_dates = load_cycle_research_calendar(as_of_date=source_trade_date)
    base_statements = _source_statements(
        source_trade_date,
        trading_dates=trading_dates,
        vt_symbols=(),
        stock_start=source_trade_date,
    )
    with session_scope() as session:
        membership_scope_row = session.execute(
            base_statements["membership_scope"]
        ).mappings().one_or_none()
        security_scope_row = session.execute(
            base_statements["security_scope"]
        ).mappings().one_or_none()
        membership_rows = session.execute(
            base_statements["membership_rows"]
        ).mappings().all()
        security_rows = session.execute(
            base_statements["security_rows"]
        ).mappings().all()

    concept_bars = pd.read_sql(
        base_statements["concept_bars"],
        engine,
        parse_dates=["trade_date"],
    )
    benchmark_bars = pd.read_sql(
        base_statements["benchmark_bars"],
        engine,
        parse_dates=["trade_date"],
    )
    memberships = pd.DataFrame(membership_rows)
    securities = pd.DataFrame(security_rows)
    active_cycles = _active_cycles_for_loading(
        source_trade_date=source_trade_date,
        trading_dates=trading_dates,
        concept_bars=concept_bars,
        benchmark_bars=benchmark_bars,
        membership_sector_ids=(
            tuple(memberships["sector_id"].astype(str).unique())
            if "sector_id" in memberships
            else ()
        ),
    )
    active_sector_ids = set(active_cycles["sector_id"].astype(str))
    vt_symbols = _active_main_board_symbols(memberships, active_sector_ids)
    stock_start = _stock_history_start(
        trading_dates,
        active_cycles=active_cycles,
        source_trade_date=source_trade_date,
    )
    stock_statement = _stock_bars_statement(
        source_trade_date,
        vt_symbols=vt_symbols,
        stock_start=stock_start,
    )
    stock_bars = pd.read_sql(
        stock_statement,
        engine,
        parse_dates=["trade_date"],
    )
    return ForwardLeaderSourceInputs(
        source_trade_date=source_trade_date,
        attempted_at=attempted_at,
        membership_scope=dict(membership_scope_row or {}),
        security_scope=dict(security_scope_row or {}),
        memberships=memberships,
        securities=securities,
        trading_dates=tuple(trading_dates),
        concept_bars=concept_bars,
        benchmark_bars=benchmark_bars,
        stock_bars=stock_bars,
    )


def save_forward_leader_capture(
    capture: ForwardLeaderCapture,
) -> ForwardLeaderSaveResult:
    """Persist the first complete fingerprint immutably; closed scopes may recover."""

    _validate_capture(capture)
    engine = get_engine()
    schema.ensure_schema_once(engine)
    rows_table = schema.low_suction_forward_leader_rank_snapshots
    scopes_table = schema.low_suction_forward_leader_rank_snapshot_scopes

    with session_scope() as session:
        existing = session.execute(
            select(
                scopes_table.c.identity_mode,
                scopes_table.c.complete,
                scopes_table.c.input_fingerprint,
            ).where(
                scopes_table.c.source_trade_date == capture.source_trade_date,
                scopes_table.c.ranking_version == capture.ranking_version,
            )
        ).mappings().all()
        decision = _existing_capture_decision(existing, capture)
        if decision is not None:
            return ForwardLeaderSaveResult(
                status=decision,
                rows_written=0,
                scopes_written=0,
                input_fingerprint=capture.input_fingerprint,
            )
        if existing:
            session.execute(
                delete(rows_table).where(
                    rows_table.c.source_trade_date == capture.source_trade_date,
                    rows_table.c.ranking_version == capture.ranking_version,
                )
            )
            session.execute(
                delete(scopes_table).where(
                    scopes_table.c.source_trade_date == capture.source_trade_date,
                    scopes_table.c.ranking_version == capture.ranking_version,
                )
            )
        if capture.rows:
            session.execute(
                insert(rows_table),
                [_rank_row_values(row) for row in capture.rows],
            )
        session.execute(
            insert(scopes_table),
            [_scope_values(scope) for scope in capture.scopes],
        )
    return ForwardLeaderSaveResult(
        status="frozen" if capture.complete else "blocked",
        rows_written=len(capture.rows),
        scopes_written=len(capture.scopes),
        input_fingerprint=capture.input_fingerprint,
    )


def resolve_next_completed_session(
    source_trade_date: date,
    completed_dates: Sequence[date],
) -> date | None:
    """Return the first observed completed session after the source date."""

    later = sorted({value for value in completed_dates if value > source_trade_date})
    return later[0] if later else None


def bind_pending_forward_target_sessions(
    *,
    as_of_date: date | None = None,
) -> tuple[dict[str, object], ...]:
    """Bind pending source freezes only after a real complete session exists."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    rows_table = schema.low_suction_forward_leader_rank_snapshots
    scopes_table = schema.low_suction_forward_leader_rank_snapshot_scopes
    cutoff = as_of_date or completed_daily_bar_cutoff()
    daily_counts = (
        select(
            schema.stock_daily_bars.c.trade_date.label("trade_date"),
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)).label(
                "symbol_count"
            ),
        )
        .where(schema.stock_daily_bars.c.trade_date <= cutoff)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(
            func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
            >= MIN_COMPLETE_DAILY_SYMBOL_COUNT
        )
        .subquery()
    )
    with session_scope() as session:
        completed_dates = tuple(
            session.execute(
                select(daily_counts.c.trade_date).order_by(daily_counts.c.trade_date)
            ).scalars()
        )
        pending = session.execute(
            select(
                scopes_table.c.source_trade_date,
                scopes_table.c.ranking_version,
            )
            .where(
                scopes_table.c.complete.is_(True),
                scopes_table.c.target_trade_date.is_(None),
            )
            .distinct()
            .order_by(scopes_table.c.source_trade_date)
        ).all()
        bound: list[dict[str, object]] = []
        for source_date, ranking_version in pending:
            target_date = resolve_next_completed_session(
                source_date,
                completed_dates,
            )
            if target_date is None:
                continue
            row_update = session.execute(
                update(rows_table)
                .where(
                    rows_table.c.source_trade_date == source_date,
                    rows_table.c.ranking_version == ranking_version,
                    rows_table.c.target_trade_date.is_(None),
                )
                .values(target_trade_date=target_date)
            )
            scope_update = session.execute(
                update(scopes_table)
                .where(
                    scopes_table.c.source_trade_date == source_date,
                    scopes_table.c.ranking_version == ranking_version,
                    scopes_table.c.target_trade_date.is_(None),
                )
                .values(
                    target_trade_date=target_date,
                    status="frozen_bound",
                )
            )
            bound.append(
                {
                    "source_trade_date": source_date,
                    "target_trade_date": target_date,
                    "ranking_version": str(ranking_version),
                    "rank_rows": int(row_update.rowcount or 0),
                    "scope_rows": int(scope_update.rowcount or 0),
                }
            )
    return tuple(bound)


def evaluate_forward_leader_ledger(
    scopes: pd.DataFrame,
    ranks: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    completed_dates: Sequence[date],
) -> dict[str, object]:
    """Evaluate identity persistence without reading any low-suction trade outcome."""

    scope_required = {
        "source_trade_date",
        "target_trade_date",
        "ranking_version",
        "identity_mode",
        "complete",
        "input_fingerprint",
    }
    rank_required = {
        "source_trade_date",
        "target_trade_date",
        "identity_mode",
        "sector_id",
        "vt_symbol",
        "rank",
        "is_top3",
        "capacity_passed",
    }
    bar_required = {"vt_symbol", "trade_date", "change_pct", "close_price"}
    _require_columns(scopes, scope_required, "forward leader scope")
    _require_columns(ranks, rank_required, "forward leader rank")
    _require_columns(daily_bars, bar_required, "forward leader strong-event bar")

    scope_frame = scopes.copy()
    rank_frame = ranks.copy()
    bar_frame = daily_bars.copy()
    for frame in (scope_frame, rank_frame):
        frame["source_trade_date"] = pd.to_datetime(
            frame["source_trade_date"], errors="raise"
        ).dt.date
        frame["target_trade_date"] = pd.to_datetime(
            frame["target_trade_date"], errors="coerce"
        ).dt.date
    bar_frame["trade_date"] = pd.to_datetime(
        bar_frame["trade_date"], errors="raise"
    ).dt.date
    if bar_frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("forward leader strong-event bar identity must be unique")

    complete_scopes = scope_frame.loc[scope_frame["complete"].astype(bool)].copy()
    bound_scopes = complete_scopes.loc[
        complete_scopes["target_trade_date"].notna()
    ].copy()
    all_top3 = rank_frame.loc[rank_frame["is_top3"].astype(bool)].copy()
    top3 = all_top3.loc[all_top3["target_trade_date"].notna()].copy()
    top3 = _attach_retention(top3, rank_frame)
    top3 = _attach_strong_event_lead(
        top3,
        bar_frame,
        completed_dates=completed_dates,
    )
    mode_metrics = _summarize_modes(top3, bound_scopes)
    bound_dates = tuple(sorted(bound_scopes["source_trade_date"].unique()))
    selection = _select_forward_mode(top3, bound_dates)
    latest_source = (
        max(complete_scopes["source_trade_date"])
        if not complete_scopes.empty
        else None
    )
    latest_top3 = _latest_top3_records(all_top3, latest_source)
    fingerprints = sorted(
        set(complete_scopes["input_fingerprint"].dropna().astype(str))
    )
    return {
        "ranking_version": (
            str(complete_scopes.iloc[-1]["ranking_version"])
            if not complete_scopes.empty
            else FORWARD_LEADER_RANKING_VERSION
        ),
        "source_sessions": int(
            complete_scopes["source_trade_date"].nunique()
        ),
        "bound_sessions": int(bound_scopes["source_trade_date"].nunique()),
        "latest_source_trade_date": (
            latest_source.isoformat() if latest_source is not None else None
        ),
        "selected_mode": selection["selected_mode"],
        "selection_status": selection["selection_status"],
        "fold_winners": selection["fold_winners"],
        "fold_win_counts": selection["fold_win_counts"],
        "selection_gate": {
            "minimum_bound_sessions": MIN_SELECTION_BOUND_SESSIONS,
            "folds": SELECTION_FOLDS,
            "minimum_fold_retention_observations": (
                MIN_FOLD_RETENTION_OBSERVATIONS
            ),
            "minimum_fold_strong_event_observations": (
                MIN_FOLD_STRONG_EVENT_OBSERVATIONS
            ),
            "criterion": [
                "next_session_top3_retention_desc",
                "strong_event_lead_sessions_asc",
                "capacity_pass_rate_desc",
                "identity_mode_asc",
            ],
        },
        "latest_scope_metrics": _latest_scope_metrics(
            complete_scopes,
            all_top3,
            latest_source,
        ),
        "mode_metrics": mode_metrics,
        "mode_top3_overlap": _mode_top3_overlap(all_top3),
        "latest_top3": latest_top3,
        "input_fingerprints": fingerprints,
        "formal_metrics": None,
        "low_suction_outcomes_read": False,
    }


def load_forward_leader_ledger_report(
    *,
    ranking_version: str = FORWARD_LEADER_RANKING_VERSION,
    as_of_date: date | None = None,
) -> dict[str, object]:
    """Load persisted forward identity evidence and build a read-only report."""

    engine = get_engine()
    schema.ensure_schema_once(engine)
    rows_table = schema.low_suction_forward_leader_rank_snapshots
    scopes_table = schema.low_suction_forward_leader_rank_snapshot_scopes
    cutoff = as_of_date or completed_daily_bar_cutoff()
    with session_scope() as session:
        scope_rows = session.execute(
            select(scopes_table)
            .where(scopes_table.c.ranking_version == ranking_version)
            .order_by(
                scopes_table.c.source_trade_date,
                scopes_table.c.identity_mode,
            )
        ).mappings().all()
        rank_rows = session.execute(
            select(rows_table)
            .where(rows_table.c.ranking_version == ranking_version)
            .order_by(
                rows_table.c.source_trade_date,
                rows_table.c.identity_mode,
                rows_table.c.sector_id,
                rows_table.c.rank,
                rows_table.c.vt_symbol,
            )
        ).mappings().all()
        completed_dates = tuple(
            session.execute(
                select(schema.stock_daily_bars.c.trade_date)
                .where(schema.stock_daily_bars.c.trade_date <= cutoff)
                .group_by(schema.stock_daily_bars.c.trade_date)
                .having(
                    func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol))
                    >= MIN_COMPLETE_DAILY_SYMBOL_COUNT
                )
                .order_by(schema.stock_daily_bars.c.trade_date)
            ).scalars()
        )
        symbols = sorted(
            {
                str(row["vt_symbol"])
                for row in rank_rows
                if bool(row.get("is_top3"))
            }
        )
        target_dates = [
            row.get("target_trade_date")
            for row in rank_rows
            if row.get("target_trade_date") is not None
        ]
        if symbols and target_dates:
            bar_rows = session.execute(
                select(
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stock_daily_bars.c.trade_date,
                    schema.stock_daily_bars.c.change_pct,
                    schema.stock_daily_bars.c.close_price,
                )
                .where(
                    schema.stock_daily_bars.c.vt_symbol.in_(symbols),
                    schema.stock_daily_bars.c.trade_date.between(
                        min(target_dates),
                        cutoff,
                    ),
                )
                .order_by(
                    schema.stock_daily_bars.c.vt_symbol,
                    schema.stock_daily_bars.c.trade_date,
                )
            ).mappings().all()
        else:
            bar_rows = []
    return evaluate_forward_leader_ledger(
        pd.DataFrame(scope_rows, columns=scope_required_columns()),
        pd.DataFrame(rank_rows, columns=rank_required_columns()),
        pd.DataFrame(
            bar_rows,
            columns=("vt_symbol", "trade_date", "change_pct", "close_price"),
        ),
        completed_dates=completed_dates,
    )


def _attach_retention(top3: pd.DataFrame, ranks: pd.DataFrame) -> pd.DataFrame:
    result = top3.copy()
    if result.empty:
        result["retained_top3_next_session"] = pd.Series(dtype="Float64")
        return result
    ranked_top3 = ranks.loc[ranks["is_top3"].astype(bool)].copy()
    ranked_top3["source_trade_date"] = pd.to_datetime(
        ranked_top3["source_trade_date"], errors="raise"
    ).dt.date
    groups = {
        (str(mode), str(sector), source_date): set(group["vt_symbol"].astype(str))
        for (mode, sector, source_date), group in ranked_top3.groupby(
            ["identity_mode", "sector_id", "source_trade_date"],
            sort=False,
        )
    }
    values: list[float] = []
    for row in result.itertuples(index=False):
        key = (
            str(row.identity_mode),
            str(row.sector_id),
            row.target_trade_date,
        )
        next_top3 = groups.get(key)
        values.append(
            np.nan
            if next_top3 is None
            else float(str(row.vt_symbol) in next_top3)
        )
    result["retained_top3_next_session"] = values
    return result


def _attach_strong_event_lead(
    top3: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    completed_dates: Sequence[date],
) -> pd.DataFrame:
    result = top3.copy()
    if result.empty:
        result["strong_event_lead_sessions"] = pd.Series(dtype="Float64")
        return result
    calendar = tuple(sorted(set(completed_dates)))
    positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    changes = {
        (str(row.vt_symbol), row.trade_date): _change_pct(row)
        for row in daily_bars.itertuples(index=False)
    }
    values: list[float] = []
    for row in result.itertuples(index=False):
        target_position = positions.get(row.target_trade_date)
        if (
            target_position is None
            or target_position + STRONG_EVENT_FUTURE_SESSIONS >= len(calendar)
        ):
            values.append(np.nan)
            continue
        score = NO_STRONG_EVENT_SCORE
        for offset in range(STRONG_EVENT_FUTURE_SESSIONS + 1):
            trade_date = calendar[target_position + offset]
            change = changes.get((str(row.vt_symbol), trade_date))
            if change is not None and change >= STRONG_EVENT_THRESHOLD_PCT:
                score = offset
                break
        values.append(float(score))
    result["strong_event_lead_sessions"] = values
    return result


def _summarize_modes(
    top3: pd.DataFrame,
    bound_scopes: pd.DataFrame,
) -> list[dict[str, object]]:
    rows = []
    for mode in LeaderIdentityMode:
        group = top3.loc[top3["identity_mode"].astype(str).eq(mode.value)]
        mode_scopes = bound_scopes.loc[
            bound_scopes["identity_mode"].astype(str).eq(mode.value)
        ]
        retention = pd.to_numeric(
            group.get("retained_top3_next_session"), errors="coerce"
        ).dropna()
        strong_lead = pd.to_numeric(
            group.get("strong_event_lead_sessions"), errors="coerce"
        ).dropna()
        capacity = group["capacity_passed"].astype(bool) if not group.empty else pd.Series(dtype=bool)
        rows.append(
            {
                "identity_mode": mode.value,
                "bound_sessions": int(mode_scopes["source_trade_date"].nunique()),
                "ranked_concept_sessions": int(
                    group[["source_trade_date", "sector_id"]]
                    .drop_duplicates()
                    .shape[0]
                ),
                "top3_observations": int(len(group)),
                "eligible_retention_observations": int(len(retention)),
                "next_session_top3_retention": _mean_or_none(retention),
                "strong_event_lead_observations": int(len(strong_lead)),
                "strong_event_lead_sessions": _median_or_none(strong_lead),
                "strong_event_within_five_rate": _mean_or_none(
                    strong_lead.le(STRONG_EVENT_FUTURE_SESSIONS).astype(float)
                ),
                "capacity_pass_rate": _mean_or_none(capacity.astype(float)),
            }
        )
    return rows


def _select_forward_mode(
    top3: pd.DataFrame,
    bound_dates: Sequence[date],
) -> dict[str, object]:
    if len(bound_dates) < MIN_SELECTION_BOUND_SESSIONS:
        return {
            "selected_mode": None,
            "selection_status": "accumulating_forward_identity",
            "fold_winners": [],
            "fold_win_counts": {},
        }
    fold_winners: list[str | None] = []
    date_arrays = np.array_split(np.array(tuple(bound_dates), dtype=object), SELECTION_FOLDS)
    for values in date_arrays:
        fold_dates = set(values.tolist())
        fold = top3.loc[top3["source_trade_date"].isin(fold_dates)]
        metrics = _summarize_modes(fold, pd.DataFrame(
            {
                "identity_mode": [mode.value for mode in LeaderIdentityMode for _ in fold_dates],
                "source_trade_date": [day for _mode in LeaderIdentityMode for day in fold_dates],
            }
        ))
        eligible = [
            metric
            for metric in metrics
            if int(metric["eligible_retention_observations"])
            >= MIN_FOLD_RETENTION_OBSERVATIONS
            and int(metric["strong_event_lead_observations"])
            >= MIN_FOLD_STRONG_EVENT_OBSERVATIONS
        ]
        if len(eligible) != len(LeaderIdentityMode):
            fold_winners.append(None)
            continue
        winner = sorted(
            eligible,
            key=lambda metric: (
                -float(metric["next_session_top3_retention"]),
                float(metric["strong_event_lead_sessions"]),
                -float(metric["capacity_pass_rate"]),
                str(metric["identity_mode"]),
            ),
        )[0]
        fold_winners.append(str(winner["identity_mode"]))
    selected = choose_stable_leader_identity(fold_winners)
    counts = Counter(winner for winner in fold_winners if winner is not None)
    return {
        "selected_mode": selected.value if selected is not None else None,
        "selection_status": (
            "selected_forward_identity"
            if selected is not None
            else "no_stable_forward_identity"
        ),
        "fold_winners": [
            {"fold": index, "identity_mode": winner}
            for index, winner in enumerate(fold_winners, start=1)
        ],
        "fold_win_counts": dict(sorted(counts.items())),
    }


def _mode_top3_overlap(top3: pd.DataFrame) -> list[dict[str, object]]:
    modes = tuple(mode.value for mode in LeaderIdentityMode)
    rows = []
    for left_index, left_mode in enumerate(modes):
        for right_mode in modes[left_index + 1 :]:
            left = top3.loc[top3["identity_mode"].astype(str).eq(left_mode)]
            right = top3.loc[top3["identity_mode"].astype(str).eq(right_mode)]
            left_groups = {
                (row[0], row[1]): set(group["vt_symbol"].astype(str))
                for row, group in left.groupby(
                    ["source_trade_date", "sector_id"], sort=False
                )
            }
            right_groups = {
                (row[0], row[1]): set(group["vt_symbol"].astype(str))
                for row, group in right.groupby(
                    ["source_trade_date", "sector_id"], sort=False
                )
            }
            shared_keys = sorted(set(left_groups) & set(right_groups))
            overlaps = [
                len(left_groups[key] & right_groups[key])
                / max(len(left_groups[key] | right_groups[key]), 1)
                for key in shared_keys
            ]
            rows.append(
                {
                    "left_mode": left_mode,
                    "right_mode": right_mode,
                    "concept_sessions": len(shared_keys),
                    "mean_top3_jaccard": (
                        round(float(np.mean(overlaps)), 12) if overlaps else None
                    ),
                }
            )
    return rows


def _latest_top3_records(
    top3: pd.DataFrame,
    latest_source: date | None,
) -> list[dict[str, object]]:
    if latest_source is None or top3.empty:
        return []
    latest = top3.loc[top3["source_trade_date"].eq(latest_source)].sort_values(
        ["identity_mode", "sector_id", "rank", "vt_symbol"],
        kind="stable",
    )
    records = []
    for row in latest.to_dict(orient="records"):
        raw = row.get("raw") if isinstance(row.get("raw"), Mapping) else {}
        target_trade_date = row.get("target_trade_date")
        records.append(
            {
                "source_trade_date": latest_source.isoformat(),
                "target_trade_date": (
                    target_trade_date.isoformat()
                    if isinstance(target_trade_date, date)
                    and not pd.isna(target_trade_date)
                    else None
                ),
                "identity_mode": str(row["identity_mode"]),
                "sector_id": str(row["sector_id"]),
                "sector_name": str(row.get("sector_name") or row["sector_id"]),
                "vt_symbol": str(row["vt_symbol"]),
                "stock_name": str(raw.get("stock_name") or ""),
                "rank": int(row["rank"]),
                "capacity_passed": bool(row["capacity_passed"]),
            }
        )
    return records


def _latest_scope_metrics(
    scopes: pd.DataFrame,
    top3: pd.DataFrame,
    latest_source: date | None,
) -> list[dict[str, object]]:
    if latest_source is None:
        return []
    latest_scopes = scopes.loc[scopes["source_trade_date"].eq(latest_source)]
    rows = []
    for mode in LeaderIdentityMode:
        mode_scope = latest_scopes.loc[
            latest_scopes["identity_mode"].astype(str).eq(mode.value)
        ]
        if mode_scope.empty:
            continue
        scope = mode_scope.iloc[0]
        mode_top3 = top3.loc[
            top3["source_trade_date"].eq(latest_source)
            & top3["identity_mode"].astype(str).eq(mode.value)
        ]
        capacity = mode_top3["capacity_passed"].astype(float)
        rows.append(
            {
                "identity_mode": mode.value,
                "active_concept_count": _optional_int_field(
                    scope,
                    "active_concept_count",
                ),
                "main_board_member_count": _optional_int_field(
                    scope,
                    "main_board_member_count",
                ),
                "security_eligible_count": _optional_int_field(
                    scope,
                    "security_eligible_count",
                ),
                "ranked_row_count": _optional_int_field(
                    scope,
                    "ranked_row_count",
                ),
                "top3_row_count": int(len(mode_top3)),
                "excluded_row_count": _optional_int_field(
                    scope,
                    "excluded_row_count",
                ),
                "capacity_pass_rate": _mean_or_none(capacity),
            }
        )
    return rows


def scope_required_columns() -> tuple[str, ...]:
    return (
        "source_trade_date",
        "target_trade_date",
        "ranking_version",
        "identity_mode",
        "complete",
        "status",
        "input_fingerprint",
        "active_concept_count",
        "main_board_member_count",
        "security_eligible_count",
        "ranked_row_count",
        "top3_row_count",
        "excluded_row_count",
    )


def rank_required_columns() -> tuple[str, ...]:
    return (
        "source_trade_date",
        "target_trade_date",
        "ranking_version",
        "identity_mode",
        "sector_id",
        "sector_name",
        "vt_symbol",
        "rank",
        "is_top3",
        "capacity_passed",
        "raw",
    )


def _change_pct(row: object) -> float | None:
    value = getattr(row, "change_pct", None)
    if value is None or pd.isna(value):
        return None
    return float(value)


def _mean_or_none(values: pd.Series) -> float | None:
    return float(values.mean()) if not values.empty else None


def _median_or_none(values: pd.Series) -> float | None:
    return float(values.median()) if not values.empty else None


def _optional_int_field(row: pd.Series, field: str) -> int | None:
    value = row.get(field)
    return None if value is None or pd.isna(value) else int(value)


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: " + ", ".join(missing))


def _source_statements(
    source_trade_date: date,
    *,
    trading_dates: Sequence[date],
    vt_symbols: Sequence[str],
    stock_start: date,
) -> dict[str, object]:
    membership_scopes = schema.low_suction_forward_membership_snapshot_scopes
    membership_rows = schema.low_suction_forward_membership_snapshots
    security_scopes = schema.low_suction_security_snapshot_scopes
    security_rows = schema.low_suction_security_snapshots
    return {
        "membership_scope": select(membership_scopes).where(
            membership_scopes.c.source_trade_date == source_trade_date,
            membership_scopes.c.scope_type == TRADABLE_SCOPE_TYPE,
            membership_scopes.c.source == FORWARD_MEMBERSHIP_SOURCE,
        ),
        "membership_rows": select(membership_rows).where(
            membership_rows.c.source_trade_date == source_trade_date,
            membership_rows.c.source == FORWARD_MEMBERSHIP_SOURCE,
        ),
        "security_scope": select(security_scopes).where(
            security_scopes.c.source_trade_date == source_trade_date,
            security_scopes.c.source == FORWARD_SECURITY_SOURCE,
        ),
        "security_rows": select(security_rows).where(
            security_rows.c.source_trade_date == source_trade_date,
            security_rows.c.source == FORWARD_SECURITY_SOURCE,
        ),
        "concept_bars": (
            select(
                schema.sector_daily_bars.c.sector_id,
                schema.sectors.c.name.label("concept_name"),
                schema.sector_daily_bars.c.trade_date,
                schema.sector_daily_bars.c.close_price,
                schema.sector_daily_bars.c.source,
            )
            .select_from(
                schema.sector_daily_bars.join(
                    schema.sectors,
                    schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
                )
            )
            .where(
                schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
                schema.sector_daily_bars.c.source
                == CANONICAL_CONCEPT_INDEX_SOURCE,
                schema.sector_daily_bars.c.trade_date.in_(tuple(trading_dates)),
            )
            .order_by(
                schema.sector_daily_bars.c.sector_id,
                schema.sector_daily_bars.c.trade_date,
            )
        ),
        "benchmark_bars": (
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.close_price,
                schema.stock_daily_bars.c.source,
            )
            .where(
                schema.stock_daily_bars.c.vt_symbol.in_(MARKET_BENCHMARK_SYMBOLS),
                schema.stock_daily_bars.c.trade_date.in_(tuple(trading_dates)),
            )
            .order_by(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
            )
        ),
        "stock_bars": _stock_bars_statement(
            source_trade_date,
            vt_symbols=vt_symbols,
            stock_start=stock_start,
        ),
    }


def _stock_bars_statement(
    source_trade_date: date,
    *,
    vt_symbols: Sequence[str],
    stock_start: date,
):
    return (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover,
            schema.stock_daily_bars.c.change_pct,
            schema.stock_daily_bars.c.source,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(tuple(vt_symbols)),
            schema.stock_daily_bars.c.trade_date.between(
                stock_start,
                source_trade_date,
            ),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )


def _active_cycles_for_loading(
    *,
    source_trade_date: date,
    trading_dates: Sequence[date],
    concept_bars: pd.DataFrame,
    benchmark_bars: pd.DataFrame,
    membership_sector_ids: Sequence[str],
) -> pd.DataFrame:
    if concept_bars.empty or benchmark_bars.empty or not trading_dates:
        return pd.DataFrame(columns=["sector_id", "cycle_start"])
    try:
        market_returns = build_market_returns(
            benchmark_bars,
            research_dates=trading_dates,
        )
        candidates = build_cycle_candidates(concept_bars, market_returns)
    except ValueError:
        return pd.DataFrame(columns=["sector_id", "cycle_start"])
    return candidates.loc[
        candidates["definition"].eq(FROZEN_MAIN_RISE_DEFINITION)
        & candidates["trade_date"].dt.date.eq(source_trade_date)
        & candidates["in_cycle"].astype(bool)
        & candidates["sector_id"].astype(str).isin(membership_sector_ids)
    ].copy()


def _active_main_board_symbols(
    memberships: pd.DataFrame,
    active_sector_ids: set[str],
) -> tuple[str, ...]:
    if memberships.empty or not active_sector_ids:
        return ()
    selected = memberships.loc[
        memberships["sector_id"].astype(str).isin(active_sector_ids),
        "vt_symbol",
    ]
    result = set()
    for value in selected:
        parts = str(value).upper().rsplit(".", 1)
        if len(parts) == 2 and is_main_board_symbol(parts[0], parts[1]):
            result.add(str(value).upper())
    return tuple(sorted(result))


def _stock_history_start(
    trading_dates: Sequence[date],
    *,
    active_cycles: pd.DataFrame,
    source_trade_date: date,
) -> date:
    dates = tuple(trading_dates)
    if not dates:
        return source_trade_date
    fallback_position = max(0, len(dates) - MIN_STOCK_FEATURE_SESSIONS)
    start_position = fallback_position
    if not active_cycles.empty:
        cycle_starts = set(pd.to_datetime(active_cycles["cycle_start"]).dt.date)
        positions = [index for index, value in enumerate(dates) if value in cycle_starts]
        if positions:
            start_position = min(start_position, max(0, min(positions) - 1))
    return dates[start_position]


def _existing_capture_decision(
    existing: Sequence[Mapping[str, Any]],
    capture: ForwardLeaderCapture,
) -> str | None:
    if not existing:
        return None
    expected_modes = {scope.identity_mode for scope in capture.scopes}
    existing_modes = {str(row.get("identity_mode") or "") for row in existing}
    if len(existing) != len(expected_modes) or existing_modes != expected_modes:
        raise ForwardLeaderLedgerImmutableError(
            "existing forward leader scope set is incomplete"
        )
    existing_complete = {bool(row.get("complete")) for row in existing}
    if len(existing_complete) != 1:
        raise ForwardLeaderLedgerImmutableError(
            "existing forward leader completeness is inconsistent"
        )
    was_complete = existing_complete == {True}
    if was_complete and not capture.complete:
        return "complete_preserved"
    fingerprints = {str(row.get("input_fingerprint") or "") for row in existing}
    if was_complete:
        if fingerprints != {capture.input_fingerprint}:
            raise ForwardLeaderLedgerImmutableError(
                "complete forward leader fingerprint is immutable"
            )
        return "already_frozen"
    if not capture.complete and fingerprints == {capture.input_fingerprint}:
        return "already_blocked"
    return None


def _validate_capture(capture: ForwardLeaderCapture) -> None:
    modes = {scope.identity_mode for scope in capture.scopes}
    expected_modes = {mode.value for mode in LeaderIdentityMode}
    if modes != expected_modes or len(capture.scopes) != len(expected_modes):
        raise ValueError("forward leader capture requires all identity modes")
    if not capture.input_fingerprint.startswith("sha256:"):
        raise ValueError("forward leader capture fingerprint must use sha256")
    if any(
        scope.source_trade_date != capture.source_trade_date
        or scope.ranking_version != capture.ranking_version
        or scope.input_fingerprint != capture.input_fingerprint
        for scope in capture.scopes
    ):
        raise ValueError("forward leader scope identity mismatch")
    if len({scope.complete for scope in capture.scopes}) != 1:
        raise ValueError("forward leader scopes must share completeness")
    if not capture.complete and capture.rows:
        raise ValueError("closed forward leader capture cannot contain rank rows")
    identities = [
        (
            row.source_trade_date,
            row.ranking_version,
            row.identity_mode,
            row.sector_id,
            row.vt_symbol,
        )
        for row in capture.rows
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("forward leader rank row identity must be unique")
    for row in capture.rows:
        if (
            row.source_trade_date != capture.source_trade_date
            or row.ranking_version != capture.ranking_version
            or row.input_fingerprint != capture.input_fingerprint
            or row.identity_mode not in modes
        ):
            raise ValueError("forward leader rank row identity mismatch")
    for scope in capture.scopes:
        mode_rows = [row for row in capture.rows if row.identity_mode == scope.identity_mode]
        if (
            scope.ranked_row_count != sum(row.rank is not None for row in mode_rows)
            or scope.top3_row_count != sum(row.is_top3 for row in mode_rows)
            or scope.excluded_row_count
            != sum(row.rank is None for row in mode_rows)
        ):
            raise ValueError("forward leader scope counts do not match rows")


def _rank_row_values(row: ForwardLeaderRankRow) -> dict[str, object]:
    return asdict(row)


def _scope_values(scope: ForwardLeaderRankScope) -> dict[str, object]:
    return asdict(scope)
