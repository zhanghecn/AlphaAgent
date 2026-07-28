import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import radar_observation_repository as repo
from alphaagent.server.services.limit_up.capture_runtime import (
    build_capture_runtime_fingerprint,
    is_capture_runtime_fingerprint,
)


def test_compact_radar_tables_are_registered() -> None:
    assert "limit_up_radar_frames" in schema.metadata.tables
    assert "limit_up_radar_observations" in schema.metadata.tables


def test_radar_observations_define_point_in_time_flow_sources() -> None:
    fields = {
        "quote_speed",
        "quote_amplitude_pct",
        "quote_main_net_inflow",
        "quote_main_inflow",
        "quote_main_outflow",
        "quote_main_net_inflow_ratio",
        "quote_flow_observed_at",
        "sector_main_net_inflow_ratio",
        "sector_flow_trade_date",
        "stock_main_net_inflow_ratio",
        "stock_flow_trade_date",
        "lane_blocker_codes",
        "prior_limit_count_126",
        "prior_industry_turnover_ratio_5d",
        "prior_return_5d_pct",
        "prior_market_phase",
        "stock_d1_sample_count",
        "stock_d1_win_rate",
        "stock_d1_average_return_pct",
        "stock_gene_combined_win_rate",
        "profitability_gate_passed",
        "recognition_gate_passed",
        "core_quality_gate_passed",
        "core_quality_gate_reason",
        "quality_priority_tier",
        "public_quality_contract_version",
        "public_quality_status",
        "public_quality_gate_passed",
        "public_quality_actionable",
        "public_quality_reason",
        "quality_win_probability",
        "quality_expected_d1_net_return_pct",
        "concept_near_limit_count",
        "concept_touched_count",
        "concept_sealed_count",
        "concept_failed_count",
        "board_level",
        "concept_candidates",
        "concept_membership_snapshot_date",
        "concept_trigger_allowed",
    }

    assert fields.issubset(
        {column.name for column in schema.limit_up_radar_observations.columns}
    )
    assert {
        "capture_runtime_fingerprint",
        "formal_two_slot_observed",
        "formal_two_slot_symbols",
    }.issubset(schema.limit_up_radar_frames.c.keys())


def test_replay_observation_loader_uses_compact_projection(monkeypatch) -> None:
    statements: list[object] = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(repo, "session_scope", fake_session_scope)

    assert repo.load_replay_observations(
        date(2026, 7, 20),
        date(2026, 7, 22),
        symbols=["600001.SSE"],
    ) == []

    sql = str(statements[0].compile(dialect=postgresql.dialect())).lower()
    assert "limit_up_radar_observations.change_pct" in sql
    assert "limit_up_radar_observations.concept_candidates" not in sql
    assert "limit_up_radar_observations.public_quality_status" not in sql


def test_forward_research_loader_pushes_quality_filters_into_sql(monkeypatch) -> None:
    statements: list[object] = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(repo, "session_scope", fake_session_scope)

    assert repo.load_forward_research_observations(
        date(2026, 7, 17),
        date(2026, 7, 28),
    ) == []

    sql = str(
        statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "limit_up_radar_frames.is_stale is false" in sql
    assert "limit_up_radar_frames.quality_status = 'ready'" in sql
    assert "limit_up_radar_observations.change_pct >= 3.0" in sql
    assert "limit_up_radar_observations.board_lane in ('first_board', 'two_to_three')" in sql
    assert "distinct on (limit_up_radar_frames.trade_date, limit_up_radar_observations.vt_symbol)" in sql
    assert "limit_up_radar_observations.concept_candidates" not in sql
    assert "limit_up_radar_observations.public_quality_status" not in sql


def test_official_two_slot_evidence_rejects_oversized_or_ambiguous_sources() -> None:
    assert repo.official_two_slot_evidence(
        {"recommendations": {"portfolio": []}}
    ) == ([], True)
    assert repo.official_two_slot_evidence(
        {
            "recommendations": {
                "portfolio": [
                    {"vt_symbol": "600001.SSE"},
                    {"vt_symbol": "600002.SSE"},
                    {"vt_symbol": "600003.SSE"},
                ]
            }
        }
    ) == ([], False)
    assert repo.official_two_slot_evidence(
        {"recommendations": {"lanes": {"now": []}}}
    ) == ([], False)


def test_flow_source_schema_patches_are_idempotent() -> None:
    executed: list[str] = []

    class Connection:
        def exec_driver_sql(self, sql: str) -> None:
            executed.append(sql)

    class Transaction:
        def __enter__(self):
            return Connection()

        def __exit__(self, exc_type, exc, traceback):
            return False

    class Engine:
        def begin(self):
            return Transaction()

    schema._apply_compatible_schema_patches(Engine())

    for field in (
        "quote_speed FLOAT",
        "quote_amplitude_pct FLOAT",
        "quote_main_net_inflow FLOAT",
        "quote_main_inflow FLOAT",
        "quote_main_outflow FLOAT",
        "quote_main_net_inflow_ratio FLOAT",
        "quote_flow_observed_at TIMESTAMPTZ",
        "sector_main_net_inflow_ratio FLOAT",
        "sector_flow_trade_date DATE",
        "stock_main_net_inflow_ratio FLOAT",
        "stock_flow_trade_date DATE",
        "lane_blocker_codes JSONB",
        "prior_limit_count_126 INTEGER",
        "prior_industry_turnover_ratio_5d FLOAT",
        "prior_return_5d_pct FLOAT",
        "prior_market_phase VARCHAR(24)",
        "stock_d1_sample_count INTEGER",
        "stock_d1_win_rate FLOAT",
        "stock_d1_average_return_pct FLOAT",
        "stock_gene_combined_win_rate FLOAT",
        "profitability_gate_passed BOOLEAN",
        "recognition_gate_passed BOOLEAN",
        "core_quality_gate_passed BOOLEAN",
        "core_quality_gate_reason VARCHAR(160)",
        "quality_priority_tier VARCHAR(40)",
        "public_quality_contract_version VARCHAR(80)",
        "public_quality_status VARCHAR(40)",
        "public_quality_gate_passed BOOLEAN",
        "public_quality_actionable BOOLEAN",
        "public_quality_reason VARCHAR(160)",
        "quality_win_probability FLOAT",
        "quality_expected_d1_net_return_pct FLOAT",
        "concept_near_limit_count INTEGER",
        "concept_touched_count INTEGER",
        "concept_sealed_count INTEGER",
        "concept_failed_count INTEGER",
        "board_level INTEGER",
        "concept_candidates JSONB",
        "concept_membership_snapshot_date DATE",
        "concept_trigger_allowed BOOLEAN",
        "capture_runtime_fingerprint VARCHAR(80)",
    ):
        assert any(
            f"ADD COLUMN IF NOT EXISTS {field}" in sql
            for sql in executed
        )
    assert any(
        "ALTER TABLE limit_up_radar_frames ADD COLUMN IF NOT EXISTS "
        "capture_runtime_fingerprint VARCHAR(80)" in sql
        for sql in executed
    )


def test_radar_retention_keeps_ninety_trade_days() -> None:
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=index) for index in range(100)]

    assert repo.retention_cutoff(dates, retain_trade_days=90) == sorted(dates)[-90]


def test_capture_runtime_fingerprint_is_deterministic_and_source_sensitive(
    tmp_path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "capture.py").write_text("VALUE = 1\n", encoding="ascii")
    (second_root / "provider.py").write_text("VALUE = 2\n", encoding="ascii")
    roots = (("second", second_root), ("first", first_root))
    metadata = {"python": "3.13", "packages": [["pandas", "2.3.0"]]}

    first = build_capture_runtime_fingerprint(roots, metadata)
    reordered = build_capture_runtime_fingerprint(tuple(reversed(roots)), metadata)
    changed_runtime = build_capture_runtime_fingerprint(
        roots,
        {"python": "3.14", "packages": [["pandas", "2.3.0"]]},
    )
    (first_root / "capture.py").write_text("VALUE = 3\n", encoding="ascii")
    changed_source = build_capture_runtime_fingerprint(roots, metadata)

    assert is_capture_runtime_fingerprint(first)
    assert reordered == first
    assert changed_runtime != first
    assert changed_source != first


def test_projection_drops_large_nested_payloads() -> None:
    row = repo.project_observation(
        _candidate("600001.SSE"),
        formal_signal={"action": "buy_now", "entry_kind": "sweep"},
    )

    assert row["vt_symbol"] == "600001.SSE"
    assert row["formal_action"] == "buy_now"
    assert "financial_snapshot" not in row
    assert "raw" not in row


def test_projection_preserves_bounded_short_horizon_evidence() -> None:
    candidate = {
        **_candidate("600001.SSE"),
        "volume": 123_400.0,
        "turnover": 456_700_000.0,
        "turnover_rate": 8.2,
        "volume_ratio": 2.4,
        "lane_rank_score": 76.5,
        "lane_blockers": ["intraday_support_unavailable"],
        "quote_speed": 1.2,
        "quote_amplitude_pct": 6.4,
        "quote_main_net_inflow": 12_000_000.0,
        "quote_main_inflow": 56_000_000.0,
        "quote_main_outflow": 44_000_000.0,
        "quote_main_net_inflow_ratio": 2.63,
        "quote_flow_observed_at": "2026-07-20T10:05:03+08:00",
        "concept_change_acceleration_1m": 0.2,
        "concept_change_acceleration_3m": 0.7,
        "concept_change_acceleration_5m": 1.1,
        "concept_turnover_acceleration_1m": 12_000_000.0,
        "concept_turnover_acceleration_3m": 30_000_000.0,
        "concept_turnover_acceleration_5m": 55_000_000.0,
        "prior_limit_count_126": 4,
        "prior_industry_turnover_ratio_5d": 1.24,
        "prior_return_5d_pct": -2.5,
        "prior_market_phase": "mixed",
        "board_level": 2,
        "concept_candidates": [
            {
                "concept_id": "BK0877",
                "concept_name": "通信设备",
                "member_count": 42,
                "strength_rank": 3,
                "ignored_large_field": "x" * 1000,
            }
        ],
        "concept_trigger_allowed": True,
        "concept_near_limit_count": 3,
        "concept_touched_count": 2,
        "concept_sealed_count": 1,
        "concept_failed_count": 1,
        "sector_main_net_inflow": 88_000_000.0,
        "sector_main_net_inflow_ratio": 2.8,
        "sector_flow_trade_date": "20260720",
        "stock_main_net_inflow": 12_000_000.0,
        "stock_main_net_inflow_ratio": 1.2,
        "stock_flow_trade_date": "2026-07-20T10:04:00+08:00",
    }
    observed_at = datetime.fromisoformat("2026-07-20T10:05:15+08:00")

    row = repo.project_observation(
        candidate,
        formal_signal={
            "stock_d1_sample_count": 6,
            "stock_gene_combined_win_rate": 42.5,
            "profitability_gate_passed": True,
            "recognition_gate_passed": True,
            "core_quality_gate_passed": True,
            "core_quality_gate_reason": "qualified",
            "quality_priority_tier": "A_industry_expanding",
        },
        quote_observed_at=observed_at,
        concept_membership_snapshot_date=date(2026, 7, 19),
    )

    assert row["quote_observed_at"] == observed_at
    assert row["volume"] == 123_400.0
    assert row["turnover"] == 456_700_000.0
    assert row["turnover_rate"] == 8.2
    assert row["volume_ratio"] == 2.4
    assert row["rank_score"] == 76.5
    assert row["lane_blocker_codes"] == ["intraday_support_unavailable"]
    assert row["quote_speed"] == 1.2
    assert row["quote_amplitude_pct"] == 6.4
    assert row["quote_main_net_inflow"] == 12_000_000.0
    assert row["quote_main_inflow"] == 56_000_000.0
    assert row["quote_main_outflow"] == 44_000_000.0
    assert row["quote_main_net_inflow_ratio"] == 2.63
    assert row["quote_flow_observed_at"] == datetime.fromisoformat(
        "2026-07-20T10:05:03+08:00"
    )
    assert row["concept_change_acceleration_1m"] == 0.2
    assert row["concept_change_acceleration_3m"] == 0.7
    assert row["concept_change_acceleration_5m"] == 1.1
    assert row["concept_turnover_acceleration_1m"] == 12_000_000.0
    assert row["concept_turnover_acceleration_3m"] == 30_000_000.0
    assert row["concept_turnover_acceleration_5m"] == 55_000_000.0
    assert row["prior_limit_count_126"] == 4
    assert row["prior_industry_turnover_ratio_5d"] == 1.24
    assert row["prior_return_5d_pct"] == -2.5
    assert row["prior_market_phase"] == "mixed"
    assert row["board_level"] == 2
    assert row["concept_candidates"] == [
        {
            "concept_id": "BK0877",
            "concept_name": "通信设备",
            "member_count": 42,
            "strength_rank": 3,
        }
    ]
    assert row["concept_membership_snapshot_date"] == date(2026, 7, 19)
    assert row["concept_trigger_allowed"] is True
    assert row["stock_d1_sample_count"] == 6
    assert row["stock_gene_combined_win_rate"] == 42.5
    assert row["profitability_gate_passed"] is True
    assert row["recognition_gate_passed"] is True
    assert row["core_quality_gate_passed"] is True
    assert row["core_quality_gate_reason"] == "qualified"
    assert row["quality_priority_tier"] == "A_industry_expanding"
    assert row["public_quality_status"] == "rejected"
    assert row["public_quality_actionable"] is False
    assert row["quality_win_probability"] == 35 / 41
    assert row["quality_expected_d1_net_return_pct"] == 3.0876
    assert row["concept_near_limit_count"] == 3
    assert row["concept_touched_count"] == 2
    assert row["concept_sealed_count"] == 1
    assert row["concept_failed_count"] == 1
    assert row["sector_main_net_inflow"] == 88_000_000.0
    assert row["sector_main_net_inflow_ratio"] == 2.8
    assert row["sector_flow_trade_date"] == date(2026, 7, 20)
    assert row["stock_main_net_inflow"] == 12_000_000.0
    assert row["stock_main_net_inflow_ratio"] == 1.2
    assert row["stock_flow_trade_date"] == date(2026, 7, 20)


def test_projection_recomputes_missing_core_quality_from_signal_time_fields() -> None:
    row = repo.project_observation(
        {
            **_candidate("600001.SSE"),
            "prior_limit_count_126": 3,
            "prior_industry_turnover_ratio_5d": 0.8,
            "signal_time": "10:30:00",
            "buy_time": "10:30:00",
            "signal_kind": "first_touch",
        },
        formal_signal={
            "historical_evidence": {
                "d1_money_effect_sample_count": 7,
                "historical_win_rate": 36.0,
            }
        },
    )

    assert row["stock_d1_sample_count"] == 7
    assert row["stock_gene_combined_win_rate"] == 36.0
    assert row["profitability_gate_passed"] is True
    assert row["recognition_gate_passed"] is True
    assert row["core_quality_gate_passed"] is True
    assert row["core_quality_gate_reason"] == "qualified"
    assert row["quality_priority_tier"] == "B_recognition_only"
    assert row["public_quality_status"] == "rejected"
    assert row["quality_win_probability"] == 0.6
    assert row["quality_expected_d1_net_return_pct"] == 1.2895


def test_projection_prefers_the_candidate_quote_source_time() -> None:
    candidate_time = datetime.fromisoformat("2026-07-20T10:05:08+08:00")
    fallback_time = datetime.fromisoformat("2026-07-20T10:04:45+08:00")

    row = repo.project_observation(
        {
            **_candidate("600001.SSE"),
            "quote_observed_at": candidate_time.isoformat(),
        },
        formal_signal=None,
        quote_observed_at=fallback_time,
    )

    assert row["quote_observed_at"] == candidate_time


def test_projection_fails_closed_for_invalid_flow_source_dates() -> None:
    candidate = {
        **_candidate("600001.SSE"),
        "sector_flow_trade_date": "2026-02-30",
        "stock_flow_trade_date": "not-a-date",
    }

    row = repo.project_observation(
        candidate,
        formal_signal=None,
    )

    assert row["sector_flow_trade_date"] is None
    assert row["stock_flow_trade_date"] is None


def test_two_hundred_projected_candidates_stay_below_size_guard() -> None:
    rows = [
        repo.project_observation(
            _candidate(f"{600000 + index:06d}.SSE"),
            formal_signal=None,
        )
        for index in range(200)
    ]

    encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()
    assert len(encoded) < 500_000


def test_fill_followup_keeps_a_signaled_stock_after_it_falls_below_three_percent() -> None:
    signal = repo.project_observation(
        _candidate("600001.SSE"),
        formal_signal={"action": "buy_now", "entry_kind": "sweep"},
    )
    signal["captured_at"] = "2026-07-20T10:05:00+08:00"
    quote = {
        "vt_symbol": "600001.SSE",
        "name": "测试股份",
        "last_price": 10.25,
        "change_pct": 2.5,
        "volume": 123_000.0,
        "turnover": 456_000_000.0,
        "turnover_rate": 7.8,
        "volume_ratio": 2.1,
    }

    rows = repo.build_fill_followup_observations(
        [signal],
        [quote],
        quote_observed_at=datetime.fromisoformat(
            "2026-07-20T10:05:25+08:00"
        ),
        current_observation_symbols=set(),
    )

    assert len(rows) == 1
    assert rows[0]["vt_symbol"] == "600001.SSE"
    assert rows[0]["last_price"] == 10.25
    assert rows[0]["change_pct"] == 2.5
    assert rows[0]["quote_observed_at"] == datetime.fromisoformat(
        "2026-07-20T10:05:25+08:00"
    )
    assert rows[0]["volume"] == 123_000.0
    assert rows[0]["turnover"] == 456_000_000.0
    assert rows[0]["turnover_rate"] == 7.8
    assert rows[0]["volume_ratio"] == 2.1
    assert rows[0]["capture_state"] == "fill_followup"
    assert rows[0]["formal_action"] == "pass"


def test_fill_followup_rejects_stale_late_and_cross_window_quotes() -> None:
    signal = repo.project_observation(
        _candidate("600001.SSE"),
        formal_signal={"action": "buy_now", "entry_kind": "sweep"},
    )
    quote = {
        "vt_symbol": "600001.SSE",
        "last_price": 10.25,
        "change_pct": 2.5,
    }

    for signal_at, quote_at in (
        ("2026-07-20T10:05:00+08:00", "2026-07-20T10:05:19+08:00"),
        ("2026-07-20T10:05:00+08:00", "2026-07-20T10:06:01+08:00"),
        ("2026-07-20T14:29:45+08:00", "2026-07-20T14:30:05+08:00"),
    ):
        signal["captured_at"] = signal_at
        rows = repo.build_fill_followup_observations(
            [signal],
            [quote],
            quote_observed_at=datetime.fromisoformat(quote_at),
            current_observation_symbols=set(),
        )
        assert rows == []


def test_recent_signal_context_keeps_the_earliest_buy_frame(monkeypatch) -> None:
    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "vt_symbol": "600001.SSE",
                    "captured_at": datetime.fromisoformat(
                        "2026-07-20T10:05:00+08:00"
                    ),
                },
                {
                    "vt_symbol": "600001.SSE",
                    "captured_at": datetime.fromisoformat(
                        "2026-07-20T10:05:15+08:00"
                    ),
                },
            ]

    class Session:
        def execute(self, _statement):
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(repo, "session_scope", fake_session_scope)

    rows = repo.load_recent_signal_observations(
        datetime.fromisoformat("2026-07-20T10:05:30+08:00")
    )

    assert len(rows) == 1
    assert rows[0]["captured_at"].isoformat() == "2026-07-20T10:05:00+08:00"


def test_day_capture_runtime_fingerprint_state_uses_one_aggregate_query(
    monkeypatch,
) -> None:
    runtime_fingerprint = "sha256:" + "a" * 64
    statements: list[object] = []

    class Result:
        def one(self):
            return (5, 4, 1, runtime_fingerprint, runtime_fingerprint)

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(repo, "session_scope", fake_session_scope)

    state = repo.load_day_capture_runtime_fingerprint_state(date(2026, 7, 21))

    assert state == {
        "frame_count": 5,
        "missing_count": 1,
        "unique_count": 1,
        "capture_runtime_fingerprint": runtime_fingerprint,
    }
    assert len(statements) == 1
    query = statements[0].compile(dialect=postgresql.dialect())
    assert date(2026, 7, 21) in query.params.values()
    assert "count(distinct" in str(query).lower()


def test_frame_and_observations_use_one_transaction(monkeypatch) -> None:
    session = _InsertSession()

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(repo, "session_scope", fake_session_scope)
    monkeypatch.setattr(repo, "_prune_once_for_trade_date", lambda _date: None)
    runtime_fingerprint = "sha256:" + "a" * 64
    monkeypatch.setattr(
        repo,
        "capture_runtime_fingerprint_safely",
        lambda: runtime_fingerprint,
    )
    observation = repo.project_observation(
        _candidate("600001.SSE"),
        formal_signal=None,
    )

    result = repo.save_frame(
        {
            "trade_date": "2026-07-20",
            "captured_at": datetime(
                2026,
                7,
                20,
                10,
                5,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ),
            "strategy_version": "obsolete-version",
            "source": "test",
            "source_updated_at": "2026-07-20T10:05:00+08:00",
            "data_quality": {"status": "ready", "is_stale": False},
            "market_context": {"timing": {"signal_state": "GOLD_ACTIVE"}},
            "recommendations": {"portfolio": []},
        },
        [observation],
    )

    assert result["frame_id"] == 101
    assert result["capture_runtime_fingerprint"] == runtime_fingerprint
    assert result["market_timing_state"] == "GOLD_ACTIVE"
    assert result["formal_two_slot_observed"] is True
    assert result["formal_two_slot_symbols"] == []
    assert len(session.executions) == 2
    assert all(statement.is_insert for statement, _params in session.executions)
    assert session.executions[0][1] is None
    assert session.executions[1][1] == [{"frame_id": 101, **observation}]


class _ScalarResult:
    def scalar_one(self) -> int:
        return 101


class _InsertSession:
    def __init__(self) -> None:
        self.executions: list[tuple[object, object | None]] = []

    def execute(self, statement, params=None):
        self.executions.append((statement, params))
        return _ScalarResult()


def _candidate(symbol: str) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": "测试股份",
        "change_pct": 3.6,
        "last_price": 10.36,
        "previous_close": 10.0,
        "limit_price": 11.0,
        "state": "pre_radar",
        "board_lane": "first_board",
        "lane_support_score": 61.0,
        "lane_entry_quality_score": 65.0,
        "concept_id": "BK0877",
        "concept_state": "launch",
        "concept_strength_score": 82.0,
        "concept_leader_rank": 2,
        "concept_strong_5_count": 3,
        "sector_id": "industry:通信",
        "sector_heat": 68.0,
        "sector_touch_count": 4,
        "d1_money_effect_sample_count": 8,
        "historical_win_rate": 42.5,
        "lane_blockers": [],
        "financial_snapshot": {"large": "payload" * 1000},
        "raw": {"large": "payload" * 1000},
    }
