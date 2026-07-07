from __future__ import annotations

from alphaagent.server.services.quant.d1_event_feature_research import classify_event_feature_groups


def test_classifies_active_source_compressed_high_close() -> None:
    result = classify_event_feature_groups(
        {
            "ret_d": 6.3,
            "close_location": 0.92,
            "vol_vs_ma20": 0.72,
            "amount_vs_ma20": 0.75,
            "turnover_to_market_cap_pct": 2.1,
            "ret20": 18.0,
            "ma20_dist_pct": 3.5,
            "intraday_amp_pct": 7.4,
            "prior_limit_up_20d": 1,
            "prior_high_touch_20d": 1,
            "lag1_vol_vs_ma20": 0.88,
            "lag2_vol_vs_ma20": 0.92,
        }
    )

    assert result["active_source_group"] == "single_limit_source"
    assert result["price_action_group"] == "first_sun_or_strong_close"
    assert result["active_source_compressed_high_close"] is True
    assert result["hot_reacceleration_exhaustion"] is False


def test_classifies_deep_low_close_rebound_absorption() -> None:
    result = classify_event_feature_groups(
        {
            "ret_d": -6.2,
            "close_location": 0.08,
            "vol_vs_ma20": 0.91,
            "amount_vs_ma20": 0.96,
            "turnover_to_market_cap_pct": 1.7,
            "ret20": -24.0,
            "ma20_dist_pct": -12.0,
            "intraday_amp_pct": 7.8,
            "prior_limit_up_20d": 0,
            "prior_high_touch_20d": 0,
            "lag1_vol_vs_ma20": 1.1,
            "lag2_vol_vs_ma20": 0.8,
        }
    )

    assert result["position_group"] == "deep_oversold"
    assert result["price_action_group"] == "panic_low_close"
    assert result["deep_low_close_rebound_absorption"] is True
    assert result["deep_low_first_sun_confirm"] is False


def test_classifies_deep_low_first_sun_confirm() -> None:
    result = classify_event_feature_groups(
        {
            "ret_d": 4.8,
            "close_location": 0.86,
            "vol_vs_ma20": 1.16,
            "amount_vs_ma20": 1.22,
            "turnover_to_market_cap_pct": 2.6,
            "ret20": -31.0,
            "ma20_dist_pct": -8.8,
            "intraday_amp_pct": 9.7,
            "prior_limit_up_20d": 0,
            "prior_high_touch_20d": 0,
            "lag1_vol_vs_ma20": 0.68,
            "lag2_vol_vs_ma20": 0.46,
        }
    )

    assert result["position_group"] == "deep_oversold"
    assert result["price_action_group"] == "first_sun_or_strong_close"
    assert result["deep_low_first_sun_confirm"] is True
    assert result["deep_low_close_rebound_absorption"] is False


def test_classifies_overheated_reacceleration_and_fade_risk() -> None:
    result = classify_event_feature_groups(
        {
            "ret_d": 11.4,
            "close_location": 0.84,
            "vol_vs_ma20": 2.4,
            "amount_vs_ma20": 2.8,
            "turnover_to_market_cap_pct": 9.5,
            "ret20": 96.0,
            "ma20_dist_pct": 42.0,
            "intraday_amp_pct": 16.0,
            "prior_limit_up_20d": 2,
            "prior_high_touch_20d": 3,
            "lag1_vol_vs_ma20": 1.4,
            "lag2_vol_vs_ma20": 1.1,
        }
    )

    assert result["position_group"] == "extreme_hot"
    assert result["volume_turnover_group"] == "extreme_high_turnover_proxy"
    assert result["hot_reacceleration_exhaustion"] is True
    assert result["active_source_compressed_high_close"] is False
