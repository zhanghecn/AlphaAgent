"""涨停股驱动新闻抓取与概念命中解析(2026-08-14).

数据源: 东财个股资讯(akshare.stock_news_em)——每只涨停股的近期新闻标题。
对标 lianban.rs 的驱动文案(其来自财联社), 我们用标题的概念名子串命中
做题材分配增强: memberships 之外的股票-概念连接(如天洋新材未挂光通信
板块, 但 8/14 新闻「"光"回来了！CPO 概念卷土重来」命中 CPO)。

噪音自抑: 标题里的娱乐性关联(如「生肖"洋"字辈」命中生肖概念)会在
分配时被聚集数竞争自然压制(产业概念当日聚集多, 娱乐概念聚集 1)。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, insert, select

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.db import schema as db_schema

logger = logging.getLogger(__name__)

# 标题中做概念名匹配的最短长度(1 字概念名如「铜」会大量误命中)。
_MIN_CONCEPT_LEN = 2
# 单股新闻抓取失败的容错上限(失败股跳过, 不阻塞归档)。
_MAX_FAILURES = 20


def _news_concept_names(session) -> list[str]:
    """候选概念名列表(全 concept 板块名, 已含「概念」后缀与原始名)。"""
    rows = session.execute(
        select(db_schema.sectors.c.name).where(db_schema.sectors.c.type == "concept")
    ).all()
    return sorted({str(r[0]) for r in rows if r[0]})


def _match_concepts(titles: list[str], concept_names: list[str]) -> list[str]:
    """标题子串命中概念名(原词或去「概念」后缀, 后缀去除后仍需 >=2 字)。

    「CPO概念」在标题「CPO 概念卷土重来」命中(CPO); 「光通信模块」需要
    标题出现完整词——新闻里常写「光模块」而非全名, 只能靠同链概念
    (CPO/光芯片等)自身命中后经聚集竞争传导, 不做同义词映射(写死词表)。
    """
    text = " ".join(titles)
    hits: set[str] = set()
    for name in concept_names:
        for word in {name, name.removesuffix("概念")}:
            if len(word) >= _MIN_CONCEPT_LEN and word in text:
                hits.add(name)
                break
    return sorted(hits)


def sync_zt_news(
    session,
    trade_date: date,
    *,
    adapter: Any = None,
) -> dict[str, Any]:
    """抓取 trade_date 涨停股的驱动新闻并解析概念命中, 幂等落库。

    归档链路后置钩子(archive_daily_pools 之后): 逐只拉取东财个股资讯,
    取发布日期 ∈ [trade_date-1, trade_date] 的标题, 与概念名子串匹配。
    单股失败跳过(容错上限), 整体失败不影响归档主流程(调用方吞异常)。
    """
    adapter = adapter if adapter is not None else AkShareAdapter()
    zt_rows = session.execute(
        select(db_schema.limit_up_pool_snapshots.c.vt_symbol)
        .where(
            db_schema.limit_up_pool_snapshots.c.trade_date == trade_date,
            db_schema.limit_up_pool_snapshots.c.pool_type == "zt",
        )
    ).all()
    if not zt_rows:
        return {"trade_date": trade_date.isoformat(), "stocks": 0, "fetched": 0}

    concept_names = _news_concept_names(session)
    day_prefix = trade_date.isoformat()
    prev_prefix = (trade_date - timedelta(days=1)).isoformat()

    table = db_schema.stock_zt_news
    session.execute(
        delete(table).where(table.c.trade_date == trade_date)
    )
    fetched = 0
    failures = 0
    rows: list[dict[str, Any]] = []
    for (vt_symbol,) in zt_rows:
        symbol = str(vt_symbol).partition(".")[0]
        try:
            payload = adapter.stock_news_titles(symbol)
        except Exception:
            failures += 1
            if failures > _MAX_FAILURES:
                logger.warning("zt news fetch failure cap reached at %s", symbol)
                break
            continue
        titles = [
            str(item.get("title") or "")
            for item in (payload.get("items") or [])
            if str(item.get("published_at") or "").startswith((day_prefix, prev_prefix))
            and item.get("title")
        ]
        if not titles:
            continue
        fetched += 1
        rows.append(
            {
                "trade_date": trade_date,
                "vt_symbol": str(vt_symbol),
                "titles": titles,
                "concepts": _match_concepts(titles, concept_names),
            }
        )
    if rows:
        session.execute(insert(table), rows)
    return {
        "trade_date": trade_date.isoformat(),
        "stocks": len(zt_rows),
        "fetched": fetched,
        "with_concepts": sum(1 for r in rows if r["concepts"]),
        "failures": failures,
    }


def news_concepts_for_date(session, trade_date: date) -> dict[str, set[str]]:
    """读取当日新闻概念命中: {vt_symbol: 概念全名集合}(无命中股不含)。

    增强路径: 表缺失/查询异常 → {}(降级纯 memberships 分配)。
    """
    try:
        rows = session.execute(
            select(
                db_schema.stock_zt_news.c.vt_symbol,
                db_schema.stock_zt_news.c.concepts,
            ).where(db_schema.stock_zt_news.c.trade_date == trade_date)
        ).all()
    except Exception:
        return {}
    return {
        str(vsym): {str(c) for c in (concepts or [])}
        for vsym, concepts in rows
        if concepts
    }
