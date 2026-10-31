from __future__ import annotations

import importlib
from datetime import date

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.first_relay import contracts, pool
from alphaagent.server.services.high_relay import pool as hpr_pool


BASE_FIELDS = {
    "pre5_pct": 0.0,
    "foundation_body": 0.0,
    "b1_turn": 10.0,
    "foundation_amplitude": 5.0,
    "today_open": 2.0,
    "foundation_yang": True,
    "foundation_pose": "骑线",
    "ma_state": "+++",
    "b1_gap": 2.0,
    "pre20_pct": 0.0,
    "b1_open": 2.0,
    "b1_break60": True,
    "foundation_vol_rel5": 1.0,
    "b1_turn_change": 5.0,
    "b1_vol_rel5": 1.0,
    "pre3_pct": 0.0,
    "dist_h60": -20.0,
}

HIT_FIELDS = {
    "F1": {"pre5_pct": -16.0, "foundation_body": -4.0},
    "F2": {"b1_turn": 4.0, "foundation_amplitude": 12.0},
    "F3": {
        "today_open": 8.0,
        "foundation_yang": False,
        "foundation_pose": "站线上",
    },
    "F4": {"ma_state": "---", "foundation_body": -6.0, "b1_gap": 9.0},
    "F5": {"foundation_yang": False, "b1_gap": 6.0, "pre20_pct": 30.0},
    "F6": {"today_open": 9.0, "b1_open": -1.0, "b1_break60": False},
    "F7": {
        "foundation_body": -6.0,
        "foundation_vol_rel5": 1.3,
        "b1_turn_change": 1.0,
    },
    "F8": {"b1_turn": 6.0, "b1_vol_rel5": 0.7, "pre3_pct": -10.0},
    "F9": {"ma_state": "---", "today_open": 8.0, "b1_turn_change": 1.0},
    "F10": {"dist_h60": -9.0, "foundation_body": 6.0, "pre3_pct": 7.0},
}

RULE_FIELDS = {
    "F1": ("pre5_pct", "foundation_body"),
    "F2": ("b1_turn", "foundation_amplitude"),
    "F3": ("today_open", "foundation_yang", "foundation_pose"),
    "F4": ("ma_state", "foundation_body", "b1_gap"),
    "F5": ("foundation_yang", "b1_gap", "pre20_pct"),
    "F6": ("today_open", "b1_open", "b1_break60"),
    "F7": ("foundation_body", "foundation_vol_rel5", "b1_turn_change"),
    "F8": ("b1_turn", "b1_vol_rel5", "pre3_pct"),
    "F9": ("ma_state", "today_open", "b1_turn_change"),
    "F10": ("dist_h60", "foundation_body", "pre3_pct"),
}

NUMERIC_RULE_FIELDS = {
    rule_id: tuple(
        field for field in fields
        if field not in {"foundation_yang", "foundation_pose", "ma_state", "b1_break60"}
    )
    for rule_id, fields in RULE_FIELDS.items()
}

BOUNDARIES = [
    ("F1", "foundation_body", -5.0, -3.0),
    ("F2", "b1_turn", 3.0, 5.0),
    ("F3", "today_open", 7.5, 8.5),
    ("F4", "b1_gap", 8.0, 12.0),
    ("F5", "b1_gap", 5.0, 8.0),
    ("F6", "today_open", 8.5, 9.5),
    ("F7", "foundation_vol_rel5", 1.2, 1.5),
    ("F7", "b1_turn_change", 0.0, 2.0),
    ("F8", "b1_turn", 5.0, 8.0),
    ("F8", "b1_vol_rel5", 0.5, 0.8),
    ("F8", "pre3_pct", -15.0, -8.0),
    ("F9", "today_open", 7.5, 8.5),
    ("F9", "b1_turn_change", 0.0, 2.0),
    ("F10", "dist_h60", -10.0, -8.0),
    ("F10", "foundation_body", 5.0, 7.0),
    ("F10", "pre3_pct", 5.0, 10.0),
]

STRICT_THRESHOLDS = [
    ("F1", "pre5_pct", -15.0, -15.01),
    ("F2", "foundation_amplitude", 11.99, 12.0),
    ("F4", "foundation_body", -5.0, -5.01),
    ("F5", "pre20_pct", 29.99, 30.0),
    ("F6", "b1_open", 0.0, -0.01),
    ("F7", "foundation_body", -5.0, -5.01),
]

REVERSED_CATEGORICAL_CONDITIONS = [
    ("F3", "foundation_yang", True),
    ("F3", "foundation_pose", "骑线"),
    ("F4", "ma_state", "+++"),
    ("F5", "foundation_yang", True),
    ("F6", "b1_break60", True),
    ("F9", "ma_state", "+++"),
]


def hit_fields(rule_id: str, **changes):
    fields = {**BASE_FIELDS, **HIT_FIELDS[rule_id]}
    fields.update(changes)
    return fields


@pytest.mark.parametrize("rule_id", list(HIT_FIELDS))
def test_each_final_rule_hits_its_own_example(rule_id):
    assert contracts.match_points(hit_fields(rule_id)) == [rule_id]


@pytest.mark.parametrize(("rule_id", "field", "lower", "upper"), BOUNDARIES)
def test_intervals_are_left_closed_right_open(rule_id, field, lower, upper):
    assert rule_id in contracts.match_points(hit_fields(rule_id, **{field: lower}))
    assert rule_id not in contracts.match_points(hit_fields(rule_id, **{field: upper}))


@pytest.mark.parametrize(("rule_id", "field", "rejected", "accepted"), STRICT_THRESHOLDS)
def test_strict_and_inclusive_thresholds(rule_id, field, rejected, accepted):
    assert rule_id not in contracts.match_points(hit_fields(rule_id, **{field: rejected}))
    assert rule_id in contracts.match_points(hit_fields(rule_id, **{field: accepted}))


@pytest.mark.parametrize(("rule_id", "field", "value"), REVERSED_CATEGORICAL_CONDITIONS)
def test_reversed_categorical_conditions_do_not_hit(rule_id, field, value):
    assert rule_id not in contracts.match_points(hit_fields(rule_id, **{field: value}))


@pytest.mark.parametrize(
    ("rule_id", "field"),
    [(rule_id, field) for rule_id, fields in NUMERIC_RULE_FIELDS.items() for field in fields],
)
def test_nan_never_satisfies_a_numeric_condition(rule_id, field):
    assert rule_id not in contracts.match_points(hit_fields(rule_id, **{field: float("nan")}))


@pytest.mark.parametrize(
    ("rule_id", "field"),
    [(rule_id, field) for rule_id, fields in RULE_FIELDS.items() for field in fields],
)
def test_missing_required_fields_never_hit(rule_id, field):
    fields = hit_fields(rule_id)
    del fields[field]

    assert rule_id not in contracts.match_points(fields)


def test_empty_fields_do_not_hit_any_rule():
    assert contracts.match_points({}) == []


def test_overlap_returns_every_hit_in_rule_order():
    fields = hit_fields("F3", ma_state="---", b1_turn_change=1.0)

    assert contracts.match_points(fields) == ["F3", "F9"]


@pytest.mark.parametrize("rule_id", ["F3", "F6", "F9"])
def test_static_match_skips_only_the_auction_gate(rule_id):
    fields = hit_fields(rule_id)
    del fields["today_open"]

    assert contracts.match_points(fields) == []
    assert contracts.match_points(fields, check_gate=False) == [rule_id]


@pytest.mark.parametrize(("rule_id", "field"), [
    ("F3", "foundation_pose"),
    ("F3", "foundation_yang"),
    ("F6", "b1_open"),
    ("F6", "b1_break60"),
    ("F9", "ma_state"),
    ("F9", "b1_turn_change"),
])
def test_static_match_still_requires_every_non_gate_field(rule_id, field):
    fields = hit_fields(rule_id)
    del fields["today_open"]
    del fields[field]

    assert contracts.match_points(fields, check_gate=False) == []


def test_static_match_ignores_an_out_of_range_open_but_not_other_nan_fields():
    assert contracts.match_points(hit_fields("F3", today_open=20.0), check_gate=False) == ["F3"]
    assert contracts.match_points(
        hit_fields("F9", today_open=float("nan"), b1_turn_change=float("nan")),
        check_gate=False,
    ) == []


def test_contract_exposes_only_the_ten_actionable_a_level_rules():
    assert contracts.J12_RULES_VERSION == "j12-v2.0"
    assert list(contracts.POINTS) == [f"F{i}" for i in range(1, 11)]
    for point in contracts.POINTS.values():
        assert point["level"] == "A"
        assert point["actionable"] is True
        assert point["name"]
        assert point["desc"]
        assert point["hint"]


def test_only_f3_f6_f9_have_auction_gates():
    expected = {"F3": (7.5, 8.5), "F6": (8.5, 9.5), "F9": (7.5, 8.5)}

    assert {rule_id: point["gate"] for rule_id, point in contracts.POINTS.items()} == {
        **{f"F{i}": None for i in range(1, 11)},
        **expected,
    }


def test_old_top_rim_dead_water_and_auction_cap_do_not_veto_final_rules():
    fields = hit_fields("F1", dist_h60=5.0, pre20_pct=-4.0, today_open=9.5)

    assert contracts.match_points(fields) == ["F1"]


def test_cheat_rows_use_research_rule_stats_and_deduplicated_total():
    expected = {
        "F1": "92笔 胜68.48% 均值+3.13 trim3+2.12",
        "F2": "61笔 胜60.66% 均值+4.63 trim3+1.76",
        "F3": "106笔 胜62.26% 均值+4.78 trim3+3.19",
        "F4": "94笔 胜71.28% 均值+3.76 trim3+2.45",
        "F5": "82笔 胜62.20% 均值+3.29 trim3+1.26",
        "F6": "70笔 胜61.43% 均值+7.10 trim3+3.43",
        "F7": "65笔 胜67.69% 均值+4.49 trim3+2.38",
        "F8": "39笔 胜66.67% 均值+9.94 trim3+4.59",
        "F9": "24笔 胜62.50% 均值+8.55 trim3+3.68",
        "F10": "23笔 胜65.22% 均值+7.43 trim3+2.55",
        "合计": "624笔 胜64.10% 均值+4.93 trim3+4.31",
    }

    assert len(contracts.CHEAT_ROWS) == 11
    for row in contracts.CHEAT_ROWS:
        rule_id = row["口诀"].split()[0]
        assert row["六年"] == expected[rule_id]
        assert "月均" not in row


def test_rules_text_describes_only_v2_entry_exit_and_honest_limits():
    text = contracts.RULES_TEXT

    assert text["avoid"] == []
    assert "严格突破+9%" in text["entry"]
    assert "开盘非涨停" in text["entry"]
    assert "开盘已高于触发价按开盘价" in text["entry"]
    assert "D+2" not in text["sell"]
    assert "深开" not in text["sell"]
    assert "一字跌停" in text["sell"]
    assert "15个交易日" in text["sell"]
    assert "满仓" not in text["position"]
    assert "空仓" not in text["position"]
    assert "171笔" in text["honest"]
    assert "60.23%" in text["honest"]
    assert "+4.41" in text["honest"]
    assert "2026" in text["honest"] and "10月23日" in text["honest"]
    for legacy_label in ("G1", "S1", "高尾组", "宽基组"):
        assert legacy_label not in str(text)


def test_main_window_separates_oob_replay_and_keeps_data_end():
    assert contracts.MAIN_WINDOW["start"] == "2023-01"
    assert contracts.MAIN_WINDOW["end"] == "2026-10-23"
    note = contracts.MAIN_WINDOW["note"]
    assert "主窗2023-01起" in note
    assert "2021-01~2022-12为回放/样本外段" in note
    assert "2026-10-23" in note


def execution_module():
    return importlib.import_module("alphaagent.server.services.first_relay.execution")


def test_limit_price_rounds_to_cent_with_half_up_epsilon():
    module = execution_module()

    assert module.limit_10pct(10.00) == pytest.approx(11.00)
    assert module.limit_10pct(5.50) == pytest.approx(6.05)
    assert module.limit_10pct(3.65) == pytest.approx(4.02)


def test_trigger_is_first_cent_strictly_above_nine_percent():
    module = execution_module()

    assert module.trigger_9pct(10.00) == pytest.approx(10.91)
    assert module.trigger_9pct(5.50) == pytest.approx(6.00)
    assert module.trigger_9pct(3.65) == pytest.approx(3.98)


def test_entry_buys_at_trigger_when_daily_high_crosses_it():
    module = execution_module()

    assert module.open9_entry(10.20, 10.91, 10.00) == pytest.approx(10.91)


def test_entry_uses_open_when_gap_is_already_above_trigger():
    module = execution_module()

    assert module.open9_entry(10.95, 11.00, 10.00) == pytest.approx(10.95)
    assert module.open9_entry(10.91, 10.95, 10.00) == pytest.approx(10.91)


def test_entry_rejects_high_below_trigger():
    module = execution_module()

    assert module.open9_entry(10.20, 10.90, 10.00) is None


def test_entry_rejects_open_at_or_above_limit():
    module = execution_module()

    assert module.open9_entry(11.00, 11.00, 10.00) is None
    assert module.open9_entry(11.01, 11.01, 10.00) is None


def test_entry_rejects_non_positive_previous_close():
    module = execution_module()

    assert module.open9_entry(0.10, 0.11, 0.00) is None
    assert module.open9_entry(-0.10, -0.09, -1.00) is None


@pytest.mark.parametrize("parameter", ["open_price", "high_price", "prev_close"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_entry_rejects_each_non_finite_price_without_raising(parameter, value):
    module = execution_module()
    prices = {"open_price": 10.20, "high_price": 10.91, "prev_close": 10.00}
    prices[parameter] = value

    assert module.open9_entry(**prices) is None


def test_tag_point_uses_final_rules_and_reports_the_first_hit():
    assert pool.tag_point(hit_fields("F1")) == ("F1", "A", None, None, True)
    assert pool.tag_point(BASE_FIELDS) == ("—", "—", None, None, False)


@pytest.mark.parametrize(("rule_id", "gate"), [
    ("F3", "7.5_8.5"),
    ("F6", "8.5_9.5"),
    ("F9", "7.5_8.5"),
])
def test_tag_point_static_candidates_keep_only_their_own_gate(rule_id, gate):
    fields = hit_fields(rule_id)
    del fields["today_open"]

    assert pool.tag_point(fields, check_gate=False) == (rule_id, "A", None, gate, True)


@pytest.mark.parametrize("rule_id", ["F3", "F6", "F9"])
def test_tag_point_with_today_open_rejects_an_out_of_window_candidate(rule_id):
    fields = hit_fields(rule_id, today_open=20.0)

    assert pool.tag_point(fields) == ("—", "—", None, None, False)
    assert pool.tag_point(fields, check_gate=False)[0] == rule_id


def test_tag_point_ungated_hit_removes_auction_gate_and_ignores_open_cap():
    fields = hit_fields("F3", pre5_pct=-16.0, foundation_body=-4.0, today_open=20.0)

    point, level, avoid, gate, actionable = pool.tag_point(fields, check_gate=False)

    assert (point, level, avoid, gate, actionable) == ("F1", "A", None, None, True)


def test_tag_point_overlap_uses_first_rule_and_shared_gate():
    fields = hit_fields("F3", ma_state="---", b1_turn_change=1.0)

    assert pool.tag_point(fields) == ("F3", "A", None, "7.5_8.5", True)


def test_tag_point_static_f3_f6_overlap_merges_adjacent_gates_without_losing_f6():
    fields = hit_fields("F3", b1_open=-1.0, b1_break60=False)
    del fields["today_open"]

    assert pool.tag_point(fields, check_gate=False) == ("F3", "A", None, "7.5_9.5", True)
    assert pool.tag_point({**fields, "today_open": 8.0}) == ("F3", "A", None, "7.5_8.5", True)
    assert pool.tag_point({**fields, "today_open": 9.0}) == ("F6", "A", None, "8.5_9.5", True)


def test_tag_point_does_not_revive_old_static_vetoes_or_bonus_labels():
    fields = hit_fields("F1", dist_h60=5.0, pre20_pct=-4.0, today_open=9.5)

    assert pool.tag_point(fields) == ("F1", "A", None, None, True)
    assert not hasattr(pool, "bonus_tags")


def _synthetic_pool_bars() -> tuple[pd.DataFrame, pd.DatetimeIndex, int]:
    dates = pd.bdate_range("2023-01-02", periods=90)
    close = np.linspace(8.0, 9.8, len(dates))
    open_ = np.r_[8.0, close[:-1] * 1.0005]
    bars = pd.DataFrame({
        "vt_symbol": "000001.SZSE",
        "trade_date": dates,
        "open_price": open_,
        "high_price": np.maximum(open_, close) * 1.002,
        "low_price": np.minimum(open_, close) * 0.998,
        "close_price": close,
        "volume": 1000.0,
        "turnover_rate": 2.0,
    })
    p1 = 65
    p2 = p1 - 1
    bars.loc[p2, ["open_price", "high_price", "low_price", "close_price"]] = [
        9.53, 10.83, 8.83, 10.03,
    ]
    bars.loc[p2, ["volume", "turnover_rate"]] = [1500.0, 5.123]
    bars.loc[p1, ["open_price", "high_price", "low_price", "close_price"]] = [
        9.83, 11.03, 9.71, 11.03,
    ]
    bars.loc[p1, ["volume", "turnover_rate"]] = [900.0, 6.456]
    return bars, dates, p1


def test_event_fields_matches_research_values_and_first_board_execution_prices():
    raw, _, p1 = _synthetic_pool_bars()
    bars = hpr_pool.derive_daily(raw)
    ctx = hpr_pool.make_ctx(bars)
    p2 = p1 - 1

    fields = pool.event_fields(bars, ctx, p1)

    static = hpr_pool.static_fields(ctx, p1, 1)
    assert static is not None
    for key, value in static.items():
        if key != "b1_type":
            assert fields[key] == value
    assert fields["pre5_pct"] == pytest.approx((10.03 / raw.at[p2 - 5, "close_price"] - 1) * 100)
    assert fields["pre3_pct"] == round((10.03 / raw.at[p2 - 3, "close_price"] - 1) * 100, 2)
    assert fields["pre20_pct"] == round((10.03 / raw.at[p2 - 20, "close_price"] - 1) * 100, 2)
    assert fields["foundation_amplitude"] == pytest.approx(
        (10.83 - 8.83) / raw.at[p2 - 1, "close_price"] * 100
    )
    assert fields["foundation_body"] == pytest.approx((10.03 / 9.53 - 1) * 100)
    assert fields["foundation_vol_rel5"] == pytest.approx(1500 / 1100)
    assert fields["foundation_turn"] == pytest.approx(5.123)
    assert fields["b1_gap"] == pytest.approx((11.03 - 9.71) / 10.03 * 100)
    assert fields["b1_vol_rel5"] == pytest.approx(900 / 1080)
    assert fields["b1_turn"] == 6.46
    assert fields["b1_turn_change"] == pytest.approx(6.46 - 5.123)
    assert fields["b1_open"] == round((9.83 / 10.03 - 1) * 100, 2)
    assert fields["b1_break60"] is True
    assert fields["b1_type"] == "下影"
    assert fields["prev_close"] == pytest.approx(11.03)
    assert fields["limit_price"] == pytest.approx(12.13)
    assert fields["trigger_price"] == pytest.approx(12.03)
    assert fields["dist_ma20"] == static["foundation_ma20_gap"]


def test_event_fields_leaves_pre5_missing_when_same_stock_history_is_too_short():
    raw, _, _ = _synthetic_pool_bars()
    raw = raw.iloc[60:66].reset_index(drop=True).copy()
    bars = hpr_pool.derive_daily(raw)

    fields = pool.event_fields(bars, hpr_pool.make_ctx(bars), 5)

    assert fields is not None
    assert fields["pre5_pct"] is None
    assert contracts.match_points(fields, check_gate=False) == []


def test_compute_pool_uses_shared_fields_deduplicates_actions_and_prices_from_first_board(
    monkeypatch,
):
    raw, dates, p1 = _synthetic_pool_bars()
    data_date = dates[p1].date()
    universe = pd.DataFrame({"vt_symbol": ["000001.SZSE"], "name": ["平安银行"]})
    monkeypatch.setattr(pool, "get_engine", lambda: object())
    monkeypatch.setattr(pool.hpr_pool, "load_universe", lambda engine: universe)
    monkeypatch.setattr(
        pool.pd,
        "read_sql",
        lambda *args, **kwargs: raw[raw["trade_date"] <= pd.Timestamp(data_date)].copy(),
    )
    original_make_ctx = pool.hpr_pool.make_ctx
    original_event_fields = pool.event_fields
    calls = {"make_ctx": 0, "event_fields": 0}

    def make_ctx_once(bars):
        calls["make_ctx"] += 1
        return original_make_ctx(bars)

    def overlap_fields(bars, ctx, i_last):
        calls["event_fields"] += 1
        fields = original_event_fields(bars, ctx, i_last)
        assert fields is not None
        fields.update(BASE_FIELDS)
        fields.update(HIT_FIELDS["F3"])
        fields.update(ma_state="---", b1_turn_change=1.0)
        return fields

    monkeypatch.setattr(pool.hpr_pool, "make_ctx", make_ctx_once)
    monkeypatch.setattr(pool, "event_fields", overlap_fields)

    result = pool.compute_pool(data_date)

    assert calls == {"make_ctx": 1, "event_fields": 1}
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    first_board_close = float(raw.at[p1, "close_price"])
    foundation_close = float(raw.at[p1 - 1, "close_price"])
    assert entry["prev_close"] == pytest.approx(first_board_close)
    assert entry["limit_price"] == pytest.approx(execution_module().limit_10pct(first_board_close))
    assert entry["trigger_price"] == pytest.approx(execution_module().trigger_9pct(first_board_close))
    assert entry["limit_price"] != pytest.approx(execution_module().limit_10pct(foundation_close))
    assert (entry["point"], entry["level"], entry["actionable"]) == ("F3", "A", True)
    assert entry["avoid_static"] is None
    assert entry["auction_gate"] == "7.5_8.5"
    assert entry["rule_ids"] == "F3+F9"
    assert entry["bonus"] == "同中F9"
    expected_stats = {"pool": 1, "actionable": 1, "avoid": 0}
    expected_stats.update({f"act_F{i}": 0 for i in range(1, 11)})
    expected_stats.update(act_F3=1, act_F9=1)
    assert result["filter_stats"] == expected_stats


def backtest_module():
    return importlib.import_module("alphaagent.server.services.first_relay.backtest")


def _synthetic_backtest_bars(mode: str) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """90 日合成日线；p1=65 是孤立首板，buy=66 是二板交易日。"""
    execution = execution_module()
    dates = pd.bdate_range("2023-01-02", periods=90)
    close = np.linspace(10.0, 10.45, len(dates))
    open_ = np.r_[10.0, close[:-1] * 1.0005]
    bars = pd.DataFrame({
        "vt_symbol": "000001.SZSE",
        "trade_date": dates,
        "open_price": open_,
        "high_price": np.maximum(open_, close) * 1.002,
        "low_price": np.minimum(open_, close) * 0.998,
        "close_price": close,
        "volume": 1000.0,
        "turnover_rate": 5.0,
    })
    p1, buy = 65, 66
    foundation_close = float(bars.at[p1 - 1, "close_price"])
    b1_limit = execution.limit_10pct(foundation_close)
    bars.loc[p1, ["open_price", "high_price", "low_price", "close_price"]] = [
        foundation_close * 1.01,
        b1_limit,
        foundation_close,
        b1_limit,
    ]
    bars.loc[p1, ["volume", "turnover_rate"]] = [1500.0, 8.0]

    b1_close = float(bars.at[p1, "close_price"])
    buy_limit = execution.limit_10pct(b1_close)
    trigger = execution.trigger_9pct(b1_close)
    bars.loc[buy, ["open_price", "high_price", "low_price", "close_price"]] = [
        b1_close * 1.005,
        trigger if mode in {"near", "below", "gap"} else buy_limit,
        b1_close,
        b1_close * 1.04 if mode in {"near", "below", "gap"} else buy_limit,
    ]
    bars.loc[buy, ["volume", "turnover_rate"]] = [2000.0, 10.0]

    if mode == "below":
        bars.loc[buy, ["open_price", "high_price", "low_price", "close_price"]] = [
            b1_close * 1.005,
            trigger - 0.01,
            b1_close,
            b1_close * 1.04,
        ]
    elif mode == "gap":
        gap_open = round((trigger + buy_limit) / 2, 2)
        bars.loc[buy, ["open_price", "high_price", "low_price", "close_price"]] = [
            gap_open,
            buy_limit,
            b1_close,
            b1_close * 1.04,
        ]
        next_close = gap_open * 1.02
        bars.loc[buy + 1, ["open_price", "high_price", "low_price", "close_price"]] = [
            gap_open, next_close, gap_open * 0.99, next_close,
        ]
    elif mode == "open_limit":
        bars.loc[buy, ["open_price", "high_price", "low_price", "close_price"]] = [
            buy_limit, buy_limit, b1_close * 1.02, b1_close * 1.05,
        ]
    elif mode == "near":
        next_close = trigger * 1.02
        bars.loc[buy + 1, ["open_price", "high_price", "low_price", "close_price"]] = [
            trigger, next_close, trigger * 0.99, next_close,
        ]
    elif mode in {"sealed", "deep_open"}:
        next_limit = execution.limit_10pct(buy_limit)
        bars.loc[buy + 1, ["open_price", "high_price", "low_price", "close_price"]] = [
            buy_limit * 1.01, next_limit, buy_limit, next_limit,
        ]
        if mode == "deep_open":
            bars.loc[buy + 2, ["open_price", "high_price", "low_price", "close_price"]] = [
                next_limit * 0.94, next_limit * 1.01, next_limit * 0.93, next_limit * 0.95,
            ]
        else:
            bars.loc[buy + 2, ["open_price", "high_price", "low_price", "close_price"]] = [
                next_limit * 1.01, next_limit * 1.03, next_limit, next_limit * 1.02,
            ]
    return bars, dates


def _build_synthetic_events(monkeypatch, bars: pd.DataFrame) -> pd.DataFrame:
    backtest = backtest_module()

    def database_must_not_be_touched():
        raise AssertionError("注入合成 bars 时不得访问数据库")

    monkeypatch.setattr(backtest, "get_engine", database_must_not_be_touched)
    return backtest.build_events(bars=bars, name_map={"000001.SZSE": "合成银行"})


def test_backtest_near_miss_buys_at_trigger_and_exits_next_day_close(monkeypatch):
    bars, dates = _synthetic_backtest_bars("near")

    events = _build_synthetic_events(monkeypatch, bars)

    assert len(events) == 1
    row = events.iloc[0]
    assert row["代码"] == "000001.SZSE"
    assert row["名称"] == "合成银行"
    assert row["买入日"] == dates[66]
    assert row["买价"] == pytest.approx(execution_module().trigger_9pct(bars.at[65, "close_price"]))
    assert row["触发价"] == pytest.approx(row["买价"])
    assert not row["触板"]
    assert not row["封住"]
    assert row["E3退出日"] == dates[67].date().isoformat()
    assert row["E3原因"] == "break_day_close"
    assert row["持有天数"] == 1
    assert row["断板天数"] is None
    assert row["E3%"] == pytest.approx(2.0)
    assert not row["未完"]


def test_backtest_sealed_board_exits_at_first_break_day_close(monkeypatch):
    bars, dates = _synthetic_backtest_bars("sealed")

    row = _build_synthetic_events(monkeypatch, bars).iloc[0]
    expected_return = round((bars.at[68, "close_price"] / row["买价"] - 1) * 100, 2)

    assert row["封住"] and row["触板"]
    assert row["E3退出日"] == dates[68].date().isoformat()
    assert row["E3原因"] == "break_close"
    assert row["持有天数"] == 2
    assert row["断板天数"] == 2
    assert row["E3%"] == pytest.approx(expected_return)
    assert row["持有到断板%"] == pytest.approx(expected_return)


def test_backtest_deep_open_still_exits_at_close_not_d2_auction(monkeypatch):
    bars, dates = _synthetic_backtest_bars("deep_open")

    row = _build_synthetic_events(monkeypatch, bars).iloc[0]
    close_return = round((bars.at[68, "close_price"] / row["买价"] - 1) * 100, 2)
    auction_return = round((bars.at[68, "open_price"] / row["买价"] - 1) * 100, 2)

    assert row["E3退出日"] == dates[68].date().isoformat()
    assert row["E3原因"] == "break_close"
    assert row["E3%"] == pytest.approx(close_return)
    assert row["E3%"] != pytest.approx(auction_return)


def test_backtest_excludes_open_limit_and_high_below_trigger(monkeypatch):
    for mode in ("open_limit", "below"):
        bars, _ = _synthetic_backtest_bars(mode)

        assert _build_synthetic_events(monkeypatch, bars).empty


def test_backtest_gap_above_trigger_buys_at_open(monkeypatch):
    bars, _ = _synthetic_backtest_bars("gap")

    row = _build_synthetic_events(monkeypatch, bars).iloc[0]

    assert row["买价"] == pytest.approx(bars.at[66, "open_price"])
    assert row["买价"] > row["触发价"]
    assert row["今开%"] == round(row["今开%"], 2)


def test_backtest_uses_shared_fields_once_and_preserves_misses_and_overlap(monkeypatch):
    backtest = backtest_module()
    bars, _ = _synthetic_backtest_bars("near")
    bars.loc[66, "open_price"] = bars.at[65, "close_price"] * 1.08
    original_make_ctx = backtest.pool_mod.hpr_pool.make_ctx
    original_event_fields = backtest.pool_mod.event_fields
    calls = {"make_ctx": 0, "event_fields": 0}

    def make_ctx_once(daily):
        calls["make_ctx"] += 1
        return original_make_ctx(daily)

    def overlapping_fields(daily, ctx, i_last):
        calls["event_fields"] += 1
        fields = original_event_fields(daily, ctx, i_last)
        assert fields is not None
        fields.update(BASE_FIELDS)
        fields.update(HIT_FIELDS["F3"])
        fields.update(ma_state="---", b1_turn_change=1.0)
        return fields

    monkeypatch.setattr(backtest.pool_mod.hpr_pool, "make_ctx", make_ctx_once)
    monkeypatch.setattr(backtest.pool_mod, "event_fields", overlapping_fields)
    row = _build_synthetic_events(monkeypatch, bars).iloc[0]

    assert calls == {"make_ctx": 1, "event_fields": 1}
    assert row["方案点"] == "F3"
    assert row["级别"] == "A"
    assert row["规则IDs"] == "F3+F9"
    assert row["加分"] == "同中F9"
    assert pd.isna(row["回避"])

    monkeypatch.setattr(
        backtest.pool_mod,
        "event_fields",
        lambda daily, ctx, i_last: {**original_event_fields(daily, ctx, i_last), **BASE_FIELDS},
    )
    miss = _build_synthetic_events(monkeypatch, bars).iloc[0]
    assert miss["方案点"] == "—"
    assert miss["规则IDs"] == ""
    assert pd.isna(miss["加分"])


def test_backtest_marks_bad_data_without_dropping_event(monkeypatch):
    backtest = backtest_module()
    bars, _ = _synthetic_backtest_bars("near")
    original_event_fields = backtest.pool_mod.event_fields

    def anomalous_fields(daily, ctx, i_last):
        fields = original_event_fields(daily, ctx, i_last)
        assert fields is not None
        fields["foundation_chg"] = 11.01
        return fields

    monkeypatch.setattr(backtest.pool_mod, "event_fields", anomalous_fields)
    events = _build_synthetic_events(monkeypatch, bars)

    assert len(events) == 1
    assert bool(events.iloc[0]["数据异常"])


def test_old_e3_exit_retains_deep_open_auction_behavior_for_research():
    backtest = backtest_module()
    bars, _ = _synthetic_backtest_bars("deep_open")
    daily = hpr_pool.derive_daily(bars)
    grouped = daily.groupby("sid", sort=False)
    for k in range(1, backtest.MAX_K + 1):
        for field in ("close", "open", "high", "low", "is_lim"):
            source = f"{field}_price" if field != "is_lim" else field
            daily[f"n{k}_{field}"] = grouped[source].shift(-k)
    i = 66

    exit_price, exit_i, reason = backtest._e3_exit(
        daily, i, True, float(daily.at[i + 2, "close_price"]), 2, i + 2, False,
    )

    assert exit_price == pytest.approx(daily.at[i + 2, "open_price"])
    assert exit_i == i + 2
    assert reason == "d2_deep_open_sell"


def _backtest_daily_with_future(bars: pd.DataFrame) -> pd.DataFrame:
    backtest = backtest_module()
    daily = hpr_pool.derive_daily(bars)
    grouped = daily.groupby("sid", sort=False)
    future = {}
    for k in range(1, backtest.MAX_K + 1):
        for field in ("close", "open", "high", "low", "is_lim"):
            source = f"{field}_price" if field != "is_lim" else field
            future[f"n{k}_{field}"] = grouped[source].shift(-k)
    return pd.concat([daily, pd.DataFrame(future, index=daily.index)], axis=1)


def _locked_limit_down_tail(mode: str) -> pd.DataFrame:
    bars, _ = _synthetic_backtest_bars("sealed")
    previous = float(bars.at[66, "close_price"])
    unlock_k = 5 if mode == "deferred" else None
    for k in range(1, backtest_module().MAX_K + 1):
        locked_close = round(previous * 0.90 + 1e-9, 2)
        if k == unlock_k:
            day_open = round(previous * 0.98, 2)
            values = [day_open, day_open * 1.01, day_open * 0.97, day_open * 1.005]
        else:
            values = [locked_close, locked_close, locked_close, locked_close]
        bars.loc[66 + k, ["open_price", "high_price", "low_price", "close_price"]] = values
        previous = float(values[3])
    return bars


def test_tail_exit_locked_through_d15_is_unfinished_not_fake_filled(monkeypatch):
    backtest = backtest_module()
    bars = _locked_limit_down_tail("locked")
    daily = _backtest_daily_with_future(bars)
    i = 66

    exit_price, exit_i, reason = backtest._tail_exit(
        daily, i, True, float(daily.at[i + 1, "close_price"]), 1, i + 1, False,
    )

    assert pd.isna(exit_price)
    assert exit_i is None
    assert reason is None
    row = _build_synthetic_events(monkeypatch, bars).iloc[0]
    assert row["未完"]
    assert pd.isna(row["E3%"])
    assert row["E3退出日"] is None
    assert row["E3原因"] is None
    assert row["持有天数"] is None


def test_tail_exit_defers_to_first_unlocked_day_open(monkeypatch):
    backtest = backtest_module()
    bars = _locked_limit_down_tail("deferred")
    daily = _backtest_daily_with_future(bars)
    i = 66

    exit_price, exit_i, reason = backtest._tail_exit(
        daily, i, True, float(daily.at[i + 1, "close_price"]), 1, i + 1, False,
    )

    assert exit_price == pytest.approx(daily.at[i + 5, "open_price"])
    assert exit_i == i + 5
    assert reason == "limit_down_defer"
    row = _build_synthetic_events(monkeypatch, bars).iloc[0]
    assert not row["未完"]
    assert row["E3退出日"] == daily.at[i + 5, "trade_date"].date().isoformat()
    assert row["E3原因"] == "limit_down_defer"
    assert row["持有天数"] == 5
    assert row["断板天数"] == 1
    assert row["E3%"] == pytest.approx(
        round((daily.at[i + 5, "open_price"] / row["买价"] - 1) * 100, 2)
    )


def _report_event(
    symbol: str,
    trade_date: str,
    point: str,
    rule_ids: str,
    ret: float,
    *,
    sealed: bool = False,
    hold_days: int | None = 1,
    unfinished: bool = False,
    bad_data: bool = False,
    avoid: str | None = None,
) -> dict[str, object]:
    day = pd.Timestamp(trade_date)
    return {
        "代码": symbol,
        "名称": symbol,
        "买入日": day,
        "段": "主窗" if day >= pd.Timestamp("2023-01-01") else "样本外",
        "方案点": point,
        "级别": "A" if point in contracts.POINTS else "—",
        "规则IDs": rule_ids,
        "回避": avoid,
        "加分": None,
        "今开%": 8.0,
        "E3%": ret,
        "未完": unfinished,
        "数据异常": bad_data,
        "封住": sealed,
        "持有天数": hold_days,
        "断板天数": hold_days if sealed else None,
        "月": day.strftime("%Y-%m"),
        "年": day.strftime("%Y"),
    }


def _report_events() -> pd.DataFrame:
    return pd.DataFrame([
        _report_event("A", "2023-01-03", "F1", "F1+F10", 10.0,
                      sealed=True, hold_days=2),
        _report_event("A", "2023-01-03", "F1", "F1+F10", 10.0,
                      sealed=True, hold_days=2),
        _report_event("B", "2023-01-04", "F10", "F10", 2.0),
        _report_event("C", "2023-02-01", "F2", "F2", -1.0,
                      sealed=True, hold_days=1),
        _report_event("D", "2022-12-01", "F1", "F1", 4.0),
        _report_event("BAD", "2023-03-01", "F1", "F1", 100.0, bad_data=True),
        _report_event("OPEN", "2023-03-02", "F1", "F1", float("nan"), unfinished=True),
        _report_event("MISS", "2023-03-03", "—", "", 1.0),
        _report_event("MISS_BAD", "2023-03-04", "—", "", 50.0, bad_data=True),
    ])


def test_report_uses_clean_deduplicated_hit_ledger_and_rule_membership():
    report = backtest_module().assemble_report(_report_events())

    assert report["total"]["n"] == 4
    assert report["total"]["e3"] == pytest.approx(3.75)
    assert report["total"]["trim3"] == pytest.approx(-1.0)
    assert report["main"]["n"] == 3
    assert report["oos"]["n"] == 1
    assert report["miss_control"]["n"] == 1
    assert report["miss_control"]["e3"] == pytest.approx(1.0)
    assert report["poison"] == {"n": 0, "e3": None}

    for segment in ("all", "main", "oos"):
        assert list(report["by_point"][segment]) == list(contracts.POINTS)
    assert report["by_point"]["all"]["F1"]["n"] == 2
    assert report["by_point"]["all"]["F10"]["n"] == 2
    assert report["by_point"]["all"]["F2"]["n"] == 1
    assert report["by_point"]["main"]["F1"]["n"] == 1
    assert report["by_point"]["main"]["F10"]["n"] == 2
    assert report["by_point"]["oos"]["F1"]["n"] == 1
    assert report["by_point"]["oos"]["F10"]["n"] == 0
    single_rule_total = sum(
        stats["n"] for stats in report["by_point"]["all"].values()
    )
    assert single_rule_total == 5
    assert single_rule_total > report["total"]["n"]


def test_report_year_stats_and_yearly_totals_include_trim3_and_sum():
    events = pd.DataFrame([
        _report_event(str(i), f"2023-01-{i + 1:02d}", "F1", "F1", ret)
        for i, ret in enumerate([100.0, 50.0, 20.0, 10.0, -5.0])
    ])

    report = backtest_module().assemble_report(events)

    year = report["total"]["by_year"]["2023"]
    assert year["n"] == 5
    assert year["sum_pct"] == pytest.approx(175.0)
    assert year["trim3"] == pytest.approx(2.5)
    assert report["total"]["trim3"] == pytest.approx(2.5)
    assert report["yearly_totals"][0]["trim3"] == pytest.approx(2.5)
    assert report["yearly_totals"][0]["sum_pct"] == pytest.approx(175.0)


def test_report_tail_structure_partitions_each_segment():
    report = backtest_module().assemble_report(_report_events())

    assert set(report["tail_structure"]) >= {"all", "main", "oos"}
    all_tail = report["tail_structure"]["all"]
    assert all_tail["未封"] == {"n": 2, "share": 50.0, "win": 100.0, "e3": 3.0}
    assert all_tail["次日断"] == {"n": 1, "share": 25.0, "win": 0.0, "e3": -1.0}
    assert all_tail["连板尾"] == {"n": 1, "share": 25.0, "win": 100.0, "e3": 10.0}
    assert report["tail_structure"]["main"]["未封"]["n"] == 1
    assert report["tail_structure"]["main"]["未封"]["share"] == pytest.approx(33.3)
    assert report["tail_structure"]["oos"]["未封"]["share"] == pytest.approx(100.0)
    assert report["tail_structure"]["oos"]["次日断"]["n"] == 0
    assert report["tail_structure"]["oos"]["连板尾"]["e3"] is None


def test_tail_structure_uses_break_day_not_deferred_execution_day():
    event = _report_event(
        "LOCK", "2023-01-03", "F1", "F1", -8.0, sealed=True, hold_days=5,
    )
    event["断板天数"] = 1

    report = backtest_module().assemble_report(pd.DataFrame([event]))

    tail = report["tail_structure"]["all"]
    assert tail["次日断"]["n"] == 1
    assert tail["次日断"]["share"] == pytest.approx(100.0)
    assert tail["连板尾"]["n"] == 0
    assert tail["未封"]["n"] == 0


def test_empty_report_has_complete_nan_free_schema():
    report = backtest_module().assemble_report(pd.DataFrame())

    aggregate_keys = {"n", "win", "e3", "med", "worst", "seal", "trim3", "by_year", "allpos"}
    for key in ("total", "main", "oos", "miss_control"):
        assert aggregate_keys <= set(report[key])
        assert report[key]["n"] == 0
        assert report[key]["e3"] is None
        assert report[key]["trim3"] is None
        assert report[key]["by_year"] == {}
    for segment in ("all", "main", "oos"):
        assert list(report["by_point"][segment]) == list(contracts.POINTS)
        assert all(stats["n"] == 0 for stats in report["by_point"][segment].values())
        assert set(report["tail_structure"][segment]) == {"未封", "次日断", "连板尾"}
        assert all(
            set(stats) == {"n", "share", "win", "e3"}
            for stats in report["tail_structure"][segment].values()
        )
    assert report["supply"] == {"months": 0, "per_month": 0.0}
    assert report["yearly_totals"] == []
    assert report["ledger_days"] == []
    assert report["best"] == [] and report["worst"] == []
    assert report["info_layer"] == {}
    assert report["poison"] == {"n": 0, "e3": None}

    def assert_no_nan(value):
        if isinstance(value, dict):
            for child in value.values():
                assert_no_nan(child)
        elif isinstance(value, list):
            for child in value:
                assert_no_nan(child)
        elif isinstance(value, float):
            assert np.isfinite(value)

    assert_no_nan(report)
    for legacy_word in ("满仓", "空仓", "贴顶", "死水", "G1", "S1"):
        assert legacy_word not in report["note_binary"]


def test_legacy_avoid_label_cannot_remove_hit_or_recreate_poison_group():
    events = pd.DataFrame([
        _report_event("A", "2023-01-03", "F1", "F1", 3.0, avoid="旧毒格"),
    ])

    report = backtest_module().assemble_report(events)

    assert report["total"]["n"] == 1
    assert report["miss_control"]["n"] == 0
    assert report["poison"] == {"n": 0, "e3": None}


def service_module():
    return importlib.import_module("alphaagent.server.services.first_relay.service")


def test_live_counts_rule_membership_and_sorts_by_final_rule_order(monkeypatch):
    service = service_module()
    pool_rows = [
        {"vt_symbol": "B", "name": "乙", "point": "F10", "actionable": True,
         "rule_ids": "F1+F10"},
        {"vt_symbol": "A", "name": "甲", "point": "F1", "actionable": True,
         "rule_ids": "F1"},
        {"vt_symbol": "C", "name": "丙", "point": "—", "actionable": False,
         "rule_ids": None},
    ]
    pool_versions = []

    def load_pool(target, rules_version=None):
        pool_versions.append(rules_version)
        return pool_rows

    monkeypatch.setattr(service.repository, "load_pool", load_pool)
    monkeypatch.setattr(service.repository, "load_signal_map", lambda target, rules_version=None: {})

    result = service.get_live(date(2023, 1, 3))

    assert [row["name"] for row in result["entries"]] == ["甲", "乙", "丙"]
    assert result["counts"]["act_F1"] == 2
    assert result["counts"]["act_F10"] == 1
    assert result["counts"]["actionable"] == 2
    assert {f"act_F{i}" for i in range(1, 11)} <= set(result["counts"])
    assert "act_G1" not in result["counts"] and "act_S1" not in result["counts"]
    assert result["rules_version"] == contracts.J12_RULES_VERSION
    assert pool_versions == [contracts.J12_RULES_VERSION]


def test_live_fallback_and_dates_pass_current_rules_version(monkeypatch):
    service = service_module()
    calls = []

    def load_pool(target, rules_version=None):
        calls.append(("load_pool", rules_version))
        return []

    def latest_pool_date(rules_version=None):
        calls.append(("latest_pool_date", rules_version))
        return date(2023, 1, 3)

    def list_pool_dates(rules_version=None):
        calls.append(("list_pool_dates", rules_version))
        return ["2023-01-03"]

    monkeypatch.setattr(service.repository, "load_pool", load_pool)
    monkeypatch.setattr(service.repository, "latest_pool_date", latest_pool_date)
    monkeypatch.setattr(service.repository, "list_pool_dates", list_pool_dates)
    monkeypatch.setattr(service.repository, "load_signal_map", lambda target, rules_version=None: {})

    result = service.get_live()
    dates = service.get_live_dates()

    assert result["trade_date"] == "2023-01-03" and result["stale"]
    assert dates == ["2023-01-03"]
    assert calls == [
        ("load_pool", contracts.J12_RULES_VERSION),
        ("latest_pool_date", contracts.J12_RULES_VERSION),
        ("load_pool", contracts.J12_RULES_VERSION),
        ("list_pool_dates", contracts.J12_RULES_VERSION),
    ]


def test_eod_message_uses_dynamic_final_rule_counts(monkeypatch):
    service = service_module()
    stats = {"actionable": 3, "avoid": 99, "act_F1": 2, "act_F10": 1}
    monkeypatch.setattr(service.pool_mod.hpr_pool, "latest_daily_date", lambda: date(2023, 1, 3))
    monkeypatch.setattr(service.pool_mod, "compute_pool", lambda data_date: {
        "exec_date": "2023-01-04", "entries": [], "filter_stats": stats,
    })
    monkeypatch.setattr(service.repository, "save_pool", lambda *args: 3)

    result = service.run_eod_finalize()

    assert "F1 2" in result["message"]
    assert "F10 1" in result["message"]
    for legacy_text in ("G1", "S1", "贴顶"):
        assert legacy_text not in result["message"]
    assert result["stats"] is stats


def test_schema_has_pool_trigger_and_rule_columns_and_idempotent_patches():
    schema = importlib.import_module("alphaagent.server.db.schema")

    assert schema.j12_pool_entries.c.trigger_price.type.python_type is float
    assert schema.j12_pool_entries.c.rule_ids.type.length == 64
    statements = []

    class Connection:
        def exec_driver_sql(self, sql):
            statements.append(sql)

    class Begin:
        def __enter__(self):
            return Connection()

        def __exit__(self, *args):
            return False

    class Engine:
        def begin(self):
            return Begin()

    schema._apply_compatible_schema_patches(Engine())

    assert "ALTER TABLE j12_pool_entries ADD COLUMN IF NOT EXISTS trigger_price FLOAT" in statements
    assert "ALTER TABLE j12_pool_entries ADD COLUMN IF NOT EXISTS rule_ids VARCHAR(64)" in statements


def test_repository_pool_reads_filter_rules_version_without_database(monkeypatch):
    repository = importlib.import_module("alphaagent.server.services.first_relay.repository")
    statements = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

        def scalar_one_or_none(self):
            return None

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    class SessionScope:
        def __enter__(self):
            return Session()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(repository.schema, "ensure_schema_once", lambda engine: None)
    monkeypatch.setattr(repository, "get_engine", lambda: object())
    monkeypatch.setattr(repository, "session_scope", lambda: SessionScope())
    version = contracts.J12_RULES_VERSION

    repository.load_pool(date(2023, 1, 3), rules_version=version)
    repository.latest_pool_date(rules_version=version)
    repository.list_pool_dates(rules_version=version)
    repository.load_pool(date(2023, 1, 3))

    assert len(statements) == 4
    for statement in statements[:3]:
        assert "j12_pool_entries.rules_version" in str(statement.whereclause)
        assert version in statement.compile().params.values()
    assert "j12_pool_entries.rules_version" not in str(statements[3].whereclause)


def test_save_pool_maps_trigger_price_and_rule_ids_without_database(monkeypatch):
    repository = importlib.import_module("alphaagent.server.services.first_relay.repository")
    schema = importlib.import_module("alphaagent.server.db.schema")
    captured = {}

    class Insert:
        def values(self, **values):
            captured.update(values)
            return self

    class Session:
        def execute(self, statement):
            return None

    class SessionScope:
        def __enter__(self):
            return Session()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(repository.schema, "ensure_schema_once", lambda engine: None)
    monkeypatch.setattr(repository, "get_engine", lambda: object())
    monkeypatch.setattr(repository, "session_scope", lambda: SessionScope())
    monkeypatch.setattr(repository, "pg_insert", lambda table: Insert())

    saved = repository.save_pool(date(2023, 1, 3), [{
        "vt_symbol": "000001.SZSE",
        "name": "平安银行",
        "point": "F1",
        "trigger_price": 12.03,
        "rule_ids": "F1+F10",
    }], contracts.J12_RULES_VERSION)

    assert saved == 1
    assert captured["trigger_price"] == pytest.approx(12.03)
    assert captured["rule_ids"] == "F1+F10"
    assert schema.j12_pool_entries.c.trigger_price is not None


def test_live_signal_map_passes_current_rules_version(monkeypatch):
    service = service_module()
    versions = []
    monkeypatch.setattr(service.repository, "load_pool", lambda *args, **kwargs: [])

    def load_signal_map(target, rules_version=None):
        versions.append(rules_version)
        return {}

    monkeypatch.setattr(service.repository, "load_signal_map", load_signal_map)

    service.get_live(date(2023, 1, 3))

    assert versions == [contracts.J12_RULES_VERSION]


def test_repository_signal_map_filters_rules_version_without_database(monkeypatch):
    repository = importlib.import_module("alphaagent.server.services.first_relay.repository")
    statements = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return Result()

    class SessionScope:
        def __enter__(self):
            return Session()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(repository.schema, "ensure_schema_once", lambda engine: None)
    monkeypatch.setattr(repository, "get_engine", lambda: object())
    monkeypatch.setattr(repository, "session_scope", lambda: SessionScope())
    version = contracts.J12_RULES_VERSION

    repository.load_signal_map(date(2023, 1, 3), rules_version=version)
    repository.load_signal_map(date(2023, 1, 3))

    assert "j12_signals.rules_version" in str(statements[0].whereclause)
    assert version in statements[0].compile().params.values()
    assert "j12_signals.rules_version" not in str(statements[1].whereclause)
