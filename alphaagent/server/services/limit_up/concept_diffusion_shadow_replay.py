"""Read-only replay for the causal A+B rescue shadow."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.sql.elements import ColumnElement

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up import cash_backtest
from alphaagent.server.services.limit_up.concept_diffusion_shadow import (
    FORWARD_START_DATE,
    evaluate_quality_rescue_shadow,
    select_causal_quality_rescue_shadow,
    settle_quality_rescue_shadow,
)
from alphaagent.server.services.limit_up.versions import CORE_ABC_STRATEGY_VERSION


def replay_quality_rescue_shadow(start: date, end: date) -> dict[str, object]:
    """Replay saved point-in-time frames without writing strategy state."""

    start = max(start, FORWARD_START_DATE)
    if end < start:
        raise ValueError("quality rescue replay ends before forward start")
    observations = _load_event_observations(start, end)
    trade_dates = _load_trade_dates(
        start - timedelta(days=10),
        end + timedelta(days=10),
    )
    required_prior_dates = _required_prior_dates(trade_dates, start, end)
    baseline_selections = _baseline_selections(observations)
    shadow_selections = select_causal_quality_rescue_shadow(
        observations,
        required_prior_dates=required_prior_dates,
    )
    symbols = sorted(
        {
            str(row.get("vt_symbol") or "")
            for row in (*baseline_selections, *shadow_selections)
            if row.get("vt_symbol")
        }
    )
    official_bars = _load_official_bars(
        symbols,
        start,
        end + timedelta(days=10),
    )
    baseline_trades, baseline_settlement = settle_quality_rescue_shadow(
        baseline_selections,
        official_bars,
        trade_dates=trade_dates,
    )
    shadow_trades, shadow_settlement = settle_quality_rescue_shadow(
        shadow_selections,
        official_bars,
        trade_dates=trade_dates,
    )
    evaluation = evaluate_quality_rescue_shadow(baseline_trades, shadow_trades)
    cash_accounts = _cash_accounts(
        (*baseline_selections, *shadow_selections),
        official_bars,
        trade_dates,
    )
    return {
        "start": start,
        "end": end,
        "data_scope": _coverage(observations, required_prior_dates),
        "baseline_settlement": baseline_settlement,
        "shadow_settlement": shadow_settlement,
        "evaluation": evaluation,
        "cash_accounts": cash_accounts,
        "shadow_ledger": _ledger(shadow_trades),
    }


def _baseline_selections(
    observations: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    selected: dict[tuple[date, str], dict[str, object]] = {}
    for row in sorted(
        observations,
        key=lambda item: (
            str(item.get("trade_date") or ""),
            str(item.get("captured_at") or ""),
            str(item.get("vt_symbol") or ""),
        ),
    ):
        trade_date = _as_date(row.get("trade_date"))
        symbol = str(row.get("vt_symbol") or "")
        if (
            trade_date is None
            or not symbol
            or str(row.get("formal_action") or "") != "buy_now"
        ):
            continue
        selected.setdefault(
            (trade_date, symbol),
            {
                **dict(row),
                "trade_date": trade_date,
                "signal_time": _signal_time(row.get("captured_at")),
            },
        )
    return list(selected.values())


def _load_event_observations(start: date, end: date) -> list[dict[str, object]]:
    observation = schema.limit_up_radar_observations
    event_query = _first_event_observation_query(
        start,
        end,
        event_filter=observation.c.board_lane.in_(("first_board", "two_to_three"))
        & observation.c.capture_state.in_(("sealed", "resealed")),
    )
    formal_query = _first_event_observation_query(
        start,
        end,
        event_filter=observation.c.formal_action == "buy_now",
    )
    with session_scope() as session:
        event_rows = session.execute(event_query).mappings().all()
        formal_rows = session.execute(formal_query).mappings().all()
    unique = {
        (
            row["trade_date"],
            str(row["vt_symbol"]),
            int(row["frame_id"]),
        ): dict(row)
        for row in (*event_rows, *formal_rows)
    }
    return sorted(
        unique.values(),
        key=lambda row: (
            row["trade_date"],
            row["captured_at"],
            str(row["vt_symbol"]),
        ),
    )


def _first_event_observation_query(
    start: date,
    end: date,
    *,
    event_filter: ColumnElement[bool],
):
    frame = schema.limit_up_radar_frames
    observation = schema.limit_up_radar_observations
    return (
        select(
            frame.c.trade_date,
            frame.c.captured_at,
            frame.c.strategy_version,
            frame.c.contract_version,
            frame.c.quality_status,
            frame.c.is_stale,
            frame.c.quote_coverage_ratio,
            observation,
        )
        .select_from(observation.join(frame, observation.c.frame_id == frame.c.id))
        .where(
            frame.c.trade_date.between(start, end),
            frame.c.strategy_version == CORE_ABC_STRATEGY_VERSION,
            event_filter,
        )
        .distinct(frame.c.trade_date, observation.c.vt_symbol)
        .order_by(
            frame.c.trade_date,
            observation.c.vt_symbol,
            frame.c.captured_at,
            frame.c.id,
        )
    )


def _cash_accounts(
    selections: Sequence[Mapping[str, object]],
    official_bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
) -> dict[str, object]:
    ordered = sorted(
        (dict(row) for row in selections),
        key=lambda row: (
            str(row.get("trade_date") or ""),
            str(row.get("signal_time") or ""),
            int(row.get("pool_rank") or 0),
            str(row.get("vt_symbol") or ""),
        ),
    )
    result: dict[str, object] = {}
    for positions in (1, 2):
        account = cash_backtest.simulate_limit_up_account(
            ordered,
            official_bars,
            trade_dates,
            "next_close",
            cash_backtest.CashBacktestConfig(
                initial_cash=100_000,
                max_positions=positions,
            ),
        )
        result[str(positions)] = account["execution_summary"]
    return result


def _load_trade_dates(start: date, end: date) -> list[date]:
    with session_scope() as session:
        return list(
            session.execute(
                select(schema.stock_daily_bars.c.trade_date)
                .where(schema.stock_daily_bars.c.trade_date.between(start, end))
                .distinct()
                .order_by(schema.stock_daily_bars.c.trade_date)
            ).scalars()
        )


def _load_official_bars(
    symbols: Sequence[str],
    start: date,
    end: date,
) -> list[dict[str, object]]:
    if not symbols:
        return []
    table = schema.stock_daily_bars
    with session_scope() as session:
        rows = (
            session.execute(
                select(table.c.vt_symbol, table.c.trade_date, table.c.close_price)
                .where(
                    table.c.vt_symbol.in_(symbols),
                    table.c.trade_date.between(start, end),
                )
                .order_by(table.c.trade_date, table.c.vt_symbol)
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def _required_prior_dates(
    trade_dates: Sequence[date],
    start: date,
    end: date,
) -> dict[date, date]:
    ordered = sorted(set(trade_dates))
    return {
        current: ordered[index - 1]
        for index, current in enumerate(ordered)
        if index > 0 and start <= current <= end
    }


def _coverage(
    observations: Sequence[Mapping[str, object]],
    required_prior_dates: Mapping[date, date],
) -> dict[str, int]:
    return {
        "observation_count": len(observations),
        "trade_date_count": len(
            {
                parsed
                for row in observations
                if (parsed := _as_date(row.get("trade_date"))) is not None
            }
        ),
        "core_quality_observation_count": sum(
            row.get("core_quality_gate_passed") is not None for row in observations
        ),
        "prior_state_observation_count": sum(
            row.get("prior_market_phase") is not None
            and row.get("prior_return_5d_pct") is not None
            for row in observations
        ),
        "all_concepts_observation_count": sum(
            isinstance(row.get("concept_candidates"), list)
            and bool(row.get("concept_candidates"))
            for row in observations
        ),
        "strict_d1_membership_observation_count": sum(
            _as_date(row.get("concept_membership_snapshot_date"))
            == required_prior_dates.get(_as_date(row.get("trade_date")))
            for row in observations
        ),
    }


def _ledger(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    fields = (
        "trade_date",
        "captured_at",
        "name",
        "vt_symbol",
        "board_lane",
        "signal_kind",
        "core_quality_gate_reason",
        "prior_market_phase",
        "prior_return_5d_pct",
        "prior_industry_turnover_ratio_5d",
        "stock_d1_sample_count",
        "stock_gene_combined_win_rate",
        "intraday_concept_name",
        "intraday_concept_prior_sealed_count",
        "intraday_concept_candidate_rank",
        "intraday_concept_prior_max_board",
        "shadow_components",
        "result_date",
        "return_pct",
    )
    return [{field: row.get(field) for field in fields} for row in rows]


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _signal_time(value: object) -> str:
    text = str(value or "")
    return text[11:19] if len(text) >= 19 else ""


def _date_argument(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=_date_argument)
    parser.add_argument("--end", type=_date_argument)
    args = parser.parse_args()
    start = args.start or FORWARD_START_DATE
    end = args.end or date.today()
    print(
        json.dumps(
            replay_quality_rescue_shadow(start, end),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
