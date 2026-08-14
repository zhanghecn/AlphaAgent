from datetime import date

from alphaagent.server.services.lianban.detector import classify_limit_up

D = date(2026, 8, 12)


def test_main_board_exact_hit():
    # 开开实业: prev=15.70 close=17.27 主板10%
    r = classify_limit_up(symbol="600272", name="开开实业", prev_close=15.70,
                          open_price=17.27, close_price=17.27, high_price=17.27, trade_date=D)
    assert r.is_limit_up and r.board == "main" and r.limit_price == 17.27 and r.is_one_word


def test_cyb_20pct():
    r = classify_limit_up(symbol="300862", name="蓝盾光电", prev_close=27.37,
                          open_price=30.0, close_price=32.84, high_price=32.84, trade_date=D)
    assert r.is_limit_up and r.board == "cyb" and r.limit_price == 32.84


def test_st_main_5pct():
    r = classify_limit_up(symbol="002052", name="ST同洲", prev_close=10.00,
                          open_price=10.2, close_price=10.50, high_price=10.50, trade_date=D)
    assert r.is_limit_up and r.limit_price == 10.50


def test_st_cyb_is_20pct_not_5pct():
    # ST迪威迅(300167) pct=14.16%: 5%档会误判,20%档正确不涨停
    r = classify_limit_up(symbol="300167", name="ST迪威迅", prev_close=4.39,
                          open_price=4.5, close_price=5.01, high_price=5.05, trade_date=D)
    assert not r.is_limit_up


def test_st_switch_day_promotes_to_10pct():
    # ST金鸿(000669) prev=3.54 close=3.89: 超5%档价3.72,精确命中10%档3.89 → 涨停
    r = classify_limit_up(symbol="000669", name="ST金鸿", prev_close=3.54,
                          open_price=3.7, close_price=3.89, high_price=3.89, trade_date=D)
    assert r.is_limit_up and r.limit_price == 3.89


def test_st_switch_day_over_5pct_but_not_limit():
    # *ST中迪 prev≈10.17 close=10.89(+7.08%): 超5%档,但未命中10%档11.19 → 不涨停
    r = classify_limit_up(symbol="000609", name="*ST中迪", prev_close=10.17,
                          open_price=10.4, close_price=10.89, high_price=11.0, trade_date=D)
    assert not r.is_limit_up


def test_bse_30pct():
    r = classify_limit_up(symbol="920856", name="浩淼科技", prev_close=10.00,
                          open_price=11.0, close_price=13.00, high_price=13.00, trade_date=D)
    assert r.is_limit_up and r.board == "bse"


def test_touched_but_not_sealed():
    r = classify_limit_up(symbol="600000", name="浦发银行", prev_close=10.00,
                          open_price=10.2, close_price=10.5, high_price=11.0, trade_date=D)
    assert not r.is_limit_up and r.touched_limit


def test_no_prev_close_skipped():
    r = classify_limit_up(symbol="600000", name="浦发银行", prev_close=None,
                          open_price=1.0, close_price=2.0, high_price=2.0, trade_date=D)
    assert not r.is_limit_up


def test_cyb_before_20200824_is_10pct():
    r = classify_limit_up(symbol="300001", name="特锐德", prev_close=10.00,
                          open_price=10.5, close_price=11.00, high_price=11.00, trade_date=date(2020, 1, 15))
    assert r.is_limit_up and r.limit_price == 11.00


def test_st_main_5pct_rounding_guard():
    # 回归: prev=10.17 → 5%档真值 10.6785, 必须 round 到 10.68(锁定 +1e-9 半值守卫)
    r = classify_limit_up(symbol="000609", name="*ST中迪", prev_close=10.17,
                          open_price=10.5, close_price=10.68, high_price=10.68, trade_date=D)
    assert r.is_limit_up and r.limit_price == 10.68


def test_zero_prev_close_skipped():
    r = classify_limit_up(symbol="600000", name="浦发银行", prev_close=0.0,
                          open_price=1.0, close_price=2.0, high_price=2.0, trade_date=D)
    assert not r.is_limit_up and r.limit_price is None


def test_none_name_treated_as_non_st():
    # 脏数据守卫: name=None 不抛异常, 按非 ST 10% 档判定
    r = classify_limit_up(symbol="600000", name=None, prev_close=10.00,
                          open_price=10.5, close_price=11.00, high_price=11.00, trade_date=D)
    assert r.is_limit_up and not r.is_st


def test_cyb_reform_day_20200824_is_20pct():
    # 注册制边界日当天即 20%
    r = classify_limit_up(symbol="300001", name="特锐德", prev_close=10.00,
                          open_price=11.0, close_price=12.00, high_price=12.00, trade_date=date(2020, 8, 24))
    assert r.is_limit_up and r.limit_price == 12.00


def test_one_word_low_none_approximation():
    # low 缺省时以 min(open, close) 近似: open==close==high 仍判一字
    r = classify_limit_up(symbol="600272", name="开开实业", prev_close=20.00,
                          open_price=22.00, close_price=22.00, high_price=22.00, trade_date=D)
    assert r.is_limit_up and r.is_one_word


def test_sealed_but_not_one_word():
    # 涨停但开板过: open < close == high == 涨停价 → 非一字
    r = classify_limit_up(symbol="600000", name="浦发银行", prev_close=10.00,
                          open_price=10.5, close_price=11.00, high_price=11.00,
                          trade_date=D, low_price=10.40)
    assert r.is_limit_up and not r.is_one_word


def test_bse_8_prefix():
    r = classify_limit_up(symbol="830799", name="艾融软件", prev_close=10.00,
                          open_price=11.0, close_price=13.00, high_price=13.00, trade_date=D)
    assert r.is_limit_up and r.board == "bse" and r.limit_price == 13.00


def test_bse_limit_price_truncates_not_rounds():
    """北交所实证(浩淼科技 920856, 2026-08-12): 11.49×1.3=14.937,
    四舍五入=14.94 会越 30% 限制, 交易所实际涨停价 14.93(分位截断)。"""
    from datetime import date as _date

    r = classify_limit_up(
        symbol="920856", name="浩淼科技", prev_close=11.49,
        open_price=11.61, close_price=14.93, high_price=14.93,
        trade_date=_date(2026, 8, 12),
    )
    assert r.is_limit_up and r.limit_price == 14.93

    # 对照: 精确命中原则下 close=14.94 ≠ 截断价 14.93 → 不判涨停(摸板)
    r2 = classify_limit_up(
        symbol="920856", name="浩淼科技", prev_close=11.49,
        open_price=11.61, close_price=14.94, high_price=14.94,
        trade_date=_date(2026, 8, 12),
    )
    assert not r2.is_limit_up and r2.touched_limit


def test_bse_floor_guard_on_exact_cent_value():
    """浮点防护: 22.00×1.3=28.6 的真值恰为整数分, 浮点可能存成 28.5999…, 截断不得丢分。"""
    from datetime import date as _date

    r = classify_limit_up(
        symbol="920222", name="测试北证", prev_close=22.00,
        open_price=26.0, close_price=28.60, high_price=28.60,
        trade_date=_date(2026, 7, 23),
    )
    assert r.is_limit_up and r.limit_price == 28.60
