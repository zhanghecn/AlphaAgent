"""Recent complete-cross-section data for causal pre-board momentum research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

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


MINIMUM_PRIOR_BARS = 120
PRIOR_EVENT_WINDOW_BARS = 126
PRIOR_EVENT_CONTEXT_BARS = PRIOR_EVENT_WINDOW_BARS + 1
PREBOARD_CAPTURE_GAIN_PCT = 3.0
MANIFEST_REASON = "daily_high_crossed_3pct"


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


def load_preboard_manifest(
    *,
    session_count: int = 60,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Load a complete recent 3% manifest, optionally ending on a frozen date."""

    require_research_runtime()
    count = max(int(session_count), 1)
    if end_date is None:
        reliable_dates = _load_reliable_dates(count + 1)
        if len(reliable_dates) < count + 1:
            return _empty_manifest()
        descending = sorted(reliable_dates, reverse=True)
        evaluation_dates = sorted(descending[1 : count + 1])
        result_date = descending[0]
    else:
        reliable_dates = _load_reliable_dates(count, end_date=end_date)
        if len(reliable_dates) < count:
            return _empty_manifest()
        evaluation_dates = sorted(reliable_dates, reverse=True)[:count]
        evaluation_dates.sort()
        result_date = _load_next_reliable_date(evaluation_dates[-1])
        if result_date is None:
            return _empty_manifest()
    manifest = _load_manifest_candidates(evaluation_dates)
    next_dates = {
        current: following
        for current, following in zip(
            evaluation_dates, evaluation_dates[1:], strict=False
        )
    }
    next_dates[evaluation_dates[-1]] = result_date
    manifest["result_date"] = manifest["trade_date"].dt.date.map(next_dates)
    manifest = manifest.loc[
        manifest["d1_trade_date"].dt.date.eq(manifest["result_date"])
    ].copy()
    return manifest.sort_values(["trade_date", "vt_symbol"], kind="stable").reset_index(
        drop=True
    )


def load_preboard_capture_manifest(
    *,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Load a label-free path index for recent point-in-time replay."""

    require_research_runtime()
    if start_date > end_date:
        raise ValueError("capture manifest start_date must not exceed end_date")
    evaluation_dates = _load_reliable_dates_between(start_date, end_date)
    if not evaluation_dates:
        return _empty_manifest().drop(
            columns=["d1_trade_date", "d1_close_price", "touched_limit", "sealed_limit"]
        )
    manifest = _load_manifest_candidates(
        evaluation_dates,
        require_d1_result=False,
    )
    outcome_fields = (
        "touched",
        "sealed",
        "touched_limit",
        "sealed_limit",
        "d1_trade_date",
        "d1_close_price",
    )
    return (
        manifest.drop(columns=list(outcome_fields), errors="ignore")
        .sort_values(["trade_date", "vt_symbol"], kind="stable")
        .reset_index(drop=True)
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


def _load_reliable_dates(
    limit: int,
    *,
    end_date: date | None = None,
) -> list[date]:
    end_clause = "WHERE trade_date <= :end_date" if end_date is not None else ""
    statement = text(
        f"""
        SELECT trade_date
        FROM stock_daily_bars
        {end_clause}
        GROUP BY trade_date
        HAVING COUNT(DISTINCT vt_symbol) >= 3000
        ORDER BY trade_date DESC
        LIMIT :limit
        """
    )
    parameters: dict[str, object] = {"limit": int(limit)}
    if end_date is not None:
        parameters["end_date"] = end_date
    with get_engine().connect() as connection:
        return list(connection.execute(statement, parameters).scalars())


def _load_next_reliable_date(after: date) -> date | None:
    statement = text(
        """
        SELECT trade_date
        FROM stock_daily_bars
        WHERE trade_date > :after
        GROUP BY trade_date
        HAVING COUNT(DISTINCT vt_symbol) >= 3000
        ORDER BY trade_date ASC
        LIMIT 1
        """
    )
    with get_engine().connect() as connection:
        return connection.execute(statement, {"after": after}).scalar_one_or_none()


def _load_reliable_dates_between(start_date: date, end_date: date) -> list[date]:
    statement = text(
        """
        SELECT trade_date
        FROM stock_daily_bars
        WHERE trade_date BETWEEN :start_date AND :end_date
        GROUP BY trade_date
        HAVING COUNT(DISTINCT vt_symbol) >= 3000
        ORDER BY trade_date ASC
        """
    )
    with get_engine().connect() as connection:
        return list(
            connection.execute(
                statement,
                {"start_date": start_date, "end_date": end_date},
            ).scalars()
        )


def _load_manifest_candidates(
    evaluation_dates: Sequence[date],
    *,
    require_d1_result: bool = True,
) -> pd.DataFrame:
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
    selected = frame["eligible_main_board"] & ~frame["prior_day_limit_up"]
    if require_d1_result:
        selected &= frame["d1_close_price"].gt(0)
    frame = frame.loc[selected].copy()
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
