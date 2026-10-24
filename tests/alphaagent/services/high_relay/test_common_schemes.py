import pandas as pd

from alphaagent.server.services.high_relay import backtest, contracts, live_scan, quiz, service


def test_dyn_take_point_only_enables_turn_warm_branch_in_every_regime():
    assert contracts.dyn_take_point("weak", "B1", "—", "转温") == "B1"
    assert contracts.dyn_take_point("strong", "B1", "—", "转温") == "B1"
    assert contracts.dyn_take_point("both", "B1", "—", "转温") == "B1"
    assert contracts.dyn_take_point("weak", "B1", "—", "续强") == ""
    assert contracts.dyn_take_point("strong", "B1", "—", "续强") == "B1"
    assert contracts.dyn_take_point("weak", "B1", "K9", "续强") == "K9"
    assert contracts.dyn_take_point("strong", "—", "K5") == "K5"


def test_common_scheme_candidates_respect_branch_and_auction_window():
    candidates = [
        {"no": "B1", "sub": "转温", "today": [3.0, 5.0]},
        {"no": "B1", "sub": "续强", "today": [6.0, 9.0]},
        {"no": "C2", "today": [5.0, 9.0]},
    ]

    assert contracts.common_scheme_candidates(candidates, 4.0) == [candidates[0]]
    assert contracts.common_scheme_candidates(candidates, 7.0) == []
    assert contracts.common_scheme_candidates(candidates) == [candidates[0]]


def test_common_scheme_labels_expose_branch_instead_of_whole_b1():
    assert contracts.common_scheme_labels() == ["K5", "B1·转温"]


def _b1_entry() -> dict[str, object]:
    return {
        "actionable": True,
        "auction_gate": "today_3_5,today_6_9",
        "group4": "二接三阴",
        "b1_open": 10.0,
        "b2_open": 8.0,
        "b3_open": None,
        "b2_turn": 18.0,
        "b3_turn": None,
        "foundation_chg": None,
        "pre10_pct": None,
        "foundation_pose": None,
        "anchor_pos": None,
        "anchor_dist": None,
        "dist_ma10": None,
    }


def test_weak_market_scan_only_opens_turn_warm_auction_window():
    allowed, scan_entry = live_scan._strong_access(_b1_entry(), "weak")

    assert allowed is True
    assert scan_entry["auction_gate"] == "today_3_5"
    assert live_scan._first_jump_status(scan_entry, 4.0, strong_ok=allowed) is None
    assert live_scan._first_jump_status(scan_entry, 7.0, strong_ok=allowed) == "skipped_auction"


def test_weak_market_scan_does_not_open_continue_strength_branch():
    entry = {**_b1_entry(), "b1_open": 1.0}

    allowed, _ = live_scan._strong_access(entry, "weak")

    assert allowed is False


def test_live_row_common_hit_respects_actual_auction():
    row = {
        "candidates": [
            {"no": "B1", "sub": "转温", "today": [3.0, 5.0]},
            {"no": "B1", "sub": "续强", "today": [6.0, 9.0]},
        ],
        "auction_pct": 7.0,
    }

    assert service._common_strong_hit(row) is False
    assert service._common_strong_hit({**row, "auction_pct": 4.0}) is True


def test_dyn_trades_keep_strong_branch_for_split_statistics():
    events = pd.DataFrame([{
        "月": "2021-01", "弱口诀": "—", "方案点": "B1", "方案子项": "转温", "E3%": 8.16,
    }])

    assert backtest._dyn_trades(events) == [
        {"m": "2021-01", "g": "strong", "p": "B1", "s": "转温", "r": 8.16},
    ]


def _row_keys(rows):
    return {(row["no"], row.get("sub")) for row in rows}


def test_rules_split_common_and_strong_rows_by_branch(monkeypatch):
    monkeypatch.setattr(service.repository, "load_backtest_report", lambda _version: None)

    payload = service.get_rules()

    assert ("K5", None) in _row_keys(payload["common_cheat_rows"])
    assert ("B1", "转温") in _row_keys(payload["common_cheat_rows"])
    assert ("B1", "续强") in _row_keys(payload["cheat_rows"])
    assert ("B1", "转温") not in _row_keys(payload["cheat_rows"])
    assert payload["dyn_always_on"] == ["K5", "B1·转温"]


def test_current_koujue_splits_b1_stats_and_health_by_branch(monkeypatch):
    report = {
        "dyn_trades": [
            {"m": "2026-01", "g": "strong", "p": "B1", "s": "转温", "r": 10.0},
            {"m": "2026-01", "g": "strong", "p": "B1", "s": "续强", "r": -5.0},
            {"m": "2026-01", "g": "weak", "p": "K5", "r": 8.0},
        ],
        "dyn_month_states": {"2026-01": "strong"},
    }
    monkeypatch.setattr(service.repository, "load_backtest_report", lambda _version: report)

    payload = service.get_current_koujue()
    common = {row["sub"]: row for row in payload["groups"]["common"]["rows"] if row["no"] == "B1"}
    strong = {row["sub"]: row for row in payload["groups"]["strong"]["rows"] if row["no"] == "B1"}
    assert common["转温"]["dyn_stat"] == "近9月 1笔·胜100%·均+10.0"
    assert strong["续强"]["dyn_stat"] == "近9月 1笔·胜0%·均-5.0"

    health = {row["sub"]: row for row in payload["health"] if row["no"] == "B1"}
    assert health["转温"]["group"] == "common"
    assert health["续强"]["group"] == "strong"
    assert health["转温"]["avg_all"] == 10.0
    assert health["续强"]["avg_all"] == -5.0


def _quiz_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    events = []
    bars = []
    cases = [("转温票", "B1", "转温", 4.0), ("续强票", "B1", "续强", 7.0),
             ("普通miss", "—", "", 0.0)]
    for offset, (name, point, sub, buy_open) in enumerate(cases):
        day = pd.Timestamp("2021-01-03") + pd.Timedelta(days=offset)
        bar_index = offset * 2 + 1
        events.append({
            "_bar_i": bar_index, "代码": f"00000{offset}.SZSE", "名称": name,
            "买入日": day, "年": "2021", "月": "2021-01", "四组": "二接三阴", "N": 2,
            "阴阳": "阴", "方案点": point, "方案子项": sub, "弱口诀": "—",
            "未完": False, "买入开盘%": buy_open, "封住": False, "_e3_exit_i": bar_index,
            "E3%": 1.0, "E3退出日": day.date().isoformat(), "E3退出价": 10.0,
            "E3原因": "break_day_close", "买价": 11.0, "链": "实体→实体",
            "b1开盘%": 10.0 if point == "B1" else 0.0,
            "b2开盘%": 8.0 if point == "B1" else 0.0, "b3开盘%": None,
            "b1换手%": 5.0, "b2换手%": 18.0 if point == "B1" else 1.0, "b3换手%": None,
            "前20日涨幅%": 0.0, "前10日涨幅%": 0.0, "地基涨跌%": 0.0,
            "前波60日最高板": 0, "距60日新高%": -10.0, "地基姿态": "骑线",
            "地基距MA20%": 1.0, "距MA10%": 1.0, "锚位%": None, "锚距": None,
        })
        bars.extend([
            {"vt_symbol": f"00000{offset}.SZSE", "trade_date": day - pd.Timedelta(days=1),
             "open_price": 10.0, "high_price": 10.2, "low_price": 9.8,
             "close_price": 10.0, "volume": 1000, "pos": 0},
            {"vt_symbol": f"00000{offset}.SZSE", "trade_date": day,
             "open_price": 10.0 * (1 + buy_open / 100), "high_price": 11.0,
             "low_price": 9.9, "close_price": 10.5, "volume": 2000, "pos": 1},
        ])
    return pd.DataFrame(events), pd.DataFrame(bars)


def test_build_questions_normalizes_no_take_to_miss_in_weak_market():
    events, bars = _quiz_inputs()

    questions = quiz.build_questions(events, bars, {"2021-01": "weak"})
    answers = {row["name"]: row["payload"]["answer"] for row in questions}

    assert answers["转温票"]["should_buy"] is True
    assert answers["转温票"]["point"] == "B1"
    assert answers["续强票"]["should_buy"] is False
    assert answers["续强票"]["point"] == "—"
    assert answers["普通miss"]["should_buy"] is False
    assert answers["普通miss"]["point"] == "—"
