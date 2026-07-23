from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import history_engine
from alphaagent.server.services.limit_up import live_evidence
from alphaagent.server.services.limit_up import live_service
from alphaagent.server.services.limit_up.first_board_profitability import (
    build_first_board_profitability_ranking_report,
    combined_historical_win_rate,
    rank_first_board_signals,
)
from alphaagent.server.services.limit_up.live_evidence import (
    attach_historical_evidence,
    build_same_stock_first_board_d1_index,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_live_evidence_indexes_share_one_projected_history_load(monkeypatch) -> None:
    signal_date = date(2026, 7, 20)
    rows = [{"trade_date": "2026-07-17", "lanes": {}, "lane_portfolio": {}}]
    calls: list[tuple[str, date]] = []
    analog_value = object()
    live_evidence.clear_live_evidence_cache()
    monkeypatch.setattr(
        live_evidence.history_repository,
        "history_coverage",
        lambda *_args: {"persisted_end": "2026-07-17", "persisted_days": 801},
    )
    monkeypatch.setattr(
        live_evidence.history_repository,
        "load_history_evidence_rows",
        lambda version, end: calls.append((version, end)) or rows,
    )
    monkeypatch.setattr(
        live_evidence.history_engine,
        "build_analog_index",
        lambda *_args, **_kwargs: {("analog",): analog_value},
    )
    monkeypatch.setattr(
        live_evidence,
        "build_same_stock_first_board_d1_index",
        lambda *_args, **_kwargs: {"600001.SSE": {"sample_count": 6}},
    )

    analog = live_evidence.load_history_analog_index(signal_date)
    stock = live_evidence.load_same_stock_first_board_d1_index(signal_date)

    assert analog == {("analog",): analog_value}
    assert analog[("analog",)] is analog_value
    assert stock == {"600001.SSE": {"sample_count": 6}}
    assert calls == [(history_engine.HISTORY_STRATEGY_VERSION, signal_date)]


def test_combined_historical_win_rate_multiplies_both_probabilities() -> None:
    assert combined_historical_win_rate(60.0, 80.0) == 48.0
    assert combined_historical_win_rate(0.0, 80.0) == 0.0
    assert combined_historical_win_rate(60.0, 0.0) == 0.0


def test_combined_historical_win_rate_fails_closed_for_invalid_inputs() -> None:
    assert combined_historical_win_rate(None, 80.0) is None
    assert combined_historical_win_rate(60.0, None) is None
    assert combined_historical_win_rate(-0.1, 80.0) is None
    assert combined_historical_win_rate(60.0, 100.1) is None
    assert combined_historical_win_rate("invalid", 80.0) is None


def test_first_board_ranking_prefers_combined_rate_then_change_pct() -> None:
    signals = [
        _signal("600001.SSE", historical_win_rate=48.0, change_pct=9.5),
        _signal("600002.SSE", historical_win_rate=48.0, change_pct=9.8),
        _signal("600003.SSE", historical_win_rate=52.0, change_pct=8.9),
        _signal("600004.SSE", historical_win_rate=None, change_pct=9.9),
    ]

    ranked = rank_first_board_signals(signals)

    assert [row["vt_symbol"] for row in ranked] == [
        "600003.SSE",
        "600002.SSE",
        "600001.SSE",
        "600004.SSE",
    ]


def test_first_board_ranking_does_not_reorder_other_lanes() -> None:
    signals = [
        _signal("600001.SSE", historical_win_rate=40.0, change_pct=9.0),
        _signal(
            "600010.SSE",
            lane="two_to_three",
            historical_win_rate=10.0,
            change_pct=9.2,
        ),
        _signal("600002.SSE", historical_win_rate=50.0, change_pct=8.0),
        _signal(
            "600011.SSE",
            lane="two_to_three",
            historical_win_rate=99.0,
            change_pct=10.0,
        ),
    ]

    ranked = rank_first_board_signals(signals)

    assert [row["vt_symbol"] for row in ranked] == [
        "600002.SSE",
        "600010.SSE",
        "600001.SSE",
        "600011.SSE",
    ]


def test_first_board_analog_separates_seal_and_d1_money_effect() -> None:
    matured = [
        _analog_candidate("2026-07-01", sealed=True, next_close_return_pct=2.0),
        _analog_candidate("2026-07-02", sealed=True, next_close_return_pct=-1.0),
        _analog_candidate("2026-07-03", sealed=True, next_close_return_pct=1.0),
        _analog_candidate("2026-07-06", sealed=False, next_close_return_pct=-4.0),
    ]
    same_day = _analog_candidate(
        "2026-07-10",
        sealed=True,
        next_close_return_pct=9.0,
    )
    analog_index = history_engine.build_analog_index(
        [{"lanes": {"sweep": [*matured, same_day]}}],
        result_before=date(2026, 7, 10),
    )

    analog = history_engine.resolve_analog(
        analog_index,
        _analog_candidate(None, sealed=False, next_close_return_pct=None),
        min_analogs=1,
    )

    assert analog["seal_sample_count"] == 4
    assert analog["seal_success_rate"] == 75.0
    assert analog["d1_money_effect_sample_count"] == 3
    assert analog["d1_money_effect_win_rate"] == 66.6667
    assert analog["d1_money_effect_average_return_pct"] == 0.6667
    assert analog["historical_win_rate"] == 50.0


def test_same_stock_d1_index_is_prior_only_and_window_bounded() -> None:
    days = [
        _stock_replay_day(
            "2026-07-01",
            _stock_event(
                "600001.SSE",
                "2026-07-02",
                sealed=True,
                return_pct=2.0,
            ),
        ),
        _stock_replay_day(
            "2026-07-02",
            _stock_event(
                "600002.SSE",
                "2026-07-03",
                sealed=True,
                return_pct=8.0,
            ),
        ),
        _stock_replay_day(
            "2026-07-03",
            _stock_event(
                "600001.SSE",
                "2026-07-06",
                sealed=True,
                return_pct=-1.0,
            ),
        ),
        _stock_replay_day(
            "2026-07-07",
            _stock_event(
                "600001.SSE",
                "2026-07-08",
                sealed=False,
                return_pct=-4.0,
            ),
        ),
        _stock_replay_day(
            "2026-07-09",
            _stock_event(
                "600001.SSE",
                "2026-07-10",
                sealed=True,
                return_pct=9.0,
            ),
        ),
    ]

    full = build_same_stock_first_board_d1_index(
        days,
        signal_date=date(2026, 7, 10),
        history_window_days=252,
    )
    bounded = build_same_stock_first_board_d1_index(
        days,
        signal_date=date(2026, 7, 10),
        history_window_days=2,
    )

    assert full["600001.SSE"] == {
        "sample_count": 2,
        "win_count": 1,
        "win_rate": 50.0,
        "average_return_pct": 0.5,
    }
    assert full["600002.SSE"]["sample_count"] == 1
    assert "600001.SSE" not in bounded


def test_live_evidence_uses_same_stock_metric_only_for_first_board() -> None:
    samples = [
        _analog_candidate("2026-07-01", sealed=True, next_close_return_pct=2.0),
        _analog_candidate("2026-07-02", sealed=False, next_close_return_pct=-3.0),
    ]
    analog_index = history_engine.build_analog_index(
        [{"lanes": {"sweep": samples}}],
        result_before=date(2026, 7, 10),
    )
    candidate = _analog_candidate(None, sealed=False, next_close_return_pct=None)
    candidate["vt_symbol"] = "600001.SSE"
    candidate.update(
        {
            "prior_limit_count_126": 6,
            "prior_touch_count_126": 8,
            "prior_seal_success_rate_126": 0.75,
        }
    )
    snapshot = {
        "trade_date": "2026-07-10",
        "candidates": [candidate],
        "market_context": {},
        "recommendations": {
            "lanes": {
                "now": [
                    {
                        "vt_symbol": "600001.SSE",
                        "board_level": 1,
                        "board_lane": "first_board",
                        "entry_kind": "sweep",
                        "action": "observe",
                    }
                ],
                "next_auction": [
                    {
                        "vt_symbol": "600001.SSE",
                        "board_level": 3,
                        "board_lane": "two_to_three",
                        "entry_kind": "next_session_watch",
                        "action": "observe",
                    }
                ],
            }
        },
    }

    result = attach_historical_evidence(
        snapshot,
        analog_index=analog_index,
        stock_d1_index={
            "600001.SSE": {
                "sample_count": 5,
                "win_count": 3,
                "win_rate": 60.0,
                "average_return_pct": 1.2,
            }
        },
    )

    first_board = result["recommendations"]["lanes"]["now"][0][
        "historical_evidence"
    ]
    assert first_board["historical_win_rate"] == 45.0
    assert first_board["d1_money_effect_win_rate"] == 60.0
    assert first_board["d1_money_effect_sample_count"] == 5
    assert first_board["seal_success_rate"] == 75.0
    assert first_board["seal_sample_count"] == 8
    assert first_board["stock_gene_sample_qualified"] is True
    assert first_board["smoothed_win_rate"] is not None
    assert (
        first_board["historical_win_rate_method"]
        == "same_stock_126d_seal_x_same_stock_first_board_d1_close_net_profit"
    )
    assert first_board["d1_exit_proxy"] == "next_close"
    relay = result["recommendations"]["lanes"]["next_auction"][0][
        "historical_evidence"
    ]
    assert "historical_win_rate" not in relay
    assert "d1_money_effect_win_rate" not in relay


def test_live_portfolio_does_not_promote_unselected_profitability_candidate() -> None:
    recommendations = {
        "lanes": {
            "now": [
                _live_signal(
                    "600001.SSE",
                    historical_win_rate=40.0,
                    change_pct=9.9,
                    portfolio_selected=True,
                ),
                _live_signal(
                    "600002.SSE",
                    historical_win_rate=60.0,
                    change_pct=8.8,
                    portfolio_selected=False,
                ),
                _live_signal(
                    "600003.SSE",
                    historical_win_rate=50.0,
                    change_pct=9.5,
                    portfolio_selected=True,
                ),
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    portfolio = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 16, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )

    assert [row["vt_symbol"] for row in portfolio] == [
        "600003.SSE",
        "600001.SSE",
    ]


def test_live_actionable_recommendations_ignore_portfolio_capacity() -> None:
    recommendations = {
        "lanes": {
            "now": [
                _live_signal(
                    "600001.SSE",
                    historical_win_rate=40.0,
                    change_pct=9.9,
                    portfolio_selected=True,
                ),
                _live_signal(
                    "600002.SSE",
                    historical_win_rate=60.0,
                    change_pct=8.8,
                    portfolio_selected=False,
                ),
                _live_signal(
                    "600003.SSE",
                    historical_win_rate=50.0,
                    change_pct=9.5,
                    portfolio_selected=True,
                ),
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    actionable = live_service._build_live_actionable_recommendations(
        recommendations,
        captured_at=datetime(2026, 7, 16, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )

    assert [row["vt_symbol"] for row in actionable] == [
        "600002.SSE",
        "600003.SSE",
        "600001.SSE",
    ]
    assert all(row["action"] == "buy_now" for row in actionable)


def test_live_risk_gate_publishes_unbounded_actionable_recommendations() -> None:
    signal = _live_signal(
        "600001.SSE",
        historical_win_rate=45.0,
        change_pct=9.2,
        portfolio_selected=False,
    )
    snapshot = {
        "captured_at": "2026-07-16T10:05:00+08:00",
        "recommendations": {
            "lanes": {"now": [signal], "tail": [], "next_auction": []},
        },
        "data_quality": {"snapshot_age_seconds": 5},
    }

    result = live_service._apply_live_risk_gates(
        snapshot,
        {
            "first_board": {
                "passed": True,
                "status": "validated",
                "reason": "测试通过",
                "summary": {},
            }
        },
    )

    recommendations = result["recommendations"]
    assert recommendations["portfolio"] == []
    assert [
        row["vt_symbol"]
        for row in recommendations["actionable_recommendations"]
    ] == ["600001.SSE"]


def test_live_actionable_uses_same_profitability_exclusion_as_backtest() -> None:
    vetoed = _live_signal(
        "600004.SSE",
        historical_win_rate=60.0,
        change_pct=9.7,
    )
    vetoed["action"] = "pass"
    vetoed["research_action"] = "buy_now"
    recommendations = {
        "lanes": {
            "now": [
                _live_signal(
                    "600001.SSE",
                    historical_win_rate=90.0,
                    change_pct=9.9,
                    d1_samples=4,
                ),
                _live_signal(
                    "600002.SSE",
                    historical_win_rate=29.9,
                    change_pct=9.8,
                ),
                _live_signal(
                    "600003.SSE",
                    historical_win_rate=30.0,
                    change_pct=9.0,
                ),
                vetoed,
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    portfolio = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 16, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )

    assert [row["vt_symbol"] for row in portfolio] == ["600003.SSE"]
    assert portfolio[0]["profitability_gate_passed"] is True
    assert portfolio[0]["profitability_gate_minimum_d1_samples"] == 5
    assert portfolio[0]["profitability_gate_minimum_combined_rate"] == 30.0
    actionable = live_service._build_live_actionable_recommendations(
        recommendations,
        captured_at=datetime(2026, 7, 16, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )
    assert [row["vt_symbol"] for row in actionable] == ["600003.SSE"]
    assert actionable[0]["profitability_gate_passed"] is True


def test_live_first_board_watchlist_uses_change_pct_as_second_key() -> None:
    recommendations = {
        "lanes": {
            "now": [
                _live_signal(
                    "600001.SSE",
                    action="observe",
                    historical_win_rate=50.0,
                    change_pct=8.8,
                ),
                _live_signal(
                    "600002.SSE",
                    action="observe",
                    historical_win_rate=50.0,
                    change_pct=9.3,
                ),
                _live_signal(
                    "600003.SSE",
                    action="observe",
                    historical_win_rate=55.0,
                    change_pct=8.0,
                ),
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    watchlist = live_service._build_live_watchlist(recommendations)

    assert [row["vt_symbol"] for row in watchlist] == [
        "600003.SSE",
        "600002.SSE",
        "600001.SSE",
    ]


def test_live_portfolio_prefers_relay_then_uses_first_board_joint_rate() -> None:
    recommendations = {
        "lanes": {
            "now": [
                _live_signal(
                    "600010.SSE",
                    lane="two_to_three",
                    historical_win_rate=10.0,
                    change_pct=9.0,
                ),
                _live_signal(
                    "600001.SSE",
                    historical_win_rate=45.0,
                    change_pct=9.8,
                ),
                _live_signal(
                    "600002.SSE",
                    historical_win_rate=55.0,
                    change_pct=8.8,
                ),
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    portfolio = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 16, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )

    assert [row["vt_symbol"] for row in portfolio] == [
        "600010.SSE",
        "600002.SSE",
    ]


def test_live_portfolio_uses_change_pct_after_equal_joint_rate() -> None:
    recommendations = {
        "lanes": {
            "now": [
                _live_signal(
                    "600001.SSE",
                    historical_win_rate=50.0,
                    change_pct=8.8,
                ),
                _live_signal(
                    "600002.SSE",
                    historical_win_rate=50.0,
                    change_pct=9.3,
                ),
                _live_signal(
                    "600003.SSE",
                    historical_win_rate=55.0,
                    change_pct=8.0,
                ),
            ],
            "tail": [],
            "next_auction": [],
        }
    }

    portfolio = live_service._build_live_portfolio(
        recommendations,
        captured_at=datetime(2026, 7, 16, 10, 5, tzinfo=SHANGHAI),
        snapshot_age_seconds=5,
    )

    assert [row["vt_symbol"] for row in portfolio] == [
        "600003.SSE",
        "600002.SSE",
    ]


def test_prior_only_ranking_report_compares_equal_daily_top_n() -> None:
    days = _ranking_replay_days()

    report = build_first_board_profitability_ranking_report(
        days,
        top_n=1,
        min_analogs=1,
    )

    assert report["status"] == "ready"
    assert report["mode"] == "prior_only_daily_candidate_ranking_proxy"
    assert report["baseline"]["trade_count"] == 1
    assert report["baseline"]["win_rate_pct"] == 0.0
    assert report["baseline"]["average_return_pct"] == -4.0
    assert report["profitability_ranking"]["trade_count"] == 1
    assert report["profitability_ranking"]["win_rate_pct"] == 100.0
    assert report["profitability_ranking"]["average_return_pct"] == 2.0
    assert report["delta"]["win_rate_pct_points"] == 100.0
    assert report["selections"]["baseline"][0]["vt_symbol"] == "600002.SSE"
    assert (
        report["selections"]["profitability_ranking"][0]["vt_symbol"]
        == "600001.SSE"
    )


def test_ranking_selection_cannot_read_same_day_outcomes() -> None:
    original = _ranking_replay_days()
    mutated = deepcopy(original)
    candidates = mutated[-1]["lane_portfolio"]["candidate_pool"]["first_board"]
    candidates[0]["outcome"].update(
        sealed=False,
        next_close_return_pct=-9.0,
    )
    candidates[1]["outcome"].update(
        sealed=True,
        next_close_return_pct=9.0,
    )

    original_report = build_first_board_profitability_ranking_report(
        original,
        top_n=1,
        min_analogs=1,
    )
    mutated_report = build_first_board_profitability_ranking_report(
        mutated,
        top_n=1,
        min_analogs=1,
    )

    assert original_report["selections"] == mutated_report["selections"]


def _signal(
    vt_symbol: str,
    *,
    lane: str = "first_board",
    historical_win_rate: float | None,
    change_pct: float | None,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "board_lane": lane,
        "change_pct": change_pct,
        "historical_evidence": {
            "historical_win_rate": historical_win_rate,
        },
    }


def _analog_candidate(
    result_date: str | None,
    *,
    sealed: bool,
    next_close_return_pct: float | None,
) -> dict[str, object]:
    return {
        "entry_mode": "sweep",
        "target_board": 1,
        "result_date": result_date,
        "known_at_signal": {
            "auction_gap_pct": 3.0,
            "prior_change_pct": 1.0,
            "prior_turnover_rate": 8.0,
            "prior_amount_ratio_5d": 1.2,
            "prior_market_phase": "repair",
        },
        "outcome": {
            "touched": True,
            "sealed": sealed,
            "next_open_return_pct": 1.0 if sealed else -3.0,
            "next_close_return_pct": next_close_return_pct,
        },
    }


def _stock_replay_day(
    trade_date: str,
    candidate: dict[str, object],
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "lane_portfolio": {"candidate_pool": {"first_board": [candidate]}},
    }


def _stock_event(
    vt_symbol: str,
    result_date: str,
    *,
    sealed: bool,
    return_pct: float,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "lane": "first_board",
        "result_date": result_date,
        "outcome": {
            "touched": True,
            "sealed": sealed,
            "next_close_return_pct": return_pct,
        },
    }


def _live_signal(
    vt_symbol: str,
    *,
    lane: str = "first_board",
    action: str = "buy_now",
    historical_win_rate: float,
    change_pct: float,
    portfolio_selected: bool = True,
    d1_samples: int = 5,
) -> dict[str, object]:
    last_price = round(10.0 * (1.0 + change_pct / 100.0), 2)
    return {
        "vt_symbol": vt_symbol,
        "name": vt_symbol,
        "board_level": 1 if lane == "first_board" else 3,
        "board_lane": lane,
        "state": "near_limit",
        "last_price": last_price,
        "limit_price": 11.0,
        "lane_decision": "eligible",
        "portfolio_selected": portfolio_selected,
        "action": action,
        "research_action": action,
        "signal_state": (
            "trigger_ready" if action == "buy_now" else "approaching_trigger"
        ),
        "blocking_scope": "none" if action == "buy_now" else "dynamic",
        "entry_kind": "sweep",
        "change_pct": change_pct,
        "historical_evidence": {
            "historical_win_rate": historical_win_rate,
            "d1_money_effect_sample_count": d1_samples,
            "tbox_score": 50.0,
            "smoothed_win_rate": 50.0,
        },
        "strategy_evidence": {"total_return_pct": 10.0},
        "leadership_score": 50.0,
    }


def _ranking_replay_days() -> list[dict[str, object]]:
    high_history = [
        _ranking_candidate(
            f"60010{index}.SSE",
            gap=3.0,
            result_date=f"2026-07-0{index + 1}",
            sealed=True,
            return_pct=2.0,
        )
        for index in range(2)
    ]
    low_history = [
        _ranking_candidate(
            "600200.SSE",
            gap=6.0,
            result_date="2026-07-03",
            sealed=True,
            return_pct=-2.0,
        ),
        _ranking_candidate(
            "600201.SSE",
            gap=6.0,
            result_date="2026-07-06",
            sealed=False,
            return_pct=-4.0,
        ),
    ]
    baseline_first = _ranking_candidate(
        "600002.SSE",
        gap=6.0,
        result_date="2026-07-13",
        sealed=False,
        return_pct=-4.0,
        pool_rank=1,
        signal_change_pct=9.8,
    )
    profitable_first = _ranking_candidate(
        "600001.SSE",
        gap=3.0,
        result_date="2026-07-13",
        sealed=True,
        return_pct=2.0,
        pool_rank=2,
        signal_change_pct=8.5,
    )
    return [
        {
            "trade_date": "2026-07-01",
            "lanes": {"sweep": [*high_history, *low_history]},
            "lane_portfolio": {"candidate_pool": {"first_board": []}},
        },
        {
            "trade_date": "2026-07-10",
            "validation_phase": "locked_holdout",
            "lanes": {"sweep": []},
            "lane_portfolio": {
                "candidate_pool": {
                    "first_board": [baseline_first, profitable_first],
                }
            },
        },
    ]


def _ranking_candidate(
    vt_symbol: str,
    *,
    gap: float,
    result_date: str,
    sealed: bool,
    return_pct: float,
    pool_rank: int = 1,
    signal_change_pct: float = 9.0,
) -> dict[str, object]:
    candidate = _analog_candidate(
        result_date,
        sealed=sealed,
        next_close_return_pct=return_pct,
    )
    candidate["vt_symbol"] = vt_symbol
    candidate["known_at_signal"]["auction_gap_pct"] = gap
    candidate.update(
        {
            "lane": "first_board",
            "decision": "eligible",
            "pool_rank": pool_rank,
            "signal_date": "2026-07-10",
            "signal_time": "10:05:00",
            "path_prefix": {"last_pct": signal_change_pct},
            "validation_phase": "locked_holdout",
        }
    )
    return candidate
