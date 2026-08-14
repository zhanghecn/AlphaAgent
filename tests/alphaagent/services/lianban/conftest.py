"""lianban 测试共享夹具: sqlite 内存库会话。

schema 的 raw 列是 postgresql.JSONB, sqlite 编译器不认识, 这里把 JSONB 在
sqlite 方言下渲染为 JSON(SQLAlchemy 通用 JSON 处理器可正常序列化/反序列化)。
仅影响 sqlite 渲染, 不影响 postgres。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from alphaagent.server.db import schema


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_, compiler, **kw):  # pragma: no cover - 编译钩子
    return "JSON"


@pytest.fixture()
def fake_session():
    """sqlite 内存库会话, 建好 lianban 归档/回补/融资余额/梯队/复盘涉及的表。"""
    engine = create_engine("sqlite:///:memory:")
    # stocks 在 stock_daily_bars 之前建(FK 指向 stocks.vt_symbol)。
    schema.stocks.create(engine)
    schema.stock_daily_bars.create(engine)
    schema.limit_up_pool_snapshots.create(engine)
    schema.market_margin_balance.create(engine)
    schema.stock_limit_up_daily.create(engine)
    schema.sectors.create(engine)
    schema.stock_sector_memberships.create(engine)
    # theme_concepts 主题材分配读 concept memberships。
    schema.sector_memberships.create(engine)
    # B3 复盘聚合增量: 情绪历史/人气榜/板块资金流(FK → sectors.id)。
    schema.mainline_sentiment_history.create(engine)
    schema.stock_hot_ranks.create(engine)
    schema.sector_fund_flows.create(engine)
    with Session(engine) as session:
        yield session
