from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.support_touch_reclaim_feature_study import (
    PRE_REGISTERED_FEATURES,
    STUDY_VERSION,
    attach_reclaim_labels,
    build_touch_feature_frame,
    rank_auc,
    summarize_feature_stability,
)


START = date(2026, 7, 1)


def _day(offset: int) -> date:
    return START + timedelta(days=offset)


def _touch(opportunity_id: str, **overrides) -> dict[str, object]:
    base = {
        "opportunity_id": opportunity_id,
        "campaign_id": "camp-1",
        "sector_id": "BK_TEST",
        "concept_name": "测试概念",
        "vt_symbol": "600001.SSE",
        "stock_name": "测试龙头",
        "entry_date": _day(0),
        "entry_price": 10.0,
        "wave_number": 1,
        "support_line": "ma5",
        "ma5": 9.9,
        "ma10": 9.5,
        "prior_high20": 10.5,
        "dynamic_rank": 1,
        "low_price": 9.85,
        "daily_return_pct": -1.5,
        "close_location": 0.4,
        "volume_ratio_prior5": 0.8,
        "turnover_expansion": 1.1,
        "sessions_since_ignition": 8,
        "last_ignition_base_close": 8.0,
    }
    base.update(overrides)
    return base


def _signal(support_test_date: date, *, daily_return: float = 9.0, close: float = 10.4,
            peak: float = 10.5, gap: float = 1.0, support: str = "ma5") -> dict[str, object]:
    return {
        "signal_id": f"sig-{support_test_date}-{daily_return}",
        "campaign_id": "camp-1",
        "vt_symbol": "600001.SSE",
        "support_test_date": support_test_date,
        "support_line": support,
        "signal_daily_return_pct": daily_return,
        "signal_close": close,
        "reference_peak_price": peak,
        "support_test_session_gap": gap,
    }


class TestAttachReclaimLabels:
    def test_touch_with_strong_reclaim_signal_is_labeled(self) -> None:
        touches = pd.DataFrame([_touch("a"), _touch("b", entry_date=_day(3))])
        signals = pd.DataFrame([_signal(_day(3))])

        result = attach_reclaim_labels(touches, signals)

        assert result.loc[result["opportunity_id"] == "a", "reclaimed"].iloc[0] == False
        assert result.loc[result["opportunity_id"] == "b", "reclaimed"].iloc[0] == True

    def test_weak_confirmation_does_not_count(self) -> None:
        touches = pd.DataFrame([_touch("a")])
        signals = pd.DataFrame([_signal(_day(0), daily_return=5.0)])

        result = attach_reclaim_labels(touches, signals)

        assert result["reclaimed"].iloc[0] == False

    def test_far_from_peak_does_not_count(self) -> None:
        touches = pd.DataFrame([_touch("a")])
        signals = pd.DataFrame([_signal(_day(0), close=9.8, peak=10.5)])

        result = attach_reclaim_labels(touches, signals)

        assert result["reclaimed"].iloc[0] == False

    def test_gap_beyond_two_sessions_does_not_count(self) -> None:
        touches = pd.DataFrame([_touch("a")])
        signals = pd.DataFrame([_signal(_day(0), gap=3.0)])

        result = attach_reclaim_labels(touches, signals)

        assert result["reclaimed"].iloc[0] == False


class TestBuildTouchFeatureFrame:
    def test_derived_features_are_causal_touch_day_values(self) -> None:
        frame = build_touch_feature_frame(pd.DataFrame([_touch("a")])).iloc[0]
        assert frame["close_holds_support"] == True  # 10.0 >= 9.9
        assert frame["undercut_depth_pct"] == pytest.approx((9.85 / 9.9 - 1.0) * 100.0)
        assert frame["peak_distance_pct"] == pytest.approx((10.0 / 10.5 - 1.0) * 100.0)
        assert frame["leg_gain_pct"] == pytest.approx((10.0 / 8.0 - 1.0) * 100.0)

    def test_ma10_touch_uses_ma10_as_support(self) -> None:
        frame = build_touch_feature_frame(
            pd.DataFrame([_touch("a", support_line="ma10", entry_price=9.4)])
        ).iloc[0]
        assert frame["close_holds_support"] == False  # 9.4 < 9.5
        assert frame["undercut_depth_pct"] == pytest.approx((9.85 / 9.5 - 1.0) * 100.0)

    def test_pre_registered_feature_list_matches_output(self) -> None:
        frame = build_touch_feature_frame(pd.DataFrame([_touch("a")]))
        for name in PRE_REGISTERED_FEATURES:
            assert name in frame.columns, name


class TestRankAuc:
    def test_perfect_separation_scores_one(self) -> None:
        features = pd.Series([1.0, 2.0, 3.0, 4.0])
        labels = pd.Series([False, False, True, True])
        assert rank_auc(features, labels) == 1.0

    def test_inverse_separation_scores_zero(self) -> None:
        features = pd.Series([4.0, 3.0, 2.0, 1.0])
        labels = pd.Series([False, False, True, True])
        assert rank_auc(features, labels) == 0.0

    def test_constant_feature_is_uninformative(self) -> None:
        assert rank_auc(pd.Series([1.0, 1.0]), pd.Series([True, False])) == 0.5

    def test_single_class_returns_none(self) -> None:
        assert rank_auc(pd.Series([1.0, 2.0]), pd.Series([True, True])) is None


class TestSummarizeFeatureStability:
    def test_counts_blocks_above_threshold(self) -> None:
        block_aucs = {"block_1": 0.61, "block_2": 0.58, "block_3": 0.49, "block_4": 0.62, "block_5": None}
        result = summarize_feature_stability(block_aucs, threshold=0.55)
        assert result["stable_blocks"] == 3
        assert result["evaluated_blocks"] == 4

    def test_study_version_is_frozen(self) -> None:
        assert STUDY_VERSION == "support-touch-reclaim-feature-v1"
