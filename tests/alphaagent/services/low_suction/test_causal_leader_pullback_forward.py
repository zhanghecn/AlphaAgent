from __future__ import annotations

import warnings
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import causal_leader_pullback_forward as forward
from alphaagent.server.services.low_suction.causal_leader_pullback_forward import (
    CausalForwardInputs,
    build_causal_forward_capture,
    evaluate_causal_forward_outcomes,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_DATE = date(2026, 7, 20)
SIGNAL_DATE = date(2026, 7, 21)
ATTEMPTED_AT = datetime(2026, 7, 21, 19, 5, tzinfo=SHANGHAI)


def test_d2_fast_limit_shadow_settles_without_changing_primary_exit() -> None:
    path = pd.DataFrame(
        [
            {"trade_date": pd.Timestamp("2026-07-21"), "open_price": 10.0, "close_price": 10.0},
            {"trade_date": pd.Timestamp("2026-07-22"), "open_price": 10.8, "close_price": 11.0},
            {"trade_date": pd.Timestamp("2026-07-23"), "open_price": 11.5, "close_price": 12.0},
        ]
    )

    result = forward._d2_fast_limit_shadow(
        {"signal_date": "2026-07-21"},
        path,
        entry_price=10.0,
        original_net_return_pct=9.8,
    )

    assert result["triggered"] is True
    assert result["status"] == "settled"
    assert result["d2_net_return_pct"] == 19.8
    assert result["return_delta_pct_points"] == 10.0


def test_v2_capture_freezes_cross_regime_funnel_and_every_decision(
    monkeypatch,
) -> None:
    inputs = _inputs()
    signals = pd.DataFrame(
        [
            _signal("rotation", "600001.SSE", phase="rotation", low=8.0),
            _signal("warming-undercut", "000001.SZSE", phase="warming", low=9.99),
        ]
    )
    leaders = pd.DataFrame(
        [
            _leader_path("campaign-1", "600001.SSE"),
            _leader_path("campaign-1", "000001.SZSE"),
        ]
    )
    features = pd.DataFrame(
        [
            {
                "vt_symbol": symbol,
                "trade_date": pd.Timestamp(SIGNAL_DATE),
                "previous_close": 90.0,
            }
            for symbol in ("600001.SSE", "000001.SZSE")
        ]
    )
    daily = pd.DataFrame(
        [
            {"trade_date": SIGNAL_DATE, "confirmation_status": "confirmed"},
            {"trade_date": SIGNAL_DATE, "confirmation_status": "confirmed"},
        ]
    )
    monkeypatch.setattr(forward, "build_causal_stock_features", lambda _bars: features)
    monkeypatch.setattr(
        forward,
        "build_dynamic_leader_paths",
        lambda *_args: (leaders, {}),
    )
    monkeypatch.setattr(
        forward,
        "replay_dynamic_leader_paths",
        lambda *_args: SimpleNamespace(signals=signals, daily_ledger=daily),
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.PerformanceWarning)
        capture = build_causal_forward_capture(inputs)

    assert not [
        warning
        for warning in caught
        if issubclass(warning.category, pd.errors.PerformanceWarning)
    ]

    assert capture.contract_version == (
        "causal-leader-pullback-cross-regime-forward-v2"
    )
    assert len(capture.scopes) == 1
    scope = capture.scopes[0]
    assert scope.identity_mode == "causal_campaign_rank_v2"
    assert scope.raw["policy_version"] == (
        "causal-leader-pullback-warming-support-relevance-v1"
    )
    assert scope.raw["signal_funnel"] == {
        "base_confirmation": 2,
        "gold_strong_reclaim": 2,
        "v3_cross_regime_support_reclaim": 2,
        "warming_support_relevance": 1,
        "rotation_next_session_diagnostic": 1,
        "three_phase_adaptive_diagnostic": 1,
    }
    diagnostic_policy = "causal-leader-pullback-rotation-next-session-v1"
    assert scope.raw["diagnostic_policies"][diagnostic_policy] == {
        "registered_before_first_natural_scope": True,
        "recommendations_created": 0,
        "orders_created": 0,
    }
    assert scope.raw["diagnostic_policies"][
        "causal-leader-pullback-three-phase-adaptive-v1"
    ]["qualification_contract_version"] == (
        "three-phase-natural-qualification-wilson-v1"
    )
    assert scope.raw["decision_reason_counts"] == {
        "eligible_rotation_strong_reclaim": 1,
        "warming_support_undercut": 1,
    }
    assert scope.signal_count == 1
    assert {row.feature_cutoff_date for row in capture.rows} == {SIGNAL_DATE}
    assert {row.vt_symbol for row in capture.rows} == {
        "600001.SSE",
        "000001.SZSE",
    }
    reasons = {row.vt_symbol: row.decision_reason for row in capture.rows}
    assert reasons == {
        "600001.SSE": "eligible_rotation_strong_reclaim",
        "000001.SZSE": "warming_support_undercut",
    }
    assert all(row.raw["minutes_used"] is False for row in capture.rows)
    assert all(row.raw["fund_flow_used"] is False for row in capture.rows)
    diagnostic = {
        row.vt_symbol: row.raw["diagnostic_policies"][diagnostic_policy][
            "signal_eligible"
        ]
        for row in capture.rows
    }
    assert diagnostic == {"600001.SSE": True, "000001.SZSE": False}
    three_phase_policy = "causal-leader-pullback-three-phase-adaptive-v1"
    three_phase = {
        row.vt_symbol: row.raw["diagnostic_policies"][three_phase_policy][
            "signal_eligible"
        ]
        for row in capture.rows
    }
    assert three_phase == {"600001.SSE": True, "000001.SZSE": False}
    assert {
        row.raw["diagnostic_policies"][three_phase_policy][
            "qualification_contract_version"
        ]
        for row in capture.rows
    } == {"three-phase-natural-qualification-wilson-v1"}


def test_v2_capture_rejects_future_daily_or_timing_rows() -> None:
    inputs = _inputs()
    future_bar = inputs.stock_bars.iloc[[0]].assign(trade_date=date(2026, 7, 22))
    with pytest.raises(ValueError, match="stock bars contain future dates"):
        build_causal_forward_capture(
            CausalForwardInputs(
                **{
                    **inputs.__dict__,
                    "stock_bars": pd.concat(
                        [inputs.stock_bars, future_bar], ignore_index=True
                    ),
                }
            )
        )

    with pytest.raises(ValueError, match="market timing contains future dates"):
        build_causal_forward_capture(
            CausalForwardInputs(
                **{
                    **inputs.__dict__,
                    "market_timing": inputs.market_timing.assign(
                        source_date=date(2026, 7, 22)
                    ),
                }
            )
        )


def test_eligible_memberships_reject_security_snapshot_gaps() -> None:
    inputs = _inputs()
    memberships = pd.concat(
        [
            inputs.memberships,
            pd.DataFrame(
                [
                    {
                        "sector_id": "BK0001",
                        "vt_symbol": "301080.SZSE",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    prepared = CausalForwardInputs(
        **{
            **inputs.__dict__,
            "memberships": memberships,
        }
    )

    eligible = forward._eligible_memberships(prepared)

    assert set(eligible["vt_symbol"]) == {"600001.SSE", "000001.SZSE"}
    assert eligible["stock_name"].ne("").all()


def test_v2_capture_requires_the_real_signal_date_after_close() -> None:
    inputs = _inputs()

    with pytest.raises(ValueError, match="after the signal close"):
        build_causal_forward_capture(
            CausalForwardInputs(
                **{
                    **inputs.__dict__,
                    "attempted_at": datetime(
                        2026,
                        7,
                        21,
                        14,
                        59,
                        tzinfo=SHANGHAI,
                    ),
                }
            )
        )

    with pytest.raises(ValueError, match="after the signal close"):
        build_causal_forward_capture(
            CausalForwardInputs(
                **{
                    **inputs.__dict__,
                    "attempted_at": datetime(
                        2026,
                        7,
                        22,
                        19,
                        0,
                        tzinfo=SHANGHAI,
                    ),
                }
            )
        )


def test_v2_outcome_diagnostics_stop_at_terminal_exit(monkeypatch) -> None:
    candidate = pd.DataFrame(
        [
            {
                "contract_version": forward.FORWARD_CONTRACT_VERSION,
                "source_trade_date": SOURCE_DATE,
                "signal_trade_date": SIGNAL_DATE,
                "identity_mode": forward.FORWARD_IDENTITY_MODE,
                "vt_symbol": "600001.SSE",
                "stock_name": "测试股份",
                "signal_eligible": True,
                "input_fingerprint": "sha256:test",
                "raw": {"signal": _signal("s1", "600001.SSE")},
            }
        ]
    )
    dates = pd.to_datetime(["2026-07-21", "2026-07-22", "2026-07-23"])
    campaign_paths = pd.DataFrame(
        {"campaign_id": "campaign-1", "trade_date": dates}
    )
    features = pd.DataFrame(
        [
            _outcome_feature("600001.SSE", dates[0], low=99.0, high=101.0),
            _outcome_feature("600001.SSE", dates[1], low=95.0, high=105.0),
            _outcome_feature("600001.SSE", dates[2], low=1.0, high=999.0),
        ]
    )
    monkeypatch.setattr(forward, "build_causal_stock_features", lambda _bars: features)
    monkeypatch.setattr(
        forward,
        "execute_close_trades",
        lambda *_args, **_kwargs: pd.DataFrame(
            [
                {
                    "entry_price": 100.0,
                    "exit_date": pd.Timestamp("2026-07-22"),
                    "exit_price": 104.0,
                    "exit_reason": "higher_high_confirmed",
                    "d1_date": pd.Timestamp("2026-07-22"),
                    "d1_close": 102.0,
                    "d1_net_return_pct": 1.8,
                    "holding_sessions": 1,
                    "net_return_pct": 3.8,
                }
            ]
        ),
    )

    outcomes = evaluate_causal_forward_outcomes(
        candidate,
        campaign_paths,
        pd.DataFrame(),
        completed_dates=(SIGNAL_DATE, date(2026, 7, 22), date(2026, 7, 23)),
    )

    assert outcomes.iloc[0]["mae_pct"] == pytest.approx(-5.0)
    assert outcomes.iloc[0]["mfe_pct"] == pytest.approx(5.0)
    assert bool(outcomes.iloc[0]["terminal"])


def _inputs() -> CausalForwardInputs:
    calendar = pd.bdate_range(end=SIGNAL_DATE, periods=65)
    stock_rows = []
    for symbol in ("600001.SSE", "000001.SZSE"):
        stock_rows.extend(
            {
                "vt_symbol": symbol,
                "trade_date": value.date(),
                "open_price": 90.0,
                "high_price": 96.0,
                "low_price": 89.0,
                "close_price": 95.0,
                "volume": 1_000_000.0,
                "turnover": 100_000_000.0,
            }
            for value in calendar
        )
    return CausalForwardInputs(
        source_trade_date=SOURCE_DATE,
        signal_trade_date=SIGNAL_DATE,
        attempted_at=ATTEMPTED_AT,
        membership_scope={
            "source_trade_date": SOURCE_DATE,
            "complete": True,
            "evidence_level": "strict",
        },
        security_scope={
            "source_trade_date": SOURCE_DATE,
            "complete": True,
            "evidence_level": "strict",
        },
        campaign_paths=pd.DataFrame(
            [
                {
                    "campaign_id": "campaign-1",
                    "sector_id": "BK0001",
                    "concept_name": "测试概念",
                    "anchor_date": SOURCE_DATE,
                    "trade_date": SIGNAL_DATE,
                    "campaign_day": 1,
                    "cumulative_gain_pct": 10.0,
                    "campaign_active": True,
                }
            ]
        ),
        memberships=pd.DataFrame(
            [
                {
                    "source_trade_date": SOURCE_DATE,
                    "sector_id": "BK0001",
                    "vt_symbol": symbol,
                    "evidence_level": "strict",
                }
                for symbol in ("600001.SSE", "000001.SZSE")
            ]
        ),
        securities=pd.DataFrame(
            [
                {
                    "source_trade_date": SOURCE_DATE,
                    "vt_symbol": symbol,
                    "symbol": symbol.split(".")[0],
                    "exchange": symbol.split(".")[1],
                    "name": "测试股份",
                    "status": "LISTED",
                    "listed_on": date(2020, 1, 1),
                    "delisted_on": None,
                    "suspended": False,
                    "risk_warning": False,
                    "evidence_level": "strict",
                }
                for symbol in ("600001.SSE", "000001.SZSE")
            ]
        ),
        stock_bars=pd.DataFrame(stock_rows),
        market_timing=pd.DataFrame(
            [
                {
                    "source_date": SIGNAL_DATE,
                    "active_direction": "GOLD",
                    "danger_state": "NORMAL",
                    "market_phase": "warming",
                    "known_at": ATTEMPTED_AT,
                }
            ]
        ),
    )


def _signal(
    signal_id: str,
    symbol: str,
    *,
    phase: str = "warming",
    low: float = 10.5,
) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "campaign_id": "campaign-1",
        "sector_id": "BK0001",
        "concept_name": "测试概念",
        "vt_symbol": symbol,
        "stock_name": "测试股份",
        "signal_date": pd.Timestamp(SIGNAL_DATE),
        "feature_cutoff_date": pd.Timestamp(SIGNAL_DATE),
        "wave_number": 1,
        "support_line": "ma5",
        "support_depth": 1,
        "support_test_date": pd.Timestamp(SOURCE_DATE),
        "support_test_session_gap": 1,
        "support_price": 10.0,
        "signal_close": 95.0,
        "signal_low": low,
        "signal_daily_return_pct": 8.0,
        "volume_ratio_prior5": 1.0,
        "reference_peak_date": pd.Timestamp(SOURCE_DATE),
        "reference_peak_price": 100.0,
        "dynamic_rank": 1,
        "dynamic_top3": True,
        "active_direction": "GOLD",
        "danger_state": "NORMAL",
        "market_phase": phase,
        "market_timing_feature_cutoff_date": pd.Timestamp(SIGNAL_DATE),
    }


def _leader_path(campaign_id: str, symbol: str) -> dict[str, object]:
    return {
        "campaign_id": campaign_id,
        "sector_id": "BK0001",
        "concept_name": "测试概念",
        "vt_symbol": symbol,
        "stock_name": "测试股份",
        "trade_date": pd.Timestamp(SIGNAL_DATE),
        "anchor_date": pd.Timestamp(SOURCE_DATE),
        "campaign_day": 1,
        "campaign_active": True,
        "dynamic_top3": True,
        "structure_intact": True,
        "leader_leg_base_close": 80.0,
        "leader_ignition_date": pd.Timestamp(SOURCE_DATE),
        "strong_days_since_ignition": 1,
        "volume_ratio_prior5": 1.0,
    }


def _outcome_feature(
    symbol: str,
    trade_date: pd.Timestamp,
    *,
    low: float,
    high: float,
) -> dict[str, object]:
    row: dict[str, object] = {
        "vt_symbol": symbol,
        "trade_date": trade_date,
    }
    for column in forward.STOCK_PATH_FEATURE_COLUMNS:
        row[column] = 0.0
    row.update(
        {
            "open_price": 100.0,
            "high_price": high,
            "low_price": low,
            "close_price": 100.0,
        }
    )
    return row
