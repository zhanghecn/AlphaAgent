"""One-way cleanup for database tables owned by removed legacy products."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


# Child tables precede their parents. Names are fixed here so no external input
# can influence destructive SQL.
LEGACY_TABLES = (
    "risk_events",
    "simulation_positions",
    "simulation_trades",
    "simulation_orders",
    "simulation_accounts",
    "portfolio_group_items",
    "portfolio_groups",
    "strategy_replay_attempts",
    "strategy_replay_runs",
    "backtest_factor_outcomes",
    "backtest_factor_snapshots",
    "backtest_signal_events",
    "backtest_daily_positions",
    "backtest_daily_equity",
    "backtest_metrics",
    "backtest_trades",
    "backtest_orders",
    "backtest_runs",
    "quant_tail_preview_cache",
    "quant_recommendations",
    "quant_stock_signals",
    "quant_signal_runs",
    "quant_strategy_templates",
)


def drop_legacy_product_tables(engine: Engine) -> None:
    """Drop the fixed legacy-product table set if any table still exists."""

    with engine.begin() as connection:
        for table_name in LEGACY_TABLES:
            connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))


__all__ = ["LEGACY_TABLES", "drop_legacy_product_tables"]
