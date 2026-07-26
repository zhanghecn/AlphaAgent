from datetime import date
from inspect import getsource
from unittest.mock import patch

from alphaagent.server.services.limit_up import (
    cash_backtest,
    preboard_decision_service,
    preboard_decision_replay,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
)
from alphaagent.server.services.limit_up.preboard_live_minute_buffer import (
    LiveMinuteBuffer,
)
from alphaagent.server.services.limit_up.lane_research import (
    select_daily_lane_portfolio,
)
from alphaagent.server.services.limit_up.versions import (
    HISTORY_STRATEGY_VERSION,
    LIVE_STRATEGY_VERSION,
)


def test_preboard_work_uses_core_ab_and_keeps_execution_contract() -> None:
    assert HISTORY_STRATEGY_VERSION == "limit-up-core-ab-v1"
    assert LIVE_STRATEGY_VERSION == "limit-up-core-ab-v1"
    assert (
        scheduled_execution.SCHEDULED_EXECUTION_VERSION
        == "limit-up-core-ab-v1"
    )
    assert cash_backtest.ACCOUNT_EXECUTION_VERSION == "limit-up-core-ab-v1"
    assert scheduled_execution.MAX_POSITIONS == 2


def test_formal_touch_baseline_is_not_marked_preboard_executable() -> None:
    assert (
        preboard_decision_replay.FORMAL_BASELINE_ENTRY_CONTRACT
        == "formal_touch_event"
    )
    assert preboard_decision_replay.FORMAL_BASELINE_PREBOARD_EXECUTABLE is False
    assert (
        preboard_decision_replay.EXIT_CONTRACT
        == "d1_official_close_after_formal_costs"
    )


def test_rejected_preboard_model_remains_research_only() -> None:
    source = getsource(preboard_decision_service)

    assert "PREBOARD_DECISION_VERSION" in source
    result = preboard_decision_service.score_active_live_preboard_snapshot_safely(
        {},
        minute_buffer=LiveMinuteBuffer(),
    )

    assert result["status"] == "model_unavailable"
    assert result["probability_status"] == "model_unavailable"
    assert result["historical_promotion_status"] == (
        "insufficient_for_portfolio_promotion"
    )
    assert result["decision_version"] == PREBOARD_DECISION_VERSION
    assert result["model_fingerprint"] is None
    assert result["observation_count"] == 0
    assert result["preboard_candidates"] == []
    assert result["feature_rows"] == []
    assert result["action_saved"] == 0
    assert result["formal_strategy_changed"] is False


def test_formal_lane_selection_and_cash_account_snapshot_stay_unchanged() -> None:
    candidates = [
        _evaluated_candidate("600001.SSE", "first_board", rank_score=90.0),
        _evaluated_candidate("600002.SSE", "two_to_three", rank_score=80.0),
        _evaluated_candidate("600003.SSE", "high_board", rank_score=100.0),
    ]
    with patch(
        "alphaagent.server.services.limit_up.lane_research.evaluate_lane_candidate",
        side_effect=lambda candidate: dict(candidate),
    ):
        selected = select_daily_lane_portfolio(candidates, max_total=2)

    assert {
        "selection_policy": selected["selection_policy"],
        "selected": [
            (row["vt_symbol"], row["lane"], row["rank_score"])
            for row in selected["selected"]
        ],
        "selected_counts_by_lane": selected["selected_counts_by_lane"],
        "candidate_count": selected["candidate_count"],
    } == {
        "selection_policy": "diversified_then_ranked_v1",
        "selected": [
            ("600001.SSE", "first_board", 90.0),
            ("600002.SSE", "two_to_three", 80.0),
        ],
        "selected_counts_by_lane": {"first_board": 1, "two_to_three": 1},
        "candidate_count": 3,
    }

    account = cash_backtest.simulate_limit_up_account(
        signals=[
            _formal_signal(
                "600001.SSE",
                lane="first_board",
                signal_kind="first_touch",
                buy_time="10:08:00",
                limit_price=10.0,
            ),
            _formal_signal(
                "600002.SSE",
                lane="two_to_three",
                signal_kind="auction",
                buy_time="09:25:00",
                limit_price=11.0,
            ),
        ],
        bars=[
            _bar("600001.SSE", "2026-01-02", 10.0),
            _bar("600001.SSE", "2026-01-05", 11.0),
            _bar("600002.SSE", "2026-01-02", 10.0),
            _bar("600002.SSE", "2026-01-05", 9.5),
        ],
        trade_dates=[date(2026, 1, 2), date(2026, 1, 5)],
        exit_mode="next_close",
        config=cash_backtest.CashBacktestConfig(
            initial_cash=100_000,
            max_positions=2,
        ),
    )

    summary = account["execution_summary"]
    assert {
        key: summary[key]
        for key in (
            "filled_count",
            "trade_count",
            "open_position_count",
            "win_count",
            "win_rate",
            "total_return_pct",
            "max_drawdown_pct",
            "profit_factor",
            "total_fees",
            "final_equity",
        )
    } == {
        "filled_count": 2,
        "trade_count": 2,
        "open_position_count": 0,
        "win_count": 1,
        "win_rate": 50.0,
        "total_return_pct": 2.2866,
        "max_drawdown_pct": -0.0797,
        "profit_factor": 1.88,
        "total_fees": 112.8784,
        "final_equity": 102_286.5716,
    }
    assert [
        (
            row["vt_symbol"],
            row["lane"],
            row["buy_time"],
            row["sell_time"],
            round(float(row["return_pct"]), 4),
        )
        for row in account["executed_trades"]
    ] == [
        ("600002.SSE", "two_to_three", "09:25:00", "15:00:00", -5.2960),
        ("600001.SSE", "first_board", "10:08:00", "15:00:00", 9.7670),
    ]


def _evaluated_candidate(
    symbol: str,
    lane: str,
    *,
    rank_score: float,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "lane": lane,
        "decision": "eligible",
        "industry_id": symbol,
        "rank_score": rank_score,
        "two_to_three_quality_tier": "A" if lane == "two_to_three" else None,
    }


def _formal_signal(
    symbol: str,
    *,
    lane: str,
    signal_kind: str,
    buy_time: str,
    limit_price: float,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": symbol,
        "lane": lane,
        "signal_kind": signal_kind,
        "entry_date": "2026-01-02",
        "signal_date": "2026-01-02",
        "result_date": "2026-01-05",
        "buy_time": buy_time,
        "entry_price": 10.0,
        "limit_price": limit_price,
        "rank_score": 80.0,
        "lane_rank": 1,
        "outcome": {"entry_day_close_price": 10.0},
    }


def _bar(symbol: str, trade_date: str, close_price: float) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "trade_date": trade_date,
        "open_price": close_price,
        "high_price": close_price,
        "low_price": close_price,
        "close_price": close_price,
    }
