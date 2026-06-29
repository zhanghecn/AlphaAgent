"""Tests for mainline replay pure-function algorithms."""

import pytest

from alphaagent.server.services.mainline_replay import (
    compute_fund_strength_batch,
    compute_raw_sector_delta,
    minmax_normalize,
    pearson,
)


# ── delta + 归一化 + fund_strength ──


def test_return_pct_from_close_prices():
    raw = compute_raw_sector_delta(
        bars_t1_close=100.0,
        bars_t2_close=110.0,
        range_turnover=[1e8, 2e8],
        prev_range_turnover=[1e8, 1e8],
        score_t1={"heat_score": 60.0, "fund_score": 55.0, "trend_state": "ROTATION", "rank_return": 10},
        score_t2={"heat_score": 75.0, "fund_score": 70.0, "trend_state": "MAINLINE_UP", "rank_return": 3},
        range_main_inflow=[5e7, 8e7],
    )
    assert raw["return_pct"] == pytest.approx(0.10)
    assert raw["accumulated_turnover"] == 3e8
    assert raw["volume_ratio"] == 1.5  # avg(1.5e8) / avg(1e8)
    assert raw["delta_heat"] == 15.0
    assert raw["delta_fund"] == 15.0
    assert raw["trend_transition"] == "ROTATION->MAINLINE_UP"
    assert raw["rank_change"] == -7  # 3 - 10
    assert raw["accumulated_main_inflow"] == 1.3e8
    assert raw["fund_inflow_available"] is True


def test_fund_inflow_unavailable_when_none():
    raw = compute_raw_sector_delta(
        bars_t1_close=100.0,
        bars_t2_close=100.0,
        range_turnover=[1e8],
        prev_range_turnover=[1e8],
        score_t1=None,
        score_t2=None,
        range_main_inflow=None,
    )
    assert raw["fund_inflow_available"] is False
    assert raw["accumulated_main_inflow"] is None
    assert raw["delta_heat"] is None  # score 缺失


def test_minmax_normalize_basic():
    assert minmax_normalize([0.0, 5.0, 10.0]) == [0.0, 0.5, 1.0]


def test_minmax_normalize_empty():
    assert minmax_normalize([]) == []


def test_minmax_normalize_constant_returns_mid():
    # 全相等：返回 0.5 中值，避免都 0 导致 fund_strength 排序失效
    assert minmax_normalize([3.0, 3.0, 3.0]) == [0.5, 0.5, 0.5]


def test_fund_strength_batch_weights_and_range():
    raws = [
        {"return_pct": 0.10, "volume_ratio": 1.5, "delta_fund": 15.0, "delta_heat": 15.0},
        {"return_pct": -0.05, "volume_ratio": 0.8, "delta_fund": -10.0, "delta_heat": -5.0},
    ]
    strengths = compute_fund_strength_batch(raws)
    assert len(strengths) == 2
    assert strengths[0] > strengths[1]  # 涨的板块更强
    for s in strengths:
        assert s is not None and 0.0 <= s <= 1.0


def test_fund_strength_batch_skips_incomplete():
    raws = [
        {"return_pct": 0.10, "volume_ratio": 1.5, "delta_fund": 15.0, "delta_heat": 15.0},
        {"return_pct": None, "volume_ratio": 1.5, "delta_fund": 15.0, "delta_heat": 15.0},
    ]
    strengths = compute_fund_strength_batch(raws)
    assert strengths[0] is not None
    assert strengths[1] is None


# ── 关联反推 ──


def test_pearson_perfect_positive():
    assert pearson([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0]) == 1.0


def test_pearson_too_few_returns_none():
    assert pearson([1.0, 2.0], [2.0, 3.0]) is None


def test_pearson_zero_variance_returns_none():
    assert pearson([3.0, 3.0, 3.0], [1.0, 2.0, 3.0]) is None


# ── compute_relations_aligned（按共同日期自动对齐） ──


def test_aligned_filters_low_common_and_ranks():
    from alphaagent.server.services.mainline_replay import compute_relations_aligned

    target_map = {1: 0.1, 2: 0.2, 3: 0.0, 4: 0.3, 5: 0.1}
    cand_a = {1: 0.11, 2: 0.22, 3: 0.01, 4: 0.33, 5: 0.11}  # 强正相关，全共同
    cand_b = {1: -0.1, 3: -0.05, 5: -0.15}                 # 部分日期，负相关，共同>=3
    cand_c = {1: 0.0}                                       # 仅1个共同点 -> 过滤
    res = compute_relations_aligned(
        target_map=target_map,
        candidate_maps={"A": cand_a, "B": cand_b, "C": cand_c},
        target_fund_map=None,
        candidate_fund_maps=None,
        target_members={100, 101},
        candidate_members={"A": {100, 102}, "B": set(), "C": set()},
        min_points=3,
    )
    ids = [r["sector_id"] for r in res]
    assert "A" in ids and "B" in ids
    assert "C" not in ids  # 共同点 <3 被过滤
    by = {r["sector_id"]: r for r in res}
    assert by["A"]["relation_score"] > by["B"]["relation_score"]


def test_aligned_uses_full_candidate_members_for_jaccard():
    from alphaagent.server.services.mainline_replay import compute_relations_aligned

    target_map = {1: 0.1, 2: 0.2, 3: 0.3}
    cand = {1: 0.1, 2: 0.2, 3: 0.3}
    res = compute_relations_aligned(
        target_map=target_map,
        candidate_maps={"A": cand},
        target_members={"S1", "S2", "S3", "S4"},
        candidate_members={"A": {"S1", "S2", "S5", "S6", "S7", "S8"}},
        min_points=3,
    )

    item = res[0]
    assert item["overlap_count"] == 2
    assert item["overlap"] == pytest.approx(0.25)
    assert item["evidence"]["shared_symbols"] == ["S1", "S2"]
    assert item["common_points"] == 3


def test_aligned_keeps_zero_overlap_high_comovement_candidate():
    from alphaagent.server.services.mainline_replay import compute_relations_aligned

    target_map = {1: 0.1, 2: 0.2, 3: -0.1, 4: 0.05}
    zero_overlap = {1: 0.2, 2: 0.4, 3: -0.2, 4: 0.1}
    res = compute_relations_aligned(
        target_map=target_map,
        candidate_maps={"B": zero_overlap},
        target_members={"S1", "S2"},
        candidate_members={"B": {"S3", "S4"}},
        relation_groups={"B": "theme"},
        min_points=3,
    )

    assert [item["sector_id"] for item in res] == ["B"]
    assert res[0]["overlap_count"] == 0
    assert res[0]["corr"] == pytest.approx(1.0)
    assert res[0]["relation_group"] == "theme"


def test_aligned_prioritizes_status_relations_for_status_target():
    from alphaagent.server.services.mainline_replay import compute_relations_aligned

    target_map = {1: 0.1, 2: 0.2, 3: 0.0, 4: 0.3}
    res = compute_relations_aligned(
        target_map=target_map,
        candidate_maps={
            "THEME": {1: 0.1, 2: 0.2, 3: 0.0, 4: 0.3},
            "STATUS": {1: 0.08, 2: 0.18, 3: 0.01, 4: 0.28},
        },
        target_members={"S1", "S2"},
        candidate_members={
            "THEME": {"S3", "S4"},
            "STATUS": {"S1", "S5"},
        },
        relation_groups={"THEME": "theme", "STATUS": "style_status"},
        target_relation_group="style_status",
        min_points=3,
    )

    assert [item["sector_id"] for item in res][:2] == ["STATUS", "THEME"]
