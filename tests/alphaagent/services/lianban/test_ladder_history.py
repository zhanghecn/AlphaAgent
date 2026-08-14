"""连板天梯历史 ladder_history: matrix 分档 / leader 确定性 / promotion_matrix
窗口口径 / 尾日剔除 / ST 过滤 / 零涨停日不进窗口 / 空库容错 / API 契约。

sqlite 内存库真实落库验证(见 conftest.fake_session), 不碰网络; API 契约测试
用 TestClient + monkeypatch service(参照 test_api.py 模式)。

主剧本(5 个有涨停数据的交易日 T1=2026-08-05 .. T5=2026-08-11; 窗口由
stock_limit_up_daily 的 is_limit_up=True 行驱动, 不依赖交易日历):
- A(600101): T1..T5 五连板(streak 1..5)
- B(600102): T1 首板→T2 仍首板(断板后再首板)→T3 无行
- C(600103): T1 首板→T2 二板→T3 三板→T4 断板无行
- D(600104): T1 三板(一字)→T2 四板→T3 五板→T4 六板→T5 七板(每日最高板龙头)
- E(600105): T3 首板→T4 二板→T5 首板(断板后再首板)
- G(600107): T5 首板(窗口尾日, 验证尾部剔除: 不进任何晋级分母)
- F(600108, ST): T4/T5 首板(仅 include_st 口径可见)
- Z=2026-08-12: 仅一行 is_limit_up=False 的摸板行(零涨停日), 不进窗口

非 ST 默认口径精确值(days=60, 窗口=T1..T5, 晋级分母日=T1..T4):
- streak1: 样本 {A@T1,B@T1,C@T1,B@T2,E@T3}=5, 晋级 {A,C,E}=3 → 0.6
  (G@T5/E@T5/F@T5 尾日剔除; B@T2→T3 无行未晋级)
- streak2: {A@T2,C@T2,E@T4}=3, 晋级 {A,C}=2 → 0.667
- streak3: {D@T1,A@T3,C@T3}=3, 晋级 {D,A}=2 → 0.667
- streak4: {D@T2,A@T4}=2, 均晋级 → 1.0
- streak5: {D@T3}=1 晋级 → 1.0; streak6: {D@T4}=1 晋级 → 1.0
- streak7 / 8+: 无样本, rate=None
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from alphaagent.server.api import lianban as lianban_api
from alphaagent.server.db import schema
from alphaagent.server.main import create_app
from alphaagent.server.services.lianban.ladder_history import ladder_history

T1 = date(2026, 8, 5)
T2 = date(2026, 8, 6)
T3 = date(2026, 8, 7)
T4 = date(2026, 8, 10)  # 周一, 跨周末
T5 = date(2026, 8, 11)
Z = date(2026, 8, 12)  # 零涨停日(仅摸板行), 不进窗口
DAYS = [T1, T2, T3, T4, T5]

A = "600101.SSE"
B = "600102.SSE"
C = "600103.SSE"
D = "600104.SSE"
E = "600105.SSE"
G = "600107.SSE"
F = "600108.SSE"  # ST


def _daily(d: date, sym: str, streak: int, *, is_st: bool = False,
           one_word: bool = False) -> dict:
    return {
        "trade_date": d,
        "vt_symbol": sym,
        "is_limit_up": True,
        "limit_up_count": streak,
        "is_one_word": one_word,
        "is_st": is_st,
        "board": "main",
        "close_price": 10.0,
        "change_pct": 10.0,
        "touched_limit": False,
        "source": "daily_rebuild",
    }


def _touched(d: date, sym: str) -> dict:
    """摸板未封行: is_limit_up=False, 不构成窗口日期。"""
    return {
        "trade_date": d,
        "vt_symbol": sym,
        "is_limit_up": False,
        "limit_up_count": 0,
        "is_one_word": False,
        "is_st": False,
        "board": "main",
        "close_price": 9.5,
        "change_pct": 5.0,
        "touched_limit": True,
        "source": "daily_rebuild",
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


def _seed_main(session) -> None:
    rows = [
        # T1: A/B/C 首板, D 三板(一字)
        _daily(T1, A, 1), _daily(T1, B, 1), _daily(T1, C, 1),
        _daily(T1, D, 3, one_word=True),
        # T2: A/C 晋级, B 断板后再首板, D 四板
        _daily(T2, A, 2), _daily(T2, B, 1), _daily(T2, C, 2), _daily(T2, D, 4),
        # T3: A/C 三板, D 五板, E 首板
        _daily(T3, A, 3), _daily(T3, C, 3), _daily(T3, D, 5), _daily(T3, E, 1),
        # T4: A 四板, D 六板, E 二板, F(ST) 首板
        _daily(T4, A, 4), _daily(T4, D, 6), _daily(T4, E, 2),
        _daily(T4, F, 1, is_st=True),
        # T5: A 五板, D 七板, E/G 首板, F(ST) 首板
        _daily(T5, A, 5), _daily(T5, D, 7), _daily(T5, E, 1), _daily(T5, G, 1),
        _daily(T5, F, 1, is_st=True),
        # Z 日: 全市场零涨停, 仅摸板行 → 不进窗口
        _touched(Z, B),
    ]
    session.execute(insert(schema.stock_limit_up_daily), rows)
    session.execute(insert(schema.stocks), [_stock(D, "丁股份")])


def _promo_buckets(result: dict) -> dict:
    return {b["streak"]: b for b in result["promotion_matrix"]}


# ── matrix 分档 / total / max_streak / leader ────────────────────────────


def test_matrix_tiers_total_and_max_streak(fake_session):
    _seed_main(fake_session)

    result = ladder_history(fake_session, days=60)

    assert result["days"] == 60
    assert result["as_of"] == T5.isoformat()
    assert result["dates"] == [d.isoformat() for d in DAYS]
    assert [m["trade_date"] for m in result["matrix"]] == result["dates"]

    m1, m2, m3, m4, m5 = result["matrix"]
    # T1: 首板3 + 三板1
    assert m1["tiers"] == {"1": 3, "2": 0, "3": 1, "4": 0, "5": 0, "6+": 0}
    assert m1["total"] == 4
    assert m1["max_streak"] == 3
    # T2: 首板1 + 二板2 + 四板1
    assert m2["tiers"] == {"1": 1, "2": 2, "3": 0, "4": 1, "5": 0, "6+": 0}
    assert m2["total"] == 4
    assert m2["max_streak"] == 4
    # T3: 首板1 + 三板2 + 五板1
    assert m3["tiers"] == {"1": 1, "2": 0, "3": 2, "4": 0, "5": 1, "6+": 0}
    assert m3["total"] == 4
    assert m3["max_streak"] == 5
    # T4: 二板1 + 四板1 + 六板1(6+ 合并档)
    assert m4["tiers"] == {"1": 0, "2": 1, "3": 0, "4": 1, "5": 0, "6+": 1}
    assert m4["total"] == 3
    assert m4["max_streak"] == 6
    # T5: 首板2 + 五板1 + 七板1(6+)
    assert m5["tiers"] == {"1": 2, "2": 0, "3": 0, "4": 0, "5": 1, "6+": 1}
    assert m5["total"] == 4
    assert m5["max_streak"] == 7


def test_matrix_leader_and_name_lookup(fake_session):
    """leader=每日最高板; name 取 stocks 表快照, 缺失回落 vt_symbol。"""
    _seed_main(fake_session)

    result = ladder_history(fake_session, days=60)

    for entry, streak in zip(result["matrix"], [3, 4, 5, 6, 7]):
        assert entry["leader"] == {
            "vt_symbol": D, "name": "丁股份", "streak": streak,
        }


def test_leader_tie_break_uses_vt_symbol_order(fake_session):
    """同板位多只: 取 vt_symbol 字典序第一只(日线表无封板时间, 确定性)。"""
    x, y = "600200.SSE", "600199.SSE"  # 字典序 y < x
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(T1, x, 2),
        _daily(T1, y, 2),
        _daily(T1, "600198.SSE", 1),
    ])

    result = ladder_history(fake_session, days=60)

    entry = result["matrix"][0]
    assert entry["max_streak"] == 2
    assert entry["tiers"]["2"] == 2
    assert entry["leader"]["vt_symbol"] == y
    # 未 seed stocks 名称 → 回落 vt_symbol
    assert entry["leader"]["name"] == y


# ── promotion_matrix 窗口晋级率 ──────────────────────────────────────────


def test_promotion_matrix_exact_values_and_tail_exclusion(fake_session):
    """分板位晋级率精确值; 窗口尾日(T5)样本剔除(与 promotion 同口径)。"""
    _seed_main(fake_session)

    buckets = _promo_buckets(ladder_history(fake_session, days=60))

    assert list(buckets) == [1, 2, 3, 4, 5, 6, 7, "8+"]
    # G@T5/E@T5 首板是尾日样本 → 剔除; streak1 样本恒为 5
    assert buckets[1] == {"streak": 1, "samples": 5, "promoted": 3, "rate": 0.6}
    assert buckets[2] == {"streak": 2, "samples": 3, "promoted": 2, "rate": 0.667}
    assert buckets[3] == {"streak": 3, "samples": 3, "promoted": 2, "rate": 0.667}
    assert buckets[4] == {"streak": 4, "samples": 2, "promoted": 2, "rate": 1.0}
    assert buckets[5] == {"streak": 5, "samples": 1, "promoted": 1, "rate": 1.0}
    assert buckets[6] == {"streak": 6, "samples": 1, "promoted": 1, "rate": 1.0}
    assert buckets[7] == {"streak": 7, "samples": 0, "promoted": 0, "rate": None}
    assert buckets["8+"] == {"streak": "8+", "samples": 0, "promoted": 0,
                             "rate": None}


def test_promotion_matrix_8plus_bucket(fake_session):
    """8+ 合并档透出(复用 promotion._by_streak): 晋级=次日 streak>=9。"""
    p1, p2 = date(2026, 8, 10), date(2026, 8, 11)
    h = "600109.SSE"
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(p1, h, 8),
        _daily(p1, "600110.SSE", 1),
        _daily(p2, h, 9),
    ])

    result = ladder_history(fake_session, days=60)

    buckets = _promo_buckets(result)
    assert buckets["8+"] == {"streak": "8+", "samples": 1, "promoted": 1,
                             "rate": 1.0}
    # 首板样本未晋级(p2 无该行), rate=0.0 而非 None
    assert buckets[1] == {"streak": 1, "samples": 1, "promoted": 0, "rate": 0.0}
    # 8 板也进 matrix 的 6+ 档
    assert result["matrix"][0]["tiers"]["6+"] == 1
    assert result["matrix"][0]["max_streak"] == 8
    assert result["matrix"][1]["max_streak"] == 9


# ── leaders 龙头序列 ─────────────────────────────────────────────────────


def test_leaders_carry_is_one_word(fake_session):
    _seed_main(fake_session)

    leaders = ladder_history(fake_session, days=60)["leaders"]

    assert [l["trade_date"] for l in leaders] == [d.isoformat() for d in DAYS]
    assert [(l["vt_symbol"], l["streak"]) for l in leaders] == [
        (D, 3), (D, 4), (D, 5), (D, 6), (D, 7),
    ]
    assert leaders[0]["name"] == "丁股份"
    # is_one_word 从表里透出: 仅 D@T1 是一字板
    assert [l["is_one_word"] for l in leaders] == [True, False, False, False, False]


# ── 窗口口径: 数据驱动日期 / days 裁剪 / 零涨停日 / ST ────────────────────


def test_zero_limit_up_day_not_in_window(fake_session):
    """Z 日(2026-08-12)只有摸板行无涨停行 → 不进 dates, as_of 停在 T5。"""
    _seed_main(fake_session)

    result = ladder_history(fake_session, days=60)

    assert Z.isoformat() not in result["dates"]
    assert result["as_of"] == T5.isoformat()
    assert len(result["matrix"]) == 5


def test_days_window_trims_older_dates(fake_session):
    """days=3 → 窗口=T3..T5; 晋级分母只剩 T3/T4。"""
    _seed_main(fake_session)

    result = ladder_history(fake_session, days=3)

    assert result["days"] == 3
    assert result["dates"] == [T3.isoformat(), T4.isoformat(), T5.isoformat()]
    assert [m["trade_date"] for m in result["matrix"]] == result["dates"]
    assert result["as_of"] == T5.isoformat()

    buckets = _promo_buckets(result)
    # streak1: T3{E}→T4 晋级 = 1/1(T1/T2 样本被裁剪, T5 尾日剔除)
    assert buckets[1] == {"streak": 1, "samples": 1, "promoted": 1, "rate": 1.0}
    # streak3: T3{A,C} → A 晋级/C 断板 = 2/1
    assert buckets[3] == {"streak": 3, "samples": 2, "promoted": 1, "rate": 0.5}
    # streak5: T3{D}→T4 晋级; streak6: T4{D}→T5 晋级
    assert buckets[5] == {"streak": 5, "samples": 1, "promoted": 1, "rate": 1.0}
    assert buckets[6] == {"streak": 6, "samples": 1, "promoted": 1, "rate": 1.0}
    # 高位样本被裁掉后 streak4 只剩 T4{A}→T5
    assert buckets[4] == {"streak": 4, "samples": 1, "promoted": 1, "rate": 1.0}


def test_st_excluded_by_default_and_included_on_flag(fake_session):
    _seed_main(fake_session)

    default = ladder_history(fake_session, days=60)
    # F 不可见: T4/T5 首板家数不含 ST
    assert default["matrix"][3]["tiers"]["1"] == 0
    assert default["matrix"][4]["tiers"]["1"] == 2
    assert default["matrix"][4]["total"] == 4
    assert _promo_buckets(default)[1]["samples"] == 5

    with_st = ladder_history(fake_session, days=60, include_st=True)
    assert with_st["matrix"][3]["tiers"]["1"] == 1  # T4 含 F
    assert with_st["matrix"][3]["total"] == 4
    assert with_st["matrix"][4]["tiers"]["1"] == 3  # T5 含 F
    assert with_st["matrix"][4]["total"] == 5
    # F@T4 首板次日仍首板 → 未晋级, 样本 +1: 5+1=6, 晋级仍 3 → 0.5
    assert _promo_buckets(with_st)[1] == {
        "streak": 1, "samples": 6, "promoted": 3, "rate": 0.5,
    }


def test_st_only_day_excluded_from_default_window(fake_session):
    """某日涨停股全是 ST: 默认口径当日无合格行 → 不进窗口; include_st 才进。"""
    w1, w2 = date(2026, 8, 10), date(2026, 8, 11)
    fake_session.execute(insert(schema.stock_limit_up_daily), [
        _daily(w1, F, 1, is_st=True),
        _daily(w2, A, 1),
    ])

    default = ladder_history(fake_session, days=60)
    assert default["dates"] == [w2.isoformat()]

    with_st = ladder_history(fake_session, days=60, include_st=True)
    assert with_st["dates"] == [w1.isoformat(), w2.isoformat()]
    assert with_st["matrix"][0]["leader"]["vt_symbol"] == F


# ── 容错 ─────────────────────────────────────────────────────────────────


def test_empty_database_returns_empty_structure(fake_session):
    """全库无涨停行: 结构完整, dates/matrix/leaders 空, 晋级率全零档 None。"""
    result = ladder_history(fake_session, days=60)

    assert result["days"] == 60
    assert result["as_of"] is None
    assert result["dates"] == []
    assert result["matrix"] == []
    assert result["leaders"] == []

    buckets = _promo_buckets(result)
    assert list(buckets) == [1, 2, 3, 4, 5, 6, 7, "8+"]
    for bucket in buckets.values():
        assert bucket["samples"] == 0
        assert bucket["promoted"] == 0
        assert bucket["rate"] is None


# ── API 契约: GET /api/lianban/ladder-history ────────────────────────────


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _patch_session(monkeypatch, session) -> None:
    """端点 DB 依赖替换(与 test_api.py 同模式)。"""

    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(lianban_api, "session_scope", fake_scope)
    monkeypatch.setattr(lianban_api, "is_database_configured", lambda: True)


def _history_payload() -> dict:
    return {
        "days": 60,
        "as_of": T5.isoformat(),
        "dates": [d.isoformat() for d in DAYS],
        "matrix": [
            {"trade_date": T5.isoformat(),
             "tiers": {"1": 2, "2": 0, "3": 0, "4": 0, "5": 1, "6+": 1},
             "total": 4, "max_streak": 7,
             "leader": {"vt_symbol": D, "name": "丁股份", "streak": 7}},
        ],
        "promotion_matrix": [
            {"streak": 1, "samples": 5, "promoted": 3, "rate": 0.6},
        ],
        "leaders": [
            {"trade_date": T5.isoformat(), "vt_symbol": D, "name": "丁股份",
             "streak": 7, "is_one_word": False},
        ],
    }


class _SpyLadderHistory:
    """ladder_history 替身: 记录调用参数, 返回固定 payload。"""

    def __init__(self, payload: dict | None = None):
        self.payload = payload or _history_payload()
        self.calls: list[dict] = []

    def __call__(self, session, *, days: int = 60, include_st: bool = False):
        self.calls.append({"days": days, "include_st": include_st})
        return self.payload


def test_api_ladder_history_ok_and_params(client, monkeypatch):
    spy = _SpyLadderHistory()
    _patch_session(monkeypatch, object())
    monkeypatch.setattr(lianban_api, "ladder_history", spy)

    response = client.get("/api/lianban/ladder-history?days=120&include_st=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["as_of"] == T5.isoformat()
    assert payload["data"]["matrix"][0]["leader"]["streak"] == 7
    assert spy.calls == [{"days": 120, "include_st": True}]


def test_api_ladder_history_default_days(client, monkeypatch):
    spy = _SpyLadderHistory()
    _patch_session(monkeypatch, object())
    monkeypatch.setattr(lianban_api, "ladder_history", spy)

    response = client.get("/api/lianban/ladder-history")

    assert response.status_code == 200
    assert spy.calls == [{"days": 60, "include_st": False}]


def test_api_ladder_history_empty_structure_ok(client, monkeypatch):
    """无数据 → 200 空结构(不 404)。"""
    spy = _SpyLadderHistory(payload={
        "days": 60, "as_of": None, "dates": [], "matrix": [],
        "promotion_matrix": [], "leaders": [],
    })
    _patch_session(monkeypatch, object())
    monkeypatch.setattr(lianban_api, "ladder_history", spy)

    response = client.get("/api/lianban/ladder-history")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["as_of"] is None
    assert data["dates"] == []
    assert data["matrix"] == []


@pytest.mark.parametrize("days", ["4", "251", "abc", "0", "-1"])
def test_api_ladder_history_invalid_days_returns_422(client, monkeypatch, days):
    """days 非整数 / <5 / >250 → FastAPI 校验 422(service 不被调用)。"""
    spy = _SpyLadderHistory()
    _patch_session(monkeypatch, object())
    monkeypatch.setattr(lianban_api, "ladder_history", spy)

    response = client.get(f"/api/lianban/ladder-history?days={days}")

    assert response.status_code == 422
    assert spy.calls == []


def test_api_ladder_history_db_unavailable_returns_503(client, monkeypatch):
    monkeypatch.setattr(lianban_api, "is_database_configured", lambda: False)

    response = client.get("/api/lianban/ladder-history")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LIANBAN_DB_UNAVAILABLE"
