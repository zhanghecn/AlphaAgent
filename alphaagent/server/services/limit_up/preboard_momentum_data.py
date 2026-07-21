"""Recent complete-cross-section data for causal pre-board momentum research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import bindparam, text

from alphaagent.server.db.session import get_engine
from alphaagent.server.services.limit_up.domain import (
    is_eligible_main_board,
    main_board_limit_price,
)
from alphaagent.server.services.limit_up.first_board_stock_gene_research import (
    attach_prior_stock_gene_evidence_to_orders,
)
from alphaagent.server.services.research_runtime import require_research_runtime


FIVE_MINUTE_INTERVAL = "5m"
MINIMUM_PRIOR_BARS = 120
PRIOR_EVENT_WINDOW_BARS = 126
PRIOR_EVENT_CONTEXT_BARS = PRIOR_EVENT_WINDOW_BARS + 1
PREBOARD_CAPTURE_GAIN_PCT = 3.0
MANIFEST_REASON = "daily_high_crossed_3pct"


def official_five_minute_close_times() -> tuple[str, ...]:
    """Return the 48 official five-minute close slots in an A-share session."""

    return tuple([*_time_grid(time(9, 35), 24), *_time_grid(time(13, 5), 24)])


def build_preboard_manifest(daily_rows: pd.DataFrame) -> pd.DataFrame:
    """Return mature first-board stock-days whose high crossed the 3% radar."""

    required = {
        "vt_symbol",
        "name",
        "trade_date",
        "open_price",
        "close_price",
        "high_price",
        "low_price",
        "volume",
        "turnover",
    }
    missing = sorted(required - set(daily_rows.columns))
    if missing:
        raise ValueError(f"missing daily columns: {', '.join(missing)}")
    if daily_rows.empty:
        return _empty_manifest()

    frame = daily_rows.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    frame = frame.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(
        drop=True
    )
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["previous_close"] = grouped["close_price"].shift(1)
    frame["previous_previous_close"] = grouped["close_price"].shift(2)
    frame["prior_history_count"] = grouped.cumcount()
    frame["d1_trade_date"] = grouped["trade_date"].shift(-1)
    frame["d1_close_price"] = grouped["close_price"].shift(-1)
    frame["prior_day_limit_up"] = [
        _prior_day_was_limit_up(previous_close, previous_previous_close)
        for previous_close, previous_previous_close in zip(
            frame["previous_close"],
            frame["previous_previous_close"],
            strict=True,
        )
    ]
    frame["eligible_main_board"] = [
        is_eligible_main_board(str(symbol), str(name))
        for symbol, name in zip(frame["vt_symbol"], frame["name"], strict=True)
    ]
    frame["limit_price"] = [
        main_board_limit_price(float(value))
        if pd.notna(value) and float(value) > 0
        else None
        for value in frame["previous_close"]
    ]
    frame["touched"] = frame["high_price"].ge(frame["limit_price"] - 0.001)
    frame["sealed"] = frame["close_price"].ge(frame["limit_price"] - 0.001)
    event_grouped = frame.groupby("vt_symbol", sort=False)
    frame["prior_limit_count_126"] = (
        event_grouped["sealed"]
        .transform(
            lambda values: values.shift(1)
            .rolling(PRIOR_EVENT_WINDOW_BARS, min_periods=1)
            .sum()
        )
        .fillna(0)
        .astype(int)
    )
    frame["prior_touch_count_126"] = (
        event_grouped["touched"]
        .transform(
            lambda values: values.shift(1)
            .rolling(PRIOR_EVENT_WINDOW_BARS, min_periods=1)
            .sum()
        )
        .fillna(0)
        .astype(int)
    )
    frame["prior_seal_success_rate_126"] = frame["prior_limit_count_126"] / frame[
        "prior_touch_count_126"
    ].replace(0, pd.NA)
    crossed_three = pd.to_numeric(
        frame["high_price"], errors="coerce"
    ) >= pd.to_numeric(frame["previous_close"], errors="coerce") * (
        1 + PREBOARD_CAPTURE_GAIN_PCT / 100
    )
    selected = frame.loc[
        frame["eligible_main_board"]
        & frame["prior_history_count"].ge(MINIMUM_PRIOR_BARS)
        & frame["previous_close"].gt(0)
        & crossed_three
        & ~frame["prior_day_limit_up"]
        & frame["d1_trade_date"].notna()
        & frame["d1_close_price"].gt(0)
    ].copy()
    selected["manifest_reason"] = MANIFEST_REASON
    selected["touched_limit"] = selected["high_price"].ge(
        selected["limit_price"] - 0.001
    )
    selected["sealed_limit"] = selected["close_price"].ge(
        selected["limit_price"] - 0.001
    )
    return selected.sort_values(["trade_date", "vt_symbol"], kind="stable").reset_index(
        drop=True
    )


def attach_preboard_prior_evidence(
    manifest: pd.DataFrame,
    history_days: Sequence[Mapping[str, object]],
) -> pd.DataFrame:
    """Attach only same-stock D+1 results matured before each manifest date."""

    if manifest.empty:
        return manifest.copy()
    required = {
        "vt_symbol",
        "trade_date",
        "prior_limit_count_126",
        "prior_touch_count_126",
        "prior_seal_success_rate_126",
    }
    missing = sorted(required - set(manifest.columns))
    if missing:
        raise ValueError(f"missing prior-evidence columns: {', '.join(missing)}")
    orders = []
    for row in manifest.to_dict(orient="records"):
        orders.append(
            {
                **row,
                "lane": "first_board",
                "signal_date": str(row.get("trade_date") or "")[:10],
            }
        )
    evidence_days = [dict(day) for day in history_days]
    available_dates = {str(day.get("trade_date") or "")[:10] for day in evidence_days}
    for signal_date in sorted({str(order["signal_date"]) for order in orders}):
        if signal_date not in available_dates:
            evidence_days.append(
                {
                    "trade_date": signal_date,
                    "lane_portfolio": {"candidate_pool": {"first_board": []}},
                }
            )
    enriched = attach_prior_stock_gene_evidence_to_orders(evidence_days, orders)
    return (
        pd.DataFrame(enriched)
        .sort_values(["trade_date", "vt_symbol"], kind="stable")
        .reset_index(drop=True)
    )


def load_preboard_manifest(*, session_count: int = 60) -> pd.DataFrame:
    """Load the latest complete recent 3% manifest from PostgreSQL."""

    require_research_runtime()
    count = max(int(session_count), 1)
    reliable_dates = _load_reliable_dates(count + 1)
    if len(reliable_dates) < count + 1:
        return _empty_manifest()
    descending = sorted(reliable_dates, reverse=True)
    evaluation_dates = sorted(descending[1 : count + 1])
    manifest = _load_manifest_candidates(evaluation_dates)
    next_dates = {
        current: following
        for current, following in zip(
            evaluation_dates, evaluation_dates[1:], strict=False
        )
    }
    next_dates[evaluation_dates[-1]] = descending[0]
    manifest["result_date"] = manifest["trade_date"].dt.date.map(next_dates)
    manifest = manifest.loc[
        manifest["d1_trade_date"].dt.date.eq(manifest["result_date"])
    ].copy()
    return manifest.sort_values(["trade_date", "vt_symbol"], kind="stable").reset_index(
        drop=True
    )


def build_five_minute_coverage(
    manifest: pd.DataFrame,
    minute_rows: pd.DataFrame,
) -> pd.DataFrame:
    """Audit exact five-minute coverage for every manifest symbol-date pair."""

    required_manifest = {"vt_symbol", "trade_date"}
    missing_manifest = sorted(required_manifest - set(manifest.columns))
    if missing_manifest:
        raise ValueError(f"missing manifest columns: {', '.join(missing_manifest)}")
    pairs = manifest.loc[:, ["vt_symbol", "trade_date"]].drop_duplicates().copy()
    pairs["trade_date"] = pd.to_datetime(pairs["trade_date"], errors="raise").dt.date
    if pairs.empty:
        return _empty_coverage()

    required_minute = {"vt_symbol", "trade_date", "bar_time", "interval"}
    missing_minute = sorted(required_minute - set(minute_rows.columns))
    if missing_minute and not minute_rows.empty:
        raise ValueError(f"missing minute columns: {', '.join(missing_minute)}")
    if minute_rows.empty:
        counts = _empty_coverage_counts()
    else:
        frame = minute_rows.loc[minute_rows["interval"].eq(FIVE_MINUTE_INTERVAL)].copy()
        frame["trade_date"] = pd.to_datetime(
            frame["trade_date"], errors="raise"
        ).dt.date
        frame["bar_time"] = pd.to_datetime(frame["bar_time"], errors="raise")
        frame["slot"] = frame["bar_time"].dt.strftime("%H:%M")
        expected = set(official_five_minute_close_times())
        frame["valid_slot"] = frame["slot"].isin(expected)
        grouped = frame.groupby(["vt_symbol", "trade_date"], sort=False)
        counts = grouped.agg(
            raw_row_count=("bar_time", "size"),
            unique_row_count=("bar_time", "nunique"),
            valid_slot_count=("slot", lambda values: len(set(values) & expected)),
            unexpected_time_count=("valid_slot", lambda values: int((~values).sum())),
            first_slot=("slot", "min"),
            last_slot=("slot", "max"),
        ).reset_index()
        counts["duplicate_count"] = counts["raw_row_count"] - counts["unique_row_count"]

    return _merge_coverage_counts(pairs, counts)


def _merge_coverage_counts(
    pairs: pd.DataFrame,
    counts: pd.DataFrame,
) -> pd.DataFrame:
    coverage = pairs.merge(
        counts,
        on=["vt_symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    integer_columns = (
        "raw_row_count",
        "unique_row_count",
        "valid_slot_count",
        "unexpected_time_count",
        "duplicate_count",
    )
    for column in integer_columns:
        coverage[column] = coverage[column].fillna(0).astype(int)
    coverage["coverage_status"] = "incomplete"
    coverage.loc[coverage["raw_row_count"].eq(0), "coverage_status"] = "missing"
    invalid = coverage["duplicate_count"].gt(0) | coverage["unexpected_time_count"].gt(
        0
    )
    coverage.loc[invalid, "coverage_status"] = "invalid"
    complete = (
        coverage["raw_row_count"].eq(48)
        & coverage["unique_row_count"].eq(48)
        & coverage["valid_slot_count"].eq(48)
        & coverage["duplicate_count"].eq(0)
        & coverage["unexpected_time_count"].eq(0)
        & coverage["first_slot"].eq("09:35")
        & coverage["last_slot"].eq("15:00")
    )
    coverage.loc[complete, "coverage_status"] = "complete"
    return coverage.sort_values(["trade_date", "vt_symbol"], kind="stable").reset_index(
        drop=True
    )


def load_preboard_minute_bars(manifest: pd.DataFrame) -> pd.DataFrame:
    """Load only stored five-minute rows that belong to manifest pairs."""

    if manifest.empty:
        return _empty_minute_rows()
    symbols = sorted(manifest["vt_symbol"].astype(str).unique())
    start = pd.to_datetime(manifest["trade_date"]).min().date()
    end = pd.to_datetime(manifest["trade_date"]).max().date()
    statement = text(
        """
        SELECT vt_symbol, trade_date, bar_time, interval,
               open_price, high_price, low_price, close_price,
               volume, turnover, source
        FROM stock_minute_bars
        WHERE interval = :interval
          AND trade_date BETWEEN :start AND :end
          AND vt_symbol IN :symbols
        ORDER BY trade_date, vt_symbol, bar_time
        """
    ).bindparams(bindparam("symbols", expanding=True))
    rows = pd.read_sql(
        statement,
        get_engine(),
        params={
            "interval": FIVE_MINUTE_INTERVAL,
            "start": start,
            "end": end,
            "symbols": symbols,
        },
        parse_dates=["trade_date", "bar_time"],
    )
    pair_index = pd.MultiIndex.from_frame(
        manifest.assign(trade_date=pd.to_datetime(manifest["trade_date"]).dt.date)[
            ["vt_symbol", "trade_date"]
        ].drop_duplicates()
    )
    row_index = pd.MultiIndex.from_arrays(
        [rows["vt_symbol"], pd.to_datetime(rows["trade_date"]).dt.date]
    )
    return rows.loc[row_index.isin(pair_index)].reset_index(drop=True)


def load_five_minute_coverage(manifest: pd.DataFrame) -> pd.DataFrame:
    """Aggregate exact pair coverage in PostgreSQL without loading all bars."""

    if manifest.empty:
        return _empty_coverage()
    pairs = manifest.loc[:, ["vt_symbol", "trade_date"]].drop_duplicates().copy()
    pairs["trade_date"] = pd.to_datetime(pairs["trade_date"], errors="raise").dt.date
    symbols = sorted(pairs["vt_symbol"].astype(str).unique())
    start = min(pairs["trade_date"])
    end = max(pairs["trade_date"])
    statement = text(
        """
        SELECT vt_symbol, trade_date,
               COUNT(*) AS raw_row_count,
               COUNT(DISTINCT bar_time) AS unique_row_count,
               COUNT(DISTINCT bar_time) FILTER (
                   WHERE (
                       (bar_time::time BETWEEN time '09:35' AND time '11:30')
                       OR (bar_time::time BETWEEN time '13:05' AND time '15:00')
                   )
                   AND MOD(EXTRACT(MINUTE FROM bar_time)::integer, 5) = 0
               ) AS valid_slot_count,
               COUNT(*) FILTER (
                   WHERE NOT (
                       (
                           (bar_time::time BETWEEN time '09:35' AND time '11:30')
                           OR (bar_time::time BETWEEN time '13:05' AND time '15:00')
                       )
                       AND MOD(EXTRACT(MINUTE FROM bar_time)::integer, 5) = 0
                   )
               ) AS unexpected_time_count,
               TO_CHAR(MIN(bar_time), 'HH24:MI') AS first_slot,
               TO_CHAR(MAX(bar_time), 'HH24:MI') AS last_slot,
               COUNT(*) - COUNT(DISTINCT bar_time) AS duplicate_count
        FROM stock_minute_bars
        WHERE interval = :interval
          AND trade_date BETWEEN :start AND :end
          AND vt_symbol IN :symbols
        GROUP BY vt_symbol, trade_date
        ORDER BY trade_date, vt_symbol
        """
    ).bindparams(bindparam("symbols", expanding=True))
    counts = pd.read_sql(
        statement,
        get_engine(),
        params={
            "interval": FIVE_MINUTE_INTERVAL,
            "start": start,
            "end": end,
            "symbols": symbols,
        },
    )
    if counts.empty:
        counts = _empty_coverage_counts()
    else:
        counts["trade_date"] = pd.to_datetime(counts["trade_date"]).dt.date
    return _merge_coverage_counts(pairs, counts)


def load_preboard_daily_bars(manifest: pd.DataFrame) -> pd.DataFrame:
    """Load daily bars required for D entry marks and D+1 close exits."""

    if manifest.empty:
        return pd.DataFrame(
            columns=[
                "vt_symbol",
                "trade_date",
                "open_price",
                "close_price",
                "high_price",
                "low_price",
            ]
        )
    symbols = sorted(manifest["vt_symbol"].astype(str).unique())
    start = pd.to_datetime(manifest["trade_date"]).min().date()
    result_dates = pd.to_datetime(manifest["result_date"], errors="coerce")
    end = result_dates.max().date() + timedelta(days=14)
    statement = text(
        """
        SELECT vt_symbol, trade_date, open_price, close_price, high_price, low_price
        FROM stock_daily_bars
        WHERE trade_date BETWEEN :start AND :end
          AND vt_symbol IN :symbols
        ORDER BY trade_date, vt_symbol
        """
    ).bindparams(bindparam("symbols", expanding=True))
    return pd.read_sql(
        statement,
        get_engine(),
        params={"start": start, "end": end, "symbols": symbols},
        parse_dates=["trade_date"],
    )


def load_reliable_trade_dates(start: date, end: date) -> list[date]:
    """Return reliable full-market dates for cash-account chronology."""

    statement = text(
        """
        SELECT trade_date
        FROM stock_daily_bars
        WHERE trade_date BETWEEN :start AND :end
        GROUP BY trade_date
        HAVING COUNT(DISTINCT vt_symbol) >= 3000
        ORDER BY trade_date
        """
    )
    with get_engine().connect() as connection:
        return list(
            connection.execute(statement, {"start": start, "end": end}).scalars()
        )


def build_backfill_gaps(
    coverage: pd.DataFrame,
    *,
    max_symbols: int,
    symbol_offset: int = 0,
) -> list[dict[str, Any]]:
    """Return every missing date for one bounded, deterministic symbol slice."""

    required = {"vt_symbol", "trade_date", "coverage_status"}
    missing = sorted(required - set(coverage.columns))
    if missing:
        raise ValueError(f"missing coverage columns: {', '.join(missing)}")
    unresolved = coverage.loc[coverage["coverage_status"].ne("complete")].copy()
    symbols = sorted(unresolved["vt_symbol"].astype(str).unique())
    start = max(int(symbol_offset), 0)
    selected = set(symbols[start : start + max(int(max_symbols), 0)])
    rows = unresolved.loc[unresolved["vt_symbol"].isin(selected)].copy()
    rows["trade_date"] = pd.to_datetime(rows["trade_date"], errors="raise").dt.date
    rows = rows.sort_values(["vt_symbol", "trade_date"], kind="stable")
    return [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": row.trade_date,
            "window": "preboard_momentum_full_session_5m",
        }
        for row in rows.itertuples(index=False)
    ]


def backfill_preboard_five_minute(
    *,
    dry_run: bool,
    max_symbols: int = 50,
    symbol_offset: int = 0,
    session_count: int = 60,
) -> dict[str, Any]:
    """Backfill one bounded symbol slice through the existing TDX importer."""

    from alphaagent.server.services.data_providers.tdx_minute_import import (
        import_tdx_minute_bars_for_gaps,
    )

    manifest = load_preboard_manifest(session_count=session_count)
    coverage = load_five_minute_coverage(manifest)
    gaps = build_backfill_gaps(
        coverage,
        max_symbols=max_symbols,
        symbol_offset=symbol_offset,
    )
    before_complete = int(coverage["coverage_status"].eq("complete").sum())
    if not gaps:
        return {
            "status": "ready",
            "dry_run": dry_run,
            "manifest_pairs": int(len(manifest)),
            "complete_pairs_before": before_complete,
            "requested_gap_count": 0,
        }
    result = import_tdx_minute_bars_for_gaps(
        gaps=gaps,
        interval=FIVE_MINUTE_INTERVAL,
        tail_entry_start="09:35",
        tail_entry_end="15:00",
        dry_run=dry_run,
        max_gaps=len(gaps),
        max_pages_per_symbol=12,
        timeout_seconds=3.0,
    )
    return {
        **result,
        "dataset": "limit_up_preboard_momentum_5m",
        "manifest_pairs": int(len(manifest)),
        "complete_pairs_before": before_complete,
        "requested_gap_count": len(gaps),
        "symbol_offset": max(int(symbol_offset), 0),
        "requested_symbol_count": len({row["vt_symbol"] for row in gaps}),
    }


def _load_reliable_dates(limit: int) -> list[date]:
    statement = text(
        """
        SELECT trade_date
        FROM stock_daily_bars
        GROUP BY trade_date
        HAVING COUNT(DISTINCT vt_symbol) >= 3000
        ORDER BY trade_date DESC
        LIMIT :limit
        """
    )
    with get_engine().connect() as connection:
        return list(connection.execute(statement, {"limit": int(limit)}).scalars())


def _load_manifest_candidates(evaluation_dates: Sequence[date]) -> pd.DataFrame:
    # The history count is only a >=120 eligibility gate.  Cap its diagnostic value
    # at the 126 bars already required for stock-gene evidence instead of scanning a
    # symbol's entire listing history for every candidate date.
    statement = text(
        """
        WITH evaluation_rows AS MATERIALIZED (
            SELECT b.vt_symbol, s.name, b.trade_date,
                   b.open_price, b.close_price, b.high_price, b.low_price,
                   b.volume, b.turnover, b.turnover_rate
            FROM stock_daily_bars AS b
            JOIN stocks AS s ON s.vt_symbol = b.vt_symbol
            WHERE b.trade_date IN :evaluation_dates
              AND (
                  UPPER(b.vt_symbol) ~ '^(600|601|603|605)[0-9]{3}[.]SSE$'
                  OR UPPER(b.vt_symbol) ~ '^(000|001|002|003)[0-9]{3}[.]SZSE$'
              )
        ),
        three_percent_candidates AS MATERIALIZED (
            SELECT evaluation_rows.*,
                   previous_day.close_price AS previous_close
            FROM evaluation_rows
            JOIN LATERAL (
                SELECT history.close_price
                FROM stock_daily_bars AS history
                WHERE history.vt_symbol = evaluation_rows.vt_symbol
                  AND history.trade_date < evaluation_rows.trade_date
                ORDER BY history.trade_date DESC
                LIMIT 1
            ) AS previous_day ON TRUE
            WHERE previous_day.close_price > 0
              AND evaluation_rows.high_price >= (
                  previous_day.close_price * :capture_ratio
              )
        ),
        candidate_rows AS MATERIALIZED (
            SELECT three_percent_candidates.*,
                   previous_previous_day.close_price AS previous_previous_close
            FROM three_percent_candidates
            LEFT JOIN LATERAL (
                SELECT history.close_price
                FROM stock_daily_bars AS history
                WHERE history.vt_symbol = three_percent_candidates.vt_symbol
                  AND history.trade_date < three_percent_candidates.trade_date
                ORDER BY history.trade_date DESC
                OFFSET 1
                LIMIT 1
            ) AS previous_previous_day ON TRUE
        )
        SELECT candidate_rows.*,
               ROUND(candidate_rows.previous_close::numeric * 1.10, 2)::double precision
                   AS limit_price,
               candidate_rows.high_price >= (
                   ROUND(candidate_rows.previous_close::numeric * 1.10, 2)::double precision - 0.001
               ) AS touched,
               candidate_rows.close_price >= (
                   ROUND(candidate_rows.previous_close::numeric * 1.10, 2)::double precision - 0.001
               ) AS sealed,
               next_day.trade_date AS d1_trade_date,
               next_day.close_price AS d1_close_price,
               prior_events.prior_history_count,
               prior_events.prior_limit_count_126,
               prior_events.prior_touch_count_126
        FROM candidate_rows
        JOIN LATERAL (
            SELECT COUNT(*) FILTER (
                       WHERE ranked.history_rank <= :history_window_bars
                   )::integer AS prior_history_count,
                   COUNT(*) FILTER (
                       WHERE ranked.history_rank <= :history_window_bars
                         AND ranked.event_previous_close > 0
                         AND ranked.close_price >= (
                             ROUND(
                                 ranked.event_previous_close::numeric * 1.10,
                                 2
                             )::double precision - 0.001
                         )
                   )::integer AS prior_limit_count_126,
                   COUNT(*) FILTER (
                       WHERE ranked.history_rank <= :history_window_bars
                         AND ranked.event_previous_close > 0
                         AND ranked.high_price >= (
                             ROUND(
                                 ranked.event_previous_close::numeric * 1.10,
                                 2
                             )::double precision - 0.001
                         )
                   )::integer AS prior_touch_count_126
            FROM (
                SELECT recent.*,
                       ROW_NUMBER() OVER (
                           ORDER BY recent.trade_date DESC
                       ) AS history_rank,
                       LEAD(recent.close_price) OVER (
                           ORDER BY recent.trade_date DESC
                       ) AS event_previous_close
                FROM (
                    SELECT history.trade_date,
                           history.close_price,
                           history.high_price
                    FROM stock_daily_bars AS history
                    WHERE history.vt_symbol = candidate_rows.vt_symbol
                      AND history.trade_date < candidate_rows.trade_date
                    ORDER BY history.trade_date DESC
                    LIMIT :history_context_bars
                ) AS recent
            ) AS ranked
        ) AS prior_events
          ON prior_events.prior_history_count >= :minimum_prior_bars
        LEFT JOIN LATERAL (
            SELECT future.trade_date, future.close_price
            FROM stock_daily_bars AS future
            WHERE future.vt_symbol = candidate_rows.vt_symbol
              AND future.trade_date > candidate_rows.trade_date
            ORDER BY future.trade_date
            LIMIT 1
        ) AS next_day ON TRUE
        ORDER BY candidate_rows.trade_date, candidate_rows.vt_symbol
        """
    ).bindparams(bindparam("evaluation_dates", expanding=True))
    frame = pd.read_sql(
        statement,
        get_engine(),
        params={
            "evaluation_dates": list(evaluation_dates),
            "minimum_prior_bars": MINIMUM_PRIOR_BARS,
            "history_window_bars": PRIOR_EVENT_WINDOW_BARS,
            "history_context_bars": PRIOR_EVENT_CONTEXT_BARS,
            "capture_ratio": 1 + PREBOARD_CAPTURE_GAIN_PCT / 100,
        },
        parse_dates=["trade_date", "d1_trade_date"],
    )
    if frame.empty:
        return _empty_manifest()
    frame["prior_day_limit_up"] = [
        _prior_day_was_limit_up(previous_close, previous_previous_close)
        for previous_close, previous_previous_close in zip(
            frame["previous_close"],
            frame["previous_previous_close"],
            strict=True,
        )
    ]
    frame["eligible_main_board"] = [
        is_eligible_main_board(str(symbol), str(name))
        for symbol, name in zip(frame["vt_symbol"], frame["name"], strict=True)
    ]
    frame = frame.loc[
        frame["eligible_main_board"]
        & ~frame["prior_day_limit_up"]
        & frame["d1_close_price"].gt(0)
    ].copy()
    frame["limit_price"] = [
        main_board_limit_price(float(value)) for value in frame["previous_close"]
    ]
    frame["prior_seal_success_rate_126"] = frame["prior_limit_count_126"] / frame[
        "prior_touch_count_126"
    ].replace(0, pd.NA)
    frame["manifest_reason"] = MANIFEST_REASON
    frame["touched_limit"] = frame["high_price"].ge(frame["limit_price"] - 0.001)
    frame["sealed_limit"] = frame["close_price"].ge(frame["limit_price"] - 0.001)
    return frame


def _prior_day_was_limit_up(
    previous_close: object,
    previous_previous_close: object,
) -> bool:
    if pd.isna(previous_close) or pd.isna(previous_previous_close):
        return False
    baseline = float(previous_previous_close)
    return (
        baseline > 0
        and float(previous_close) >= main_board_limit_price(baseline) - 0.001
    )


def _time_grid(first_close: time, count: int) -> list[str]:
    current = datetime.combine(date.min, first_close)
    return [
        (current + timedelta(minutes=5 * index)).strftime("%H:%M")
        for index in range(count)
    ]


def _empty_manifest() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "vt_symbol",
            "name",
            "trade_date",
            "previous_close",
            "limit_price",
            "d1_trade_date",
            "d1_close_price",
            "prior_history_count",
            "prior_day_limit_up",
            "prior_limit_count_126",
            "prior_touch_count_126",
            "prior_seal_success_rate_126",
            "touched_limit",
            "sealed_limit",
            "manifest_reason",
        ]
    )


def _empty_coverage_counts() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "vt_symbol",
            "trade_date",
            "raw_row_count",
            "unique_row_count",
            "valid_slot_count",
            "unexpected_time_count",
            "first_slot",
            "last_slot",
            "duplicate_count",
        ]
    )


def _empty_coverage() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            *_empty_coverage_counts().columns,
            "coverage_status",
        ]
    )


def _empty_minute_rows() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "vt_symbol",
            "trade_date",
            "bar_time",
            "interval",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "turnover",
            "source",
        ]
    )
