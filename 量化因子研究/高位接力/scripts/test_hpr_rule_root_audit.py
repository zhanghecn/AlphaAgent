"""逐口诀寻根研究审计器的最小回归测试。"""

from __future__ import annotations

import pandas as pd
import pytest

import hpr_rule_root_audit as audit


def row(group: str, **changes) -> dict:
    base = {
        "买入日": pd.Timestamp("2024-01-02"), "四组": group, "N": 3,
        "b1开盘%": 0.0, "b2开盘%": 0.0, "b3开盘%": 0.0, "买入开盘%": 2.0,
        "b1换手%": 6.0, "b2换手%": 15.0, "b3换手%": 14.0,
        "地基涨跌%": 0.0, "前10日涨幅%": 10.0, "距MA10%": 1.0,
        "前波60日最高板": 0, "距60日新高%": -10.0, "地基姿态": "站线上",
        "锚位%": None, "锚距": None, "E3%": 5.0,
    }
    base.update(changes)
    return base


def test_branch_catalog_covers_thirteen_rules_and_eighteen_branches():
    branches = audit.branch_catalog()
    assert len({branch["no"] for branch in branches}) == 13
    assert len(branches) == 18
    assert {(branch["no"], branch["sub"]) for branch in branches if branch["no"] == "K4"} == {
        ("K4", "缩量承接"), ("K4", "一板平开")}


def test_research_event_loader_rejects_missing_or_stale_dataset(tmp_path):
    path = tmp_path / "events.csv"
    with pytest.raises(SystemExit, match="build"):
        audit.load_research_events(path)
    pd.DataFrame({"买入日": [pd.Timestamp("2024-01-01")]}).to_csv(path, index=False)
    with pytest.raises(SystemExit, match="6370"):
        audit.load_research_events(path)


def test_open_entry_report_separates_touch_non_touch_and_all_trades():
    events = pd.DataFrame([
        {"买入日": pd.Timestamp("2023-01-02"), "方案点": "B2", "弱口诀": "—", "E3%": 0.0,
         "开盘买E3%": 10.0, "当日触板": True},
        {"买入日": pd.Timestamp("2023-02-02"), "方案点": "B2", "弱口诀": "—", "E3%": -20.0,
         "开盘买E3%": -5.0, "当日触板": False},
    ])
    report = audit.open_entry_report(events)["B2"]["discovery"]
    assert report["current_touch"]["mean"] == 0.0
    assert report["open_touch"]["mean"] == 10.0
    assert report["open_non_touch"]["mean"] == -5.0
    assert report["open_all"]["mean"] == 2.5


def test_common_branches_use_all_years_and_split_the_two_eras():
    k5 = row("三接四阴", **{"b2开盘%": 2.0, "买入开盘%": 7.0, "b3换手%": 5.0})
    b1 = row("二接三阴", N=2, **{"b1开盘%": 8.0, "b2开盘%": 8.0,
                                   "买入开盘%": 4.0, "b2换手%": 6.0})
    events = pd.DataFrame([
        {**k5, "买入日": pd.Timestamp("2020-01-02")},
        {**k5, "买入日": pd.Timestamp("2023-01-02")},
        {**k5, "买入日": pd.Timestamp("2024-01-02")},
        {**k5, "买入日": pd.Timestamp("2025-01-02")},
        {**k5, "买入日": pd.Timestamp("2026-01-02"), "E3%": -99.0},
        {**b1, "买入日": pd.Timestamp("2021-01-02")},
        {**b1, "买入日": pd.Timestamp("2024-01-02")},
    ])
    report = audit.baseline_report(events, include_final=False)
    k5_report = next(item for item in report if item["no"] == "K5")
    b1_report = next(item for item in report if item["no"] == "B1" and item["sub"] == "转温")
    assert k5_report["periods"]["discovery"]["n"] == 3
    assert k5_report["periods"]["weak_era"]["n"] == 1
    assert k5_report["periods"]["strong_era"]["n"] == 2
    assert k5_report["periods"]["validation"]["n"] == 1
    assert "final" not in k5_report["periods"]
    assert b1_report["periods"]["discovery"]["n"] == 2
    assert b1_report["periods"]["weak_era"]["n"] == 1
    assert b1_report["periods"]["strong_era"]["n"] == 1


def test_weak_reference_contains_2023_to_2025_but_not_2026():
    k9 = row("二接三阴", N=2, **{"b1开盘%": 1.0, "b2开盘%": -1.0, "买入开盘%": 4.0})
    events = pd.DataFrame([{**k9, "买入日": pd.Timestamp(f"{year}-01-02")}
                           for year in (2022, 2024, 2025, 2026)])
    periods = audit.era_frames(events, "weak", include_final=False)
    assert periods["reference"]["买入日"].dt.year.tolist() == [2024, 2025]
    final_periods = audit.era_frames(events, "weak", include_final=True)
    assert final_periods["reference"]["买入日"].dt.year.tolist() == [2024, 2025, 2026]


def test_baseline_report_uses_each_rules_own_era_and_branch():
    a2 = row("二接三阳", N=2, **{"b2开盘%": 9.5, "买入开盘%": 8.0, "b2换手%": 4.0})
    k4 = row("三接四阳")
    events = pd.DataFrame([
        {**a2, "买入日": pd.Timestamp("2023-01-02"), "E3%": 10.0},
        {**a2, "买入日": pd.Timestamp("2025-01-02"), "E3%": -5.0},
        {**a2, "买入日": pd.Timestamp("2026-01-02"), "E3%": -99.0},
        {**k4, "买入日": pd.Timestamp("2020-01-02"), "E3%": 8.0},
        {**k4, "买入日": pd.Timestamp("2022-01-02"), "E3%": -2.0},
    ])
    report = audit.baseline_report(events, include_final=False)
    a2_report = next(item for item in report if item["no"] == "A2")
    k4_report = next(item for item in report if item["no"] == "K4" and item["sub"] == "缩量承接")
    assert a2_report["periods"]["discovery"]["mean"] == 10.0
    assert a2_report["periods"]["validation"]["mean"] == -5.0
    assert "final" not in a2_report["periods"]
    assert k4_report["periods"]["discovery"]["mean"] == 8.0
    assert k4_report["periods"]["validation"]["mean"] == -2.0


def test_all_day_builder_relaxes_only_the_touch_event_filter():
    from unittest.mock import patch
    from alphaagent.server.services.high_relay import backtest

    bars = pd.DataFrame({"touch": [False, True]})
    def fake_build_events():
        derived = backtest.pool_mod.derive_daily(None)
        assert derived["touch"].all()
        return derived, "bars"
    with patch.object(backtest.pool_mod, "derive_daily", return_value=bars.copy()):
        with patch.object(backtest, "build_events", side_effect=fake_build_events):
            events, returned_bars = audit.build_all_day_events()
    assert events["touch"].tolist() == [True, True]
    assert returned_bars == "bars"


def test_open_entry_returns_use_actual_open_and_preserve_touch_flag():
    events = pd.DataFrame([
        {"_bar_i": 0, "买价": 11.0, "E3退出价": 12.0, "持有到断板%": 9.0909},
        {"_bar_i": 1, "买价": 11.0, "E3退出价": 9.0, "持有到断板%": -18.1818},
    ])
    bars = pd.DataFrame({"open_price": [10.0, 10.0], "high_price": [11.0, 10.9],
                         "limit_price": [11.0, 11.0]})
    result = audit.attach_open_entry_returns(events, bars)
    assert result["开盘买E3%"].tolist() == [20.0, -10.0]
    assert result["开盘买E0%"].tolist() == [20.0, -10.0]
    assert result["当日触板"].tolist() == [True, False]


def test_cross_group_variant_excludes_existing_other_rule_from_net_added():
    c2_trade = row("三接四阳", **{"b2开盘%": 9.5, "买入开盘%": 8.0, "b2换手%": 4.0})
    events = pd.DataFrame([c2_trade])
    branch = next(item for item in audit.branch_catalog() if item["no"] == "A2")
    report = audit.audit_branch(events, branch, include_final=False)
    adjacent = next(item for item in report if item["variant"] == "相邻板位")
    assert adjacent["periods"]["discovery"]["added"]["n"] == 1
    assert adjacent["periods"]["discovery"]["net_added"]["n"] == 0


def test_neutral_rule_also_tests_adjacent_board_position():
    branch = next(item for item in audit.branch_catalog() if item["no"] == "C1")
    variants = audit.variant_definitions(branch)
    adjacent = next(changes for name, changes in variants if name == "相邻板位")
    assert adjacent["group4"] == ("三接四阳", "三接四阴")


def test_variant_removes_only_the_target_auxiliary_leg():
    base = row("二接三阳", N=2, **{"b2开盘%": 9.5, "买入开盘%": 8.0, "b2换手%": 4.0,
                                    "前10日涨幅%": 20.0})
    events = pd.DataFrame([base])
    branch = next(item for item in audit.branch_catalog() if item["no"] == "A2")
    assert not audit.match_branch(events, branch).iloc[0]
    assert audit.match_branch(events, branch, {"block_pre10": None}).iloc[0]


def test_audit_branch_includes_body_and_full_opening_spectrum_without_final_year():
    base = row("二接三阳", N=2, **{"b2开盘%": 9.5, "买入开盘%": 8.0, "b2换手%": 4.0})
    events = pd.DataFrame([{**base, "买入日": pd.Timestamp("2023-01-02")},
                           {**base, "买入日": pd.Timestamp("2026-01-02"), "E3%": -99.0}])
    branch = next(item for item in audit.branch_catalog() if item["no"] == "A2")
    report = audit.audit_branch(events, branch, include_final=False)
    names = {item["variant"] for item in report}
    assert "形态本体" in names
    assert "今天开盘全谱" in names
    assert all("final" not in item["periods"] for item in report)


def test_weak_matching_separates_k4_branches_and_does_not_inherit_strong_sub():
    events = pd.DataFrame([
        row("三接四阳"),
        row("三接四阳", **{"b3换手%": 16.0}),
        row("三接四阴", **{"b2开盘%": 2.0, "买入开盘%": 7.0, "b3换手%": 5.0}),
    ])
    assert audit.match_weak(events).tolist() == ["K4·缩量承接", "K4·一板平开", "K5"]


def test_strong_matching_uses_production_auxiliary_legs():
    base = row("二接三阳", N=2, **{"b2开盘%": 9.5, "买入开盘%": 8.0, "b2换手%": 4.0})
    events = pd.DataFrame([base, {**base, "前10日涨幅%": 20.0}])
    assert audit.match_strong(events).tolist() == ["A2", "—"]


def test_net_added_excludes_trades_migrating_from_another_rule():
    events = pd.DataFrame({"E3%": [8.0, 10.0, 20.0]})
    baseline = pd.Series([False, False, False])
    variant = pd.Series([True, True, False])
    current_any = pd.Series([True, False, False])
    result = audit.compare_masks(events, baseline, variant, current_any)
    assert result["added"]["n"] == 2
    assert result["net_added"]["n"] == 1
    assert result["net_added"]["mean"] == 10.0


def test_compare_masks_reports_kept_added_and_removed_returns():
    events = pd.DataFrame({"E3%": [10.0, -5.0, 20.0, -10.0]})
    baseline = pd.Series([True, True, False, False])
    variant = pd.Series([True, False, True, False])
    result = audit.compare_masks(events, baseline, variant)
    assert result["baseline"]["n"] == 2
    assert result["variant"]["n"] == 2
    assert result["kept"]["mean"] == 10.0
    assert result["removed"]["mean"] == -5.0
    assert result["added"]["mean"] == 20.0


def test_strong_periods_keep_2026_closed_until_final_verification():
    events = pd.DataFrame({"买入日": pd.to_datetime(["2022-01-01", "2023-01-01", "2024-01-01",
                                                    "2025-01-01", "2026-01-01"])})
    periods = audit.era_frames(events, "strong", include_final=False)
    assert set(periods) == {"discovery", "validation"}
    assert periods["discovery"]["买入日"].dt.year.tolist() == [2023, 2024]
    assert periods["validation"]["买入日"].dt.year.tolist() == [2025]
