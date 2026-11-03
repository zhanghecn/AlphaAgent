"""hpr-v7.28 展示成绩单一来源:规则页/题库/面板都读同一份成交口径。"""

from alphaagent.server.services.high_relay import backtest, contracts, service


def test_stat_text_is_one_format():
    assert contracts.stat_text({"n": 48, "win": 0.75, "mean": 10.549375}) == \
        "48笔·胜75%·均+10.5"
    # 四舍五入到 0.1:9.95 显示 +10.0(不是浮点砍尾的 +9.9)
    assert contracts.stat_text({"n": 2, "win": 1.0, "mean": 9.95}) == \
        "2笔·胜100%·均+10.0"
    assert contracts.stat_text(None) == ""


def test_stat_rows_group_point_and_branch_by_taken():
    rows = backtest._stat_rows([
        {"p": "K4", "s": "缩量承接", "tk": True, "r": 10.0},
        {"p": "K4", "s": "缩量承接", "tk": True, "r": 9.9},
        {"p": "K4", "s": "一板平开", "tk": True, "r": -5.0},
        {"p": "K4", "s": "一板平开", "tk": False, "r": 99.0},
    ])
    assert rows["K4"]["n"] == 3
    assert rows["K4|缩量承接"]["mean"] == 9.95
    assert rows["K4|一板平开"]["n"] == 1


def test_rules_read_materialized_stat_rows(monkeypatch):
    fake = {
        "stat_rows": {
            "B1": {"n": 24, "win": 0.9583, "mean": 13.7504},
            "B1|转温": {"n": 14, "win": 0.9286, "mean": 16.4993},
            "K4|缩量承接": {"n": 2, "win": 1.0, "mean": 9.95},
        }
    }
    monkeypatch.setattr(service.repository, "load_backtest_report", lambda _v: fake)

    rules = service.get_rules()
    assert rules["point_stats"]["B1"] == "24笔·胜96%·均+13.8"
    row = next(r for r in rules["common_cheat_rows"]
               if r["no"] == "B1" and r["sub"] == "转温")
    assert row["stat"] == "14笔·胜93%·均+16.5"
    k4 = next(r for r in rules["weak_cheat_rows"]
              if r["no"] == "K4" and r["sub"] == "缩量承接")
    assert k4["stat"] == "2笔·胜100%·均+10.0"


def test_rules_fall_back_to_constants_without_report(monkeypatch):
    monkeypatch.setattr(service.repository, "load_backtest_report", lambda _v: None)
    rules = service.get_rules()
    assert rules["point_stats"]["C1"] == contracts.POINT_STATS["C1"]


def test_stats_are_all_era_taken_caliber():
    assert contracts.POINT_STATS["B1"] == "24笔·胜96%·均+13.8"
    assert contracts.POINT_STATS["C1"] == "8笔·胜100%·均+14.8"
    assert contracts.POINT_STATS["C2"] == "48笔·胜75%·均+10.5"
    assert contracts.POINT_STATS["C3"] == "5笔·胜100%·均+13.2"


def test_weak_branch_stats_are_branch_specific():
    k4 = {r["sub"]: r["stat"] for r in contracts.WEAK_CHEAT_ROWS if r["no"] == "K4"}
    assert k4 == {
        "缩量承接": "2笔·胜100%·均+10.0",
        "一板平开": "4笔·胜75%·均+32.3",
    }
    k5 = next(r["stat"] for r in contracts.WEAK_CHEAT_ROWS if r["no"] == "K5")
    assert k5 == "25笔·胜84%·均+7.8"
