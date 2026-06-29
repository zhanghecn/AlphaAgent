"""Database schema for the AlphaAgent sync MVP."""

from __future__ import annotations

import logging
import threading

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()
logger = logging.getLogger(__name__)

sync_sources = Table(
    "sync_sources",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("kind", String(40), nullable=False),
    Column("base_url", String(255), nullable=True),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("priority", Integer, nullable=False, server_default="100"),
    Column("status", String(40), nullable=False, server_default="unknown"),
    Column("message", Text, nullable=True),
    Column("checked_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)

sync_job_definitions = Table(
    "sync_job_definitions",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("description", Text, nullable=False),
    Column("source_id", String(80), ForeignKey("sync_sources.id"), nullable=False),
    Column("target_table", String(80), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("default_params", JSONB, nullable=False, server_default="{}"),
    Column("schedule_cron", String(80), nullable=True),
    Column("last_status", String(40), nullable=True),
    Column("last_run_id", BigInteger, nullable=True),
    Column("last_started_at", DateTime(timezone=True), nullable=True),
    Column("last_finished_at", DateTime(timezone=True), nullable=True),
    Column("last_message", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)

sync_job_runs = Table(
    "sync_job_runs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("job_id", String(80), ForeignKey("sync_job_definitions.id"), nullable=False),
    Column("status", String(40), nullable=False),
    Column("params", JSONB, nullable=False, server_default="{}"),
    Column("rows_read", Integer, nullable=False, server_default="0"),
    Column("rows_written", Integer, nullable=False, server_default="0"),
    Column("message", Text, nullable=True),
    Column("error_type", String(120), nullable=True),
    Column("error_detail", Text, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
)

sync_batch_schedules = Table(
    "sync_batch_schedules",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("cron", String(80), nullable=False),
    Column("action", String(40), nullable=False, server_default="sync"),
    Column("job_ids", JSONB, nullable=False, server_default="[]"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("concurrency", Integer, nullable=False, server_default="8"),
    Column("last_status", String(40), nullable=True),
    Column("last_started_at", DateTime(timezone=True), nullable=True),
    Column("last_finished_at", DateTime(timezone=True), nullable=True),
    Column("last_message", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)


stocks = Table(
    "stocks",
    metadata,
    Column("vt_symbol", String(32), primary_key=True),
    Column("symbol", String(16), nullable=False),
    Column("exchange", String(16), nullable=False),
    Column("name", String(80), nullable=False),
    Column("industry", String(120), nullable=True),
    Column("area", String(80), nullable=True),
    Column("last_price", Float, nullable=True),
    Column("change_pct", Float, nullable=True),
    Column("return_5d", Float, nullable=True),
    Column("return_10d", Float, nullable=True),
    Column("return_20d", Float, nullable=True),
    Column("turnover", Float, nullable=True),
    Column("market_cap", Float, nullable=True),
    Column("pe", Float, nullable=True),
    Column("pb", Float, nullable=True),
    Column("turnover_rate", Float, nullable=True),
    Column("volume_ratio", Float, nullable=True),
    Column("trade_time", String(40), nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stocks_symbol", stocks.c.symbol)
Index("ix_stocks_name", stocks.c.name)

stock_daily_bars = Table(
    "stock_daily_bars",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", Date, primary_key=True),
    Column("open_price", Float, nullable=False),
    Column("close_price", Float, nullable=False),
    Column("high_price", Float, nullable=False),
    Column("low_price", Float, nullable=False),
    Column("volume", Float, nullable=True),
    Column("turnover", Float, nullable=True),
    Column("change_pct", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_daily_bars_trade_date", stock_daily_bars.c.trade_date)

stock_minute_bars = Table(
    "stock_minute_bars",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("bar_time", DateTime(timezone=False), primary_key=True),
    Column("interval", String(8), primary_key=True),
    Column("trade_date", Date, nullable=False),
    Column("open_price", Float, nullable=False),
    Column("close_price", Float, nullable=False),
    Column("high_price", Float, nullable=False),
    Column("low_price", Float, nullable=False),
    Column("volume", Float, nullable=True),
    Column("turnover", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_minute_bars_trade_date", stock_minute_bars.c.trade_date)
Index("ix_stock_minute_bars_symbol_date", stock_minute_bars.c.vt_symbol, stock_minute_bars.c.trade_date)

sectors = Table(
    "sectors",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("type", String(40), nullable=False),
    Column("category", String(160), nullable=True),
    Column("path", JSONB, nullable=False, server_default="[]"),
    Column("stock_count", Integer, nullable=True),
    Column("change_pct", Float, nullable=True),
    Column("market_cap", Float, nullable=True),
    Column("turnover_rate", Float, nullable=True),
    Column("rise_count", Integer, nullable=True),
    Column("fall_count", Integer, nullable=True),
    Column("leader_stock", String(120), nullable=True),
    Column("leader_change_pct", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_sectors_name", sectors.c.name)
Index("ix_sectors_type", sectors.c.type)

sector_memberships = Table(
    "sector_memberships",
    metadata,
    Column("sector_id", String(64), ForeignKey("sectors.id", ondelete="CASCADE"), primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("symbol", String(16), nullable=False),
    Column("exchange", String(16), nullable=False),
    Column("name", String(80), nullable=False),
    Column("change_pct", Float, nullable=True),
    Column("return_5d", Float, nullable=True),
    Column("return_10d", Float, nullable=True),
    Column("return_20d", Float, nullable=True),
    Column("turnover", Float, nullable=True),
    Column("market_cap", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_sector_memberships_vt_symbol", sector_memberships.c.vt_symbol)

stock_sector_memberships = Table(
    "stock_sector_memberships",
    metadata,
    Column("vt_symbol", String(32), primary_key=True),
    Column("sector_id", String(64), primary_key=True),
    Column("sector_name", String(160), nullable=False),
    Column("sector_type", String(40), nullable=False),
    Column("rank", Integer, nullable=True),
    Column("confirmed", Boolean, nullable=True),
    Column("is_precise", Boolean, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_sector_memberships_sector", stock_sector_memberships.c.sector_id)

stock_business_segments = Table(
    "stock_business_segments",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("vt_symbol", String(32), nullable=False),
    Column("segment_name", String(240), nullable=False),
    Column("segment_type", String(40), nullable=True),
    Column("report_date", String(40), nullable=True),
    Column("revenue", Float, nullable=True),
    Column("revenue_ratio", Float, nullable=True),
    Column("revenue_yoy", Float, nullable=True),
    Column("gross_profit", Float, nullable=True),
    Column("gross_profit_ratio", Float, nullable=True),
    Column("gross_margin", Float, nullable=True),
    Column("profit_ratio", Float, nullable=True),
    Column("rank", Integer, nullable=True),
    Column("confidence", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint("vt_symbol", "segment_name", "report_date", name="uq_stock_business_segment"),
)
Index("ix_stock_business_segments_vt_symbol", stock_business_segments.c.vt_symbol)


# ── Shenwan Industry Classification ──

shenwan_industries = Table(
    "shenwan_industries",
    metadata,
    Column("code", String(32), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("level", Integer, nullable=False),
    Column("parent_code", String(32), ForeignKey("shenwan_industries.code"), nullable=True),
    Column("path", JSONB, nullable=False, server_default="[]"),
    Column("stock_count", Integer, nullable=True),
    Column("change_pct", Float, nullable=True),
    Column("market_cap", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_shenwan_industries_level", shenwan_industries.c.level)
Index("ix_shenwan_industries_parent_code", shenwan_industries.c.parent_code)
Index("ix_shenwan_industries_name", shenwan_industries.c.name)

shenwan_industry_members = Table(
    "shenwan_industry_members",
    metadata,
    Column("industry_code", String(32), ForeignKey("shenwan_industries.code", ondelete="CASCADE"), primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("symbol", String(16), nullable=False),
    Column("exchange", String(16), nullable=False),
    Column("name", String(80), nullable=False),
    Column("market_cap", Float, nullable=True),
    Column("change_pct", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_shenwan_industry_members_vt_symbol", shenwan_industry_members.c.vt_symbol)

industry_chain_edges = Table(
    "industry_chain_edges",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("as_of_date", Date, nullable=True),
    Column("period", String(16), nullable=True),
    Column("source_industry_code", String(32), ForeignKey("shenwan_industries.code"), nullable=False),
    Column("target_industry_code", String(32), ForeignKey("shenwan_industries.code"), nullable=False),
    Column("source_node_id", String(64), nullable=True),
    Column("target_node_id", String(64), nullable=True),
    Column("relationship_type", String(40), nullable=False),
    Column("relation_type", String(40), nullable=True),
    Column("strength", Float, nullable=False),
    Column("score", Float, nullable=True),
    Column("evidence_count", Integer, nullable=False, server_default="0"),
    Column("evidence_detail", JSONB, nullable=False, server_default="[]"),
    Column("evidence", JSONB, nullable=True),
    Column("confidence", Float, nullable=True),
    Column("level", Integer, nullable=False),
    Column("source", String(160), nullable=False, server_default="alphaagent_supply_chain_inference"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "source_industry_code", "target_industry_code", "relationship_type", "level",
        name="uq_industry_chain_edge",
    ),
)
Index("ix_industry_chain_edges_source", industry_chain_edges.c.source_industry_code)
Index("ix_industry_chain_edges_target", industry_chain_edges.c.target_industry_code)

industry_board_mapping = Table(
    "industry_board_mapping",
    metadata,
    Column("industry_code", String(32), ForeignKey("shenwan_industries.code", ondelete="CASCADE"), primary_key=True),
    Column("board_id", String(64), primary_key=True),
    Column("board_name", String(160), nullable=False),
    Column("board_type", String(40), nullable=False),
    Column("overlap_count", Integer, nullable=False, server_default="0"),
    Column("overlap_ratio", Float, nullable=False, server_default="0.0"),
    Column("source", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)


# ── Sector dashboard: daily bars, metrics, period scores ──

sector_daily_bars = Table(
    "sector_daily_bars",
    metadata,
    Column("sector_id", String(64), ForeignKey("sectors.id", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", Date, primary_key=True),
    Column("open_price", Float, nullable=False),
    Column("close_price", Float, nullable=False),
    Column("high_price", Float, nullable=False),
    Column("low_price", Float, nullable=False),
    Column("volume", Float, nullable=True),
    Column("turnover", Float, nullable=True),
    Column("change_pct", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_sector_daily_bars_trade_date", sector_daily_bars.c.trade_date)

sector_daily_metrics = Table(
    "sector_daily_metrics",
    metadata,
    Column("sector_id", String(64), ForeignKey("sectors.id", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", Date, primary_key=True),
    Column("stock_count", Integer, nullable=True),
    Column("rise_count", Integer, nullable=True),
    Column("fall_count", Integer, nullable=True),
    Column("flat_count", Integer, nullable=True),
    Column("limit_up_count", Integer, nullable=True),
    Column("limit_down_count", Integer, nullable=True),
    Column("avg_change_pct", Float, nullable=True),
    Column("median_change_pct", Float, nullable=True),
    Column("turnover_weighted_change_pct", Float, nullable=True),
    Column("market_cap_weighted_change_pct", Float, nullable=True),
    Column("turnover", Float, nullable=True),
    Column("main_net_inflow", Float, nullable=True),
    Column("main_net_inflow_ratio", Float, nullable=True),
    Column("leader_vt_symbol", String(32), nullable=True),
    Column("leader_name", String(80), nullable=True),
    Column("leader_change_pct", Float, nullable=True),
    Column("leader_reason", String(80), nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_sector_daily_metrics_trade_date", sector_daily_metrics.c.trade_date)

sector_period_scores = Table(
    "sector_period_scores",
    metadata,
    Column("sector_id", String(64), ForeignKey("sectors.id", ondelete="CASCADE"), primary_key=True),
    Column("as_of_date", Date, primary_key=True),
    Column("period", String(16), primary_key=True),
    Column("sector_type", String(40), nullable=True),
    Column("return_pct", Float, nullable=True),
    Column("rank_return", Integer, nullable=True),
    Column("momentum_score", Float, nullable=True),
    Column("breadth_score", Float, nullable=True),
    Column("fund_score", Float, nullable=True),
    Column("sentiment_score", Float, nullable=True),
    Column("leader_score", Float, nullable=True),
    Column("continuity_score", Float, nullable=True),
    Column("liquidity_score", Float, nullable=True),
    Column("risk_penalty", Float, nullable=True),
    Column("heat_score", Float, nullable=True),
    Column("trend_state", String(20), nullable=True),
    Column("confidence", Float, nullable=True),
    Column("evidence", JSONB, nullable=True),
    Column("source", String(160), nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_sector_period_scores_date", sector_period_scores.c.as_of_date)
Index("ix_sector_period_scores_period", sector_period_scores.c.period)

# ── Sector relation graph ──

sector_relation_edges = Table(
    "sector_relation_edges",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("as_of_date", Date, nullable=False),
    Column("period", String(16), nullable=False),
    Column("source_sector_id", String(64), ForeignKey("sectors.id", ondelete="CASCADE"), nullable=False),
    Column("target_sector_id", String(64), ForeignKey("sectors.id", ondelete="CASCADE"), nullable=False),
    Column("score", Float, nullable=True),
    Column("shared_stock_count", Integer, nullable=True),
    Column("shared_stock_ratio", Float, nullable=True),
    Column("jaccard", Float, nullable=True),
    Column("price_correlation", Float, nullable=True),
    Column("fund_correlation", Float, nullable=True),
    Column("limit_up_cooccurrence", Float, nullable=True),
    Column("keyword_similarity", Float, nullable=True),
    Column("leader_overlap", Float, nullable=True),
    Column("evidence", JSONB, nullable=True),
    Column("confidence", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "as_of_date", "period", "source_sector_id", "target_sector_id",
        name="uq_sector_relation_edge",
    ),
)
Index("ix_sector_relation_edges_date", sector_relation_edges.c.as_of_date)
Index("ix_sector_relation_edges_source", sector_relation_edges.c.source_sector_id)
Index("ix_sector_relation_edges_target", sector_relation_edges.c.target_sector_id)

# ── Dynamic industry chain (entity extraction + relationship scoring) ──

industry_chain_nodes = Table(
    "industry_chain_nodes",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("as_of_date", Date, nullable=True),
    Column("name", String(160), nullable=False),
    Column("node_type", String(40), nullable=True),
    Column("stage", String(40), nullable=True),
    Column("sector_id", String(64), ForeignKey("sectors.id", ondelete="SET NULL"), nullable=True),
    Column("vt_symbol", String(32), nullable=True),
    Column("keywords", JSONB, nullable=True),
    Column("metrics", JSONB, nullable=True),
    Column("evidence", JSONB, nullable=True),
    Column("confidence", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_industry_chain_nodes_stage", industry_chain_nodes.c.stage)
Index("ix_industry_chain_nodes_sector_id", industry_chain_nodes.c.sector_id)

# ── Stock financial reports ──

stock_financial_reports = Table(
    "stock_financial_reports",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("report_date", String(20), primary_key=True),
    Column("period_type", String(20), primary_key=True),
    Column("publish_date", String(20), nullable=True),
    Column("revenue", Float, nullable=True),
    Column("revenue_yoy", Float, nullable=True),
    Column("revenue_qoq", Float, nullable=True),
    Column("net_profit", Float, nullable=True),
    Column("net_profit_yoy", Float, nullable=True),
    Column("net_profit_qoq", Float, nullable=True),
    Column("deducted_net_profit", Float, nullable=True),
    Column("eps", Float, nullable=True),
    Column("gross_margin", Float, nullable=True),
    Column("net_margin", Float, nullable=True),
    Column("roe", Float, nullable=True),
    Column("debt_asset_ratio", Float, nullable=True),
    Column("operating_cash_flow", Float, nullable=True),
    Column("cash_flow_quality", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_financial_reports_date", stock_financial_reports.c.report_date)

stock_financial_statement_items = Table(
    "stock_financial_statement_items",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("report_date", String(20), primary_key=True),
    Column("statement_type", String(40), primary_key=True),
    Column("item_code", String(80), nullable=True),
    Column("item_name", String(160), primary_key=True),
    Column("value", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_financial_stmt_items_date", stock_financial_statement_items.c.report_date)

# ── Stock events (news, notices, announcements) ──

stock_events = Table(
    "stock_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), nullable=False),
    Column("event_date", String(20), nullable=False),
    Column("event_type", String(40), nullable=False),
    Column("title", String(500), nullable=True),
    Column("summary", Text, nullable=True),
    Column("url", String(500), nullable=True),
    Column("keywords", JSONB, nullable=True),
    Column("sentiment", String(20), nullable=True),
    Column("importance", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_events_vt_symbol", stock_events.c.vt_symbol)
Index("ix_stock_events_date", stock_events.c.event_date)

# ── Stock fund flows ──

stock_fund_flows = Table(
    "stock_fund_flows",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", String(20), primary_key=True),
    Column("period", String(20), primary_key=True),
    Column("main_net_inflow", Float, nullable=True),
    Column("main_net_inflow_ratio", Float, nullable=True),
    Column("super_large_net_inflow", Float, nullable=True),
    Column("large_net_inflow", Float, nullable=True),
    Column("medium_net_inflow", Float, nullable=True),
    Column("small_net_inflow", Float, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_fund_flows_date", stock_fund_flows.c.trade_date)

# ── Sector fund flows ──

sector_fund_flows = Table(
    "sector_fund_flows",
    metadata,
    Column("sector_id", String(64), ForeignKey("sectors.id", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", String(20), primary_key=True),
    Column("period", String(20), primary_key=True),
    Column("main_net_inflow", Float, nullable=True),
    Column("main_net_inflow_ratio", Float, nullable=True),
    Column("rank", Integer, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_sector_fund_flows_date", sector_fund_flows.c.trade_date)

# ── Stock hot ranks ──

stock_hot_ranks = Table(
    "stock_hot_ranks",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("rank_time", String(30), primary_key=True),
    Column("rank", Integer, nullable=True),
    Column("rank_change", Float, nullable=True),
    Column("keywords", JSONB, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint("vt_symbol", "rank_time", "source", name="uq_stock_hot_rank"),
)
Index("ix_stock_hot_ranks_time", stock_hot_ranks.c.rank_time)

# ── Stock dragon-tiger board (龙虎榜) records ──

stock_lhb_records = Table(
    "stock_lhb_records",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", String(20), primary_key=True),
    Column("reason", String(200), primary_key=True),
    Column("buy_amount", Float, nullable=True),
    Column("sell_amount", Float, nullable=True),
    Column("net_amount", Float, nullable=True),
    Column("departments", JSONB, nullable=True),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_stock_lhb_records_date", stock_lhb_records.c.trade_date)


# ── Quant strategy, backtest, portfolio, simulation ──

quant_strategy_templates = Table(
    "quant_strategy_templates",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("strategy_type", String(60), nullable=False),
    Column("version", String(40), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("description", Text, nullable=True),
    Column("params", JSONB, nullable=False, server_default="{}"),
    Column("source", String(160), nullable=False, server_default="alphaagent.quant"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_quant_strategy_templates_type", quant_strategy_templates.c.strategy_type)

quant_signal_runs = Table(
    "quant_signal_runs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("strategy_id", String(80), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("trade_date", Date, nullable=False),
    Column("status", String(40), nullable=False),
    Column("params", JSONB, nullable=False, server_default="{}"),
    Column("candidate_count", Integer, nullable=False, server_default="0"),
    Column("signal_count", Integer, nullable=False, server_default="0"),
    Column("recommendation_count", Integer, nullable=False, server_default="0"),
    Column("message", Text, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
)
Index("ix_quant_signal_runs_date", quant_signal_runs.c.trade_date)
Index("ix_quant_signal_runs_strategy", quant_signal_runs.c.strategy_id)

quant_stock_signals = Table(
    "quant_stock_signals",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("run_id", BigInteger, ForeignKey("quant_signal_runs.id", ondelete="CASCADE"), nullable=True),
    Column("trade_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("strategy_id", String(80), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("signal_type", String(80), nullable=False),
    Column("total_score", Float, nullable=True),
    Column("relative_strength_score", Float, nullable=True),
    Column("washout_score", Float, nullable=True),
    Column("trend_quality_score", Float, nullable=True),
    Column("sector_mainline_score", Float, nullable=True),
    Column("financial_improvement_score", Float, nullable=True),
    Column("liquidity_score", Float, nullable=True),
    Column("risk_score", Float, nullable=True),
    Column("entry_signal", Boolean, nullable=False, server_default="false"),
    Column("risk_level", String(20), nullable=True),
    Column("evidence", JSONB, nullable=True),
    Column("source", String(160), nullable=False, server_default="alphaagent.quant.signal"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("trade_date", "vt_symbol", "strategy_id", "strategy_version", name="uq_quant_stock_signal"),
)
Index("ix_quant_stock_signals_date", quant_stock_signals.c.trade_date)
Index("ix_quant_stock_signals_vt_symbol", quant_stock_signals.c.vt_symbol)

quant_recommendations = Table(
    "quant_recommendations",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("run_id", BigInteger, ForeignKey("quant_signal_runs.id", ondelete="CASCADE"), nullable=True),
    Column("trade_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("strategy_id", String(80), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("rank", Integer, nullable=False),
    Column("action", String(40), nullable=False),
    Column("horizon", String(40), nullable=False),
    Column("confidence", Float, nullable=True),
    Column("total_score", Float, nullable=True),
    Column("reason", JSONB, nullable=True),
    Column("risk_control", JSONB, nullable=True),
    Column("status", String(40), nullable=False, server_default="active"),
    Column("expires_at", Date, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("trade_date", "vt_symbol", "strategy_id", "strategy_version", name="uq_quant_recommendation"),
)
Index("ix_quant_recommendations_date", quant_recommendations.c.trade_date)
Index("ix_quant_recommendations_vt_symbol", quant_recommendations.c.vt_symbol)

quant_tail_preview_cache = Table(
    "quant_tail_preview_cache",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("strategy_id", String(80), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("status", String(40), nullable=False),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("source_schedule_id", String(80), nullable=True),
    Column("base_daily_date", Date, nullable=True),
    Column("latest_daily_date", Date, nullable=True),
    Column("recommendation_count", Integer, nullable=False, server_default="0"),
    Column("total", Integer, nullable=False, server_default="0"),
    Column("generated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint("trade_date", "strategy_id", "strategy_version", name="uq_quant_tail_preview_cache"),
)
Index("ix_quant_tail_preview_cache_date", quant_tail_preview_cache.c.trade_date)
Index("ix_quant_tail_preview_cache_strategy", quant_tail_preview_cache.c.strategy_id)

backtest_runs = Table(
    "backtest_runs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("strategy_id", String(80), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
    Column("status", String(40), nullable=False),
    Column("initial_cash", Float, nullable=False),
    Column("final_equity", Float, nullable=True),
    Column("params", JSONB, nullable=False, server_default="{}"),
    Column("metrics", JSONB, nullable=True),
    Column("message", Text, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
)
Index("ix_backtest_runs_strategy", backtest_runs.c.strategy_id)

backtest_orders = Table(
    "backtest_orders",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("backtest_id", BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
    Column("trade_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("side", String(20), nullable=False),
    Column("price", Float, nullable=True),
    Column("volume", Integer, nullable=True),
    Column("status", String(40), nullable=False),
    Column("reason", String(240), nullable=True),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_backtest_orders_run", backtest_orders.c.backtest_id)

backtest_trades = Table(
    "backtest_trades",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("backtest_id", BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
    Column("trade_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("side", String(20), nullable=False),
    Column("price", Float, nullable=False),
    Column("volume", Integer, nullable=False),
    Column("amount", Float, nullable=False),
    Column("fee", Float, nullable=False),
    Column("pnl", Float, nullable=True),
    Column("reason", String(240), nullable=True),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_backtest_trades_run", backtest_trades.c.backtest_id)
Index("ix_backtest_trades_vt_symbol", backtest_trades.c.vt_symbol)

backtest_signal_events = Table(
    "backtest_signal_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("backtest_id", BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
    Column("trade_date", Date, nullable=False),
    Column("signal_date", Date, nullable=False),
    Column("execute_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("side", String(20), nullable=False),
    Column("price", Float, nullable=True),
    Column("score", Float, nullable=True),
    Column("reason", String(240), nullable=True),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_backtest_signal_events_run_date", backtest_signal_events.c.backtest_id, backtest_signal_events.c.trade_date)
Index("ix_backtest_signal_events_symbol", backtest_signal_events.c.backtest_id, backtest_signal_events.c.vt_symbol)

backtest_factor_snapshots = Table(
    "backtest_factor_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("backtest_id", BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
    Column("trade_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("rank", Integer, nullable=True),
    Column("entry_family", String(64), nullable=True),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("backtest_id", "trade_date", "vt_symbol", "rank", name="uq_backtest_factor_snapshot"),
)
Index("ix_backtest_factor_snapshots_run_date", backtest_factor_snapshots.c.backtest_id, backtest_factor_snapshots.c.trade_date)
Index("ix_backtest_factor_snapshots_symbol", backtest_factor_snapshots.c.backtest_id, backtest_factor_snapshots.c.vt_symbol)

backtest_factor_outcomes = Table(
    "backtest_factor_outcomes",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("backtest_id", BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False),
    Column("signal_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("rank", Integer, nullable=True),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("backtest_id", "signal_date", "vt_symbol", "rank", name="uq_backtest_factor_outcome"),
)
Index("ix_backtest_factor_outcomes_run_date", backtest_factor_outcomes.c.backtest_id, backtest_factor_outcomes.c.signal_date)
Index("ix_backtest_factor_outcomes_symbol", backtest_factor_outcomes.c.backtest_id, backtest_factor_outcomes.c.vt_symbol)

backtest_daily_equity = Table(
    "backtest_daily_equity",
    metadata,
    Column("backtest_id", BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", Date, primary_key=True),
    Column("cash", Float, nullable=False),
    Column("market_value", Float, nullable=False),
    Column("total_equity", Float, nullable=False),
    Column("drawdown_pct", Float, nullable=True),
    Column("position_count", Integer, nullable=False, server_default="0"),
)
Index("ix_backtest_daily_equity_date", backtest_daily_equity.c.trade_date)

backtest_daily_positions = Table(
    "backtest_daily_positions",
    metadata,
    Column("backtest_id", BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", Date, primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("name", String(80), nullable=True),
    Column("volume", Integer, nullable=False),
    Column("cost_price", Float, nullable=False),
    Column("close_price", Float, nullable=True),
    Column("market_value", Float, nullable=False),
    Column("floating_pnl", Float, nullable=True),
    Column("floating_pnl_pct", Float, nullable=True),
    Column("weight_pct", Float, nullable=True),
    Column("entry_date", Date, nullable=False),
    Column("holding_days", Integer, nullable=False, server_default="0"),
    Column("highest_price", Float, nullable=True),
    Column("raw", JSONB, nullable=False, server_default="{}"),
)
Index("ix_backtest_daily_positions_date", backtest_daily_positions.c.backtest_id, backtest_daily_positions.c.trade_date)
Index("ix_backtest_daily_positions_symbol", backtest_daily_positions.c.backtest_id, backtest_daily_positions.c.vt_symbol)

backtest_metrics = Table(
    "backtest_metrics",
    metadata,
    Column("backtest_id", BigInteger, ForeignKey("backtest_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("metric_key", String(80), primary_key=True),
    Column("metric_value", Float, nullable=True),
    Column("metric_text", Text, nullable=True),
    Column("raw", JSONB, nullable=True),
)

strategy_replay_runs = Table(
    "strategy_replay_runs",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("strategy_id", String(80), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("start_date", Date, nullable=False),
    Column("end_date", Date, nullable=False),
    Column("status", String(40), nullable=False),
    Column("params", JSONB, nullable=False, server_default="{}"),
    Column("metrics", JSONB, nullable=True),
    Column("message", Text, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finished_at", DateTime(timezone=True), nullable=True),
)
Index("ix_strategy_replay_runs_strategy", strategy_replay_runs.c.strategy_id)
Index("ix_strategy_replay_runs_date", strategy_replay_runs.c.start_date, strategy_replay_runs.c.end_date)

strategy_replay_attempts = Table(
    "strategy_replay_attempts",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("replay_run_id", BigInteger, ForeignKey("strategy_replay_runs.id", ondelete="CASCADE"), nullable=False),
    Column("signal_run_id", BigInteger, ForeignKey("quant_signal_runs.id", ondelete="SET NULL"), nullable=True),
    Column("signal_date", Date, nullable=False),
    Column("execute_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("side", String(20), nullable=False),
    Column("signal_type", String(80), nullable=True),
    Column("plan_status", String(40), nullable=False),
    Column("execution_status", String(40), nullable=False),
    Column("price", Float, nullable=True),
    Column("price_source", String(160), nullable=True),
    Column("proxy_used", Boolean, nullable=False, server_default="false"),
    Column("reject_reason", String(240), nullable=True),
    Column("score", Float, nullable=True),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "replay_run_id",
        "signal_date",
        "execute_date",
        "vt_symbol",
        "side",
        "signal_type",
        name="uq_strategy_replay_attempt",
    ),
)
Index("ix_strategy_replay_attempts_run_symbol", strategy_replay_attempts.c.replay_run_id, strategy_replay_attempts.c.vt_symbol)
Index("ix_strategy_replay_attempts_signal_date", strategy_replay_attempts.c.replay_run_id, strategy_replay_attempts.c.signal_date)
Index("ix_strategy_replay_attempts_execute_date", strategy_replay_attempts.c.replay_run_id, strategy_replay_attempts.c.execute_date)

portfolio_groups = Table(
    "portfolio_groups",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("name", String(120), nullable=False),
    Column("group_type", String(40), nullable=False),
    Column("description", Text, nullable=True),
    Column("auto_managed", Boolean, nullable=False, server_default="false"),
    Column("risk_profile", String(40), nullable=False, server_default="balanced"),
    Column("sort_order", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint("name", name="uq_portfolio_group_name"),
)

portfolio_group_items = Table(
    "portfolio_group_items",
    metadata,
    Column("group_id", BigInteger, ForeignKey("portfolio_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("name", String(80), nullable=True),
    Column("source", String(40), nullable=False, server_default="manual"),
    Column("reason", Text, nullable=True),
    Column("strategy_id", String(80), nullable=True),
    Column("strategy_version", String(40), nullable=True),
    Column("expires_at", Date, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_portfolio_group_items_symbol", portfolio_group_items.c.vt_symbol)

simulation_accounts = Table(
    "simulation_accounts",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("name", String(120), nullable=False),
    Column("initial_cash", Float, nullable=False),
    Column("cash", Float, nullable=False),
    Column("status", String(40), nullable=False, server_default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)

simulation_orders = Table(
    "simulation_orders",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("account_id", BigInteger, ForeignKey("simulation_accounts.id", ondelete="CASCADE"), nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("side", String(20), nullable=False),
    Column("price", Float, nullable=True),
    Column("volume", Integer, nullable=True),
    Column("amount", Float, nullable=True),
    Column("status", String(40), nullable=False),
    Column("reason", Text, nullable=True),
    Column("recommendation_id", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index("ix_simulation_orders_account", simulation_orders.c.account_id)

simulation_trades = Table(
    "simulation_trades",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("account_id", BigInteger, ForeignKey("simulation_accounts.id", ondelete="CASCADE"), nullable=False),
    Column("order_id", BigInteger, ForeignKey("simulation_orders.id", ondelete="SET NULL"), nullable=True),
    Column("vt_symbol", String(32), nullable=False),
    Column("side", String(20), nullable=False),
    Column("price", Float, nullable=False),
    Column("volume", Integer, nullable=False),
    Column("amount", Float, nullable=False),
    Column("fee", Float, nullable=False),
    Column("pnl", Float, nullable=True),
    Column("trade_time", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_simulation_trades_account", simulation_trades.c.account_id)

simulation_positions = Table(
    "simulation_positions",
    metadata,
    Column("account_id", BigInteger, ForeignKey("simulation_accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("name", String(80), nullable=True),
    Column("volume", Integer, nullable=False),
    Column("available", Integer, nullable=False),
    Column("cost_price", Float, nullable=False),
    Column("last_price", Float, nullable=True),
    Column("market_value", Float, nullable=True),
    Column("floating_pnl", Float, nullable=True),
    Column("floating_pnl_pct", Float, nullable=True),
    Column("stop_loss_price", Float, nullable=True),
    Column("take_profit_price", Float, nullable=True),
    Column("trailing_stop_price", Float, nullable=True),
    Column("source", String(40), nullable=False, server_default="manual"),
    Column("reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)

risk_events = Table(
    "risk_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("account_id", BigInteger, ForeignKey("simulation_accounts.id", ondelete="CASCADE"), nullable=True),
    Column("vt_symbol", String(32), nullable=True),
    Column("event_type", String(80), nullable=False),
    Column("severity", String(20), nullable=False),
    Column("message", Text, nullable=False),
    Column("context", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index("ix_risk_events_account", risk_events.c.account_id)


def create_schema(engine) -> None:
    """Create all AlphaAgent sync tables when they are missing."""

    metadata.create_all(engine)
    _apply_compatible_schema_patches(engine)


def ensure_schema_once(engine) -> None:
    """Create/patch schema once per API process.

    Several read endpoints call service-level schema bootstrapping so they can
    also run from tests and direct service calls. Without this process-local
    guard, frequent frontend polling repeatedly issues idempotent DDL and can
    take relation locks while long quant research jobs are writing candidates.
    """

    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        create_schema(engine)
        _SCHEMA_READY = True


def _apply_compatible_schema_patches(engine) -> None:
    """Patch columns added after early local databases were created."""

    patches = (
        "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS volume_ratio FLOAT",
        "ALTER TABLE sync_batch_schedules ADD COLUMN IF NOT EXISTS action VARCHAR(40) NOT NULL DEFAULT 'sync'",
        """
        CREATE TABLE IF NOT EXISTS quant_tail_preview_cache (
            id BIGSERIAL PRIMARY KEY,
            trade_date DATE NOT NULL,
            strategy_id VARCHAR(80) NOT NULL,
            strategy_version VARCHAR(40) NOT NULL,
            status VARCHAR(40) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            source_schedule_id VARCHAR(80),
            base_daily_date DATE,
            latest_daily_date DATE,
            recommendation_count INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_quant_tail_preview_cache UNIQUE (trade_date, strategy_id, strategy_version)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_quant_tail_preview_cache_date ON quant_tail_preview_cache (trade_date)",
        "CREATE INDEX IF NOT EXISTS ix_quant_tail_preview_cache_strategy ON quant_tail_preview_cache (strategy_id)",
    )
    for sql in patches:
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL lock_timeout = '1500ms'")
                connection.exec_driver_sql(sql)
        except Exception as exc:
            if not _is_schema_patch_lock_timeout(exc):
                raise
            logger.warning("compatible schema patch skipped: %s", exc.__class__.__name__)


def _is_schema_patch_lock_timeout(exc: Exception) -> bool:
    orig = getattr(exc, "orig", None)
    pgcode = str(getattr(orig, "pgcode", "") or getattr(orig, "sqlstate", "") or "")
    if pgcode == "55P03":
        return True
    message = str(exc).lower()
    return isinstance(exc, TimeoutError) or "lock timeout" in message or "lock not available" in message
