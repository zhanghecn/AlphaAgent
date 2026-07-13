from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.live_policy import (
    build_live_recommendations,
    rank_live_candidates,
    session_stage,
)
from alphaagent.server.services.limit_up.entry_backtest import build_limit_up_entry_backtest
from alphaagent.server.services.limit_up import entry_backtest as entry_backtest_service
from alphaagent.server.services.limit_up import history_engine
from alphaagent.server.services.limit_up.live_service import build_live_snapshot
from alphaagent.server.services.limit_up import live_service
from alphaagent.server.services.limit_up import live_repository
from alphaagent.server.services.limit_up.live_evidence import attach_historical_evidence
from alphaagent.server.services.limit_up import signal_service
from alphaagent.server.services.limit_up.signal_service import build_historical_signal_proxy


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _candidate(symbol: str, **overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "vt_symbol": symbol,
        "name": symbol,
        "sector_id": "theme-a",
        "sector_name": "机器人",
        "board_level": 1,
        "state": "near_limit",
        "change_pct": 9.2,
        "distance_to_limit_pct": 0.7,
        "open_times": 0,
        "sector_touch_count": 3,
        "sector_heat": 70.0,
        "sector_main_net_inflow": 2_000_000_000.0,
        "stock_main_net_inflow": 120_000_000.0,
        "turnover_rate": 8.0,
        "seal_amount": None,
        "turnover": 500_000_000.0,
        "limit_price": 11.0,
        "last_price": 10.92,
        "previous_limit_up": False,
        "auction_gap_pct": None,
    }
    candidate.update(overrides)
    return candidate


def _market(**overrides: object) -> dict[str, object]:
    market: dict[str, object] = {
        "sealed_count": 35,
        "failed_count": 10,
        "failed_rate": 0.2222,
        "sealed_change": 4,
        "failed_change": -2,
        "timing": {"signal_state": "STALE"},
        "sentiment": {"phase": "repair", "phase_label": "修复"},
    }
    market.update(overrides)
    return market


def test_session_stage_uses_a_share_trading_windows() -> None:
    assert session_stage(datetime(2026, 7, 10, 9, 14, tzinfo=SHANGHAI)) == "preopen"
    assert session_stage(datetime(2026, 7, 10, 9, 18, tzinfo=SHANGHAI)) == "auction_watch"
    assert session_stage(datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI)) == "auction"
    assert session_stage(datetime(2026, 7, 10, 10, 30, tzinfo=SHANGHAI)) == "morning"
    assert session_stage(datetime(2026, 7, 10, 12, 0, tzinfo=SHANGHAI)) == "lunch"
    assert session_stage(datetime(2026, 7, 10, 14, 35, tzinfo=SHANGHAI)) == "tail"
    assert session_stage(datetime(2026, 7, 10, 15, 5, tzinfo=SHANGHAI)) == "closed"
    assert session_stage(datetime(2026, 7, 11, 10, 30, tzinfo=SHANGHAI)) == "closed"


def test_live_price_context_contains_shifted_limit_gene_and_position() -> None:
    rows = [
        {
            "trade_date": (date(2025, 1, 1) + timedelta(days=index)).isoformat(),
            "close_price": 10.0,
            "high_price": 10.2,
            "low_price": 9.5,
            "change_pct": 0.0,
            "turnover": 100_000_000.0,
        }
        for index in range(130)
    ]
    rows[5].update(close_price=11.0, high_price=11.0, change_pct=10.0)
    rows[100].update(close_price=12.0, high_price=12.0, change_pct=10.0)
    for row in rows[101:]:
        row.update(close_price=10.2, high_price=10.4, low_price=9.8)

    context = live_repository._prior_price_context(rows)

    assert context["prior_limit_count_126"] == 2
    assert context["prior_limit_count_5"] == 0
    assert context["trade_days_since_prior_limit"] == 30
    assert round(float(context["pullback_from_prior_limit_pct"]), 2) == -15.0
    assert 0 <= float(context["prior_position_120"]) < 0.5


def test_weekend_snapshot_uses_source_trade_date_and_blocks_actions() -> None:
    captured_at = datetime(2026, 7, 11, 10, 30, tzinfo=SHANGHAI)
    pools = {
        "trade_date": "20260710",
        "pools": {
            "zt": {
                "items": [
                    {
                        "vt_symbol": "600001.SSE",
                        "name": "周五涨停",
                        "close_price": 11.0,
                        "limit_up_price": 11.0,
                        "change_pct": 10.0,
                        "turnover_rate": 8.0,
                        "raw": {"炸板次数": 1, "成交额": 500_000_000.0},
                    }
                ]
            }
        },
    }
    context = {
        "by_symbol": {
            "600001.SSE": {
                "sector_id": "BK1",
                "sector_name": "机器人",
                "sector_heat": 75.0,
                "sector_main_net_inflow": 2_000_000_000.0,
                "stock_main_net_inflow": 100_000_000.0,
            }
        },
        "sentiment": {"phase": "repair"},
    }

    snapshot = build_live_snapshot({"items": []}, pools, captured_at, context)

    assert snapshot["trade_date"] == "2026-07-10"
    assert snapshot["mode"] == "stale_snapshot"
    assert snapshot["data_quality"]["is_stale"] is True
    assert snapshot["recommendations"]["market_gate"]["passed"] is False
    assert all(
        signal["action"] == "pass"
        for lane in snapshot["recommendations"]["lanes"].values()
        for signal in lane
    )


def test_saved_weekend_snapshot_is_normalized_to_latest_market_date() -> None:
    snapshot = {
        "trade_date": "2026-07-11",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "recommendations": {
            "market_gate": {"passed": True, "reasons": []},
            "lanes": {
                "now": [{"action": "buy_now", "entry_kind": "sweep", "reason": "旧动作"}],
                "tail": [],
                "next_auction": [],
            },
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }

    normalized = live_service._snapshot_for_session(
        snapshot,
        datetime(2026, 7, 11, 10, 30, tzinfo=SHANGHAI),
        date(2026, 7, 10),
    )

    assert normalized["trade_date"] == "2026-07-10"
    assert normalized["mode"] == "stale_snapshot"
    assert normalized["recommendations"]["lanes"]["now"][0]["action"] == "pass"
    assert normalized["data_quality"]["is_stale"] is True


def test_refresh_outside_active_session_does_not_fetch_or_persist(monkeypatch) -> None:
    fetched: list[bool] = []
    persisted: list[dict[str, object]] = []
    saved_snapshot = {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T14:55:00+08:00",
        "session_stage": "tail",
        "mode": "live_snapshot",
        "recommendations": {
            "market_gate": {"passed": True, "reasons": []},
            "lanes": {"now": [], "tail": [], "next_auction": []},
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(live_service, "load_latest_snapshot", lambda **_kwargs: saved_snapshot)
    monkeypatch.setattr(
        live_service,
        "load_latest_daily_trade_date",
        lambda _date: date(2026, 7, 10),
    )
    monkeypatch.setattr(
        live_service,
        "_fetch_live_payloads",
        lambda *_args: fetched.append(True) or ({}, {}, []),
    )
    monkeypatch.setattr(
        live_service,
        "save_snapshot",
        lambda snapshot: persisted.append(snapshot) or snapshot,
    )

    result = live_service.refresh_live_snapshot(
        datetime(2026, 7, 11, 10, 30, tzinfo=SHANGHAI),
        adapter=object(),
    )

    assert fetched == []
    assert persisted == []
    assert result["trade_date"] == "2026-07-10"
    assert result["mode"] == "stale_snapshot"
    assert result["data_quality"]["is_stale"] is True


def test_refresh_does_not_persist_previous_market_date_during_session(monkeypatch) -> None:
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(
        live_service,
        "_fetch_live_payloads",
        lambda *_args: (
            {"items": []},
            {"trade_date": "20260710", "pools": {}},
            [],
        ),
    )
    monkeypatch.setattr(live_service, "load_latest_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        live_service,
        "save_snapshot",
        lambda snapshot: persisted.append(snapshot) or snapshot,
    )

    result = live_service.refresh_live_snapshot(
        datetime(2026, 7, 13, 10, 5, tzinfo=SHANGHAI),
        adapter=object(),
    )

    assert result["trade_date"] == "2026-07-10"
    assert result["mode"] == "stale_snapshot"
    assert persisted == []


def test_refresh_persists_verified_current_session_snapshot(monkeypatch) -> None:
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(
        live_service,
        "_fetch_live_payloads",
        lambda *_args: (
            {"items": []},
            {"trade_date": "20260710", "pools": {}},
            [],
        ),
    )
    monkeypatch.setattr(live_service, "load_latest_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        live_service,
        "save_snapshot",
        lambda snapshot: persisted.append(snapshot) or snapshot,
    )

    result = live_service.refresh_live_snapshot(
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
        adapter=object(),
    )

    assert result["trade_date"] == "2026-07-10"
    assert result["mode"] == "live_snapshot"
    assert result["data_quality"]["is_stale"] is False
    assert persisted == [result]


def test_live_read_reuses_fresh_current_snapshot(monkeypatch) -> None:
    now = datetime(2026, 7, 10, 10, 5, 30, tzinfo=SHANGHAI)
    snapshot = {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T10:05:25+08:00",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "recommendations": {"lanes": {"now": [], "tail": [], "next_auction": []}},
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(live_service, "load_latest_snapshot", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(
        live_service,
        "load_latest_daily_trade_date",
        lambda _date: date(2026, 7, 9),
    )

    def unexpected_refresh(*_args, **_kwargs):
        raise AssertionError("fresh snapshot must not refresh")

    monkeypatch.setattr(live_service, "refresh_live_snapshot", unexpected_refresh)

    result = live_service.get_latest_live_snapshot(now)

    assert result["captured_at"] == snapshot["captured_at"]
    assert result["data_quality"]["snapshot_age_seconds"] == 5


def test_live_read_returns_old_saved_snapshot_without_external_refresh(monkeypatch) -> None:
    now = datetime(2026, 7, 10, 10, 5, 30, tzinfo=SHANGHAI)
    old_snapshot = {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T10:04:00+08:00",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "recommendations": {"lanes": {"now": [], "tail": [], "next_auction": []}},
        "data_quality": {"status": "ready", "is_stale": False},
    }
    refresh_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        live_service,
        "load_latest_snapshot",
        lambda *_args, **_kwargs: old_snapshot,
    )
    monkeypatch.setattr(
        live_service,
        "load_latest_daily_trade_date",
        lambda _date: date(2026, 7, 9),
    )

    def refresh(captured_at, **kwargs):
        refresh_calls.append({"captured_at": captured_at, **kwargs})
        raise AssertionError("GET must not call external quote refresh")

    monkeypatch.setattr(live_service, "refresh_live_snapshot", refresh)

    first = live_service.get_latest_live_snapshot(now)
    second = live_service.get_latest_live_snapshot(now)

    assert refresh_calls == []
    assert first["captured_at"] == old_snapshot["captured_at"]
    assert second["captured_at"] == old_snapshot["captured_at"]
    assert first["data_quality"]["snapshot_age_seconds"] == 90


def test_live_read_fails_closed_when_background_snapshot_is_overdue(
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 10, 10, 5, 31, tzinfo=SHANGHAI)
    snapshot = {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T10:04:00+08:00",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "recommendations": {
            "market_gate": {"passed": True, "reasons": []},
            "lanes": {
                "now": [{"action": "buy_now", "entry_kind": "sweep"}],
                "tail": [],
                "next_auction": [],
            },
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(
        live_service,
        "load_latest_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )

    result = live_service.get_latest_live_snapshot(now)

    assert result["mode"] == "stale_snapshot"
    assert result["data_quality"]["is_stale"] is True
    assert result["data_quality"]["snapshot_age_seconds"] == 91
    assert result["recommendations"]["market_gate"]["passed"] is False
    signal = result["recommendations"]["lanes"]["now"][0]
    assert signal["action"] == "pass"
    assert signal["execution_state"] == "cancelled"
    assert "等待后台扫描更新" in signal["reason"]


def test_signal_dates_exclude_snapshots_outside_daily_bar_calendar(monkeypatch) -> None:
    monkeypatch.setattr(
        signal_service,
        "get_limit_up_trade_dates",
        lambda: {"dates": ["2026-07-09", "2026-07-10"]},
    )
    monkeypatch.setattr(
        signal_service,
        "list_snapshot_dates",
        lambda: ["2026-07-10", "2026-07-11"],
    )
    monkeypatch.setattr(
        signal_service,
        "list_daily_trade_dates",
        lambda: ["2026-07-09", "2026-07-10"],
    )

    result = signal_service.get_limit_up_signal_dates()

    assert result["dates"] == ["2026-07-09", "2026-07-10"]
    assert result["latest"] == "2026-07-10"
    assert result["count"] == 2


def test_signal_dates_keep_verified_current_live_snapshot_before_daily_bar(monkeypatch) -> None:
    snapshot = {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T10:30:00+08:00",
        "mode": "live_snapshot",
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(
        signal_service,
        "get_limit_up_trade_dates",
        lambda: {"dates": ["2026-07-09"]},
    )
    monkeypatch.setattr(signal_service, "list_snapshot_dates", lambda: ["2026-07-10"])
    monkeypatch.setattr(signal_service, "list_daily_trade_dates", lambda: ["2026-07-09"])
    monkeypatch.setattr(signal_service, "load_latest_snapshot", lambda *_args: snapshot)

    result = signal_service.get_limit_up_signal_dates(
        datetime(2026, 7, 10, 10, 30, tzinfo=SHANGHAI)
    )

    assert result["dates"] == ["2026-07-09", "2026-07-10"]
    assert result["latest"] == "2026-07-10"


def test_signal_lookup_downgrades_snapshot_from_invalid_trade_date(monkeypatch) -> None:
    snapshot = {
        "trade_date": "2026-07-11",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "recommendations": {
            "market_gate": {"passed": True, "reasons": []},
            "lanes": {
                "now": [{"action": "buy_now", "entry_kind": "sweep", "reason": "旧动作"}],
                "tail": [],
                "next_auction": [],
            },
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(signal_service, "load_snapshot_as_of", lambda *_args: snapshot)
    monkeypatch.setattr(
        signal_service,
        "load_latest_daily_trade_date",
        lambda _target_date: date(2026, 7, 10),
    )

    result = signal_service.get_limit_up_signals(date(2026, 7, 11))

    assert result["trade_date"] == "2026-07-10"
    assert result["mode"] == "stale_snapshot"
    assert result["session_stage"] == "closed"
    assert result["recommendations"]["market_gate"]["passed"] is False
    assert result["recommendations"]["lanes"]["now"][0]["action"] == "pass"
    assert result["data_quality"]["is_stale"] is True


def test_signal_lookup_preserves_snapshot_from_valid_historical_date(monkeypatch) -> None:
    snapshot = {
        "trade_date": "2026-07-10",
        "mode": "live_snapshot",
        "recommendations": {
            "lanes": {"now": [{"action": "buy_now", "entry_kind": "sweep"}]},
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(signal_service, "load_snapshot_as_of", lambda *_args: snapshot)
    monkeypatch.setattr(
        signal_service,
        "load_latest_daily_trade_date",
        lambda _target_date: date(2026, 7, 10),
    )

    result = signal_service.get_limit_up_signals(date(2026, 7, 10))

    assert result == snapshot


def test_signal_lookup_attaches_mature_evidence_to_historical_proxy(monkeypatch) -> None:
    dashboard = {
        "top_dragons": [{"vt_symbol": "600001.SSE"}],
        "research_plan": {"plans": [{"vt_symbol": "600001.SSE"}]},
    }

    def add_evidence(snapshot):
        result = dict(snapshot)
        recommendations = dict(result["recommendations"])
        lanes = {
            lane: [
                {
                    **signal,
                    "historical_evidence": {
                        "status": "ready",
                        "effective_sample_count": 60,
                        "smoothed_win_rate": 38.0,
                        "average_return_pct": -1.2,
                        "hard_loss_rate": 23.0,
                        "risk_vetoed": True,
                    },
                }
                for signal in signals
            ]
            for lane, signals in recommendations["lanes"].items()
        }
        recommendations["lanes"] = lanes
        result["recommendations"] = recommendations
        return result

    monkeypatch.setattr(signal_service, "load_snapshot_as_of", lambda *_args: None)
    monkeypatch.setattr(
        signal_service,
        "load_latest_daily_trade_date",
        lambda _target_date: date(2026, 7, 10),
    )
    monkeypatch.setattr(signal_service, "get_limit_up_dashboard", lambda *_args: dashboard)
    monkeypatch.setattr(signal_service, "attach_historical_evidence", add_evidence)

    result = signal_service.get_limit_up_signals(date(2026, 7, 10))

    assert result["mode"] == "historical_proxy"
    for signals in result["recommendations"]["lanes"].values():
        evidence = signals[0]["historical_evidence"]
        assert evidence["effective_sample_count"] == 60
        assert evidence["average_return_pct"] == -1.2


def test_signal_lookup_keeps_historical_proxy_when_evidence_loading_fails(monkeypatch) -> None:
    dashboard = {
        "top_dragons": [{"vt_symbol": "600001.SSE"}],
        "research_plan": {"plans": [{"vt_symbol": "600001.SSE"}]},
    }
    monkeypatch.setattr(signal_service, "load_snapshot_as_of", lambda *_args: None)
    monkeypatch.setattr(
        signal_service,
        "load_latest_daily_trade_date",
        lambda _target_date: date(2026, 7, 10),
    )
    monkeypatch.setattr(signal_service, "get_limit_up_dashboard", lambda *_args: dashboard)

    def fail_evidence(_snapshot):
        raise RuntimeError("history store unavailable")

    monkeypatch.setattr(signal_service, "attach_historical_evidence", fail_evidence)

    result = signal_service.get_limit_up_signals(date(2026, 7, 10))

    assert result["mode"] == "historical_proxy"
    assert result["recommendations"]["lanes"]["now"][0]["vt_symbol"] == "600001.SSE"
    assert result["data_quality"]["source_errors"] == ["history_evidence:RuntimeError"]
    assert "历史相似样本暂不可用" in result["data_quality"]["limitations"][-1]


def test_signal_lookup_preserves_verified_current_snapshot_during_trading(monkeypatch) -> None:
    snapshot = {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T10:30:00+08:00",
        "mode": "live_snapshot",
        "recommendations": {
            "lanes": {"now": [{"action": "buy_now", "entry_kind": "sweep"}]},
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(signal_service, "load_snapshot_as_of", lambda *_args: snapshot)
    monkeypatch.setattr(
        signal_service,
        "load_latest_daily_trade_date",
        lambda _target_date: date(2026, 7, 9),
    )

    result = signal_service.get_limit_up_signals(
        date(2026, 7, 10),
        now=datetime(2026, 7, 10, 10, 30, tzinfo=SHANGHAI),
    )

    assert result == snapshot


def test_signal_lookup_blocks_current_snapshot_outside_trading_session(monkeypatch) -> None:
    snapshot = {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T10:30:00+08:00",
        "mode": "live_snapshot",
        "recommendations": {
            "market_gate": {"passed": True, "reasons": []},
            "lanes": {"now": [{"action": "buy_now", "entry_kind": "sweep"}]},
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(signal_service, "load_snapshot_as_of", lambda *_args: snapshot)
    monkeypatch.setattr(
        signal_service,
        "load_latest_daily_trade_date",
        lambda _target_date: date(2026, 7, 9),
    )

    result = signal_service.get_limit_up_signals(
        date(2026, 7, 10),
        now=datetime(2026, 7, 10, 12, 0, tzinfo=SHANGHAI),
    )

    assert result["trade_date"] == "2026-07-10"
    assert result["mode"] == "stale_snapshot"
    assert result["recommendations"]["lanes"]["now"][0]["action"] == "pass"
    assert result["recommendations"]["market_gate"]["passed"] is False


def test_live_top5_is_recomputed_and_later_stronger_candidate_replaces_weak_one() -> None:
    candidates = [
        _candidate("600001.SSE", change_pct=8.6, sector_heat=45, sector_touch_count=1),
        _candidate("600002.SSE", change_pct=9.0, sector_id="theme-b"),
        _candidate("600003.SSE", change_pct=9.1, sector_id="theme-c"),
        _candidate("600004.SSE", change_pct=9.2, sector_id="theme-d"),
        _candidate("600005.SSE", change_pct=9.3, sector_id="theme-e"),
        _candidate(
            "600006.SSE",
            change_pct=9.95,
            sector_id="theme-f",
            state="resealed",
            open_times=6,
            sector_heat=82,
            sector_touch_count=6,
        ),
    ]

    ranked = rank_live_candidates(candidates)

    assert [row["market_dragon_rank"] for row in ranked] == [1, 2, 3, 4, 5]
    assert ranked[0]["vt_symbol"] == "600006.SSE"
    assert "600001.SSE" not in {row["vt_symbol"] for row in ranked}


def test_live_ranking_keeps_only_sector_top_two() -> None:
    candidates = [
        _candidate("600001.SSE", state="resealed", open_times=5, change_pct=9.9),
        _candidate("600002.SSE", state="resealed", open_times=4, change_pct=9.8),
        _candidate("600003.SSE", state="resealed", open_times=3, change_pct=9.7),
        _candidate("600004.SSE", sector_id="theme-b", change_pct=9.6),
    ]

    ranked = rank_live_candidates(candidates)

    assert {row["vt_symbol"] for row in ranked} == {
        "600001.SSE",
        "600002.SSE",
        "600004.SSE",
    }
    assert max(
        int(row["sector_dragon_rank"])
        for row in ranked
        if row["sector_id"] == "theme-a"
    ) == 2


def test_morning_recommendation_buys_only_sufficiently_resealed_leader() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    candidates = rank_live_candidates(
        [
            _candidate("600001.SSE", state="resealed", open_times=5, change_pct=9.98),
            _candidate("600002.SSE", state="sealed", open_times=0, change_pct=10.0),
        ]
    )

    result = build_live_recommendations(candidates, _market(), captured_at)

    now_by_symbol = {row["vt_symbol"]: row for row in result["lanes"]["now"]}
    assert now_by_symbol["600001.SSE"]["action"] == "buy_now"
    assert now_by_symbol["600001.SSE"]["entry_kind"] == "reseal"
    assert now_by_symbol["600002.SSE"]["action"] == "wait_tail"
    assert result["market_gate"]["passed"] is True
    assert result["market_gate"]["timing_used"] is False


def test_live_signal_exposes_execution_state_and_operation_rules() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [_candidate("600001.SSE", state="resealed", open_times=5, change_pct=9.98)]
    )[0]

    result = build_live_recommendations([candidate], _market(), captured_at)

    actionable = result["lanes"]["now"][0]
    waiting = result["lanes"]["tail"][0]
    assert actionable["execution_state"] == "actionable"
    assert "涨停" in actionable["buy_condition"]
    assert "D+1" in actionable["sell_condition"]
    assert actionable["state_updated_at"] == "2026-07-10T10:05:00+08:00"
    assert waiting["execution_state"] == "waiting"
    assert waiting["buy_condition"]
    assert waiting["cancel_condition"]


def test_live_signals_include_only_matured_point_in_time_analogs() -> None:
    candidate = _candidate(
        "600001.SSE",
        state="resealed",
        open_times=5,
        change_pct=9.98,
        prior_change_pct=2.0,
        prior_turnover_rate=8.0,
        prior_amount_ratio_5d=1.2,
    )
    snapshot = build_live_snapshot(
        {"items": []},
        {"trade_date": "20260710", "pools": {"zt": {"items": []}}},
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
        {"by_symbol": {}},
    )
    snapshot["candidates"] = [candidate]
    snapshot["market_context"] = _market()
    snapshot["recommendations"] = build_live_recommendations(
        rank_live_candidates([candidate]),
        _market(),
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
    )
    matured = _history_analog_candidate("2026-07-09", 2.5, entry_mode="sweep")
    same_day = _history_analog_candidate("2026-07-10", -9.0, entry_mode="sweep")
    analog_index = history_engine.build_analog_index(
        [{"lanes": {"sweep": [matured, same_day]}}],
        result_before=date(2026, 7, 10),
    )

    result = attach_historical_evidence(snapshot, analog_index=analog_index)

    evidence = result["recommendations"]["lanes"]["now"][0]["historical_evidence"]
    assert evidence["entry_mode"] == "sweep"
    assert evidence["effective_sample_count"] == 1
    assert evidence["smoothed_win_rate"] == 100.0
    assert evidence["average_return_pct"] == 2.5
    next_evidence = result["recommendations"]["lanes"]["next_auction"][0][
        "historical_evidence"
    ]
    assert next_evidence["feature_scope"] == "next_auction_gap_pending"


def test_tail_recommendation_requires_consecutive_stable_snapshots() -> None:
    captured_at = datetime(2026, 7, 10, 14, 35, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                state="resealed",
                open_times=3,
                change_pct=10.0,
                stable_minutes=4,
            )
        ]
    )[0]
    previous_snapshot = {
        "captured_at": "2026-07-10T14:31:00+08:00",
        "candidates": [
            {
                "vt_symbol": "600001.SSE",
                "state": "resealed",
                "seal_amount": 80_000_000.0,
            }
        ],
    }

    result = build_live_recommendations(
        [candidate],
        _market(),
        captured_at,
        previous_snapshot=previous_snapshot,
    )

    tail = result["lanes"]["tail"][0]
    assert tail["action"] == "buy_now"
    assert tail["entry_kind"] == "tail_seal"
    assert tail["stable_minutes"] == 4


def test_live_snapshot_tracks_seal_amount_change_from_previous_snapshot() -> None:
    candidates = [
        _candidate(
            "600001.SSE",
            state="resealed",
            seal_amount=60_000_000.0,
        )
    ]
    previous_snapshot = {
        "captured_at": "2026-07-10T10:04:00+08:00",
        "candidates": [
            {
                "vt_symbol": "600001.SSE",
                "state": "resealed",
                "stable_minutes": 2,
                "seal_amount": 100_000_000.0,
            }
        ],
    }

    live_service._attach_stability(
        candidates,
        previous_snapshot,
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
    )

    candidate = candidates[0]
    assert candidate["stable_minutes"] == 3
    assert candidate["seal_amount_retention_ratio"] == 0.6
    assert candidate["seal_amount_change_pct"] == -40.0


def test_live_snapshot_resets_stability_after_collection_gap() -> None:
    candidates = [
        _candidate(
            "600001.SSE",
            state="resealed",
            seal_amount=60_000_000.0,
        )
    ]
    previous_snapshot = {
        "captured_at": "2026-07-10T10:00:00+08:00",
        "candidates": [
            {
                "vt_symbol": "600001.SSE",
                "state": "resealed",
                "stable_minutes": 8,
                "seal_amount": 100_000_000.0,
            }
        ],
    }

    live_service._attach_stability(
        candidates,
        previous_snapshot,
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
    )

    candidate = candidates[0]
    assert candidate["stable_minutes"] == 0
    assert candidate["seal_amount_retention_ratio"] is None
    assert candidate["seal_amount_change_pct"] is None


def test_live_buy_is_blocked_when_seal_amount_shrinks_sharply() -> None:
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                state="resealed",
                open_times=6,
                seal_amount=60_000_000.0,
                seal_amount_retention_ratio=0.6,
                seal_amount_change_pct=-40.0,
            )
        ]
    )[0]

    result = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
    )

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "pass"
    assert signal["seal_amount_change_pct"] == -40.0
    assert "封单较上一快照缩水40.0%" in signal["reason"]


def test_auction_recommendation_uses_previous_board_and_gap_range() -> None:
    captured_at = datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                previous_limit_up=True,
                auction_gap_pct=4.5,
                state="near_limit",
            )
        ]
    )[0]

    result = build_live_recommendations([candidate], _market(), captured_at)

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "buy_now"
    assert signal["entry_kind"] == "auction"
    assert signal["trigger_price"] == candidate["last_price"]


def test_auction_watch_can_approach_but_not_trigger_before_0920() -> None:
    captured_at = datetime(2026, 7, 10, 9, 18, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                previous_limit_up=True,
                auction_gap_pct=3.0,
                state="near_limit",
            )
        ]
    )[0]

    result = build_live_recommendations([candidate], _market(), captured_at)

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "observe"
    assert signal["signal_state"] == "approaching_trigger"
    assert signal["execution_permission"] == "research_only"
    assert signal["entry_kind"] == "auction"


def test_auction_trigger_has_structured_strategy_and_rules() -> None:
    captured_at = datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                previous_limit_up=True,
                auction_gap_pct=3.0,
                state="near_limit",
                board_level=3,
                board_lane="two_to_three",
                lane_decision="eligible",
                lane_favorable_factors=[
                    "prior_board_changed_hands_and_resealed",
                    "third_board_weak_to_strong",
                ],
                setup_tags=["weak_to_strong_breakout"],
            )
        ]
    )[0]

    result = build_live_recommendations([candidate], _market(), captured_at)

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "buy_now"
    assert signal["signal_state"] == "trigger_ready"
    assert signal["execution_permission"] == "research_only"
    assert signal["strategy_name"] == "二进三·弱转强突破"
    assert signal["selection_reasons"] == ["前板换手回封", "三板弱转强"]
    assert [check["code"] for check in signal["trigger_checks"]] == [
        "market_gate",
        "lane_gate",
        "auction_gap",
    ]
    assert signal["trigger_checks"][2]["status"] == "passed"
    assert signal["buy_instruction"]
    assert signal["sell_instruction"]
    assert signal["cancel_checks"]


def test_auction_can_consider_first_board_when_live_gates_pass() -> None:
    captured_at = datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                previous_limit_up=False,
                auction_gap_pct=3.2,
                state="near_limit",
            )
        ]
    )[0]

    result = build_live_recommendations([candidate], _market(), captured_at)

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "buy_now"
    assert signal["entry_kind"] == "auction"
    assert "首板" in signal["reason"]


def test_live_high_board_auction_requires_prior_divergence_reseal() -> None:
    captured_at = datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI)
    eligible = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                board_level=4,
                previous_limit_up=True,
                auction_gap_pct=3.2,
                prior_streak=3,
                prior_limit_count_5=3,
                prior_limit_count_126=8,
                prior_industry_leader_rank=1,
                prior_board={"is_sealed": True, "open_times": 2},
                lane_decision="eligible",
                board_lane="high_board",
                lane_setup_type="high_board_weak_to_strong",
            )
        ]
    )[0]
    missing_divergence = {
        **eligible,
        "lane_decision": "blocked",
        "lane_blockers": ["high_board_prior_divergence_missing"],
    }

    accepted = build_live_recommendations([eligible], _market(), captured_at)
    rejected = build_live_recommendations([missing_divergence], _market(), captured_at)

    assert accepted["lanes"]["now"][0]["action"] == "buy_now"
    assert "弱转强" in accepted["lanes"]["now"][0]["reason"]
    assert rejected["lanes"]["now"][0]["action"] == "pass"
    assert "前日分歧回封" in rejected["lanes"]["now"][0]["reason"]


def test_auction_snapshot_keeps_previous_board_with_three_percent_gap() -> None:
    captured_at = datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI)
    quotes = {
        "trade_date": "20260710",
        "items": [
            {
                "vt_symbol": "600001.SSE",
                "name": "高板核心",
                "change_pct": 3.0,
                "open_price": 11.33,
                "last_price": 11.33,
                "turnover_rate": 8.0,
            }
        ],
    }
    pools = {
        "trade_date": "20260710",
        "pools": {
            "zt_previous": {"items": [{"vt_symbol": "600001.SSE"}]},
        },
    }
    context = {
        "by_symbol": {
            "600001.SSE": {
                "previous_close": 11.0,
                "previous_limit_up": True,
                "prior_streak": 3,
                "prior_limit_count_5": 3,
                "prior_limit_count_126": 8,
                "prior_touch_count_126": 10,
                "prior_seal_success_rate_126": 0.8,
                "prior_turnover_rate": 8.0,
                "prior_amount_ratio_5d": 1.4,
                "prior_position_120": 0.9,
                "trade_days_since_prior_limit": 1,
                "pullback_from_prior_limit_pct": 0.0,
                "prior_board": {
                    "is_sealed": True,
                    "first_limit_time": "09:46:00",
                    "last_limit_time": "14:08:00",
                    "open_times": 2,
                },
                "financial_risk": {"blocked": False, "level": "clear"},
                "lane_feature_ready": True,
                "sector_id": "BK1001",
                "sector_name": "机器人",
                "sector_heat": 80.0,
                "sector_main_net_inflow": 2_000_000_000.0,
                "stock_main_net_inflow": 100_000_000.0,
            }
        },
        "sentiment": {"phase": "repair"},
    }

    snapshot = build_live_snapshot(quotes, pools, captured_at, context)

    assert [row["vt_symbol"] for row in snapshot["candidates"]] == ["600001.SSE"]
    candidate = snapshot["candidates"][0]
    assert candidate["board_lane"] == "high_board"
    assert candidate["lane_decision"] == "eligible"
    assert snapshot["recommendations"]["lanes"]["now"][0]["action"] == "buy_now"


def test_live_snapshot_fails_closed_when_lane_features_are_unavailable() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                state="near_limit",
                lane_feature_ready=False,
            )
        ]
    )[0]

    live_service._attach_lane_decisions([candidate], _market(), captured_at)
    result = build_live_recommendations([candidate], _market(), captured_at)

    assert candidate["lane_decision"] == "blocked"
    assert candidate["lane_blockers"] == ["lane_features_unavailable"]
    assert result["lanes"]["now"][0]["action"] == "pass"
    assert "前置证据未就绪" in result["lanes"]["now"][0]["reason"]


def test_live_two_to_three_exposes_auction_quality_and_risk() -> None:
    candidate = _candidate(
        "600001.SSE",
        board_level=3,
        lane_feature_ready=True,
        auction_gap_pct=3.2,
        prior_streak=2,
        prior_limit_count_5=2,
        prior_turnover_rate=14.0,
        prior_amount_ratio_5d=1.6,
        prior_low_change_pct=0.5,
        sector_dragon_rank=1,
        financial_snapshot={"net_profit_yoy": 18.0},
        prior_board={
            "is_sealed": True,
            "first_limit_time": "10:08:00",
            "last_limit_time": "14:20:00",
            "open_times": 4,
        },
    )

    live_service._attach_lane_decisions(
        [candidate],
        _market(sentiment={"phase": "repair", "failed_limit_up_rate": 0.30}),
        datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI),
    )
    recommendations = build_live_recommendations(
        [candidate],
        _market(sentiment={"phase": "repair", "failed_limit_up_rate": 0.30}),
        datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI),
    )

    assert candidate["lane_decision"] == "eligible"
    assert candidate["lane_quality_tier"] == "A"
    assert candidate["lane_risk_count"] == 0
    assert candidate["lane_risk_flags"] == []
    signal = recommendations["lanes"]["now"][0]
    assert signal["lane_quality_tier"] == "A"
    assert signal["lane_risk_count"] == 0
    assert signal["lane_risk_flags"] == []


def test_live_two_to_three_blocks_visible_risk_stack() -> None:
    candidate = _candidate(
        "600001.SSE",
        board_level=3,
        lane_feature_ready=True,
        auction_gap_pct=5.5,
        prior_streak=2,
        prior_limit_count_5=2,
        prior_turnover_rate=8.0,
        prior_amount_ratio_5d=1.0,
        prior_low_change_pct=-1.0,
        sector_dragon_rank=1,
        financial_snapshot=None,
        prior_board={
            "is_sealed": True,
            "first_limit_time": "10:08:00",
            "last_limit_time": "14:20:00",
            "open_times": 4,
        },
    )

    live_service._attach_lane_decisions(
        [candidate],
        _market(sentiment={"phase": "repair", "failed_limit_up_rate": 0.40}),
        datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI),
    )
    recommendations = build_live_recommendations(
        [candidate],
        _market(sentiment={"phase": "repair", "failed_limit_up_rate": 0.40}),
        datetime(2026, 7, 10, 9, 25, tzinfo=SHANGHAI),
    )

    assert candidate["lane_decision"] == "blocked"
    assert candidate["lane_quality_tier"] == "B"
    assert candidate["lane_risk_count"] == 6
    assert "two_to_three_risk_stack" in candidate["lane_blockers"]
    assert recommendations["lanes"]["now"][0]["action"] == "pass"
    assert "二进三可见风险达到4项" in recommendations["lanes"]["now"][0]["reason"]


def test_live_first_board_uses_visible_quote_range_as_lower_confidence_support() -> None:
    captured_at = datetime(2026, 7, 10, 10, 12, tzinfo=SHANGHAI)
    quotes = {
        "trade_date": "20260710",
        "items": [
            {
                "vt_symbol": "600001.SSE",
                "name": "盘中承接",
                "change_pct": 9.2,
                "last_price": 10.92,
                "open_price": 10.4,
                "high_price": 10.98,
                "low_price": 10.35,
                "previous_close": 10.0,
                "turnover_rate": 8.0,
                "volume_ratio": 1.1,
            }
        ],
    }
    pools = {"trade_date": "20260710", "pools": {}}
    context = {
        "by_symbol": {
            "600001.SSE": {
                "previous_close": 10.0,
                "prior_streak": 0,
                "prior_limit_count_5": 0,
                "prior_limit_count_126": 3,
                "prior_touch_count_126": 8,
                "prior_seal_success_rate_126": 0.75,
                "prior_position_120": 0.28,
                "trade_days_since_prior_limit": 18,
                "pullback_from_prior_limit_pct": -12.0,
                "financial_risk": {"blocked": False, "level": "clear"},
                "financial_snapshot": {
                    "publish_date": "2026-06-30",
                    "period_type": "quarterly",
                    "net_profit_yoy": 18.0,
                },
                "lane_feature_ready": True,
                "sector_id": "BK1001",
                "sector_name": "机器人",
                "sector_heat": 72.0,
                "sector_main_net_inflow": 2_000_000_000.0,
                "stock_main_net_inflow": 100_000_000.0,
            }
        },
        "sentiment": {"phase": "repair", "failed_limit_up_rate": 0.40},
    }

    snapshot = build_live_snapshot(quotes, pools, captured_at, context)

    candidate = snapshot["candidates"][0]
    assert candidate["session_low_change_pct"] == 3.5
    assert candidate["lane_decision"] == "eligible"
    assert candidate["financial_snapshot"]["net_profit_yoy"] == 18.0
    assert candidate["lane_premium_gate_passed"] is True
    assert "intraday_support_confirmed" in candidate["lane_favorable_factors"]
    assert float(candidate["lane_support_score"]) > 35
    assert snapshot["recommendations"]["lanes"]["now"][0]["session_low_change_pct"] == 3.5


def test_live_first_board_does_not_reject_an_early_low_by_itself() -> None:
    candidate = {
        **_candidate("600001.SSE", lane_feature_ready=True),
        "prior_streak": 0,
        "prior_limit_count_5": 0,
        "prior_limit_count_126": 3,
        "prior_touch_count_126": 8,
        "prior_seal_success_rate_126": 0.75,
        "prior_position_120": 0.28,
        "trade_days_since_prior_limit": 18,
        "pullback_from_prior_limit_pct": -12.0,
        "financial_snapshot": {
            "publish_date": "2026-06-30",
            "period_type": "quarterly",
            "net_profit_yoy": 18.0,
        },
        "session_low_change_pct": 1.0,
    }

    live_service._attach_lane_decisions(
        [candidate],
        _market(sentiment={"phase": "repair", "failed_limit_up_rate": 0.40}),
        datetime(2026, 7, 10, 10, 12, tzinfo=SHANGHAI),
    )

    assert candidate["lane_decision"] == "eligible"
    assert "intraday_support_out_of_range" not in candidate["lane_blockers"]
    assert float(candidate["lane_support_score"]) >= 35


def test_market_gate_allows_prior_ebb_only_after_live_repair_confirmation() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [_candidate("600001.SSE", state="resealed", open_times=8, change_pct=9.98)]
    )[0]
    repaired = _market(
        sentiment={"phase": "ebb", "failed_limit_up_rate": 0.48},
        failed_rate=0.30,
        sealed_change=3,
        failed_change=-2,
    )
    unrepaired = {
        **repaired,
        "sealed_change": 0,
        "failed_change": 1,
    }

    accepted = build_live_recommendations([candidate], repaired, captured_at)
    rejected = build_live_recommendations([candidate], unrepaired, captured_at)

    assert accepted["market_gate"]["repair_confirmed"] is True
    assert accepted["market_gate"]["passed"] is True
    assert rejected["market_gate"]["repair_confirmed"] is False
    assert rejected["market_gate"]["passed"] is False
    assert "尚未确认修复" in rejected["market_gate"]["reasons"][0]


def test_next_auction_plan_is_classified_by_tomorrows_target_board() -> None:
    candidate = rank_live_candidates(
        [_candidate("600001.SSE", board_level=1, state="resealed", open_times=2)]
    )[0]

    result = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 10, 14, 35, tzinfo=SHANGHAI),
    )

    signal = result["lanes"]["next_auction"][0]
    assert signal["board_level"] == 2
    assert signal["board_lane"] == "one_to_two"


def test_lane_validation_veto_downgrades_live_buy_to_observation() -> None:
    recommendations = {
        "lanes": {
            "now": [
                {
                    "vt_symbol": "600001.SSE",
                    "board_level": 4,
                    "board_lane": "high_board",
                    "action": "buy_now",
                    "entry_kind": "auction",
                    "reason": "前日分歧回封，竞价弱转强",
                }
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    result = live_service.apply_lane_validation_veto(
        recommendations,
        {
            "high_board": {
                "passed": False,
                "status": "research_only",
                "reason": "锁定留出只有6笔",
            }
        },
    )

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "pass"
    assert signal["research_action"] == "buy_now"
    assert signal["validation_status"] == "research_only"
    assert "只观察" in signal["reason"]


def test_historical_veto_runs_before_lane_validation_and_blocks_research_action(
    monkeypatch,
) -> None:
    snapshot = {
        "trade_date": "2026-07-10",
        "candidates": [{"vt_symbol": "600001.SSE"}],
        "recommendations": {
            "lanes": {
                "now": [
                    {
                        "vt_symbol": "600001.SSE",
                        "board_level": 4,
                        "board_lane": "high_board",
                        "action": "buy_now",
                        "entry_kind": "sweep",
                        "reason": "规则买点成立",
                    }
                ],
                "tail": [],
                "next_auction": [],
            }
        },
        "data_quality": {"source_errors": [], "limitations": []},
    }

    def veto_with_history(raw_snapshot):
        result = dict(raw_snapshot)
        recommendations = dict(result["recommendations"])
        lanes = dict(recommendations["lanes"])
        signal = dict(lanes["now"][0])
        signal.update(
            action="pass",
            reason="历史证据否决：同路径平均净收益为负",
            historical_evidence={"risk_vetoed": True},
        )
        lanes["now"] = [signal]
        recommendations["lanes"] = lanes
        result["recommendations"] = recommendations
        return result

    monkeypatch.setattr(live_service, "_with_historical_evidence", veto_with_history)

    result = live_service._apply_live_risk_gates(
        snapshot,
        {
            "high_board": {
                "passed": False,
                "status": "research_only",
                "reason": "规则冻结后前向样本不足",
            }
        },
    )

    signal = result["recommendations"]["lanes"]["now"][0]
    assert signal["action"] == "pass"
    assert signal["research_action"] == "pass"
    assert signal["historical_evidence"]["risk_vetoed"] is True
    assert signal["reason"].startswith("历史证据否决")


def test_negative_matured_history_vetoes_rule_buy() -> None:
    candidate = _candidate(
        "600001.SSE",
        state="resealed",
        open_times=5,
        prior_change_pct=2.0,
        prior_turnover_rate=8.0,
        prior_amount_ratio_5d=1.2,
    )
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    snapshot = {
        "trade_date": "2026-07-10",
        "market_context": _market(),
        "candidates": [candidate],
        "recommendations": build_live_recommendations(
            rank_live_candidates([candidate]),
            _market(),
            captured_at,
        ),
    }
    negative_samples = [
        _history_analog_candidate("2026-07-09", -1.2, entry_mode="sweep")
        for _ in range(60)
    ]
    analog_index = history_engine.build_analog_index(
        [{"lanes": {"sweep": negative_samples}}],
        result_before=date(2026, 7, 10),
    )

    result = attach_historical_evidence(snapshot, analog_index=analog_index)

    signal = result["recommendations"]["lanes"]["now"][0]
    assert signal["action"] == "pass"
    assert signal["historical_evidence"]["risk_vetoed"] is True
    assert "历史证据否决" in signal["reason"]


def test_history_evidence_failure_blocks_trade_actions_but_keeps_observation(monkeypatch) -> None:
    signal = {
        "vt_symbol": "600001.SSE",
        "name": "证据故障候选",
        "board_level": 1,
        "action": "buy_now",
        "entry_kind": "reseal",
        "reason": "规则买入",
    }
    snapshot = {
        "trade_date": "2026-07-10",
        "recommendations": {
            "lanes": {
                "now": [signal, {**signal, "vt_symbol": "600002.SSE", "action": "wait_tail"}],
                "tail": [{**signal, "entry_kind": "tail_seal"}],
                "next_auction": [
                    {**signal, "action": "next_auction", "entry_kind": "next_auction"}
                ],
            }
        },
        "data_quality": {"source_errors": [], "limitations": []},
    }

    def fail_evidence(_snapshot):
        raise RuntimeError("history evidence unavailable")

    monkeypatch.setattr(live_service, "attach_historical_evidence", fail_evidence)

    result = live_service._with_historical_evidence(snapshot)

    lanes = result["recommendations"]["lanes"]
    assert lanes["now"][0]["action"] == "pass"
    assert lanes["now"][1]["action"] == "wait_tail"
    assert lanes["tail"][0]["action"] == "pass"
    assert lanes["next_auction"][0]["action"] == "pass"
    assert lanes["now"][0]["historical_evidence"]["status"] == "unavailable"
    assert "历史证据不可用" in lanes["now"][0]["reason"]
    assert result["data_quality"]["source_errors"] == ["history_evidence:RuntimeError"]
    assert "已禁止执行" in result["data_quality"]["limitations"][-1]


def test_market_gate_blocks_buy_when_failed_rate_is_too_high() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [_candidate("600001.SSE", state="resealed", open_times=8, change_pct=9.98)]
    )[0]

    result = build_live_recommendations(
        [candidate],
        _market(failed_count=30, sealed_count=30, failed_rate=0.5),
        captured_at,
    )

    assert result["lanes"]["now"][0]["action"] == "pass"
    assert result["market_gate"]["passed"] is False


def test_live_buy_is_blocked_when_sector_fund_flow_is_negative() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                state="resealed",
                open_times=6,
                sector_main_net_inflow=-500_000_000.0,
            )
        ]
    )[0]

    result = build_live_recommendations([candidate], _market(), captured_at)

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "pass"
    assert "板块主力净流出" in signal["reason"]


def test_live_snapshot_merges_quotes_and_pools_without_non_main_board() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    quotes = {
        "items": [
            {
                "vt_symbol": "600001.SSE",
                "name": "主板近板",
                "open_price": 10.3,
                "last_price": 10.92,
                "previous_close": 10.0,
                "change_pct": 9.2,
                "turnover": 420_000_000.0,
                "turnover_rate": 8.2,
            },
            {
                "vt_symbol": "300001.SZSE",
                "name": "创业板样本",
                "last_price": 13.0,
                "previous_close": 11.0,
                "change_pct": 18.2,
            },
        ],
        "source": "quote-test",
        "updated_at": "2026-07-10T10:05:01+08:00",
    }
    pools = {
        "trade_date": "20260710",
        "source": "pool-test",
        "updated_at": "2026-07-10T10:05:02+08:00",
        "pools": {
            "zt": {
                "items": [
                    {
                        "vt_symbol": "600002.SSE",
                        "name": "换手回封",
                        "close_price": 11.0,
                        "limit_up_price": 11.0,
                        "change_pct": 10.0,
                        "first_limit_time": "094500",
                        "last_limit_time": "100300",
                        "limit_up_count": 2,
                        "limit_amount": 88_000_000.0,
                        "turnover_rate": 12.0,
                        "raw": {"炸板次数": 5, "成交额": 650_000_000.0, "流通市值": 5_000_000_000.0},
                    }
                ]
            },
            "zbgc": {
                "items": [
                    {
                        "vt_symbol": "600003.SSE",
                        "name": "盘中炸板",
                        "close_price": 10.55,
                        "limit_up_price": 11.0,
                        "change_pct": 5.5,
                        "first_limit_time": "093800",
                        "turnover_rate": 18.0,
                        "raw": {"炸板次数": 2, "成交额": 720_000_000.0},
                    }
                ]
            },
            "zt_previous": {"items": [{"vt_symbol": "600001.SSE"}]},
        },
    }
    context = {
        "by_symbol": {
            "600001.SSE": {
                "sector_id": "BK1001",
                "sector_name": "机器人",
                "sector_heat": 72.0,
                "sector_main_net_inflow": 2_500_000_000.0,
            },
            "600002.SSE": {
                "sector_id": "BK1002",
                "sector_name": "算力",
                "sector_heat": 81.0,
                "sector_main_net_inflow": 3_600_000_000.0,
                "stock_main_net_inflow": 180_000_000.0,
            },
            "600003.SSE": {
                "sector_id": "BK1002",
                "sector_name": "算力",
                "sector_heat": 81.0,
                "sector_main_net_inflow": 3_600_000_000.0,
            },
        },
        "timing": {"signal_state": "STALE"},
        "sentiment": {"phase": "repair", "phase_label": "修复"},
    }

    snapshot = build_live_snapshot(quotes, pools, captured_at, context)

    by_symbol = {row["vt_symbol"]: row for row in snapshot["candidates"]}
    assert set(by_symbol) == {"600001.SSE", "600002.SSE", "600003.SSE"}
    assert by_symbol["600001.SSE"]["state"] == "near_limit"
    assert by_symbol["600001.SSE"]["auction_gap_pct"] == 3.0
    assert by_symbol["600001.SSE"]["previous_limit_up"] is True
    assert by_symbol["600002.SSE"]["state"] == "resealed"
    assert by_symbol["600002.SSE"]["open_times"] == 5
    assert by_symbol["600002.SSE"]["seal_to_turnover_ratio"] > 0
    assert by_symbol["600003.SSE"]["state"] == "failed"
    assert snapshot["market_context"]["sealed_count"] == 1
    assert snapshot["market_context"]["failed_count"] == 1
    assert snapshot["source_updated_at"] == "2026-07-10T10:05:02+08:00"
    assert snapshot["data_quality"]["execution_confidence"] == "proxy_without_l2"


def _history_analog_candidate(
    result_date: str,
    return_pct: float,
    *,
    entry_mode: str,
) -> dict[str, object]:
    return {
        "entry_mode": entry_mode,
        "target_board": 1,
        "result_date": result_date,
        "known_at_signal": {
            "auction_gap_pct": 4.0,
            "prior_change_pct": 2.0,
            "prior_turnover_rate": 8.0,
            "prior_amount_ratio_5d": 1.2,
            "prior_market_phase": "repair",
        },
        "outcome": {
            "touched": True,
            "sealed": return_pct > 0,
            "next_open_return_pct": return_pct,
        },
    }


def test_live_snapshot_recomputes_sector_touch_count_before_top5_ranking() -> None:
    captured_at = datetime(2026, 7, 10, 10, 15, tzinfo=SHANGHAI)
    pool_items = [
        {
            "vt_symbol": f"60000{index}.SSE",
            "name": f"板块股{index}",
            "close_price": 11.0,
            "limit_up_price": 11.0,
            "change_pct": 10.0,
            "limit_up_count": 1,
            "raw": {"炸板次数": 0, "成交额": 300_000_000.0},
        }
        for index in range(1, 4)
    ]
    pools = {
        "trade_date": "20260710",
        "source": "pool-test",
        "updated_at": "2026-07-10T10:15:00+08:00",
        "pools": {"zt": {"items": pool_items}},
    }
    context = {
        "by_symbol": {
            item["vt_symbol"]: {
                "sector_id": "BK2001",
                "sector_name": "商业航天",
                "sector_heat": 78.0,
            }
            for item in pool_items
        }
    }

    snapshot = build_live_snapshot({"items": []}, pools, captured_at, context)

    assert len(snapshot["candidates"]) == 2
    assert {row["sector_dragon_rank"] for row in snapshot["candidates"]} == {1, 2}
    assert all(row["sector_touch_count"] == 3 for row in snapshot["candidates"])


def test_live_snapshot_accumulates_continuous_tail_seal_minutes() -> None:
    context = {
        "by_symbol": {
            "600001.SSE": {
                "sector_id": "BK1",
                "sector_name": "机器人",
                "sector_heat": 75.0,
                "sector_main_net_inflow": 2_000_000_000.0,
                "stock_main_net_inflow": 100_000_000.0,
            }
        },
        "sentiment": {"phase": "repair"},
    }
    pools = {
        "trade_date": "20260710",
        "source": "pool-test",
        "pools": {
            "zt": {
                "items": [
                    {
                        "vt_symbol": "600001.SSE",
                        "name": "连续封板",
                        "close_price": 11.0,
                        "limit_up_price": 11.0,
                        "change_pct": 10.0,
                        "turnover_rate": 8.0,
                        "raw": {"炸板次数": 1, "成交额": 500_000_000.0},
                    }
                ]
            }
        },
    }
    first = build_live_snapshot(
        {"items": []},
        pools,
        datetime(2026, 7, 10, 14, 31, tzinfo=SHANGHAI),
        context,
    )
    second = build_live_snapshot(
        {"items": []},
        pools,
        datetime(2026, 7, 10, 14, 32, tzinfo=SHANGHAI),
        context,
        previous_snapshot=first,
    )
    third = build_live_snapshot(
        {"items": []},
        pools,
        datetime(2026, 7, 10, 14, 33, tzinfo=SHANGHAI),
        context,
        previous_snapshot=second,
    )

    assert first["candidates"][0]["stable_minutes"] == 0
    assert second["candidates"][0]["stable_minutes"] == 1
    assert third["candidates"][0]["stable_minutes"] == 2


def test_historical_proxy_never_claims_an_unrecorded_intraday_fill() -> None:
    dashboard = {
        "status": "ready",
        "as_of_time": "2026-07-10T15:00:00+08:00",
        "summary": {"sealed_count": 30, "failed_count": 10},
        "pretrade_market": {
            "sentiment": {"phase": "repair", "phase_label": "修复"},
            "timing": {"signal_state": "STALE"},
        },
        "top_dragons": [
            {
                "vt_symbol": "600001.SSE",
                "name": "历史龙头",
                "sector_id": "BK1",
                "sector_name": "机器人",
                "market_dragon_rank": 1,
                "sector_dragon_rank": 1,
                "signal_board_level": 1,
                "decision": "eligible",
                "outcome": {"final_status": "sealed", "d1_analysis": {"outcome_code": "close_premium"}},
            }
        ],
        "research_plan": {
            "plans": [{"vt_symbol": "600001.SSE"}],
            "reason": "修复期低板前排",
        },
    }

    snapshot = build_historical_signal_proxy(dashboard, date(2026, 7, 10))

    assert snapshot["mode"] == "historical_proxy"
    assert snapshot["recommendations"]["lanes"]["now"][0]["action"] == "wait_tail"
    assert snapshot["recommendations"]["lanes"]["next_auction"][0]["action"] == "next_auction"
    assert not any(
        row["action"] == "buy_now"
        for rows in snapshot["recommendations"]["lanes"].values()
        for row in rows
    )
    assert snapshot["data_quality"]["execution_confidence"] == "historical_proxy_unverifiable"


def test_entry_backtest_aligns_sweep_with_d1_open_and_deducts_costs() -> None:
    snapshots = [_saved_signal_snapshot()]
    report = build_limit_up_entry_backtest(
        _entry_backtest_dataset(),
        snapshots,
        entry_mode="sweep",
        exit_mode="next_open",
    )

    trade = report["trades"][0]
    assert report["coverage"]["strict_snapshot_orders"] == 1
    assert trade["signal_date"] == "2026-07-10"
    assert trade["entry_date"] == "2026-07-10"
    assert trade["exit_date"] == "2026-07-13"
    assert trade["entry_price"] == 11.0
    assert trade["return_pct"] == 4.69
    assert report["summary"]["win_rate"] == 100.0


def test_next_auction_backtest_enters_d1_and_exits_d2_open() -> None:
    report = build_limit_up_entry_backtest(
        _entry_backtest_dataset(),
        [_saved_signal_snapshot()],
        entry_mode="next_auction",
        exit_mode="next_open",
    )

    trade = report["trades"][0]
    assert trade["signal_date"] == "2026-07-10"
    assert trade["entry_date"] == "2026-07-13"
    assert trade["auction_gap_pct"] == 5.0
    assert trade["exit_date"] == "2026-07-14"
    assert trade["entry_price"] == 11.55
    assert trade["return_pct"] == 3.5861


def test_entry_backtest_compatibility_entrypoint_uses_full_history(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_history(start, end, entry_mode, exit_mode):
        captured.update(start=start, end=end, entry_mode=entry_mode, exit_mode=exit_mode)
        return {"status": "ready", "mode": "point_in_time_history_replay"}

    monkeypatch.setattr(entry_backtest_service, "get_history_backtest", fake_history)

    result = entry_backtest_service.get_limit_up_entry_backtest(
        date(2026, 7, 10),
        date(2026, 7, 10),
        "next_auction",
        "next_open",
    )

    assert result["mode"] == "point_in_time_history_replay"
    assert captured["entry_mode"] == "next_auction"


def _saved_signal_snapshot() -> dict[str, object]:
    signal = {
        "vt_symbol": "600001.SSE",
        "name": "严格信号",
        "sector_id": "BK1",
        "sector_name": "机器人",
        "market_dragon_rank": 1,
        "sector_dragon_rank": 1,
        "board_level": 1,
        "state": "resealed",
        "open_times": 5,
        "trigger_price": 11.0,
        "execution_confidence": "proxy_without_l2",
    }
    return {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T10:05:00+08:00",
        "candidates": [signal],
        "recommendations": {
            "lanes": {
                "now": [{**signal, "action": "buy_now", "entry_kind": "sweep"}],
                "tail": [],
                "next_auction": [
                    {**signal, "action": "next_auction", "entry_kind": "next_auction"}
                ],
            }
        },
    }


def _entry_backtest_dataset() -> dict[str, object]:
    bars = [
        {
            "vt_symbol": "600001.SSE",
            "trade_date": trade_date,
            "open_price": open_price,
            "close_price": close_price,
            "high_price": max(open_price, close_price),
            "low_price": min(open_price, close_price),
        }
        for trade_date, open_price, close_price in (
            ("2026-07-09", 9.8, 10.0),
            ("2026-07-10", 10.2, 11.0),
            ("2026-07-13", 11.55, 11.8),
            ("2026-07-14", 12.0, 12.1),
        )
    ]
    return {"events": [], "daily_bars": bars, "coverage": {"event_trade_days": 0}}
