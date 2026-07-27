from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import live_trace_repository
from alphaagent.server.services.limit_up import live_trace_service
from alphaagent.server.services.limit_up.live_trace_service import (
    build_day_trace,
    build_symbol_trace,
    clear_live_trace_read_cache,
    get_live_trace_day,
    get_live_trace_symbol,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


class _InsertResult:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row

    def scalar_one(self) -> int:
        return int(self.row["id"])


class _InsertSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def execute(self, statement: object) -> _InsertResult:
        self.statements.append(statement)
        return _InsertResult({"id": len(self.statements)})


class _SelectResult:
    partition_size: int | None = None

    def mappings(self) -> _SelectResult:
        return self

    def partitions(self, size: int):
        type(self).partition_size = size
        return iter(())

    def all(self) -> list[dict[str, object]]:
        raise AssertionError("trace rows must be streamed in bounded partitions")


class _SelectSession:
    def __init__(self) -> None:
        self.statement: object | None = None

    def execute(self, statement: object) -> _SelectResult:
        self.statement = statement
        return _SelectResult()


def test_live_trace_table_is_registered() -> None:
    assert "limit_up_live_trace_snapshots" in schema.metadata.tables


def test_retention_cutoff_keeps_two_latest_trade_dates() -> None:
    trade_dates = [date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 14)]

    assert live_trace_repository.retention_cutoff(
        trade_dates,
        retain_trade_days=2,
    ) == date(2026, 7, 13)
    assert live_trace_repository.retention_cutoff(
        trade_dates[:1],
        retain_trade_days=2,
    ) is None


def test_live_trace_reader_selects_only_timeline_columns(monkeypatch) -> None:
    session = _SelectSession()

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(live_trace_repository, "session_scope", fake_session_scope)

    assert list(
        live_trace_repository.iter_live_trace_row_batches(date(2026, 7, 14))
    ) == []
    assert session.statement is not None
    assert tuple(session.statement.selected_columns.keys()) == (
        "id",
        "trade_date",
        "captured_at",
        "mode",
        "radar_candidates",
        "recommendations",
        "data_quality",
    )
    assert "strategy_version" in str(session.statement)
    assert "limit-up-core-abc-v1" in session.statement.compile().params.values()
    assert _SelectResult.partition_size == 32


def test_trace_projection_keeps_diagnostics_without_full_research_payload() -> None:
    rows = live_trace_repository._project_rows(
        [
            {
                "vt_symbol": "600001.SSE",
                "name": "测试股份",
                "board_lane": "first_board",
                "lane_blockers": ["first_touch_too_early"],
                "sector_heat": 62.5,
                "sector_touch_count": 3,
                "sector_main_net_inflow": 120_000_000.0,
                "stock_main_net_inflow": 30_000_000.0,
                "turnover_rate": 8.2,
                "portfolio_selected": True,
                "financial_snapshot": {"large": "payload"},
                "historical_evidence": {"trade_count": 500},
            }
        ],
        live_trace_repository.TRACE_CANDIDATE_FIELDS,
    )

    assert rows == [
        {
            "vt_symbol": "600001.SSE",
            "name": "测试股份",
            "board_lane": "first_board",
            "lane_blockers": ["first_touch_too_early"],
            "sector_heat": 62.5,
            "sector_touch_count": 3,
            "sector_main_net_inflow": 120_000_000.0,
            "stock_main_net_inflow": 30_000_000.0,
            "turnover_rate": 8.2,
            "portfolio_selected": True,
        }
    ]


def test_trace_recommendations_keep_one_best_signal_per_symbol() -> None:
    symbol = "600001.SSE"

    recommendations = live_trace_repository._trace_recommendations(
        {
            "market_gate": {"passed": True},
            "lanes": {
                "now": [
                    {
                        "vt_symbol": symbol,
                        "signal_state": "observing",
                        "action": "observe",
                    }
                ],
                "tail": [
                    {
                        "vt_symbol": symbol,
                        "signal_state": "trigger_ready",
                        "action": "buy_now",
                    }
                ],
                "next_auction": [
                    {
                        "vt_symbol": symbol,
                        "signal_state": "rejected",
                        "action": "pass",
                    }
                ],
            },
            "watchlist": [{"vt_symbol": symbol, "historical_evidence": {"large": True}}],
        }
    )

    assert recommendations == {
        "market_gate": {"passed": True},
        "lanes": {
            "now": [],
            "tail": [
                {
                    "vt_symbol": symbol,
                    "signal_state": "trigger_ready",
                    "action": "buy_now",
                }
            ],
            "next_auction": [],
        },
    }


def test_same_minute_live_trace_scans_use_independent_inserts(monkeypatch) -> None:
    session = _InsertSession()

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(live_trace_repository, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        live_trace_repository,
        "_prune_once_for_trade_date",
        lambda _trade_date: None,
    )

    for second in (5, 42):
        live_trace_repository.save_live_trace_snapshot(
            {
                "trade_date": "2026-07-14",
                "captured_at": datetime(2026, 7, 14, 10, 5, second, tzinfo=SHANGHAI),
                "session_stage": "morning",
                "strategy_version": "limit-up-live-test",
                "mode": "live_snapshot",
                "source": "test",
                "market_context": {},
                "trace_radar_candidates": [],
                "candidates": [],
                "recommendations": {},
                "data_quality": {"status": "ready", "is_stale": False},
            }
        )

    assert len(session.statements) == 2
    assert all(getattr(statement, "is_insert", False) for statement in session.statements)
    assert all(
        tuple(column.key for column in statement._returning) == ("id",)
        for statement in session.statements
    )


def test_trace_write_does_not_persist_duplicate_ranked_candidates(monkeypatch) -> None:
    session = _InsertSession()

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(live_trace_repository, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        live_trace_repository,
        "_prune_once_for_trade_date",
        lambda _trade_date: None,
    )
    candidate = _trace_candidate("600001.SSE", 8.2, "near_limit")

    live_trace_repository.save_live_trace_snapshot(
        {
            "trade_date": "2026-07-14",
            "captured_at": datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
            "session_stage": "morning",
            "strategy_version": "limit-up-live-test",
            "mode": "live_snapshot",
            "source": "test",
            "market_context": {},
            "trace_radar_candidates": [candidate],
            "candidates": [candidate],
            "recommendations": {},
            "data_quality": {"status": "ready", "is_stale": False},
        }
    )

    values = session.statements[0].compile().params
    assert values["radar_candidates"] == [candidate]
    assert values["ranked_candidates"] == []


def _trace_candidate(
    symbol: str,
    change_pct: float,
    state: str,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": "测试股份",
        "board_level": 1,
        "board_lane": "first_board",
        "state": state,
        "change_pct": change_pct,
        "last_price": round(10 * (1 + change_pct / 100), 2),
        "distance_to_limit_pct": max(round(10 - change_pct, 2), 0),
        "lane_blockers": [],
        "sector_heat": 62.5,
        "sector_touch_count": 3,
        "sector_main_net_inflow": 120_000_000.0,
        "stock_main_net_inflow": 30_000_000.0,
        "turnover_rate": 8.2,
        "portfolio_selected": True,
    }


def _trace_signal(
    symbol: str,
    signal_state: str,
    *,
    reason: str = "等待触发",
) -> dict[str, object]:
    action = "buy_now" if signal_state == "trigger_ready" else "observe"
    return {
        **_trace_candidate(symbol, 9.3, "near_limit"),
        "market_dragon_rank": 1,
        "signal_state": signal_state,
        "action": action,
        "research_action": action,
        "reason": reason,
        "blocking_scope": "dynamic" if signal_state == "approaching_trigger" else "none",
        "pending_reasons": (
            ["等待板块扩散"] if signal_state == "approaching_trigger" else []
        ),
        "trigger_checks": [
            {
                "code": "sector_expansion",
                "label": "板块扩散",
                "status": "pending" if signal_state == "approaching_trigger" else "passed",
                "observed": "2只" if signal_state == "approaching_trigger" else "3只",
                "required": ">=3只",
            }
        ],
    }


def _trace_row(
    clock: str,
    *,
    radar: list[dict[str, object]],
    signals: list[dict[str, object]],
    mode: str = "live_trace",
) -> dict[str, object]:
    captured_at = datetime.fromisoformat(f"2026-07-14T{clock}+08:00")
    return {
        "trade_date": date(2026, 7, 14),
        "captured_at": captured_at,
        "mode": mode,
        "radar_candidates": radar,
        "ranked_candidates": radar,
        "market_context": {},
        "recommendations": {
            "market_gate": {
                "passed": True,
                "repair_state": "repair_confirmed",
                "repair_confirmed_at": "2026-07-14T09:59:22+08:00",
                "reasons": [],
            },
            "lanes": {"now": signals, "tail": [], "next_auction": []},
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }


def test_symbol_trace_preserves_fast_first_board_state_changes() -> None:
    symbol = "600001.SSE"
    rows = [
        _trace_row(
            "10:05:05",
            radar=[_trace_candidate(symbol, 5.2, "near_limit")],
            signals=[],
        ),
        _trace_row(
            "10:05:20",
            radar=[_trace_candidate(symbol, 9.3, "near_limit")],
            signals=[_trace_signal(symbol, "approaching_trigger")],
        ),
        _trace_row(
            "10:05:42",
            radar=[_trace_candidate(symbol, 10.0, "sealed")],
            signals=[],
        ),
    ]

    events = build_symbol_trace(rows, symbol)

    assert [event["event"] for event in events] == [
        "radar_entered",
        "recommended",
        "approaching_trigger",
        "dropped_from_top5",
        "sealed",
    ]
    assert not any(event["event"] == "trigger_ready" for event in events)
    approaching = next(event for event in events if event["event"] == "approaching_trigger")
    assert approaching["blocking_scope"] == "dynamic"
    assert approaching["pending_reasons"] == ["等待板块扩散"]
    assert approaching["trigger_checks"][0]["code"] == "sector_expansion"
    assert approaching["market_repair_state"] == "repair_confirmed"
    assert approaching["market_repair_confirmed_at"] == "2026-07-14T09:59:22+08:00"
    assert approaching["sector_heat"] == 62.5
    assert approaching["sector_touch_count"] == 3


def test_research_buy_cancelled_by_formal_gate_is_not_counted_as_trigger() -> None:
    symbol = "600001.SSE"
    rejected = {
        **_trace_signal(symbol, "trigger_ready", reason="只观察，不执行：质量门未通过"),
        "action": "pass",
        "research_action": "buy_now",
    }
    rows = [
        _trace_row(
            "10:05:20",
            radar=[_trace_candidate(symbol, 9.3, "near_limit")],
            signals=[rejected],
        )
    ]

    events = build_symbol_trace(rows, symbol)
    day = build_day_trace(rows)

    assert [event["event"] for event in events] == [
        "radar_entered",
        "recommended",
        "rejected",
    ]
    assert not any(event["event"] == "trigger_ready" for event in events)
    assert day["items"][0]["ever_triggered"] is False
    assert day["lane_funnels"]["first_board"]["triggered_count"] == 0


def test_trace_records_concept_warming_before_top5_entry() -> None:
    symbol = "600001.SSE"

    def state_row(
        clock: str,
        signal_state: str,
        market_rank: int,
    ) -> dict[str, object]:
        candidate = {
            **_trace_candidate(symbol, 7.5, "near_limit"),
            "market_dragon_rank": market_rank,
            "concept_id": "BK0877",
            "concept_name": "PCB",
            "concept_state": "warming" if signal_state == "concept_warming" else "launch",
            "concept_strength_rank": 1,
            "concept_leader_rank": 2,
        }
        signal = {
            **_trace_signal(symbol, signal_state),
            **candidate,
            "signal_state": signal_state,
            "market_dragon_rank": market_rank,
        }
        return _trace_row(clock, radar=[candidate], signals=[signal])

    events = build_symbol_trace(
        [
            state_row("13:02:30", "concept_warming", 12),
            state_row("13:04:00", "approaching_trigger", 7),
            state_row("13:04:20", "trigger_ready", 3),
        ],
        symbol,
    )

    assert [event["event"] for event in events] == [
        "radar_entered",
        "concept_warming",
        "approaching_trigger",
        "recommended",
        "trigger_ready",
    ]
    assert events[1]["concept_name"] == "PCB"
    assert events[1]["concept_leader_rank"] == 2


def test_in_top5_uses_market_rank_not_signal_presence() -> None:
    symbol = "600001.SSE"
    candidate = {
        **_trace_candidate(symbol, 7.5, "near_limit"),
        "market_dragon_rank": 12,
    }
    signal = {
        **_trace_signal(symbol, "concept_warming"),
        "market_dragon_rank": 12,
    }

    state = live_trace_service._row_symbol_states(
        _trace_row("13:03:00", radar=[candidate], signals=[signal]),
        {},
    )[symbol]

    assert state["in_top5"] is False


def test_symbol_trace_preserves_trigger_time_after_invalidation() -> None:
    symbol = "600001.SSE"
    rows = [
        _trace_row(
            "10:05:20",
            radar=[_trace_candidate(symbol, 9.5, "near_limit")],
            signals=[_trace_signal(symbol, "trigger_ready", reason="扫板条件通过")],
        ),
        _trace_row(
            "10:05:42",
            radar=[_trace_candidate(symbol, 8.8, "near_limit")],
            signals=[_trace_signal(symbol, "invalidated", reason="板块扩散转弱")],
        ),
    ]

    events = build_symbol_trace(rows, symbol)

    assert [event["event"] for event in events][-1] == "invalidated"
    assert events[-1]["triggered_at"] == "2026-07-14T10:05:20+08:00"
    assert events[-1]["reason"] == "板块扩散转弱"


def test_symbol_trace_records_structural_rejection() -> None:
    symbol = "600001.SSE"
    rejected = _trace_signal(symbol, "rejected", reason="半年内缺少涨停基因")
    rejected["blocking_scope"] = "structural"
    rejected["lane_blocker_reasons"] = ["limit_up_gene_missing"]

    events = build_symbol_trace(
        [_trace_row("10:05:20", radar=[_trace_candidate(symbol, 8.2, "near_limit")], signals=[rejected])],
        symbol,
    )

    assert [event["event"] for event in events] == [
        "radar_entered",
        "recommended",
        "rejected",
    ]
    assert events[-1]["blocking_scope"] == "structural"
    assert events[-1]["blockers"] == ["limit_up_gene_missing"]


def test_symbol_trace_emits_source_missing_only_once() -> None:
    symbol = "600001.SSE"
    rows = [
        _trace_row(
            "10:05:05",
            radar=[_trace_candidate(symbol, 5.2, "near_limit")],
            signals=[],
        ),
        _trace_row("10:05:20", radar=[], signals=[]),
        _trace_row("10:05:42", radar=[], signals=[]),
        _trace_row("10:05:55", radar=[], signals=[], mode="scan_error"),
    ]

    events = build_symbol_trace(rows, symbol)

    assert [event["event"] for event in events].count("source_missing") == 1


def test_scan_error_does_not_mark_visible_symbol_as_source_missing() -> None:
    symbol = "600001.SSE"
    rows = [
        _trace_row(
            "10:05:05",
            radar=[_trace_candidate(symbol, 5.2, "near_limit")],
            signals=[],
        ),
        _trace_row("10:05:20", radar=[], signals=[], mode="scan_error"),
    ]

    events = build_symbol_trace(rows, symbol)

    assert [event["event"] for event in events] == ["radar_entered"]


def test_source_missing_does_not_replace_reached_radar_state() -> None:
    symbol = "600001.SSE"
    rows = [
        _trace_row(
            "10:05:05",
            radar=[_trace_candidate(symbol, 5.2, "near_limit")],
            signals=[],
        ),
        _trace_row("10:05:20", radar=[], signals=[]),
    ]

    result = build_day_trace(rows)

    assert result["items"][0]["highest_state"] == "radar_entered"
    assert result["items"][0]["final_state"] == "source_missing"


def test_day_trace_summarizes_trigger_and_final_state() -> None:
    symbol = "600001.SSE"
    rows = [
        _trace_row(
            "10:05:05",
            radar=[_trace_candidate(symbol, 5.2, "near_limit")],
            signals=[],
        ),
        _trace_row(
            "10:05:20",
            radar=[_trace_candidate(symbol, 9.5, "near_limit")],
            signals=[_trace_signal(symbol, "trigger_ready")],
        ),
        _trace_row(
            "10:05:42",
            radar=[_trace_candidate(symbol, 8.8, "failed")],
            signals=[_trace_signal(symbol, "invalidated", reason="炸板失效")],
        ),
    ]

    result = build_day_trace(rows)

    assert result["trade_date"] == "2026-07-14"
    assert result["snapshot_count"] == 3
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["vt_symbol"] == symbol
    assert item["first_seen_at"] == "2026-07-14T10:05:05+08:00"
    assert item["last_seen_at"] == "2026-07-14T10:05:42+08:00"
    assert item["highest_state"] == "trigger_ready"
    assert item["final_state"] == "failed"
    assert item["ever_recommended"] is True
    assert item["ever_triggered"] is True


def test_day_trace_builds_first_board_zero_buy_funnel_by_symbol() -> None:
    triggered = "600001.SSE"
    missed = "600002.SSE"
    rejected = "600003.SSE"
    rejected_signal = _trace_signal(rejected, "rejected", reason="缺少点时财报")
    rejected_signal["blocking_scope"] = "structural"
    rejected_signal["lane_blocker_reasons"] = ["缺少点时财报"]
    rows = [
        _trace_row(
            "13:20:00",
            radar=[
                _trace_candidate(triggered, 9.5, "near_limit"),
                _trace_candidate(missed, 9.3, "near_limit"),
                _trace_candidate(rejected, 9.1, "near_limit"),
            ],
            signals=[
                _trace_signal(triggered, "trigger_ready"),
                _trace_signal(missed, "approaching_trigger"),
                rejected_signal,
            ],
        ),
        _trace_row(
            "13:20:20",
            radar=[
                _trace_candidate(triggered, 9.7, "near_limit"),
                _trace_candidate(missed, 10.0, "sealed"),
                _trace_candidate(rejected, 9.0, "near_limit"),
            ],
            signals=[_trace_signal(triggered, "trigger_ready")],
        ),
    ]

    result = build_day_trace(rows)
    funnel = result["lane_funnels"]["first_board"]

    assert funnel["radar_count"] == 3
    assert funnel["recommended_count"] == 3
    assert funnel["approaching_count"] == 1
    assert funnel["triggered_count"] == 1
    assert funnel["sealed_without_trigger_count"] == 0
    assert funnel["structural_rejected_count"] == 1
    assert funnel["primary_blockers"] == [
        {"code": "sector_expansion", "label": "板块扩散", "count": 1}
    ]


def test_read_cache_aggregates_only_new_scan_rows(monkeypatch) -> None:
    trade_date = date(2026, 7, 14)
    symbol = "600001.SSE"
    first = _trace_row(
        "10:05:05",
        radar=[_trace_candidate(symbol, 5.2, "near_limit")],
        signals=[],
    )
    first["id"] = 1
    second = _trace_row(
        "10:05:20",
        radar=[_trace_candidate(symbol, 9.3, "near_limit")],
        signals=[_trace_signal(symbol, "approaching_trigger")],
    )
    second["id"] = 2
    calls: list[int | None] = []

    def load_row_batches(_trade_date: date, *, after_id: int | None = None):
        calls.append(after_id)
        if after_id is None:
            return iter([[first]])
        if after_id == 1:
            return iter([[second]])
        return iter(())

    clear_live_trace_read_cache()
    monkeypatch.setattr(
        live_trace_repository,
        "iter_live_trace_row_batches",
        load_row_batches,
    )

    first_result = get_live_trace_day(trade_date)
    second_result = get_live_trace_day(trade_date)
    symbol_result = get_live_trace_symbol(trade_date, symbol)

    assert calls == [None, 1, 2]
    assert first_result["snapshot_count"] == 1
    assert second_result["snapshot_count"] == 2
    assert [event["event"] for event in symbol_result["events"]] == [
        "radar_entered",
        "recommended",
        "approaching_trigger",
    ]
    clear_live_trace_read_cache()
