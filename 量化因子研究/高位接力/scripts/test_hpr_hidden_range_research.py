"""高位接力隐藏特征研究的最小回归测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import hpr_hidden_range_research as research


def _bars() -> pd.DataFrame:
    n = 130
    idx = np.arange(n, dtype=float)
    close = 10 + idx * 0.03 + np.sin(idx / 5) * 0.2
    return pd.DataFrame({
        "vt_symbol": ["000001.SZSE"] * n,
        "trade_date": pd.bdate_range("2024-01-01", periods=n),
        "open_price": close * (1 + np.cos(idx / 7) * 0.01),
        "high_price": close * 1.02,
        "low_price": close * 0.98,
        "close_price": close,
        "volume": 10000 + idx * 20,
        "turnover_rate": 2 + idx % 8,
    })


def test_persist_dataset_writes_all_cli_inputs(tmp_path):
    events = pd.DataFrame({"买入日": [pd.Timestamp("2024-01-01")], "E3%": [5.0]})
    output = tmp_path / "events.pkl"
    research.persist_dataset(events, output, {"2024-01": "strong"})
    assert pd.read_pickle(output).equals(events)
    assert len(pd.read_csv(output.with_suffix(".csv"))) == 1
    assert output.with_suffix(".json").exists()


def test_hidden_features_do_not_change_when_future_bars_change():
    bars = _bars()
    original = research.compute_event_features(bars, 100, 2)
    last = bars.iloc[99]
    expected_volume_ratio = last["volume"] / bars.iloc[79:99]["volume"].mean()
    assert original["last_vol20"] == pytest.approx(expected_volume_ratio)
    assert original["chain_turn_sum"] == pytest.approx(
        bars.iloc[98:100]["turnover_rate"].sum())
    assert original["b1_f_turn_ratio"] == pytest.approx(
        bars.iloc[98]["turnover_rate"] / bars.iloc[97]["turnover_rate"])
    float_shares = bars.iloc[99]["volume"] * 10000 / bars.iloc[99]["turnover_rate"]
    expected_total_turn = bars.iloc[38:98]["volume"].sum() * 10000 / float_shares
    assert original["pre60_total_turn"] == pytest.approx(expected_total_turn)
    foundation = bars.iloc[97]
    expected_close_pos = ((foundation["close_price"] - foundation["low_price"])
                          / (foundation["high_price"] - foundation["low_price"]))
    assert original["f_close_pos"] == pytest.approx(expected_close_pos)
    changed = bars.copy()
    future = changed.index > 100
    changed.loc[future, ["open_price", "high_price", "low_price", "close_price"]] *= 5
    changed.loc[future, ["volume", "turnover_rate"]] *= 20
    actual = research.compute_event_features(changed, 100, 2)
    assert actual.keys() == original.keys()
    for key, expected in original.items():
        if np.isnan(expected):
            assert np.isnan(actual[key]), key
        else:
            assert actual[key] == pytest.approx(expected), key


def test_discovery_excludes_validation_and_final_test():
    events = pd.DataFrame({"买入日": pd.to_datetime(["2024-12-31", "2025-01-01", "2026-01-01"])})
    assert research.period_frame(events, "discovery")["买入日"].dt.year.tolist() == [2024]
    assert research.period_frame(events, "validation")["买入日"].dt.year.tolist() == [2025]


def test_dynamic_take_point_matches_common_branch_rules():
    events = pd.DataFrame([
        {"月": "2024-12", "方案点": "C2", "方案子项": "", "弱口诀": "K5"},
        {"月": "2021-01", "方案点": "B1", "方案子项": "转温", "弱口诀": "—"},
        {"月": "2021-01", "方案点": "B1", "方案子项": "续强", "弱口诀": "—"},
        {"月": "2021-01", "方案点": "—", "方案子项": "", "弱口诀": "K4"},
    ])
    states = {"2024-12": "strong", "2021-01": "weak"}
    assert research.assign_take_points(events, states).tolist() == ["K5", "B1", "", "K4"]


def test_discovery_finds_repeatable_range_without_reading_final_year():
    rows = []
    for year in range(2020, 2027):
        for index in range(20):
            positive = index >= 5
            rows.append({
                "买入日": pd.Timestamp(f"{year}-01-02") + pd.Timedelta(days=index),
                "四组": "二接三阴", "N": 2, "出手点": "", "方案点": "—", "弱口诀": "—",
                "买入开盘%": 2.0, "feature": np.nan if index == 0 else float(index),
                "E3%": (8.0 if positive else -8.0) if year < 2026 else -50.0,
            })
    events = pd.DataFrame(rows)
    candidates = research.discover_candidates(events, ["feature"])
    assert candidates
    assert all("final" not in candidate["periods"] for candidate in candidates)
    assert any(condition[0] == "feature" for candidate in candidates
               for condition in candidate["conditions"])
    for candidate in candidates:
        selected = events[research.candidate_mask(events, candidate)]
        discovery = research.period_frame(selected, "discovery")
        if candidate["context"].startswith("强市"):
            discovery = discovery[discovery["买入日"].dt.year >= 2023]
        assert candidate["periods"]["discovery"] == research.summarize(discovery)
        assert candidate["periods"]["validation"] == research.summarize(
            research.period_frame(selected, "validation"))


def test_candidate_mask_applies_action_and_group_context():
    events = pd.DataFrame({
        "四组": ["二接三阴", "二接三阳"], "N": [2, 2], "出手点": ["", ""],
        "买入开盘%": [2.0, 2.0], "feature": [1.0, 1.0],
    })
    candidate = {"action": "expand", "context": "强市·二接三阴",
                 "conditions": [["feature", "<=", 1.0]]}
    assert research.candidate_mask(events, candidate).tolist() == [True, False]


def test_quality_evaluation_reports_baseline_removed_and_kept():
    events = pd.DataFrame({
        "买入日": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01",
                                "2025-01-01", "2025-02-01"]),
        "四组": ["二接三阴"] * 6, "N": [2] * 6, "出手点": ["C2"] * 6,
        "买入开盘%": [2.0] * 6, "feature": [1.0, 2.0, 3.0, 4.0, 1.0, 2.0],
        "E3%": [-10.0, 10.0, 20.0, 30.0, -5.0, 10.0],
    })
    candidate = {"action": "quality", "context": "全部", "conditions": [["feature", "<=", 1.0]]}
    result = research.evaluate_candidate(events, candidate, include_final=False)
    assert result["discovery"]["mean"] == -10.0
    assert result["discovery"]["baseline"]["n"] == 4
    assert result["discovery"]["kept"]["mean"] == 20.0
    assert result["validation"]["baseline"]["n"] == 2
    assert result["validation"]["kept"]["mean"] == 10.0


def test_discovery_quality_candidate_contains_kept_and_yearly_evidence():
    rows = []
    for year in range(2020, 2026):
        for index in range(20):
            rows.append({
                "买入日": pd.Timestamp(f"{year}-01-02") + pd.Timedelta(days=index),
                "四组": "二接三阴", "N": 2, "出手点": "C2", "方案点": "C2", "弱口诀": "—",
                "买入开盘%": 2.0, "feature": float(index), "E3%": 8.0 if index >= 5 else -8.0,
            })
    candidates = research.discover_candidates(pd.DataFrame(rows), ["feature"])
    quality = [candidate for candidate in candidates if candidate["action"] == "quality"]
    assert quality
    evidence = quality[0]["quality"]["discovery"]
    assert evidence["kept"]["mean"] > evidence["baseline"]["mean"]
    assert quality[0]["quality"]["yearly"]
    assert quality[0]["quality"]["removed_trades"]


def test_candidate_evaluation_keeps_final_test_closed_until_verify():
    events = pd.DataFrame({
        "买入日": pd.to_datetime(["2024-01-01", "2025-01-01", "2026-01-01"]),
        "E3%": [5.0, 6.0, -99.0],
        "feature": [1.0, 1.0, 1.0],
    })
    candidate = {"name": "测试", "conditions": [["feature", "<=", 1.0]]}
    discovery = research.evaluate_candidate(events, candidate, include_final=False)
    verified = research.evaluate_candidate(events, candidate, include_final=True)
    assert set(discovery) == {"discovery", "validation"}
    assert discovery["discovery"]["mean"] == 5.0
    assert verified["final"]["mean"] == -99.0


def test_zero_e3_return_is_not_a_win():
    assert research.summarize(pd.DataFrame({"E3%": [0.0]}))["win"] == 0.0


def test_trimmed_stats_remove_three_largest_returns():
    events = pd.DataFrame({"E3%": [100.0, 50.0, 20.0, -10.0, -10.0]})
    stats = research.summarize(events)
    assert stats["n"] == 5
    assert stats["trim3"] == -10.0
    assert stats["win"] == 60.0
