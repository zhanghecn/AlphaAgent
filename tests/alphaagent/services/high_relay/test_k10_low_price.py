"""hpr-v7.30 K10 低价一字锁仓：分支、价格上界、N=3高位加速腿与镜像。"""

from alphaagent.server.services.high_relay import contracts, pool, quiz


def test_k10_is_registered_with_low_price_branches():
    assert "K10" in contracts.WEAK_POINT_KEYS
    rows = [r for r in contracts.WEAK_CHEAT_ROWS if r["no"] == "K10"]
    assert {r["sub"] for r in rows} == {"低价·二接三", "低价·三接四"}
    assert contracts.HPR_RULES_VERSION == "hpr-v7.31"
    assert quiz.QUIZ_CONTENT_VERSION == 63


def test_low_price_n2_matches_and_price_cliff():
    hit = pool.tag_weak(
        "二接三阳", None, None, None, auction_pct=3.0,
        b2_type="一字", buy_price=4.0, b1_f_turn_ratio=0.8)
    assert hit is not None
    assert (hit["no"], hit["sub"]) == ("K10", "低价·二接三")

    # 买价 4.41 > 4.4：低价分支不命中（阳顶格已退役）
    assert pool.tag_weak(
        "二接三阳", None, None, None, auction_pct=3.0,
        b2_type="一字", buy_price=4.41, b1_f_turn_ratio=0.8) is None


def test_low_price_requires_one_word_and_turnover_band():
    assert pool.tag_weak(
        "二接三阳", None, None, None, auction_pct=3.0,
        b2_type="下影", buy_price=4.0, b1_f_turn_ratio=0.8) is None
    assert pool.tag_weak(
        "二接三阳", None, None, None, auction_pct=3.0,
        b2_type="一字", buy_price=4.0, b1_f_turn_ratio=1.50) is None


def test_n3_high_accel_is_blocked_but_n2_is_not():
    common = dict(auction_pct=3.0, b2_type="一字", buy_price=3.5,
                  b1_f_turn_ratio=0.8, dist_h60=-1.0, dist_ma10=5.0)
    # N=3 高位加速：距60高>-10 且 距MA10>3 -> 不接
    assert pool.tag_weak("三接四阳", None, None, None, **common) is None
    # 同一位置在 N=2 不误伤（N=2 该段中性）
    n2 = pool.tag_weak("二接三阳", None, None, None, **common)
    assert n2 is not None and n2["sub"] == "低价·二接三"


def test_n3_deep_position_still_matches():
    hit = pool.tag_weak(
        "三接四阳", None, None, None, auction_pct=3.0,
        b2_type="一字", buy_price=3.5, b1_f_turn_ratio=0.8,
        dist_h60=-27.0, dist_ma10=-5.5)
    assert hit is not None
    assert (hit["no"], hit["sub"]) == ("K10", "低价·三接四")


def test_top_open_branch_is_retired():
    """阳顶格已退役(v7.31):弱市去top3 -3.6、强市未启用去top3 -19.5,两时代都靠3笔。"""
    assert pool.tag_weak(
        "二接三阳", None, None, None, auction_pct=8.5,
        b2_type="一字", buy_price=10.0) is None
    assert pool.tag_weak(
        "二接三阴", None, None, None, auction_pct=8.5,
        b2_type="一字", buy_price=10.0) is None


def test_match_weak_schemes_mirrors_k10():
    deep = pool.match_weak_schemes(
        "三接四阳", None, None, None, b2_type="一字", buy_price=3.5,
        b1_f_turn_ratio=0.8, dist_h60=-27.0, dist_ma10=-5.5)
    assert [s["sub"] for s in deep if s["no"] == "K10"] == ["低价·三接四"]
    hot = pool.match_weak_schemes(
        "三接四阳", None, None, None, b2_type="一字", buy_price=3.5,
        b1_f_turn_ratio=0.8, dist_h60=-1.0, dist_ma10=5.0)
    assert not [s for s in hot if s["no"] == "K10"]
