from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.event_neutral_panel import (
    NEUTRAL_STATE_FEATURES,
    build_event_neutral_state_panel,
)


def _candidate(event_id: int = 1, symbol: str = "600001.SSE") -> dict[str, object]:
    return {
        "event_id": event_id,
        "leader_spell_id": f"BK0963:cycle-1:{symbol}",
        "source_date": date(2025, 7, 2),
        "entry_date": date(2025, 7, 2),
        "planned_exit_date": date(2025, 7, 3),
        "sector_id": "BK0963",
        "concept_name": "商业航天",
        "cycle_id": "cycle-1",
        "vt_symbol": symbol,
        "recognition_rank": 1,
        "signal_close": 10.0,
        "previous_high": 10.5,
        "ma5": 9.8,
        "ma10": 9.5,
        "cycle_relative_percentile": 0.9,
        "spell_session_offset": 1,
        "active_direction": "SILVER",
        "danger_state": "NORMAL",
        "market_phase": "recovery",
        "main_rise": True,
        "is_top3": True,
        "rank_mode": "event_recognition_proxy",
        "evidence_level": "event_recognition_neutral_day_falsification",
    }


def _candidates() -> pd.DataFrame:
    return pd.DataFrame([_candidate()])


def _minute_bars(
    symbol: str = "600001.SSE",
    *,
    future_close: float | None = None,
) -> pd.DataFrame:
    morning = [
        datetime(2025, 7, 2, 9, 35) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    afternoon = [
        datetime(2025, 7, 2, 13, 5) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    times = [*morning, *afternoon]
    closes = [10.0 + index * 0.01 for index in range(48)]
    if future_close is not None:
        closes[8:] = [future_close] * 40
    opens = [closes[0], *closes[:-1]]
    volumes = [100.0 * (index + 1) for index in range(48)]
    return pd.DataFrame(
        [
            {
                "vt_symbol": symbol,
                "trade_date": date(2025, 7, 2),
                "bar_time": bar_time,
                "interval": "5m",
                "open_price": open_price,
                "high_price": max(open_price, close_price) + 0.02,
                "low_price": min(open_price, close_price) - 0.02,
                "close_price": close_price,
                "volume": volume,
                "turnover": close_price * volume,
                "source": "tdx_public_hq",
            }
            for bar_time, open_price, close_price, volume in zip(
                times,
                opens,
                closes,
                volumes,
                strict=True,
            )
        ]
    )


def test_point_in_time_features_match_manual_values() -> None:
    panel = build_event_neutral_state_panel(_candidates(), _minute_bars())
    row = panel.loc[panel["bar_time"].eq(datetime(2025, 7, 2, 9, 55))].iloc[0]
    closes = [10.0, 10.01, 10.02, 10.03, 10.04]
    volumes = [100.0, 200.0, 300.0, 400.0, 500.0]
    manual_vwap = sum(
        close * volume for close, volume in zip(closes, volumes, strict=True)
    ) / sum(volumes)

    assert row["vwap"] == pytest.approx(manual_vwap)
    assert row["return_3bar_pct"] == pytest.approx((10.04 / 10.01 - 1.0) * 100)
    assert row["volume_ratio_prior_3bars"] == pytest.approx(500.0 / 300.0)
    assert row["distance_to_previous_high_pct"] == pytest.approx(
        (10.04 / 10.5 - 1.0) * 100
    )
    assert row["minutes_from_open"] == 25
    assert set(NEUTRAL_STATE_FEATURES) <= set(panel)


def test_future_bars_do_not_change_earlier_state() -> None:
    before = build_event_neutral_state_panel(_candidates(), _minute_bars())
    after = build_event_neutral_state_panel(
        _candidates(),
        _minute_bars(future_close=20.0),
    )
    earlier = before["bar_time"].lt(datetime(2025, 7, 2, 10, 10))

    pd.testing.assert_frame_equal(
        before.loc[earlier, ["bar_time", *NEUTRAL_STATE_FEATURES]].reset_index(drop=True),
        after.loc[earlier, ["bar_time", *NEUTRAL_STATE_FEATURES]].reset_index(drop=True),
    )


def test_outcome_or_future_columns_are_rejected() -> None:
    bars = _minute_bars().assign(session_final_low=1.0)

    with pytest.raises(ValueError, match="future or outcome"):
        build_event_neutral_state_panel(_candidates(), bars)


def test_each_date_cycle_block_has_total_weight_one() -> None:
    candidates = pd.DataFrame(
        [
            _candidate(event_id=1, symbol="600001.SSE"),
            _candidate(event_id=2, symbol="600002.SSE"),
        ]
    )
    bars = pd.concat(
        [_minute_bars("600001.SSE"), _minute_bars("600002.SSE")],
        ignore_index=True,
    )

    panel = build_event_neutral_state_panel(candidates, bars)
    totals = panel.groupby("independence_block_id")["sample_weight"].sum()

    assert totals.tolist() == pytest.approx([1.0])
    assert len(panel) == 88
    assert panel["observation_id"].is_unique
