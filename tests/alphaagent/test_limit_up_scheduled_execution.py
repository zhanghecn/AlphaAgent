from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import scheduled_execution


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_additive_concept_execution_contract_is_frozen() -> None:
    assert scheduled_execution.SCHEDULED_EXECUTION_VERSION == "limit-up-core-abc-v1"
    assert scheduled_execution.EXIT_MODE == "next_close"
    assert scheduled_execution.RULE_FREEZE_DATE == date(2026, 7, 15)


def test_first_board_profitability_gate_accepts_exact_boundary() -> None:
    decision = scheduled_execution.first_board_profitability_gate(
        {
            "lane": "first_board",
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 30.0,
        }
    )

    assert decision["profitability_gate_passed"] is True
    assert decision["profitability_gate_reason"] == "qualified"
    assert decision["profitability_gate_minimum_d1_samples"] == 5
    assert decision["profitability_gate_minimum_combined_rate"] == 30.0


def test_first_board_profitability_gate_rejects_weak_or_missing_evidence() -> None:
    insufficient = scheduled_execution.first_board_profitability_gate(
        {
            "lane": "first_board",
            "stock_d1_sample_count": 4,
            "stock_gene_combined_win_rate": 90.0,
        }
    )
    weak = scheduled_execution.first_board_profitability_gate(
        {
            "lane": "first_board",
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 29.9999,
        }
    )
    unavailable = scheduled_execution.first_board_profitability_gate(
        {
            "lane": "first_board",
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": None,
        }
    )

    assert insufficient["profitability_gate_reason"] == (
        "same_stock_d1_samples_below_5"
    )
    assert weak["profitability_gate_reason"] == (
        "same_stock_joint_rate_below_30"
    )
    assert unavailable["profitability_gate_reason"] == (
        "same_stock_joint_rate_unavailable"
    )
    assert not any(
        decision["profitability_gate_passed"]
        for decision in (insufficient, weak, unavailable)
    )


def test_profitability_gate_reads_live_evidence_and_bypasses_two_to_three() -> None:
    live = scheduled_execution.first_board_profitability_gate(
        {
            "board_lane": "first_board",
            "historical_evidence": {
                "d1_money_effect_sample_count": 6,
                "historical_win_rate": 35.0,
            },
        }
    )
    relay = scheduled_execution.first_board_profitability_gate(
        {
            "lane": "two_to_three",
            "historical_evidence": {},
        }
    )

    assert live["profitability_gate_passed"] is True
    assert live["profitability_gate_sample_count"] == 6
    assert live["profitability_gate_combined_rate"] == 35.0
    assert relay["profitability_gate_applies"] is False
    assert relay["profitability_gate_passed"] is True
    assert relay["profitability_gate_reason"] == "not_first_board"


def test_profitability_gate_recognizes_first_board_from_board_level() -> None:
    decision = scheduled_execution.first_board_profitability_gate(
        {
            "board_level": 1,
            "historical_evidence": {
                "d1_money_effect_sample_count": 4,
                "historical_win_rate": 90.0,
            },
        }
    )

    assert decision["profitability_gate_applies"] is True
    assert decision["profitability_gate_passed"] is False
    assert decision["profitability_gate_reason"] == (
        "same_stock_d1_samples_below_5"
    )


def test_filter_profitability_orders_keeps_order_and_reports_rejections() -> None:
    selected, audit = scheduled_execution.filter_profitability_qualified_orders(
        [
            {
                "vt_symbol": "600001.SSE",
                "lane": "first_board",
                "stock_d1_sample_count": 4,
                "stock_gene_combined_win_rate": 60.0,
            },
            {
                "vt_symbol": "600002.SSE",
                "lane": "two_to_three",
            },
            {
                "vt_symbol": "600003.SSE",
                "lane": "first_board",
                "stock_d1_sample_count": 5,
                "stock_gene_combined_win_rate": 30.0,
            },
        ]
    )

    assert [row["vt_symbol"] for row in selected] == [
        "600002.SSE",
        "600003.SSE",
    ]
    assert audit["input_count"] == 3
    assert audit["selected_count"] == 2
    assert audit["excluded_count"] == 1
    assert audit["reason_counts"] == {
        "not_first_board": 1,
        "qualified": 1,
        "same_stock_d1_samples_below_5": 1,
    }


def _candidate(
    vt_symbol: str,
    buy_time: str,
    *,
    decision: str = "eligible",
    lane: str = "first_board",
    rank_score: float = 60.0,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "name": vt_symbol,
        "lane": lane,
        "decision": decision,
        "buy_time": buy_time,
        "signal_time": buy_time,
        "entry_date": "2026-04-10",
        "signal_date": "2026-04-10",
        "result_date": "2026-04-13",
        "entry_price": 10.0,
        "limit_price": 10.0,
        "rank_score": rank_score,
        "pool_rank": 1,
        "industry_id": "BK001",
    }


def _history_day(
    *,
    candidate_pool: list[dict[str, object]],
    selected: list[dict[str, object]] | None = None,
    trade_date: str = "2026-04-10",
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "validation_phase": "locked_holdout",
        "lane_portfolio": {
            "candidate_pool": {
                "first_board": candidate_pool,
                "one_to_two": [],
                "two_to_three": [],
                "high_board": [],
            },
            "selected": selected or [],
        },
    }


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 7, 14, hour, minute, second, tzinfo=SHANGHAI)


def test_scheduled_entry_window_boundaries() -> None:
    assert scheduled_execution.is_entry_time("09:59:59") is False
    assert scheduled_execution.is_entry_time("10:00:00") is True
    assert scheduled_execution.is_entry_time("11:29:59") is True
    assert scheduled_execution.is_entry_time("11:30:00") is False
    assert scheduled_execution.is_entry_time("12:59:59") is False
    assert scheduled_execution.is_entry_time("13:00:00") is True
    assert scheduled_execution.is_entry_time("13:15:00") is True
    assert scheduled_execution.is_entry_time("14:29:59") is True
    assert scheduled_execution.is_entry_time("14:30:00") is False


def test_relay_trigger_uses_first_touch_inside_shared_window() -> None:
    result = scheduled_execution.resolve_relay_entry_trigger("10:12:03", [])

    assert result == {
        "status": "ready",
        "signal_time": "10:12:03",
        "signal_kind": "first_touch",
        "reason": None,
    }


def test_relay_trigger_requires_path_for_pre_ten_reseal() -> None:
    result = scheduled_execution.resolve_relay_entry_trigger("09:35:00", [])

    assert result == {
        "status": "missing_reseal_path",
        "signal_time": None,
        "signal_kind": None,
        "reason": "pre_ten_touch_without_reseal_path",
    }


def test_relay_trigger_uses_first_observable_window_reseal() -> None:
    path = [0.0] * 80
    path[2] = 9.8   # 09:36 first touch
    path[3] = 8.8   # 09:39 break
    path[11] = 9.8  # 10:03 reseal

    result = scheduled_execution.resolve_relay_entry_trigger("09:36:00", path)

    assert result == {
        "status": "ready",
        "signal_time": "10:03:00",
        "signal_kind": "reseal",
        "reason": None,
    }


def test_execution_clock_uses_five_minute_reminders_and_fixed_exit() -> None:
    first_reminder = scheduled_execution.execution_clock(_at(9, 55))
    assert first_reminder["state"] == "entry_reminder"
    assert first_reminder["message"] == "买入窗口将在 10:00 开始"

    first_window = scheduled_execution.execution_clock(_at(10, 0))
    assert first_window["entry_allowed"] is True
    assert first_window["message"] == "连续评估 10:00-11:30"

    morning = scheduled_execution.execution_clock(_at(10, 20))
    assert morning["entry_allowed"] is True
    assert morning["message"] == "连续评估 10:00-11:30"

    lunch = scheduled_execution.execution_clock(_at(12, 0))
    assert lunch["entry_allowed"] is False
    assert lunch["message"] == "午间休市，13:00恢复连续评估"

    afternoon = scheduled_execution.execution_clock(_at(13, 0))
    assert afternoon["entry_allowed"] is True
    assert afternoon["message"] == "连续评估 13:00-14:30"

    second_window = scheduled_execution.execution_clock(_at(14, 29, 59))
    assert second_window["entry_allowed"] is True
    assert second_window["message"] == "连续评估 13:00-14:30"

    wait_close = scheduled_execution.execution_clock(_at(14, 30))
    assert wait_close["state"] == "waiting_close"
    assert wait_close["entry_allowed"] is False
    assert wait_close["message"] == "买入窗口已结束，15:00执行D+1收盘卖出"

    sell_reminder = scheduled_execution.execution_clock(_at(14, 55))
    assert sell_reminder["state"] == "exit_reminder"
    assert sell_reminder["entry_allowed"] is False
    assert sell_reminder["message"] == "准备按官方收盘价卖出D+1持仓"

    sell_time = scheduled_execution.execution_clock(_at(15, 0))
    assert sell_time["state"] == "exit_time"
    assert sell_time["message"] == "D+1收盘卖出已结束"


def test_extract_scheduled_orders_uses_complete_pool_not_end_of_day_selected() -> None:
    visible = _candidate("600001.SSE", "10:05:00")
    future_winner = _candidate("600999.SSE", "10:06:00", rank_score=99)
    rows = [_history_day(candidate_pool=[visible], selected=[future_winner])]

    orders = scheduled_execution.extract_scheduled_orders(rows)

    assert [row["vt_symbol"] for row in orders] == ["600001.SSE"]
    assert orders[0]["candidate_source"] == "complete_first_board_candidate_pool"


def test_extract_scheduled_orders_never_reads_preboard_observations() -> None:
    preboard = _candidate("600999.SSE", "10:05:00")
    day = _history_day(candidate_pool=[])
    day["preboard_candidates"] = [preboard]

    orders = scheduled_execution.extract_scheduled_orders([day])

    assert orders == []


def test_default_product_orders_include_first_board_and_two_to_three() -> None:
    first_board = _candidate("600001.SSE", "10:06:00")
    two_to_three = {
        **_candidate("600002.SSE", "10:06:00", lane="two_to_three"),
        "relay_trigger_status": "ready",
        "signal_kind": "first_touch",
    }
    high_board = {
        **_candidate("600003.SSE", "10:06:00", lane="high_board"),
        "relay_trigger_status": "ready",
        "signal_kind": "first_touch",
    }
    day = _history_day(candidate_pool=[first_board])
    pools = day["lane_portfolio"]["candidate_pool"]
    pools["two_to_three"] = [two_to_three]
    pools["high_board"] = [high_board]

    orders = scheduled_execution.extract_scheduled_orders([day])

    assert [(row["lane"], row["vt_symbol"]) for row in orders] == [
        ("two_to_three", "600002.SSE"),
        ("first_board", "600001.SSE"),
    ]


def test_extract_scheduled_orders_filters_lane_decision_window_and_duplicates() -> None:
    rows = [
        _history_day(
            candidate_pool=[
                _candidate("600001.SSE", "10:05:00"),
                _candidate("600001.SSE", "10:06:00", rank_score=90),
                _candidate("600002.SSE", "11:30:00"),
                _candidate("600003.SSE", "10:35:00", decision="blocked"),
                _candidate("600004.SSE", "10:40:00", lane="one_to_two"),
                _candidate("600005.SSE", "13:20:00"),
                _candidate("600006.SSE", "13:35:00"),
            ]
        )
    ]

    orders = scheduled_execution.extract_scheduled_orders(rows)

    assert [(row["vt_symbol"], row["buy_time"]) for row in orders] == [
        ("600001.SSE", "10:05:00"),
        ("600005.SSE", "13:20:00"),
        ("600006.SSE", "13:35:00"),
    ]


def test_extract_scheduled_orders_ignores_final_board_outcome() -> None:
    candidates = [
        {
            **_candidate("600001.SSE", "10:05:00", rank_score=61),
            "outcome": {"touched": True, "sealed": True},
        },
        {
            **_candidate("600002.SSE", "10:08:00", rank_score=60),
            "outcome": {"touched": True, "sealed": False},
        },
    ]
    flipped = [
        {
            **candidate,
            "outcome": {
                "touched": not bool(candidate["outcome"]["touched"]),
                "sealed": not bool(candidate["outcome"]["sealed"]),
            },
        }
        for candidate in candidates
    ]

    baseline = scheduled_execution.extract_scheduled_orders(
        [_history_day(candidate_pool=candidates)]
    )
    changed = scheduled_execution.extract_scheduled_orders(
        [_history_day(candidate_pool=flipped)]
    )

    selection_fields = ("vt_symbol", "buy_time", "rank_score", "pool_rank")
    assert [tuple(row[field] for field in selection_fields) for row in baseline] == [
        tuple(row[field] for field in selection_fields) for row in changed
    ]


def test_scheduled_position_policy_is_two_half_positions() -> None:
    assert scheduled_execution.MAX_POSITIONS == 2
    assert scheduled_execution.TARGET_POSITION_PCT == 50.0
    assert scheduled_execution.PRODUCT_EXECUTION_LANES == (
        "first_board",
        "two_to_three",
    )
    assert scheduled_execution.ENTRY_WINDOWS == (
        ("10:00:00", "11:30:00"),
        ("13:00:00", "14:30:00"),
    )
    assert scheduled_execution.ENTRY_WINDOW_LABELS == (
        "10:00-11:30",
        "13:00-14:30",
    )
    assert scheduled_execution.ENTRY_CUTOFF_TIME == time(14, 30)
    assert scheduled_execution.ENTRY_CUTOFF_LABEL == "14:30"
    assert scheduled_execution.EXIT_MODE == "next_close"
    assert scheduled_execution.EXIT_TIME == "15:00:00"
    assert scheduled_execution.RESEARCH_SAMPLE_START == date(2026, 1, 16)
    assert scheduled_execution.VALIDATION_START == date(2026, 4, 14)


def test_next_session_clock_is_available_after_close_without_a_stock_pick() -> None:
    clock = scheduled_execution.next_session_execution_clock()

    assert clock["state"] == "next_session_wait"
    assert clock["entry_allowed"] is False
    assert clock["message"] == "下一交易日09:55提醒，10:00开始连续盘中评估"
    assert clock["entry_windows"] == ["10:00-11:30", "13:00-14:30"]
    assert clock["exit_time"] == "15:00"
