"""连板天梯 build_ladder: 双数据源 / ST 过滤 / 反标 / 今日晋级率 / 概念 / 排序。

sqlite 内存库真实落库验证(见 conftest.fake_session), 不碰网络。

数据剧本(两个连续交易日 D2=2026-08-11 / D3=2026-08-12):
- D2 涨停: S1/S2 首板, S3(ST) 首板, S4 二板, S5 三板, S6/S7 四板
- D3 涨停: S1 二板, S3(ST) 二板, S4 三板, S6 五板, S8/S9/S10 首板
  (S2/S5/S7 断板)
非 ST 口径梯队: 5板{S6} / 3板{S4} / 2板{S1} / 1板{S8,S9,S10};
晋级率精确值见 test_pool_archive_today_promotion_exact。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import insert

from alphaagent.server.db import schema
from alphaagent.server.services.lianban.ladder import build_ladder

D2 = date(2026, 8, 11)
D3 = date(2026, 8, 12)

S1, S2, S3 = "600001.SSE", "600002.SSE", "600003.SSE"
S4, S5, S6, S7 = "600004.SSE", "600005.SSE", "600006.SSE", "600007.SSE"
S8, S9, S10 = "600008.SSE", "600009.SSE", "600010.SSE"


# ── 数据构造辅助 ─────────────────────────────────────────────────────────


def _daily(d: date, sym: str, streak: int, *, is_st: bool = False,
           close: float = 10.0, pct: float = 10.0, one_word: bool = False,
           board: str = "main") -> dict:
    return {
        "trade_date": d,
        "vt_symbol": sym,
        "is_limit_up": True,
        "limit_up_count": streak,
        "is_one_word": one_word,
        "is_st": is_st,
        "board": board,
        "close_price": close,
        "change_pct": pct,
        "source": "daily_rebuild",
    }


def _pool(d: date, sym: str, name: str, count: int, *, first: str | None = None,
          last: str | None = None, amount: float | None = None,
          breaks: int | None = None, days: int | None = None,
          boards: int | None = None, industry: str | None = None,
          close: float | None = None, pct: float | None = None) -> dict:
    return {
        "trade_date": d,
        "pool_type": "zt",
        "vt_symbol": sym,
        "name": name,
        "close_price": close,
        "change_pct": pct,
        "limit_amount": amount,
        "first_limit_time": first,
        "last_limit_time": last,
        "break_count": breaks,
        "limit_stat_days": days,
        "limit_stat_boards": boards,
        "limit_up_count": count,
        "industry": industry,
        "source": "test",
    }


def _stock(sym: str, name: str) -> dict:
    code, exchange = sym.split(".")
    return {
        "vt_symbol": sym,
        "symbol": code,
        "exchange": exchange,
        "name": name,
        "source": "test",
    }


def _sector(sid: str, name: str, stype: str) -> dict:
    return {"id": sid, "name": name, "type": stype, "source": "test"}


def _membership(sym: str, sid: str, name: str, stype: str) -> dict:
    return {
        "vt_symbol": sym,
        "sector_id": sid,
        "sector_name": name,
        "sector_type": stype,
        "source": "test",
    }


def _seed_daily(session) -> None:
    """剧本的 D2/D3 两日 stock_limit_up_daily 行。"""
    rows = [
        # D2(前一交易日)
        _daily(D2, S1, 1),
        _daily(D2, S2, 1),
        _daily(D2, S3, 1, is_st=True),
        _daily(D2, S4, 2),
        _daily(D2, S5, 3),
        _daily(D2, S6, 4),
        _daily(D2, S7, 4),
        # D3(当日): S2/S5/S7 断板
        _daily(D3, S1, 2, close=11.0, pct=10.0),
        _daily(D3, S3, 2, is_st=True, close=5.0, pct=5.0),
        _daily(D3, S4, 3, close=12.1, pct=10.0, one_word=True),
        _daily(D3, S6, 5, close=14.64, pct=10.0, board="main"),
        _daily(D3, S8, 1, close=10.0, pct=10.0, board="cyb"),
        _daily(D3, S9, 1, close=20.0, pct=20.0, board="cyb"),
        _daily(D3, S10, 1, close=8.0, pct=10.0),
    ]
    session.execute(insert(schema.stock_limit_up_daily), rows)


def _seed_pool(session) -> None:
    """D3 涨停池归档行(盘口字段全); S3 名称含 ST。"""
    rows = [
        _pool(D3, S6, "六号股份", 5, first="09:35:00", last="09:35:00",
              amount=6.0e8, breaks=0, days=13, boards=9, industry="汽车整车",
              close=14.64, pct=10.0),
        _pool(D3, S4, "四号食品", 3, first="09:40:00", last="10:01:00",
              amount=4.0e8, breaks=2, days=5, boards=3, industry="食品",
              close=12.1, pct=10.0),
        _pool(D3, S1, "一号家电", 2, first="09:45:00", last="09:45:00",
              amount=1.0e8, breaks=0, days=None, boards=None, industry="家电",
              close=11.0, pct=10.0),
        _pool(D3, S3, "ST三号", 2, first="10:00:00", last="10:00:00",
              amount=3.0e7, breaks=0, days=2, boards=2, industry="化工",
              close=5.0, pct=5.0),
        _pool(D3, S8, "八号科技", 1, first="09:31:00", last="09:31:00",
              amount=8.0e7, breaks=0, days=1, boards=1, industry="电子",
              close=10.0, pct=10.0),
        _pool(D3, S9, "九号智能", 1, first="09:25:00", last="09:25:00",
              amount=9.0e7, breaks=0, days=1, boards=1, industry="计算机",
              close=20.0, pct=20.0),
        _pool(D3, S10, "十号机械", 1, first=None, last=None,
              amount=None, breaks=None, days=None, boards=None,
              industry="机械", close=8.0, pct=10.0),
    ]
    session.execute(insert(schema.limit_up_pool_snapshots), rows)


def _seed_stocks(session) -> None:
    session.execute(insert(schema.stocks), [
        _stock(S1, "一号家电"),
        _stock(S3, "ST三号"),
        _stock(S4, "四号食品"),
        _stock(S6, "六号股份"),
        _stock(S8, "八号科技"),
        _stock(S9, "九号智能"),
        _stock(S10, "十号机械"),
    ])


def _seed_concepts(session) -> None:
    """S8 挂 4 个概念(截断前 3); S9 挂 1 概念 + 1 行业(行业不进 concepts)。"""
    session.execute(insert(schema.sectors), [
        _sector("BK0800", "人工智能", "concept"),
        _sector("BK0801", "新能源", "concept"),
        _sector("BK0802", "机器人", "concept"),
        _sector("BK0803", "芯片", "concept"),
        _sector("BK0900", "白酒", "industry"),
    ])
    session.execute(insert(schema.stock_sector_memberships), [
        _membership(S8, "BK0803", "芯片", "concept"),
        _membership(S8, "BK0800", "人工智能", "concept"),
        _membership(S8, "BK0802", "机器人", "concept"),
        _membership(S8, "BK0801", "新能源", "concept"),
        _membership(S9, "BK0900", "白酒", "industry"),
        _membership(S9, "BK0800", "人工智能", "concept"),
    ])


def _seed_all(session) -> None:
    _seed_daily(session)
    _seed_pool(session)
    _seed_stocks(session)
    _seed_concepts(session)


def _tiers_by_streak(result: dict) -> dict[int, dict]:
    return {tier["streak"]: tier for tier in result["tiers"]}


# ── pool_archive 模式 ────────────────────────────────────────────────────


def test_pool_archive_tiers_fields_and_ordering(fake_session):
    _seed_all(fake_session)

    result = build_ladder(fake_session, D3)

    assert result["trade_date"] == "2026-08-12"
    assert result["source"] == "pool_archive"
    # 档位 streak 降序, 空档(4板)不输出; ST(S3)默认排除
    assert [t["streak"] for t in result["tiers"]] == [5, 3, 2, 1]
    tiers = _tiers_by_streak(result)
    assert tiers[5]["count"] == tiers[3]["count"] == tiers[2]["count"] == 1
    assert tiers[1]["count"] == 3

    # 盘口字段取自归档行
    s6 = tiers[5]["stocks"][0]
    assert s6["vt_symbol"] == S6
    assert s6["name"] == "六号股份"
    assert s6["limit_up_count"] == 5
    assert s6["first_limit_time"] == "09:35:00"
    assert s6["last_limit_time"] == "09:35:00"
    assert s6["limit_amount"] == 6.0e8
    assert s6["break_count"] == 0
    assert s6["limit_stat_days"] == 13
    assert s6["limit_stat_boards"] == 9
    assert s6["industry"] == "汽车整车"
    assert s6["close_price"] == 14.64
    assert s6["change_pct"] == 10.0

    # 档内按 first_limit_time 升序, None 最后
    tier1_symbols = [s["vt_symbol"] for s in tiers[1]["stocks"]]
    assert tier1_symbols == [S9, S8, S10]
    assert tiers[1]["stocks"][-1]["first_limit_time"] is None


def test_pool_archive_is_reverse_three_states(fake_session):
    """反标三态: 13/9 连板5 → True; 5/3 连板3 → False; 统计缺失 → None。"""
    _seed_all(fake_session)

    tiers = _tiers_by_streak(build_ladder(fake_session, D3))

    assert tiers[5]["stocks"][0]["is_reverse"] is True
    assert tiers[3]["stocks"][0]["is_reverse"] is False
    assert tiers[2]["stocks"][0]["is_reverse"] is None


def test_pool_archive_today_promotion_exact(fake_session):
    """今日 X进Y 晋级率(base=昨日 N-1 板非ST家数, promoted=其中今日 N 板家数)。"""
    _seed_all(fake_session)

    tiers = _tiers_by_streak(build_ladder(fake_session, D3))

    # 5板档(4进5): 昨日4板 {S6,S7}, 今日5板仅 S6
    assert tiers[5]["today_promotion"] == {"base": 2, "promoted": 1, "rate": 0.5}
    # 3板档(2进3): 昨日2板 {S4}, 今日3板 S4
    assert tiers[3]["today_promotion"] == {"base": 1, "promoted": 1, "rate": 1.0}
    # 2板档(1进2): 昨日首板非ST {S1,S2}(S3 是 ST 不计), 今日2板非ST仅 S1
    assert tiers[2]["today_promotion"] == {"base": 2, "promoted": 1, "rate": 0.5}
    # 1板档 = 1进2: base=昨日首板数, promoted=今日2板数
    assert tiers[1]["today_promotion"] == {"base": 2, "promoted": 1, "rate": 0.5}


def test_include_st_flag(fake_session):
    """默认排除 ST; include_st=True 纳入梯队且晋级率分母分子同口径含 ST。"""
    _seed_all(fake_session)

    default = _tiers_by_streak(build_ladder(fake_session, D3))
    assert S3 not in [s["vt_symbol"] for t in default.values() for s in t["stocks"]]

    with_st = _tiers_by_streak(build_ladder(fake_session, D3, include_st=True))
    # S3 进入 2板档, 档内仍按首封时间排序
    assert [s["vt_symbol"] for s in with_st[2]["stocks"]] == [S1, S3]
    assert with_st[2]["stocks"][1]["is_st"] is True
    # 2板档(1进2): base 昨日首板含ST {S1,S2,S3}=3, promoted 今日2板含ST {S1,S3}=2
    assert with_st[2]["today_promotion"] == {
        "base": 3, "promoted": 2, "rate": round(2 / 3, 3),
    }


# ── concepts ─────────────────────────────────────────────────────────────


def test_concepts_capped_sorted_and_absent(fake_session):
    _seed_all(fake_session)

    tiers = _tiers_by_streak(build_ladder(fake_session, D3))
    stocks = {s["vt_symbol"]: s for t in tiers.values() for s in t["stocks"]}

    # 4 个概念按名称排序取前 3(确定性); 行业板块不出现
    assert stocks[S8]["concepts"] == ["人工智能", "新能源", "机器人"]
    assert stocks[S9]["concepts"] == ["人工智能"]
    # 无概念的股票给空列表而不是缺键
    assert stocks[S1]["concepts"] == []


# ── daily_rebuild 降级 ───────────────────────────────────────────────────


def test_daily_rebuild_fallback_when_archive_empty(fake_session):
    """归档表无当日行 → 降级 stock_limit_up_daily, 盘口字段 None, 结构不变。"""
    _seed_daily(fake_session)
    _seed_stocks(fake_session)
    _seed_concepts(fake_session)

    result = build_ladder(fake_session, D3)

    assert result["source"] == "daily_rebuild"
    assert [t["streak"] for t in result["tiers"]] == [5, 3, 2, 1]
    tiers = _tiers_by_streak(result)

    s6 = tiers[5]["stocks"][0]
    # 盘口字段 None
    assert s6["first_limit_time"] is None
    assert s6["last_limit_time"] is None
    assert s6["limit_amount"] is None
    assert s6["break_count"] is None
    assert s6["limit_stat_days"] is None
    assert s6["limit_stat_boards"] is None
    assert s6["is_reverse"] is None
    assert s6["industry"] is None
    # 但仍提供日线字段 + stocks 表名称
    assert s6["name"] == "六号股份"
    assert s6["limit_up_count"] == 5
    assert s6["close_price"] == 14.64
    assert s6["change_pct"] == 10.0
    assert s6["is_one_word"] is False
    assert s6["is_st"] is False
    assert s6["board"] == "main"

    s4 = tiers[3]["stocks"][0]
    assert s4["is_one_word"] is True

    # first_limit_time 全 None → 档内按 vt_symbol 确定性排序
    assert [s["vt_symbol"] for s in tiers[1]["stocks"]] == [S8, S9, S10]
    # concepts 在降级模式同样提供
    s8 = tiers[1]["stocks"][0]
    assert s8["concepts"] == ["人工智能", "新能源", "机器人"]
    # 晋级率不受影响(同一张表)
    assert tiers[5]["today_promotion"] == {"base": 2, "promoted": 1, "rate": 0.5}


# ── 容错 ─────────────────────────────────────────────────────────────────


def test_promotion_none_when_prev_day_missing(fake_session):
    """首个重建日(无前一日数据): today_promotion=None 不炸, 梯队正常。"""
    rows = [
        _daily(D3, S1, 2),
        _daily(D3, S8, 1),
    ]
    fake_session.execute(insert(schema.stock_limit_up_daily), rows)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D3, S1, "一号家电", 2, first="09:45:00"),
        _pool(D3, S8, "八号科技", 1, first="09:31:00"),
    ])

    result = build_ladder(fake_session, D3)

    assert result["source"] == "pool_archive"
    tiers = _tiers_by_streak(result)
    assert tiers[2]["today_promotion"] is None
    assert tiers[1]["today_promotion"] is None
    assert tiers[2]["count"] == tiers[1]["count"] == 1


def test_promotion_none_when_today_not_rebuilt(fake_session):
    """pool_archive 模式但当日尚未 rebuild: today_promotion=None 容错。"""
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D2, S1, 1),
        _daily(D2, S6, 4),
    ])
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        _pool(D3, S6, "六号股份", 5, first="09:35:00"),
        _pool(D3, S1, "一号家电", 2, first="09:45:00"),
    ])

    result = build_ladder(fake_session, D3)

    assert result["source"] == "pool_archive"
    tiers = _tiers_by_streak(result)
    assert tiers[5]["today_promotion"] is None
    assert tiers[2]["today_promotion"] is None


def test_empty_ladder_when_no_data(fake_session):
    """当日无任何涨停数据 → 空梯队不报错。"""
    result = build_ladder(fake_session, D3)

    assert result == {
        "trade_date": "2026-08-12",
        "source": "daily_rebuild",
        "tiers": [],
    }
