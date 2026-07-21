from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.forward_leader_identity import (
    FORWARD_LEADER_RANKING_VERSION,
)
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.forward_ma5_pullback import (
    FORWARD_MA5_CONTRACT_VERSION,
    ForwardMa5Inputs,
    build_forward_ma5_capture,
    evaluate_forward_ma5_outcomes,
)
from alphaagent.server.services.low_suction.leader_identity import LeaderIdentityMode

SHANGHAI = ZoneInfo("Asia/Shanghai")
MODES = tuple(mode.value for mode in LeaderIdentityMode)
ATTEMPTED_AT = datetime(2026, 6, 30, 19, 30, tzinfo=SHANGHAI)


def _bars() -> pd.DataFrame:
    dates = tuple(timestamp.date() for timestamp in pd.bdate_range("2026-05-01", periods=29))
    closes = [6.0 + index * 0.4 for index in range(20)]
    closes.extend([14.2, 13.7, 14.5, 14.0, 14.9, 14.3, 14.55, 14.7, 15.2])
    highs = [value + 0.08 for value in closes]
    lows = [value - 0.08 for value in closes]
    highs[20:] = [14.3, 13.9, 14.6, 14.2, 15.0, 14.6, 14.8, 14.9, 15.3]
    lows[20:] = [14.0, 13.5, 14.1, 13.85, 14.5, 14.2, 14.3, 14.4, 14.9]
    rows = []
    for index, trade_date in enumerate(dates):
        close = closes[index]
        rows.append(
            {
                "vt_symbol": "000001.SZSE",
                "trade_date": trade_date,
                "open_price": close,
                "high_price": highs[index],
                "low_price": lows[index],
                "close_price": close,
                "volume": 10_000_000.0 + index * 100_000.0,
                "turnover": 150_000_000.0,
                "change_pct": (
                    (close / closes[index - 1] - 1.0) * 100.0 if index else 0.0
                ),
                "source": "test.daily",
            }
        )
    return pd.DataFrame(rows)


def _calendar() -> tuple[date, ...]:
    return tuple(pd.to_datetime(_bars()["trade_date"]).dt.date)


def _signal_date() -> date:
    return _calendar()[26]


def _source_date() -> date:
    return _calendar()[25]


def _scopes(source_date: date, *, target_date: date | None, complete: bool = True) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_trade_date": source_date,
                "target_trade_date": target_date,
                "ranking_version": FORWARD_LEADER_RANKING_VERSION,
                "identity_mode": mode,
                "complete": complete,
                "status": "frozen_bound" if target_date else "frozen",
                "input_fingerprint": f"sha256:{mode}:scope",
                "selected_mode": None,
            }
            for mode in MODES
        ]
    )


def _rank_history(*, omit_target: date | None = None) -> pd.DataFrame:
    rows = []
    calendar = _calendar()
    signal_date = _signal_date()
    for mode in MODES:
        for target_date in calendar[20:27]:
            if target_date == omit_target:
                continue
            source_position = calendar.index(target_date) - 1
            rows.append(
                {
                    "source_trade_date": calendar[source_position],
                    "target_trade_date": target_date,
                    "ranking_version": FORWARD_LEADER_RANKING_VERSION,
                    "identity_mode": mode,
                    "sector_id": "BK_TEST",
                    "sector_name": "测试主升",
                    "vt_symbol": "000001.SZSE",
                    "rank": 1,
                    "is_top3": True,
                    "capacity_passed": True,
                    "cycle_start": calendar[20],
                    "input_fingerprint": f"sha256:{mode}:{target_date}",
                    "raw": {"stock_name": "测试龙头"},
                }
            )
        rows.append(
            {
                "source_trade_date": signal_date,
                "target_trade_date": None,
                "ranking_version": FORWARD_LEADER_RANKING_VERSION,
                "identity_mode": mode,
                "sector_id": "BK_TEST",
                "sector_name": "测试主升",
                "vt_symbol": "000002.SZSE",
                "rank": 1,
                "is_top3": True,
                "capacity_passed": True,
                "cycle_start": calendar[20],
                "input_fingerprint": f"sha256:{mode}:signal",
                "raw": {"stock_name": "当日龙头"},
            }
        )
    return pd.DataFrame(rows)


def _inputs() -> ForwardMa5Inputs:
    signal_date = _signal_date()
    source_date = _source_date()
    return ForwardMa5Inputs(
        source_trade_date=source_date,
        signal_trade_date=signal_date,
        attempted_at=ATTEMPTED_AT,
        prior_scopes=_scopes(source_date, target_date=signal_date),
        signal_scopes=_scopes(signal_date, target_date=None),
        rank_history=_rank_history(),
        stock_bars=_bars().loc[lambda frame: frame["trade_date"].le(signal_date)],
        stock_fund_flows=pd.DataFrame(
            [
                {
                    "vt_symbol": "000001.SZSE",
                    "trade_date": signal_date,
                    "period": "即时",
                    "main_net_inflow": 20_000_000.0,
                    "main_net_inflow_ratio": 2.5,
                    "source": "test.flow",
                    "updated_at": ATTEMPTED_AT - timedelta(minutes=10),
                }
            ]
        ),
        sector_fund_flow_snapshots=pd.DataFrame(
            [
                {
                    "sector_id": "BK_TEST",
                    "trade_date": signal_date,
                    "period": "即时",
                    "captured_at": ATTEMPTED_AT - timedelta(minutes=5),
                    "main_net_inflow": 100_000_000.0,
                    "main_net_inflow_ratio": 3.0,
                    "is_stale": False,
                    "source": "test.sector.flow",
                }
            ]
        ),
        market_timing_rows=pd.DataFrame(
            [
                {
                    "trade_date": signal_date,
                    "active_direction": "GOLD",
                    "danger_state": "NORMAL",
                    "known_at": ATTEMPTED_AT - timedelta(minutes=1),
                }
            ]
        ),
        completed_dates=_calendar()[:27],
        selected_mode=None,
    )


def test_candidate_emits_only_first_wave_three_ma5_stabilization() -> None:
    capture = build_forward_ma5_capture(_inputs())

    assert capture.contract_version == FORWARD_MA5_CONTRACT_VERSION
    assert capture.complete
    assert len(capture.rows) == 3
    assert {scope.signal_count for scope in capture.scopes} == {1}
    assert {row.identity_mode for row in capture.rows} == set(MODES)
    for row in capture.rows:
        assert row.signal_eligible is True
        assert row.current_wave_number == 3
        assert row.confirmed_higher_highs == 2
        assert row.support_line == "ma5"
        assert row.signal_trade_date == _signal_date()
        assert row.feature_cutoff_date == _signal_date()
        assert row.selected_mode_at_capture is None
        assert row.decision_reason == "eligible_forward_ma5_shadow"


def test_future_bars_cannot_change_candidate_or_fingerprint() -> None:
    original = build_forward_ma5_capture(_inputs())
    future = _bars().loc[lambda frame: frame["trade_date"].gt(_signal_date())].assign(
        high_price=999.0,
        close_price=998.0,
    )
    changed = build_forward_ma5_capture(
        replace(
            _inputs(),
            stock_bars=pd.concat([_inputs().stock_bars, future], ignore_index=True),
        )
    )

    assert changed.input_fingerprint == original.input_fingerprint
    assert changed.rows == original.rows


def test_incomplete_signal_day_main_rise_closes_all_modes() -> None:
    scopes = _inputs().signal_scopes.copy()
    scopes.loc[scopes.index[0], "complete"] = False

    capture = build_forward_ma5_capture(replace(_inputs(), signal_scopes=scopes))

    assert not capture.complete
    assert capture.rows == ()
    assert {scope.status for scope in capture.scopes} == {"blocked"}
    assert {scope.raw["blocking_reason"] for scope in capture.scopes} == {
        "signal_top3_scopes_not_complete"
    }


def test_rank_gap_resets_spell_and_prevents_old_wave_reuse() -> None:
    gap_date = _calendar()[23]
    capture = build_forward_ma5_capture(
        replace(_inputs(), rank_history=_rank_history(omit_target=gap_date))
    )

    assert capture.complete
    assert all(row.signal_eligible is False for row in capture.rows)
    assert {row.decision_reason for row in capture.rows} == {
        "fewer_than_two_confirmed_higher_highs"
    }


def test_missing_signal_stock_bar_is_an_explicit_non_signal() -> None:
    bars = _inputs().stock_bars.loc[
        ~_inputs().stock_bars["trade_date"].eq(_signal_date())
    ]

    capture = build_forward_ma5_capture(replace(_inputs(), stock_bars=bars))

    assert capture.complete
    assert len(capture.rows) == 3
    assert {row.signal_eligible for row in capture.rows} == {False}
    assert {row.decision_reason for row in capture.rows} == {
        "signal_stock_bar_unavailable"
    }


def test_first_stabilized_ma10_is_not_relabelled_as_ma5() -> None:
    bars = _inputs().stock_bars.copy()
    for index in range(20):
        close = 10.0 + index * 0.2
        bars.loc[bars.index[index], ["open_price", "close_price"]] = close
        bars.loc[bars.index[index], "high_price"] = close + 0.08
        bars.loc[bars.index[index], "low_price"] = close - 0.08

    capture = build_forward_ma5_capture(replace(_inputs(), stock_bars=bars))

    assert {row.support_line for row in capture.rows} == {"ma10"}
    assert {row.decision_reason for row in capture.rows} == {
        "first_stabilized_support_not_ma5"
    }


def test_diagnostics_never_change_signal_decision() -> None:
    original = build_forward_ma5_capture(_inputs())
    changed = build_forward_ma5_capture(
        replace(
            _inputs(),
            stock_fund_flows=_inputs().stock_fund_flows.assign(
                main_net_inflow=-999_000_000.0,
                main_net_inflow_ratio=-99.0,
            ),
            sector_fund_flow_snapshots=_inputs().sector_fund_flow_snapshots.assign(
                main_net_inflow=-999_000_000.0,
                main_net_inflow_ratio=-99.0,
            ),
            market_timing_rows=_inputs().market_timing_rows.assign(
                active_direction="SILVER",
                danger_state="DANGER",
            ),
        )
    )

    assert [row.signal_eligible for row in changed.rows] == [
        row.signal_eligible for row in original.rows
    ]
    assert {row.market_timing_direction for row in changed.rows} == {"SILVER"}
    assert {row.market_timing_danger_state for row in changed.rows} == {"DANGER"}


def test_outcome_uses_next_open_and_first_higher_high_close() -> None:
    capture = build_forward_ma5_capture(_inputs())
    candidates = pd.DataFrame([row.__dict__ for row in capture.rows])

    outcomes = evaluate_forward_ma5_outcomes(
        candidates,
        _bars(),
        completed_dates=_calendar(),
    )

    assert len(outcomes) == 3
    assert set(outcomes["status"]) == {"closed"}
    assert set(outcomes["entry_date"]) == {_calendar()[27]}
    assert set(outcomes["entry_proxy"]) == {"next_completed_session_open"}
    assert set(outcomes["exit_date"]) == {_calendar()[28]}
    assert set(outcomes["exit_reason"]) == {"reference_peak_rebroken"}
    assert set(outcomes["round_trip_cost_pct"]) == {0.2}


def test_entry_open_at_peak_is_terminal_rejection() -> None:
    capture = build_forward_ma5_capture(_inputs())
    candidates = pd.DataFrame([capture.rows[0].__dict__])
    bars = _bars()
    bars.loc[bars["trade_date"].eq(_calendar()[27]), "open_price"] = 15.0
    bars.loc[bars["trade_date"].eq(_calendar()[27]), "high_price"] = 15.1

    outcome = evaluate_forward_ma5_outcomes(
        candidates,
        bars,
        completed_dates=_calendar(),
    ).iloc[0]

    assert outcome["status"] == "opportunity_gone_at_entry"
    assert outcome["terminal"]
    assert pd.isna(outcome["net_return_pct"])


def test_second_close_below_ma20_exits_before_any_rebreak() -> None:
    capture = build_forward_ma5_capture(_inputs())
    candidates = pd.DataFrame([capture.rows[0].__dict__])
    bars = _bars()
    for position, close in ((27, 10.0), (28, 9.5)):
        bars.loc[bars.index[position], "open_price"] = close
        bars.loc[bars.index[position], "close_price"] = close
        bars.loc[bars.index[position], "high_price"] = close + 0.2
        bars.loc[bars.index[position], "low_price"] = close - 0.2

    outcome = evaluate_forward_ma5_outcomes(
        candidates,
        bars,
        completed_dates=_calendar(),
    ).iloc[0]

    assert outcome["status"] == "closed"
    assert outcome["exit_date"] == _calendar()[28]
    assert outcome["exit_reason"] == "second_consecutive_close_below_ma20"


def test_observation_boundary_right_censors_without_return_fallback() -> None:
    capture = build_forward_ma5_capture(_inputs())
    candidates = pd.DataFrame([capture.rows[0].__dict__])
    bars = _bars()
    bars = bars.loc[bars["trade_date"].le(_signal_date())].copy()
    next_dates = tuple(
        timestamp.date()
        for timestamp in pd.bdate_range(_signal_date(), periods=36)[1:]
    )
    additions = pd.DataFrame(
        [
            {
                "vt_symbol": "000001.SZSE",
                "trade_date": trade_date,
                "open_price": 14.6,
                "high_price": 14.9,
                "low_price": 14.4,
                "close_price": 14.6,
                "volume": 12_000_000.0,
                "turnover": 150_000_000.0,
                "change_pct": 0.0,
                "source": "test.daily",
            }
            for trade_date in next_dates
        ]
    )
    bars = pd.concat([bars, additions], ignore_index=True)
    completed = tuple(pd.to_datetime(bars["trade_date"]).dt.date)

    outcome = evaluate_forward_ma5_outcomes(
        candidates,
        bars,
        completed_dates=completed,
    ).iloc[0]

    assert outcome["status"] == "right_censored"
    assert outcome["terminal"]
    assert outcome["right_censored"]
    assert pd.isna(outcome["exit_price"])
    assert pd.isna(outcome["net_return_pct"])


def test_awaiting_entry_and_terminal_outcome_are_causal() -> None:
    capture = build_forward_ma5_capture(_inputs())
    candidates = pd.DataFrame([capture.rows[0].__dict__])
    through_signal = _bars().loc[lambda frame: frame["trade_date"].le(_signal_date())]

    awaiting = evaluate_forward_ma5_outcomes(
        candidates,
        through_signal,
        completed_dates=_calendar()[:27],
    ).iloc[0]
    closed = evaluate_forward_ma5_outcomes(
        candidates,
        _bars(),
        completed_dates=_calendar(),
    ).iloc[0]
    later = pd.concat(
        [
            _bars(),
            _bars().iloc[[-1]].assign(
                trade_date=_calendar()[-1] + timedelta(days=1),
                high_price=1_000.0,
                close_price=999.0,
            ),
        ],
        ignore_index=True,
    )
    closed_after_mutation = evaluate_forward_ma5_outcomes(
        candidates,
        later,
        completed_dates=(*_calendar(), _calendar()[-1] + timedelta(days=1)),
    ).iloc[0]

    assert awaiting["status"] == "awaiting_entry"
    assert not awaiting["terminal"]
    assert closed["terminal"]
    for field in ("entry_date", "entry_price", "exit_date", "exit_price", "net_return_pct"):
        assert closed_after_mutation[field] == closed[field]


def test_candidate_input_rejects_future_or_outcome_columns() -> None:
    with pytest.raises(ValueError, match="future or outcome"):
        build_forward_ma5_capture(
            replace(
                _inputs(),
                rank_history=_rank_history().assign(future_return_pct=10.0),
            )
        )


def test_forward_ma5_cli_has_no_threshold_overrides() -> None:
    run = build_parser().parse_args(
        ["v2-forward-ma5-shadow-run", "--as-of-date", "2026-07-17"]
    )
    report = build_parser().parse_args(
        ["v2-forward-ma5-shadow-report", "--format", "markdown"]
    )

    assert run.command == "v2-forward-ma5-shadow-run"
    assert run.as_of_date == date(2026, 7, 17)
    assert report.command == "v2-forward-ma5-shadow-report"
    assert report.format == "markdown"
    assert not hasattr(run, "pullback_pct")
    assert not hasattr(run, "approach_tolerance_pct")
