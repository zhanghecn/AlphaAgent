from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from alphaagent.server.api import limit_up
from alphaagent.server.db import schema
from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up import data_quality
from alphaagent.server.services.limit_up import data_quality_repository
from alphaagent.server.services.limit_up import history_repository
from alphaagent.server.services.limit_up import live_repository
from alphaagent.server.services.limit_up import minute_backfill_batch
from alphaagent.server.services.limit_up.data_quality import build_data_quality_report


def _raw_coverage() -> dict[str, object]:
    return {
        "history": {
            "start": "2024-01-15",
            "end": "2026-07-10",
            "trade_days": 600,
        },
        "events": {
            "start": "2026-06-12",
            "end": "2026-07-10",
            "trade_days": 22,
            "rows": 6_939,
            "sealed_rows": 4_939,
            "failed_rows": 2_000,
            "first_touch_rows": 6_939,
            "last_seal_rows": 4_939,
            "open_path_rows": 6_939,
            "seal_amount_rows": 4_939,
        },
        "memberships": {
            "mode": "current_snapshot",
            "symbols": 5_120,
            "rows": 31_000,
            "point_in_time_trade_days": 0,
        },
        "stock_minute": {
            "start": "2026-02-03",
            "end": "2026-07-10",
            "trade_days": 55,
            "symbols": 650,
            "bars": 396_776,
            "event_pairs": 6_939,
            "covered_event_pairs": 1_250,
        },
        "sector_minute": {"trade_days": 0, "rows": 0},
        "auction": {"trade_days": 0, "rows": 0},
        "tick_l2": {"trade_days": 0, "rows": 0},
        "forward": {
            "raw_snapshot_count": 1,
            "eligible_snapshot_count": 0,
            "eligible_trade_days": 0,
        },
        "minute_backfill": {
            "provider": "tdx",
            "attempted_pair_count": 12,
            "covered_pair_count": 8,
            "empty_pair_count": 3,
            "error_pair_count": 1,
            "cooling_down_pair_count": 4,
            "retryable_pair_count": 0,
            "last_attempt_at": "2026-07-11T13:30:00+00:00",
            "next_retry_at": "2026-07-12T13:30:00+00:00",
        },
    }


def test_data_quality_does_not_treat_research_history_as_execution_ready() -> None:
    report = build_data_quality_report(
        _raw_coverage(),
        as_of_date=date(2026, 7, 11),
    )

    gates = {item["key"]: item for item in report["gates"]}
    assert report["status"] == "collecting"
    assert report["research_ledger_ready"] is True
    assert report["simulation_eligible"] is False
    assert gates["history_ledger"]["status"] == "ready"
    assert gates["limit_event_path"]["status"] == "partial"
    assert gates["historical_memberships"]["status"] == "missing"
    assert gates["historical_memberships"]["current"] == 0
    assert gates["stock_minute_path"]["status"] == "partial"
    assert gates["auction_snapshots"]["status"] == "missing"
    assert gates["sector_minute_flow"]["status"] == "missing"
    assert gates["tick_l2_queue"]["status"] == "missing"
    assert gates["forward_observation"]["status"] == "missing"
    assert set(report["blocker_keys"]) == {
        "limit_event_path",
        "historical_memberships",
        "stock_minute_path",
        "auction_snapshots",
        "sector_minute_flow",
        "tick_l2_queue",
        "forward_observation",
    }


def test_data_quality_reports_field_and_candidate_pair_coverage() -> None:
    report = build_data_quality_report(
        _raw_coverage(),
        as_of_date=date(2026, 7, 11),
    )

    assert report["event_fields"] == {
        "first_touch_pct": 100.0,
        "open_path_pct": 100.0,
        "last_seal_pct": 100.0,
        "seal_amount_pct": 100.0,
    }
    assert report["minute_event_pair_coverage"] == {
        "covered": 1_250,
        "total": 6_939,
        "coverage_pct": 18.0141,
    }
    assert report["targets"] == {
        "research_trade_days": 500,
        "execution_history_trade_days": 500,
        "forward_trade_days": 60,
    }
    assert report["minute_backfill_attempts"] == _raw_coverage()["minute_backfill"]


def test_minute_backfill_schema_uses_one_attempt_ledger_row_per_provider_pair() -> None:
    table = schema.limit_up_minute_backfill_attempts

    assert [column.name for column in table.primary_key.columns] == [
        "vt_symbol",
        "trade_date",
        "provider",
    ]
    assert {
        "status",
        "attempt_count",
        "last_rows_read",
        "last_error",
        "last_attempt_at",
        "next_retry_at",
        "created_at",
        "updated_at",
    }.issubset(table.c.keys())


def test_point_in_time_market_evidence_tables_keep_daily_and_intraday_versions() -> None:
    memberships = schema.stock_sector_membership_snapshots
    sector_flows = schema.sector_fund_flow_snapshots
    auctions = schema.stock_auction_snapshots

    assert [column.name for column in memberships.primary_key.columns] == [
        "snapshot_date",
        "vt_symbol",
        "sector_id",
    ]
    assert {
        "captured_at",
        "sector_name",
        "sector_type",
        "source",
        "raw",
    }.issubset(memberships.c.keys())

    assert "captured_minute" in sector_flows.c
    assert "session_stage" in sector_flows.c
    assert "is_stale" in sector_flows.c
    assert {"rise_count", "fall_count", "flat_count", "rise_ratio"}.issubset(
        sector_flows.c.keys()
    )
    assert "uq_sector_fund_flow_snapshot_minute" in {
        constraint.name for constraint in sector_flows.constraints
    }

    assert [column.name for column in auctions.primary_key.columns] == [
        "trade_date",
        "vt_symbol",
    ]
    assert {
        "auction_price",
        "matched_volume",
        "matched_amount",
        "unmatched_volume",
        "unmatched_side",
        "source_updated_at",
        "strict_complete",
    }.issubset(auctions.c.keys())


def test_history_candidate_pool_projection_returns_only_scheduled_inputs(monkeypatch) -> None:
    captured: dict[str, object] = {}
    candidate_pool = {
        "first_board": [{"vt_symbol": "600000.SSE"}],
        "two_to_three": [],
    }

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "trade_date": date(2026, 7, 9),
                    "validation_phase": "locked_holdout",
                    "candidate_pool": candidate_pool,
                }
            ]

    class Session:
        def execute(self, statement):
            captured["statement"] = statement
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(history_repository.schema, "ensure_schema_once", lambda _engine: None)
    monkeypatch.setattr(history_repository, "get_engine", lambda: object())
    monkeypatch.setattr(history_repository, "session_scope", fake_session_scope)

    rows = history_repository.load_history_candidate_pools("limit-up-history-v15")

    assert rows == [
        {
            "trade_date": "2026-07-09",
            "validation_phase": "locked_holdout",
            "lane_portfolio": {"candidate_pool": candidate_pool},
        }
    ]
    sql = str(captured["statement"].compile(dialect=postgresql.dialect()))
    assert "candidate_pool" in sql
    assert "limit_up_history_replays.coverage" not in sql


def test_account_1430_price_query_requires_exact_minute(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "vt_symbol": "600000.SSE",
                    "trade_date": date(2026, 7, 10),
                    "bar_time": datetime(2026, 7, 10, 14, 30),
                    "close_price": 10.8,
                }
            ]

    class Session:
        def execute(self, statement):
            captured["statement"] = statement
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(history_repository.schema, "ensure_schema_once", lambda _engine: None)
    monkeypatch.setattr(history_repository, "get_engine", lambda: object())
    monkeypatch.setattr(history_repository, "session_scope", fake_session_scope)

    rows = history_repository.load_account_1430_prices(
        [("600000.SSE", date(2026, 7, 10))]
    )

    assert rows[0]["price_1430"] == 10.8
    sql = str(
        captured["statement"].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "stock_minute_bars.interval = '1m'" in sql
    assert "to_char(stock_minute_bars.bar_time, 'HH24:MI') = '14:30'" in sql


def test_scheduled_exit_minute_requests_use_all_research_candidate_pools(monkeypatch) -> None:
    history_rows = [
        {
            "trade_date": "2026-07-09",
            "validation_phase": "locked_holdout",
            "lane_portfolio": {
                "candidate_pool": {
                    "first_board": [
                        {
                            "decision": "eligible",
                            "lane": "first_board",
                            "buy_time": "10:05:00",
                            "entry_date": "2026-07-09",
                            "result_date": "2026-07-10",
                            "vt_symbol": "600000.SSE",
                        }
                    ],
                    "two_to_three": [
                        {
                            "decision": "eligible",
                            "lane": "two_to_three",
                            "relay_trigger_status": "ready",
                            "buy_time": "10:10:00",
                            "entry_date": "2026-07-09",
                            "result_date": "2026-07-10",
                            "vt_symbol": "000001.SZSE",
                        }
                    ],
                    "high_board": [
                        {
                            "decision": "eligible",
                            "lane": "high_board",
                            "relay_trigger_status": "ready",
                                "buy_time": "13:35:00",
                            "entry_date": "2026-07-09",
                            "result_date": "2026-07-10",
                            "vt_symbol": "600001.SSE",
                        },
                        {
                            "decision": "blocked",
                            "lane": "high_board",
                            "relay_trigger_status": "ready",
                                "buy_time": "13:36:00",
                            "entry_date": "2026-07-09",
                            "result_date": "2026-07-10",
                            "vt_symbol": "600002.SSE",
                        },
                    ],
                }
            },
        }
    ]
    monkeypatch.setattr(
        data_quality.history_repository,
        "load_history_candidate_pools",
        lambda _version: history_rows,
    )
    monkeypatch.setattr(
        data_quality,
        "_live_recommendation_exit_minute_requests",
        lambda: [
            ("600000.SSE", date(2026, 7, 10)),
            ("600003.SSE", date(2026, 7, 10)),
        ],
    )

    assert data_quality._scheduled_exit_minute_requests() == [
        ("000001.SZSE", date(2026, 7, 10)),
        ("600000.SSE", date(2026, 7, 10)),
        ("600001.SSE", date(2026, 7, 10)),
        ("600003.SSE", date(2026, 7, 10)),
    ]


def test_live_actionable_recommendation_repository_uses_compact_projection(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "trade_date": date(2026, 7, 16),
                    "actionable_recommendations": [
                        {"vt_symbol": "600000.SSE", "action": "buy_now"},
                    ],
                }
            ]

    class Session:
        def execute(self, statement):
            captured["statement"] = statement
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(live_repository, "session_scope", fake_session_scope)

    rows = live_repository.load_actionable_recommendation_snapshots(
        "limit-up-live-v10"
    )

    assert rows == [
        {
            "trade_date": "2026-07-16",
            "actionable_recommendations": [
                {"vt_symbol": "600000.SSE", "action": "buy_now"},
            ],
        }
    ]
    sql = str(
        captured["statement"].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "actionable_recommendations" in sql
    assert "limit_up_signal_snapshots.mode = 'live_snapshot'" in sql


def test_live_recommendation_exit_requests_use_next_completed_trading_date(
    monkeypatch,
) -> None:
    loaded_versions: list[str] = []

    def fake_load(strategy_version: str):
        loaded_versions.append(strategy_version)
        return [
            {
                "trade_date": "2026-07-16",
                "actionable_recommendations": [
                    {"vt_symbol": "600000.SSE"},
                    {"vt_symbol": "600001.SSE"},
                ],
            },
            {
                "trade_date": "2026-07-16",
                "actionable_recommendations": [
                    {"vt_symbol": "600000.SSE"},
                ],
            },
            {
                "trade_date": "2026-07-17",
                "actionable_recommendations": [
                    {"vt_symbol": "600002.SSE"},
                ],
            },
        ]

    monkeypatch.setattr(
        data_quality.live_repository,
        "load_actionable_recommendation_snapshots",
        fake_load,
    )
    monkeypatch.setattr(
        data_quality.live_repository,
        "list_daily_trade_dates",
        lambda: ["2026-07-15", "2026-07-16", "2026-07-17"],
    )

    assert data_quality._live_recommendation_exit_minute_requests() == [
        ("600000.SSE", date(2026, 7, 17)),
        ("600001.SSE", date(2026, 7, 17)),
    ]
    assert loaded_versions == [data_quality.LIVE_STRATEGY_VERSION]


def test_retryable_minute_pairs_use_scoped_provider_and_due_time(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "trade_date": date(2026, 7, 10),
                    "vt_symbol": "600000.SSE",
                    "next_retry_at": None,
                },
                {
                    "trade_date": date(2026, 7, 10),
                    "vt_symbol": "000001.SZSE",
                    "next_retry_at": attempted_at + timedelta(days=1),
                },
            ]

    class Session:
        def execute(self, statement):
            captured["statement"] = statement
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(data_quality_repository.schema, "ensure_schema_once", lambda _engine: None)
    monkeypatch.setattr(data_quality_repository, "get_engine", lambda: object())
    monkeypatch.setattr(data_quality_repository, "session_scope", fake_session_scope)
    attempted_at = datetime(2026, 7, 16, 13, 30, tzinfo=timezone.utc)

    gaps = data_quality_repository.list_retryable_minute_pairs(
        [
            ("600000.SSE", date(2026, 7, 10)),
            ("000001.SZSE", date(2026, 7, 10)),
        ],
        limit=20,
        provider="tdx_exit_1430",
        as_of=attempted_at,
    )

    assert gaps == [{"trade_date": "2026-07-10", "vt_symbol": "600000.SSE"}]
    sql = str(
        captured["statement"].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "limit_up_minute_backfill_attempts.provider = 'tdx_exit_1430'" in sql
    assert "limit_up_minute_backfill_attempts.next_retry_at" in sql


def test_missing_radar_minute_pairs_require_a_complete_240_bar_path(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "trade_date": date(2026, 7, 20),
                    "vt_symbol": "600001.SSE",
                },
                {
                    "trade_date": date(2026, 7, 20),
                    "vt_symbol": "600002.SSE",
                },
            ]

    class Session:
        def execute(self, statement):
            captured["statement"] = statement
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(
        data_quality_repository.schema,
        "ensure_schema_once",
        lambda _engine: None,
    )
    monkeypatch.setattr(data_quality_repository, "get_engine", lambda: object())
    monkeypatch.setattr(data_quality_repository, "session_scope", fake_session_scope)

    gaps = data_quality_repository.list_missing_radar_minute_pairs(
        300,
        provider="tdx_radar_3pct",
        as_of=datetime(2026, 7, 20, 11, 30, tzinfo=timezone.utc),
    )

    assert gaps == [
        {"trade_date": "2026-07-20", "vt_symbol": "600001.SSE"},
        {"trade_date": "2026-07-20", "vt_symbol": "600002.SSE"},
    ]
    sql = str(
        captured["statement"].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "select distinct" in sql
    assert "limit_up_radar_frames.is_stale is false" in sql
    assert "limit_up_radar_frames.quality_status = 'ready'" in sql
    assert (
        "limit_up_radar_frames.source_trade_date = "
        "limit_up_radar_frames.trade_date"
    ) in sql
    assert "stock_minute_bars.interval = '1m'" in sql
    assert "date_trunc('minute'" in sql
    assert "09:31:00" in sql
    assert "11:30:00" in sql
    assert "13:01:00" in sql
    assert "15:00:00" in sql
    assert "coalesce" in sql
    assert "< 240" in sql
    assert "limit_up_minute_backfill_attempts.provider = 'tdx_radar_3pct'" in sql


def test_radar_minute_path_is_complete_only_at_240_bars() -> None:
    assert data_quality_repository.radar_minute_path_complete(239) is False
    assert data_quality_repository.radar_minute_path_complete(240) is True
    assert data_quality_repository.radar_minute_path_complete(241) is True


def test_membership_gate_query_requires_reliable_daily_industry_coverage() -> None:
    statement = data_quality_repository._qualifying_membership_dates_query()
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "stock_sector_membership_snapshots.sector_type = 'industry'" in sql
    assert "count(distinct" in sql.lower()
    assert f">= {data_quality_repository.MIN_RELIABLE_DAILY_SYMBOLS}" in sql
    assert "* 100.0 >=" in sql
    assert f"* {data_quality_repository.MIN_MEMBERSHIP_COVERAGE_PCT}" in sql


def test_membership_counts_separate_raw_industry_concept_and_qualifying_days() -> None:
    class Result:
        def __init__(self, values):
            self.values = values

        def one(self):
            return self.values

    class Session:
        def __init__(self):
            self.results = iter(
                [
                    (31_000, 5_120),
                    (date(2024, 1, 15), date(2026, 7, 10), 600, 3_100_000, 5_120),
                    (date(2024, 1, 15), date(2026, 7, 10), 600, 1_850_000, 3_420),
                    (date(2026, 6, 1), date(2026, 7, 10), 28, 1_250_000, 4_900),
                    (date(2024, 1, 16), date(2026, 7, 10), 599),
                ]
            )

        def execute(self, _statement):
            return Result(next(self.results))

    result = data_quality_repository._membership_counts(Session())

    assert result["raw_snapshot_trade_days"] == 600
    assert result["industry_snapshot_trade_days"] == 600
    assert result["concept_snapshot_trade_days"] == 28
    assert result["point_in_time_trade_days"] == 599
    assert result["start"] == "2024-01-16"
    assert result["mode"] == "daily_point_in_time_industry_snapshot"


def test_membership_counts_short_circuit_when_snapshot_table_is_empty() -> None:
    class Result:
        def __init__(self, values):
            self.values = values

        def one(self):
            return self.values

    class Session:
        def __init__(self):
            self.results = iter([(31_000, 5_120), (None, None, 0, 0, 0)])
            self.execute_count = 0

        def execute(self, _statement):
            self.execute_count += 1
            return Result(next(self.results))

    session = Session()
    result = data_quality_repository._membership_counts(session)

    assert session.execute_count == 2
    assert result["point_in_time_trade_days"] == 0
    assert result["industry_snapshot_trade_days"] == 0
    assert result["concept_snapshot_trade_days"] == 0


def test_partial_auction_quotes_never_unlock_simulation_without_unmatched_volume() -> None:
    raw = _raw_coverage()
    raw["memberships"] = {
        "mode": "daily_append_only_snapshot",
        "symbols": 5_120,
        "rows": 3_100_000,
        "point_in_time_trade_days": 600,
        "start": "2024-01-15",
        "end": "2026-07-10",
    }
    raw["sector_minute"] = {
        "mode": "intraday_append_only_snapshot",
        "trade_days": 600,
        "rows": 1_800_000,
        "start": "2024-01-15",
        "end": "2026-07-10",
    }
    raw["auction"] = {
        "mode": "partial_auction_snapshot",
        "trade_days": 600,
        "strict_trade_days": 0,
        "rows": 3_000_000,
        "strict_rows": 0,
        "unmatched_volume_rows": 0,
        "start": "2024-01-15",
        "end": "2026-07-10",
    }

    report = build_data_quality_report(raw, as_of_date=date(2026, 7, 11))
    gates = {item["key"]: item for item in report["gates"]}

    assert gates["historical_memberships"]["status"] == "ready"
    assert gates["sector_minute_flow"]["status"] == "ready"
    assert gates["auction_snapshots"]["current"] == 600
    assert gates["auction_snapshots"]["status"] == "partial"
    assert report["simulation_eligible"] is False


def test_minute_backfill_retry_policy_uses_one_three_then_fourteen_days() -> None:
    attempted_at = datetime(2026, 7, 11, 13, 30, tzinfo=timezone.utc)

    assert data_quality.minute_backfill_retry_at(attempted_at, 1) == attempted_at + timedelta(days=1)
    assert data_quality.minute_backfill_retry_at(attempted_at, 2) == attempted_at + timedelta(days=3)
    assert data_quality.minute_backfill_retry_at(attempted_at, 3) == attempted_at + timedelta(days=14)
    assert data_quality.minute_backfill_retry_at(attempted_at, 9) == attempted_at + timedelta(days=14)


def test_minute_backfill_error_prefers_the_matching_symbol_request_error() -> None:
    result = {
        "status": "partial",
        "errors": [
            "600001.SSE start=0: TdxFunctionCallError",
            "600002.SSE start=0: TimeoutError",
        ],
        "note": "generic provider note",
    }

    assert data_quality._provider_error_message(result, "600002.SSE") == (
        "600002.SSE start=0: TimeoutError"
    )


def test_event_minute_coverage_and_backfill_use_only_non_st_main_board() -> None:
    statement = data_quality_repository._event_pairs().select()
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "JOIN stocks" in sql
    assert "JOIN stock_daily_bars" in sql
    assert "stock_daily_bars.vt_symbol = stock_events.vt_symbol" in sql
    assert "stock_daily_bars.trade_date = CASE" in sql
    assert "stocks.exchange = 'SSE'" in sql
    assert "stocks.exchange = 'SZSE'" in sql
    assert all(f"stocks.symbol LIKE '{prefix}'" in sql for prefix in data_quality_repository.MAIN_BOARD_PREFIXES)
    assert "300" not in sql
    assert "688" not in sql
    assert "coalesce(stocks.name" in sql


def test_event_gate_counts_only_same_symbol_trading_dates() -> None:
    captured: dict[str, object] = {}

    class Result:
        def one(self):
            return (None, None, 0, 0, 0, 0, 0, 0, 0, 0)

    class Session:
        def execute(self, statement):
            captured["statement"] = statement
            return Result()

    data_quality_repository._event_counts(Session())
    sql = str(
        captured["statement"].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "JOIN stock_daily_bars" in sql
    assert "stock_daily_bars.vt_symbol = stock_events.vt_symbol" in sql
    assert "stock_daily_bars.trade_date = CASE" in sql
    assert sql.count("anon_1.event_type = 'limit_pool_zt'") == 3
    assert (
        "anon_1.event_type = 'limit_pool_zt' AND "
        "(anon_1.raw ->> '\u6700\u540e\u5c01\u677f\u65f6\u95f4') IS NOT NULL"
    ) in sql
    assert (
        "anon_1.event_type = 'limit_pool_zt' AND "
        "coalesce((anon_1.raw ->> '\u5c01\u677f\u8d44\u91d1'), "
        "(anon_1.raw ->> '\u6da8\u505c\u5c01\u5355\u91cf')) IS NOT NULL"
    ) in sql


def test_event_gate_keeps_only_the_latest_intraday_stock_state() -> None:
    statement = data_quality_repository._valid_event_rows().select()
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "row_number() OVER" in sql
    assert "PARTITION BY stock_events.vt_symbol" in sql
    assert (
        "ORDER BY stock_events.updated_at DESC, stock_events.created_at DESC, "
        "stock_events.id DESC"
    ) in sql
    assert "event_snapshot_rank = 1" in sql


def test_minute_backfill_attempt_counts_ignore_obsolete_non_trading_event_pairs() -> None:
    captured: dict[str, object] = {}

    class Result:
        def one(self):
            return (0, 0, 0, 0, 0, 0, None, None)

    class Session:
        def execute(self, statement):
            captured["statement"] = statement
            return Result()

    data_quality_repository._minute_backfill_counts(Session(), provider="tdx")
    sql = str(
        captured["statement"].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "JOIN stock_daily_bars" in sql
    assert "limit_up_minute_backfill_attempts.vt_symbol" in sql
    assert "limit_up_minute_backfill_attempts.trade_date" in sql
    assert "limit_up_minute_backfill_attempts.provider = 'tdx'" in sql


def test_data_quality_endpoint_returns_service_payload(monkeypatch) -> None:
    expected = {"status": "collecting", "simulation_eligible": False}
    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_data_quality", lambda: expected)

    response = TestClient(create_app()).get("/api/limit-up/data-quality")

    assert response.status_code == 200
    assert response.json()["data"] == expected


def test_data_quality_endpoint_fails_closed_without_database(monkeypatch) -> None:
    monkeypatch.setattr(limit_up, "is_database_configured", lambda: False)

    response = TestClient(create_app()).get("/api/limit-up/data-quality")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_event_minute_backfill_uses_only_missing_pairs_and_full_session(monkeypatch) -> None:
    captured: dict[str, object] = {}
    recorded: dict[str, object] = {}
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "list_missing_event_minute_pairs",
        lambda limit, **_kwargs: [
            {"trade_date": "2026-07-10", "vt_symbol": "000004.SZSE"},
            {"trade_date": "2026-07-10", "vt_symbol": "000021.SZSE"},
        ][:limit],
    )

    def fake_import(params: dict[str, object]) -> dict[str, object]:
        captured.update(params)
        return {"status": "ready", "rows_read": 480, "rows_written": 480}

    monkeypatch.setattr(data_quality.minute_provider_imports, "import_minute_bars_for_gaps", fake_import)
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "load_event_minute_pair_bar_counts",
        lambda gaps: {
            ("000004.SZSE", date(2026, 7, 10)): 240,
            ("000021.SZSE", date(2026, 7, 10)): 0,
        },
    )

    def fake_record(attempts, *, provider, attempted_at):
        recorded.update({"attempts": attempts, "provider": provider, "attempted_at": attempted_at})

    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "record_minute_backfill_attempts",
        fake_record,
    )
    monkeypatch.setattr(
        data_quality,
        "get_limit_up_data_quality",
        lambda: {"minute_event_pair_coverage": {"covered": 208, "total": 2_839, "coverage_pct": 7.3265}},
    )

    result = data_quality.backfill_limit_up_event_minutes(max_gaps=2, dry_run=False)

    assert result["status"] == "ready"
    assert result["scope"] == "limit_up_event_full_session"
    assert result["requested_gap_count"] == 2
    assert captured["provider"] == "tdx"
    assert captured["tail_entry_start"] == "09:15"
    assert captured["tail_entry_end"] == "15:00"
    assert captured["dry_run"] is False
    assert captured["gaps"] == [
        {"trade_date": "2026-07-10", "vt_symbol": "000004.SZSE"},
        {"trade_date": "2026-07-10", "vt_symbol": "000021.SZSE"},
    ]
    assert result["data_quality"]["minute_event_pair_coverage"]["covered"] == 208
    assert recorded["provider"] == "tdx"
    assert [item["status"] for item in recorded["attempts"]] == ["covered", "empty"]
    assert [item["last_rows_read"] for item in recorded["attempts"]] == [240, 0]


def test_event_minute_backfill_records_remote_failure_and_dry_run_records_nothing(monkeypatch) -> None:
    gap = {"trade_date": "2026-07-10", "vt_symbol": "000004.SZSE"}
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "list_missing_event_minute_pairs",
        lambda limit, **_kwargs: [gap][:limit],
    )
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "load_event_minute_pair_bar_counts",
        lambda _gaps: {("000004.SZSE", date(2026, 7, 10)): 0},
    )
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "record_minute_backfill_attempts",
        lambda attempts, **_kwargs: recorded.extend(attempts),
    )
    monkeypatch.setattr(
        data_quality,
        "get_limit_up_data_quality",
        lambda: {"minute_event_pair_coverage": {"covered": 0, "total": 1, "coverage_pct": 0}},
    )
    monkeypatch.setattr(
        data_quality.minute_provider_imports,
        "import_minute_bars_for_gaps",
        lambda _params: {
            "status": "unavailable",
            "rows_read": 0,
            "rows_written": 0,
            "message": "TDX unavailable",
        },
    )

    result = data_quality.backfill_limit_up_event_minutes(max_gaps=1, dry_run=False)

    assert result["status"] == "unavailable"
    assert recorded == [
        {
            **gap,
            "status": "error",
            "last_rows_read": 0,
            "last_error": "TDX unavailable",
        }
    ]

    recorded.clear()
    dry_run = data_quality.backfill_limit_up_event_minutes(max_gaps=1, dry_run=True)
    assert dry_run["dry_run"] is True
    assert recorded == []


def test_event_minute_backfill_reports_cooling_down_when_no_pair_is_retryable(monkeypatch) -> None:
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "list_missing_event_minute_pairs",
        lambda _limit, **_kwargs: [],
    )
    monkeypatch.setattr(
        data_quality,
        "get_limit_up_data_quality",
        lambda: {
            "minute_event_pair_coverage": {"covered": 10, "total": 20, "coverage_pct": 50},
            "minute_backfill_attempts": {
                "cooling_down_pair_count": 10,
                "next_retry_at": "2026-07-12T13:30:00+00:00",
            },
        },
    )

    result = data_quality.backfill_limit_up_event_minutes(max_gaps=20, dry_run=False)

    assert result["status"] == "cooling_down"
    assert result["requested_gap_count"] == 0
    assert "10 个缺口处于冷却" in result["message"]


def test_radar_minute_backfill_requires_240_bars_and_uses_its_own_retry_scope(
    monkeypatch,
) -> None:
    gaps = [
        {"trade_date": "2026-07-20", "vt_symbol": "600001.SSE"},
        {"trade_date": "2026-07-20", "vt_symbol": "600002.SSE"},
    ]
    captured: dict[str, object] = {}
    recorded: dict[str, object] = {}
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "list_missing_radar_minute_pairs",
        lambda limit, **kwargs: captured.update(
            {"gap_limit": limit, "gap_query": kwargs}
        )
        or gaps[:limit],
    )

    def fake_import(params: dict[str, object]) -> dict[str, object]:
        captured["import_params"] = dict(params)
        return {"status": "ready", "rows_read": 479, "rows_written": 479}

    monkeypatch.setattr(
        data_quality.minute_provider_imports,
        "import_minute_bars_for_gaps",
        fake_import,
    )
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "load_radar_minute_pair_slot_counts",
        lambda _gaps: {
            ("600001.SSE", date(2026, 7, 20)): 240,
            ("600002.SSE", date(2026, 7, 20)): 239,
        },
    )

    def fake_record(attempts, *, provider, attempted_at):
        recorded.update(
            {
                "attempts": attempts,
                "provider": provider,
                "attempted_at": attempted_at,
            }
        )

    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "record_minute_backfill_attempts",
        fake_record,
    )

    result = data_quality.backfill_limit_up_radar_minutes(
        max_gaps=300,
        dry_run=False,
    )

    assert captured["gap_limit"] == 300
    assert captured["gap_query"]["provider"] == "tdx_radar_3pct"
    params = captured["import_params"]
    assert params["provider"] == "tdx"
    assert params["tail_entry_start"] == "09:15"
    assert params["tail_entry_end"] == "15:00"
    assert params["max_gaps"] == 2
    assert params["gaps"] == gaps
    assert recorded["provider"] == "tdx_radar_3pct"
    assert [item["status"] for item in recorded["attempts"]] == [
        "covered",
        "empty",
    ]
    assert [item["last_rows_read"] for item in recorded["attempts"]] == [240, 239]
    assert result["scope"] == "limit_up_radar_3pct_full_session"
    assert result["covered_gap_count"] == 1
    assert result["empty_gap_count"] == 1


def test_radar_minute_backfill_does_not_record_dry_run(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "list_missing_radar_minute_pairs",
        lambda *_args, **_kwargs: [
            {"trade_date": "2026-07-20", "vt_symbol": "600001.SSE"}
        ],
    )
    monkeypatch.setattr(
        data_quality.minute_provider_imports,
        "import_minute_bars_for_gaps",
        lambda _params: {
            "status": "ready",
            "rows_read": 240,
            "rows_written": 0,
            "preview_covered_gap_count": 1,
        },
    )
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "record_minute_backfill_attempts",
        lambda attempts, **_kwargs: recorded.extend(attempts),
    )

    result = data_quality.backfill_limit_up_radar_minutes(
        max_gaps=1,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["covered_gap_count"] == 1
    assert recorded == []


def test_exit_minute_backfill_imports_only_missing_exact_1430_pairs(monkeypatch) -> None:
    existing = ("000001.SZSE", date(2026, 7, 10))
    covered_after_import = ("600000.SSE", date(2026, 7, 10))
    still_missing = ("600001.SSE", date(2026, 7, 10))
    captured: dict[str, object] = {}
    recorded: dict[str, object] = {}
    price_load_count = 0

    monkeypatch.setattr(
        data_quality,
        "_scheduled_exit_minute_requests",
        lambda: [existing, covered_after_import, still_missing],
    )

    def fake_load_1430(requests):
        nonlocal price_load_count
        price_load_count += 1
        captured[f"price_requests_{price_load_count}"] = list(requests)
        pair = existing if price_load_count == 1 else covered_after_import
        return [
            {
                "vt_symbol": pair[0],
                "trade_date": pair[1].isoformat(),
                "bar_time": f"{pair[1].isoformat()}T14:30:00",
                "price_1430": 10.8,
            }
        ]

    monkeypatch.setattr(
        data_quality.history_repository,
        "load_account_1430_prices",
        fake_load_1430,
    )

    def fake_retryable(pairs, *, provider, as_of, limit):
        captured.update(
            {
                "retry_pairs": list(pairs),
                "retry_provider": provider,
                "retry_as_of": as_of,
                "retry_limit": limit,
            }
        )
        return [
            {"vt_symbol": symbol, "trade_date": trade_date.isoformat()}
            for symbol, trade_date in pairs[:limit]
        ]

    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "list_retryable_minute_pairs",
        fake_retryable,
    )

    def fake_import(params):
        captured["import_params"] = dict(params)
        return {"status": "ready", "rows_read": 2, "rows_written": 2}

    monkeypatch.setattr(
        data_quality.minute_provider_imports,
        "import_minute_bars_for_gaps",
        fake_import,
    )

    def fake_record(attempts, *, provider, attempted_at):
        recorded.update(
            {
                "attempts": attempts,
                "provider": provider,
                "attempted_at": attempted_at,
            }
        )

    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "record_minute_backfill_attempts",
        fake_record,
    )

    result = data_quality.backfill_limit_up_exit_minutes(max_gaps=2, dry_run=False)

    assert captured["retry_pairs"] == [covered_after_import, still_missing]
    assert captured["retry_provider"] == "tdx_exit_1430"
    assert captured["retry_limit"] == 2
    assert captured["price_requests_2"] == [covered_after_import, still_missing]
    assert captured["import_params"]["provider"] == "tdx"
    assert captured["import_params"]["tail_entry_start"] == "14:30"
    assert captured["import_params"]["tail_entry_end"] == "14:30"
    assert captured["import_params"]["gaps"] == [
        {"vt_symbol": "600000.SSE", "trade_date": "2026-07-10"},
        {"vt_symbol": "600001.SSE", "trade_date": "2026-07-10"},
    ]
    assert recorded["provider"] == "tdx_exit_1430"
    assert [item["status"] for item in recorded["attempts"]] == ["covered", "empty"]
    assert [item["last_rows_read"] for item in recorded["attempts"]] == [1, 0]
    assert result["scope"] == "limit_up_candidate_exit_1430"
    assert result["candidate_request_count"] == 3
    assert result["existing_covered_pair_count"] == 1
    assert result["covered_gap_count"] == 1
    assert result["empty_gap_count"] == 1


def test_exit_minute_backfill_reports_cooling_down_without_retryable_pairs(monkeypatch) -> None:
    request = ("600000.SSE", date(2026, 7, 10))
    monkeypatch.setattr(data_quality, "_scheduled_exit_minute_requests", lambda: [request])
    monkeypatch.setattr(
        data_quality.history_repository,
        "load_account_1430_prices",
        lambda _requests: [],
    )
    monkeypatch.setattr(
        data_quality.data_quality_repository,
        "list_retryable_minute_pairs",
        lambda _pairs, **_kwargs: [],
    )

    result = data_quality.backfill_limit_up_exit_minutes(max_gaps=20, dry_run=False)

    assert result["status"] == "cooling_down"
    assert result["scope"] == "limit_up_candidate_exit_1430"
    assert result["candidate_request_count"] == 1
    assert result["missing_pair_count"] == 1
    assert result["requested_gap_count"] == 0
    assert "1 个候选卖出价缺口处于冷却" in result["message"]


def test_event_minute_backfill_endpoint_validates_batch_size(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_backfill(*, max_gaps: int, dry_run: bool) -> dict[str, object]:
        captured.update({"max_gaps": max_gaps, "dry_run": dry_run})
        return {"status": "ready", "rows_written": 2_400}

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "backfill_limit_up_event_minutes", fake_backfill)

    response = TestClient(create_app()).post(
        "/api/limit-up/data-quality/minute-backfill",
        json={"max_gaps": 20, "dry_run": False},
    )

    assert response.status_code == 200
    assert response.json()["data"]["rows_written"] == 2_400
    assert captured == {"max_gaps": 20, "dry_run": False}

    invalid = TestClient(create_app()).post(
        "/api/limit-up/data-quality/minute-backfill",
        json={"max_gaps": 201, "dry_run": False},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_GAP_BATCH_SIZE"


def _minute_backfill_batch(batch_id: str = "batch-1") -> dict[str, object]:
    return {
        "id": batch_id,
        "status": "running",
        "total_jobs": 1,
        "completed_jobs": 0,
        "rows_read": 0,
        "rows_written": 0,
        "jobs": [
            {
                "job_id": minute_backfill_batch.JOB_ID,
                "status": "running",
                "rows_read": 0,
                "rows_written": 0,
                "message": "",
            }
        ],
    }


def test_minute_backfill_batch_service_starts_only_the_target_job(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_start_sync_batch(**kwargs):
        captured.update(kwargs)
        return _minute_backfill_batch()

    monkeypatch.setattr(minute_backfill_batch.data_sync, "start_sync_batch", fake_start_sync_batch)

    result = minute_backfill_batch.start_minute_backfill_batch(max_gaps=200)

    assert result["id"] == "batch-1"
    assert captured == {
        "job_ids": [minute_backfill_batch.JOB_ID],
        "params": {
            "jobs": {
                minute_backfill_batch.JOB_ID: {
                    "max_gaps": 200,
                    "dry_run": False,
                }
            }
        },
        "concurrency": 1,
        "source": "manual",
    }


def test_minute_backfill_batch_service_rejects_an_unrelated_running_batch(monkeypatch) -> None:
    unrelated = {
        **_minute_backfill_batch("other-batch"),
        "jobs": [{"job_id": "sync_stock_daily_bars", "status": "running"}],
    }
    monkeypatch.setattr(
        minute_backfill_batch.data_sync,
        "start_sync_batch",
        lambda **_kwargs: unrelated,
    )

    with pytest.raises(minute_backfill_batch.MinuteBackfillBatchBusyError) as exc_info:
        minute_backfill_batch.start_minute_backfill_batch(max_gaps=200)

    assert exc_info.value.batch["id"] == "other-batch"


def test_minute_backfill_batch_start_endpoint_returns_202_and_validates_size(monkeypatch) -> None:
    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "start_limit_up_minute_backfill_batch",
        lambda *, max_gaps: _minute_backfill_batch(),
    )

    response = TestClient(create_app()).post(
        "/api/limit-up/data-quality/minute-backfill/start",
        json={"max_gaps": 200},
    )

    assert response.status_code == 202
    assert response.json()["data"]["id"] == "batch-1"

    invalid = TestClient(create_app()).post(
        "/api/limit-up/data-quality/minute-backfill/start",
        json={"max_gaps": 201},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_GAP_BATCH_SIZE"


def test_minute_backfill_batch_start_endpoint_reports_unrelated_batch_as_busy(monkeypatch) -> None:
    unrelated = {
        **_minute_backfill_batch("other-batch"),
        "jobs": [{"job_id": "sync_stock_daily_bars", "status": "running"}],
    }
    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)

    def raise_busy(*, max_gaps: int):
        raise minute_backfill_batch.MinuteBackfillBatchBusyError(unrelated)

    monkeypatch.setattr(limit_up, "start_limit_up_minute_backfill_batch", raise_busy)

    response = TestClient(create_app()).post(
        "/api/limit-up/data-quality/minute-backfill/start",
        json={"max_gaps": 200},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATA_SYNC_BATCH_BUSY"
    assert response.json()["error"]["detail"]["batch_id"] == "other-batch"


def test_minute_backfill_batch_query_rejects_an_unrelated_batch(monkeypatch) -> None:
    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)

    def raise_not_found(_batch_id: str):
        raise minute_backfill_batch.MinuteBackfillBatchNotFoundError("other-batch")

    monkeypatch.setattr(limit_up, "get_limit_up_minute_backfill_batch", raise_not_found)

    response = TestClient(create_app()).get(
        "/api/limit-up/data-quality/minute-backfill/batches/other-batch"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MINUTE_BACKFILL_BATCH_NOT_FOUND"
