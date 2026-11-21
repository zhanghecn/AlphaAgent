"""v7.34 高价锁仓庄股回避:买价≥45元×决策板换手<3% 命中也不买。

证据锚(203笔交割单,勿回归):
- 命中 3 笔全雷:雷赛智能 76.51×2.48→-9.42 / 浙江东日 58.60×1.04→+2.10 /
  三棵树 49.49×2.50→+2.44,均 -1.63;
- 66 笔大肉(≥15%)零误伤;边界扰动九宫格(价40/45/50×换手2.5/3/3.5)全稳;
- 低价锁仓=K10 肥腿(<8元 +11.71 / 8~20元 +17.90)不得误杀;
- 42~43 元锁仓大肉(旭光电子 42.01×0.50→+16.16 / 友邦吊顶 43.48×1.12→+13.11)
  在 45 线下必须放行;紫光国微 106.51 换手 4.0(放量)必须放行;
- 天普股份 73.82×三板 1.09/1.72/1.44(实盘 -19%)为口诀源案例。
"""
from alphaagent.server.services.high_relay import contracts
from alphaagent.server.services.high_relay import pool as pool_mod


def test_version() -> None:
    assert contracts.HPR_RULES_VERSION == "hpr-v7.34"


def test_avoid_hits_three_evidence_trades() -> None:
    # 雷赛智能(二接三,b2t=2.48)/浙江东日(b1 口径 b2t=1.04)/三棵树(b2t=2.50)
    assert pool_mod.static_avoid("A2", "二接三阳", 0, 0, 0,
                                 buy_price=76.51, n_board=2, b2_turn=2.48) \
        == contracts.HIGH_PRICE_LOCK_TEXT
    assert pool_mod.static_avoid("B1", "二接三阴", 0, 0, 0,
                                 buy_price=58.60, n_board=2, b2_turn=1.04)
    assert pool_mod.static_avoid("A1", "二接三阳", 0, 0, 0,
                                 buy_price=49.49, n_board=2, b2_turn=2.50)


def test_avoid_tianpu_triple_lock() -> None:
    # 天普 73.82 三接四,三板换手 1.44(2% 分位)
    assert pool_mod.static_avoid("B3", "三接四阴", 0, 0, 0,
                                 buy_price=73.82, n_board=3, b2_turn=1.72, b3_turn=1.44)


def test_no_avoid_below_45_even_locked() -> None:
    # 42~43 元锁仓大肉必须放行(旭光/友邦);低价 K10 肥腿(华瓷 19.88×1.69)不拦
    assert pool_mod.static_avoid("C3", "三接四阴", 0, 0, 0,
                                 buy_price=42.01, n_board=3, b3_turn=0.50) == ""
    assert pool_mod.static_avoid("C2", "三接四阴", 0, 0, 0,
                                 buy_price=43.48, n_board=3, b3_turn=1.12) == ""
    assert pool_mod.static_avoid("A2", "二接三阳", 0, 0, 0,
                                 buy_price=19.88, n_board=2, b2_turn=1.69) == ""


def test_no_avoid_high_price_with_volume() -> None:
    # 高价放量不拦:紫光国微 106.51×4.0 / 云南锗业 100.08×4.77
    assert pool_mod.static_avoid("K2", "三接四阴", 0, 0, 0,
                                 buy_price=106.51, n_board=3, b3_turn=4.00) == ""
    assert pool_mod.static_avoid("C2", "三接四阳", 0, 0, 0,
                                 buy_price=100.08, n_board=3, b3_turn=4.77) == ""


def test_boundary_exact_45_and_3() -> None:
    # 边界含在雷区:45.00 元命中、换手恰 3.0 不拦(雷票换手全 <2.5,上界留 3.0 平台)
    assert pool_mod.static_avoid("C2", "三接四阳", 0, 0, 0,
                                 buy_price=45.00, n_board=3, b3_turn=2.99)
    assert pool_mod.static_avoid("C2", "三接四阳", 0, 0, 0,
                                 buy_price=50.00, n_board=3, b3_turn=3.00) == ""


def test_legacy_signature_still_empty() -> None:
    # 旧签名(不传新参)保持恒空,兼容历史调用
    assert pool_mod.static_avoid("A1", "二接三阳", 0, 0, 0) == ""
