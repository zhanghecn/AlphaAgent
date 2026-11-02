"""hpr-v7.26 C3 三板一字退役:只保留二板一字,三板一字不再独立成口诀。"""

from alphaagent.server.services.high_relay import contracts, pool


def test_c3_has_only_second_board_yizi():
    subs = [s.get("sub") for s in contracts.SCHEMES if s["no"] == "C3"]
    assert subs == ["二板一字"]
    assert all(
        r.get("sub") != "三板一字" for r in contracts.CHEAT_ROWS if r["no"] == "C3"
    )


def test_three_board_yizi_no_longer_matches_c3():
    hit = pool.tag_scheme(
        "三接四阳", b1_open=2.0, b2_open=1.0, b3_open=10.0,
        auction_pct=7.2, b3_turn=4.0,
    )
    assert hit is None


def test_weak_era_group_states_are_frozen():
    """2020-22 弱市定型段不随强市分支退役改写:2020-01/02=both,其后=weak。"""
    trades = [
        {"m": "2020-01", "g": "strong", "p": "A1", "r": 99.0},
        {"m": "2020-03", "g": "strong", "p": "C3", "r": -99.0},
        {"m": "2020-04", "g": "weak", "p": "K5", "r": 1.0},
        {"m": "2022-12", "g": "weak", "p": "K5", "r": 1.0},
    ]
    states = contracts.dyn_month_states(trades)
    assert contracts.dyn_state_at(states, "2020-01") == "both"
    assert contracts.dyn_state_at(states, "2020-03") == "weak"
    assert contracts.dyn_state_at(states, "2020-04") == "weak"
    assert contracts.dyn_state_at(states, "2022-12") == "weak"
    # 即使旧物化里残留 strong,也只读冻结值
    assert contracts.dyn_state_at({"2020-03": "strong"}, "2020-03") == "weak"
