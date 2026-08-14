"""news_driver 驱动新闻概念命中测试(2026-08-14 天洋新材案例固化)."""
from __future__ import annotations

import datetime

import pytest
from sqlalchemy import insert

from alphaagent.server.db import schema
from alphaagent.server.services.lianban.news_driver import (
    _match_concepts,
    news_concepts_for_date,
    sync_zt_news,
)
from alphaagent.server.services.lianban.theme_concepts import assign_theme_concepts

D = datetime.date(2026, 8, 14)


def test_match_concepts_hits_full_and_suffix_stripped():
    names = ["CPO概念", "光通信模块", "液冷概念", "铜"]
    titles = ["CPO 概念卷土重来", "液冷散热订单放量"]
    hits = _match_concepts(titles, names)
    assert "CPO概念" in hits
    assert "液冷概念" in hits
    assert "光通信模块" not in hits
    assert "铜" not in hits  # 单字概念不做匹配(误命中)


class _FakeNewsAdapter:
    def __init__(self, news: dict[str, list[dict]]):
        self.news = news
        self.calls: list[str] = []

    def stock_news_titles(self, symbol: str):
        self.calls.append(symbol)
        return {"items": self.news.get(symbol, [])}


def _zt_pool_row(vsym: str) -> dict:
    return {
        "trade_date": D, "pool_type": "zt", "vt_symbol": vsym,
        "name": "测试股", "limit_up_count": 1, "source": "test",
    }


def test_sync_zt_news_stores_day_scoped_hits(fake_session):
    s = fake_session
    s.execute(insert(schema.limit_up_pool_snapshots), [
        _zt_pool_row("603330.SSE"), _zt_pool_row("600105.SSE"),
    ])
    s.execute(insert(schema.sectors).values(
        id="BKCPO", name="CPO概念", type="concept", source="test"))
    adapter = _FakeNewsAdapter({
        "603330": [
            {"title": "CPO 概念卷土重来", "published_at": "2026-08-14 18:30:00"},
            {"title": "生肖概念爆火", "published_at": "2026-08-14 19:09:00"},
            {"title": "旧新闻不该进", "published_at": "2026-08-10 09:00:00"},
        ],
        "600105": [{"title": "无概念命中", "published_at": "2026-08-14 12:00:00"}],
    })
    result = sync_zt_news(s, D, adapter=adapter)
    assert result["fetched"] == 2
    stored = news_concepts_for_date(s, D)
    # 生肖概念板块未建 → 只有 CPO 命中可解; 标题过滤掉 8-10 旧新闻
    assert stored.get("603330.SSE") >= {"CPO概念"}
    assert "600105.SSE" not in stored


def test_sync_zt_news_adapter_failure_degrades(fake_session):
    s = fake_session
    s.execute(insert(schema.limit_up_pool_snapshots), [_zt_pool_row("600106.SSE")])

    class _Boom:
        def stock_news_titles(self, symbol):
            raise RuntimeError("network")

    result = sync_zt_news(s, D, adapter=_Boom())
    assert result["fetched"] == 0
    assert news_concepts_for_date(s, D) == {}


def test_news_concept_links_stock_into_cluster(fake_session):
    """天洋新材端到端: 新闻命中 CPO → 无 memberships 连接的股经新闻进入
    CPO 聚集(聚集 3 > 其他候选聚集 1) → 归 CPO 而非弱兜底概念。"""
    s = fake_session
    # CPO memberships 聚集 3(不含天洋)
    s.execute(insert(schema.sectors).values(
        id="BKCPO", name="CPO概念", type="concept", source="test"))
    for v in ("600111.SSE", "600112.SSE", "600113.SSE"):
        sym, _, ex = v.partition(".")
        s.execute(insert(schema.sector_memberships).values(
            sector_id="BKCPO", vt_symbol=v, symbol=sym, exchange=ex,
            name=f"股{sym}", source="test"))
    # 天洋只挂一个弱概念(聚集 1)
    s.execute(insert(schema.sectors).values(
        id="BKWK", name="网红经济", type="concept", source="test"))
    s.execute(insert(schema.sector_memberships).values(
        sector_id="BKWK", vt_symbol="603330.SSE", symbol="603330",
        exchange="SSE", name="天洋新材", source="test"))
    s.flush()
    result = assign_theme_concepts(
        s,
        ["603330.SSE", "600111.SSE", "600112.SSE", "600113.SSE"],
        news_concepts={"603330.SSE": {"CPO概念"}},
    )
    assert result["603330.SSE"] == "CPO"
    assert result["600111.SSE"] == "CPO"
