"""连板晋级率统计 promotion_stats: by_streak 历史频率 / 尾部样本日剔除 /
8+ 合并档 / 当日 1进2 / 分日均值 / 五日接力 / ST 口径 / lookback 裁剪 / 空数据容错。

sqlite 内存库真实落库验证(见 conftest.fake_session), 不碰网络。

主剧本(10 个交易日 D1=2026-08-03 .. D10=2026-08-14, 跨周末; 交易日历由
stock_daily_bars distinct 提供, 每日一根 bar):
- A(600101): D1..D9 九连板(streak 1..9), D10 断板无行
- B(600102): D1 首板→D2 无行(未晋级); D3 首板→D4 二板(晋级)→D5 无行
- C(600103, ST): D1 首板→D2 二板→D3 三板
- E(600105): D9 首板→D10 二板(晋级)
- F(600106): D9 首板→D10 无行(未晋级)
- G(600107): D10 首板(窗口最后一日, 验证尾部剔除: 不进任何分母)
- H(600108, ST): D9 首板→D10 二板(晋级, 仅 include_st 口径可见)

非 ST 默认口径精确值(trade_date=D10, lookback=250, 分母日=D1..D9):
- streak1: 样本 {A@D1,B@D1,B@D3,E@D9,F@D9}=5, 晋级 {A,B@D3,E}=3 → 0.6
- streak2: {A@D2,B@D4}=2, {A}=1 → 0.5
- streak3..7: 各 1 样本(A), 均晋级 → 1.0
- 8+: {A@D8(s8),A@D9(s9)}=2, 晋级 {A@D8→D9 s9}=1 → 0.5
- first_board_today: 前一日 D9 首板 {E,F}=2, 当日二板 {E}=1 → 0.5
- first_board_mean: D1 1/2=0.5, D3 1/1=1.0, D9 1/2=0.5 → 分日均值 0.667
  (总样本比例为 3/5=0.6, 二者不同, 证明口径是分日均值)
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import insert

from alphaagent.server.db import schema
from alphaagent.server.services.lianban.promotion import promotion_stats

DAYS = [
    date(2026, 8, 3),   # D1 周一
    date(2026, 8, 4),
    date(2026, 8, 5),
    date(2026, 8, 6),
    date(2026, 8, 7),   # D5 周五
    date(2026, 8, 10),  # D6 周一(跨周末, 次日取自交易日历而非日期加一)
    date(2026, 8, 11),
    date(2026, 8, 12),
    date(2026, 8, 13),
    date(2026, 8, 14),  # D10 周五
]
D1, D2, D3, D4, D5, D6, D7, D8, D9, D10 = DAYS

A = "600101.SSE"
B = "600102.SSE"
C = "600103.SSE"  # ST
E = "600105.SSE"
F = "600106.SSE"
G = "600107.SSE"
H = "600108.SSE"  # ST
BAR_SYM = "600000.SSE"  # 仅用于铺交易日历


def _daily(d: date, sym: str, streak: int, *, is_st: bool = False) -> dict:
    return {
        "trade_date": d,
        "vt_symbol": sym,
        "is_limit_up": True,
        "limit_up_count": streak,
        "is_one_word": False,
        "is_st": is_st,
        "board": "main",
        "close_price": 10.0,
        "change_pct": 10.0,
        "source": "daily_rebuild",
    }


def _bar(d: date) -> dict:
    return {
        "vt_symbol": BAR_SYM,
        "trade_date": d,
        "open_price": 10.0,
        "close_price": 10.0,
        "high_price": 10.0,
        "low_price": 10.0,
        "source": "test",
    }


def _seed_calendar(session, days: list[date] = DAYS) -> None:
    session.execute(insert(schema.stock_daily_bars), [_bar(d) for d in days])


def _seed_main(session) -> None:
    _seed_calendar(session)
    rows = [
        # A: D1..D9 九连板, D10 断板
        *(_daily(DAYS[i], A, i + 1) for i in range(9)),
        # B: D1 首板未晋级; D3 首板→D4 二板→D5 断板
        _daily(D1, B, 1),
        _daily(D3, B, 1),
        _daily(D4, B, 2),
        # C(ST): D1→D2→D3 三连板
        _daily(D1, C, 1, is_st=True),
        _daily(D2, C, 2, is_st=True),
        _daily(D3, C, 3, is_st=True),
        # E/F: D9 首板, E 晋级 D10 二板
        _daily(D9, E, 1),
        _daily(D10, E, 2),
        _daily(D9, F, 1),
        # G: D10 首板(尾部样本日)
        _daily(D10, G, 1),
        # H(ST): D9 首板→D10 二板
        _daily(D9, H, 1, is_st=True),
        _daily(D10, H, 2, is_st=True),
    ]
    session.execute(insert(schema.stock_limit_up_daily), rows)


def _buckets(result: dict) -> dict:
    return {b["streak"]: b for b in result["by_streak"]}


# ── by_streak 明日晋级率 ─────────────────────────────────────────────────


def test_by_streak_exact_and_tail_exclusion(fake_session):
    """精确值 + 「次日无行=未晋级」+ 窗口最后一日(D10)样本不进分母。"""
    _seed_main(fake_session)

    result = promotion_stats(fake_session, D10)

    assert result["trade_date"] == "2026-08-14"
    assert result["lookback_days"] == 250
    assert result["sample_start"] == "2026-08-03"
    assert result["sample_end"] == "2026-08-14"

    buckets = _buckets(result)
    # 档位齐全: 1..7 + "8+"
    assert list(buckets) == [1, 2, 3, 4, 5, 6, 7, "8+"]

    # streak1: 5 样本(B@D1 次日无行仍在分母但未晋级), G@D10 被尾部剔除
    assert buckets[1] == {"streak": 1, "samples": 5, "promoted": 3, "rate": 0.6}
    assert buckets[2] == {"streak": 2, "samples": 2, "promoted": 1, "rate": 0.5}
    for n in (3, 4, 5, 6, 7):
        assert buckets[n] == {"streak": n, "samples": 1, "promoted": 1, "rate": 1.0}


def test_top_bucket_merges_streak_8_plus(fake_session):
    """8+ 合并档: streak>=8 同档, 晋级=次日 streak>=9。"""
    _seed_main(fake_session)

    top = _buckets(promotion_stats(fake_session, D10))["8+"]

    # A@D8(s8)→D9 s9 晋级; A@D9(s9)→D10 无行未晋级
    assert top == {"streak": "8+", "samples": 2, "promoted": 1, "rate": 0.5}


def test_empty_bucket_rate_none(fake_session):
    """无样本档位: samples=0, rate=None 不除零。"""
    _seed_calendar(fake_session)
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D1, A, 1),
        _daily(D2, A, 2),
    ])

    buckets = _buckets(promotion_stats(fake_session, D10))

    assert buckets[3] == {"streak": 3, "samples": 0, "promoted": 0, "rate": None}
    assert buckets["8+"] == {"streak": "8+", "samples": 0, "promoted": 0, "rate": None}


# ── first_board_today / first_board_mean ─────────────────────────────────


def test_first_board_today_exact(fake_session):
    """当日实际 1进2: base=前一交易日首板非ST家数, promoted=其中当日二板家数。"""
    _seed_main(fake_session)

    today = promotion_stats(fake_session, D10)["first_board_today"]

    # 前一交易日=D9(周末前的 D5→D6 同理取日历前一天): D9 首板 {E,F}, D10 二板 {E}
    assert today == {"base": 2, "promoted": 1, "rate": 0.5}


def test_first_board_mean_is_per_day_average(fake_session):
    """历史均值=分日 1进2 频率的均值, 不是总样本比例。

    两日剧本: T1 1/2=0.5, T2 0/4=0 → mean=(0.5+0)/2=0.25;
    总样本比例=1/6≈0.167。断言 0.25 且 by_streak[1].rate==0.167 以示区分。
    """
    t1, t2, t3 = date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)
    _seed_calendar(fake_session, [t1, t2, t3])
    rows = [
        _daily(t1, "600201.SSE", 1),
        _daily(t1, "600202.SSE", 1),
        _daily(t2, "600201.SSE", 2),  # T1→T2 仅一股晋级: 1/2
        _daily(t2, "600203.SSE", 1),
        _daily(t2, "600204.SSE", 1),
        _daily(t2, "600205.SSE", 1),
        _daily(t2, "600206.SSE", 1),  # T2→T3 无人晋级: 0/4
    ]
    fake_session.execute(insert(schema.stock_limit_up_daily), rows)

    result = promotion_stats(fake_session, t3)

    assert result["first_board_mean"] == 0.25
    assert _buckets(result)[1]["rate"] == 0.167  # 总样本比例, 与分日均值不同


def test_first_board_mean_skips_zero_base_days(fake_session):
    """首板为 0 的样本日不 definable, 从均值中剔除。"""
    _seed_main(fake_session)

    # D2/D4..D8 首板家数为 0, 不参与均值; 仅 D1(0.5)/D3(1.0)/D9(0.5)
    assert promotion_stats(fake_session, D10)["first_board_mean"] == 0.667


# ── relay_5d 五日接力矩阵 ────────────────────────────────────────────────


def test_relay_5d_structure_and_6plus_merge(fake_session):
    _seed_main(fake_session)

    relay = promotion_stats(fake_session, D10)["relay_5d"]

    assert [r["trade_date"] for r in relay] == [
        "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
    ]
    # D6/D7/D8 各只有 A 的高位板(s6/s7/s8 → 6+ 合并档)
    assert relay[0]["tiers"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6+": 1}
    assert relay[1]["tiers"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6+": 1}
    assert relay[2]["tiers"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6+": 1}
    # D9: A s9 + E/F 首板
    assert relay[3]["tiers"] == {"1": 2, "2": 0, "3": 0, "4": 0, "5": 0, "6+": 1}
    # D10: E 二板 + G 首板
    assert relay[4]["tiers"] == {"1": 1, "2": 1, "3": 0, "4": 0, "5": 0, "6+": 0}


# ── ST 口径 ──────────────────────────────────────────────────────────────


def test_st_excluded_by_default_and_included_on_flag(fake_session):
    _seed_main(fake_session)

    default = promotion_stats(fake_session, D10)
    d_buckets = _buckets(default)
    # C/H 是 ST: 默认不进任何统计
    assert d_buckets[1] == {"streak": 1, "samples": 5, "promoted": 3, "rate": 0.6}
    assert default["first_board_today"] == {"base": 2, "promoted": 1, "rate": 0.5}
    assert default["relay_5d"][3]["tiers"]["1"] == 2  # D9 首板不含 H

    with_st = promotion_stats(fake_session, D10, include_st=True)
    s_buckets = _buckets(with_st)
    # C@D1/H@D9 首板均晋级, C@D2 二板晋级, C@D3 三板未晋级(D4 无行)
    assert s_buckets[1] == {
        "streak": 1, "samples": 7, "promoted": 5, "rate": round(5 / 7, 3),
    }
    assert s_buckets[2] == {
        "streak": 2, "samples": 3, "promoted": 2, "rate": round(2 / 3, 3),
    }
    assert s_buckets[3] == {"streak": 3, "samples": 2, "promoted": 1, "rate": 0.5}
    # H@D9 首板晋级 D10 二板 → 1进2 口径含 ST
    assert with_st["first_board_today"] == {
        "base": 3, "promoted": 2, "rate": round(2 / 3, 3),
    }
    assert with_st["relay_5d"][3]["tiers"]["1"] == 3  # D9 首板 {E,F,H}
    assert with_st["relay_5d"][4]["tiers"]["2"] == 2  # D10 二板 {E,H}
    # 分日均值: D1 2/3, D3 1/1, D9 2/3 → 7/9
    assert with_st["first_board_mean"] == round(7 / 9, 3)


# ── lookback 窗口裁剪 ────────────────────────────────────────────────────


def test_lookback_window_trims_old_samples(fake_session):
    """lookback=5: 样本窗口 D6..D10, 更早的 D1..D5 数据不进入任何统计。"""
    _seed_main(fake_session)

    result = promotion_stats(fake_session, D10, lookback=5)

    assert result["lookback_days"] == 5
    assert result["sample_start"] == "2026-08-10"
    assert result["sample_end"] == "2026-08-14"

    buckets = _buckets(result)
    # streak1 只剩 D9 的 {E,F}(D1/D3 样本被裁剪)
    assert buckets[1] == {"streak": 1, "samples": 2, "promoted": 1, "rate": 0.5}
    # A 的低位板(D1..D5)被裁剪, 高位板仍在窗口内
    assert buckets[2]["samples"] == 0
    assert buckets[6] == {"streak": 6, "samples": 1, "promoted": 1, "rate": 1.0}
    assert buckets[7] == {"streak": 7, "samples": 1, "promoted": 1, "rate": 1.0}
    assert buckets["8+"] == {"streak": "8+", "samples": 2, "promoted": 1, "rate": 0.5}
    # 分日均值只剩 D9(0.5)
    assert result["first_board_mean"] == 0.5
    # relay_5d 与 lookback 无关, 仍是日历最后 5 日
    assert [r["trade_date"] for r in result["relay_5d"]] == [
        "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
    ]


# ── 容错 ─────────────────────────────────────────────────────────────────


def test_empty_database_returns_complete_structure(fake_session):
    """当日(及全库)无数据: 结构完整, rate 一律 None, 不炸。"""
    result = promotion_stats(fake_session, D10)

    assert result["trade_date"] == "2026-08-14"
    assert result["lookback_days"] == 250
    assert result["sample_start"] is None
    assert result["sample_end"] is None

    buckets = _buckets(result)
    assert list(buckets) == [1, 2, 3, 4, 5, 6, 7, "8+"]
    for bucket in buckets.values():
        assert bucket["samples"] == 0
        assert bucket["promoted"] == 0
        assert bucket["rate"] is None

    assert result["first_board_today"] == {"base": 0, "promoted": 0, "rate": None}
    assert result["first_board_mean"] is None
    assert result["relay_5d"] == []


def test_first_board_today_none_when_today_not_rebuilt(fake_session):
    """日历有当日但 stock_limit_up_daily 无当日行(未重建): rate=None 容错。

    注意口径边界: D9 不是窗口最后一日, 仍进分母并对着空的 D10 判晋级
    → 频率 0.0(spec 只剔除窗口最后一日, 不感知 rebuild 缺口; 调用方
    应传已重建的交易日)。
    """
    _seed_calendar(fake_session)
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(D9, E, 1),
        _daily(D9, F, 1),
    ])

    result = promotion_stats(fake_session, D10)

    assert result["first_board_today"] == {"base": 0, "promoted": 0, "rate": None}
    assert _buckets(result)[1] == {"streak": 1, "samples": 2, "promoted": 0, "rate": 0.0}
    # relay_5d 正常输出(D9 两家首板, D10 零)
    assert result["relay_5d"][-2]["tiers"]["1"] == 2
    assert result["relay_5d"][-1]["tiers"]["1"] == 0
