from pathlib import Path

from alphaagent.server.db import legacy_product_cleanup, schema
from alphaagent.server.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_TABLES = {
    "leader_forward_signals",
    "premarket_prelude_snapshots",
    "premarket_fused_score_snapshots",
    "leader_first_board_backtest_runs",
    "leader_minute_backtest_runs",
    "leader_sweep_backtest_runs",
    "limit_up_radar_observations",
    "limit_up_radar_frames",
    "limit_up_live_trace_snapshots",
    "limit_up_concept_strength_snapshots",
    "limit_up_signal_snapshots",
    "limit_up_history_replays",
    "limit_up_minute_backfill_attempts",
    "limit_up_preboard_point_actions",
    "limit_up_preboard_point_day_scopes",
    "limit_up_preboard_point_feature_rows",
    "limit_up_preboard_point_model_versions",
    "limit_up_transaction_feature_scopes",
    "limit_up_transaction_features",
    "limit_up_transaction_pair_manifests",
    "quant_strategy_templates",
    "quant_signal_runs",
    "quant_stock_signals",
    "quant_recommendations",
    "quant_tail_preview_cache",
    "backtest_runs",
    "backtest_orders",
    "backtest_trades",
    "backtest_signal_events",
    "backtest_factor_snapshots",
    "backtest_factor_outcomes",
    "backtest_daily_equity",
    "backtest_daily_positions",
    "backtest_metrics",
    "strategy_replay_runs",
    "strategy_replay_attempts",
    "portfolio_groups",
    "portfolio_group_items",
    "simulation_accounts",
    "simulation_orders",
    "simulation_trades",
    "simulation_positions",
    "risk_events",
}


def test_market_timing_imports_do_not_use_quant_namespace() -> None:
    roots = [
        PROJECT_ROOT / "alphaagent/server/api/market_timing.py",
        PROJECT_ROOT / "alphaagent/server/main.py",
        PROJECT_ROOT / "alphaagent/server/services/market_context.py",
        PROJECT_ROOT / "alphaagent/server/services/market_timing",
    ]
    sources: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        sources.extend(path.read_text() for path in paths)

    assert sources
    assert "services.quant" not in "\n".join(sources)


def test_legacy_product_routes_are_absent() -> None:
    paths = {route.path for route in create_app().routes}

    assert not any(path.startswith("/api/quant") for path in paths)
    assert not any(path.startswith("/api/backtests") for path in paths)
    assert not any(path.startswith("/api/portfolios") for path in paths)
    assert not any(path.startswith("/api/simulation") for path in paths)


def test_preserved_research_routes_remain() -> None:
    paths = {route.path for route in create_app().routes}

    assert not any(path.startswith("/api/limit-up") for path in paths)
    assert any(path.startswith("/api/first-board") for path in paths)
    assert any(path.startswith("/api/low-suction") for path in paths)
    assert any(path.startswith("/api/market-timing") for path in paths)
    assert any(path.startswith("/api/mainline-replay") for path in paths)


def test_legacy_tables_are_not_in_metadata() -> None:
    assert LEGACY_TABLES.isdisjoint(schema.metadata.tables)


def test_cleanup_manifest_matches_schema_test() -> None:
    assert set(legacy_product_cleanup.LEGACY_TABLES) == LEGACY_TABLES


def test_legacy_service_packages_are_absent() -> None:
    services_root = PROJECT_ROOT / "alphaagent/server/services"
    for package_name in ("quant", "backtest", "portfolio", "simulation"):
        assert not any((services_root / package_name).glob("*.py"))
    assert not (services_root / "limit_up").exists()
