from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.live_policy import (
    build_live_recommendations,
    rank_live_candidates,
    rank_live_opportunities,
    session_stage,
)
from alphaagent.server.services.limit_up.entry_backtest import build_limit_up_entry_backtest
from alphaagent.server.services.limit_up import entry_backtest as entry_backtest_service
from alphaagent.server.services.limit_up import history_engine
from alphaagent.server.services.limit_up import live_evidence
from alphaagent.server.services.limit_up import live_policy
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


def _previous_live_snapshot(
    captured_at: datetime,
    *,
    repair_state: str,
    repair_confirmed_at: str | None = None,
) -> dict[str, object]:
    return {
        "trade_date": captured_at.date().isoformat(),
        "captured_at": captured_at.isoformat(),
        "recommendations": {
            "market_gate": {
                "repair_state": repair_state,
                "repair_confirmed": repair_state == "repair_confirmed",
                "repair_confirmed_at": repair_confirmed_at,
                "reasons": [],
            }
        },
    }


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


def test_prior_board_context_serializes_database_date() -> None:
    context = live_repository._prior_board_context(
        {
            "trade_date": date(2026, 7, 10),
            "is_sealed": True,
            "open_times": 2,
        },
        {},
    )

    assert context is not None
    assert context["trade_date"] == "2026-07-10"
    assert json.loads(json.dumps(context))["trade_date"] == "2026-07-10"


def test_tbox_score_rewards_high_quality_history_and_is_bounded() -> None:
    high_quality = live_evidence.tbox_score(
        {
            "smoothed_win_rate": 65.0,
            "average_return_pct": 3.0,
            "hard_loss_rate": 5.0,
            "seal_after_touch_rate": 80.0,
            "confidence": "high",
        }
    )
    low_quality = live_evidence.tbox_score(
        {
            "smoothed_win_rate": 42.0,
            "average_return_pct": -0.5,
            "hard_loss_rate": 24.0,
            "seal_after_touch_rate": 42.0,
            "confidence": "low",
        }
    )

    assert high_quality > low_quality
    assert 0 <= low_quality <= high_quality <= 100
    assert live_evidence.tbox_score({}) == 0


def test_next_auction_evidence_uses_the_signal_target_board() -> None:
    entry_mode, target_board, feature_scope = live_evidence._route_context(
        {"board_level": 3},
        {},
        "next_auction",
    )

    assert entry_mode == "next_auction"
    assert target_board == 3
    assert feature_scope == "next_auction_gap_pending"


def test_live_lane_decisions_mark_shared_portfolio_members(monkeypatch) -> None:
    candidates = [
        _candidate(
            "600001.SSE",
            lane_feature_ready=True,
            sector_id="BK1",
            sector_name="机器人",
        ),
        _candidate(
            "600002.SSE",
            lane_feature_ready=True,
            sector_id="BK2",
            sector_name="算力",
        ),
    ]
    selected_inputs: list[list[dict[str, object]]] = []

    def select(rows):
        selected_inputs.append([dict(row) for row in rows])
        return {"selected": [{"vt_symbol": "600002.SSE"}]}

    monkeypatch.setattr(live_service, "select_daily_lane_portfolio", select)

    live_service._attach_lane_decisions(
        candidates,
        _market(),
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
    )

    assert len(selected_inputs) == 1
    assert candidates[0]["portfolio_selected"] is False
    assert candidates[1]["portfolio_selected"] is True


def test_live_lane_decisions_skip_reclassified_one_to_two_candidate() -> None:
    candidate = _candidate(
        "600001.SSE",
        board_level=1,
        prior_streak=1,
        lane_feature_ready=True,
    )

    live_service._attach_lane_decisions(
        [candidate],
        _market(),
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
    )

    assert candidate["board_lane"] == "one_to_two"
    assert candidate["lane_decision"] == "removed"
    assert candidate["lane_blockers"] == ["one_to_two_removed"]
    assert candidate["portfolio_selected"] is False


def test_live_portfolio_prefers_same_frame_relay_then_first_board() -> None:
    def signal(
        symbol: str,
        lane: str,
        *,
        action: str,
        tbox: float,
        win_rate: float,
        compound: float,
        selected: bool = True,
    ) -> dict[str, object]:
        return {
            "vt_symbol": symbol,
            "board_lane": lane,
            "portfolio_selected": selected,
            "action": action,
            "research_action": action,
            "leadership_score": 80.0,
                "historical_evidence": {
                    "tbox_score": tbox,
                    "smoothed_win_rate": win_rate,
                    **(
                        {
                            "d1_money_effect_sample_count": 5,
                            "historical_win_rate": 30.0,
                        }
                        if lane == "first_board"
                        else {}
                    ),
                },
            "strategy_evidence": {"total_return_pct": compound},
        }

    missed = signal(
        "600006.SSE",
        "first_board",
        action="observe",
        tbox=98,
        win_rate=68,
        compound=35,
    )
    missed["missed_preseal_entry"] = True
    recommendations = {
        "lanes": {
            "now": [
                signal("600001.SSE", "first_board", action="buy_now", tbox=95, win_rate=60, compound=20),
                signal("600007.SSE", "first_board", action="buy_now", tbox=90, win_rate=59, compound=18),
                signal("600008.SSE", "first_board", action="buy_now", tbox=85, win_rate=58, compound=16),
                signal("600002.SSE", "high_board", action="buy_now", tbox=70, win_rate=55, compound=12),
                signal("600003.SSE", "two_to_three", action="buy_now", tbox=80, win_rate=58, compound=18),
                signal("600005.SSE", "high_board", action="buy_now", tbox=100, win_rate=75, compound=50, selected=False),
                missed,
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    portfolio = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=10,
    )

    assert [row["vt_symbol"] for row in portfolio] == [
        "600003.SSE",
        "600001.SSE",
    ]
    assert [row["board_lane"] for row in portfolio] == [
        "two_to_three",
        "first_board",
    ]
    assert all(row["action"] == "buy_now" for row in portfolio)
    assert all(row["signal_state"] == "trigger_ready" for row in portfolio)
    assert all(row["execution_permission"] == "research_only" for row in portfolio)
    assert all(row["sell_instruction"] == "D+1 14:30 统一卖出" for row in portfolio)


def test_live_portfolio_is_empty_outside_entry_window_or_when_snapshot_is_old() -> None:
    recommendations = {
        "lanes": {
            "now": [
                {
                    "vt_symbol": "600001.SSE",
                    "board_lane": "first_board",
                    "portfolio_selected": True,
                    "action": "buy_now",
                    "research_action": "buy_now",
                    "reason": "研究买点成立",
                    "historical_evidence": {
                        "tbox_score": 80.0,
                        "d1_money_effect_sample_count": 5,
                        "historical_win_rate": 30.0,
                    },
                    "strategy_evidence": {"total_return_pct": 20.0},
                }
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    continuous = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 14, 10, 20, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )[0]
    assert continuous["action"] == "buy_now"
    assert continuous["signal_state"] == "trigger_ready"
    assert len(
        live_service._build_live_actionable_recommendations(
            recommendations,
            captured_at=datetime(2026, 7, 14, 10, 20, tzinfo=SHANGHAI),
            snapshot_age_seconds=5,
        )
    ) == 1

    paused = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 14, 12, 0, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )
    assert paused == []
    assert live_service._build_live_actionable_recommendations(
        recommendations,
        captured_at=datetime(2026, 7, 14, 12, 0, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    ) == []

    stale = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=21,
    )
    assert stale == []
    assert live_service._build_live_actionable_recommendations(
        recommendations,
        captured_at=datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=21,
    ) == []


def test_live_portfolio_excludes_structurally_selected_observation() -> None:
    recommendations = {
        "lanes": {
            "now": [
                {
                    "vt_symbol": "600001.SSE",
                    "board_lane": "first_board",
                    "portfolio_selected": True,
                    "state": "near_limit",
                    "action": "observe",
                    "research_action": "observe",
                    "signal_state": "approaching_trigger",
                    "entry_kind": "sweep",
                    "reason": "板块触板2/3只",
                    "pending_reasons": ["板块触板2/3只"],
                    "historical_evidence": {"tbox_score": 80.0},
                    "strategy_evidence": {"total_return_pct": 20.0},
                }
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    portfolio = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 14, 13, 20, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )

    assert portfolio == []


def test_live_watchlist_only_keeps_candidates_that_can_transition_to_buy() -> None:
    recommendations = {
        "lanes": {
            "now": [
                {
                    "vt_symbol": "600001.SSE",
                    "board_lane": "first_board",
                    "lane_decision": "blocked",
                    "state": "near_limit",
                    "distance_to_limit_pct": 0.5,
                    "action": "pass",
                    "signal_state": "rejected",
                    "blocking_scope": "structural",
                    "reason": "缺少财报证据",
                    "leadership_score": 70.0,
                    "strategy_evidence": {"total_return_pct": 55.0},
                    "historical_evidence": {"tbox_score": 45.0},
                },
                {
                    "vt_symbol": "600002.SSE",
                    "board_lane": "first_board",
                    "lane_decision": "blocked",
                    "state": "near_limit",
                    "distance_to_limit_pct": 1.4,
                    "action": "observe",
                    "signal_state": "approaching_trigger",
                    "blocking_scope": "dynamic",
                    "reason": "等待进入1%扫板触发区",
                    "leadership_score": 90.0,
                    "strategy_evidence": {"total_return_pct": 58.0},
                    "historical_evidence": {"tbox_score": 90.0},
                },
                {
                    "vt_symbol": "600003.SSE",
                    "board_lane": "first_board",
                    "lane_decision": "blocked",
                    "state": "strong",
                    "action": "observe",
                    "signal_state": "concept_warming",
                    "blocking_scope": "dynamic",
                    "reason": "PCB板块预热",
                    "strategy_evidence": {"total_return_pct": 50.0},
                    "historical_evidence": {"tbox_score": 85.0},
                },
                {
                    "vt_symbol": "600004.SSE",
                    "board_lane": "first_board",
                    "lane_decision": "eligible",
                    "state": "sealed",
                    "action": "wait_tail",
                    "signal_state": "missed",
                    "reason": "已封板，买点错过",
                },
                {
                    "vt_symbol": "600005.SSE",
                    "board_lane": "first_board",
                    "lane_decision": "eligible",
                    "state": "near_limit",
                    "action": "pass",
                    "signal_state": "rejected",
                    "blocking_scope": "structural",
                    "reason": "首板结构硬门未通过",
                },
                {
                    "vt_symbol": "600006.SSE",
                    "board_lane": "first_board",
                    "lane_decision": "eligible",
                    "state": "near_limit",
                    "action": "observe",
                    "signal_state": "invalidated",
                    "reason": "实时快照已失效",
                },
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    watchlist = live_service._build_live_watchlist(recommendations)

    assert [row["vt_symbol"] for row in watchlist] == [
        "600002.SSE",
        "600003.SSE",
    ]
    assert {row["signal_state"] for row in watchlist} == {
        "approaching_trigger",
        "concept_warming",
    }
    assert all(row["action"] == "observe" for row in watchlist)
    assert all("今日拒买" not in str(row.get("reason") or "") for row in watchlist)


def test_lane_validation_attaches_strategy_history_summary() -> None:
    recommendations = {
        "lanes": {
            "now": [
                {
                    "vt_symbol": "600001.SSE",
                    "board_level": 1,
                    "board_lane": "first_board",
                    "action": "observe",
                }
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    result = live_service.apply_lane_validation_veto(
        recommendations,
        {
            "first_board": {
                "passed": True,
                "status": "validated",
                "reason": "验证通过",
                "summary": {
                    "win_rate": 56.0,
                    "total_return_pct": 28.0,
                    "max_drawdown_pct": -12.0,
                    "trade_count": 80,
                },
            }
        },
    )

    assert result["lanes"]["now"][0]["strategy_evidence"] == {
        "win_rate": 56.0,
        "total_return_pct": 28.0,
        "max_drawdown_pct": -12.0,
        "trade_count": 80,
    }


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


def test_five_percent_radar_candidates_are_all_evaluated_before_ranking() -> None:
    captured_at = datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI)
    quotes = {
        "items": [
            {
                "vt_symbol": "600001.SSE",
                "name": "预热股",
                "change_pct": 5.5,
                "last_price": 10.55,
                "previous_close": 10.0,
            },
            {
                "vt_symbol": "600002.SSE",
                "name": "临板股",
                "change_pct": 9.2,
                "last_price": 10.92,
                "previous_close": 10.0,
            },
            {
                "vt_symbol": "600003.SSE",
                "name": "板块待补",
                "change_pct": 6.0,
                "last_price": 10.6,
                "previous_close": 10.0,
            },
        ]
    }
    context = {
        "by_symbol": {
            "600001.SSE": {"sector_id": "BK1", "sector_name": "机器人"},
            "600002.SSE": {"sector_id": "BK2", "sector_name": "算力"},
        }
    }

    snapshot = build_live_snapshot(
        quotes,
        {"trade_date": "20260714", "pools": {}},
        captured_at,
        context,
    )

    assert {row["vt_symbol"] for row in snapshot["trace_radar_candidates"]} == {
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    }
    assert {
        row["vt_symbol"]: row["board_lane"]
        for row in snapshot["trace_radar_candidates"]
    } == {
        "600001.SSE": "first_board",
        "600002.SSE": "first_board",
        "600003.SSE": "first_board",
    }
    assert {row["vt_symbol"] for row in snapshot["candidates"]} == {
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    }


def test_saved_weekend_snapshot_is_normalized_to_latest_market_date() -> None:
    snapshot = {
        "trade_date": "2026-07-11",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "recommendations": {
            "market_gate": {
                "passed": True,
                "repair_confirmed": True,
                "repair_state": "repair_confirmed",
                "repair_confirmed_at": "2026-07-10T10:01:00+08:00",
                "reasons": [],
            },
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
    traces: list[dict[str, object]] = []
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
    monkeypatch.setattr(
        live_service,
        "save_live_trace_snapshot",
        lambda snapshot: traces.append(snapshot) or snapshot,
    )

    result = live_service.refresh_live_snapshot(
        datetime(2026, 7, 13, 10, 5, tzinfo=SHANGHAI),
        adapter=object(),
    )

    assert result["trade_date"] == "2026-07-10"
    assert result["mode"] == "stale_snapshot"
    assert persisted == []
    assert traces == [result]


def test_refresh_persists_verified_current_session_snapshot(monkeypatch) -> None:
    persisted: list[dict[str, object]] = []
    traces: list[dict[str, object]] = []
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
    monkeypatch.setattr(
        live_service,
        "save_live_trace_snapshot",
        lambda snapshot: traces.append(snapshot) or snapshot,
    )

    result = live_service.refresh_live_snapshot(
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
        adapter=object(),
    )

    assert result["trade_date"] == "2026-07-10"
    assert result["mode"] == "live_snapshot"
    assert result["data_quality"]["is_stale"] is False
    assert persisted == [result]
    assert traces == [result]


def test_trace_write_failure_does_not_block_official_snapshot(monkeypatch) -> None:
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(
        live_service,
        "_fetch_live_payloads",
        lambda *_args: (
            {"items": []},
            {"trade_date": "20260714", "pools": {}},
            [],
        ),
    )
    monkeypatch.setattr(live_service, "load_latest_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        live_service,
        "save_live_trace_snapshot",
        lambda _snapshot: (_ for _ in ()).throw(RuntimeError("trace unavailable")),
    )
    monkeypatch.setattr(
        live_service,
        "save_snapshot",
        lambda snapshot: persisted.append(snapshot) or snapshot,
    )

    result = live_service.refresh_live_snapshot(
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
        adapter=object(),
    )

    assert persisted == [result]
    assert result["mode"] == "live_snapshot"
    assert result["data_quality"]["trace_cache_status"] == "error"
    assert result["data_quality"]["trace_cache_error"] == "trace unavailable"


def test_total_source_failure_records_trace_error_before_stale_fallback(monkeypatch) -> None:
    errors: list[tuple[datetime, str]] = []
    fallback = {
        "trade_date": "2026-07-13",
        "captured_at": "2026-07-13T14:57:00+08:00",
        "session_stage": "tail",
        "strategy_version": "limit-up-live-v2",
        "mode": "live_snapshot",
        "recommendations": {
            "market_gate": {"passed": True, "reasons": []},
            "lanes": {"now": [], "tail": [], "next_auction": []},
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(
        live_service,
        "_fetch_live_payloads",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("source down")),
    )
    monkeypatch.setattr(
        live_service,
        "load_latest_snapshot",
        lambda *_args, **_kwargs: fallback,
    )
    monkeypatch.setattr(
        live_service,
        "save_live_trace_error",
        lambda captured_at, error, **_kwargs: errors.append((captured_at, str(error))) or {},
    )

    result = live_service.refresh_live_snapshot(
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
        adapter=object(),
    )

    assert [(captured_at.isoformat(), message) for captured_at, message in errors] == [
        ("2026-07-14T10:05:00+08:00", "source down")
    ]
    assert result["mode"] == "stale_snapshot"


def test_refresh_persists_nonempty_snapshot_with_prior_board_date(monkeypatch) -> None:
    persisted: list[dict[str, object]] = []
    monkeypatch.setattr(
        live_service,
        "_fetch_live_payloads",
        lambda *_args: (
            {
                "items": [
                    {
                        "vt_symbol": "600001.SSE",
                        "name": "测试股份",
                        "change_pct": 9.2,
                        "last_price": 10.92,
                        "previous_close": 10.0,
                    }
                ]
            },
            {"trade_date": "20260710", "pools": {}},
            [],
        ),
    )
    monkeypatch.setattr(
        live_service,
        "load_live_context",
        lambda *_args: {
            "by_symbol": {
                "600001.SSE": {
                    "sector_id": "BK1",
                    "sector_name": "机器人",
                    "prior_board": {
                        "trade_date": "2026-07-09",
                        "is_sealed": True,
                    },
                }
            }
        },
    )
    monkeypatch.setattr(live_service, "load_latest_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(live_service, "_load_lane_validations", lambda: {})
    monkeypatch.setattr(
        live_service,
        "_apply_live_risk_gates",
        lambda snapshot, _validations: snapshot,
    )

    def save(snapshot):
        json.dumps(snapshot)
        persisted.append(snapshot)
        return snapshot

    monkeypatch.setattr(live_service, "save_snapshot", save)

    result = live_service.refresh_live_snapshot(
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
        adapter=object(),
    )

    assert len(result["candidates"]) == 1
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


def test_live_read_prefers_same_day_snapshot_during_lunch(monkeypatch) -> None:
    now = datetime(2026, 7, 10, 12, 0, tzinfo=SHANGHAI)
    morning_snapshot = {
        "trade_date": "2026-07-10",
        "captured_at": "2026-07-10T11:30:00+08:00",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "recommendations": {
            "market_gate": {"passed": True, "reasons": []},
            "actionable_recommendations": [
                {"action": "buy_now", "entry_kind": "sweep", "reason": "旧买点"}
            ],
            "portfolio": [{"action": "buy_now", "entry_kind": "sweep", "reason": "旧买点"}],
            "watchlist": [{"action": "observe", "entry_kind": "sweep", "reason": "旧观察"}],
            "lanes": {
                "now": [{"action": "buy_now", "entry_kind": "sweep", "reason": "旧买点"}],
                "tail": [],
                "next_auction": [],
            },
        },
        "data_quality": {"status": "ready", "is_stale": False},
    }
    monkeypatch.setattr(
        live_service,
        "load_latest_snapshot",
        lambda *_args, **_kwargs: morning_snapshot,
    )

    result = live_service.get_latest_live_snapshot(now)

    assert result["captured_at"] == morning_snapshot["captured_at"]
    assert result["trade_date"] == "2026-07-10"
    assert result["session_stage"] == "lunch"
    assert result["mode"] == "stale_snapshot"
    assert result["recommendations"]["lanes"]["now"][0]["action"] == "pass"
    assert result["recommendations"]["actionable_recommendations"][0]["action"] == "pass"
    assert result["recommendations"]["portfolio"][0]["action"] == "pass"
    assert result["recommendations"]["watchlist"][0]["action"] == "pass"
    assert "午间休市" in result["recommendations"]["lanes"]["now"][0]["reason"]


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
    assert result["recommendations"]["market_gate"]["repair_confirmed"] is False
    assert result["recommendations"]["market_gate"]["repair_state"] == "repair_revoked"
    assert "延迟91秒" in result["recommendations"]["market_gate"]["repair_revoked_reason"]
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


def test_live_opportunity_ranking_puts_unsealed_trigger_window_before_sealed_board() -> None:
    candidates = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                state="sealed",
                change_pct=10.0,
                distance_to_limit_pct=0.0,
                lane_decision="eligible",
                lane_rank_score=95.0,
            ),
            _candidate(
                "600002.SSE",
                state="near_limit",
                change_pct=8.0,
                distance_to_limit_pct=1.8,
                sector_id="theme-b",
                lane_decision="eligible",
                lane_rank_score=70.0,
            ),
        ],
        limit=10,
    )

    ranked = rank_live_opportunities(candidates)

    assert [row["vt_symbol"] for row in ranked] == [
        "600002.SSE",
        "600001.SSE",
    ]


def test_live_radar_starts_at_seven_percent_before_limit_up() -> None:
    rows = live_service._merge_source_rows(
        {
            "items": [
                {
                    "vt_symbol": "600001.SSE",
                    "name": "雷达候选",
                    "change_pct": 7.0,
                },
                {
                    "vt_symbol": "600002.SSE",
                    "name": "未到雷达",
                    "change_pct": 6.99,
                },
            ]
        },
        {},
    )

    assert set(rows) == {"600001.SSE"}


def test_live_stability_remembers_board_first_seen_after_seal() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    first = [_candidate("600001.SSE", state="sealed")]

    live_service._attach_stability(first, None, captured_at)

    assert first[0]["seen_before_seal"] is False
    assert first[0]["missed_preseal_entry"] is True

    second = [_candidate("600001.SSE", state="sealed")]
    live_service._attach_stability(
        second,
        {
            "captured_at": captured_at.isoformat(),
            "candidates": [first[0]],
        },
        captured_at + timedelta(seconds=15),
    )

    assert second[0]["seen_before_seal"] is False
    assert second[0]["missed_preseal_entry"] is True


def test_live_stability_remembers_candidate_seen_before_seal() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    previous = _candidate("600001.SSE", state="near_limit")
    previous["seen_before_seal"] = True
    current = [_candidate("600001.SSE", state="sealed")]

    live_service._attach_stability(
        current,
        {
            "captured_at": captured_at.isoformat(),
            "candidates": [previous],
        },
        captured_at + timedelta(seconds=15),
    )

    assert current[0]["seen_before_seal"] is True
    assert current[0]["missed_preseal_entry"] is False


def test_live_ranking_assigns_sector_rank_without_dropping_candidates() -> None:
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
        "600003.SSE",
        "600004.SSE",
    }
    assert max(
        int(row["sector_dragon_rank"])
        for row in ranked
        if row["sector_id"] == "theme-a"
    ) == 3


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

    result = attach_historical_evidence(
        snapshot,
        analog_index=analog_index,
        stock_d1_index={},
    )

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
    assert signal["action"] == "observe"
    assert signal["entry_kind"] == "auction"
    assert signal["trigger_price"] == candidate["last_price"]
    assert "10:00" in signal["reason"]


def test_live_signal_exposes_point_in_time_quote() -> None:
    candidate = rank_live_candidates(
        [_candidate("600001.SSE", last_price=10.87, change_pct=8.73)]
    )[0]

    result = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI),
    )

    signal = result["lanes"]["now"][0]
    assert signal["last_price"] == candidate["last_price"]
    assert signal["change_pct"] == candidate["change_pct"]


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
    assert signal["action"] == "observe"
    assert signal["signal_state"] == "approaching_trigger"
    assert signal["execution_permission"] == "research_only"
    assert signal["strategy_name"] == "二进三·弱转强突破"
    assert signal["selection_reasons"] == ["前板换手回封", "三板弱转强"]
    assert [check["code"] for check in signal["trigger_checks"]] == [
        "market_gate",
        "lane_gate",
        "auction_gap",
        "sector_heat",
        "sector_flow",
        "stock_flow",
        "turnover_rate",
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
    assert signal["action"] == "observe"
    assert signal["entry_kind"] == "auction"
    assert "10:00" in signal["reason"]


def test_live_two_to_three_first_touch_can_trigger_in_shared_window() -> None:
    captured_at = datetime(2026, 7, 10, 10, 6, 15, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                board_level=3,
                board_lane="two_to_three",
                lane_decision="eligible",
                state="sealed",
                first_limit_time="10:06:02",
            )
        ]
    )[0]
    candidate.update(live_service._live_relay_trigger(candidate, captured_at))

    result = build_live_recommendations([candidate], _market(), captured_at)

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "buy_now"
    assert signal["entry_kind"] == "first_touch"


def test_live_pre_ten_seal_without_new_window_reseal_is_not_bought() -> None:
    captured_at = datetime(2026, 7, 10, 10, 5, tzinfo=SHANGHAI)
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                board_level=3,
                board_lane="two_to_three",
                lane_decision="eligible",
                state="sealed",
                first_limit_time="09:35:00",
                last_limit_time="09:35:00",
            )
        ]
    )[0]
    candidate.update(live_service._live_relay_trigger(candidate, captured_at))

    result = build_live_recommendations([candidate], _market(), captured_at)

    signal = result["lanes"]["now"][0]
    assert signal["action"] == "observe"
    assert "不追已经封住" in signal["reason"]


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

    assert accepted["lanes"]["now"][0]["action"] == "observe"
    assert "10:00" in accepted["lanes"]["now"][0]["reason"]
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
    signal = snapshot["recommendations"]["lanes"]["now"][0]
    assert signal["action"] == "observe"
    assert any(
        check["code"] == "concept_state" and check["status"] == "pending"
        for check in signal["trigger_checks"]
    )


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


def test_market_repair_stays_confirmed_when_next_snapshot_delta_is_zero() -> None:
    repaired_at = datetime(2026, 7, 14, 9, 59, 22, tzinfo=SHANGHAI)
    current_at = datetime(2026, 7, 14, 9, 59, 38, tzinfo=SHANGHAI)
    previous = _previous_live_snapshot(
        repaired_at,
        repair_state="repair_confirmed",
        repair_confirmed_at=repaired_at.isoformat(),
    )

    result = build_live_recommendations(
        [],
        _market(
            sentiment={"phase": "ice", "failed_limit_up_rate": 0.54},
            sealed_count=24,
            failed_count=7,
            failed_rate=7 / 31,
            sealed_change=0,
            failed_change=0,
        ),
        current_at,
        previous_snapshot=previous,
    )

    gate = result["market_gate"]
    assert gate["passed"] is True
    assert gate["repair_state"] == "repair_confirmed"
    assert gate["repair_confirmed_at"] == repaired_at.isoformat()


def test_market_repair_is_revoked_by_failed_rate_breakdown() -> None:
    previous_at = datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI)
    current_at = datetime(2026, 7, 14, 10, 6, tzinfo=SHANGHAI)
    previous = _previous_live_snapshot(
        previous_at,
        repair_state="repair_confirmed",
        repair_confirmed_at=previous_at.isoformat(),
    )

    result = build_live_recommendations(
        [],
        _market(
            sentiment={"phase": "ice", "failed_limit_up_rate": 0.54},
            sealed_count=20,
            failed_count=12,
            failed_rate=0.375,
            sealed_change=-2,
            failed_change=2,
        ),
        current_at,
        previous_snapshot=previous,
    )

    gate = result["market_gate"]
    assert gate["passed"] is False
    assert gate["repair_state"] == "repair_revoked"
    assert "炸板率" in gate["repair_revoked_reason"]


def test_confirmed_live_repair_removes_only_duplicated_d1_market_blockers() -> None:
    base = _candidate(
        "600001.SSE",
        board_level=3,
        previous_limit_up=True,
        lane_feature_ready=True,
        sector_heat=70.0,
        sector_dragon_rank=1,
        auction_gap_pct=3.0,
        prior_turnover_rate=15.0,
        prior_amount_ratio_5d=1.5,
        prior_amplitude_pct=7.0,
        prior_low_change_pct=-1.0,
        prior_market_two_to_three_rate=0.30,
        prior_board={
            "is_sealed": True,
            "first_limit_time": "10:10:00",
            "last_limit_time": "10:25:00",
            "open_times": 1,
        },
        financial_snapshot={"publish_date": "2026-06-30"},
    )
    missing_prior_board = {
        **base,
        "vt_symbol": "600002.SSE",
        "prior_board": None,
    }

    candidates = [base, missing_prior_board]
    live_service._attach_lane_decisions(
        candidates,
        _market(sentiment={"phase": "ice", "failed_limit_up_rate": 0.54}),
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
        market_gate={"repair_confirmed": True},
    )

    assert base["lane_decision"] == "eligible"
    assert "market_retreat" not in base["lane_blockers"]
    assert "market_failed_rate_high" not in base["lane_blockers"]
    assert missing_prior_board["lane_decision"] == "blocked"
    assert "prior_board_evidence_missing" in missing_prior_board["lane_blockers"]


def test_market_pending_keeps_structurally_eligible_near_limit_candidate_approaching() -> None:
    signal = build_live_recommendations(
        [_candidate("600001.SSE", state="near_limit", distance_to_limit_pct=0.6)],
        _market(
            sentiment={"phase": "ice", "failed_limit_up_rate": 0.54},
            sealed_change=0,
            failed_change=0,
        ),
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
    )["lanes"]["now"][0]

    assert signal["action"] == "observe"
    assert signal["signal_state"] == "approaching_trigger"
    assert signal["blocking_scope"] == "market"
    assert "尚未确认修复" in signal["pending_reasons"][0]


def test_structural_lane_failure_is_rejected() -> None:
    candidate = _candidate(
        "600001.SSE",
        state="near_limit",
        lane_decision="blocked",
        lane_blockers=["limit_up_gene_missing"],
    )

    signal = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
    )["lanes"]["now"][0]

    assert signal["action"] == "pass"
    assert signal["signal_state"] == "rejected"
    assert signal["blocking_scope"] == "structural"


def test_first_board_before_ten_is_dynamic_waiting_not_hard_rejection() -> None:
    candidate = _candidate(
        "600001.SSE",
        state="near_limit",
        lane_decision="blocked",
        lane_blockers=["first_touch_too_early"],
    )

    signal = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 14, 9, 55, tzinfo=SHANGHAI),
    )["lanes"]["now"][0]

    assert signal["action"] == "observe"
    assert signal["signal_state"] == "approaching_trigger"
    assert signal["blocking_scope"] == "dynamic"
    assert signal["pending_reasons"] == ["10点前仅观察，等待10点后确认"]


def test_sweep_checks_expose_the_same_heat_and_expansion_thresholds_used_to_trigger() -> None:
    candidate = _candidate(
        "600001.SSE",
        state="near_limit",
        distance_to_limit_pct=0.5,
        sector_heat=55.0,
        sector_touch_count=2,
    )

    signal = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
    )["lanes"]["now"][0]

    assert signal["action"] == "observe"
    assert signal["signal_state"] == "approaching_trigger"
    assert signal["blocking_scope"] == "dynamic"
    checks = {check["code"]: check for check in signal["trigger_checks"]}
    assert checks["sector_heat"]["observed"] == "55.00"
    assert checks["sector_heat"]["required"] == ">=60"
    assert checks["sector_expansion"]["observed"] == "2只"
    assert checks["sector_expansion"]["required"] == ">=3只"


def test_first_board_does_not_create_tomorrows_one_to_two_plan() -> None:
    candidate = rank_live_candidates(
        [_candidate("600001.SSE", board_level=1, state="resealed", open_times=2)]
    )[0]

    result = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 10, 14, 35, tzinfo=SHANGHAI),
    )

    signal = result["lanes"]["next_auction"][0]
    assert signal["board_level"] == 1
    assert signal["action"] == "pass"
    assert "不生成一进二" in signal["reason"]


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
                    "signal_state": "trigger_ready",
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
    assert signal["signal_state"] == "trigger_ready"
    assert signal["validation_status"] == "research_only"
    assert "只观察" in signal["reason"]


def test_live_two_to_three_uses_the_passing_product_portfolio_gate(monkeypatch) -> None:
    from alphaagent.server.services.limit_up import history_service

    monkeypatch.setattr(
        history_service,
        "get_lane_validation_snapshot",
        lambda: {
            "first_board": {"passed": True, "status": "validated"},
            "two_to_three": {"passed": False, "status": "research_only"},
            "high_board": {"passed": False, "status": "research_only"},
        },
    )
    monkeypatch.setattr(
        history_service,
        "get_scheduled_history_backtest",
        lambda *_args, **_kwargs: {
            "relay_comparison": {
                "configured_variant": "first_board_two_to_three",
                "configuration_matches_gate": True,
                "variants": {
                    "first_board_two_to_three": {
                        "passed": True,
                        "summary": {"total_return_pct": 266.4},
                    }
                },
            }
        },
    )

    validations = live_service._load_lane_validations()

    assert validations["first_board"]["passed"] is True
    assert validations["first_board"]["status"] == "portfolio_gate_passed"
    assert validations["two_to_three"]["passed"] is True
    assert validations["two_to_three"]["status"] == "portfolio_gate_passed"
    assert validations["high_board"]["passed"] is False


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

    result = attach_historical_evidence(
        snapshot,
        analog_index=analog_index,
        stock_d1_index={},
    )

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
    assert set(by_symbol) == {"600001.SSE", "600003.SSE"}
    assert by_symbol["600001.SSE"]["state"] == "near_limit"
    assert by_symbol["600001.SSE"]["auction_gap_pct"] == 3.0
    assert by_symbol["600001.SSE"]["previous_limit_up"] is True
    assert by_symbol["600003.SSE"]["state"] == "failed"
    next_session = {
        row["vt_symbol"]: row
        for row in snapshot["recommendations"]["lanes"]["next_auction"]
    }
    assert next_session["600002.SSE"]["board_level"] == 3
    assert next_session["600002.SSE"]["board_lane"] == "two_to_three"
    assert next_session["600002.SSE"]["action"] == "observe"
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

    assert len(snapshot["candidates"]) == 3
    assert {row["sector_dragon_rank"] for row in snapshot["candidates"]} == {1, 2, 3}
    assert all(row["sector_touch_count"] == 3 for row in snapshot["candidates"])


def test_live_snapshot_evaluates_full_radar_and_marks_top5_by_rank() -> None:
    captured_at = datetime(2026, 7, 10, 10, 15, tzinfo=SHANGHAI)
    quote_items = [
        {
            "vt_symbol": f"60000{index}.SSE",
            "name": f"雷达股{index}",
            "last_price": 10.8,
            "previous_close": 10.0,
            "change_pct": 8.0 + index / 10,
        }
        for index in range(1, 7)
    ]
    context = {
        "by_symbol": {
            item["vt_symbol"]: {
                "sector_id": f"BK{index}",
                "sector_name": f"板块{index}",
                "sector_heat": 60.0 + index,
            }
            for index, item in enumerate(quote_items, start=1)
        }
    }

    snapshot = build_live_snapshot(
        {"items": quote_items},
        {"trade_date": "20260710", "pools": {}},
        captured_at,
        context,
    )

    assert len(snapshot["candidates"]) == 6
    assert snapshot["data_quality"]["radar_candidate_count"] == 6
    assert snapshot["data_quality"]["ranked_candidate_count"] == 6
    assert len(snapshot["recommendations"]["lanes"]["now"]) == 6
    assert sum(row["market_dragon_rank"] <= 5 for row in snapshot["candidates"]) == 5


def test_all_radar_candidates_receive_lane_and_concept_decisions_before_top5() -> None:
    captured_at = datetime(2026, 7, 14, 13, 3, 30, tzinfo=SHANGHAI)
    symbols = [f"60000{index}.SSE" for index in range(8)]
    quotes = [
        {
            "vt_symbol": symbol,
            "name": f"PCB{index}",
            "change_pct": 9.0 + index / 100,
            "last_price": 10.9,
            "previous_close": 10.0,
            "turnover_rate": 8.0,
        }
        for index, symbol in enumerate(symbols)
    ]
    concept = {
        "concept_id": "BK0877",
        "concept_name": "PCB",
        "concept_state": "launch",
        "strength_score": 92.0,
        "strength_rank": 1,
        "strength_percentile": 0.01,
        "coverage_ratio": 0.98,
        "strong_5_count": 8,
        "near_limit_count": 8,
        "sealed_count": 0,
        "failed_count": 0,
        "change_acceleration_3m": 3.2,
        "turnover_acceleration_3m": 2_000_000_000.0,
    }
    concept_snapshot = {
        "trade_date": "2026-07-14",
        "captured_at": "2026-07-14T13:03:20+08:00",
        "source_updated_at": "2026-07-14T13:03:20+08:00",
        "radar_quotes": quotes,
        "membership": {"by_symbol": {symbol: ["BK0877"] for symbol in symbols}},
        "concepts_by_id": {"BK0877": concept},
        "data_quality": {
            "status": "ready",
            "age_seconds": 10,
            "quote_coverage_ratio": 0.98,
            "trigger_allowed": True,
        },
        "membership_snapshot_date": "2026-07-13",
    }
    context = {
        "by_symbol": {
            symbol: {"lane_feature_ready": False}
            for symbol in symbols
        }
    }

    snapshot = build_live_snapshot(
        {"items": []},
        {"trade_date": "20260714", "pools": {}},
        captured_at,
        context,
        concept_snapshot=concept_snapshot,
    )

    assert len(snapshot["candidates"]) == 8
    assert all(candidate.get("lane_decision") for candidate in snapshot["candidates"])
    assert all(candidate.get("concept_id") == "BK0877" for candidate in snapshot["candidates"])
    assert len(snapshot["recommendations"]["lanes"]["now"]) == 8


def test_fifteen_second_pool_increment_updates_cached_concept_seal_count() -> None:
    membership = {
        "snapshot_date": "2026-07-13",
        "by_symbol": {
            "600001.SSE": ["BK0877"],
            "600002.SSE": ["BK0877"],
        },
        "by_concept": {
            "BK0877": {
                "concept_id": "BK0877",
                "concept_name": "PCB",
                "sector_type": "theme",
                "members": {"600001.SSE", "600002.SSE"},
            }
        },
    }
    quotes = [
        {
            "vt_symbol": "600001.SSE",
            "name": "PCB一号",
            "change_pct": 9.4,
            "last_price": 10.94,
            "previous_close": 10.0,
            "turnover": 500_000_000.0,
        },
        {
            "vt_symbol": "600002.SSE",
            "name": "PCB二号",
            "change_pct": 7.2,
            "last_price": 10.72,
            "previous_close": 10.0,
            "turnover": 400_000_000.0,
        },
    ]
    base = {
        "captured_at": "2026-07-14T13:03:00+08:00",
        "trade_date": "2026-07-14",
        "quotes": quotes,
        "radar_quotes": quotes,
        "membership": membership,
        "concepts": [
            {
                "concept_id": "BK0877",
                "concept_name": "PCB",
                "change_acceleration_3m": 1.2,
            }
        ],
        "concepts_by_id": {},
        "data_quality": {"age_seconds": 15, "quote_coverage_ratio": 1.0},
    }
    pools = {
        "pools": {
            "zt": {
                "items": [
                    {
                        "vt_symbol": "600001.SSE",
                        "name": "PCB一号",
                        "change_pct": 10.0,
                        "close_price": 11.0,
                        "limit_up_price": 11.0,
                    }
                ]
            }
        }
    }

    result = live_service._concept_snapshot_with_incremental_quotes(
        base,
        {"items": quotes},
        pools,
        datetime(2026, 7, 14, 13, 3, 15, tzinfo=SHANGHAI),
    )

    assert result is not None
    assert result["concepts_by_id"]["BK0877"]["sealed_count"] == 1
    assert result["concepts_by_id"]["BK0877"]["strong_5_count"] == 2


def test_sweep_requires_fresh_concept_launch_and_top3_leader() -> None:
    candidate = _candidate(
        "600001.SSE",
        concept_state="launch",
        concept_snapshot_age_seconds=12,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=6,
        concept_leader_rank=2,
        stock_main_net_inflow=None,
    )

    checks = live_policy._candidate_execution_checks(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    )
    by_code = {check["code"]: check for check in checks}

    assert by_code["concept_state"]["status"] == "informational"
    assert by_code["concept_state"]["diagnostic_status"] == "passed"
    assert by_code["concept_leader"]["status"] == "informational"
    assert by_code["concept_leader"]["diagnostic_status"] == "passed"
    assert by_code["sector_route"]["status"] == "passed"
    assert by_code["stock_flow"]["status"] == "informational"
    assert live_policy._candidate_execution_reasons(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    ) == []


def test_legacy_sector_route_survives_unavailable_concept() -> None:
    candidate = _candidate(
        "600001.SSE",
        concept_state="unavailable",
        concept_trigger_allowed=False,
        concept_snapshot_age_seconds=None,
        concept_coverage_ratio=0.0,
        concept_strong_5_count=0,
        concept_leader_rank=None,
    )

    checks = live_policy._candidate_execution_checks(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    )
    by_code = {check["code"]: check for check in checks}

    assert live_policy._sweep_ready(candidate) is True
    assert by_code["sector_route"]["status"] == "passed"
    assert by_code["sector_route"]["observed"] == "行业基线通过"
    assert by_code["concept_state"]["status"] == "informational"
    assert by_code["concept_state"]["diagnostic_status"] == "pending"


def test_concept_increment_bypasses_wrong_legacy_sector_group() -> None:
    candidate = _candidate(
        "600001.SSE",
        sector_heat=45.0,
        sector_touch_count=0,
        sector_main_net_inflow=-5_000_000_000.0,
        concept_state="launch",
        concept_trigger_allowed=True,
        concept_snapshot_age_seconds=12,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=9,
        concept_leader_rank=2,
    )

    checks = live_policy._candidate_execution_checks(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    )
    by_code = {check["code"]: check for check in checks}

    assert live_policy._sweep_ready(candidate) is True
    assert by_code["sector_route"]["status"] == "passed"
    assert by_code["sector_route"]["observed"] == "概念增量通过"
    assert by_code["sector_heat"]["status"] == "informational"
    assert by_code["sector_heat"]["diagnostic_status"] == "pending"
    assert by_code["sector_flow"]["blocking"] is False


def test_both_sector_routes_failing_keeps_candidate_in_observation() -> None:
    candidate = _candidate(
        "600001.SSE",
        sector_heat=45.0,
        sector_touch_count=0,
        concept_state="warming",
        concept_trigger_allowed=True,
        concept_snapshot_age_seconds=12,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=4,
        concept_leader_rank=1,
    )

    checks = live_policy._candidate_execution_checks(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    )
    by_code = {check["code"]: check for check in checks}

    assert live_policy._sweep_ready(candidate) is False
    assert by_code["sector_route"]["status"] == "pending"
    assert by_code["sector_route"]["observed"] == "两条路径均未通过"


def test_stale_concept_snapshot_blocks_concept_only_trigger() -> None:
    candidate = _candidate(
        "600001.SSE",
        sector_heat=45.0,
        sector_touch_count=0,
        concept_state="launch",
        concept_snapshot_age_seconds=46,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=6,
        concept_leader_rank=1,
    )

    reasons = live_policy._candidate_execution_reasons(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    )

    assert any("概念行情已超过45秒" in reason for reason in reasons)


def test_global_concept_quality_blocks_concept_only_trigger() -> None:
    candidate = _candidate(
        "600001.SSE",
        sector_heat=45.0,
        sector_touch_count=0,
        concept_state="launch",
        concept_snapshot_age_seconds=12,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=6,
        concept_leader_rank=1,
        concept_trigger_allowed=False,
    )

    reasons = live_policy._candidate_execution_reasons(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    )

    assert any(
        "概念完整行情未通过交易日或全市场覆盖检查" in reason
        for reason in reasons
    )


def test_severe_stock_outflow_blocks_passing_concept_increment() -> None:
    candidate = _candidate(
        "600001.SSE",
        sector_heat=45.0,
        sector_touch_count=0,
        sector_main_net_inflow=-5_000_000_000.0,
        stock_main_net_inflow=-200_000_000.0,
        concept_state="launch",
        concept_trigger_allowed=True,
        concept_snapshot_age_seconds=12,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=9,
        concept_leader_rank=2,
    )

    reasons = live_policy._candidate_execution_reasons(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    )

    assert live_policy._sweep_ready(candidate) is False
    assert any("个股主力净流出" in reason for reason in reasons)


def test_short_cycle_pcb_increment_reaches_first_board_trigger() -> None:
    captured_at = datetime(2026, 7, 14, 13, 1, 57, tzinfo=SHANGHAI)
    market = _market(
        sentiment={
            "phase": "repair",
            "phase_label": "修复",
            "failed_limit_up_rate": 0.40,
        }
    )
    candidate = _candidate(
        "002384.SZSE",
        name="东山精密式样本",
        board_level=1,
        lane_feature_ready=True,
        previous_limit_up=False,
        prior_streak=0,
        prior_limit_count_5=1,
        prior_limit_count_126=8,
        prior_touch_count_126=13,
        prior_seal_success_rate_126=0.6154,
        trade_days_since_prior_limit=3,
        pullback_from_prior_limit_pct=-9.42,
        prior_position_120=0.8056,
        prior_change_pct=-2.31,
        prior_amplitude_pct=8.36,
        auction_gap_pct=2.04,
        prior_industry_heat_score=50.0,
        prior_market_failed_rate=0.40,
        path_prefix={
            "point_count": 15,
            "last_pct": 9.8,
            "touch_count": 0,
            "break_count": 0,
            "reseal_count": 0,
            "minimum_pct": 0.0,
            "approach_3point_pct": 3.0,
            "recent_15m_min_pct": 4.0,
            "recent_15m_change_pct": 5.8,
            "recent_15m_range_pct": 5.8,
            "recent_15m_drawdown_pct": 0.0,
            "recent_30m_min_pct": 1.8,
            "recent_30m_change_pct": 8.0,
        },
        financial_risk={"level": "clear", "blocked": False, "reasons": []},
        financial_snapshot={"net_profit_yoy": 563.64},
        state="near_limit",
        distance_to_limit_pct=0.2,
        sector_heat=50.0,
        sector_touch_count=0,
        sector_main_net_inflow=-5_200_000_000.0,
        stock_main_net_inflow=2_070_000_000.0,
        turnover_rate=5.72,
        concept_id="BK0877",
        concept_name="PCB",
        concept_state="launch",
        concept_trigger_allowed=True,
        concept_snapshot_age_seconds=12,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=9,
        concept_leader_rank=2,
    )

    live_service._attach_lane_decisions(
        [candidate],
        market,
        captured_at,
        market_gate={"repair_confirmed": True},
    )
    signal = build_live_recommendations(
        [candidate],
        market,
        captured_at,
    )["lanes"]["now"][0]

    assert candidate["board_lane"] == "first_board"
    assert candidate["lane_decision"] == "eligible"
    assert signal["action"] == "buy_now"
    assert signal["signal_state"] == "trigger_ready"
    assert signal["sector_route"] == "concept_increment"
    assert "prior_board_evidence_missing" not in signal["lane_blockers"]


def test_weak_market_theme_attack_reaches_live_first_board_trigger() -> None:
    captured_at = datetime(2026, 7, 15, 10, 12, tzinfo=SHANGHAI)
    market = _market(
        sentiment={
            "phase": "divergence",
            "phase_label": "分歧",
            "failed_limit_up_rate": 0.30,
        }
    )
    candidate = _candidate(
        "600001.SSE",
        name="弱市题材龙二",
        lane_feature_ready=True,
        prior_streak=0,
        prior_limit_count_5=0,
        prior_limit_count_126=3,
        prior_touch_count_126=3,
        prior_seal_success_rate_126=0.75,
        trade_days_since_prior_limit=18,
        pullback_from_prior_limit_pct=-12.0,
        prior_position_120=0.28,
        financial_risk={
            "level": "unknown",
            "blocked": False,
            "reasons": ["financial_report_missing"],
        },
        financial_snapshot=None,
        path_prefix={
            "point_count": 15,
            "last_pct": 9.2,
            "touch_count": 0,
            "break_count": 0,
            "reseal_count": 0,
            "minimum_pct": 5.0,
            "approach_3point_pct": 0.0,
            "recent_15m_min_pct": 5.0,
            "recent_15m_change_pct": 0.0,
            "recent_15m_range_pct": 0.0,
            "recent_15m_drawdown_pct": 0.0,
            "recent_30m_min_pct": 4.0,
            "recent_30m_change_pct": 1.0,
        },
        state="near_limit",
        distance_to_limit_pct=0.7,
        sector_heat=45.0,
        sector_touch_count=0,
        sector_main_net_inflow=-5_000_000_000.0,
        stock_main_net_inflow=120_000_000.0,
        turnover_rate=8.0,
        concept_id="BK1001",
        concept_name="题材概念",
        concept_state="launch",
        concept_trigger_allowed=True,
        concept_strength_score=60.0,
        concept_snapshot_age_seconds=12,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=6,
        concept_leader_rank=2,
    )

    live_service._attach_lane_decisions([candidate], market, captured_at)
    signal = build_live_recommendations(
        [candidate],
        market,
        captured_at,
    )["lanes"]["now"][0]

    assert candidate["lane_decision"] == "eligible"
    assert candidate["first_board_route"] == "weak_market_theme_attack"
    assert candidate["lane_premium_gate_passed"] is True
    assert "weak_market_theme_attack" in candidate["setup_tags"]
    assert signal["action"] == "buy_now"
    assert signal["signal_state"] == "trigger_ready"
    assert signal["first_board_route"] == "weak_market_theme_attack"
    assert signal["sector_route"] == "concept_increment"
    assert not {
        "first_board_touch_gene_weak",
        "financial_report_unavailable",
        "first_board_repair_setup_missing",
    }.intersection(signal["lane_blockers"])

    blocked = {
        **candidate,
        "financial_risk": {"level": "blocked", "blocked": True},
    }
    live_service._attach_lane_decisions([blocked], market, captured_at)
    blocked_signal = build_live_recommendations(
        [blocked],
        market,
        captured_at,
    )["lanes"]["now"][0]

    assert blocked["lane_decision"] == "blocked"
    assert "fundamental_risk" in blocked["lane_blockers"]
    assert blocked_signal["action"] == "pass"


def test_warming_concept_outside_one_percent_zone_is_prelimit_observation() -> None:
    candidate = rank_live_candidates(
        [
            _candidate(
                "600001.SSE",
                distance_to_limit_pct=2.5,
                concept_state="warming",
                concept_snapshot_age_seconds=12,
                concept_coverage_ratio=0.97,
                concept_strong_5_count=4,
                concept_leader_rank=1,
            )
        ]
    )[0]

    signal = build_live_recommendations(
        [candidate],
        _market(),
        datetime(2026, 7, 14, 13, 3, tzinfo=SHANGHAI),
    )["lanes"]["now"][0]

    assert signal["action"] == "observe"
    assert signal["signal_state"] == "concept_warming"


def test_live_research_uses_actual_touch_time_for_a_sealed_board() -> None:
    research = live_service._live_research_candidate(
        _candidate(
            "600001.SSE",
            state="sealed",
            first_limit_time="09:53:06",
        ),
        {},
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
    )

    assert research["evaluation_time"] == "10:05:00"
    assert research["signal_time"] == "09:53:06"


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
