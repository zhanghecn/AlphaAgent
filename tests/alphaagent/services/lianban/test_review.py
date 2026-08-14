"""复盘聚合 build_review: final/rebuild 双模式 / 统计口径对账 / 各块独立降级。

sqlite 内存库真实落库验证(见 conftest.fake_session), 不碰网络。

数据剧本(复盘日 D2=2026-08-13 周四, 前一日 D1=2026-08-12 周三):
- 日线 bars: AAA/BBB/CCC/FILL 铺 64 个历史交易日 + D2(验证 63 日新高新低
  窗口裁剪: 窗口外首日 AAA high=99 / BBB low=0.5, 正确窗口下不影响);
  DDD/HHH/指数只有 D2 行。
- D1 涨停(非ST): AAA 二板 / BBB 首板 / DDD 首板; STX(ST) 首板。
- D2 涨停(非ST): AAA 三板 / CCC 首板 / DDD 二板; BBB 摸板未封(touched)。
- D2 归档: zt={AAA,CCC,DDD,EEE,SST(ST)} zbgc={BBB,FFF} dtgc={GGG}
  zt_previous={AAA,BBB,DDD,HHH}; D1 归档 zt/zbgc/dtgc 各 3/1/1 行。

非 ST 口径精确值(final 模式):
- limit_up=4(SST 被 ST 过滤), prev=3; lianban=2(AAA,DDD), prev=1(AAA);
  max_streak=3, prev=2; broken=2, prev=1; limit_down=1, prev=1;
  seal_rate=4/6=0.667, prev=3/4=0.75。
- 昨涨停今表现: zt_previous 四股 join 当日 bars [5.0,-3.0,10.0,100.0]
  → mean=28.0 / median=7.5 / rise_ratio=0.75(归档路径; rebuild 路径无 HHH
  → 4.0/5.0/0.667)。
- 新高新低: AAA 收盘 11 ≥ 前63日最高 10 → 新高 1; BBB 收盘 8 ≤ 前63日最低 9
  → 新低 1(指数 000001.SSE 收盘 9999 被排除, DDD/HHH 无历史不进分母)。
- total_amount=1e9+2e9+3e9+4e9=1e10(指数 5e9 被排除, DDD/HHH turnover None)。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import insert

from alphaagent.server.db import schema
from alphaagent.server.services.lianban.review import ReviewNotFound, build_review

D0 = date(2026, 8, 11)  # 周二(融资 T-2)
D1 = date(2026, 8, 12)  # 周三(前一交易日)
D2 = date(2026, 8, 13)  # 周四(复盘日)

AAA, BBB, CCC, DDD = "600101.SSE", "600102.SSE", "600103.SSE", "600104.SSE"
EEE, FFF, GGG, HHH = "600105.SSE", "600106.SSE", "600107.SSE", "600110.SSE"
SST, STX, ZZZ, FILL = "600111.SSE", "600109.SSE", "600108.SSE", "600000.SSE"

# 64 个历史交易日(D1-63 .. D1): 窗口=最近 63 日, 最早一日(D1-63)在窗口外。
HIST_DAYS = [D1 - timedelta(days=i) for i in range(63, -1, -1)]
OUT_OF_WINDOW = HIST_DAYS[0]

SENT_D2 = {
    "date": "2026-08-13",
    "phase": "ebb",
    "phase_label": "退潮",
    "score": 40.0,
    "score_change": -12.5,
    "rise_count": 1100,
    "fall_count": 4091,
    "flat_count": 100,
    "total_stocks": 5291,
    "limit_up_count": 59,
    "temporary": False,
}


# ── 数据构造辅助 ─────────────────────────────────────────────────────────


def _stock(sym: str, name: str, industry: str | None = None) -> dict:
    code, exchange = sym.split(".")
    return {
        "vt_symbol": sym,
        "symbol": code,
        "exchange": exchange,
        "name": name,
        "industry": industry,
        "source": "test",
    }


def _bar(sym: str, d: date, *, open_: float = 9.5, close: float = 9.5,
         high: float = 10.0, low: float = 9.0, change: float | None = None,
         turnover: float | None = None) -> dict:
    return {
        "vt_symbol": sym,
        "trade_date": d,
        "open_price": open_,
        "close_price": close,
        "high_price": high,
        "low_price": low,
        "change_pct": change,
        "turnover": turnover,
        "source": "test",
    }


def _daily(d: date, sym: str, streak: int, *, is_st: bool = False,
           is_up: bool = True, touched: bool = False) -> dict:
    return {
        "trade_date": d,
        "vt_symbol": sym,
        "is_limit_up": is_up,
        "limit_up_count": streak,
        "is_one_word": False,
        "is_st": is_st,
        "board": "main",
        "close_price": 10.0,
        "change_pct": 10.0,
        "touched_limit": touched,
        "source": "daily_rebuild",
    }


def _pool(d: date, sym: str, name: str, count: int | None, *, pool: str = "zt",
          first: str | None = None, breaks: int | None = None,
          days: int | None = None, boards: int | None = None,
          industry: str | None = None) -> dict:
    return {
        "trade_date": d,
        "pool_type": pool,
        "vt_symbol": sym,
        "name": name,
        "first_limit_time": first,
        "break_count": breaks,
        "limit_stat_days": days,
        "limit_stat_boards": boards,
        "limit_up_count": count,
        "industry": industry,
        "source": "test",
    }


# ── 分块 seed ────────────────────────────────────────────────────────────


def _seed_stocks(session) -> None:
    rows = [
        _stock(AAA, "甲股份", "医药"), _stock(BBB, "乙股份", "医药"),
        _stock(CCC, "丙股份", "医药"), _stock(DDD, "丁股份", "科技"),
        _stock(EEE, "戊股份"), _stock(FFF, "己股份", "科技"),
        _stock(GGG, "庚股份", "科技"), _stock(HHH, "辛股份", "科技"),
        _stock(SST, "ST长城", "医药"), _stock(STX, "ST翔宇"),
        _stock(ZZZ, "壬股份", "科技"), _stock(FILL, "浦发银行"),
        _stock("000001.SSE", "上证指数"), _stock("399001.SZSE", "深证成指"),
        _stock("399006.SZSE", "创业板指"), _stock("000688.SSE", "科创50"),
    ]
    session.execute(insert(schema.stocks), rows)


def _seed_bars(session) -> None:
    rows = []
    for d in HIST_DAYS:
        for sym in (AAA, BBB, CCC, FILL):
            # 窗口外首日极值: 窗口裁剪正确则不影响 63 日新高新低
            high = 99.0 if d == OUT_OF_WINDOW and sym == AAA else 10.0
            low = 0.5 if d == OUT_OF_WINDOW and sym == BBB else 9.0
            rows.append(_bar(sym, d, high=high, low=low))
    # D2 当日: AAA 新高 / BBB 新低 / CCC 平 / FILL 平
    rows += [
        _bar(AAA, D2, open_=10.5, close=11.0, high=11.0, low=10.5,
             change=5.0, turnover=1e9),
        _bar(BBB, D2, open_=9.4, close=8.0, high=9.4, low=8.0,
             change=-3.0, turnover=2e9),
        _bar(CCC, D2, change=1.0, turnover=3e9),
        _bar(FILL, D2, change=0.1, turnover=4e9),
        _bar(DDD, D2, open_=9.0, close=9.9, high=9.9, low=8.9, change=10.0),
        _bar(HHH, D2, open_=18.0, close=20.0, high=20.0, low=18.0, change=100.0),
    ]
    # 六指数只落 4 个(上证50/北证50 缺失 → null 容错);
    # 000001.SSE 收盘 9999 创"新高", 验证指数被排除出新高新低统计。
    # 创业板指走 change_pct 列缺失 → close/prev_close 回补计算路径:
    # 2046/2000-1 = +2.3%。
    rows += [
        _bar("000001.SSE", D2, open_=9998.0, close=9999.0, high=9999.0,
             low=9998.0, change=-0.5, turnover=5e9),
        _bar("399001.SZSE", D2, open_=8888.0, close=8888.0, high=8888.0,
             low=8888.0, change=-1.2),
        _bar("399006.SZSE", D1, open_=2000.0, close=2000.0, high=2000.0,
             low=2000.0),
        _bar("399006.SZSE", D2, open_=2046.0, close=2046.0, high=2046.0,
             low=2046.0),
        _bar("000688.SSE", D2, open_=999.0, close=999.0, high=999.0,
             low=999.0, change=0.7),
    ]
    session.execute(insert(schema.stock_daily_bars), rows)


def _seed_daily(session) -> None:
    rows = [
        _daily(D1, AAA, 2), _daily(D1, BBB, 1), _daily(D1, DDD, 1),
        _daily(D1, STX, 1, is_st=True),
        _daily(D2, AAA, 3), _daily(D2, CCC, 1), _daily(D2, DDD, 2),
        _daily(D2, BBB, 0, is_up=False, touched=True),
    ]
    session.execute(insert(schema.stock_limit_up_daily), rows)


def _seed_archive(session) -> None:
    rows = [
        # D1: zt 3 行(非ST), zbgc/dtgc 各 1 行
        _pool(D1, AAA, "甲股份", 2, first="09:30:00", industry="医药"),
        _pool(D1, BBB, "乙股份", 1, first="09:40:00", industry="医药"),
        _pool(D1, DDD, "丁股份", 1, first="09:50:00", industry="科技"),
        _pool(D1, ZZZ, "壬股份", None, pool="zbgc", first="10:00:00",
              breaks=1, industry="科技"),
        _pool(D1, GGG, "庚股份", None, pool="dtgc"),
        # D2 zt: 甲3板/丙首板/丁2板(5日3板→反)/戊首板(无行业)/ST长城(ST, 过滤)
        _pool(D2, AAA, "甲股份", 3, first="09:30:00", days=3, boards=3,
              industry="医药"),
        _pool(D2, CCC, "丙股份", 1, first="10:00:00", days=1, boards=1,
              industry="医药"),
        _pool(D2, DDD, "丁股份", 2, first="09:45:00", days=5, boards=3,
              industry="科技"),
        _pool(D2, EEE, "戊股份", 1, first="11:00:00"),
        _pool(D2, SST, "ST长城", 1, first="09:31:00", industry="医药"),
        # D2 zbgc/dtgc
        _pool(D2, BBB, "乙股份", None, pool="zbgc", first="09:35:00",
              breaks=2, industry="医药"),
        _pool(D2, FFF, "己股份", None, pool="zbgc", first="14:00:00",
              breaks=1, industry="科技"),
        _pool(D2, GGG, "庚股份", None, pool="dtgc"),
        # D2 zt_previous = 昨日涨停名单 + 一只无归档的 HHH(区分归档/重建路径)
        _pool(D2, AAA, "甲股份", None, pool="zt_previous"),
        _pool(D2, BBB, "乙股份", None, pool="zt_previous"),
        _pool(D2, DDD, "丁股份", None, pool="zt_previous"),
        _pool(D2, HHH, "辛股份", None, pool="zt_previous"),
    ]
    session.execute(insert(schema.limit_up_pool_snapshots), rows)


def _seed_sentiment(session) -> None:
    session.execute(insert(schema.mainline_sentiment_history), [{
        "id": 1,
        "anchor_date": D2,
        "history_span_days": 2,
        "points": [
            {"date": "2026-08-12", "phase": "repair", "phase_label": "修复",
             "score": 52.5, "rise_count": 3000, "fall_count": 2000},
            SENT_D2,
        ],
        "symbol_state": {},
    }])


def _seed_margin(session) -> None:
    session.execute(insert(schema.market_margin_balance), [
        {"trade_date": D1, "margin_balance": 2.65e12, "source": "test"},
        {"trade_date": D0, "margin_balance": 2.64e12, "source": "test"},
    ])


def _seed_flows(session) -> None:
    session.execute(insert(schema.sectors), [
        {"id": "BK001", "name": "医药生物", "type": "industry", "source": "test"},
        {"id": "BK002", "name": "芯片概念", "type": "concept", "source": "test"},
    ])
    session.execute(insert(schema.sector_fund_flows), [
        {"sector_id": "BK001", "trade_date": "2026-08-13", "period": "即时",
         "main_net_inflow": 9e8, "source": "test", "raw": {"今日涨跌幅": 1.5}},
        {"sector_id": "BK002", "trade_date": "2026-08-13", "period": "即时",
         "main_net_inflow": 5e8, "source": "test", "raw": {"今日涨跌幅": -0.6}},
        # 干扰行: 5日周期 / 前一交易日, 均应被过滤
        {"sector_id": "BK002", "trade_date": "2026-08-13", "period": "5日",
         "main_net_inflow": 99e9, "source": "test", "raw": {}},
        {"sector_id": "BK001", "trade_date": "2026-08-12", "period": "即时",
         "main_net_inflow": 88e8, "source": "test", "raw": {}},
    ])


def _seed_hot(session) -> None:
    session.execute(insert(schema.stock_hot_ranks), [
        {"vt_symbol": DDD, "rank_time": "2026-08-13T15:00:00+00:00",
         "rank": 1, "keywords": ["芯片"], "source": "test"},
        {"vt_symbol": AAA, "rank_time": "2026-08-13T15:00:00+00:00",
         "rank": 2, "keywords": [], "source": "test"},
        # 前一日批次: 复盘 D1 时应 as-of 命中这一批
        {"vt_symbol": ZZZ, "rank_time": "2026-08-12T15:00:00+00:00",
         "rank": 1, "keywords": [], "source": "test"},
        # 未来批次: 复盘 D2 时绝不可见(as-of 防时间穿越)
        {"vt_symbol": HHH, "rank_time": "2026-08-14T09:00:00+00:00",
         "rank": 1, "keywords": [], "source": "test"},
    ])


def _seed_all(session) -> None:
    _seed_stocks(session)
    _seed_bars(session)
    _seed_daily(session)
    _seed_archive(session)
    _seed_sentiment(session)
    _seed_margin(session)
    _seed_flows(session)
    _seed_hot(session)


# ── final 模式全量对账 ───────────────────────────────────────────────────


def test_final_mode_full_payload_exact(fake_session):
    _seed_all(fake_session)

    result = build_review(fake_session, D2)

    # 骨架键
    assert set(result) == {
        "trade_date", "mode", "weekday", "indices", "stats", "sentiment",
        "ladder", "promotion", "relay", "broken_list", "themes",
        "theme_strength", "hot_leaders", "data_quality",
    }
    assert result["trade_date"] == "2026-08-13"
    assert result["mode"] == "final"
    assert result["weekday"] == "周四"

    # 六指数: 4 有值 + 上证50/北证50 None 容错
    indices = {i["key"]: i for i in result["indices"]}
    assert [i["key"] for i in result["indices"]] == [
        "sh", "sz", "cyb", "kc50", "sz50", "bz50",
    ]
    assert indices["sh"] == {
        "key": "sh", "name": "上证", "vt_symbol": "000001.SSE",
        "change_pct": -0.5,
    }
    assert indices["sz"]["change_pct"] == -1.2
    assert indices["cyb"]["change_pct"] == 2.3  # 列缺失, close/prev_close 回补
    assert indices["kc50"]["change_pct"] == 0.7
    assert indices["sz50"]["change_pct"] is None
    assert indices["bz50"]["change_pct"] is None

    # stats 全键精确对账
    stats = result["stats"]
    assert set(stats) == {
        "limit_up", "limit_up_prev", "lianban", "lianban_prev",
        "max_streak", "max_streak_prev", "limit_down", "limit_down_prev",
        "seal_rate", "seal_rate_prev", "broken", "broken_prev",
        "prev_lu_avg_change", "prev_lu_median_change", "prev_lu_rise_ratio",
        "sentiment_phase", "sentiment_score", "rise_count", "fall_count",
        "new_high_63", "new_low_63", "total_amount",
        "margin_balance", "margin_change", "margin_date",
    }
    assert stats["limit_up"] == 4  # SST(ST) 被过滤
    assert stats["limit_up_prev"] == 3
    assert stats["lianban"] == 2
    assert stats["lianban_prev"] == 1
    assert stats["max_streak"] == 3
    assert stats["max_streak_prev"] == 2
    assert stats["limit_down"] == 1
    assert stats["limit_down_prev"] == 1
    assert stats["broken"] == 2
    assert stats["broken_prev"] == 1
    assert stats["seal_rate"] == round(4 / 6, 3) == 0.667
    assert stats["seal_rate_prev"] == 0.75
    # 昨涨停今表现(归档路径含 HHH): [5.0,-3.0,10.0,100.0]
    assert stats["prev_lu_avg_change"] == 28.0
    assert stats["prev_lu_median_change"] == 7.5
    assert stats["prev_lu_rise_ratio"] == 0.75
    assert stats["sentiment_phase"] == "退潮期"
    assert stats["sentiment_score"] == 40.0
    assert stats["rise_count"] == 1100
    assert stats["fall_count"] == 4091
    assert stats["new_high_63"] == 1
    assert stats["new_low_63"] == 1
    assert stats["total_amount"] == 1e10
    assert stats["margin_balance"] == 2.65e12
    assert stats["margin_change"] == 1e10
    assert stats["margin_date"] == "2026-08-12"

    # sentiment 原文 + ladder/promotion 直挂
    assert result["sentiment"] == SENT_D2
    assert result["ladder"]["source"] == "pool_archive"
    assert [t["streak"] for t in result["ladder"]["tiers"]] == [3, 2, 1]
    assert result["promotion"]["first_board_mean"] == 0.5

    # relay 梯队接力: 昨日板位降序, promoted/broken 三态
    relay = result["relay"]
    assert [t["prev_streak"] for t in relay["tiers"]] == [2, 1]
    tier2 = relay["tiers"][0]["stocks"]
    assert tier2 == [{
        "vt_symbol": AAA, "name": "甲股份", "today_change_pct": 5.0,
        "status": "promoted", "today_streak": 3,
    }]
    tier1 = relay["tiers"][1]["stocks"]
    # 档内按今日涨幅降序: DDD(+10, promoted) 在前, BBB(-3, broken) 在后
    assert [(s["vt_symbol"], s["status"], s["today_streak"]) for s in tier1] == [
        (DDD, "promoted", 2), (BBB, "broken", None),
    ]
    assert relay["first_board"] == {
        "base": 2, "promoted": 1, "rate": 0.5, "mean": 0.5,
    }

    # broken_list: zbgc 按首封时间升序
    assert result["broken_list"] == [
        {"vt_symbol": BBB, "name": "乙股份", "first_limit_time": "09:35:00",
         "break_count": 2, "industry": "医药"},
        {"vt_symbol": FFF, "name": "己股份", "first_limit_time": "14:00:00",
         "break_count": 1, "industry": "科技"},
    ]

    # themes: count 降序(同数按名), 龙头=最高板, 档内首封升序; ST 不进组
    themes = result["themes"]
    assert [t["name"] for t in themes] == ["医药", "其他", "科技"]
    med = themes[0]
    assert med["count"] == 2
    assert med["leader"] == {"vt_symbol": AAA, "name": "甲股份", "limit_up_count": 3}
    assert [(s["vt_symbol"], s["first_limit_time"], s["is_reverse"])
            for s in med["stocks"]] == [
        (AAA, "09:30:00", False), (CCC, "10:00:00", False),
    ]
    assert themes[1]["leader"]["vt_symbol"] == EEE
    tech = themes[2]
    assert tech["leader"] == {"vt_symbol": DDD, "name": "丁股份", "limit_up_count": 2}
    assert tech["stocks"][0]["is_reverse"] is True  # 5日3板 > 当前2板

    # theme_strength: 当日"即时"主力净额降序, 干扰行(5日/昨日)被过滤
    assert result["theme_strength"] == [
        {"name": "医药生物", "change_pct": 1.5, "main_net_inflow": 9e8},
        {"name": "芯片概念", "change_pct": -0.6, "main_net_inflow": 5e8},
    ]

    # hot_leaders: as-of 复盘日的最新批次 join 当日连板/涨幅;
    # 昨日批次 ZZZ 与未来批次 HHH 都不出现
    assert result["hot_leaders"] == {
        "as_of": "2026-08-13T15:00:00+00:00",
        "items": [
            {"rank": 1, "vt_symbol": DDD, "name": "丁股份", "hot_score": None,
             "limit_up_count": 2, "change_pct": 10.0, "keywords": ["芯片"]},
            {"rank": 2, "vt_symbol": AAA, "name": "甲股份", "hot_score": None,
             "limit_up_count": 3, "change_pct": 5.0, "keywords": []},
        ],
    }

    # data_quality
    assert result["data_quality"] == {
        "pool_archived": True,
        "live": False,
        "rebuild_date": "2026-08-13",
        "missing": ["indices:sz50", "indices:bz50"],
    }


# ── rebuild 模式降级 ─────────────────────────────────────────────────────


def test_rebuild_mode_degrades_cleanly(fake_session):
    """无归档 → rebuild: 统计走 stock_limit_up_daily, 盘口块 None/空 + missing。"""
    _seed_stocks(fake_session)
    _seed_bars(fake_session)
    _seed_daily(fake_session)
    _seed_sentiment(fake_session)
    _seed_margin(fake_session)
    _seed_flows(fake_session)
    _seed_hot(fake_session)

    result = build_review(fake_session, D2)

    assert result["mode"] == "rebuild"
    assert result["ladder"]["source"] == "daily_rebuild"

    stats = result["stats"]
    assert stats["limit_up"] == 3  # AAA/CCC/DDD(STX 是 ST)
    assert stats["limit_up_prev"] == 3
    assert stats["lianban"] == 2
    assert stats["lianban_prev"] == 1
    assert stats["max_streak"] == 3
    assert stats["max_streak_prev"] == 2
    # 归档专属口径 rebuild 无数据 → None 不炸
    assert stats["limit_down"] is None
    assert stats["limit_down_prev"] is None
    assert stats["broken"] is None
    assert stats["broken_prev"] is None
    assert stats["seal_rate"] is None
    assert stats["seal_rate_prev"] is None
    # 昨涨停今表现(rebuild 路径, 无 HHH): [5.0,-3.0,10.0]
    assert stats["prev_lu_avg_change"] == 4.0
    assert stats["prev_lu_median_change"] == 5.0
    assert stats["prev_lu_rise_ratio"] == round(2 / 3, 3)

    # broken_list 无归档源 → 空 + missing 标注
    assert result["broken_list"] == []
    assert "broken_list" in result["data_quality"]["missing"]
    assert result["data_quality"]["pool_archived"] is False

    # themes: 行业从 stocks 表补(归档行 industry 不可用)
    themes = {t["name"]: t for t in result["themes"]}
    assert set(themes) == {"医药", "科技"}
    assert themes["医药"]["count"] == 2
    assert themes["医药"]["leader"] == {
        "vt_symbol": AAA, "name": "甲股份", "limit_up_count": 3,
    }
    assert themes["科技"]["leader"]["vt_symbol"] == DDD
    # rebuild 无盘口字段: 首封 None, 反标 None
    assert themes["医药"]["stocks"][0]["first_limit_time"] is None
    assert themes["医药"]["stocks"][0]["is_reverse"] is None

    # relay 仍可用(全走重建表): BBB touched 未封 → broken
    relay = result["relay"]
    assert [t["prev_streak"] for t in relay["tiers"]] == [2, 1]
    statuses = {
        s["vt_symbol"]: s["status"]
        for t in relay["tiers"] for s in t["stocks"]
    }
    assert statuses == {AAA: "promoted", DDD: "promoted", BBB: "broken"}


# ── 降级路径 ─────────────────────────────────────────────────────────────


def test_final_mode_without_daily_rebuild(fake_session):
    """final 但当日未重建: 今日 streak 从归档 zt 回补, rebuild_date=None。"""
    _seed_stocks(fake_session)
    _seed_bars(fake_session)
    _seed_archive(fake_session)
    _seed_hot(fake_session)

    result = build_review(fake_session, D2)

    assert result["mode"] == "final"
    assert result["stats"]["limit_up"] == 4
    # 无重建: ladder 晋级率 None, relay 无昨日板位(重建表空) → 空档
    assert result["ladder"]["tiers"][0]["today_promotion"] is None
    assert result["relay"]["tiers"] == []
    assert result["relay"]["first_board"] == {
        "base": 0, "promoted": 0, "rate": None, "mean": None,
    }
    # hot_leaders 的连板数从归档 zt 回补
    leaders = {h["vt_symbol"]: h for h in result["hot_leaders"]["items"]}
    assert result["hot_leaders"]["as_of"] == "2026-08-13T15:00:00+00:00"
    assert leaders[DDD]["limit_up_count"] == 2
    assert leaders[AAA]["limit_up_count"] == 3
    # prev 统计仍可从归档前一日取
    assert result["stats"]["limit_up_prev"] == 3
    assert result["stats"]["seal_rate_prev"] == 0.75

    quality = result["data_quality"]
    assert quality["rebuild_date"] is None
    # 未 seed sentiment/margin/flows → missing 标注, 块本身 None/空不炸
    assert result["sentiment"] is None
    assert result["theme_strength"] == []
    assert result["stats"]["margin_balance"] is None
    assert set(quality["missing"]) == {
        "indices:sz50", "indices:bz50",
        "sentiment", "margin", "theme_strength",
    }


def test_optional_blocks_degrade_independently(fake_session):
    """final + 重建齐, 但 zt_previous/sentiment/margin/flows/hot 全缺。"""
    _seed_stocks(fake_session)
    _seed_bars(fake_session)
    _seed_daily(fake_session)
    # 归档只留 zt/zbgc/dtgc(无 zt_previous → prev_lu 回落重建路径)
    fake_session.execute(insert(schema.limit_up_pool_snapshots), [
        row for row in [
            _pool(D1, AAA, "甲股份", 2), _pool(D1, BBB, "乙股份", 1),
            _pool(D1, DDD, "丁股份", 1),
            _pool(D2, AAA, "甲股份", 3), _pool(D2, CCC, "丙股份", 1),
            _pool(D2, DDD, "丁股份", 2),
        ]
    ])

    result = build_review(fake_session, D2)

    assert result["mode"] == "final"
    # prev_lu 回落重建路径: [5.0,-3.0,10.0](无 HHH)
    assert result["stats"]["prev_lu_avg_change"] == 4.0
    assert result["stats"]["prev_lu_median_change"] == 5.0
    assert result["stats"]["prev_lu_rise_ratio"] == round(2 / 3, 3)

    assert result["sentiment"] is None
    assert result["stats"]["sentiment_phase"] is None
    assert result["stats"]["sentiment_score"] is None
    assert result["stats"]["rise_count"] is None
    assert result["stats"]["fall_count"] is None
    assert result["theme_strength"] == []
    assert result["hot_leaders"] == {"as_of": None, "items": []}
    assert result["stats"]["margin_balance"] is None
    assert result["stats"]["margin_change"] is None
    assert result["stats"]["margin_date"] is None

    missing = set(result["data_quality"]["missing"])
    assert {"sentiment", "margin", "theme_strength", "hot_leaders"} <= missing


# ── 无数据 ───────────────────────────────────────────────────────────────


def test_not_found_raises(fake_session):
    """完全无数据 / 只有别的日期 → ReviewNotFound(API 层转 404)。"""
    with pytest.raises(ReviewNotFound):
        build_review(fake_session, D2)

    _seed_stocks(fake_session)
    _seed_bars(fake_session)
    _seed_daily(fake_session)  # 只有 D1/D2 的重建行
    with pytest.raises(ReviewNotFound):
        build_review(fake_session, date(2026, 8, 14))


# ── hot_leaders as-of 口径 ───────────────────────────────────────────────


def test_hot_leaders_as_of_prevents_time_travel(fake_session):
    """复盘旧日期命中旧批次榜; 晚于复盘日的批次不可见(防时间穿越)。"""
    _seed_all(fake_session)

    d1 = build_review(fake_session, D1)

    # D1 复盘: as-of 截到 8-13 之前 → 命中 8-12 批次(ZZZ)
    assert d1["hot_leaders"]["as_of"] == "2026-08-12T15:00:00+00:00"
    assert [h["vt_symbol"] for h in d1["hot_leaders"]["items"]] == [ZZZ]
    # ZZZ 在 D1 无日线 bar、非涨停 → 价格/连板字段 None 容错
    assert d1["hot_leaders"]["items"][0]["change_pct"] is None
    assert d1["hot_leaders"]["items"][0]["limit_up_count"] is None

    # D2 复盘: 命中 8-13 批次, 8-14 未来批次不可见
    d2 = build_review(fake_session, D2)
    assert d2["hot_leaders"]["as_of"] == "2026-08-13T15:00:00+00:00"
    assert HHH not in {h["vt_symbol"] for h in d2["hot_leaders"]["items"]}


# ── 块级异常隔离 ─────────────────────────────────────────────────────────


def test_block_exception_isolated(fake_session, monkeypatch):
    """单块异常 → 该块空形 + missing "<block>:error", 整页仍返回。"""
    from alphaagent.server.services.lianban import review as review_mod

    _seed_all(fake_session)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    # 普通块(板块资金流)异常
    monkeypatch.setattr(review_mod, "_theme_strength", _boom)
    result = build_review(fake_session, D2)
    assert result["theme_strength"] == []
    assert "theme_strength:error" in result["data_quality"]["missing"]
    assert result["stats"]["limit_up"] == 4  # 其余块不受影响

    # 核心块 ladder/promotion 异常也降级: 块置 None, relay 给空形 first_board
    monkeypatch.setattr(review_mod, "build_ladder", _boom)
    monkeypatch.setattr(review_mod, "promotion_stats", _boom)
    result = build_review(fake_session, D2)
    assert result["ladder"] is None
    assert result["promotion"] is None
    assert result["relay"]["first_board"] == {
        "base": 0, "promoted": 0, "rate": None, "mean": None,
    }
    assert result["relay"]["tiers"]  # 梯队接力不依赖 promotion, 仍正常
    missing = result["data_quality"]["missing"]
    assert "ladder:error" in missing
    assert "promotion:error" in missing
    assert result["stats"]["seal_rate"] == 0.667


# ── live 模式(pool_rows_override, B4 盘中分流) ───────────────────────────


def _live_seed_without_archive(session) -> None:
    """盘中场景: 无当日归档, 当日重建未跑(重建表止于 D1)。"""
    _seed_stocks(session)
    _seed_bars(session)
    session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D1, AAA, 2), _daily(D1, BBB, 1), _daily(D1, DDD, 1),
        _daily(D1, STX, 1, is_st=True),
    ])
    _seed_sentiment(session)
    _seed_margin(session)
    _seed_flows(session)
    _seed_hot(session)


def _live_override() -> dict[str, list[dict]]:
    """实时五池映射后的"归档行形状"override(与 archive.pool_row 输出同构)。"""
    return {
        "zt": [
            _pool(D2, AAA, "甲股份", 3, first="09:30:00", days=3, boards=3,
                  industry="医药"),
            _pool(D2, CCC, "丙股份", 1, first="10:00:00", days=1, boards=1,
                  industry="医药"),
            _pool(D2, DDD, "丁股份", 2, first="09:45:00", days=5, boards=3,
                  industry="科技"),
            _pool(D2, EEE, "戊股份", 1, first="11:00:00"),
            _pool(D2, SST, "ST长城", 1, first="09:31:00", industry="医药"),
        ],
        "zbgc": [
            _pool(D2, BBB, "乙股份", None, pool="zbgc", first="09:35:00",
                  breaks=2, industry="医药"),
            _pool(D2, FFF, "己股份", None, pool="zbgc", first="14:00:00",
                  breaks=1, industry="科技"),
        ],
        "dtgc": [_pool(D2, GGG, "庚股份", None, pool="dtgc")],
        "zt_previous": [
            _pool(D2, AAA, "甲股份", None, pool="zt_previous"),
            _pool(D2, BBB, "乙股份", None, pool="zt_previous"),
            _pool(D2, DDD, "丁股份", None, pool="zt_previous"),
            _pool(D2, HHH, "辛股份", None, pool="zt_previous"),
        ],
        "strong": [],
    }


def test_live_mode_aggregates_override_like_final(fake_session):
    """override 注入走 final 同路径聚合, payload 标识 live/未归档。"""
    _live_seed_without_archive(fake_session)

    result = build_review(fake_session, D2, pool_rows_override=_live_override())

    assert result["mode"] == "live"
    assert result["data_quality"]["pool_archived"] is False
    assert result["data_quality"]["live"] is True
    stats = result["stats"]
    assert stats["limit_up"] == 4  # SST 被 ST 过滤, 与 final 同口径
    assert stats["broken"] == 2
    assert stats["seal_rate"] == 0.667
    assert stats["lianban"] == 2
    assert stats["max_streak"] == 3
    # prev 回落重建表 D1(归档无行): 3 家非 ST 涨停
    assert stats["limit_up_prev"] == 3
    # 昨涨停今表现走 override 的 zt_previous(含无归档 HHH → 归档路径口径)
    assert stats["prev_lu_avg_change"] == 28.0
    # ladder 直接吃 override 的 zt 行(当日归档未落库, 查表必空)
    assert result["ladder"]["source"] == "live_pool"
    assert result["ladder"]["tiers"][0]["streak"] == 3
    # 炸板/题材走 override 归档行
    assert [row["vt_symbol"] for row in result["broken_list"]] == [BBB, FFF]
    assert result["themes"]
    # 梯队接力: 昨日板位(重建 D1) join 实时 streak
    assert result["relay"]["tiers"]
    # promotion 锚定最近重建日 D1(当日重建未跑, 防窗口尾日污染样本)
    assert result["promotion"]["trade_date"] == D1.isoformat()
    assert result["data_quality"]["rebuild_date"] == D1.isoformat()


def test_live_mode_empty_zt_raises_not_found(fake_session):
    """开盘前实时池尚无涨停 → ReviewNotFound(同"当日无数据"语义)。"""
    _live_seed_without_archive(fake_session)
    with pytest.raises(ReviewNotFound):
        build_review(fake_session, D2, pool_rows_override={"zt": []})


def test_live_mode_mode_override(fake_session):
    """mode_override 指定汇报标识; data_quality.live 只认 "live"。"""
    _live_seed_without_archive(fake_session)
    result = build_review(
        fake_session,
        D2,
        pool_rows_override=_live_override(),
        mode_override="intraday",
    )
    assert result["mode"] == "intraday"
    assert result["data_quality"]["live"] is False
    # 聚合口径仍是归档行路径
    assert result["stats"]["limit_up"] == 4
