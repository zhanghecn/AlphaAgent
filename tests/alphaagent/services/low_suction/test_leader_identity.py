from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.leader_identity import (
    LeaderIdentityMode,
    choose_stable_leader_identity,
    evaluate_leader_identity,
    rank_leader_identities,
    rank_prevalidated_leader_identities,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _leader_features(
    *,
    trade_date: date = date(2026, 6, 1),
    calendar_position: int = 0,
    count: int = 7,
) -> pd.DataFrame:
    prior = trade_date - timedelta(days=1)
    rows = []
    for index in range(count):
        symbol = f"00000{index + 1}"
        rows.append(
            {
                "trade_date": trade_date,
                "calendar_position": calendar_position,
                "sector_id": "BK_TEST",
                "vt_symbol": f"{symbol}.SZSE",
                "symbol": symbol,
                "exchange": "SZSE",
                "cutoff": datetime.combine(
                    trade_date,
                    datetime.min.time(),
                    tzinfo=SHANGHAI,
                ).replace(hour=9, minute=25),
                "feature_cutoff": datetime.combine(
                    prior,
                    datetime.min.time(),
                    tzinfo=SHANGHAI,
                ).replace(hour=15),
                "membership_known_at": datetime.combine(
                    prior,
                    datetime.min.time(),
                    tzinfo=SHANGHAI,
                ).replace(hour=18),
                "membership_source_trade_date": prior,
                "membership_evidence_level": "strict",
                "membership_scope_complete": True,
                "security_known_at": datetime.combine(
                    prior,
                    datetime.min.time(),
                    tzinfo=SHANGHAI,
                ).replace(hour=18),
                "security_evidence_level": "strict",
                "name": f"测试{index + 1}",
                "status": "LISTED",
                "listed_sessions": 500,
                "suspended": False,
                "risk_warning": False,
                "delisted": False,
                "cycle_relative_return": float(count - index),
                "strong_day_count_cycle": count - index,
                "sessions_since_strong": index,
                "turnover_median_20d": float((count - index) * 100_000_000),
                "capacity_passed": index < count - 1,
            }
        )
    return pd.DataFrame(rows)


def test_lexicographic_rank_does_not_sum_arbitrary_weights() -> None:
    ranked = rank_leader_identities(
        _leader_features(),
        mode=LeaderIdentityMode.MARKET_RECOGNITION,
    )

    assert ranked.loc[0, "vt_symbol"] == "000001.SZSE"
    assert "leader_score" not in ranked.columns
    assert ranked.loc[:2, "is_top3"].all()


def test_current_membership_is_rejected_for_v2_identity() -> None:
    features = _leader_features()
    features["membership_evidence_level"] = "current_proxy"

    with pytest.raises(ValueError, match="strict membership"):
        rank_leader_identities(features, mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH)


def test_membership_known_after_open_is_rejected() -> None:
    features = _leader_features()
    features.loc[0, "membership_known_at"] = features.loc[0, "cutoff"] + pd.Timedelta(minutes=1)

    with pytest.raises(ValueError, match="membership known_at"):
        rank_leader_identities(features, mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH)


def test_non_main_board_security_is_excluded_before_ranking() -> None:
    features = _leader_features()
    features.loc[0, ["symbol", "vt_symbol"]] = ["300001", "300001.SZSE"]

    ranked = rank_leader_identities(features, mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH)
    excluded = ranked.loc[ranked["vt_symbol"] == "300001.SZSE"].iloc[0]

    assert excluded["excluded_reason"] == "board_not_supported"
    assert not excluded["is_top3"]
    assert pd.isna(excluded["rank"])


def test_capacity_breaks_otherwise_identical_market_ties() -> None:
    features = _leader_features(count=2)
    features[["cycle_relative_return", "strong_day_count_cycle", "sessions_since_strong"]] = 1.0
    features["capacity_passed"] = [False, True]
    features["turnover_median_20d"] = [500_000_000.0, 100_000_000.0]

    ranked = rank_leader_identities(features, mode=LeaderIdentityMode.MARKET_RECOGNITION)

    assert ranked.loc[0, "vt_symbol"] == "000002.SZSE"


def test_future_date_rows_cannot_change_prior_top3() -> None:
    prior = _leader_features()
    future = _leader_features(
        trade_date=date(2026, 6, 2),
        calendar_position=1,
    )
    future["cycle_relative_return"] *= -100
    original = rank_leader_identities(
        prior,
        mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH,
    )
    combined = rank_leader_identities(
        pd.concat([prior, future], ignore_index=True),
        mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH,
    )

    pd.testing.assert_frame_equal(
        original.reset_index(drop=True),
        combined.loc[combined["trade_date"] == date(2026, 6, 1)].reset_index(drop=True),
    )


def test_consensus_requires_top_five_in_both_base_modes() -> None:
    features = _leader_features()
    features.loc[0, "cycle_relative_return"] = -100.0
    features.loc[6, "strong_day_count_cycle"] = 100
    ranked = rank_leader_identities(features, mode=LeaderIdentityMode.RECOGNITION_CONSENSUS)
    eligible = ranked.loc[ranked["rank_eligible"]]

    assert (eligible["relative_strength_rank"] <= 5).all()
    assert (eligible["market_recognition_rank"] <= 5).all()


def test_identity_evaluation_rejects_low_suction_outcomes() -> None:
    ranks = rank_leader_identities(
        _leader_features(),
        mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH,
    )
    outcomes = pd.DataFrame(
        {
            "trade_date": [date(2026, 6, 1)],
            "sector_id": ["BK_TEST"],
            "vt_symbol": ["000001.SZSE"],
            "sessions_to_next_strong_event": [1],
            "net_return_pct": [99.0],
        }
    )

    with pytest.raises(ValueError, match="low-suction outcomes"):
        evaluate_leader_identity(ranks, outcomes=outcomes)


def test_identity_evaluation_uses_exact_next_day_top3_retention() -> None:
    first = _leader_features()
    second = _leader_features(
        trade_date=date(2026, 6, 2),
        calendar_position=1,
    )
    second.loc[2, "cycle_relative_return"] = -100.0
    second.loc[3, "cycle_relative_return"] = 100.0
    ranks = rank_leader_identities(
        pd.concat([first, second], ignore_index=True),
        mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH,
    )

    metrics = evaluate_leader_identity(ranks)

    assert metrics.loc[0, "eligible_retention_observations"] == 3
    assert metrics.loc[0, "next_day_top3_retention"] == pytest.approx(2 / 3)


def test_three_of_five_fold_wins_freeze_one_identity_mode() -> None:
    winner = choose_stable_leader_identity(
        (
            "cycle_relative_strength",
            "market_recognition_lexicographic",
            "cycle_relative_strength",
            "recognition_consensus",
            "cycle_relative_strength",
        )
    )

    assert winner == LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH


def _forward_rank_features() -> pd.DataFrame:
    features = _leader_features().rename(
        columns={"trade_date": "source_trade_date"}
    )
    features["excluded_reason"] = None
    return features


@pytest.mark.parametrize("mode", tuple(LeaderIdentityMode))
def test_prevalidated_forward_rank_uses_the_existing_mode_order(
    mode: LeaderIdentityMode,
) -> None:
    historical = rank_leader_identities(_leader_features(), mode=mode)
    forward = rank_prevalidated_leader_identities(
        _forward_rank_features(),
        mode=mode,
        session_column="source_trade_date",
    )

    assert forward.loc[forward["is_top3"], "vt_symbol"].tolist() == historical.loc[
        historical["is_top3"], "vt_symbol"
    ].tolist()
    assert set(forward["identity_mode"]) == {mode.value}


def test_prevalidated_forward_rank_preserves_exclusions() -> None:
    features = _forward_rank_features()
    features.loc[0, "excluded_reason"] = "not_in_active_security_scope"

    ranked = rank_prevalidated_leader_identities(
        features,
        mode=LeaderIdentityMode.MARKET_RECOGNITION,
        session_column="source_trade_date",
    )
    excluded = ranked.loc[ranked["vt_symbol"] == "000001.SZSE"].iloc[0]

    assert excluded["excluded_reason"] == "not_in_active_security_scope"
    assert not excluded["rank_eligible"]
    assert not excluded["is_top3"]
    assert pd.isna(excluded["rank"])


def test_prevalidated_forward_rank_rejects_duplicates_and_outcomes() -> None:
    duplicate = pd.concat(
        [_forward_rank_features(), _forward_rank_features().iloc[[0]]],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="identity must be unique"):
        rank_prevalidated_leader_identities(
            duplicate,
            mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH,
            session_column="source_trade_date",
        )

    outcomes = _forward_rank_features().assign(future_return=99.0)
    with pytest.raises(ValueError, match="low-suction outcomes"):
        rank_prevalidated_leader_identities(
            outcomes,
            mode=LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH,
            session_column="source_trade_date",
        )
