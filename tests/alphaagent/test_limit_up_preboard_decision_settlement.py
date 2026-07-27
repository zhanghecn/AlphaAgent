from __future__ import annotations

from datetime import datetime, timedelta

from alphaagent.server.services.limit_up.preboard_decision_settlement import (
    build_action_intraday_outcomes,
    build_d1_outcome,
    build_touch_labels,
)


def test_touch_labels_join_only_after_frozen_decision_time() -> None:
    decision_at = datetime(2026, 7, 21, 10, 5)
    rows = [
        {
            "frame_id": 100,
            "vt_symbol": "600001.SSE",
            "decision_at": decision_at,
            "label_status": "pending",
        },
        {
            "frame_id": 101,
            "vt_symbol": "600002.SSE",
            "decision_at": decision_at,
            "label_status": "pending",
        },
    ]
    observations = [
        {
            "frame_id": 99,
            "vt_symbol": "600001.SSE",
            "captured_at": decision_at - timedelta(seconds=5),
            "formal_action": "buy_now",
        },
        {
            "frame_id": 110,
            "vt_symbol": "600001.SSE",
            "captured_at": decision_at + timedelta(minutes=2),
            "formal_action": "buy_now",
        },
    ]

    labels = build_touch_labels(rows, observations, scope_complete=True)

    assert labels[(100, "600001.SSE")] == {
        "label_status": "known",
        "formal_touch_within_3m": True,
        "eventual_formal_touch": True,
    }
    assert labels[(101, "600002.SSE")] == {
        "label_status": "known",
        "formal_touch_within_3m": False,
        "eventual_formal_touch": False,
    }


def test_incomplete_scope_never_turns_missing_frames_into_negative_labels() -> None:
    labels = build_touch_labels(
        [
            {
                "frame_id": 100,
                "vt_symbol": "600001.SSE",
                "decision_at": datetime(2026, 7, 21, 10, 5),
            }
        ],
        [],
        scope_complete=False,
    )

    assert labels[(100, "600001.SSE")] == {
        "label_status": "incomplete_scope",
        "formal_touch_within_3m": None,
        "eventual_formal_touch": None,
    }


def test_action_fill_uses_first_new_strictly_below_limit_quote() -> None:
    decision_at = datetime.fromisoformat("2026-07-21T10:05:00+08:00")
    outcomes = build_action_intraday_outcomes(
        {
            "contract_version": "limit-up-preboard-decision-v2",
            "captured_at": decision_at,
            "vt_symbol": "600001.SSE",
            "limit_price": 11.0,
        },
        [
            {
                "frame_id": 101,
                "vt_symbol": "600001.SSE",
                "captured_at": decision_at + timedelta(seconds=10),
                "quote_observed_at": decision_at - timedelta(seconds=1),
                "last_price": 10.7,
                "capture_state": "near_limit",
                "formal_action": "pass",
            },
            {
                "frame_id": 102,
                "vt_symbol": "600001.SSE",
                "captured_at": decision_at + timedelta(seconds=20),
                "quote_observed_at": decision_at + timedelta(seconds=20),
                "last_price": 11.0,
                "capture_state": "sealed",
                "formal_action": "buy_now",
            },
            {
                "frame_id": 103,
                "vt_symbol": "600001.SSE",
                "captured_at": decision_at + timedelta(seconds=30),
                "quote_observed_at": decision_at + timedelta(seconds=30),
                "last_price": 10.9,
                "capture_state": "near_limit",
                "formal_action": "pass",
            },
        ],
        daily_bar={"high_price": 11.0, "close_price": 11.0},
        scope_complete=True,
    )

    assert outcomes["fill"]["fill_price"] == 10.9
    assert outcomes["fill"]["fill_at"] == decision_at + timedelta(seconds=30)
    assert outcomes["formal_touch"]["formal_identity_matched"] is True
    assert outcomes["physical_touch"] == {
        "physical_touch_status": "touched",
        "physical_touch_at": decision_at + timedelta(seconds=20),
        "final_sealed": True,
    }


def test_incomplete_action_scope_keeps_all_stages_pending() -> None:
    assert (
        build_action_intraday_outcomes(
            {
                "captured_at": datetime(2026, 7, 21, 10, 5),
                "vt_symbol": "600001.SSE",
                "limit_price": 11.0,
            },
            [],
            daily_bar=None,
            scope_complete=False,
        )
        == {}
    )


def test_d1_outcome_uses_official_close_and_formal_cost_model() -> None:
    outcome = build_d1_outcome(
        {
            "fill_status": "filled",
            "fill_price": 10.0,
            "limit_price": 11.0,
        },
        daily_bar={"trade_date": "2026-07-22", "close_price": 10.5},
        expected_d1_trade_date=datetime(2026, 7, 22).date(),
    )

    assert outcome is not None
    assert outcome["d1_status"] == "closed"
    assert outcome["gross_return_pct"] == 5.0
    assert outcome["net_return_pct"] < outcome["gross_return_pct"]
    assert outcome["double_cost_net_return_pct"] < outcome["net_return_pct"]
