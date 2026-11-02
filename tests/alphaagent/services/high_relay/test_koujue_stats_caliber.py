"""hpr-v7.27 全口诀展示成绩统一为成交口径(共用/未启用不计)。"""

from alphaagent.server.services.high_relay import contracts


def test_strong_point_stats_are_taken_caliber():
    assert contracts.POINT_STATS["C1"] == "7笔·胜100%·均+16.4"
    assert contracts.POINT_STATS["C2"] == "47笔·胜77%·均+10.9"
    assert contracts.POINT_STATS["C3"] == "5笔·胜100%·均+13.2"


def test_weak_branch_stats_are_branch_specific():
    k4 = {r["sub"]: r["stat"] for r in contracts.WEAK_CHEAT_ROWS if r["no"] == "K4"}
    assert k4 == {
        "缩量承接": "2笔·胜100%·均+10.0",
        "一板平开": "4笔·胜75%·均+32.3",
    }
