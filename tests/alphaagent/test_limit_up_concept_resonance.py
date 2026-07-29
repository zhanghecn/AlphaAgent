from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.concept_resonance import (
    aggregate_concept_strength,
    attach_candidate_concepts,
    build_membership_index,
    concept_state,
    is_execution_concept,
    rank_concepts,
    replay_radar_concepts,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_membership_index_keeps_pcb_and_excludes_style_labels() -> None:
    index = build_membership_index(
        [
            {
                "vt_symbol": "600183.SSE",
                "stock_name": "生益科技",
                "sector_id": "BK0877",
                "sector_name": "PCB",
                "sector_type": "theme",
            },
            {
                "vt_symbol": "600183.SSE",
                "stock_name": "生益科技",
                "sector_id": "BK0821",
                "sector_name": "MSCI中国",
                "sector_type": "theme",
            },
            {
                "vt_symbol": "002463.SZSE",
                "stock_name": "沪电股份",
                "sector_id": "BK0877",
                "sector_name": "PCB",
                "sector_type": "theme",
            },
        ],
        snapshot_date="2026-07-13",
    )

    assert index["snapshot_date"] == "2026-07-13"
    assert index["by_symbol"]["600183.SSE"] == ["BK0877"]
    assert index["by_concept"]["BK0877"]["members"] == {
        "600183.SSE",
        "002463.SZSE",
    }


def test_execution_concept_excludes_index_and_attribute_boards() -> None:
    excluded = (
        "百元股",
        "标准普尔",
        "富时罗素",
        "历史新高",
        "百日新高",
        "最近多板",
        "次新股",
        "超跌股",
        "趋势股",
        "反转股",
        "题材股",
        "微利股",
        "红利股",
        "中报预增",
        "2026中报首亏",
        "2026中报预减",
        "QFII重仓",
        "社保重仓",
        "破净股",
        "HS300_",
        "上证180_",
        "创业板综",
    )

    assert all(not is_execution_concept(name) for name in excluded)
    assert is_execution_concept("存储芯片") is True
    assert is_execution_concept("低空经济") is True


def test_membership_index_filters_st_and_non_main_board() -> None:
    index = build_membership_index(
        [
            {"vt_symbol": "600001.SSE", "stock_name": "*ST测试", "sector_id": "A", "sector_name": "PCB"},
            {"vt_symbol": "300001.SZSE", "stock_name": "创业板", "sector_id": "A", "sector_name": "PCB"},
        ],
        snapshot_date="2026-07-13",
    )

    assert index["by_symbol"] == {}


def test_aggregate_concept_strength_calculates_realtime_pcb_diffusion() -> None:
    membership = _membership(5)
    quotes = [
        _quote(index, change)
        for index, change in enumerate((9.9, 8.2, 6.5, 5.1, -1.0))
    ]

    rows = aggregate_concept_strength(
        quotes,
        membership,
        captured_at=datetime(2026, 7, 14, 13, 3, tzinfo=SHANGHAI),
        history_by_concept={},
    )

    pcb = next(row for row in rows if row["concept_id"] == "BK0877")
    assert pcb["observed_count"] == 5
    assert pcb["coverage_ratio"] == 1.0
    assert pcb["rise_count"] == 4
    assert pcb["strong_5_count"] == 4
    assert pcb["median_change_pct"] == 6.5


def test_concept_strength_uses_only_earlier_frames_for_acceleration() -> None:
    history = {
        "BK0877": [
            {"captured_at": "2026-07-14T12:58:00+08:00", "median_change_pct": 0.5, "strong_5_count": 0, "turnover": 500.0},
            {"captured_at": "2026-07-14T13:00:00+08:00", "median_change_pct": 1.0, "strong_5_count": 0, "turnover": 1_000.0},
            {"captured_at": "2026-07-14T13:02:00+08:00", "median_change_pct": 2.0, "strong_5_count": 1, "turnover": 2_000.0},
            {"captured_at": "2026-07-14T13:04:00+08:00", "median_change_pct": 99.0, "strong_5_count": 99, "turnover": 99_000.0},
        ]
    }
    row = aggregate_concept_strength(
        [_quote(0, 3.0)],
        _membership(1),
        captured_at=datetime(2026, 7, 14, 13, 3, tzinfo=SHANGHAI),
        history_by_concept=history,
    )[0]

    assert row["change_acceleration_1m"] == 1.0
    assert row["change_acceleration_3m"] == 2.0
    assert row["turnover_acceleration_1m"] > 0


def test_concept_acceleration_requires_all_fresh_anchors() -> None:
    history = {
        "BK0877": [
            {"captured_at": "2026-07-14T12:56:00+08:00", "median_change_pct": 0.5, "strong_5_count": 0, "turnover": 500.0},
            {"captured_at": "2026-07-14T13:00:00+08:00", "median_change_pct": 1.0, "strong_5_count": 0, "turnover": 1_000.0},
            {"captured_at": "2026-07-14T13:02:00+08:00", "median_change_pct": 2.0, "strong_5_count": 1, "turnover": 2_000.0},
        ]
    }

    row = aggregate_concept_strength(
        [_quote(0, 3.0)],
        _membership(1),
        captured_at=datetime(2026, 7, 14, 13, 3, tzinfo=SHANGHAI),
        history_by_concept=history,
    )[0]

    assert all(
        row[f"{metric}_acceleration_{minutes}m"] is None
        for metric in ("change", "turnover")
        for minutes in (1, 3, 5)
    )


def test_rank_concepts_assigns_best_strength_to_lowest_percentile() -> None:
    ranked = rank_concepts(
        [
            _concept("A", median_change_pct=4.0, rise_ratio=0.9, strong_5_count=5),
            _concept("B", median_change_pct=1.0, rise_ratio=0.6, strong_5_count=1),
        ]
    )

    assert ranked[0]["concept_id"] == "A"
    assert ranked[0]["strength_rank"] == 1
    assert ranked[0]["strength_percentile"] == 0.5


def test_concept_launch_uses_absolute_internal_breadth_not_market_percentile() -> None:
    row = _concept(
        "BK0896",
        observed_count=43,
        rise_ratio=41 / 43,
        median_change_pct=2.73,
        strong_5_count=4,
        strong_7_count=2,
        near_limit_count=2,
        strength_percentile=0.50,
    )

    assert concept_state(row) == "launch"


def test_concept_launch_scales_strong_stock_requirement_with_member_count() -> None:
    below = _concept(
        "LARGE",
        observed_count=101,
        rise_ratio=0.90,
        median_change_pct=3.0,
        strong_5_count=5,
        strong_7_count=2,
        near_limit_count=1,
    )
    passed = {**below, "strong_5_count": 6}

    assert concept_state(below) != "launch"
    assert concept_state(passed) == "launch"


def test_concept_warming_uses_absolute_internal_acceleration() -> None:
    row = _concept(
        "WARM",
        observed_count=30,
        rise_ratio=0.65,
        median_change_pct=1.0,
        strong_5_count=2,
        change_acceleration_3m=0.01,
        strength_percentile=1.0,
    )

    assert concept_state(row) == "warming"


def test_concept_state_keeps_coverage_and_ebb_ahead_of_launch() -> None:
    launch = _concept(
        "RISK",
        observed_count=20,
        rise_ratio=0.90,
        median_change_pct=4.0,
        strong_5_count=5,
        strong_7_count=3,
        near_limit_count=2,
        touched_count=3,
        failed_count=2,
    )

    assert concept_state({**launch, "coverage_ratio": 0.899}) == "unavailable"
    assert concept_state(launch) == "ebb"


def test_concept_launch_requires_rise_ratio_and_median_change_thresholds() -> None:
    launch = _concept(
        "BOUNDARY",
        observed_count=20,
        rise_ratio=0.80,
        median_change_pct=2.5,
        strong_5_count=3,
        near_limit_count=1,
    )

    assert concept_state({**launch, "rise_ratio": 0.799}) != "launch"
    assert concept_state({**launch, "median_change_pct": 2.499}) != "launch"
    assert concept_state(launch) == "launch"


def test_concept_launch_accepts_near_limit_or_two_strong_7_members() -> None:
    launch = _concept(
        "EVIDENCE",
        observed_count=20,
        rise_ratio=0.80,
        median_change_pct=2.5,
        strong_5_count=3,
    )

    assert concept_state(launch) != "launch"
    assert concept_state({**launch, "near_limit_count": 1}) == "launch"
    assert concept_state({**launch, "strong_7_count": 2}) == "launch"


def test_attach_candidate_concepts_selects_strongest_execution_concept() -> None:
    candidates = [
        {
            "vt_symbol": "600183.SSE",
            "change_pct": 9.2,
            "turnover": 5_000_000_000,
        }
    ]
    snapshot = {
        "membership": {"by_symbol": {"600183.SSE": ["BK0877"]}},
        "concepts_by_id": {
            "BK0877": {
                "concept_id": "BK0877",
                "concept_name": "PCB",
                "concept_state": "launch",
                "strength_score": 92.0,
                "strength_rank": 1,
                "near_limit_count": 3,
                "touched_count": 2,
                "sealed_count": 1,
                "failed_count": 1,
                "change_acceleration_1m": 0.2,
                "change_acceleration_3m": 0.7,
                "change_acceleration_5m": 1.1,
                "turnover_acceleration_1m": 12_000_000.0,
                "turnover_acceleration_3m": 30_000_000.0,
                "turnover_acceleration_5m": 55_000_000.0,
            }
        },
        "data_quality": {"age_seconds": 12.0, "trigger_allowed": False},
    }

    attach_candidate_concepts(candidates, snapshot)

    assert candidates[0]["concept_id"] == "BK0877"
    assert candidates[0]["concept_name"] == "PCB"
    assert candidates[0]["concept_leader_rank"] == 1
    assert candidates[0]["concept_snapshot_age_seconds"] == 12.0
    assert candidates[0]["concept_trigger_allowed"] is False
    assert candidates[0]["concept_near_limit_count"] == 3
    assert candidates[0]["concept_touched_count"] == 2
    assert candidates[0]["concept_sealed_count"] == 1
    assert candidates[0]["concept_failed_count"] == 1
    assert candidates[0]["concept_change_acceleration_1m"] == 0.2
    assert candidates[0]["concept_change_acceleration_3m"] == 0.7
    assert candidates[0]["concept_change_acceleration_5m"] == 1.1
    assert candidates[0]["concept_turnover_acceleration_1m"] == 12_000_000.0
    assert candidates[0]["concept_turnover_acceleration_3m"] == 30_000_000.0
    assert candidates[0]["concept_turnover_acceleration_5m"] == 55_000_000.0


def test_attach_candidate_concepts_keeps_every_real_theme_with_its_rank() -> None:
    candidates = [
        {"vt_symbol": "600001.SSE", "change_pct": 8.0, "turnover": 800.0},
        {"vt_symbol": "600002.SSE", "change_pct": 7.0, "turnover": 700.0},
    ]
    snapshot = {
        "membership": {
            "by_symbol": {
                "600001.SSE": ["A", "B"],
                "600002.SSE": ["A"],
            }
        },
        "concepts_by_id": {
            "A": {
                "concept_id": "A",
                "concept_name": "存储芯片",
                "concept_state": "warming",
                "strength_score": 80.0,
                "strength_rank": 2,
            },
            "B": {
                "concept_id": "B",
                "concept_name": "机器人",
                "concept_state": "launch",
                "strength_score": 90.0,
                "strength_rank": 1,
            },
        },
        "data_quality": {"age_seconds": 10.0, "trigger_allowed": True},
    }

    attach_candidate_concepts(candidates, snapshot)

    assert candidates[0]["concept_id"] == "B"
    assert candidates[0]["concept_candidate_count"] == 2
    assert [
        (row["concept_id"], row["leader_rank"])
        for row in candidates[0]["concept_candidates"]
    ] == [("B", 1), ("A", 1)]
    assert candidates[1]["concept_candidates"][0]["leader_rank"] == 2


def test_attach_candidate_concepts_prefers_candidate_specific_execution_fit() -> None:
    target = {
        "vt_symbol": "600001.SSE",
        "change_pct": 8.0,
        "turnover": 800.0,
    }
    broad_leaders = [
        {
            "vt_symbol": f"60000{index}.SSE",
            "change_pct": 10.0 - index / 10,
            "turnover": 1_000.0 - index,
        }
        for index in range(2, 7)
    ]
    candidates = [target, *broad_leaders]
    snapshot = {
        "membership": {
            "by_symbol": {
                "600001.SSE": ["BROAD", "SPECIFIC"],
                **{
                    str(candidate["vt_symbol"]): ["BROAD"]
                    for candidate in broad_leaders
                },
            }
        },
        "concepts_by_id": {
            "BROAD": {
                "concept_id": "BROAD",
                "concept_name": "宽泛热门概念",
                "concept_state": "launch",
                "strength_score": 95.0,
                "strength_rank": 1,
            },
            "SPECIFIC": {
                "concept_id": "SPECIFIC",
                "concept_name": "个股主导细分概念",
                "concept_state": "launch",
                "strength_score": 75.0,
                "strength_rank": 20,
            },
        },
        "data_quality": {"age_seconds": 10.0, "trigger_allowed": True},
    }

    attach_candidate_concepts(candidates, snapshot)

    assert target["concept_id"] == "SPECIFIC"
    assert target["concept_leader_rank"] == 1
    assert [
        (row["concept_id"], row["leader_rank"])
        for row in target["concept_candidates"]
    ] == [("SPECIFIC", 1), ("BROAD", 6)]


def test_20260714_pcb_replay_uses_prior_membership_and_preseal_frames_only() -> None:
    membership = build_membership_index(
        [
            {
                "vt_symbol": f"6001{index:02d}.SSE",
                "stock_name": f"PCB样本{index}",
                "sector_id": "BK0877",
                "sector_name": "PCB",
                "sector_type": "theme",
            }
            for index in range(9)
        ],
        snapshot_date="2026-07-13",
    )
    changes = [9.95, 9.8, 9.7, 9.6, 9.5, 9.3, 9.1, 6.8, 5.4]
    frames = [
        {
            "captured_at": "2026-07-14T13:04:21+08:00",
            "items": [
                {
                    "vt_symbol": f"6001{index:02d}.SSE",
                    "name": f"PCB样本{index}",
                    "change_pct": change,
                    "turnover": 1_000_000_000 + index,
                }
                for index, change in enumerate(changes)
            ],
        }
    ]

    report = replay_radar_concepts(
        frames,
        membership,
        signal_at="2026-07-14T13:04:21+08:00",
    )

    assert report["membership_snapshot_date"] == "2026-07-13"
    assert report["future_frame_count"] == 0
    assert report["concepts"]["BK0877"]["radar_5_count"] == 9
    assert report["concepts"]["BK0877"]["within_1pct_count"] == 7


def _membership(count: int) -> dict[str, object]:
    return build_membership_index(
        [
            {
                "vt_symbol": f"60000{index}.SSE",
                "stock_name": f"PCB{index}",
                "sector_id": "BK0877",
                "sector_name": "PCB",
                "sector_type": "theme",
            }
            for index in range(count)
        ],
        snapshot_date="2026-07-13",
    )


def _quote(index: int, change: float) -> dict[str, object]:
    return {
        "vt_symbol": f"60000{index}.SSE",
        "name": f"PCB{index}",
        "change_pct": change,
        "turnover": 100_000_000 + index,
        "previous_close": 10.0,
        "last_price": 10.0 * (1 + change / 100),
    }


def _concept(concept_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "concept_id": concept_id,
        "concept_name": concept_id,
        "coverage_ratio": 1.0,
        "observed_count": 10,
        "median_change_pct": 0.0,
        "weighted_change_pct": 0.0,
        "rise_ratio": 0.0,
        "strong_5_count": 0,
        "near_limit_count": 0,
        "touched_count": 0,
        "sealed_count": 0,
        "failed_count": 0,
        "change_acceleration_3m": 0.0,
        "turnover_acceleration_3m": 0.0,
        "strong_7_count": 0,
    }
    row.update(overrides)
    return row
