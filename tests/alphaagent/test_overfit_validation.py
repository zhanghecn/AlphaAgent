"""overfit_validation 单测：验证 CPCV / PBO / Deflated Sharpe 的纯数学边界。

只覆盖纯函数（cpcv_split / PBO / DSR / skewness / kurtosis / daily_returns 提取），
不依赖数据库与 run_backtest。cpcv_analyze 的集成验证见基线诊断（阶段 0 任务 11）。
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from alphaagent.server.services.backtest import overfit_validation as ov


# ===== cpcv_split =====

def _dates(n: int) -> list[date]:
    return [date(2025, 1, 1) + timedelta(days=i) for i in range(n)]


def test_cpcv_split_combination_count():
    """C(6,2)=15 条路径，C(8,3)=56 条路径。"""
    assert len(ov.cpcv_split(_dates(300), n_groups=6, n_test_groups=2, purge_days=0, embargo_days=0)) == 15
    assert len(ov.cpcv_split(_dates(400), n_groups=8, n_test_groups=3, purge_days=0, embargo_days=0)) == 56


def test_cpcv_split_invalid_groups():
    with pytest.raises(ValueError):
        ov.cpcv_split(_dates(300), n_groups=1)
    with pytest.raises(ValueError):
        ov.cpcv_split(_dates(300), n_groups=6, n_test_groups=6)


def test_cpcv_split_insufficient_dates():
    with pytest.raises(ValueError):
        ov.cpcv_split(_dates(3), n_groups=6)


def test_cpcv_split_train_test_disjoint():
    """train 与 test 日期必须不相交。"""
    paths = ov.cpcv_split(_dates(300), n_groups=6, n_test_groups=2, purge_days=5, embargo_days=3)
    assert len(paths) > 0
    for p in paths:
        assert set(p["train"]).isdisjoint(set(p["test"]))


def test_cpcv_split_purge_embargo_reduces_train():
    """开启 purge/embargo 后 train 不应比关闭时更多。"""
    no_purge = ov.cpcv_split(_dates(300), n_groups=6, n_test_groups=2, purge_days=0, embargo_days=0)
    with_purge = ov.cpcv_split(_dates(300), n_groups=6, n_test_groups=2, purge_days=10, embargo_days=10)
    for p_no, p_yes in zip(no_purge, with_purge):
        assert len(p_yes["train"]) <= len(p_no["train"])


# ===== PBO =====

def test_pbo_all_below_median_is_one():
    """IS 最优 variant 全部在 OOS 落到中位数以下 → PBO=1（严重过拟合）。"""
    report = ov.probability_of_backtest_overfitting([0, 0, 0, 0], n_variants=10)
    assert report["pbo"] == 1.0
    assert report["logit_pbo"] == float("inf")


def test_pbo_all_above_median_is_zero():
    """IS 最优 variant 全部高于中位数 → PBO=0（稳健）。"""
    report = ov.probability_of_backtest_overfitting([9, 9, 9, 9], n_variants=10)
    assert report["pbo"] == 0.0
    assert report["logit_pbo"] == float("-inf")


def test_pbo_half_below_is_half():
    # 中位数 = (10-1)/2 = 4.5；rank 2 < 4.5（below），rank 8 >= 4.5（not below）。
    report = ov.probability_of_backtest_overfitting([2, 8, 2, 8], n_variants=10)
    assert report["pbo"] == 0.5


def test_pbo_empty_returns_none():
    report = ov.probability_of_backtest_overfitting([], n_variants=10)
    assert report["pbo"] is None


# ===== Deflated Sharpe =====

def test_dsr_high_sharpe_normal_is_significant():
    """高 Sharpe（日频 0.10 ≈ 年化 1.59）+ 正态 + 单次检验 → DSR > 0.95（显著）。"""
    report = ov.deflated_sharpe_ratio(0.10, n_trials=1, sample_len=500, skew=0.0, kurt=3.0)
    assert report["dsr"] is not None
    assert report["dsr"] > 0.95


def test_dsr_zero_sharpe_is_not_significant():
    """Sharpe≈0 → DSR≈0.5（不显著）。"""
    report = ov.deflated_sharpe_ratio(0.0, n_trials=1, sample_len=500, skew=0.0, kurt=3.0)
    assert report["dsr"] is not None
    assert 0.3 < report["dsr"] < 0.7


def test_dsr_multiple_trials_deflates():
    """多重检验（n_trials 大）会压低 DSR。"""
    single = ov.deflated_sharpe_ratio(0.03, n_trials=1, sample_len=500, skew=0.0, kurt=3.0)
    multi = ov.deflated_sharpe_ratio(0.03, n_trials=100, sample_len=500, skew=0.0, kurt=3.0)
    assert multi["dsr"] < single["dsr"]


def test_dsr_none_sharpe_returns_none():
    report = ov.deflated_sharpe_ratio(None, n_trials=1, sample_len=500, skew=0.0, kurt=3.0)
    assert report["dsr"] is None


# ===== skewness / kurtosis =====

def test_skewness_normal_is_near_zero():
    random.seed(42)
    values = [random.gauss(0, 1) for _ in range(10000)]
    assert abs(ov.skewness(values)) < 0.1


def test_kurtosis_normal_is_near_three():
    random.seed(42)
    values = [random.gauss(0, 1) for _ in range(10000)]
    assert abs(ov.kurtosis(values) - 3.0) < 0.2


# ===== _extract_daily_returns =====

def test_extract_daily_returns_from_equity():
    equity = [{"total_equity": 100}, {"total_equity": 110}, {"total_equity": 105}]
    rets = ov._extract_daily_returns(equity)
    assert len(rets) == 2
    assert rets[0] == pytest.approx(0.10)
    assert rets[1] == pytest.approx(105 / 110 - 1)


def test_extract_daily_returns_empty_cases():
    assert ov._extract_daily_returns([]) == []
    assert ov._extract_daily_returns(None) == []
    assert ov._extract_daily_returns([{"total_equity": 100}]) == []
    assert ov._extract_daily_returns("not a list") == []
