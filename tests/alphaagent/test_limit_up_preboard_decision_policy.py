from __future__ import annotations

from datetime import date, datetime

from alphaagent.server.services.limit_up import preboard_decision_model
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    PreboardExecutionMode,
    PreboardPolicyThresholds,
    PreboardState,
)
from alphaagent.server.services.limit_up.preboard_decision_policy import (
    can_compete_for_action,
    evaluate_preboard_decisions,
    preboard_action_sort_key,
    select_preboard_decisions,
)


def test_three_percent_only_observes_after_quality_gate() -> None:
    ordinary = _row("600001.SSE", "09:55:00", gain=3.1, quality=False)
    qualified = _row(
        "600002.SSE",
        "09:55:00",
        gain=3.1,
        touch_3m=0.20,
        eventual=0.40,
    )

    decisions = select_preboard_decisions([ordinary, qualified], _thresholds())

    assert [row["preboard_state"] for row in decisions] == [
        PreboardState.REJECTED,
        PreboardState.OBSERVE,
    ]
    assert all(row["daily_slot"] is None for row in decisions)


def test_high_probability_outside_entry_window_prepares_without_occupying_slot() -> None:
    row = _row("600001.SSE", "09:58:00", gain=6.0)
    row["entry_window_passed"] = False
    row["execution_environment_passed"] = False

    decision = select_preboard_decisions([row], _thresholds())[0]

    assert decision["preboard_state"] == PreboardState.PREPARE
    assert decision["daily_slot"] is None


def test_formal_action_and_portfolio_selection_are_not_action_requirements() -> None:
    row = _row("600001.SSE", "10:05:00", gain=6.0)
    row.update(action="observe", portfolio_selected=False)

    decision = select_preboard_decisions([row], _thresholds())[0]

    assert can_compete_for_action(row, _thresholds()) is True
    assert decision["preboard_state"] == PreboardState.ACTIONABLE
    assert decision["daily_slot"] == 1
    assert decision["policy_version"] == PREBOARD_DECISION_VERSION
    assert decision["execution_mode"] == "shadow"
    assert decision["actionable"] is False


def test_same_minute_uses_d1_return_then_d1_win_before_touch_probability() -> None:
    rows = [
        _row(
            "600001.SSE",
            "10:15:00",
            expected_return=1.0,
            d1_win=0.80,
            touch_3m=0.95,
        ),
        _row(
            "600002.SSE",
            "10:15:00",
            expected_return=2.0,
            d1_win=0.65,
            touch_3m=0.70,
        ),
        _row(
            "600003.SSE",
            "10:15:00",
            expected_return=1.0,
            d1_win=0.85,
            touch_3m=0.70,
        ),
    ]

    decisions = select_preboard_decisions(rows, _thresholds())
    actions = [
        row for row in decisions if row["preboard_state"] == PreboardState.ACTIONABLE
    ]

    assert [row["vt_symbol"] for row in actions] == ["600002.SSE", "600003.SSE"]
    assert [row["daily_slot"] for row in actions] == [1, 2]


def test_eight_percent_high_d1_quality_outranks_nine_percent_low_quality() -> None:
    high_quality = _row(
        "600001.SSE",
        "10:15:00",
        gain=8.0,
        expected_return=1.8,
        d1_win=0.72,
    )
    low_quality = _row(
        "600002.SSE",
        "10:15:00",
        gain=9.0,
        expected_return=0.4,
        d1_win=0.58,
        touch_3m=0.95,
    )

    assert preboard_action_sort_key(high_quality) < preboard_action_sort_key(
        low_quality
    )


def test_false_positive_occupies_slot_and_later_strong_stock_cannot_replace_it() -> None:
    prior = _row("600001.SSE", "10:01:00", expected_return=0.5)
    later = _row("600002.SSE", "10:05:00", expected_return=3.0)
    relay = {
        "trade_date": "2026-07-20",
        "vt_symbol": "600099.SSE",
        "daily_slot": 1,
        "preboard_state": PreboardState.ACTIONABLE,
        "board_lane": "two_to_three",
    }

    decisions = select_preboard_decisions(
        [prior, later],
        _thresholds(),
        prior_actions=[relay],
    )
    actions = [
        row for row in decisions if row["preboard_state"] == PreboardState.ACTIONABLE
    ]

    assert [(row["vt_symbol"], row["daily_slot"]) for row in actions] == [
        ("600001.SSE", 2)
    ]
    later_decision = next(row for row in decisions if row["vt_symbol"] == "600002.SSE")
    assert later_decision["preboard_state"] == PreboardState.PREPARE


def test_touched_quote_is_missed_and_never_actionable() -> None:
    touched = _row("600001.SSE", "10:05:00")
    touched["last_price"] = touched["limit_price"]
    sealed = _row("600002.SSE", "10:05:00")
    sealed["state"] = "sealed"

    decisions = select_preboard_decisions([touched, sealed], _thresholds())

    assert [row["preboard_state"] for row in decisions] == [
        PreboardState.MISSED,
        PreboardState.MISSED,
    ]
    assert all(row["daily_slot"] is None for row in decisions)


def test_missing_prior_or_failed_environment_cannot_act() -> None:
    missing_prior = _row("600001.SSE", "10:05:00")
    missing_prior["historical_prior_status"] = "incomplete"
    environment_failed = _row("600002.SSE", "10:05:00")
    environment_failed["execution_environment_passed"] = False

    decisions = select_preboard_decisions(
        [missing_prior, environment_failed],
        _thresholds(),
    )

    assert all(row["preboard_state"] != PreboardState.ACTIONABLE for row in decisions)


def test_shared_decision_entry_fails_closed_without_promoted_policy() -> None:
    qualified = _row("600001.SSE", "10:05:00", gain=6.0)
    touched = _row("600002.SSE", "10:05:00", gain=8.0)
    touched["last_price"] = touched["limit_price"]
    ordinary = _row("600003.SSE", "10:05:00", gain=4.0, quality=False)

    decisions = evaluate_preboard_decisions(
        [qualified, touched, ordinary],
        model_bundle=None,
        thresholds=None,
    )

    assert PREBOARD_DECISION_VERSION == "limit-up-preboard-decision-v1"
    assert [row["preboard_state"] for row in decisions] == [
        PreboardState.OBSERVE,
        PreboardState.MISSED,
        PreboardState.REJECTED,
    ]
    assert all(row["probability_status"] == "model_unavailable" for row in decisions)
    assert all(row["touch_probability_3m"] is None for row in decisions)
    assert all(row["eventual_touch_probability"] is None for row in decisions)
    assert all(row["daily_slot"] is None for row in decisions)
    assert all(row["policy_fingerprint"] is None for row in decisions)


def test_ready_probabilities_survive_without_action_thresholds(monkeypatch) -> None:
    row = _row("600001.SSE", "10:05:00", gain=6.0)
    monkeypatch.setattr(
        preboard_decision_model,
        "score_preboard_rows",
        lambda _bundle, rows: [dict(value) for value in rows],
    )

    decisions = evaluate_preboard_decisions(
        [row],
        model_bundle=object(),
        thresholds=None,
        execution_mode=PreboardExecutionMode.RESEARCH_ONLY,
    )

    decision = decisions[0]
    assert decision["decision_state"] == "observe"
    assert decision["execution_mode"] == "research_only"
    assert decision["touch_probability_3m"] == 0.75
    assert decision["eventual_touch_probability"] == 0.85
    assert decision["actionable"] is False


def test_later_rows_for_same_stock_do_not_create_second_action() -> None:
    rows = [
        _row("600001.SSE", "10:05:00", expected_return=1.0),
        _row("600001.SSE", "10:06:00", expected_return=2.0),
    ]

    decisions = select_preboard_decisions(rows, _thresholds())

    assert sum(
        row["preboard_state"] == PreboardState.ACTIONABLE for row in decisions
    ) == 1


def _thresholds() -> PreboardPolicyThresholds:
    return PreboardPolicyThresholds(
        minimum_touch_probability_3m=0.60,
        minimum_eventual_touch_probability=0.70,
        calibrated_dates=(date(2026, 7, 1),),
        fingerprint="sha256:thresholds",
    )


def _row(
    symbol: str,
    signal_time: str,
    *,
    gain: float = 6.0,
    quality: bool = True,
    expected_return: float = 1.0,
    d1_win: float = 0.70,
    touch_3m: float = 0.75,
    eventual: float = 0.85,
) -> dict[str, object]:
    decision_at = datetime.fromisoformat(f"2026-07-20T{signal_time}")
    last_price = 10.0 * (1.0 + gain / 100.0)
    return {
        "trade_date": "2026-07-20",
        "signal_date": "2026-07-20",
        "decision_at": decision_at.isoformat(),
        "vt_symbol": symbol,
        "board_lane": "first_board",
        "state": "near_limit",
        "change_pct": gain,
        "last_price": last_price,
        "limit_price": 11.0,
        "quality_gate_passed": quality,
        "preparation_environment_passed": True,
        "execution_environment_passed": True,
        "entry_window_passed": True,
        "profitability_gate_passed": True,
        "historical_prior_status": "ready",
        "probability_status": "ready",
        "touch_probability_3m": touch_3m,
        "eventual_touch_probability": eventual,
        "expected_d1_net_return_pct": expected_return,
        "d1_win_probability": d1_win,
        "seal_probability_given_touch": 0.75,
        "d1_win_probability_given_seal": 0.65,
        "lane_support_score": 60.0,
        "action": "observe",
        "portfolio_selected": False,
    }
