from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.concept_resonance import (
    aggregate_concept_strength,
    attach_candidate_concepts,
    build_membership_index,
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
