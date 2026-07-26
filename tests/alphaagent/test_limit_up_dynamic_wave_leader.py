from datetime import date

import pandas as pd
from pandas.testing import assert_frame_equal

from alphaagent.server.services.limit_up.capital_mainline_contract import EvidenceLevel
from alphaagent.server.services.limit_up.capital_mainline_repository import (
    CapitalMainlineInputs,
)
from alphaagent.server.services.limit_up.capital_mainline_research import (
    MembershipContext,
)
from alphaagent.server.services.limit_up.dynamic_wave_leader import (
    attach_dynamic_wave_features,
    build_dynamic_leader_mappings,
    build_wave_member_features,
    evaluate_dynamic_wave_factors,
    rank_dynamic_wave_leaders,
    segment_concept_waves,
)


D1 = date(2026, 7, 1)
D2 = date(2026, 7, 2)
D3 = date(2026, 7, 3)
D4 = date(2026, 7, 6)
D5 = date(2026, 7, 7)
D6 = date(2026, 7, 8)
D7 = date(2026, 7, 9)
D8 = date(2026, 7, 10)
DATES = (D1, D2, D3, D4, D5, D6, D7, D8)


def test_segment_concept_waves_splits_reignition_after_joint_weakness() -> None:
    waves = segment_concept_waves(_concept_panel())

    assert waves["wave_id"].nunique() == 2
    assert waves.groupby("wave_id")["trade_date"].min().tolist() == [D1, D7]
    assert waves.loc[waves["trade_date"].eq(D6), "wave_phase"].item() == "ebb"


def test_segment_concept_waves_accepts_index_turnover_trend_ignition() -> None:
    panel = _concept_panel().iloc[:2].copy()
    panel["first_board_count"] = 0
    panel["sealed_count"] = 0

    waves = segment_concept_waves(panel)

    assert waves.iloc[0]["wave_start_reason"] == "index_turnover_trend_ignition"


def test_segment_concept_waves_marks_only_first_two_breadth_expansion_days() -> None:
    panel = _concept_panel().iloc[:4].copy()
    panel.loc[panel["trade_date"].eq(D2), [
        "ladder_strength",
        "turnover_strength",
        "first_board_count",
        "sealed_count",
    ]] = [0.72, 0.82, 2, 3]
    panel.loc[panel["trade_date"].eq(D3), [
        "ladder_strength",
        "turnover_strength",
        "first_board_count",
        "sealed_count",
    ]] = [0.75, 0.84, 2, 3]
    panel.loc[panel["trade_date"].eq(D4), [
        "ladder_strength",
        "turnover_strength",
        "first_board_count",
        "sealed_count",
    ]] = [0.78, 0.86, 3, 4]

    waves = segment_concept_waves(panel).set_index("trade_date")

    assert waves.loc[D2, "wave_expansion_onset"]
    assert waves.loc[D2, "wave_expansion_impulse"]
    assert waves.loc[D2, "wave_expansion_age_sessions"] == 1
    assert waves.loc[D3, "wave_early_expansion"]
    assert waves.loc[D3, "wave_expansion_age_sessions"] == 2
    assert not waves.loc[D4, "wave_early_expansion"]
    assert waves.loc[D4, "wave_expansion_age_sessions"] == 3


def test_acceleration_without_breadth_is_not_diffusion_onset() -> None:
    panel = _concept_panel().iloc[:2].copy()
    panel.loc[panel["trade_date"].eq(D2), [
        "index_strength",
        "turnover_strength",
        "ladder_strength",
        "first_board_count",
        "sealed_count",
    ]] = [0.90, 0.90, 0.40, 0, 0]

    waves = segment_concept_waves(panel).set_index("trade_date")

    assert waves.loc[D2, "wave_phase"] == "acceleration"
    assert not waves.loc[D2, "wave_expansion_onset"]
    assert not waves.loc[D2, "wave_early_expansion"]


def test_segment_concept_waves_restarts_after_one_session_cooldown() -> None:
    panel = _concept_panel().iloc[:6].copy()
    panel.loc[panel["trade_date"].eq(D6), [
        "index_strength",
        "turnover_strength",
        "ladder_strength",
        "mainline_percentile",
        "first_board_count",
        "sealed_count",
        "return_1d_pct",
    ]] = [0.88, 0.84, 0.72, 0.92, 1, 1, 2.5]

    waves = segment_concept_waves(panel)

    assert waves["wave_id"].nunique() == 2
    assert waves.groupby("wave_id")["trade_date"].min().tolist() == [D1, D6]
    assert waves.loc[waves["trade_date"].eq(D5), "wave_phase"].item() == "divergence"
    assert (
        waves.loc[waves["trade_date"].eq(D6), "wave_start_reason"].item()
        == "board_reignition_after_cooldown"
    )


def test_segment_concept_waves_restarts_on_board_rotation_during_shock() -> None:
    panel = _concept_panel().iloc[:5].copy()
    panel.loc[panel["trade_date"].eq(D5), [
        "index_strength",
        "turnover_strength",
        "ladder_strength",
        "mainline_percentile",
        "first_board_count",
        "sealed_count",
        "return_1d_pct",
    ]] = [0.70, 0.80, 0.70, 0.90, 1, 1, -3.5]

    waves = segment_concept_waves(panel)

    assert waves["wave_id"].nunique() == 2
    assert waves.loc[waves["trade_date"].eq(D5), "wave_phase"].item() == "ignition"
    assert (
        waves.loc[waves["trade_date"].eq(D5), "wave_start_reason"].item()
        == "board_rotation_ignition"
    )


def test_leadership_asof_is_unchanged_by_future_stock_bars() -> None:
    before = build_wave_member_features(
        _inputs(D4),
        _waves(D4),
        _contexts(D4),
    )
    after = build_wave_member_features(
        _inputs(D8),
        _waves(D8),
        _contexts(D8),
    )

    columns = [
        "trade_date",
        "vt_symbol",
        "wave_return_pct",
        "relative_wave_return_pct",
        "stock_return_3d_pct",
        "cumulative_limit_up_count",
        "first_strength_date",
        "response_member_count_asof",
    ]
    assert_frame_equal(
        before[columns].reset_index(drop=True),
        after.loc[after["trade_date"].le(D4), columns].reset_index(drop=True),
    )


def test_wave_member_features_report_all_concept_member_universe() -> None:
    inputs = _inputs(D4)
    inputs.coverage["event_coverage"] = {
        "stock_bar_universe": "all_concept_members"
    }

    features = build_wave_member_features(
        inputs,
        _waves(D4),
        _contexts(D4),
    )

    assert set(features["member_universe_mode"]) == {"all_concept_members"}


def test_dynamic_rank_can_select_trend_capacity_leader_without_second_board() -> None:
    features = pd.DataFrame.from_records(
        [
            _feature("600001.SSE", 30.0, 0.95, 0, D1, 4),
            _feature("600002.SSE", 8.0, 0.40, 2, D2, 1),
            _feature("600003.SSE", 12.0, 0.60, 1, D3, 2),
            _feature("600004.SSE", 2.0, 0.20, 0, D3, 0),
        ]
    )

    ranks = rank_dynamic_wave_leaders(features)
    row = ranks.loc[ranks["leader_rank"].eq(1)].iloc[0]

    assert row["vt_symbol"] == "600001.SSE"
    assert {"trend_leader", "capacity_leader"}.issubset(row["leader_roles"])
    assert row["cumulative_limit_up_count"] == 0


def test_follower_mapping_stays_in_wave_and_preserves_rank_migration() -> None:
    ranks = pd.DataFrame.from_records(
        [
            _rank(D2, "600001.SSE", 1),
            _rank(D2, "600002.SSE", 2),
            _rank(D2, "600003.SSE", 3),
            _rank(D3, "600001.SSE", 1),
            _rank(D3, "600003.SSE", 2),
            _rank(D3, "600002.SSE", 3),
            {**_rank(D3, "600004.SSE", 2), "wave_id": "BK999:2026-07-01:1"},
        ]
    )
    bars = pd.DataFrame.from_records(
        [
            {"trade_date": day, "vt_symbol": symbol, "close_price": close}
            for symbol, closes in {
                "600001.SSE": (10.0, 11.0, 11.5, 12.0, 12.2),
                "600002.SSE": (10.0, 10.5, 10.8, 11.0, 11.2),
                "600003.SSE": (10.0, 10.2, 10.6, 11.3, 11.8),
                "600004.SSE": (10.0, 10.1, 10.2, 10.3, 10.4),
            }.items()
            for day, close in zip((D1, D2, D3, D4, D5), closes, strict=True)
        ]
    )

    mappings = build_dynamic_leader_mappings(ranks, bars, DATES)
    follower = mappings.loc[mappings["follower_symbol"].eq("600003.SSE")]

    assert set(mappings["wave_id"]) == {"BK001:2026-07-01:1"}
    assert follower["rank_at_response"].tolist() == [3, 2]
    assert follower.iloc[0]["realized_forward_1d_close_return_pct"] > 0


def test_candidate_uses_previous_session_dynamic_rank_only() -> None:
    candidates = pd.DataFrame.from_records(
        [
            {
                "trade_date": D4,
                "vt_symbol": "600003.SSE",
                "prior_sector_id": "BK001",
                "return_pct": 3.0,
            }
        ]
    )
    ranks = pd.DataFrame.from_records(
        [
            _rank(D3, "600001.SSE", 1),
            _rank(D3, "600003.SSE", 2),
            _rank(D4, "600003.SSE", 1),
        ]
    )

    result = attach_dynamic_wave_features(candidates, ranks, DATES)

    assert result.loc[0, "prior_dynamic_leader_rank"] == 2
    assert result.loc[0, "prior_wave_id"] == "BK001:2026-07-01:1"
    assert result.loc[0, "prior_wave_leader_symbol"] == "600001.SSE"


def test_candidate_uses_previous_session_expansion_timing_only() -> None:
    candidates = pd.DataFrame.from_records(
        [
            {
                "trade_date": D4,
                "vt_symbol": "600003.SSE",
                "prior_sector_id": "BK001",
                "return_pct": 3.0,
            }
        ]
    )
    ranks = pd.DataFrame.from_records(
        [
            {
                **_rank(D3, "600003.SSE", None),
                "wave_expansion_age_sessions": 1,
                "wave_expansion_onset": True,
                "wave_early_expansion": True,
                "wave_breadth_rising": True,
                "wave_turnover_rising": True,
                "wave_expansion_impulse": True,
                "wave_ladder_delta_1d": 0.2,
                "wave_turnover_delta_1d": 0.1,
                "wave_first_board_delta_1d": 1,
                "wave_sealed_delta_1d": 2,
            },
            {
                **_rank(D4, "600003.SSE", None),
                "wave_expansion_age_sessions": 2,
                "wave_expansion_onset": False,
                "wave_early_expansion": True,
            },
        ]
    )

    result = attach_dynamic_wave_features(candidates, ranks, DATES)

    assert result.loc[0, "prior_dynamic_trade_date"] == D3
    assert result.loc[0, "prior_wave_expansion_onset"]
    assert result.loc[0, "prior_wave_expansion_impulse"]
    assert result.loc[0, "prior_wave_expansion_age_sessions"] == 1


def test_candidate_prefers_dynamic_propagation_over_static_primary_concept() -> None:
    candidates = pd.DataFrame.from_records(
        [
            {
                "trade_date": D4,
                "vt_symbol": "600003.SSE",
                "prior_sector_id": "BK001",
                "return_pct": 3.0,
            }
        ]
    )
    static_primary = {
        **_rank(D3, "600003.SSE", None),
        "wave_phase": "confirmation",
        "wave_mainline_percentile": 0.95,
        "wave_expansion_impulse": False,
        "wave_early_expansion": False,
        "wave_breadth_rising": False,
    }
    propagation = {
        **_rank(D3, "600003.SSE", None),
        "sector_id": "BK002",
        "sector_name": "Propagating Concept",
        "wave_id": "BK002:2026-07-01:1",
        "wave_phase": "diffusion",
        "wave_mainline_percentile": 0.80,
        "wave_expansion_impulse": True,
        "wave_early_expansion": True,
        "wave_breadth_rising": True,
    }

    result = attach_dynamic_wave_features(
        candidates,
        pd.DataFrame.from_records([static_primary, propagation]),
        DATES,
    )

    assert result.loc[0, "prior_wave_match_mode"] == "dynamic_propagation_override"
    assert result.loc[0, "prior_static_primary_sector_id"] == "BK001"
    assert result.loc[0, "prior_wave_sector_id"] == "BK002"
    assert result.loc[0, "prior_wave_sector_name"] == "Propagating Concept"
    assert result.loc[0, "prior_wave_expansion_impulse"]


def test_candidate_inherits_prior_wave_leader_as_low_position_follower() -> None:
    candidates = pd.DataFrame.from_records(
        [
            {
                "trade_date": D4,
                "vt_symbol": "600004.SSE",
                "prior_sector_id": "BK001",
                "lane": "first_board",
                "target_board": 1,
                "return_pct": 3.0,
            }
        ]
    )
    leader = {
        **_rank(D3, "600001.SSE", 1),
        "leader_roles": ["trend_leader", "capacity_leader"],
        "leader_rank_1_tenure_sessions": 2,
    }
    follower = {
        **_rank(D3, "600004.SSE", None),
        "leader_roles": [],
    }

    result = attach_dynamic_wave_features(
        candidates,
        pd.DataFrame.from_records([leader, follower]),
        DATES,
    )

    assert pd.isna(result.loc[0, "prior_dynamic_leader_rank"])
    assert result.loc[0, "prior_has_dynamic_wave_leader"]
    assert result.loc[0, "prior_same_wave_low_position_follower"]
    assert result.loc[0, "prior_wave_leader_symbol"] == "600001.SSE"
    assert result.loc[0, "prior_wave_leader_rank_1_tenure"] == 2


def test_factor_evaluation_uses_all_formal_rows_not_portfolio_slots() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                "trade_date": date(2026, month, day),
                "return_pct": result,
                "signal_time": "10:00:00",
                "pool_rank": day,
                "vt_symbol": f"6000{day:02d}.SSE",
                "prior_dynamic_leader_rank": rank,
                "prior_dynamic_leader_roles": roles,
                "prior_wave_phase": phase,
            }
            for month, day, result, rank, roles, phase in (
                (3, 2, 3.0, 1, ["trend_leader", "capacity_leader"], "diffusion"),
                (4, 2, -2.0, 2, ["board_leader"], "diffusion"),
                (5, 6, 4.0, 3, ["trend_leader"], "acceleration"),
                (6, 2, -1.0, None, [], None),
                (7, 2, 2.0, 2, ["capacity_leader"], "divergence"),
            )
        ]
    )
    frame["signal_time"] = "10:00:00"
    frame["pool_rank"] = range(1, len(frame) + 1)

    results = evaluate_dynamic_wave_factors(frame)

    assert results["formal_baseline"]["full"]["closed_count"] == 5
    assert results["dynamic_top_3"]["full"]["closed_count"] == 4
    assert results["dynamic_leader_2_3"]["full"]["closed_count"] == 3


def test_factor_status_requires_both_time_splits_to_reach_sixty_percent() -> None:
    records = []
    for month, wins, losses in (
        (3, 5, 5),
        (4, 5, 5),
        (5, 7, 3),
        (6, 9, 1),
        (7, 9, 1),
    ):
        for sequence, result in enumerate([3.0] * wins + [-2.0] * losses, start=1):
            records.append(
                {
                    "trade_date": date(2026, month, sequence),
                    "vt_symbol": f"{month:02d}{sequence:04d}.SSE",
                    "lane": "first_board",
                    "target_board": 1,
                    "return_pct": result,
                    "signal_time": "10:00:00",
                    "pool_rank": sequence,
                    "prior_wave_phase": "diffusion",
                    "prior_has_dynamic_wave_leader": True,
                    "prior_same_wave_low_position_follower": True,
                }
            )

    results = evaluate_dynamic_wave_factors(pd.DataFrame.from_records(records))

    factor = results["low_position_follower_in_diffusion"]
    assert factor["full"]["win_rate_pct"] == 70.0
    assert factor["discovery_3_5"]["win_rate_pct"] < 60.0
    assert factor["holdout_6_7"]["win_rate_pct"] >= 60.0
    assert factor["status"] == "time_split_reversal"


def test_factor_evaluation_targets_low_position_followers_under_wave_leader() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                "trade_date": D2,
                "vt_symbol": "600002.SSE",
                "lane": "first_board",
                "target_board": 1,
                "return_pct": 3.0,
                "prior_dynamic_leader_rank": None,
                "prior_dynamic_leader_roles": [],
                "prior_wave_phase": "acceleration",
                "prior_wave_mainline_percentile": 0.90,
                "prior_wave_turnover_strength": 0.85,
                "prior_turnover_strength": 0.85,
                "prior_has_dynamic_wave_leader": True,
                "prior_same_wave_low_position_follower": True,
                "prior_wave_leader_roles": ["trend_leader", "capacity_leader"],
                "prior_wave_leader_rank_1_tenure": 1,
            },
            {
                "trade_date": D3,
                "vt_symbol": "600003.SSE",
                "lane": "two_to_three",
                "target_board": 3,
                "return_pct": -2.0,
                "prior_dynamic_leader_rank": None,
                "prior_dynamic_leader_roles": [],
                "prior_wave_phase": "diffusion",
                "prior_wave_mainline_percentile": 0.90,
                "prior_wave_turnover_strength": 0.85,
                "prior_turnover_strength": 0.85,
                "prior_has_dynamic_wave_leader": True,
                "prior_same_wave_low_position_follower": True,
                "prior_wave_leader_roles": ["board_leader"],
                "prior_wave_leader_rank_1_tenure": 2,
            },
            {
                "trade_date": D4,
                "vt_symbol": "600004.SSE",
                "lane": "first_board",
                "target_board": 1,
                "return_pct": -1.0,
                "prior_dynamic_leader_rank": None,
                "prior_dynamic_leader_roles": [],
                "prior_wave_phase": None,
                "prior_wave_mainline_percentile": None,
                "prior_wave_turnover_strength": None,
                "prior_turnover_strength": 0.40,
                "prior_has_dynamic_wave_leader": False,
                "prior_same_wave_low_position_follower": False,
                "prior_wave_leader_roles": [],
                "prior_wave_leader_rank_1_tenure": None,
            },
            {
                "trade_date": D5,
                "vt_symbol": "600005.SSE",
                "lane": "first_board",
                "target_board": 1,
                "return_pct": 1.0,
                "prior_dynamic_leader_rank": None,
                "prior_dynamic_leader_roles": [],
                "prior_wave_phase": "diffusion",
                "prior_wave_mainline_percentile": 0.90,
                "prior_wave_turnover_strength": 0.40,
                "prior_turnover_strength": 0.85,
                "prior_has_dynamic_wave_leader": True,
                "prior_same_wave_low_position_follower": True,
                "prior_wave_leader_roles": ["board_leader"],
                "prior_wave_leader_rank_1_tenure": 1,
            },
        ]
    )
    frame["signal_time"] = "10:00:00"
    frame["pool_rank"] = range(1, len(frame) + 1)

    results = evaluate_dynamic_wave_factors(frame)

    assert results["wave_leader_present"]["full"]["closed_count"] == 3
    assert results["low_position_follower_under_leader"]["full"]["closed_count"] == 3
    assert results["first_board_low_position_follower"]["full"]["closed_count"] == 2
    assert results["two_to_three_low_position_follower"]["full"]["closed_count"] == 1
    assert results["turnover_capacity_ge_080_reference"]["full"]["closed_count"] == 3
    assert results["turnover_capacity_low_position_follower"]["full"]["closed_count"] == 2
    assert (
        results["mainline_turnover_ge_080_low_position_follower"]["full"][
            "closed_count"
        ]
        == 2
    )
    assert (
        results["trend_capacity_leader_low_position_follower"]["full"][
            "closed_count"
        ]
        == 1
    )


def test_quality_core_and_early_expansion_are_evaluated_without_confirmed_leader() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                "trade_date": D2,
                "vt_symbol": "600001.SSE",
                "lane": "first_board",
                "target_board": 1,
                "signal_time": "10:00:00",
                "pool_rank": 1,
                "return_pct": 3.0,
                "prior_limit_count_126": 3,
                "prior_industry_turnover_ratio_5d": 1.2,
                "prior_wave_early_expansion": True,
                "prior_wave_expansion_onset": True,
                "prior_wave_expansion_impulse": True,
                "prior_has_dynamic_wave_leader": False,
            },
            {
                "trade_date": D3,
                "vt_symbol": "600002.SSE",
                "lane": "first_board",
                "target_board": 1,
                "signal_time": "10:00:00",
                "pool_rank": 2,
                "return_pct": -2.0,
                "prior_limit_count_126": 8,
                "prior_industry_turnover_ratio_5d": 1.2,
                "prior_wave_early_expansion": True,
                "prior_wave_expansion_onset": False,
                "prior_wave_expansion_impulse": False,
                "prior_has_dynamic_wave_leader": True,
            },
        ]
    )

    results = evaluate_dynamic_wave_factors(frame)

    assert results["wave_early_expansion"]["full"]["closed_count"] == 2
    assert results["quality_reconstruction_core"]["full"]["closed_count"] == 1
    assert results["quality_core_wave_early_expansion"]["full"]["closed_count"] == 1
    assert (
        results["quality_core_probable_guide_early_expansion"]["full"][
            "closed_count"
        ]
        == 0
    )


def _concept_panel() -> pd.DataFrame:
    values = [
        (D1, 0.85, 0.80, 0.70, 0.90, 1, 1, 2.0),
        (D2, 0.82, 0.78, 0.72, 0.88, 0, 1, 1.0),
        (D3, 0.70, 0.65, 0.60, 0.76, 0, 1, 0.5),
        (D4, 0.60, 0.55, 0.52, 0.65, 0, 0, -0.2),
        (D5, 0.40, 0.35, 0.60, 0.42, 0, 0, -1.0),
        (D6, 0.38, 0.30, 0.40, 0.35, 0, 0, -1.2),
        (D7, 0.88, 0.84, 0.72, 0.92, 1, 1, 2.5),
        (D8, 0.90, 0.82, 0.75, 0.94, 0, 1, 1.5),
    ]
    return pd.DataFrame.from_records(
        [
            {
                "trade_date": day,
                "sector_id": "BK001",
                "sector_name": "Dynamic Concept",
                "index_strength": index,
                "turnover_strength": turnover,
                "ladder_strength": ladder,
                "mainline_percentile": mainline,
                "first_board_count": first_boards,
                "sealed_count": sealed,
                "return_1d_pct": change,
                "close_price": 100.0 + position,
                "membership_evidence_level": "point_in_time_complete",
            }
            for position, (
                day,
                index,
                turnover,
                ladder,
                mainline,
                first_boards,
                sealed,
                change,
            ) in enumerate(values)
        ]
    )


def _waves(end: date) -> pd.DataFrame:
    rows = _concept_panel()
    rows = rows.loc[rows["trade_date"].le(end)].copy()
    rows["wave_id"] = "BK001:2026-07-01:1"
    rows["wave_start_date"] = D1
    rows["wave_age_sessions"] = range(1, len(rows) + 1)
    rows["wave_phase"] = "diffusion"
    return rows


def _inputs(end: date) -> CapitalMainlineInputs:
    dates = tuple(day for day in DATES if day <= end)
    bars = []
    for symbol, base, changes, turnovers in (
        ("600001.SSE", 10.0, (5.0, 4.0, 3.0, 2.0, 1.0, -1.0, 2.0, 3.0), (300, 330, 360, 390, 350, 320, 370, 400)),
        ("600002.SSE", 10.0, (1.0, 10.0, -2.0, 1.0, 0.0, -1.0, 1.0, 2.0), (100, 120, 90, 95, 80, 70, 85, 90)),
        ("600003.SSE", 10.0, (-1.0, 1.0, 6.0, 4.0, 3.0, 2.0, 1.0, 1.0), (80, 85, 130, 150, 160, 170, 180, 190)),
    ):
        close = base
        for day, change, turnover in zip(DATES, changes, turnovers, strict=True):
            if day > end:
                break
            close *= 1.0 + change / 100.0
            bars.append(
                {
                    "trade_date": day,
                    "vt_symbol": symbol,
                    "name": symbol,
                    "close_price": close,
                    "change_pct": change,
                    "turnover": float(turnover),
                    "turnover_rate": 5.0,
                }
            )
    return CapitalMainlineInputs(
        trade_dates=dates,
        concept_bars=(),
        sector_fund_flows=(),
        stock_fund_flows=(),
        memberships=(),
        membership_scopes=(),
        membership_counts=(),
        current_memberships=(),
        stock_bars=tuple(bars),
        limit_up_events=(),
        sentiment_points=(),
        formal_candidate_days=(),
        coverage={},
        fingerprints={},
    )


def _contexts(end: date) -> dict[date, MembershipContext]:
    symbols = frozenset({"600001.SSE", "600002.SSE", "600003.SSE"})
    context = MembershipContext(
        evidence_level=EvidenceLevel.POINT_IN_TIME,
        snapshot_date=D1,
        by_symbol={symbol: ("BK001",) for symbol in symbols},
        by_sector={"BK001": symbols},
        member_counts={"BK001": len(symbols)},
        sector_names={"BK001": "Dynamic Concept"},
    )
    return {day: context for day in DATES if day <= end}


def _feature(
    symbol: str,
    relative_return: float,
    turnover_percentile: float,
    limit_count: int,
    first_strength_date: date,
    response_count: int,
) -> dict[str, object]:
    return {
        "trade_date": D4,
        "sector_id": "BK001",
        "sector_name": "Dynamic Concept",
        "wave_id": "BK001:2026-07-01:1",
        "wave_phase": "diffusion",
        "vt_symbol": symbol,
        "name": symbol,
        "relative_wave_return_pct": relative_return,
        "stock_return_3d_pct": relative_return,
        "stock_return_5d_pct": relative_return,
        "turnover_percentile": turnover_percentile,
        "cumulative_limit_up_count": limit_count,
        "effective_board_streak": limit_count,
        "first_strength_date": first_strength_date,
        "response_member_count_asof": response_count,
    }


def _rank(day: date, symbol: str, rank: int | None) -> dict[str, object]:
    score_rank = rank if rank is not None else 4
    return {
        "trade_date": day,
        "sector_id": "BK001",
        "sector_name": "Dynamic Concept",
        "wave_id": "BK001:2026-07-01:1",
        "wave_phase": "diffusion",
        "vt_symbol": symbol,
        "name": symbol,
        "leader_rank": rank,
        "leader_roles": ["trend_leader"],
        "leadership_score": 0.9 - score_rank * 0.1,
        "leadership_tenure_sessions": 1,
        "leader_rank_1_tenure_sessions": int(rank == 1),
    }
