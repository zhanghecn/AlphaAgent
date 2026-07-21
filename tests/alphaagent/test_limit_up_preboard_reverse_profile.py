from __future__ import annotations

from copy import deepcopy

from alphaagent.server.services.limit_up.preboard_reverse_profile import (
    align_pair_to_touch_horizons,
    feature_separation,
    first_observable_leads,
    matched_risk_set,
    positive_rank_diagnostics,
    snapshot_pair_at_touch_horizons,
    trading_minutes_between,
)


def test_alignment_uses_trading_minutes_across_lunch() -> None:
    rows = [
        _row("600001.SSE", "11:20:00", gain=3.2),
        _row("600001.SSE", "11:25:00", gain=3.5),
        _row("600001.SSE", "13:05:00", gain=5.1),
    ]

    aligned = align_pair_to_touch_horizons(
        rows,
        touch_time="13:10:00",
        horizons=(30, 15, 5),
    )

    assert trading_minutes_between("11:25:00", "13:05:00") == 10.0
    assert aligned[30] is None
    assert aligned[15] is not None
    assert aligned[15]["signal_time"] == "11:25:00"
    assert aligned[5] is not None
    assert aligned[5]["signal_time"] == "13:05:00"


def test_first_observable_leads_separate_three_pct_and_shared() -> None:
    rows = [
        _row("600001.SSE", "10:00:00", gain=3.1, shared=False),
        _row("600001.SSE", "10:05:00", gain=4.2, shared=False),
        _row("600001.SSE", "10:10:00", gain=5.3, shared=True),
        _row("600001.SSE", "10:15:00", gain=7.0, shared=True),
    ]

    result = first_observable_leads(rows, touch_time="10:20:00")

    assert result == {
        "first_3pct_lead_minutes": 20.0,
        "first_shared_lead_minutes": 10.0,
    }


def test_alignment_is_immutable_and_outcome_independent() -> None:
    rows = [_row("600001.SSE", "10:10:00", gain=5.0, shared=True)]
    baseline_rows = deepcopy(rows)
    baseline = align_pair_to_touch_horizons(
        rows,
        touch_time="10:20:00",
        horizons=(10,),
    )
    changed = deepcopy(rows)
    changed[0].update(
        formal_touch_baseline_target=False,
        formal_touch_account_target=False,
        touched_limit=False,
        sealed_limit=False,
        d1_close_price=1.0,
        net_return_pct=-90.0,
        account_status="skipped",
    )

    mutated = align_pair_to_touch_horizons(
        changed,
        touch_time="10:20:00",
        horizons=(10,),
    )

    assert rows == baseline_rows
    assert baseline[10] is not None
    assert mutated[10] is not None
    assert baseline[10]["features"] == mutated[10]["features"]
    assert baseline[10]["ignition_features"] == mutated[10]["ignition_features"]


def test_alignment_rejects_below_three_and_post_touch_rows() -> None:
    rows = [
        _row("600001.SSE", "10:00:00", gain=2.9),
        _row(
            "600001.SSE",
            "10:05:00",
            gain=4.0,
            before_first_touch=False,
        ),
    ]

    aligned = align_pair_to_touch_horizons(
        rows,
        touch_time="10:10:00",
        horizons=(5,),
    )

    assert aligned == {5: None}


def test_snapshot_uses_nearest_prefix_instead_of_stale_qualifying_row() -> None:
    rows = [
        _row("600001.SSE", "10:15:00", gain=8.0, shared=True),
        _row("600001.SSE", "10:45:00", gain=2.5, shared=False),
    ]

    cumulative = align_pair_to_touch_horizons(
        rows,
        touch_time="11:00:00",
        horizons=(10,),
    )
    snapshot = snapshot_pair_at_touch_horizons(
        rows,
        touch_time="11:00:00",
        horizons=(10,),
    )

    assert cumulative[10] is not None
    assert cumulative[10]["signal_time"] == "10:15:00"
    assert snapshot[10] is not None
    assert snapshot[10]["signal_time"] == "10:45:00"
    assert snapshot[10]["tracked_after_3pct"] is True
    assert snapshot[10]["snapshot_current_gte_3pct"] is False
    assert snapshot[10]["snapshot_shared_eligible"] is False


def test_matched_risk_set_uses_exact_date_time_and_observation_state() -> None:
    anchor = _row("600001.SSE", "10:10:00", gain=6.0, shared=True)
    rows = [
        anchor,
        _row("600002.SSE", "10:10:00", gain=5.0, shared=False),
        _row("600003.SSE", "10:05:00", gain=7.0, shared=True),
        _row(
            "600004.SSE",
            "10:10:00",
            gain=8.0,
            shared=True,
            signal_date="2026-01-06",
        ),
        _row("600005.SSE", "10:10:00", gain=2.9, shared=True),
        _row(
            "600006.SSE",
            "10:10:00",
            gain=8.0,
            shared=True,
            before_first_touch=False,
        ),
    ]

    raw = matched_risk_set(rows, anchor, require_shared=False)
    shared = matched_risk_set(rows, anchor, require_shared=True)

    assert {row["vt_symbol"] for row in raw} == {"600001.SSE", "600002.SSE"}
    assert {row["vt_symbol"] for row in shared} == {"600001.SSE"}


def test_matched_risk_set_deduplicates_symbol_date_time() -> None:
    anchor = _row("600001.SSE", "10:10:00", gain=6.0, shared=True)

    result = matched_risk_set(
        [anchor, deepcopy(anchor)],
        anchor,
        require_shared=False,
    )

    assert len(result) == 1


def test_positive_rank_diagnostics_use_fixed_directions() -> None:
    rows = [
        _row("600001.SSE", "10:10:00", gain=8.0, shared=True, rank=80.0),
        _row("600002.SSE", "10:10:00", gain=9.0, shared=True, rank=90.0),
        _row("600003.SSE", "10:10:00", gain=7.0, shared=True, rank=70.0),
    ]

    result = positive_rank_diagnostics(
        rows,
        positive_pair=("600001.SSE", "2026-01-05"),
    )

    assert result["rank_score"]["rank"] == 2
    assert result["rank_score"]["top2"] is True
    assert result["gain_pct"]["rank"] == 2
    assert result["distance_to_limit_pct"]["rank"] == 2
    assert result["rank_score"]["candidate_count"] == 3


def test_feature_separation_reports_higher_and_lower_directions() -> None:
    positives = [
        _row("600001.SSE", "10:10:00", gain=8.0, shared=True),
        _row("600002.SSE", "10:10:00", gain=9.0, shared=True),
    ]
    controls = [
        _row("600003.SSE", "10:10:00", gain=4.0),
        _row("600004.SSE", "10:10:00", gain=5.0),
    ]

    result = feature_separation(positives, controls)

    assert result["gain_pct"]["rank_auc"] == 1.0
    assert result["gain_pct"]["direction"] == "higher"
    assert result["distance_to_limit_pct"]["rank_auc"] == 0.0
    assert result["distance_to_limit_pct"]["direction"] == "lower"


def test_rank_and_separation_ignore_outcomes_and_missing_feature_values() -> None:
    positive = _row("600001.SSE", "10:10:00", gain=8.0, shared=True, rank=80.0)
    control = _row("600002.SSE", "10:10:00", gain=6.0, shared=True, rank=70.0)
    baseline_rank = positive_rank_diagnostics(
        [positive, control],
        positive_pair=("600001.SSE", "2026-01-05"),
    )
    changed = deepcopy(positive)
    changed.update(
        formal_touch_baseline_target=False,
        formal_touch_account_target=False,
        d1_close_price=1.0,
        net_return_pct=-90.0,
    )
    missing = deepcopy(control)
    missing["ignition_features"]["gain_pct"] = None
    missing["features"]["gain_pct"] = None

    mutated_rank = positive_rank_diagnostics(
        [changed, control],
        positive_pair=("600001.SSE", "2026-01-05"),
    )
    separation = feature_separation([positive], [missing])

    assert mutated_rank == baseline_rank
    assert separation["gain_pct"]["control_count"] == 0
    assert separation["gain_pct"]["rank_auc"] is None


def _row(
    symbol: str,
    signal_time: str,
    *,
    gain: float,
    shared: bool = False,
    before_first_touch: bool = True,
    signal_date: str = "2026-01-05",
    rank: float = 70.0,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "signal_time": signal_time,
        "signal_at": f"{signal_date}T{signal_time}",
        "before_first_limit_touch": before_first_touch,
        "shared_strategy_passed": shared,
        "features": {
            "gain_pct": gain,
            "return_30m_pct": gain - 2.0,
            "prior_30m_range_pct": 1.0,
            "prior_30m_floor_pct": 2.0,
            "breakout_margin_pct": gain - 3.0,
            "opening_gap_pct": 1.0,
            "minute_of_window": 10.0,
        },
        "ignition_features": {
            "gain_pct": gain,
            "return_5m_pct": 0.5,
            "return_15m_pct": 1.0,
            "acceleration_pct": 0.2,
            "distance_to_limit_pct": 10.0 - gain,
            "session_drawdown_pct": -0.2,
            "bar_close_location": 0.8,
            "volume_ratio_30m": 1.2,
            "amount_ratio_30m": 1.3,
            "amount_acceleration_ratio": 1.1,
            "support_score": 60.0,
            "entry_quality_score": 65.0,
            "rank_score": rank,
        },
        "rank_score": rank,
        "support_score": 60.0,
        "entry_quality_score": 65.0,
    }
