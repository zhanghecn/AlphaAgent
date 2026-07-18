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

from alphaagent.server.db.legacy_product_cleanup import drop_legacy_product_tables

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
    Column("turnover_rate", Float, nullable=True),
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

low_suction_concept_membership_history = Table(
    "low_suction_concept_membership_history",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("sector_id", String(64), nullable=False),
    Column("sector_name", String(160), nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("in_date", Date, nullable=False),
    Column("out_date", Date, nullable=False),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_record_id", String(240), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "source",
        "source_record_id",
        name="uq_low_suction_membership_source_record",
    ),
)
Index(
    "ix_low_suction_membership_sector_validity",
    low_suction_concept_membership_history.c.sector_id,
    low_suction_concept_membership_history.c.in_date,
    low_suction_concept_membership_history.c.out_date,
)
Index(
    "ix_low_suction_membership_symbol_validity",
    low_suction_concept_membership_history.c.vt_symbol,
    low_suction_concept_membership_history.c.in_date,
    low_suction_concept_membership_history.c.out_date,
)

low_suction_concept_membership_scopes = Table(
    "low_suction_concept_membership_scopes",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("source_trade_date", Date, nullable=False),
    Column("sector_id", String(64), nullable=False),
    Column("expected_member_count", Integer, nullable=False),
    Column("returned_member_count", Integer, nullable=False),
    Column("pagination_complete", Boolean, nullable=False),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_request_id", String(240), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "source",
        "trade_date",
        "sector_id",
        name="uq_low_suction_membership_scope_pair",
    ),
    UniqueConstraint(
        "source",
        "source_request_id",
        name="uq_low_suction_membership_scope_request",
    ),
)
Index(
    "ix_low_suction_membership_scope_evidence_date",
    low_suction_concept_membership_scopes.c.evidence_level,
    low_suction_concept_membership_scopes.c.trade_date,
)
Index(
    "ix_low_suction_membership_scope_sector_date",
    low_suction_concept_membership_scopes.c.sector_id,
    low_suction_concept_membership_scopes.c.trade_date,
)

low_suction_security_history = Table(
    "low_suction_security_history",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("vt_symbol", String(32), nullable=False),
    Column("symbol", String(16), nullable=False),
    Column("exchange", String(16), nullable=False),
    Column("name", String(80), nullable=False),
    Column("status", String(32), nullable=False),
    Column("board", String(32), nullable=False),
    Column("listed_on", Date, nullable=False),
    Column("delisted_on", Date, nullable=True),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date, nullable=False),
    Column("suspended", Boolean, nullable=False),
    Column("risk_warning", Boolean, nullable=False),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_record_id", String(240), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "source",
        "source_record_id",
        name="uq_low_suction_security_source_record",
    ),
)
Index(
    "ix_low_suction_security_symbol_validity",
    low_suction_security_history.c.vt_symbol,
    low_suction_security_history.c.valid_from,
    low_suction_security_history.c.valid_to,
)
Index(
    "ix_low_suction_security_evidence_date",
    low_suction_security_history.c.evidence_level,
    low_suction_security_history.c.valid_from,
)
Index(
    "ix_low_suction_security_delisted_on",
    low_suction_security_history.c.delisted_on,
)

low_suction_security_history_scopes = Table(
    "low_suction_security_history_scopes",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "source",
        "trade_date",
        "vt_symbol",
        name="uq_low_suction_security_scope_pair",
    ),
)
Index(
    "ix_low_suction_security_scope_evidence_date",
    low_suction_security_history_scopes.c.evidence_level,
    low_suction_security_history_scopes.c.trade_date,
)
Index(
    "ix_low_suction_security_scope_symbol_date",
    low_suction_security_history_scopes.c.vt_symbol,
    low_suction_security_history_scopes.c.trade_date,
)

low_suction_security_snapshots = Table(
    "low_suction_security_snapshots",
    metadata,
    Column("source_trade_date", Date, primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("source", String(160), primary_key=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("symbol", String(16), nullable=False),
    Column("exchange", String(16), nullable=False),
    Column("name", String(80), nullable=False),
    Column("status", String(32), nullable=False),
    Column("board", String(32), nullable=False),
    Column("listed_on", Date, nullable=False),
    Column("delisted_on", Date, nullable=True),
    Column("suspended", Boolean, nullable=False),
    Column("risk_warning", Boolean, nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source_record_id", String(240), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_low_suction_security_snapshots_symbol_date",
    low_suction_security_snapshots.c.vt_symbol,
    low_suction_security_snapshots.c.source_trade_date,
)
Index(
    "ix_low_suction_security_snapshots_evidence_date",
    low_suction_security_snapshots.c.evidence_level,
    low_suction_security_snapshots.c.source_trade_date,
)

low_suction_security_snapshot_scopes = Table(
    "low_suction_security_snapshot_scopes",
    metadata,
    Column("source_trade_date", Date, primary_key=True),
    Column("source", String(160), primary_key=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("expected_symbol_count", Integer, nullable=False),
    Column("returned_symbol_count", Integer, nullable=False),
    Column("total_master_rows", Integer, nullable=False),
    Column("total_daily_rows", Integer, nullable=False),
    Column("suspended_count", Integer, nullable=False),
    Column("risk_warning_count", Integer, nullable=False),
    Column("complete", Boolean, nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_low_suction_security_snapshot_scope_evidence_date",
    low_suction_security_snapshot_scopes.c.evidence_level,
    low_suction_security_snapshot_scopes.c.source_trade_date,
)

low_suction_forward_membership_snapshots = Table(
    "low_suction_forward_membership_snapshots",
    metadata,
    Column("source_trade_date", Date, primary_key=True),
    Column("sector_id", String(64), primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("source", String(160), primary_key=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("sector_name", String(160), nullable=False),
    Column("sector_type", String(40), nullable=False),
    Column("manifest_class", String(40), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_low_suction_forward_membership_symbol_date",
    low_suction_forward_membership_snapshots.c.vt_symbol,
    low_suction_forward_membership_snapshots.c.source_trade_date,
)
Index(
    "ix_low_suction_forward_membership_sector_date",
    low_suction_forward_membership_snapshots.c.sector_id,
    low_suction_forward_membership_snapshots.c.source_trade_date,
)

low_suction_forward_membership_snapshot_scopes = Table(
    "low_suction_forward_membership_snapshot_scopes",
    metadata,
    Column("source_trade_date", Date, primary_key=True),
    Column("scope_type", String(32), primary_key=True),
    Column("source", String(160), primary_key=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("expected_sector_count", Integer, nullable=False),
    Column("returned_sector_count", Integer, nullable=False),
    Column("row_count", Integer, nullable=False),
    Column("symbol_count", Integer, nullable=False),
    Column("complete", Boolean, nullable=False),
    Column("evidence_level", String(40), nullable=False),
    Column("manifest_version", String(120), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_low_suction_forward_membership_scope_evidence_date",
    low_suction_forward_membership_snapshot_scopes.c.evidence_level,
    low_suction_forward_membership_snapshot_scopes.c.source_trade_date,
)

low_suction_forward_leader_rank_snapshots = Table(
    "low_suction_forward_leader_rank_snapshots",
    metadata,
    Column("source_trade_date", Date, primary_key=True),
    Column("ranking_version", String(80), primary_key=True),
    Column("identity_mode", String(64), primary_key=True),
    Column("sector_id", String(64), primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("target_session", String(40), nullable=False),
    Column("target_trade_date", Date, nullable=True),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("feature_cutoff", DateTime(timezone=True), nullable=False),
    Column("membership_known_at", DateTime(timezone=True), nullable=False),
    Column("security_known_at", DateTime(timezone=True), nullable=False),
    Column("sector_name", String(160), nullable=False),
    Column("cycle_id", String(240), nullable=False),
    Column("cycle_start", Date, nullable=False),
    Column("cycle_days", Integer, nullable=False),
    Column("cycle_relative_return", Float, nullable=True),
    Column("strong_day_count_cycle", Integer, nullable=True),
    Column("sessions_since_strong", Integer, nullable=True),
    Column("turnover_median_20d", Float, nullable=True),
    Column("capacity_passed", Boolean, nullable=False),
    Column("relative_strength_rank", Integer, nullable=True),
    Column("market_recognition_rank", Integer, nullable=True),
    Column("rank", Integer, nullable=True),
    Column("rank_eligible", Boolean, nullable=False),
    Column("is_top3", Boolean, nullable=False),
    Column("excluded_reason", String(80), nullable=True),
    Column("input_fingerprint", String(80), nullable=False),
    Column("evidence_level", String(40), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_low_suction_forward_leader_target_mode_top3",
    low_suction_forward_leader_rank_snapshots.c.target_trade_date,
    low_suction_forward_leader_rank_snapshots.c.identity_mode,
    low_suction_forward_leader_rank_snapshots.c.is_top3,
)
Index(
    "ix_low_suction_forward_leader_symbol_source",
    low_suction_forward_leader_rank_snapshots.c.vt_symbol,
    low_suction_forward_leader_rank_snapshots.c.source_trade_date,
)

low_suction_forward_leader_rank_snapshot_scopes = Table(
    "low_suction_forward_leader_rank_snapshot_scopes",
    metadata,
    Column("source_trade_date", Date, primary_key=True),
    Column("ranking_version", String(80), primary_key=True),
    Column("identity_mode", String(64), primary_key=True),
    Column("target_session", String(40), nullable=False),
    Column("target_trade_date", Date, nullable=True),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("feature_cutoff", DateTime(timezone=True), nullable=False),
    Column("main_rise_definition", String(64), nullable=False),
    Column("active_concept_count", Integer, nullable=False),
    Column("membership_row_count", Integer, nullable=False),
    Column("main_board_member_count", Integer, nullable=False),
    Column("security_eligible_count", Integer, nullable=False),
    Column("ranked_row_count", Integer, nullable=False),
    Column("top3_row_count", Integer, nullable=False),
    Column("excluded_row_count", Integer, nullable=False),
    Column("complete", Boolean, nullable=False),
    Column("status", String(40), nullable=False),
    Column("input_fingerprint", String(80), nullable=False),
    Column("selected_mode", String(64), nullable=True),
    Column("evidence_level", String(40), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_low_suction_forward_leader_scope_complete_source",
    low_suction_forward_leader_rank_snapshot_scopes.c.complete,
    low_suction_forward_leader_rank_snapshot_scopes.c.source_trade_date,
)

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

stock_sector_membership_snapshots = Table(
    "stock_sector_membership_snapshots",
    metadata,
    Column("snapshot_date", Date, primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("sector_id", String(64), primary_key=True),
    Column("captured_at", DateTime(timezone=True), nullable=False),
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
Index(
    "ix_stock_sector_membership_snapshots_symbol_date",
    stock_sector_membership_snapshots.c.vt_symbol,
    stock_sector_membership_snapshots.c.snapshot_date,
)
Index(
    "ix_stock_sector_membership_snapshots_sector_date",
    stock_sector_membership_snapshots.c.sector_id,
    stock_sector_membership_snapshots.c.snapshot_date,
)

stock_sector_membership_snapshot_scopes = Table(
    "stock_sector_membership_snapshot_scopes",
    metadata,
    Column("snapshot_date", Date, primary_key=True),
    Column("scope_type", String(24), primary_key=True),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("expected_sector_count", Integer, nullable=False),
    Column("captured_sector_count", Integer, nullable=False),
    Column("row_count", Integer, nullable=False),
    Column("symbol_count", Integer, nullable=False),
    Column("complete", Boolean, nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_stock_sector_membership_scope_evidence_date",
    stock_sector_membership_snapshot_scopes.c.evidence_level,
    stock_sector_membership_snapshot_scopes.c.snapshot_date,
)

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

stock_financial_sync_attempts = Table(
    "stock_financial_sync_attempts",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("status", String(20), nullable=False),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("last_error", Text, nullable=True),
    Column("last_attempt_at", DateTime(timezone=True), nullable=False),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_stock_financial_sync_attempts_retry",
    stock_financial_sync_attempts.c.next_retry_at,
    stock_financial_sync_attempts.c.last_attempt_at,
)

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


limit_up_signal_snapshots = Table(
    "limit_up_signal_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("captured_minute", DateTime(timezone=True), nullable=False),
    Column("session_stage", String(32), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("mode", String(32), nullable=False, server_default="live_snapshot"),
    Column("source", String(160), nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("market_context", JSONB, nullable=False, server_default="{}"),
    Column("candidates", JSONB, nullable=False, server_default="[]"),
    Column("recommendations", JSONB, nullable=False, server_default="{}"),
    Column("data_quality", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "trade_date",
        "captured_minute",
        "strategy_version",
        name="uq_limit_up_signal_snapshot_minute_version",
    ),
)
Index(
    "ix_limit_up_signal_snapshots_date_time",
    limit_up_signal_snapshots.c.trade_date,
    limit_up_signal_snapshots.c.captured_at,
)


limit_up_concept_strength_snapshots = Table(
    "limit_up_concept_strength_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("captured_minute", DateTime(timezone=True), nullable=False),
    Column("membership_snapshot_date", Date, nullable=False),
    Column("concept_id", String(64), nullable=False),
    Column("concept_name", String(160), nullable=False),
    Column("concept_state", String(32), nullable=False),
    Column("strength_score", Float, nullable=False),
    Column("strength_rank", Integer, nullable=False),
    Column("strength_percentile", Float, nullable=False),
    Column("coverage_ratio", Float, nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("is_stale", Boolean, nullable=False, server_default="false"),
    Column("metrics", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "trade_date",
        "concept_id",
        "captured_minute",
        name="uq_limit_up_concept_strength_minute",
    ),
)
Index(
    "ix_limit_up_concept_strength_date_time",
    limit_up_concept_strength_snapshots.c.trade_date,
    limit_up_concept_strength_snapshots.c.captured_at,
)


limit_up_live_trace_snapshots = Table(
    "limit_up_live_trace_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("source_trade_date", Date, nullable=True),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("session_stage", String(32), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("mode", String(32), nullable=False, server_default="live_trace"),
    Column("source", String(160), nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("market_context", JSONB, nullable=False, server_default="{}"),
    Column("radar_candidates", JSONB, nullable=False, server_default="[]"),
    Column("ranked_candidates", JSONB, nullable=False, server_default="[]"),
    Column("recommendations", JSONB, nullable=False, server_default="{}"),
    Column("data_quality", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index(
    "ix_limit_up_live_trace_date_time",
    limit_up_live_trace_snapshots.c.trade_date,
    limit_up_live_trace_snapshots.c.captured_at,
)
Index(
    "ix_limit_up_live_trace_version_date_time",
    limit_up_live_trace_snapshots.c.strategy_version,
    limit_up_live_trace_snapshots.c.trade_date,
    limit_up_live_trace_snapshots.c.captured_at,
)


limit_up_radar_frames = Table(
    "limit_up_radar_frames",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("contract_version", String(40), nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("source_trade_date", Date, nullable=True),
    Column("quality_status", String(24), nullable=False),
    Column("is_stale", Boolean, nullable=False),
    Column("capture_count", Integer, nullable=False),
    Column("scan_duration_ms", Integer, nullable=True),
    Column("quote_coverage_ratio", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "captured_at",
        "strategy_version",
        name="uq_limit_up_radar_frame_time_version",
    ),
)
Index(
    "ix_limit_up_radar_frames_date_time",
    limit_up_radar_frames.c.trade_date,
    limit_up_radar_frames.c.captured_at,
)


limit_up_radar_observations = Table(
    "limit_up_radar_observations",
    metadata,
    Column(
        "frame_id",
        BigInteger,
        ForeignKey("limit_up_radar_frames.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "vt_symbol",
        String(32),
        ForeignKey("stocks.vt_symbol", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("name", String(80), nullable=False),
    Column("change_pct", Float, nullable=False),
    Column("last_price", Float, nullable=False),
    Column("previous_close", Float, nullable=False),
    Column("limit_price", Float, nullable=False),
    Column("capture_state", String(24), nullable=False),
    Column("board_lane", String(24), nullable=False),
    Column("support_score", Float, nullable=True),
    Column("entry_quality_score", Float, nullable=True),
    Column("concept_id", String(64), nullable=True),
    Column("concept_state", String(24), nullable=True),
    Column("concept_strength_score", Float, nullable=True),
    Column("concept_leader_rank", Integer, nullable=True),
    Column("concept_strong_5_count", Integer, nullable=True),
    Column("sector_id", String(64), nullable=True),
    Column("sector_heat", Float, nullable=True),
    Column("sector_touch_count", Integer, nullable=True),
    Column("history_sample_count", Integer, nullable=True),
    Column("historical_combined_rate", Float, nullable=True),
    Column("formal_action", String(24), nullable=False),
    Column("early_action", String(24), nullable=False),
    Column("early_entry_kind", String(24), nullable=False),
    Column("blocking_scope", String(24), nullable=False),
    Column("decision_reason", String(500), nullable=True),
    Column("blocker_codes", JSONB, nullable=False, server_default="[]"),
)
Index(
    "ix_limit_up_radar_observations_symbol_frame",
    limit_up_radar_observations.c.vt_symbol,
    limit_up_radar_observations.c.frame_id,
)


limit_up_history_replays = Table(
    "limit_up_history_replays",
    metadata,
    Column("trade_date", Date, primary_key=True),
    Column("strategy_version", String(40), primary_key=True),
    Column("source_mode", String(40), nullable=False, server_default="daily_point_in_time"),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("coverage", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_limit_up_history_replays_version_date",
    limit_up_history_replays.c.strategy_version,
    limit_up_history_replays.c.trade_date,
)


limit_up_minute_backfill_attempts = Table(
    "limit_up_minute_backfill_attempts",
    metadata,
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("trade_date", Date, primary_key=True),
    Column("provider", String(40), primary_key=True),
    Column("status", String(20), nullable=False),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("last_rows_read", Integer, nullable=False, server_default="0"),
    Column("last_error", Text, nullable=True),
    Column("last_attempt_at", DateTime(timezone=True), nullable=False),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_limit_up_minute_backfill_attempts_retry",
    limit_up_minute_backfill_attempts.c.provider,
    limit_up_minute_backfill_attempts.c.next_retry_at,
)

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

sector_fund_flow_snapshots = Table(
    "sector_fund_flow_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("captured_minute", DateTime(timezone=True), nullable=False),
    Column("session_stage", String(32), nullable=False),
    Column("sector_id", String(64), nullable=False),
    Column("sector_name", String(160), nullable=False),
    Column("sector_type", String(40), nullable=False),
    Column("period", String(20), nullable=False),
    Column("change_pct", Float, nullable=True),
    Column("main_net_inflow", Float, nullable=True),
    Column("main_net_inflow_ratio", Float, nullable=True),
    Column("super_large_net_inflow", Float, nullable=True),
    Column("large_net_inflow", Float, nullable=True),
    Column("medium_net_inflow", Float, nullable=True),
    Column("small_net_inflow", Float, nullable=True),
    Column("rank", Integer, nullable=True),
    Column("rise_count", Integer, nullable=True),
    Column("fall_count", Integer, nullable=True),
    Column("flat_count", Integer, nullable=True),
    Column("rise_ratio", Float, nullable=True),
    Column("leader_stock", String(120), nullable=True),
    Column("leader_stock_code", String(32), nullable=True),
    Column("source", String(160), nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("is_stale", Boolean, nullable=False, server_default="false"),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "trade_date",
        "sector_id",
        "period",
        "captured_minute",
        name="uq_sector_fund_flow_snapshot_minute",
    ),
)
Index(
    "ix_sector_fund_flow_snapshots_date_time",
    sector_fund_flow_snapshots.c.trade_date,
    sector_fund_flow_snapshots.c.captured_at,
)
Index(
    "ix_sector_fund_flow_snapshots_sector_time",
    sector_fund_flow_snapshots.c.sector_id,
    sector_fund_flow_snapshots.c.captured_at,
)

stock_auction_snapshots = Table(
    "stock_auction_snapshots",
    metadata,
    Column("trade_date", Date, primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("symbol", String(16), nullable=False),
    Column("exchange", String(16), nullable=False),
    Column("name", String(80), nullable=False),
    Column("auction_price", Float, nullable=True),
    Column("previous_close", Float, nullable=True),
    Column("auction_change_pct", Float, nullable=True),
    Column("matched_volume", Float, nullable=True),
    Column("matched_amount", Float, nullable=True),
    Column("unmatched_volume", Float, nullable=True),
    Column("unmatched_side", String(20), nullable=True),
    Column("auction_status", String(32), nullable=False),
    Column("source_quote_time", String(40), nullable=True),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("strict_complete", Boolean, nullable=False, server_default="false"),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
Index(
    "ix_stock_auction_snapshots_date_capture",
    stock_auction_snapshots.c.trade_date,
    stock_auction_snapshots.c.captured_at,
)
Index(
    "ix_stock_auction_snapshots_strict_date",
    stock_auction_snapshots.c.strict_complete,
    stock_auction_snapshots.c.trade_date,
)

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


market_timing_panel = Table(
    "market_timing_panel",
    metadata,
    Column("id", Integer, primary_key=True),  # 固定为 1: 单行存最新预计算面板
    Column("panel", JSONB, nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def create_schema(engine) -> None:
    """Create all AlphaAgent sync tables when they are missing."""

    drop_legacy_product_tables(engine)
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
        "ALTER TABLE stock_daily_bars ADD COLUMN IF NOT EXISTS turnover_rate FLOAT",
        "ALTER TABLE sync_batch_schedules ADD COLUMN IF NOT EXISTS action VARCHAR(40) NOT NULL DEFAULT 'sync'",
        "ALTER TABLE sector_fund_flow_snapshots ADD COLUMN IF NOT EXISTS rise_count INTEGER",
        "ALTER TABLE sector_fund_flow_snapshots ADD COLUMN IF NOT EXISTS fall_count INTEGER",
        "ALTER TABLE sector_fund_flow_snapshots ADD COLUMN IF NOT EXISTS flat_count INTEGER",
        "ALTER TABLE sector_fund_flow_snapshots ADD COLUMN IF NOT EXISTS rise_ratio FLOAT",
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
