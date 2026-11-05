"""hpr-v7.24 质量腿：K4 二板板型 + C1 地基位置。"""

from __future__ import annotations

from alphaagent.server.services.high_relay import contracts, pool, quiz


def _k4(**overrides):
    kwargs = {
        "group4": "三接四阳", "b1_open": 1.0, "b2_open": 0.0, "b3_open": 5.0,
        "auction_pct": 1.0, "b1_turn": 6.0, "b2_turn": 10.0, "b3_turn": 15.0,
        "foundation_chg": 0.0, "prev_wave60": 0, "dist_h60": -10.0,
        "b1_type": "下影", "b2_type": "下影", "b3_type": "下影",
    }
    kwargs.update(overrides)
    return pool.tag_weak(**kwargs)


def test_k4_requires_shadow_second_board():
    assert _k4()["no"] == "K4"
    for bad in ("实体", "一字"):
        assert _k4(b2_type=bad) is None
    assert _k4(b2_type=None)["no"] == "K4"  # 缺板型不误杀


def test_weak_matcher_mirrors_tag_weak():
    chain = dict(b1_open=1.0, b2_open=0.0, b3_open=5.0, b1_turn=6.0,
                 b2_turn=10.0, b3_turn=15.0, foundation_chg=0.0,
                 prev_wave60=0, dist_h60=-10.0)
    assert pool.match_weak_schemes("三接四阳", **chain, b2_type="下影")
    assert pool.match_weak_schemes("三接四阳", **chain, b2_type="一字") == []


def test_c1_requires_foundation_below_ma10():
    hit = pool.tag_scheme("二接三阳", 8.0, 5.0, None, auction_pct=1.0,
                          dist_ma10=-3.0)
    assert hit is not None and hit["no"] == "C1"
    assert pool.tag_scheme("二接三阳", 8.0, 5.0, None, auction_pct=1.0,
                           dist_ma10=0.0) is None
    assert pool.tag_scheme("二接三阳", 8.0, 5.0, None, auction_pct=1.0,
                           dist_ma10=1.0) is None


def test_c1_matcher_mirrors():
    assert pool.match_schemes("二接三阳", 8.0, 5.0, None, dist_ma10=-3.0)
    assert pool.match_schemes("二接三阳", 8.0, 5.0, None, dist_ma10=0.0) == []


def test_quiz_explains_c1_foundation_leg():
    reasons, kind, fails, _ = quiz.explain_miss(
        n_board=2, yang=True, group4="二接三阳",
        b1_open=8.0, b2_open=5.0, b3_open=None,
        b2_turn=10.0, b3_turn=None, buy_open=1.0,
        pre20_pct=5.0, foundation_chg=0.0, dist_ma10=3.0,
    )
    assert kind == "toxic"
    assert "距MA10" in fails
    assert any("C1" in line and "十日线" in line for line in reasons)


def test_quiz_explains_weak_board_type_leg():
    line, near, fails, row = quiz._nearest_weak_line(
        "三接四阳", 1.0, 0.0, 5.0, 6.0, 10.0, 15.0, 1.0,
        foundation_chg=0.0, prev_wave60=0, dist_h60=-10.0,
        b1_type="下影", b2_type="实体", b3_type="下影",
    )
    assert near is True
    assert "二板开" in fails
    assert "板型" in line
    assert row is not None and row["no"] == "K4"


def test_version():
    assert contracts.HPR_RULES_VERSION == "hpr-v7.31"
    assert quiz.QUIZ_CONTENT_VERSION == 63

