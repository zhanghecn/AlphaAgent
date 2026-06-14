"""Persistence helpers for AlphaAgent backtest runs."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from alphaagent.server.db import schema
from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant.factors import STRATEGY_VERSION
from alphaagent.server.services.quant.strategy_registry import get_strategy


def persist_run(
    session,
    params: BacktestParams,
    run: dict[str, Any],
    end: date,
    *,
    params_to_json,
) -> int:
    """Persist one completed backtest and return its database id."""

    metrics = run["metrics"]
    strategy = get_strategy(params.strategy)
    strategy_version = strategy.version if strategy else STRATEGY_VERSION
    backtest_id = session.execute(
        schema.backtest_runs.insert()
        .values(
            strategy_id=params.strategy,
            strategy_version=strategy_version,
            start_date=params.start,
            end_date=end,
            status="succeeded",
            initial_cash=params.initial_cash,
            final_equity=metrics.get("final_equity"),
            params=params_to_json(params),
            metrics=metrics,
            finished_at=datetime.now(timezone.utc),
        )
        .returning(schema.backtest_runs.c.id)
    ).scalar_one()

    for item in run["equity"]:
        session.execute(
            schema.backtest_daily_equity.insert().values(
                backtest_id=backtest_id,
                **table_values(schema.backtest_daily_equity, item),
            )
        )
    for item in run.get("positions") or []:
        session.execute(
            schema.backtest_daily_positions.insert().values(
                backtest_id=backtest_id,
                **table_values(schema.backtest_daily_positions, item),
            )
        )
    for item in run.get("signal_events") or []:
        session.execute(
            schema.backtest_signal_events.insert().values(
                backtest_id=backtest_id,
                **table_values(schema.backtest_signal_events, item),
            )
        )
    for item in run["orders"]:
        session.execute(
            schema.backtest_orders.insert().values(
                backtest_id=backtest_id,
                **table_values(schema.backtest_orders, item),
            )
        )
    for item in run["trades"]:
        session.execute(
            schema.backtest_trades.insert().values(
                backtest_id=backtest_id,
                **table_values(schema.backtest_trades, item),
            )
        )
    for key, value in metrics.items():
        if isinstance(value, (int, float)) or value is None:
            session.execute(schema.backtest_metrics.insert().values(backtest_id=backtest_id, metric_key=key, metric_value=value))
        else:
            session.execute(schema.backtest_metrics.insert().values(backtest_id=backtest_id, metric_key=key, metric_text=str(value)))
    return int(backtest_id)


def table_values(table, item: dict[str, Any]) -> dict[str, Any]:
    """Return only columns that can be persisted for a backtest child table."""

    columns = set(table.c.keys())
    return {
        key: value
        for key, value in parse_dates(item).items()
        if key in columns and key not in {"id", "backtest_id", "created_at"}
    }


def parse_dates(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("trade_date", "signal_date", "execute_date", "entry_date", "start_date", "end_date"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = date.fromisoformat(value[:10])
    return result
