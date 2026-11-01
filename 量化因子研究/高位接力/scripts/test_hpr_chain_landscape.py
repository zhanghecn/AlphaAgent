"""全连板全景研究底座的回归测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.high_relay import pool
import hpr_chain_landscape as landscape


def _stock(symbol: str, start: str, pattern: list[str]) -> pd.DataFrame:
    rows = []
    previous = 10.0
    for index, kind in enumerate(["N"] * 6 + pattern):
        limit = round(previous * 1.10 + 1e-9, 2)
        if kind in {"L", "O"}:
            close = limit
            open_price = close if kind == "O" else round(previous * 1.03, 2)
            high = close
            low = close if kind == "O" else round(previous * 0.99, 2)
        elif kind == "T":
            close = round(previous * 1.03, 2)
            open_price = round(previous * 1.02, 2)
            high = limit
            low = round(previous * 0.99, 2)
        else:
            close = round(previous * 1.01, 2)
            open_price = previous
            high = round(previous * 1.04, 2)
            low = round(previous * 0.99, 2)
        rows.append({
            "vt_symbol": symbol,
            "trade_date": pd.Timestamp(start) + pd.Timedelta(days=index),
            "open_price": open_price,
            "high_price": high,
            "low_price": low,
            "close_price": close,
            "volume": 10000 + index * 100,
            "turnover_rate": 2.0 + index % 5,
        })
        previous = close
    return pd.DataFrame(rows)


def _derived(pattern: list[str]) -> pd.DataFrame:
    return pool.derive_daily(_stock("000001.SZSE", "2024-01-01", pattern))


def _feature_bars() -> pd.DataFrame:
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


def test_chain_nodes_cover_three_outcomes_and_restarted_chain():
    bars = _derived(["L", "L", "L", "T", "L", "L", "N"])
    nodes = landscape.build_chain_nodes(bars)
    assert nodes["N"].tolist() == [2, 3, 2]
    assert nodes["outcome"].tolist() == ["continue", "touch_break", "no_touch"]
    assert nodes["chain_id"].nunique() == 2
    assert nodes["final_height"].tolist() == [3, 3, 2]
    first = nodes.iloc[0]
    assert first["first_board_date"] == bars["trade_date"].iat[6]
    assert first["foundation_date"] == bars["trade_date"].iat[5]
    assert first["_anchor_i"] == 7 and first["_decision_i"] == 8


def test_chain_nodes_mark_missing_next_bar_pending_and_keep_one_word():
    bars = _derived(["L", "L", "O"])
    nodes = landscape.build_chain_nodes(bars)
    assert len(nodes) == 2
    assert nodes.iloc[0]["next_one_word"]
    assert nodes.iloc[0]["outcome"] == "continue"
    assert nodes.iloc[1]["outcome"] == "pending"
    assert pd.isna(nodes.iloc[1]["decision_date"])


def test_chain_nodes_never_shift_across_stocks():
    bars = pool.derive_daily(pd.concat([
        _stock("000001.SZSE", "2024-01-01", ["L", "L"]),
        _stock("000002.SZSE", "2024-01-01", ["L", "L", "N"]),
    ], ignore_index=True))
    nodes = landscape.build_chain_nodes(bars)
    first = nodes[nodes["代码"] == "000001.SZSE"].iloc[0]
    assert first["outcome"] == "pending"
    assert pd.isna(first["decision_date"])


def test_trade_link_distinguishes_source_and_reached_anchor_without_losing_break():
    bars = _derived(["L", "L", "L", "T"])
    nodes = landscape.build_chain_nodes(bars)
    events = pd.DataFrame([
        {"_bar_i": 8, "代码": "000001.SZSE", "买入日": bars["trade_date"].iat[8],
         "N": 2, "封住": True, "E3%": 8.0},
        {"_bar_i": 9, "代码": "000001.SZSE", "买入日": bars["trade_date"].iat[9],
         "N": 3, "封住": False, "E3%": -6.0},
        {"_bar_i": 6, "代码": "000001.SZSE", "买入日": bars["trade_date"].iat[6],
         "N": 1, "封住": True, "E3%": 2.0},
    ])
    linked = landscape.link_trade_events(nodes, events)
    assert len(linked) == 3
    assert linked["link_status"].tolist()[:2] == ["ok", "ok"]
    assert pd.notna(linked.iloc[0]["source_anchor_id"])
    assert pd.notna(linked.iloc[0]["reached_anchor_id"])
    assert pd.isna(linked.iloc[1]["reached_anchor_id"])
    assert linked.iloc[1]["chain_id"] == linked.iloc[0]["chain_id"]
    assert linked.iloc[2]["link_status"] == "missing_source"
    assert linked["E3%"].tolist() == [8.0, -6.0, 2.0]


def test_pending_node_does_not_use_last_bar_as_decision_day():
    bars = _derived(["L", "L", "O"])
    nodes = landscape.build_chain_nodes(bars)
    attached = landscape.attach_node_features(nodes, bars)
    assert not attached.iloc[0]["features_missing"]
    assert attached.iloc[1]["features_missing"]


def test_decision_open_features_do_not_read_same_day_after_open_or_future():
    bars = _feature_bars()
    original = landscape.build_node_features(bars, 100, 2)
    changed = bars.copy()
    changed.loc[100, ["high_price", "low_price", "close_price", "volume", "turnover_rate"]] *= 3
    changed.loc[changed.index > 100, ["open_price", "high_price", "low_price", "close_price"]] *= 5
    changed.loc[changed.index > 100, ["volume", "turnover_rate"]] *= 20
    actual = landscape.build_node_features(changed, 100, 2)
    assert actual.keys() == original.keys()
    for key, expected in original.items():
        if pd.isna(expected):
            assert pd.isna(actual[key]), key
        else:
            assert actual[key] == pytest.approx(expected), key


def test_sequence_features_describe_positions_not_only_last_board():
    record = {
        "b1_type": "一字", "b2_type": "一字", "b3_type": "实体",
        "b1_open": 9.8, "b2_open": 9.9, "b3_open": 4.0,
        "b1_turn": 1.0, "b2_turn": 2.0, "b3_turn": 12.0,
    }
    features = landscape.sequence_features(record, 3)
    assert features["one_word_count"] == 2
    assert features["last_entity"] == 1
    assert features["first_entity_pos"] == 3
    assert features["open_peak_pos"] == 2
    assert features["turn_peak_pos"] == 3
    assert features["last_turn_vs_prev"] == 6.0
    assert features["open_slope"] == pytest.approx(-5.8)


def test_tree_search_proposes_raw_mask_candidates_without_reading_final():
    rows = []
    for year, count in ((2024, 20), (2025, 10), (2026, 10)):
        for index in range(count):
            multi = index >= count / 2 if year != 2026 else index < count / 2
            rows.append({
                "decision_date": pd.Timestamp(f"{year}-01-02") + pd.Timedelta(days=index),
                "chain_id": f"{year}-{index}", "代码": f"{year}-{index}",
                "outcome": "continue" if multi else "no_touch",
                "remaining_boards": 2 if multi else 0,
                "feature": float(index), "second": float(index % 2),
            })
    nodes = pd.DataFrame(rows)
    found = landscape.search_evolution_trees(
        nodes, ["feature", "second"], {"全部": pd.Series(True, index=nodes.index)},
        depths=(2,), leaf_sizes=(2,), min_train=4, min_validation=2)
    assert found
    assert all("final" not in item for item in found)
    assert any(item["conditions"] for item in found)
    for item in found:
        mask = landscape.candidate_condition_mask(nodes, item)
        assert item["discovery"]["n"] == int((mask & nodes.decision_date.dt.year.le(2024)).sum())
        assert item["validation"]["n"] == int((mask & nodes.decision_date.dt.year.eq(2025)).sum())


def test_trade_evidence_separates_net_new_removed_and_kept():
    nodes = pd.DataFrame({
        "decision_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2025-01-01"]),
        "chain_id": ["a", "b", "c"], "代码": ["1", "2", "3"], "名称": ["甲", "乙", "丙"],
        "trade_event": [True, True, True], "出手点": ["", "A2", ""],
        "feature": [1.0, 1.0, 3.0], "E3%": [8.0, -5.0, 10.0], "remaining_boards": [2, 0, 2],
    })
    candidate = {"feature": "feature", "lo": 0.0, "hi": 2.0}
    evidence = landscape.trade_evidence(nodes, candidate, pd.Series(True, index=nodes.index))
    assert evidence["discovery"]["new"]["n"] == 1
    assert evidence["discovery"]["removed_active"]["n"] == 1
    assert evidence["discovery"]["kept_active"]["n"] == 0
    assert evidence["validation"]["new"]["n"] == 0
    assert evidence["validation"]["kept_active"]["n"] == 0


def test_evolution_search_freezes_discovery_thresholds_and_never_reads_2026():
    rows = []
    for year, count in ((2024, 12), (2025, 6), (2026, 6)):
        for index in range(count):
            continued = index >= count / 2 if year != 2026 else index < count / 2
            rows.append({
                "decision_date": pd.Timestamp(f"{year}-01-02") + pd.Timedelta(days=index),
                "chain_id": f"{year}-{index}", "代码": f"{year}-{index}",
                "outcome": "continue" if continued else "no_touch",
                "remaining_boards": int(continued), "feature": float(index),
            })
    nodes = pd.DataFrame(rows)
    results = landscape.search_evolution_factors(
        nodes, ["feature"], contexts={"全部": pd.Series(True, index=nodes.index)},
        bins=2, min_train=4, min_validation=2)
    assert results
    assert all("final" not in item for item in results)
    best = results[0]
    selected = landscape.interval_mask(nodes, "feature", best["lo"], best["hi"])
    assert best["discovery"]["n"] == int((selected & nodes["decision_date"].dt.year.eq(2024)).sum())
    assert best["validation"]["n"] == int((selected & nodes["decision_date"].dt.year.eq(2025)).sum())


def test_production_view_and_rule_core_use_same_fields_as_existing_audit():
    import hpr_rule_root_audit as audit

    base = {
        "decision_date": pd.Timestamp("2024-01-02"), "N": 2, "foundation_yang": True,
        "b1_open": 0.0, "b2_open": 9.8, "b3_open": np.nan, "next_open_pct": 8.0,
        "b1_turn": 6.0, "b2_turn": 4.0, "b3_turn": np.nan,
        "foundation_chg": 0.0, "pre10_pct": 5.0, "dist_ma10": 1.0,
        "prev_wave60": 0, "dist_h60": -10.0, "foundation_pose": "站线上",
        "anchor_pos": np.nan, "anchor_dist": np.nan,
    }
    nodes = pd.DataFrame([base, {**base, "pre10_pct": 30.0}])
    view = landscape.production_view(nodes)
    assert audit.match_strong(view).tolist() == ["A2", "—"]
    cores = landscape.rule_core_masks(nodes)
    assert cores["A2"].tolist() == [True, True]


def test_attach_trade_allows_multiple_pending_nodes():
    nodes = pd.DataFrame({"anchor_id": ["a", "b", "c"], "_decision_i": [-1, -1, 8]})
    linked = pd.DataFrame({
        "_bar_i": [8], "买入日": [pd.Timestamp("2024-01-08")], "E3%": [5.0],
        "方案点": ["A2"], "方案子项": [""], "弱口诀": ["—"], "出手点": ["A2"],
        "封住": [True], "买价": [11.0], "持有到断板%": [4.0], "E3退出日": ["2024-01-09"],
        "持有天数": [1],
    })
    result = landscape.attach_trade_to_nodes(nodes, linked)
    assert len(result) == 3
    assert result["trade_event"].tolist() == [False, False, True]


def test_outcome_summary_reports_independent_chains_and_all_paths():
    frame = pd.DataFrame({
        "chain_id": ["a", "a", "b", "c"], "代码": ["1", "1", "2", "3"],
        "decision_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-02-01", "2024-02-02"]),
        "outcome": ["continue", "touch_break", "no_touch", "continue"],
        "remaining_boards": [2, 1, 0, 1],
    })
    stats = landscape.outcome_summary(frame)
    assert stats["n"] == 4 and stats["chains"] == 3 and stats["months"] == 2
    assert stats["continue"] == 50.0 and stats["touch_break"] == 25.0 and stats["no_touch"] == 25.0
    assert stats["multi_continue"] == 25.0


def test_factor_spectrum_reuses_frozen_thresholds():
    train = pd.DataFrame({"feature": np.arange(10, dtype=float)})
    thresholds = landscape.quantile_thresholds(train, "feature", bins=2)
    frame = pd.DataFrame({
        "feature": [-10.0, 5.0, 100.0], "chain_id": ["a", "b", "c"], "代码": ["1", "2", "3"],
        "decision_date": pd.to_datetime(["2025-01-01"] * 3),
        "outcome": ["no_touch", "continue", "continue"], "remaining_boards": [0, 1, 2],
    })
    report = landscape.factor_spectrum(frame, "feature", thresholds)
    assert report["n"].tolist() == [1, 2]
    assert report["continue"].tolist() == [0.0, 100.0]


def test_periods_keep_2026_closed_and_chain_summary_trims_chains():
    nodes = pd.DataFrame({
        "decision_date": pd.to_datetime(["2024-01-01", "2025-01-01", "2026-01-01"]),
        "chain_id": ["a", "b", "c"], "E3%": [5.0, 6.0, -99.0],
    })
    assert set(landscape.research_periods(nodes, include_final=False)) == {"discovery", "validation"}
    frame = pd.DataFrame({
        "chain_id": ["a", "b", "c", "d", "e"],
        "代码": list("12345"), "decision_date": pd.bdate_range("2024-01-01", periods=5),
        "E3%": [100.0, 50.0, 20.0, 10.0, -10.0],
    })
    stats = landscape.chain_aware_summary(frame, "E3%")
    assert stats["n"] == 5 and stats["chains"] == 5 and stats["months"] == 1
    assert stats["trim3_chain"] == 0.0
