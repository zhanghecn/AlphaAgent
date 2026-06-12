"""Data sync service — background sync jobs and local query helpers.

Manages scheduled and on-demand data synchronization from AkShare / EastMoney
public sources into PostgreSQL tables.  Also exposes *local_* query functions
that the API layer falls back to when live data is unavailable.

Key public symbols consumed elsewhere:
  - ensure_sync_schema, start_data_sync_scheduler  (main.py)
  - coverage, usage, list_sources, list_jobs, ...   (api/data_sync.py, health.py)
  - local_list_stocks, local_stock_bars, ...         (market/providers.py)
  - local_shenwan_industry_tree, ...                 (market/providers.py)
  - local_sector_relation_graph, local_sector_stub_graph (api/industry_chains.py)
"""

from __future__ import annotations

import logging
import threading
import time
import csv
import io
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Sequence
from uuid import uuid4

from sqlalchemy import desc, func, select, text
from sqlalchemy.engine import Engine

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.symbols import normalize_exchange, vt_symbol
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services import research_sector_scores

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALLOWED_IMPORT_DIRS = (
    PROJECT_ROOT / "data" / "imports",
    PROJECT_ROOT / "memory" / "06_backtests",
)

# ─── Source / Job constants ──────────────────────────────────────────────

DEFAULT_SOURCE: dict[str, dict[str, Any]] = {
    "akshare": {
        "id": "akshare",
        "name": "AkShare (东方财富/腾讯/新浪)",
        "kind": "akshare",
        "base_url": "",
        "enabled": True,
        "priority": 100,
    },
}


@dataclass(frozen=True)
class JobDefinition:
    """Immutable definition of a sync job."""

    id: str
    name: str
    description: str
    source_id: str
    target_table: str
    default_params: dict[str, Any] = field(default_factory=dict)
    schedule_cron: str | None = None
    enabled: bool = True


DEFAULT_JOBS: tuple[JobDefinition, ...] = (
    JobDefinition(
        id="sync_stock_list",
        name="全 A 股票清单",
        description="同步沪深北交所全部股票基础信息和最新行情快照。",
        source_id="akshare",
        target_table="stocks",
        default_params={"page_size": 200, "sort": "mktcap"},
        schedule_cron="30 8 * * 1-5",
    ),
    JobDefinition(
        id="sync_sector_list",
        name="板块 / 概念清单",
        description="同步行业板块、概念板块、主题板块列表。",
        source_id="akshare",
        target_table="sectors",
        default_params={"types": ["concept", "industry", "theme"]},
        schedule_cron="45 8 * * 1-5",
    ),
    JobDefinition(
        id="sync_sector_members",
        name="板块成分股",
        description="同步每个板块的成分股列表及实时行情。",
        source_id="akshare",
        target_table="sector_memberships",
        default_params={"page_size": 200},
        schedule_cron="0 9 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_daily_bars",
        name="股票日 K 线",
        description="增量同步全 A 股票日线行情 (OHLCV)。",
        source_id="akshare",
        target_table="stock_daily_bars",
        default_params={"limit": 250},
        schedule_cron="30 17 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_minute_bars",
        name="股票分钟 K 线",
        description="同步高流动性/候选股票最近分钟线，用于尾盘 5 日线低吸入场验证。",
        source_id="akshare",
        target_table="stock_minute_bars",
        default_params={"stock_limit": 100, "limit": 240, "interval": "1m", "only_missing": True},
        schedule_cron="5 15 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_sector_memberships",
        name="股票-板块反向索引",
        description="重建每只股票所属板块的反向索引。",
        source_id="akshare",
        target_table="stock_sector_memberships",
        default_params={},
        schedule_cron="0 10 * * 1-5",
    ),
    # ── Shenwan Industry Classification ──
    JobDefinition(
        id="sync_shenwan_industry_tree",
        name="申万行业分类树",
        description="同步申万一/二/三级行业分类。",
        source_id="akshare",
        target_table="shenwan_industries",
        default_params={"levels": [1, 2, 3]},
        schedule_cron="0 4 * * 1",
    ),
    JobDefinition(
        id="sync_shenwan_industry_members",
        name="申万行业成分股",
        description="同步三级行业成分股列表。",
        source_id="akshare",
        target_table="shenwan_industry_members",
        default_params={},
        schedule_cron="30 4 * * 1",
    ),
    JobDefinition(
        id="sync_industry_board_mapping",
        name="行业-板块映射",
        description="构建申万行业与东方财富板块的映射关系。",
        source_id="akshare",
        target_table="industry_board_mapping",
        default_params={},
        schedule_cron="0 5 * * 1",
    ),
    JobDefinition(
        id="sync_supply_chain_edges",
        name="供应链关系推断",
        description="基于主营构成交叉分析推断行业间供应链关系。",
        source_id="akshare",
        target_table="industry_chain_edges",
        default_params={"level": 2},
        schedule_cron="30 5 * * 1",
    ),
    # ── Research data: sector dashboard ──
    JobDefinition(
        id="sync_sector_daily_bars",
        name="板块历史 K 线",
        description="同步行业/概念板块历史日 K 线数据。",
        source_id="akshare",
        target_table="sector_daily_bars",
        default_params={"limit": 250},
        schedule_cron="0 18 * * 1-5",
    ),
    JobDefinition(
        id="sync_sector_fund_flows",
        name="板块资金流",
        description="同步行业/概念板块资金流向数据。",
        source_id="akshare",
        target_table="sector_fund_flows",
        default_params={"periods": ["即时", "3日", "5日", "10日"]},
        schedule_cron="*/10 9-15 * * 1-5",
    ),
    JobDefinition(
        id="sync_sector_period_scores",
        name="板块周期评分",
        description="根据板块 K 线、资金流、成员涨跌和情绪事件计算主线热度评分。",
        source_id="akshare",
        target_table="sector_period_scores",
        default_params={"periods": ["20d"], "sector_limit": 300},
        schedule_cron="30 18 * * 1-5",
    ),
    JobDefinition(
        id="sync_limit_up_pools",
        name="涨停池 / 跌停池",
        description="同步涨停、强势、炸板、跌停池数据。",
        source_id="akshare",
        target_table="stock_events",
        default_params={},
        schedule_cron="*/5 9-15 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_fund_flows",
        name="个股资金流",
        description="同步个股资金流向数据。",
        source_id="akshare",
        target_table="stock_fund_flows",
        default_params={"stock_limit": 200},
        schedule_cron="*/10 9-15 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_hot_ranks",
        name="个股热度排行",
        description="同步个股热度排行和关键词数据。",
        source_id="akshare",
        target_table="stock_hot_ranks",
        default_params={"limit": 100},
        schedule_cron="*/5 9-15 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_lhb_records",
        name="龙虎榜",
        description="同步龙虎榜交易明细数据。",
        source_id="akshare",
        target_table="stock_lhb_records",
        default_params={"days": 30},
        schedule_cron="0 20 * * 1-5",
    ),
    # ── Research data: stock financials ──
    JobDefinition(
        id="sync_stock_financial_quarterly",
        name="个股季度财报",
        description="同步个股利润表/资产负债表/现金流季度数据。",
        source_id="akshare",
        target_table="stock_financial_reports",
        default_params={"stock_limit": 100},
        schedule_cron="0 22 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_financial_indicators",
        name="个股财务指标",
        description="同步 ROE、毛利率、净利率等财务分析指标。",
        source_id="akshare",
        target_table="stock_financial_reports",
        default_params={"stock_limit": 100},
        schedule_cron="30 22 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_business_segments_history",
        name="主营构成历史",
        description="同步个股主营构成多报告期历史数据。",
        source_id="akshare",
        target_table="stock_business_segments",
        default_params={"stock_limit": 100},
        schedule_cron="0 23 * * 1-5",
    ),
    JobDefinition(
        id="sync_stock_notices",
        name="个股公告",
        description="同步个股公告/公告数据。",
        source_id="akshare",
        target_table="stock_events",
        default_params={},
        schedule_cron="0 21 * * 1-5",
    ),
)

SYNC_BATCH_PROFILES: dict[str, tuple[str, ...]] = {
    "core": (
        "sync_stock_list",
        "sync_sector_list",
        "sync_stock_daily_bars",
        "sync_stock_fund_flows",
        "sync_stock_hot_ranks",
    ),
    "all": tuple(job.id for job in DEFAULT_JOBS),
}

_BATCH_LOCK = threading.Lock()
_SYNC_BATCHES: dict[str, dict[str, Any]] = {}
_LATEST_BATCH_ID: str | None = None
_BATCH_KEEP_LIMIT = 20
ProgressCallback = Callable[[dict[str, Any]], None]


# ─── Job runner registry ─────────────────────────────────────────────────

class DataSyncRunner:
    """Executes individual sync jobs against AkShare / local data."""

    def __init__(self, adapter: AkShareAdapter | None = None, progress: ProgressCallback | None = None) -> None:
        self.adapter = adapter or AkShareAdapter()
        self.progress = progress

    def _report_progress(
        self,
        stage: str,
        *,
        current: int | None = None,
        total: int | None = None,
        current_label: str | None = None,
        rows_read: int | None = None,
        rows_written: int | None = None,
        sample_items: Sequence[dict[str, Any]] | None = None,
        message: str | None = None,
    ) -> None:
        if not self.progress:
            return
        patch: dict[str, Any] = {"stage": stage}
        if current is not None:
            patch["progress_current"] = max(int(current), 0)
        if total is not None:
            patch["progress_total"] = max(int(total), 0)
        if current_label is not None:
            patch["current_label"] = current_label
        if rows_read is not None:
            patch["rows_read"] = max(int(rows_read), 0)
        if rows_written is not None:
            patch["rows_written"] = max(int(rows_written), 0)
        if sample_items is not None:
            patch["sample_items"] = [_compact_progress_item(item) for item in list(sample_items)[-3:]]
        if message:
            patch["message"] = message
        try:
            self.progress(patch)
        except Exception:
            logger.debug("data sync progress callback failed", exc_info=True)

    # ── original 5 runners ──

    def _run_sync_stock_list(self, params: dict[str, Any]) -> dict[str, Any]:
        page_size = min(int(params.get("page_size", 200)), 500)
        sort = str(params.get("sort", "mktcap"))
        all_items: list[dict[str, Any]] = []
        page = 1
        total: int | None = None
        self._report_progress("读取股票清单", current=0, current_label=f"第 {page} 页")
        while True:
            self._report_progress("读取股票清单", current=len(all_items), total=total, current_label=f"第 {page} 页")
            data = self.adapter.list_stocks(page=page, page_size=page_size, sort=sort)
            items = data.get("items") or []
            total = data.get("total")
            if not items:
                break
            all_items.extend(items)
            self._report_progress(
                "读取股票清单",
                current=len(all_items),
                total=total,
                current_label=f"第 {page} 页，累计 {len(all_items)} 只",
                rows_read=len(all_items),
                sample_items=items,
            )
            if total is not None and len(all_items) >= total:
                break
            page += 1
            if page > 40:
                break
        self._report_progress("写入股票清单", current=0, total=len(all_items), rows_read=len(all_items), sample_items=all_items)
        rows_written = _upsert_stocks(all_items)
        self._report_progress(
            "写入股票清单",
            current=rows_written,
            total=len(all_items),
            rows_read=len(all_items),
            rows_written=rows_written,
            sample_items=all_items,
        )
        return {"rows_read": len(all_items), "rows_written": rows_written}

    def _run_sync_sector_list(self, params: dict[str, Any]) -> dict[str, Any]:
        types = params.get("types", ["concept", "industry", "theme"])
        if isinstance(types, str):
            types = [types]
        all_items: list[dict[str, Any]] = []
        total_types = len(types)
        self._report_progress("读取板块清单", current=0, total=total_types)
        for index, sector_type in enumerate(types, start=1):
            self._report_progress("读取板块清单", current=index - 1, total=total_types, current_label=str(sector_type))
            data = self.adapter.list_sectors(sector_type)
            items = data.get("items") or []
            for item in items:
                item["type"] = sector_type
            all_items.extend(items)
            self._report_progress(
                "读取板块清单",
                current=index,
                total=total_types,
                current_label=f"{sector_type}，{len(items)} 个",
                rows_read=len(all_items),
                sample_items=items,
            )
        self._report_progress("写入板块清单", current=0, total=len(all_items), rows_read=len(all_items), sample_items=all_items)
        rows_written = _upsert_sectors(all_items)
        self._report_progress(
            "写入板块清单",
            current=rows_written,
            total=len(all_items),
            rows_read=len(all_items),
            rows_written=rows_written,
            sample_items=all_items,
        )
        return {"rows_read": len(all_items), "rows_written": rows_written}

    def _run_sync_sector_members(self, params: dict[str, Any]) -> dict[str, Any]:
        page_size = min(int(params.get("page_size", 200)), 500)
        # First load sectors from DB
        with session_scope() as session:
            sector_rows = session.execute(select(schema.sectors)).mappings().all()
        if not sector_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No sectors in DB; run sync_sector_list first."}
        total_read = 0
        total_written = 0
        total_sectors = len(sector_rows)
        self._report_progress("同步板块成分股", current=0, total=total_sectors)
        for index, sector_row in enumerate(sector_rows, start=1):
            sector_id = str(sector_row["id"])
            sector_type = str(sector_row["type"])
            sector_name = str(sector_row.get("name") or sector_id)
            label = f"{sector_name} {sector_id}"
            self._report_progress("读取板块成分股", current=index - 1, total=total_sectors, current_label=label, rows_read=total_read, rows_written=total_written)
            try:
                data = self.adapter.sector_stocks(sector_id, page=1, page_size=page_size)
            except Exception as exc:
                logger.warning("sector_stocks(%s) failed: %s", sector_id, exc)
                self._report_progress("读取板块成分股", current=index, total=total_sectors, current_label=label, rows_read=total_read, rows_written=total_written, message=f"{sector_id} 失败：{exc.__class__.__name__}")
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_sector_memberships(sector_id, items)
            total_written += written
            self._report_progress(
                "写入板块成分股",
                current=index,
                total=total_sectors,
                current_label=f"{label}，{len(items)} 只",
                rows_read=total_read,
                rows_written=total_written,
                sample_items=items,
            )
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_stock_daily_bars(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit", 250))
        stock_limit = int(params.get("stock_limit", 0) or 0)
        only_missing = _truthy(params.get("only_missing", False))
        with session_scope() as session:
            query = select(schema.stocks).order_by(desc(schema.stocks.c.turnover), desc(schema.stocks.c.market_cap))
            if only_missing:
                existing_symbols = (
                    select(schema.stock_daily_bars.c.vt_symbol)
                    .group_by(schema.stock_daily_bars.c.vt_symbol)
                    .having(func.count() >= min(limit, 80))
                )
                query = query.where(schema.stocks.c.vt_symbol.not_in(existing_symbols))
            if stock_limit > 0:
                query = query.limit(stock_limit)
            stock_rows = session.execute(query).mappings().all()
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks in DB; run sync_stock_list first."}
        total_read = 0
        total_written = 0
        batch_size = 0
        total_stocks = len(stock_rows)
        self._report_progress("同步股票日 K 线", current=0, total=total_stocks)
        for index, stock_row in enumerate(stock_rows, start=1):
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            label = f"{current_vts} {stock_name}"
            self._report_progress("读取股票日 K 线", current=index - 1, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written)
            try:
                data = self.adapter.stock_bars(symbol, exchange, limit=limit, interval="1d")
            except Exception as exc:
                logger.debug("stock_bars(%s) failed: %s", symbol, exc)
                self._report_progress("读取股票日 K 线", current=index, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written, message=f"{current_vts} 失败：{exc.__class__.__name__}")
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_daily_bars(symbol, exchange, items)
            total_written += written
            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name} for item in items[-3:]]
            self._report_progress(
                "写入股票日 K 线",
                current=index,
                total=total_stocks,
                current_label=f"{label}，{len(items)} 根",
                rows_read=total_read,
                rows_written=total_written,
                sample_items=sample_items,
            )
            batch_size += 1
            if batch_size % 50 == 0:
                logger.info("sync_stock_daily_bars: processed %d stocks", batch_size)
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_stock_minute_bars(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit", 240))
        stock_limit = int(params.get("stock_limit", 100))
        interval = str(params.get("interval", "1m")).strip().lower()
        only_missing = _truthy(params.get("only_missing", True))
        symbols = _param_list(params.get("symbols"))
        start_date = _parse_date(params.get("start_date"))
        end_date = _parse_date(params.get("end_date"))
        if interval not in {"1m", "5m", "15m", "30m", "60m"}:
            raise DataSyncError(f"Unsupported minute interval: {interval}")

        with session_scope() as session:
            query = select(schema.stocks).order_by(desc(schema.stocks.c.turnover), desc(schema.stocks.c.market_cap))
            if symbols:
                query = query.where(schema.stocks.c.vt_symbol.in_(symbols))
            if only_missing:
                coverage_start = start_date or date.today() - timedelta(days=10)
                coverage_end = end_date or date.today()
                expected_floor = min(limit, 60)
                existing_symbols = (
                    select(schema.stock_minute_bars.c.vt_symbol)
                    .where(
                        (schema.stock_minute_bars.c.interval == interval)
                        & (schema.stock_minute_bars.c.trade_date >= coverage_start)
                        & (schema.stock_minute_bars.c.trade_date <= coverage_end)
                    )
                    .group_by(schema.stock_minute_bars.c.vt_symbol)
                    .having(func.count() >= expected_floor)
                )
                query = query.where(schema.stocks.c.vt_symbol.not_in(existing_symbols))
            if stock_limit > 0:
                query = query.limit(min(stock_limit, 5000 if symbols else 500))
            stock_rows = session.execute(query).mappings().all()
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks need minute sync."}

        total_read = 0
        total_written = 0
        total_stocks = len(stock_rows)
        self._report_progress("同步股票分钟 K 线", current=0, total=total_stocks)
        for index, stock_row in enumerate(stock_rows, start=1):
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            label = f"{current_vts} {stock_name}"
            self._report_progress("读取股票分钟 K 线", current=index - 1, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written)
            try:
                data = self.adapter.stock_bars(
                    symbol,
                    exchange,
                    limit=limit,
                    interval=interval,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception as exc:
                logger.debug("stock_minute_bars(%s, %s) failed: %s", symbol, interval, exc)
                self._report_progress("读取股票分钟 K 线", current=index, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written, message=f"{current_vts} 失败：{exc.__class__.__name__}")
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_minute_bars(symbol, exchange, items, interval, data.get("source", "akshare"))
            total_written += written
            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name, "interval": interval} for item in items[-3:]]
            self._report_progress(
                "写入股票分钟 K 线",
                current=index,
                total=total_stocks,
                current_label=f"{label}，{len(items)} 根",
                rows_read=total_read,
                rows_written=total_written,
                sample_items=sample_items,
            )
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_stock_sector_memberships(self, params: dict[str, Any]) -> dict[str, Any]:
        rows_written = _rebuild_stock_sector_memberships()
        return {"rows_read": rows_written, "rows_written": rows_written}

    # ── 4 Shenwan runners ──

    def _run_sync_shenwan_industry_tree(self, params: dict[str, Any]) -> dict[str, Any]:
        levels = params.get("levels", [1, 2, 3])
        total_read = 0
        total_written = 0
        for level in levels:
            data = self.adapter.shenwan_industry_tree(level=level)
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_shenwan_industries(items, level)
            total_written += written
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_shenwan_industry_members(self, params: dict[str, Any]) -> dict[str, Any]:
        with session_scope() as session:
            industries = session.execute(
                select(schema.shenwan_industries).where(schema.shenwan_industries.c.level == 3)
            ).mappings().all()
        if not industries:
            return {"rows_read": 0, "rows_written": 0, "message": "No level-3 industries; run sync_shenwan_industry_tree first."}
        total_read = 0
        total_written = 0
        for ind in industries:
            code = str(ind["code"])
            try:
                data = self.adapter.shenwan_industry_constituents(code)
            except Exception as exc:
                logger.debug("shenwan_industry_constituents(%s) failed: %s", code, exc)
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_shenwan_industry_members(code, items)
            total_written += written
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_industry_board_mapping(self, params: dict[str, Any]) -> dict[str, Any]:
        rows_written = _build_industry_board_mapping(self.adapter)
        return {"rows_read": rows_written, "rows_written": rows_written}

    def _run_sync_supply_chain_edges(self, params: dict[str, Any]) -> dict[str, Any]:
        level = int(params.get("level", 2))
        from alphaagent.server.services.supply_chain import infer_supply_chain_edges
        edges = infer_supply_chain_edges(level=level)
        rows_written = _upsert_industry_chain_edges(edges, level)
        return {"rows_read": len(edges), "rows_written": rows_written}

    # ── Research data runners: sector dashboard ──

    def _run_sync_sector_daily_bars(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit", 250))
        sector_limit = int(params.get("sector_limit", 0))
        with session_scope() as session:
            sector_rows = session.execute(select(schema.sectors)).mappings().all()
        if not sector_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No sectors in DB; run sync_sector_list first."}
        if sector_limit > 0:
            sector_rows = sector_rows[:sector_limit]
        total_read = 0
        total_written = 0
        for sector_row in sector_rows:
            sector_id = str(sector_row["id"])
            sector_type = str(sector_row["type"])
            try:
                data = self.adapter.sector_daily_bars(sector_id, board_type=sector_type, limit=limit)
            except Exception as exc:
                logger.debug("sector_daily_bars(%s) failed: %s", sector_id, exc)
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_sector_daily_bars(sector_id, items, data.get("source", "akshare"))
            total_written += written
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_sector_fund_flows(self, params: dict[str, Any]) -> dict[str, Any]:
        periods = params.get("periods", ["即时"])
        if isinstance(periods, str):
            periods = [periods]
        total_read = 0
        total_written = 0
        for sector_type in ("concept", "industry"):
            for period in periods:
                try:
                    data = self.adapter.sector_fund_flows(sector_type=sector_type, period=period)
                except Exception as exc:
                    logger.debug("sector_fund_flows(%s, %s) failed: %s", sector_type, period, exc)
                    continue
                items = data.get("items") or []
                total_read += len(items)
                written = _upsert_sector_fund_flows(items, period, sector_type)
                total_written += written
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_limit_up_pools(self, params: dict[str, Any]) -> dict[str, Any]:
        trade_date = params.get("trade_date")
        data = self.adapter.limit_up_pools(trade_date=trade_date)
        pools = data.get("pools") or {}
        total_read = 0
        total_written = 0
        for pool_key, pool_data in pools.items():
            if not isinstance(pool_data, dict):
                continue
            items = pool_data.get("items") or []
            total_read += len(items)
            written = _upsert_limit_up_events(items, pool_key, data.get("trade_date", ""))
            total_written += written
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_stock_fund_flows(self, params: dict[str, Any]) -> dict[str, Any]:
        stock_limit = int(params.get("stock_limit", 200))
        period = str(params.get("period", "即时"))
        limit = min(max(stock_limit, 1), 5000)
        self._report_progress("读取个股资金流", current=0, total=limit, current_label=f"{period} / 前 {limit} 只")
        try:
            data = self.adapter.stock_fund_flows("", exchange="SSE", period=period, limit=limit)
        except Exception as exc:
            logger.debug("stock_fund_flows(all) failed: %s", exc)
            return {"rows_read": 0, "rows_written": 0, "message": f"stock fund flow unavailable: {exc.__class__.__name__}"}
        items = data.get("items") or []
        if stock_limit > 0:
            items = items[: min(stock_limit, 5000)]
        self._report_progress(
            "写入个股资金流",
            current=len(items),
            total=len(items),
            current_label=f"{period} / {len(items)} 条",
            rows_read=len(items),
            sample_items=items,
        )
        rows_written = _upsert_stock_fund_flow_items(items, period)
        self._report_progress(
            "写入个股资金流",
            current=rows_written,
            total=len(items),
            current_label=f"{period} / 写入 {rows_written} 条",
            rows_read=len(items),
            rows_written=rows_written,
            sample_items=items,
        )
        return {"rows_read": len(items), "rows_written": rows_written}

    def _run_sync_stock_hot_ranks(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit", 100))
        self._report_progress("读取个股热度排行", current=0, total=limit, current_label=f"前 {limit} 名")
        data = self.adapter.stock_hot_ranks(limit=limit)
        items = data.get("items") or []
        self._report_progress(
            "写入个股热度排行",
            current=len(items),
            total=len(items),
            current_label=f"{len(items)} 条热度排行",
            rows_read=len(items),
            sample_items=items,
        )
        rows_written = _upsert_stock_hot_ranks(items)
        self._report_progress(
            "写入个股热度排行",
            current=rows_written,
            total=len(items),
            current_label=f"写入 {rows_written} 条",
            rows_read=len(items),
            rows_written=rows_written,
            sample_items=items,
        )
        return {"rows_read": len(items), "rows_written": rows_written}

    def _run_sync_stock_lhb_records(self, params: dict[str, Any]) -> dict[str, Any]:
        days = int(params.get("days", 30))
        start_date = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
        end_date = date.today().strftime("%Y%m%d")
        data = self.adapter.stock_lhb_records(start_date=start_date, end_date=end_date)
        items = data.get("items") or []
        rows_written = _upsert_stock_lhb_records(items)
        return {"rows_read": len(items), "rows_written": rows_written}

    def _run_sync_sector_period_scores(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_periods = params.get("periods", ["20d"])
        periods = [raw_periods] if isinstance(raw_periods, str) else list(raw_periods)
        sector_limit = int(params.get("sector_limit", 300) or 0)
        as_of = _parse_date(params.get("as_of_date")) if params.get("as_of_date") else None
        result = research_sector_scores.compute_and_persist(as_of_date=as_of, periods=periods, sector_limit=sector_limit)
        return {
            "rows_read": result.get("sectors_scored", 0),
            "rows_written": result.get("rows_written", 0),
            "message": f"as_of_date={result.get('as_of_date')}",
        }

    # ── Research data runners: stock financials ──

    def _run_sync_stock_financial_quarterly(self, params: dict[str, Any]) -> dict[str, Any]:
        stock_limit = int(params.get("stock_limit", 100))
        only_missing = _truthy(params.get("only_missing", True))
        stock_rows = _financial_sync_stock_rows(stock_limit, only_missing)
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks in DB."}
        total_read = 0
        total_written = 0
        total_stocks = len(stock_rows)
        self._report_progress("同步个股季度财报", current=0, total=total_stocks)
        for index, stock_row in enumerate(stock_rows, start=1):
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            label = f"{current_vts} {stock_name}"
            self._report_progress("读取个股季度财报", current=index - 1, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written)

            # Fetch quarterly profit sheet data
            try:
                data = self.adapter.stock_financial_quarterly(symbol, exchange=exchange)
            except Exception as exc:
                logger.debug("stock_financial_quarterly(%s) failed: %s", symbol, exc)
                self._report_progress("读取个股季度财报", current=index, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written, message=f"{current_vts} 失败：{exc.__class__.__name__}")
                continue
            items = data.get("items") or []

            # Enrich with ROE by fetching equity from the balance sheet.
            # ROE = (归母净利润 / 归母权益) * 100
            self._enrich_quarterly_with_roe(items, symbol, exchange)
            self._enrich_quarterly_with_cash_flow(items, symbol, exchange)

            total_read += len(items)
            written = _upsert_stock_financial_reports(
                symbol, exchange, items, "quarterly",
            )
            total_written += written
            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name} for item in items[-3:]]
            self._report_progress(
                "写入个股季度财报",
                current=index,
                total=total_stocks,
                current_label=f"{label}，{len(items)} 期",
                rows_read=total_read,
                rows_written=total_written,
                sample_items=sample_items,
            )
        return {"rows_read": total_read, "rows_written": total_written}

    @staticmethod
    def _to_float(value: Any) -> float | None:
        """Convert a value to float, returning None for missing / invalid."""
        if value is None or value == "" or value == "-":
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _enrich_quarterly_with_roe(
        self,
        items: list[dict[str, Any]],
        symbol: str,
        exchange: str,
    ) -> None:
        """Enrich quarterly items with computed ROE, margins, and EPS.

        ROE requires equity from the balance sheet.
        Gross margin = (revenue - cost) / revenue * 100.
        Net margin = net_profit / revenue * 100.
        EPS is extracted from BASIC_EPS in raw data.
        """
        if not items:
            return

        # Build report_date → TOTAL_PARENT_EQUITY from balance sheet
        equity_map: dict[str, float] = {}
        try:
            bs_data = self.adapter.stock_balance_sheet(symbol, exchange=exchange)
            for bs in bs_data.get("items") or []:
                bs_dict = bs if isinstance(bs, dict) else {}
                report_date_raw = bs_dict.get("REPORT_DATE")
                if not report_date_raw:
                    continue
                rd = str(report_date_raw)[:10]
                equity = self._to_float(bs_dict.get("TOTAL_PARENT_EQUITY"))
                if equity:
                    equity_map[rd] = equity
        except Exception:
            pass

        for item in items:
            raw = item.get("raw") or {}
            rd = str(item.get("report_date", ""))[:10]

            # --- EPS from raw fallback ---
            if item.get("eps") is None:
                eps = self._to_float(raw.get("BASIC_EPS"))
                if eps is not None:
                    item["eps"] = eps

            # --- Gross margin = (income - cost) / income * 100 ---
            if item.get("gross_margin") is None:
                income = self._to_float(raw.get("TOTAL_OPERATE_INCOME") or raw.get("OPERATE_INCOME"))
                cost = self._to_float(raw.get("OPERATE_COST"))
                if income and cost is not None:
                    item["gross_margin"] = round(((income - cost) / income) * 100, 4)

            # --- Net margin = net_profit / income * 100 ---
            if item.get("net_margin") is None:
                income = self._to_float(raw.get("TOTAL_OPERATE_INCOME") or raw.get("OPERATE_INCOME"))
                np = self._to_float(raw.get("NETPROFIT"))
                if income and np is not None:
                    item["net_margin"] = round((np / income) * 100, 4)

            # --- ROE = parent_net_profit / parent_equity * 100 ---
            if item.get("roe") is None:
                equity = equity_map.get(rd)
                if equity:
                    pnp = self._to_float(raw.get("PARENT_NETPROFIT"))
                    if pnp is not None:
                        item["roe"] = round((pnp / equity) * 100, 4)

    def _enrich_quarterly_with_cash_flow(
        self,
        items: list[dict[str, Any]],
        symbol: str,
        exchange: str,
    ) -> None:
        """Enrich quarterly items with operating cash flow and disclosure date."""
        if not items:
            return

        cash_flow_map: dict[str, dict[str, Any]] = {}
        try:
            cash_flow_data = self.adapter.stock_cash_flow_sheet(symbol, exchange=exchange)
        except Exception:
            return

        for row in cash_flow_data.get("items") or []:
            record = row if isinstance(row, dict) else {}
            report_date = str(record.get("REPORT_DATE") or record.get("报告期") or "")[:10]
            if report_date:
                cash_flow_map[report_date] = record

        for item in items:
            report_date = str(item.get("report_date") or "")[:10]
            cash_flow_row = cash_flow_map.get(report_date)
            if not cash_flow_row:
                continue

            if item.get("publish_date") is None:
                item["publish_date"] = cash_flow_row.get("NOTICE_DATE") or cash_flow_row.get("公告日期")

            if item.get("operating_cash_flow") is None:
                item["operating_cash_flow"] = self._to_float(
                    cash_flow_row.get("NETCASH_OPERATE")
                    or cash_flow_row.get("经营活动产生的现金流量净额")
                )

            if item.get("cash_flow_quality") is None:
                operating_cash_flow = self._to_float(item.get("operating_cash_flow"))
                net_profit = self._to_float(item.get("net_profit") or cash_flow_row.get("NETPROFIT"))
                if operating_cash_flow is not None and net_profit not in (None, 0):
                    item["cash_flow_quality"] = round(operating_cash_flow / net_profit, 4)

    def _run_sync_stock_financial_indicators(self, params: dict[str, Any]) -> dict[str, Any]:
        stock_limit = int(params.get("stock_limit", 100))
        only_missing = _truthy(params.get("only_missing", True))
        stock_rows = _financial_sync_stock_rows(stock_limit, only_missing)
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks in DB."}
        total_read = 0
        total_written = 0
        total_stocks = len(stock_rows)
        self._report_progress("同步个股财务指标", current=0, total=total_stocks)
        for index, stock_row in enumerate(stock_rows, start=1):
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            label = f"{current_vts} {stock_name}"
            self._report_progress("读取个股财务指标", current=index - 1, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written)
            try:
                data = self.adapter.stock_financial_indicators(symbol, exchange=exchange)
            except Exception as exc:
                logger.debug("stock_financial_indicators(%s) failed: %s", symbol, exc)
                self._report_progress("读取个股财务指标", current=index, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written, message=f"{current_vts} 失败：{exc.__class__.__name__}")
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_stock_financial_reports(
                symbol, exchange, items, "indicator",
            )
            total_written += written
            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name} for item in items[-3:]]
            self._report_progress(
                "写入个股财务指标",
                current=index,
                total=total_stocks,
                current_label=f"{label}，{len(items)} 期",
                rows_read=total_read,
                rows_written=total_written,
                sample_items=sample_items,
            )
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_stock_business_segments_history(self, params: dict[str, Any]) -> dict[str, Any]:
        stock_limit = int(params.get("stock_limit", 100))
        with session_scope() as session:
            stock_rows = session.execute(
                select(schema.stocks).limit(min(stock_limit, 500))
            ).mappings().all()
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks in DB."}
        total_read = 0
        total_written = 0
        total_stocks = len(stock_rows)
        self._report_progress("同步主营构成历史", current=0, total=total_stocks)
        for index, stock_row in enumerate(stock_rows, start=1):
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            label = f"{current_vts} {stock_name}"
            self._report_progress("读取主营构成历史", current=index - 1, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written)
            try:
                data = self.adapter.stock_business_segments_history(symbol, exchange=exchange)
            except Exception as exc:
                logger.debug("stock_business_segments_history(%s) failed: %s", symbol, exc)
                self._report_progress("读取主营构成历史", current=index, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written, message=f"{current_vts} 失败：{exc.__class__.__name__}")
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_stock_business_segments(symbol, exchange, items)
            total_written += written
            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name} for item in items[-3:]]
            self._report_progress(
                "写入主营构成历史",
                current=index,
                total=total_stocks,
                current_label=f"{label}，{len(items)} 条",
                rows_read=total_read,
                rows_written=total_written,
                sample_items=sample_items,
            )
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_stock_notices(self, params: dict[str, Any]) -> dict[str, Any]:
        stock_limit = int(params.get("stock_limit", 100))
        with session_scope() as session:
            stock_rows = session.execute(
                select(schema.stocks).limit(min(stock_limit, 500))
            ).mappings().all()
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks in DB."}
        total_read = 0
        total_written = 0
        total_stocks = len(stock_rows)
        self._report_progress("同步个股公告", current=0, total=total_stocks)
        for index, stock_row in enumerate(stock_rows, start=1):
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row.get("exchange") or normalize_exchange(symbol))
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            label = f"{current_vts} {stock_name}"
            self._report_progress("读取个股公告", current=index - 1, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written)
            try:
                data = self.adapter.stock_notices(symbol)
            except Exception as exc:
                logger.debug("stock_notices(%s) failed: %s", symbol, exc)
                self._report_progress("读取个股公告", current=index, total=total_stocks, current_label=label, rows_read=total_read, rows_written=total_written, message=f"{current_vts} 失败：{exc.__class__.__name__}")
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_stock_events(symbol, items, "notice")
            total_written += written
            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name} for item in items[-3:]]
            self._report_progress(
                "写入个股公告",
                current=index,
                total=total_stocks,
                current_label=f"{label}，{len(items)} 条",
                rows_read=total_read,
                rows_written=total_written,
                sample_items=sample_items,
            )
        return {"rows_read": total_read, "rows_written": total_written}


JOB_RUNNERS: dict[str, str] = {
    "sync_stock_list": "_run_sync_stock_list",
    "sync_sector_list": "_run_sync_sector_list",
    "sync_sector_members": "_run_sync_sector_members",
    "sync_stock_daily_bars": "_run_sync_stock_daily_bars",
    "sync_stock_minute_bars": "_run_sync_stock_minute_bars",
    "sync_stock_sector_memberships": "_run_sync_stock_sector_memberships",
    "sync_shenwan_industry_tree": "_run_sync_shenwan_industry_tree",
    "sync_shenwan_industry_members": "_run_sync_shenwan_industry_members",
    "sync_industry_board_mapping": "_run_sync_industry_board_mapping",
    "sync_supply_chain_edges": "_run_sync_supply_chain_edges",
    # ── Research data: sector dashboard ──
    "sync_sector_daily_bars": "_run_sync_sector_daily_bars",
    "sync_sector_fund_flows": "_run_sync_sector_fund_flows",
    "sync_sector_period_scores": "_run_sync_sector_period_scores",
    "sync_limit_up_pools": "_run_sync_limit_up_pools",
    "sync_stock_fund_flows": "_run_sync_stock_fund_flows",
    "sync_stock_hot_ranks": "_run_sync_stock_hot_ranks",
    "sync_stock_lhb_records": "_run_sync_stock_lhb_records",
    # ── Research data: stock financials ──
    "sync_stock_financial_quarterly": "_run_sync_stock_financial_quarterly",
    "sync_stock_financial_indicators": "_run_sync_stock_financial_indicators",
    "sync_stock_business_segments_history": "_run_sync_stock_business_segments_history",
    "sync_stock_notices": "_run_sync_stock_notices",
}


# ─── Global state ────────────────────────────────────────────────────────

_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()


# ─── Error class ──────────────────────────────────────────────────────────

class DataSyncError(RuntimeError):
    """Raised when a sync job fails."""


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _param_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    result = []
    for item in raw_items:
        text = str(item or "").strip().upper()
        if not text or "." not in text:
            continue
        if text not in result:
            result.append(text)
    return result


def _normalize_csv_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _minute_csv_symbol_exchange(row: dict[str, Any]) -> tuple[str, str]:
    vt_symbol_value = str(row.get("vt_symbol") or row.get("code_exchange") or "").strip().upper()
    if vt_symbol_value and "." in vt_symbol_value:
        symbol, exchange = vt_symbol_value.split(".", 1)
        return symbol.strip(), exchange.strip()
    symbol = str(row.get("symbol") or row.get("code") or row.get("股票代码") or "").strip()
    exchange = str(row.get("exchange") or row.get("market") or row.get("交易所") or "").strip().upper()
    if not symbol:
        raise ValueError("missing vt_symbol or symbol")
    if not exchange:
        exchange = normalize_exchange(symbol)
    return symbol, exchange


def _minute_csv_item(row: dict[str, Any]) -> dict[str, Any]:
    bar_time = (
        row.get("bar_time")
        or row.get("trade_date")
        or row.get("datetime")
        or row.get("time")
        or row.get("date_time")
    )
    if _parse_datetime(bar_time) is None:
        raise ValueError("missing or invalid bar_time")
    open_price = _required_number(row, "open", "open_price", "开盘")
    high_price = _required_number(row, "high", "high_price", "最高")
    low_price = _required_number(row, "low", "low_price", "最低")
    close_price = _required_number(row, "close", "close_price", "收盘")
    return {
        "trade_date": bar_time,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": _optional_number(row, "volume", "vol", "成交量"),
        "turnover": _optional_number(row, "turnover", "amount", "成交额"),
        "raw": row,
    }


def _required_number(row: dict[str, Any], *keys: str) -> float:
    value = _optional_number(row, *keys)
    if value is None:
        raise ValueError(f"missing numeric field: {keys[0]}")
    return value


def _optional_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(_normalize_csv_key(key))
        if value in (None, ""):
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"invalid numeric field {key}: {value}") from exc
    return None


# ─── Schema bootstrap ────────────────────────────────────────────────────

def ensure_sync_schema() -> None:
    """Create sync tables if they are missing."""
    if not is_database_configured():
        return
    schema.create_schema(get_engine())
    # Idempotent column additions for tables created by earlier migrations
    try:
        with session_scope() as session:
            session.execute(text(
                "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS volume_ratio FLOAT"
            ))
    except Exception:
        pass
    seed_default_registry()
    mark_interrupted_runs()


def seed_default_registry() -> None:
    """Insert default sources and job definitions when they are missing."""
    try:
        with session_scope() as session:
            for source_info in DEFAULT_SOURCE.values():
                existing = session.execute(
                    select(schema.sync_sources).where(schema.sync_sources.c.id == source_info["id"])
                ).first()
                if existing is None:
                    session.execute(schema.sync_sources.insert().values(**source_info))

            for job in DEFAULT_JOBS:
                existing = session.execute(
                    select(schema.sync_job_definitions).where(schema.sync_job_definitions.c.id == job.id)
                ).first()
                if existing is None:
                    session.execute(schema.sync_job_definitions.insert().values(
                        id=job.id,
                        name=job.name,
                        description=job.description,
                        source_id=job.source_id,
                        target_table=job.target_table,
                        enabled=job.enabled,
                        default_params=job.default_params,
                        schedule_cron=job.schedule_cron,
                    ))
    except Exception as exc:
        logger.warning("seed_default_registry failed: %s", exc)


def mark_interrupted_runs() -> None:
    """Mark runs left in running state by a previous API process as failed."""
    try:
        with session_scope() as session:
            session.execute(
                schema.sync_job_runs.update()
                .where(schema.sync_job_runs.c.status == "running")
                .values(
                    status="failed",
                    message="API process restarted before this sync job finished.",
                    error_type="Interrupted",
                    finished_at=datetime.now(timezone.utc),
                )
            )
            session.execute(
                schema.sync_job_definitions.update()
                .where(schema.sync_job_definitions.c.last_status == "running")
                .values(
                    last_status="failed",
                    last_message="API process restarted before this sync job finished.",
                    last_finished_at=datetime.now(timezone.utc),
                )
            )
    except Exception as exc:
        logger.warning("mark_interrupted_runs failed: %s", exc)


# ─── Public query API ────────────────────────────────────────────────────

def list_sources() -> list[dict[str, Any]]:
    if not is_database_configured():
        return _default_sources("unavailable", "DATABASE_URL not configured")
    try:
        with session_scope() as session:
            rows = session.execute(select(schema.sync_sources).order_by(schema.sync_sources.c.priority)).mappings().all()
        return [_mapping_to_api(dict(row)) for row in rows]
    except Exception as exc:
        return _default_sources("unavailable", exc.__class__.__name__)


def list_jobs() -> list[dict[str, Any]]:
    if not is_database_configured():
        return _default_jobs("unavailable", "DATABASE_URL not configured")
    try:
        with session_scope() as session:
            rows = session.execute(select(schema.sync_job_definitions).order_by(schema.sync_job_definitions.c.id)).mappings().all()
        return [_mapping_to_api(dict(row)) for row in rows]
    except Exception as exc:
        return _default_jobs("unavailable", exc.__class__.__name__)


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    if not is_database_configured():
        return []
    try:
        with session_scope() as session:
            rows = session.execute(
                select(schema.sync_job_runs)
                .order_by(desc(schema.sync_job_runs.c.id))
                .limit(min(max(limit, 1), 100))
            ).mappings().all()
        return [_mapping_to_api(dict(row)) for row in rows]
    except Exception:
        return []


def update_job_schedule(job_id: str, schedule_cron: str | None) -> dict[str, Any]:
    with session_scope() as session:
        session.execute(
            schema.sync_job_definitions.update()
            .where(schema.sync_job_definitions.c.id == job_id)
            .values(schedule_cron=schedule_cron)
        )
    return {"job_id": job_id, "schedule_cron": schedule_cron}


# ─── Sync batches ────────────────────────────────────────────────────────

def start_sync_batch(profile: str = "core", params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start a background batch that runs sync jobs in dependency order."""
    global _LATEST_BATCH_ID

    if not is_database_configured():
        raise DataSyncError("DATABASE_URL is not configured")

    profile_key = profile if profile in SYNC_BATCH_PROFILES else "core"
    with _BATCH_LOCK:
        if _LATEST_BATCH_ID:
            latest = _SYNC_BATCHES.get(_LATEST_BATCH_ID)
            if latest and latest.get("status") == "running":
                return _copy_batch(latest)

    batch_id = uuid4().hex
    job_ids = list(SYNC_BATCH_PROFILES[profile_key])
    created_at = _utc_now_iso()
    batch = {
        "id": batch_id,
        "profile": profile_key,
        "status": "running",
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": None,
        "current_job_id": job_ids[0] if job_ids else None,
        "total_jobs": len(job_ids),
        "completed_jobs": 0,
        "succeeded_jobs": 0,
        "failed_jobs": 0,
        "rows_read": 0,
        "rows_written": 0,
        "message": "",
        "jobs": [
            {
                "job_id": job_id,
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "rows_read": 0,
                "rows_written": 0,
                "progress_current": 0,
                "progress_total": 0,
                "progress_pct": 0,
                "stage": "",
                "current_label": "",
                "sample_items": [],
                "message": "",
            }
            for job_id in job_ids
        ],
    }

    with _BATCH_LOCK:
        _SYNC_BATCHES[batch_id] = batch
        _LATEST_BATCH_ID = batch_id
        _trim_batches_locked()

    thread = threading.Thread(
        target=_run_sync_batch,
        args=(batch_id, params or {}),
        name=f"data-sync-batch-{batch_id[:8]}",
        daemon=True,
    )
    thread.start()
    return get_sync_batch(batch_id)


def get_sync_batch(batch_id: str) -> dict[str, Any]:
    """Return a sync batch snapshot."""
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if batch is None:
            raise DataSyncError(f"Unknown sync batch: {batch_id}")
        return _copy_batch(batch)


def get_latest_sync_batch() -> dict[str, Any] | None:
    """Return the latest sync batch snapshot, if any."""
    with _BATCH_LOCK:
        if not _LATEST_BATCH_ID:
            return None
        batch = _SYNC_BATCHES.get(_LATEST_BATCH_ID)
        return _copy_batch(batch) if batch is not None else None


def _run_sync_batch(batch_id: str, params: dict[str, Any]) -> None:
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if not batch:
            return
        job_ids = [item["job_id"] for item in batch["jobs"]]

    for index, job_id in enumerate(job_ids):
        _update_batch_job(
            batch_id,
            job_id,
            {
                "status": "running",
                "started_at": _utc_now_iso(),
                "progress_current": 0,
                "progress_total": 0,
                "progress_pct": 0,
                "stage": "准备执行",
                "current_label": "",
                "sample_items": [],
            },
        )
        _patch_batch(batch_id, {"current_job_id": job_id, "message": f"正在同步 {job_id}"})
        try:
            result = run_job(job_id, _batch_job_params(job_id, params), progress=_batch_progress_callback(batch_id, job_id))
            rows_read = int(result.get("rows_read") or 0)
            rows_written = int(result.get("rows_written") or 0)
            _update_batch_job(
                batch_id,
                job_id,
                {
                    "status": "succeeded",
                    "finished_at": _utc_now_iso(),
                    "rows_read": rows_read,
                    "rows_written": rows_written,
                    "progress_pct": 100,
                    "stage": "完成",
                    "current_label": "",
                    "message": str(result.get("message") or ""),
                    "run_id": result.get("run_id") or result.get("id"),
                },
            )
            _increment_batch(batch_id, completed=1, succeeded=1, rows_read=rows_read, rows_written=rows_written)
        except Exception as exc:
            _update_batch_job(
                batch_id,
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now_iso(),
                    "message": str(exc),
                    "error_type": exc.__class__.__name__,
                    "stage": "失败",
                },
            )
            _increment_batch(batch_id, completed=1, failed=1)
            _finish_batch(batch_id, "failed", f"{job_id} 失败：{exc}")
            return

        with _BATCH_LOCK:
            batch = _SYNC_BATCHES.get(batch_id)
            if batch:
                batch["current_job_id"] = job_ids[index + 1] if index + 1 < len(job_ids) else None

    _finish_batch(batch_id, "succeeded", "同步完成")


def _batch_job_params(job_id: str, batch_params: dict[str, Any]) -> dict[str, Any]:
    per_job = batch_params.get("jobs") if isinstance(batch_params.get("jobs"), dict) else {}
    params = per_job.get(job_id, {}) if isinstance(per_job, dict) else {}
    return params if isinstance(params, dict) else {}


def _batch_progress_callback(batch_id: str, job_id: str) -> ProgressCallback:
    def callback(patch: dict[str, Any]) -> None:
        safe_patch = _progress_patch_to_batch_fields(patch)
        if not safe_patch:
            return
        _update_batch_job(batch_id, job_id, safe_patch)
        stage = safe_patch.get("stage")
        label = safe_patch.get("current_label")
        if stage or label:
            message = f"{stage or '同步中'}：{label}" if label else str(stage)
            _patch_batch(batch_id, {"message": message})

    return callback


def _progress_patch_to_batch_fields(patch: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "stage",
        "current_label",
        "rows_read",
        "rows_written",
        "progress_current",
        "progress_total",
        "sample_items",
        "message",
    }
    safe: dict[str, Any] = {key: patch[key] for key in allowed if key in patch}
    if "progress_current" in safe:
        safe["progress_current"] = max(int(safe["progress_current"] or 0), 0)
    if "progress_total" in safe:
        safe["progress_total"] = max(int(safe["progress_total"] or 0), 0)
    if "rows_read" in safe:
        safe["rows_read"] = max(int(safe["rows_read"] or 0), 0)
    if "rows_written" in safe:
        safe["rows_written"] = max(int(safe["rows_written"] or 0), 0)
    if "sample_items" in safe:
        samples = safe.get("sample_items") if isinstance(safe.get("sample_items"), list) else []
        safe["sample_items"] = [_compact_progress_item(item) for item in samples[-3:] if isinstance(item, dict)]
    current = safe.get("progress_current")
    total = safe.get("progress_total")
    if isinstance(current, int) and isinstance(total, int) and total > 0:
        safe["progress_pct"] = round(min(current / total * 100, 100), 2)
    return safe


def _compact_progress_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return a small, UI-safe sample of one synced record."""
    allowed_keys = (
        "vt_symbol",
        "symbol",
        "exchange",
        "name",
        "id",
        "type",
        "trade_date",
        "bar_time",
        "interval",
        "open",
        "high",
        "low",
        "close",
        "close_price",
        "volume",
        "turnover",
        "change_pct",
        "rank",
        "rank_change",
        "main_net_inflow",
        "main_net_inflow_pct",
        "report_date",
        "publish_date",
        "net_profit",
        "revenue",
        "operating_cash_flow",
        "cash_flow_quality",
        "title",
    )
    compact: dict[str, Any] = {}
    for key in allowed_keys:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            compact[key] = value
        elif isinstance(value, date):
            compact[key] = value.isoformat()
        elif isinstance(value, datetime):
            compact[key] = value.isoformat()
        elif isinstance(value, list):
            compact[key] = [str(v)[:80] for v in value[:3]]
    if "vt_symbol" not in compact and compact.get("symbol"):
        try:
            compact["vt_symbol"] = vt_symbol(str(compact["symbol"]), str(compact.get("exchange") or normalize_exchange(str(compact["symbol"]))))
        except Exception:
            pass
    return compact


def _patch_batch(batch_id: str, patch: dict[str, Any]) -> None:
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if batch:
            batch.update(patch)


def _increment_batch(batch_id: str, completed: int = 0, succeeded: int = 0, failed: int = 0, rows_read: int = 0, rows_written: int = 0) -> None:
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if not batch:
            return
        batch["completed_jobs"] = int(batch.get("completed_jobs") or 0) + completed
        batch["succeeded_jobs"] = int(batch.get("succeeded_jobs") or 0) + succeeded
        batch["failed_jobs"] = int(batch.get("failed_jobs") or 0) + failed
        batch["rows_read"] = int(batch.get("rows_read") or 0) + rows_read
        batch["rows_written"] = int(batch.get("rows_written") or 0) + rows_written


def _finish_batch(batch_id: str, status: str, message: str) -> None:
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if not batch:
            return
        batch["status"] = status
        batch["finished_at"] = _utc_now_iso()
        batch["current_job_id"] = None
        batch["message"] = message


def _update_batch_job(batch_id: str, job_id: str, patch: dict[str, Any]) -> None:
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if not batch:
            return
        for item in batch["jobs"]:
            if item["job_id"] == job_id:
                item.update(patch)
                break


def _copy_batch(batch: dict[str, Any]) -> dict[str, Any]:
    copied = dict(batch)
    copied["jobs"] = []
    for item in batch.get("jobs", []):
        job = dict(item)
        samples = job.get("sample_items") if isinstance(job.get("sample_items"), list) else []
        job["sample_items"] = [dict(sample) for sample in samples if isinstance(sample, dict)]
        total_units = int(job.get("progress_total") or 0)
        current_units = int(job.get("progress_current") or 0)
        if job.get("status") == "succeeded":
            job["progress_pct"] = 100
        elif total_units > 0:
            job["progress_pct"] = round(min(current_units / total_units * 100, 100), 2)
        else:
            job["progress_pct"] = 0
        copied["jobs"].append(job)
    total = int(copied.get("total_jobs") or 0)
    completed = int(copied.get("completed_jobs") or 0)
    copied["progress_pct"] = round(completed / total * 100, 2) if total else 0
    return copied


def _trim_batches_locked() -> None:
    if len(_SYNC_BATCHES) <= _BATCH_KEEP_LIMIT:
        return
    ordered = sorted(_SYNC_BATCHES.items(), key=lambda item: str(item[1].get("created_at") or ""))
    for batch_id, batch in ordered[: max(len(_SYNC_BATCHES) - _BATCH_KEEP_LIMIT, 0)]:
        if batch.get("status") != "running":
            _SYNC_BATCHES.pop(batch_id, None)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Coverage / usage ────────────────────────────────────────────────────

def coverage() -> dict[str, Any]:
    """Return per-table row counts and freshness."""
    if not is_database_configured():
        return {"status": "unavailable", "tables": {}, "message": "DATABASE_URL not configured"}

    table_names = [
        "stocks", "stock_daily_bars", "stock_minute_bars", "sectors", "sector_memberships",
        "stock_sector_memberships", "stock_business_segments",
        "shenwan_industries", "shenwan_industry_members",
        "industry_chain_edges", "industry_board_mapping",
        # ── Research tables ──
        "sector_daily_bars", "sector_daily_metrics", "sector_period_scores",
        "sector_relation_edges", "industry_chain_nodes",
        "stock_financial_reports", "stock_financial_statement_items",
        "stock_events", "stock_fund_flows", "sector_fund_flows",
        "stock_hot_ranks", "stock_lhb_records",
    ]
    tables: dict[str, dict[str, Any]] = {}
    with session_scope() as session:
        for table_name in table_names:
            table_obj = getattr(schema, table_name, None)
            if table_obj is None:
                continue
            try:
                count = session.execute(select(func.count()).select_from(table_obj)).scalar() or 0
            except Exception:
                count = 0
            # Try to get latest updated_at
            freshness = None
            try:
                latest = session.execute(
                    select(table_obj.c.updated_at).order_by(desc(table_obj.c.updated_at)).limit(1)
                ).scalar()
                if latest is not None:
                    freshness = latest.isoformat() if hasattr(latest, "isoformat") else str(latest)
            except Exception:
                pass
            tables[table_name] = {"count": count, "last_updated": freshness}

    return {
        "status": "ready" if any(t["count"] > 0 for t in tables.values()) else "empty",
        "tables": tables,
    }


def usage() -> dict[str, Any]:
    """Return capability usage report for the health / readiness endpoint."""
    return {
        "capabilities": _usage_capabilities(),
        "coverage": coverage(),
    }


def minute_csv_template() -> str:
    """Return a minimal CSV template for importing historical minute bars."""

    return (
        "vt_symbol,bar_time,open,high,low,close,volume,turnover\n"
        "600000.SSE,2026-01-08 14:56:00,10.00,10.10,9.98,10.05,120000,1206000\n"
    )


def import_stock_minute_bars_csv(
    csv_text: str,
    *,
    interval: str = "1m",
    source: str = "manual_csv",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import historical minute bars from CSV text into stock_minute_bars."""

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    interval = str(interval or "1m").strip().lower()
    if interval not in {"1m", "5m", "15m", "30m", "60m"}:
        raise DataSyncError(f"Unsupported minute interval: {interval}")
    if not csv_text.strip():
        return {"status": "empty", "rows_read": 0, "rows_written": 0, "rows_skipped": 0, "errors": ["CSV is empty"]}

    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    return _import_stock_minute_bars_from_reader(reader, interval=interval, source=source, dry_run=dry_run)


def import_stock_minute_bars_file(
    file_path: str,
    *,
    interval: str = "1m",
    source: str = "manual_csv_file",
    dry_run: bool = False,
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Import historical minute bars from an allowed local CSV file path."""

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    interval = str(interval or "1m").strip().lower()
    if interval not in {"1m", "5m", "15m", "30m", "60m"}:
        raise DataSyncError(f"Unsupported minute interval: {interval}")
    resolved = _allowed_import_file(file_path)
    with resolved.open("r", encoding=encoding, newline="") as file:
        reader = csv.DictReader(file)
        result = _import_stock_minute_bars_from_reader_streaming(
            reader,
            interval=interval,
            source=source,
            dry_run=dry_run,
        )
    result["file_path"] = str(resolved.relative_to(PROJECT_ROOT))
    return result


def _import_stock_minute_bars_from_reader(
    reader: csv.DictReader,
    *,
    interval: str,
    source: str,
    dry_run: bool,
) -> dict[str, Any]:
    if not reader.fieldnames:
        return {"status": "empty", "rows_read": 0, "rows_written": 0, "rows_skipped": 0, "errors": ["CSV header is missing"]}

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    errors: list[str] = []
    rows_read = 0
    rows_skipped = 0
    for row in reader:
        rows_read += 1
        normalized = {_normalize_csv_key(key): value for key, value in row.items()}
        try:
            symbol, exchange = _minute_csv_symbol_exchange(normalized)
            item = _minute_csv_item(normalized)
        except ValueError as exc:
            rows_skipped += 1
            if len(errors) < 20:
                errors.append(f"row {rows_read}: {exc}")
            continue
        grouped.setdefault((symbol, exchange), []).append(item)

    rows_written = 0
    if not dry_run:
        ensure_sync_schema()
        for (symbol, exchange), items in grouped.items():
            rows_written += _upsert_minute_bars(symbol, exchange, items, interval, source)

    return {
        "status": "ready" if rows_read and (rows_written or dry_run) else "empty",
        "interval": interval,
        "source": source,
        "dry_run": dry_run,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "rows_skipped": rows_skipped,
        "symbol_count": len(grouped),
        "errors": errors,
        "required_columns": ["vt_symbol 或 symbol+exchange", "bar_time/trade_date/time/datetime", "open/high/low/close"],
    }


def _import_stock_minute_bars_from_reader_streaming(
    reader: csv.DictReader,
    *,
    interval: str,
    source: str,
    dry_run: bool,
    batch_size: int = 2000,
) -> dict[str, Any]:
    """Import minute bars from a CSV reader without holding the whole file."""

    if not reader.fieldnames:
        return {"status": "empty", "rows_read": 0, "rows_written": 0, "rows_skipped": 0, "errors": ["CSV header is missing"]}

    errors: list[str] = []
    rows_read = 0
    rows_skipped = 0
    rows_written = 0
    symbol_keys: set[tuple[str, str]] = set()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}

    if not dry_run:
        ensure_sync_schema()

    def flush(force: bool = False) -> None:
        nonlocal rows_written, grouped
        if not grouped:
            return
        pending_count = sum(len(items) for items in grouped.values())
        if not force and pending_count < batch_size:
            return
        if not dry_run:
            for (symbol, exchange), items in grouped.items():
                rows_written += _upsert_minute_bars(symbol, exchange, items, interval, source)
        grouped = {}

    for row in reader:
        rows_read += 1
        normalized = {_normalize_csv_key(key): value for key, value in row.items()}
        try:
            symbol, exchange = _minute_csv_symbol_exchange(normalized)
            item = _minute_csv_item(normalized)
        except ValueError as exc:
            rows_skipped += 1
            if len(errors) < 20:
                errors.append(f"row {rows_read}: {exc}")
            continue
        key = (symbol, exchange)
        symbol_keys.add(key)
        grouped.setdefault(key, []).append(item)
        flush()

    flush(force=True)

    return {
        "status": "ready" if rows_read and (rows_written or dry_run) else "empty",
        "interval": interval,
        "source": source,
        "dry_run": dry_run,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "rows_skipped": rows_skipped,
        "symbol_count": len(symbol_keys),
        "errors": errors,
        "required_columns": ["vt_symbol 或 symbol+exchange", "bar_time/trade_date/time/datetime", "open/high/low/close"],
    }


def audit_minute_gap_csv(
    gap_csv_text: str,
    *,
    interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:57",
    min_tail_bars: int = 1,
) -> dict[str, Any]:
    """Check whether stock_minute_bars covers a strict-tail backtest gap CSV."""

    interval = str(interval or "1m").strip().lower()
    if interval not in {"1m", "5m", "15m", "30m", "60m"}:
        raise DataSyncError(f"Unsupported minute interval: {interval}")
    if not gap_csv_text.strip():
        return {"status": "empty", "rows_read": 0, "rows_skipped": 0, "errors": ["CSV is empty"]}
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}

    requirements = _parse_minute_gap_requirements(gap_csv_text)
    return _audit_minute_gap_requirements(
        requirements,
        interval=interval,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        min_tail_bars=min_tail_bars,
    )


def audit_minute_gap_file(
    file_path: str,
    *,
    interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:57",
    min_tail_bars: int = 1,
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Check minute-bar coverage for a strict-tail gap CSV file."""

    interval = str(interval or "1m").strip().lower()
    if interval not in {"1m", "5m", "15m", "30m", "60m"}:
        raise DataSyncError(f"Unsupported minute interval: {interval}")
    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    resolved = _allowed_import_file(file_path)
    with resolved.open("r", encoding=encoding, newline="") as file:
        requirements = _parse_minute_gap_reader(csv.DictReader(file))
    result = _audit_minute_gap_requirements(
        requirements,
        interval=interval,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        min_tail_bars=min_tail_bars,
    )
    result["file_path"] = str(resolved.relative_to(PROJECT_ROOT))
    return result


def _audit_minute_gap_requirements(
    requirements: dict[str, Any],
    *,
    interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
    min_tail_bars: int,
) -> dict[str, Any]:
    if requirements["errors"] and not requirements["items"]:
        return {
            "status": "empty",
            "rows_read": requirements["rows_read"],
            "rows_skipped": requirements["rows_skipped"],
            "errors": requirements["errors"],
        }

    items = requirements["items"]
    coverage = _minute_gap_coverage_counts(items, interval, tail_entry_start, tail_entry_end)
    covered = []
    missing = []
    for item in items:
        key = (item["vt_symbol"], item["trade_date"])
        count = int(coverage.get(key, 0) or 0)
        row = {**item, "minute_bar_count": count, "required_tail_bars": min_tail_bars}
        if count >= min_tail_bars:
            covered.append(row)
        else:
            row["missing_reason"] = "no_tail_window_minute_bars" if count == 0 else "insufficient_tail_window_minute_bars"
            missing.append(row)

    unique_symbols = sorted({item["vt_symbol"] for item in items})
    unique_dates = sorted({item["trade_date"] for item in items})
    missing_symbols = sorted({item["vt_symbol"] for item in missing})
    missing_dates = sorted({item["trade_date"] for item in missing})
    return {
        "status": "ready" if not missing else "incomplete",
        "interval": interval,
        "tail_entry_window": f"{tail_entry_start}-{tail_entry_end}",
        "required_tail_bars": min_tail_bars,
        "rows_read": requirements["rows_read"],
        "rows_skipped": requirements["rows_skipped"],
        "gap_count": len(items),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "coverage_pct": round(len(covered) / len(items) * 100, 4) if items else 0,
        "symbol_count": len(unique_symbols),
        "date_count": len(unique_dates),
        "missing_symbol_count": len(missing_symbols),
        "missing_date_count": len(missing_dates),
        "symbols": unique_symbols[:500],
        "missing_symbols": missing_symbols[:500],
        "missing_dates": [item.isoformat() for item in missing_dates[:500]],
        "covered_examples": _minute_gap_rows_to_api(covered[:20]),
        "missing_examples": _minute_gap_rows_to_api(missing[:100]),
        "errors": requirements["errors"],
        "next_action": (
            "strict_tail_backtest_ready"
            if not missing
            else "import historical 1m bars for missing_symbols/missing_dates, then rerun audit and strict backtest"
        ),
    }


def minute_gap_import_template(gap_csv_text: str, *, sample_limit: int = 200) -> str:
    """Build a minute-bar import template scoped to rows from a gap CSV."""

    parsed = _parse_minute_gap_requirements(gap_csv_text)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["vt_symbol", "bar_time", "open", "high", "low", "close", "volume", "turnover"])
    seen: set[tuple[str, date]] = set()
    for item in parsed["items"]:
        key = (item["vt_symbol"], item["trade_date"])
        if key in seen:
            continue
        seen.add(key)
        writer.writerow([item["vt_symbol"], f"{item['trade_date'].isoformat()} 14:56:00", "", "", "", "", "", ""])
        if len(seen) >= max(sample_limit, 1):
            break
    return "\ufeff" + buffer.getvalue()


def minute_gap_vendor_manifest(
    gap_csv_text: str = "",
    *,
    file_path: str = "",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:57",
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Build a provider-facing request manifest from a strict-tail gap CSV."""

    requirements = load_minute_gap_requirements(gap_csv_text, file_path=file_path)
    items = requirements["items"]
    rows = _minute_gap_vendor_rows(items, tail_entry_start, tail_entry_end)
    symbols = sorted({row["vt_symbol"] for row in rows})
    dates = sorted({row["trade_date"] for row in rows})
    return {
        "status": "ready" if rows else "empty",
        "rows_read": requirements["rows_read"],
        "rows_skipped": requirements["rows_skipped"],
        "errors": requirements["errors"],
        "request_count": len(rows),
        "symbol_count": len(symbols),
        "date_count": len(dates),
        "tail_entry_window": f"{tail_entry_start}-{tail_entry_end}",
        "start_date": dates[0].isoformat() if dates else None,
        "end_date": dates[-1].isoformat() if dates else None,
        "symbols": symbols[:500],
        "dates": [item.isoformat() for item in dates[:500]],
        "sample_rows": [_vendor_row_to_api(row) for row in rows[: max(sample_limit, 1)]],
        "required_import_columns": ["vt_symbol", "bar_time", "open", "high", "low", "close", "volume", "turnover"],
        "provider_notes": [
            "每个 vt_symbol + trade_date 需要覆盖 tail_start 至 tail_end 的真实 1 分钟 K 线。",
            "AlphaAgent 导入 CSV 使用 vt_symbol,bar_time,open,high,low,close,volume,turnover。",
            "Tushare Pro 可按 ts_code + start_date/end_date + freq=1min 拉取；返回行必须属于目标 trade_date。",
            "vn.py 数据库可按 symbol/exchange/Interval.MINUTE 查询同一窗口后通过 /api/vnpy/import-minute-bars/gaps 导入。",
        ],
    }


def minute_gap_vendor_manifest_csv(
    gap_csv_text: str = "",
    *,
    file_path: str = "",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:57",
) -> str:
    """Return a provider-facing CSV request list for strict-tail gaps."""

    requirements = load_minute_gap_requirements(gap_csv_text, file_path=file_path)
    rows = _minute_gap_vendor_rows(requirements["items"], tail_entry_start, tail_entry_end)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "vt_symbol",
            "symbol",
            "exchange",
            "tushare_ts_code",
            "trade_date",
            "tail_start",
            "tail_end",
            "start_datetime",
            "end_datetime",
            "reference_date",
            "ma5",
            "alphaagent_import_columns",
            "note",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["vt_symbol"],
                row["symbol"],
                row["exchange"],
                row["tushare_ts_code"],
                row["trade_date"].isoformat(),
                row["tail_start"],
                row["tail_end"],
                row["start_datetime"],
                row["end_datetime"],
                row["reference_date"].isoformat() if row.get("reference_date") else "",
                row.get("ma5") if row.get("ma5") is not None else "",
                "vt_symbol,bar_time,open,high,low,close,volume,turnover",
                "return all real 1m bars in [tail_start, tail_end] for this symbol-date",
            ]
        )
    return "\ufeff" + buffer.getvalue()


def load_minute_gap_requirements(gap_csv_text: str = "", *, file_path: str = "") -> dict[str, Any]:
    """Load strict-tail gap requirements from inline CSV text or an allowed file."""

    if str(file_path or "").strip():
        resolved = _allowed_import_file(file_path)
        with resolved.open("r", encoding="utf-8-sig", newline="") as file:
            return _parse_minute_gap_reader(csv.DictReader(file))
    if not str(gap_csv_text or "").strip():
        return {"items": [], "rows_read": 0, "rows_skipped": 0, "errors": ["CSV is empty"]}
    return _parse_minute_gap_requirements(gap_csv_text)


def _minute_gap_vendor_rows(items: list[dict[str, Any]], tail_entry_start: str, tail_entry_end: str) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[str, date]] = set()
    start_time = _parse_time_value(tail_entry_start)
    end_time = _parse_time_value(tail_entry_end)
    for item in sorted(items, key=lambda value: (value["trade_date"], value["vt_symbol"])):
        key = (item["vt_symbol"], item["trade_date"])
        if key in seen:
            continue
        seen.add(key)
        symbol, exchange = _split_vt_symbol(item["vt_symbol"])
        rows.append(
            {
                "vt_symbol": item["vt_symbol"],
                "symbol": symbol,
                "exchange": exchange,
                "tushare_ts_code": _tushare_ts_code(symbol, exchange),
                "trade_date": item["trade_date"],
                "tail_start": start_time,
                "tail_end": end_time,
                "start_datetime": f"{item['trade_date'].isoformat()} {start_time}:00",
                "end_datetime": f"{item['trade_date'].isoformat()} {end_time}:00",
                "reference_date": item.get("reference_date"),
                "ma5": item.get("ma5"),
            }
        )
    return rows


def _split_vt_symbol(value: str) -> tuple[str, str]:
    parts = str(value or "").strip().upper().split(".")
    if len(parts) != 2:
        return str(value or "").strip().upper(), ""
    return parts[0], parts[1]


def _tushare_ts_code(symbol: str, exchange: str) -> str:
    suffix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(exchange, exchange)
    return f"{symbol}.{suffix}" if symbol and suffix else symbol


def _vendor_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "trade_date": row["trade_date"].isoformat() if isinstance(row.get("trade_date"), date) else row.get("trade_date"),
        "reference_date": row["reference_date"].isoformat() if isinstance(row.get("reference_date"), date) else row.get("reference_date"),
    }


def _parse_minute_gap_requirements(gap_csv_text: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(gap_csv_text.lstrip("\ufeff")))
    return _parse_minute_gap_reader(reader)


def _parse_minute_gap_reader(reader: csv.DictReader) -> dict[str, Any]:
    if not reader.fieldnames:
        return {"items": [], "rows_read": 0, "rows_skipped": 0, "errors": ["CSV header is missing"]}

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, date]] = set()
    errors: list[str] = []
    rows_read = 0
    rows_skipped = 0
    for row in reader:
        rows_read += 1
        normalized = {_normalize_csv_key(key): value for key, value in row.items()}
        try:
            vt_symbol_value = str(normalized.get("vt_symbol") or "").strip().upper()
            if not vt_symbol_value:
                symbol, exchange = _minute_csv_symbol_exchange(normalized)
                vt_symbol_value = vt_symbol(symbol, normalize_exchange(symbol, exchange))
            trade_date = _parse_date(
                normalized.get("trade_date")
                or normalized.get("bar_date")
                or normalized.get("date")
            )
            if trade_date is None:
                raise ValueError("missing or invalid trade_date")
            key = (vt_symbol_value, trade_date)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "vt_symbol": vt_symbol_value,
                    "trade_date": trade_date,
                    "reference_date": _parse_date(normalized.get("reference_date")),
                    "ma5": _optional_number(normalized, "ma5"),
                    "window": str(normalized.get("window") or "").strip(),
                }
            )
        except ValueError as exc:
            rows_skipped += 1
            if len(errors) < 20:
                errors.append(f"row {rows_read}: {exc}")
    return {"items": items, "rows_read": rows_read, "rows_skipped": rows_skipped, "errors": errors}


def _allowed_import_file(file_path: str) -> Path:
    text_path = str(file_path or "").strip()
    if not text_path:
        raise DataSyncError("CSV file path is empty")
    raw_path = Path(text_path)
    resolved = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
    resolved = resolved.resolve()
    allowed_roots = []
    for directory in ALLOWED_IMPORT_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
        allowed_roots.append(directory.resolve())
    if not resolved.is_file():
        raise DataSyncError(f"CSV file not found: {file_path}")
    if resolved.suffix.lower() != ".csv":
        raise DataSyncError("Only .csv files are allowed")
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        allowed = ", ".join(str(root.relative_to(PROJECT_ROOT)) for root in allowed_roots)
        raise DataSyncError(f"CSV file must be under one of: {allowed}")
    return resolved


def _minute_gap_coverage_counts(
    items: list[dict[str, Any]],
    interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
) -> dict[tuple[str, date], int]:
    if not items:
        return {}
    vt_symbols = sorted({item["vt_symbol"] for item in items})
    dates = sorted({item["trade_date"] for item in items})
    start_time = _parse_time_value(tail_entry_start)
    end_time = _parse_time_value(tail_entry_end)
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_minute_bars.c.vt_symbol,
                schema.stock_minute_bars.c.trade_date,
                func.count().label("bar_count"),
            )
            .where(
                schema.stock_minute_bars.c.vt_symbol.in_(vt_symbols),
                schema.stock_minute_bars.c.trade_date >= dates[0],
                schema.stock_minute_bars.c.trade_date <= dates[-1],
                schema.stock_minute_bars.c.interval == interval,
                func.to_char(schema.stock_minute_bars.c.bar_time, "HH24:MI") >= start_time,
                func.to_char(schema.stock_minute_bars.c.bar_time, "HH24:MI") <= end_time,
            )
            .group_by(schema.stock_minute_bars.c.vt_symbol, schema.stock_minute_bars.c.trade_date)
        ).mappings().all()
    return {(str(row["vt_symbol"]), row["trade_date"]): int(row["bar_count"] or 0) for row in rows}


def _parse_time_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("time is empty")
    try:
        parsed = datetime.strptime(text[:5], "%H:%M")
    except ValueError as exc:
        raise ValueError(f"invalid HH:MM time: {text}") from exc
    return parsed.strftime("%H:%M")


def _minute_gap_rows_to_api(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        result.append(
            {
                **row,
                "trade_date": row["trade_date"].isoformat() if isinstance(row.get("trade_date"), date) else row.get("trade_date"),
                "reference_date": row["reference_date"].isoformat() if isinstance(row.get("reference_date"), date) else row.get("reference_date"),
            }
        )
    return result


def _usage_capabilities() -> list[dict[str, Any]]:
    caps = [
        {"name": "stock_list", "table": "stocks", "description": "全 A 股票清单"},
        {"name": "stock_daily_bars", "table": "stock_daily_bars", "description": "股票日 K 线"},
        {"name": "stock_minute_bars", "table": "stock_minute_bars", "description": "股票分钟 K 线 / 尾盘入场验证"},
        {"name": "sector_list", "table": "sectors", "description": "板块 / 概念清单"},
        {"name": "sector_members", "table": "sector_memberships", "description": "板块成分股"},
        {"name": "stock_sectors", "table": "stock_sector_memberships", "description": "股票-板块反向索引"},
        {"name": "business_segments", "table": "stock_business_segments", "description": "主营构成"},
        {"name": "shenwan_industry_tree", "table": "shenwan_industries", "description": "申万行业分类"},
        {"name": "shenwan_industry_members", "table": "shenwan_industry_members", "description": "申万行业成分股"},
        {"name": "shenwan_industry_chain", "table": "industry_chain_edges", "description": "供应链关系"},
        {"name": "industry_board_mapping", "table": "industry_board_mapping", "description": "行业-板块映射"},
        # ── Research capabilities ──
        {"name": "sector_daily_bars", "table": "sector_daily_bars", "description": "板块历史 K 线"},
        {"name": "sector_daily_metrics", "table": "sector_daily_metrics", "description": "板块每日指标"},
        {"name": "sector_period_scores", "table": "sector_period_scores", "description": "板块周期评分"},
        {"name": "sector_relation_edges", "table": "sector_relation_edges", "description": "板块关系图"},
        {"name": "industry_chain_nodes", "table": "industry_chain_nodes", "description": "产业链节点"},
        {"name": "stock_financial_reports", "table": "stock_financial_reports", "description": "个股财报"},
        {"name": "stock_events", "table": "stock_events", "description": "个股事件"},
        {"name": "stock_fund_flows", "table": "stock_fund_flows", "description": "个股资金流"},
        {"name": "sector_fund_flows", "table": "sector_fund_flows", "description": "板块资金流"},
        {"name": "stock_hot_ranks", "table": "stock_hot_ranks", "description": "个股热度"},
        {"name": "stock_lhb_records", "table": "stock_lhb_records", "description": "龙虎榜"},
    ]
    if not is_database_configured():
        for cap in caps:
            cap["status"] = "unavailable"
            cap["count"] = 0
            cap["message"] = "DATABASE_URL not configured"
        return caps
    try:
        with session_scope() as session:
            for cap in caps:
                table_obj = getattr(schema, cap["table"], None)
                if table_obj is None:
                    cap["status"] = "unknown"
                    cap["count"] = 0
                    continue
                try:
                    count = session.execute(select(func.count()).select_from(table_obj)).scalar() or 0
                    cap["status"] = "ready" if count > 0 else "empty"
                    cap["count"] = count
                except Exception as exc:
                    cap["status"] = "unavailable"
                    cap["count"] = 0
                    cap["message"] = exc.__class__.__name__
    except Exception as exc:
        for cap in caps:
            cap["status"] = "unavailable"
            cap["count"] = 0
            cap["message"] = exc.__class__.__name__
    return caps


def _default_sources(status: str, message: str) -> list[dict[str, Any]]:
    return [
        {
            **source,
            "status": status,
            "message": message,
            "checked_at": "",
        }
        for source in DEFAULT_SOURCE.values()
    ]


def _default_jobs(status: str, message: str) -> list[dict[str, Any]]:
    return [
        {
            "id": job.id,
            "name": job.name,
            "description": job.description,
            "source_id": job.source_id,
            "target_table": job.target_table,
            "enabled": False,
            "default_params": job.default_params,
            "schedule_cron": job.schedule_cron,
            "last_status": status,
            "last_run_id": None,
            "last_started_at": None,
            "message": message,
        }
        for job in DEFAULT_JOBS
    ]


# ─── Run job ─────────────────────────────────────────────────────────────

def run_job(job_id: str, params: dict[str, Any] | None = None, progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Execute a sync job immediately (synchronous, in-process)."""
    if not is_database_configured():
        raise DataSyncError("DATABASE_URL is not configured")

    run_params = params or {}

    # Resolve job definition
    job_def: JobDefinition | None = None
    for job in DEFAULT_JOBS:
        if job.id == job_id:
            job_def = job
            break
    if job_def is None:
        raise DataSyncError(f"Unknown job: {job_id}")

    # Resolve runner method
    method_name = JOB_RUNNERS.get(job_id)
    if not method_name:
        raise DataSyncError(f"No runner registered for job: {job_id}")

    # Create run record
    run_id = _create_run(job_id, run_params)
    try:
        runner = DataSyncRunner(progress=progress)
        method = getattr(runner, method_name)
        merged_params = {**job_def.default_params, **run_params}
        result = method(merged_params)
        _finish_run(run_id, "succeeded", rows_read=result.get("rows_read", 0), rows_written=result.get("rows_written", 0))
        return {
            "run_id": run_id,
            "job_id": job_id,
            "status": "succeeded",
            **result,
        }
    except Exception as exc:
        _finish_run(run_id, "failed", message=str(exc), error_type=exc.__class__.__name__)
        raise DataSyncError(str(exc)) from exc


# ─── Scheduler ────────────────────────────────────────────────────────────

def start_data_sync_scheduler() -> None:
    """Start a background thread that runs scheduled jobs."""
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, name="data-sync-scheduler", daemon=True)
    _scheduler_thread.start()
    logger.info("Data sync scheduler started")


def stop_data_sync_scheduler() -> None:
    """Signal the scheduler to stop."""
    _scheduler_stop.set()


def _scheduler_loop() -> None:
    """Main scheduler loop — wakes up every 60 seconds."""
    while not _scheduler_stop.is_set():
        try:
            _run_scheduled_jobs()
        except Exception as exc:
            logger.error("Scheduler tick error: %s", exc)
        _scheduler_stop.wait(timeout=60)


def _run_scheduled_jobs() -> None:
    """Check and run jobs whose cron schedule matches current time."""
    now = datetime.now(timezone.utc)
    # Convert to China timezone for cron matching
    china_tz = timezone(timedelta(hours=8))
    now_china = now.astimezone(china_tz)

    with session_scope() as session:
        rows = session.execute(
            select(schema.sync_job_definitions).where(schema.sync_job_definitions.c.enabled == True)  # noqa: E712
        ).mappings().all()

    for row in rows:
        job_id = str(row["id"])
        schedule_cron = row.get("schedule_cron")
        if not schedule_cron:
            continue
        last_status = row.get("last_status")
        last_started = row.get("last_started_at")
        # Simple throttle: don't re-run within 30 minutes
        if last_started is not None:
            if hasattr(last_started, "tzinfo") and last_started.tzinfo is None:
                last_started = last_started.replace(tzinfo=timezone.utc)
            elapsed = (now - last_started).total_seconds()
            if elapsed < 1800:
                continue
        # Very simple cron matching: check if minute and hour match
        try:
            if _cron_matches(schedule_cron, now_china):
                try:
                    run_job(job_id)
                except Exception as exc:
                    logger.warning("Scheduled job %s failed: %s", job_id, exc)
        except Exception:
            pass


def _cron_matches(cron_expr: str, now: datetime) -> bool:
    """Minimal cron matcher — supports minute/hour/day-of-month/month/day-of-week."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    minute_pat, hour_pat, dom_pat, month_pat, dow_pat = parts

    def _field_matches(pattern: str, value: int) -> bool:
        if pattern == "*":
            return True
        for part in pattern.split(","):
            if part == "*":
                return True
            if "/" in part:
                base, step = part.split("/", 1)
                base_val = int(base) if base != "*" else 0
                step_val = int(step)
                return (value - base_val) % step_val == 0
            if "-" in part:
                low, high = part.split("-", 1)
                if int(low) <= value <= int(high):
                    return True
            elif int(part) == value:
                return True
        return False

    return (
        _field_matches(minute_pat, now.minute)
        and _field_matches(hour_pat, now.hour)
        and _field_matches(dom_pat, now.day)
        and _field_matches(month_pat, now.month)
        and _field_matches(dow_pat, now.weekday())
    )


# ─── Local query functions ───────────────────────────────────────────────

def local_list_stocks(
    page: int = 1,
    page_size: int = 50,
    sort: str = "mktcap",
    q: str = "",
    order: str = "desc",
) -> dict[str, Any] | None:
    """Read stocks from local DB, return None if empty."""
    # Map frontend sort keys to DB columns (descending by default)
    _sort_col_map = {
        "mktcap": schema.stocks.c.market_cap,
        "market_cap": schema.stocks.c.market_cap,
        "amount": schema.stocks.c.turnover,
        "turnover": schema.stocks.c.turnover,
        "changepercent": schema.stocks.c.change_pct,
        "change_pct": schema.stocks.c.change_pct,
        "turnoverratio": schema.stocks.c.turnover_rate,
        "turnover_rate": schema.stocks.c.turnover_rate,
        "volume_ratio": schema.stocks.c.volume_ratio,
        "volumeratio": schema.stocks.c.volume_ratio,
        "pe": schema.stocks.c.pe,
        "pb": schema.stocks.c.pb,
    }
    sort_col = _sort_col_map.get(sort.strip().lower(), schema.stocks.c.market_cap)

    try:
        with session_scope() as session:
            query = select(schema.stocks)
            normalized_q = q.strip().lower()
            if normalized_q:
                query = query.where(
                    (schema.stocks.c.name.ilike(f"%{normalized_q}%"))
                    | (schema.stocks.c.symbol.ilike(f"%{normalized_q}%"))
                    | (schema.stocks.c.vt_symbol.ilike(f"%{normalized_q}%"))
                )
            total = session.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
            sort_expr = sort_col.asc().nulls_last() if order.strip().lower() == "asc" else sort_col.desc().nulls_last()
            query = query.order_by(sort_expr)
            offset = (max(page, 1) - 1) * min(max(page_size, 1), 200)
            query = query.offset(offset).limit(min(max(page_size, 1), 200))
            rows = session.execute(query).mappings().all()
        if not rows and not q:
            return None
        items = [_stock_db_row_to_api(dict(row)) for row in rows]
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "source": "postgresql",
            "data_origin": "local_db",
            "storage_table": "stocks",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def local_list_sectors(sector_type: str = "") -> dict[str, Any] | None:
    """Read sectors from local DB."""
    try:
        with session_scope() as session:
            query = select(schema.sectors)
            if sector_type.strip():
                query = query.where(schema.sectors.c.type == sector_type.strip())
            rows = session.execute(query.order_by(schema.sectors.c.name)).mappings().all()
        if not rows:
            return None
        items = [_sector_db_row_to_api(dict(row)) for row in rows]
        return {
            "items": items,
            "total": len(items),
            "type": sector_type or "all",
            "source": "postgresql",
            "data_origin": "local_db",
            "storage_table": "sectors",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def local_sector_stocks(
    sector_id: str,
    page: int = 1,
    page_size: int = 50,
    sort: str = "changepercent",
    with_returns: bool = False,
    q: str = "",
) -> dict[str, Any] | None:
    """Read sector members from local DB."""
    try:
        with session_scope() as session:
            query = select(schema.sector_memberships).where(
                schema.sector_memberships.c.sector_id == sector_id
            )
            normalized_q = q.strip().lower()
            if normalized_q:
                query = query.where(
                    (schema.sector_memberships.c.name.ilike(f"%{normalized_q}%"))
                    | (schema.sector_memberships.c.symbol.ilike(f"%{normalized_q}%"))
                )
            total = session.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
            offset = (max(page, 1) - 1) * min(max(page_size, 1), 200)
            rows = session.execute(query.offset(offset).limit(min(max(page_size, 1), 200))).mappings().all()
        if not rows and total == 0:
            return None
        items = [_sector_member_db_row_to_api(dict(row)) for row in rows]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "sector_id": sector_id,
            "source": "postgresql",
            "data_origin": "local_db",
            "storage_table": "sector_memberships",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def local_sector_trend(sector_id: str) -> dict[str, Any] | None:
    """Compute sector breadth from local DB."""
    try:
        with session_scope() as session:
            rows = session.execute(
                select(schema.sector_memberships).where(
                    schema.sector_memberships.c.sector_id == sector_id
                )
            ).mappings().all()
        if not rows:
            return None
        items = [_sector_member_db_row_to_api(dict(row)) for row in rows]
        changes = [item.get("change_pct") for item in items if item.get("change_pct") is not None]
        valid_changes = [float(c) for c in changes]
        rise_count = sum(1 for c in valid_changes if c > 0)
        fall_count = sum(1 for c in valid_changes if c < 0)
        avg = sum(valid_changes) / len(valid_changes) if valid_changes else None
        return {
            "sector_id": sector_id,
            "trend_state": "UP" if avg and avg >= 1 else "DOWN" if avg and avg <= -1 else "RANGE",
            "sample_size": len(valid_changes),
            "rise_count": rise_count,
            "fall_count": fall_count,
            "avg_change_pct": avg,
            "source": "postgresql",
            "data_origin": "local_db",
            "storage_table": "sector_memberships",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def local_stock_bars(
    symbol: str,
    exchange: str | None = None,
    limit: int = 90,
    interval: str = "1d",
) -> dict[str, Any] | None:
    """Read stock daily bars from local DB.

    Only serves daily/weekly/monthly intervals — minute-level bars are not
    stored locally and must come from the live AkShare API instead.
    """
    # Minute intervals are not available in local DB — let caller fall through
    # to the live AkShare data source which does return intraday bars.
    if interval in {"1m", "5m", "15m", "30m", "60m"}:
        return None

    try:
        normalized = normalize_exchange(symbol, exchange)
        vts = vt_symbol(symbol, normalized)
        with session_scope() as session:
            rows = session.execute(
                select(schema.stock_daily_bars)
                .where(schema.stock_daily_bars.c.vt_symbol == vts)
                .order_by(desc(schema.stock_daily_bars.c.trade_date))
                .limit(min(max(limit, 1), 1000))
            ).mappings().all()
        if not rows:
            return None
        # Reverse to chronological order
        items = [_bar_db_row_to_api(dict(row)) for row in reversed(rows)]
        return {
            "symbol": symbol,
            "exchange": normalized,
            "vt_symbol": vts,
            "interval": interval,
            "items": items,
            "source": "postgresql",
            "data_origin": "local_db",
            "storage_table": "stock_daily_bars",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def local_stock_sectors(
    symbol: str,
    exchange: str | None = None,
) -> dict[str, Any] | None:
    """Read stock-sector memberships from local DB."""
    try:
        normalized = normalize_exchange(symbol, exchange)
        vts = vt_symbol(symbol, normalized)
        with session_scope() as session:
            rows = session.execute(
                select(schema.stock_sector_memberships)
                .where(schema.stock_sector_memberships.c.vt_symbol == vts)
            ).mappings().all()
        if not rows:
            return None
        items = [_stock_sector_row_to_api(dict(row)) for row in rows]
        return {
            "vt_symbol": vts,
            "items": items,
            "source": "postgresql",
            "data_origin": "local_db",
            "storage_table": "stock_sector_memberships",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


# ─── Local Shenwan query functions ───────────────────────────────────────

def local_shenwan_industry_tree(level: int = 1) -> dict[str, Any] | None:
    """Read Shenwan industry tree from local DB."""
    try:
        with session_scope() as session:
            rows = session.execute(
                select(schema.shenwan_industries)
                .where(schema.shenwan_industries.c.level == level)
                .order_by(schema.shenwan_industries.c.code)
            ).mappings().all()
        if not rows:
            return None
        items = [_shenwan_industry_row_to_api(dict(row)) for row in rows]
        return {
            "items": items,
            "level": level,
            "total": len(items),
            "source": "postgresql",
            "data_origin": "local_db",
            "storage_table": "shenwan_industries",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def local_shenwan_industry_detail(code: str) -> dict[str, Any] | None:
    """Read Shenwan industry detail from local DB."""
    try:
        with session_scope() as session:
            row = session.execute(
                select(schema.shenwan_industries)
                .where(schema.shenwan_industries.c.code == code)
            ).mappings().first()
        if not row:
            return None
        industry = _shenwan_industry_row_to_api(dict(row))
        # Load members
        member_rows = session.execute(
            select(schema.shenwan_industry_members)
            .where(schema.shenwan_industry_members.c.industry_code == code)
        ).mappings().all()
        members = [_shenwan_member_row_to_api(dict(m)) for m in member_rows]
        industry["top_stocks"] = members[:50]
        industry["stock_count"] = len(members)
        # Load board mappings
        mapping_rows = session.execute(
            select(schema.industry_board_mapping)
            .where(schema.industry_board_mapping.c.industry_code == code)
        ).mappings().all()
        industry["related_boards"] = [
            {
                "board_id": m["board_id"],
                "board_name": m["board_name"],
                "board_type": m["board_type"],
                "overlap_count": m["overlap_count"],
                "overlap_ratio": m["overlap_ratio"],
            }
            for m in mapping_rows
        ]
        industry["source"] = "postgresql"
        industry["data_origin"] = "local_db"
        industry["storage_table"] = "shenwan_industries"
        industry["fallback_used"] = False
        return industry
    except Exception:
        return None


def local_shenwan_industry_graph(code: str, level: int = 2) -> dict[str, Any] | None:
    """Build industry chain graph from local DB data."""
    try:
        with session_scope() as session:
            # Get the industry
            row = session.execute(
                select(schema.shenwan_industries)
                .where(schema.shenwan_industries.c.code == code)
            ).mappings().first()
            if not row:
                return None
            industry_name = str(row["name"])
            # Get related edges
            edge_rows = session.execute(
                select(schema.industry_chain_edges).where(
                    (schema.industry_chain_edges.c.source_industry_code == code)
                    | (schema.industry_chain_edges.c.target_industry_code == code)
                )
            ).mappings().all()
            if not edge_rows:
                # Return just the single node
                return {
                    "industry_code": code,
                    "industry_name": industry_name,
                    "level": level,
                    "nodes": [_shenwan_industry_row_to_api(dict(row))],
                    "edges": [],
                    "source": "postgresql",
                    "data_origin": "local_db",
                    "status": "ready",
                    "fallback_used": False,
                }
            # Collect all industry codes from edges
            codes = {code}
            for edge in edge_rows:
                codes.add(str(edge["source_industry_code"]))
                codes.add(str(edge["target_industry_code"]))
            # Load all related industries
            ind_rows = session.execute(
                select(schema.shenwan_industries)
                .where(schema.shenwan_industries.c.code.in_(codes))
            ).mappings().all()
            nodes = [_shenwan_industry_row_to_api(dict(r)) for r in ind_rows]
            edges = [
                {
                    "source_industry_code": str(e["source_industry_code"]),
                    "target_industry_code": str(e["target_industry_code"]),
                    "relationship_type": str(e["relationship_type"]),
                    "strength": float(e["strength"]),
                    "evidence_count": int(e["evidence_count"]),
                    "evidence_detail": e["evidence_detail"],
                }
                for e in edge_rows
            ]
            # Resolve names
            edges = _resolve_edge_names(edges, ind_rows)
            return {
                "industry_code": code,
                "industry_name": industry_name,
                "level": level,
                "nodes": nodes,
                "edges": edges,
                "source": "postgresql",
                "data_origin": "local_db",
                "status": "ready",
                "fallback_used": False,
            }
    except Exception:
        return None


# ─── Local sector relation graph helpers (for industry_chains.py) ────────

def local_sector_relation_graph(
    query: str,
    limit: int = 12,
) -> dict[str, Any] | None:
    """Try to build a sector relation graph from local DB data.

    Returns None if local data is insufficient (triggers live fallback).
    """
    try:
        with session_scope() as session:
            # Load sectors that match query
            q = select(schema.sectors)
            if query.strip():
                q = q.where(schema.sectors.c.name.ilike(f"%{query.strip()}%"))
            q = q.limit(min(max(limit, 1), 50))
            sector_rows = session.execute(q).mappings().all()
        if not sector_rows:
            return None
        nodes = [_sector_db_row_to_api(dict(r)) for r in sector_rows]
        # Build edges from shared members (constituent overlap)
        sector_ids = [str(r["id"]) for r in sector_rows]
        with session_scope() as session:
            member_rows = session.execute(
                select(schema.sector_memberships)
                .where(schema.sector_memberships.c.sector_id.in_(sector_ids))
            ).mappings().all()
        # Build sector_id -> set(vt_symbol)
        members_by_sector: dict[str, set[str]] = {}
        for m in member_rows:
            sid = str(m["sector_id"])
            members_by_sector.setdefault(sid, set()).add(str(m["vt_symbol"]))
        edges: list[dict[str, Any]] = []
        for i, sid_a in enumerate(sector_ids):
            for sid_b in sector_ids[i + 1:]:
                set_a = members_by_sector.get(sid_a, set())
                set_b = members_by_sector.get(sid_b, set())
                if not set_a or not set_b:
                    continue
                shared = set_a & set_b
                if not shared:
                    continue
                min_size = max(min(len(set_a), len(set_b)), 1)
                ratio = len(shared) / min_size
                if ratio < 0.10:
                    continue
                edges.append({
                    "source": sid_a,
                    "target": sid_b,
                    "shared_stock_count": len(shared),
                    "shared_stock_ratio": round(ratio * 100, 2),
                    "score": round(min(ratio * 72 + ratio * 18, 100), 2),
                    "evidence_level": "strong" if ratio >= 0.20 else "weak",
                })
        if not edges and not query.strip():
            return None
        return {
            "query": query,
            "nodes": nodes,
            "edges": edges,
            "clusters": [],
            "central_nodes": [],
            "algorithm": {
                "name": "local_sector_constituent_overlap",
                "node_basis": "PostgreSQL 本地板块数据 + 成分股交集",
            },
            "status": "ready" if nodes else "empty",
            "source": "postgresql",
            "data_origin": "local_db",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def local_sector_stub_graph(
    query: str,
    limit: int = 12,
) -> dict[str, Any] | None:
    """Return a minimal stub graph from local sectors when no edges exist."""
    try:
        with session_scope() as session:
            rows = session.execute(
                select(schema.sectors).limit(min(max(limit, 1), 50))
            ).mappings().all()
        if not rows:
            return None
        nodes = [_sector_db_row_to_api(dict(r)) for r in rows]
        return {
            "query": query,
            "nodes": nodes,
            "edges": [],
            "clusters": [],
            "central_nodes": [],
            "algorithm": {"name": "local_sector_stub"},
            "status": "ready" if nodes else "empty",
            "source": "postgresql",
            "data_origin": "local_db",
            "fallback_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


# ─── Run record helpers ──────────────────────────────────────────────────

def _create_run(job_id: str, params: dict[str, Any]) -> int:
    with session_scope() as session:
        result = session.execute(
            schema.sync_job_runs.insert().values(
                job_id=job_id,
                status="running",
                params=params,
            )
        )
        session.flush()
        run_id = result.inserted_primary_key[0]
        # Update job definition last_status
        session.execute(
            schema.sync_job_definitions.update()
            .where(schema.sync_job_definitions.c.id == job_id)
            .values(
                last_status="running",
                last_run_id=run_id,
                last_started_at=datetime.now(timezone.utc),
            )
        )
        return int(run_id)


def _finish_run(
    run_id: int,
    status: str,
    *,
    rows_read: int = 0,
    rows_written: int = 0,
    message: str | None = None,
    error_type: str | None = None,
) -> None:
    with session_scope() as session:
        session.execute(
            schema.sync_job_runs.update()
            .where(schema.sync_job_runs.c.id == run_id)
            .values(
                status=status,
                rows_read=rows_read,
                rows_written=rows_written,
                message=message,
                error_type=error_type,
                finished_at=datetime.now(timezone.utc),
            )
        )
        # Update job definition
        run_row = session.execute(
            select(schema.sync_job_runs).where(schema.sync_job_runs.c.id == run_id)
        ).mappings().first()
        if run_row:
            job_id = str(run_row["job_id"])
            update_vals: dict[str, Any] = {
                "last_status": status,
                "last_finished_at": datetime.now(timezone.utc),
            }
            if message:
                update_vals["last_message"] = message[:500]
            session.execute(
                schema.sync_job_definitions.update()
                .where(schema.sync_job_definitions.c.id == job_id)
                .values(**update_vals)
            )


# ─── Upsert helpers ──────────────────────────────────────────────────────

def _upsert_stocks(items: list[dict[str, Any]]) -> int:
    """Upsert stock rows into the stocks table."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            symbol = str(item.get("symbol") or "")
            exchange = str(item.get("exchange") or normalize_exchange(symbol))
            vts = vt_symbol(symbol, exchange)
            values = {
                "vt_symbol": vts,
                "symbol": symbol,
                "exchange": exchange,
                "name": str(item.get("name") or symbol),
                "industry": item.get("industry"),
                "area": item.get("area"),
                "last_price": item.get("last_price"),
                "change_pct": item.get("change_pct"),
                "return_5d": item.get("return_5d"),
                "return_10d": item.get("return_10d"),
                "return_20d": item.get("return_20d"),
                "turnover": item.get("turnover"),
                "market_cap": item.get("market_cap"),
                "pe": item.get("pe"),
                "pb": item.get("pb"),
                "turnover_rate": item.get("turnover_rate"),
                "volume_ratio": item.get("volume_ratio"),
                "trade_time": item.get("trade_time"),
                "source": str(item.get("source") or "akshare"),
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stocks).where(schema.stocks.c.vt_symbol == vts)
            ).first()
            if existing:
                session.execute(
                    schema.stocks.update().where(schema.stocks.c.vt_symbol == vts).values(**values)
                )
            else:
                session.execute(schema.stocks.insert().values(**values))
            written += 1
    return written


def _upsert_sectors(items: list[dict[str, Any]]) -> int:
    """Upsert sector rows."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            sector_id = str(item.get("id") or item.get("akshare_symbol") or "")
            if not sector_id:
                continue
            name = str(item.get("name") or "")
            if not name:
                continue
            sector_type = str(item.get("type") or "concept")
            values = {
                "id": sector_id,
                "name": name,
                "type": sector_type,
                "category": item.get("category"),
                "path": item.get("path") or [],
                "stock_count": item.get("stock_count"),
                "change_pct": item.get("change_pct"),
                "market_cap": item.get("market_cap"),
                "turnover_rate": item.get("turnover_rate"),
                "rise_count": item.get("rise_count"),
                "fall_count": item.get("fall_count"),
                "leader_stock": item.get("leader_stock"),
                "leader_change_pct": item.get("leader_change_pct"),
                "source": str(item.get("source") or "akshare"),
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.sectors).where(schema.sectors.c.id == sector_id)
            ).first()
            if existing:
                session.execute(
                    schema.sectors.update().where(schema.sectors.c.id == sector_id).values(**values)
                )
            else:
                session.execute(schema.sectors.insert().values(**values))
            written += 1
    return written


def _upsert_sector_memberships(sector_id: str, items: list[dict[str, Any]]) -> int:
    """Upsert sector membership rows for a single sector."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            symbol = str(item.get("symbol") or "")
            exchange = str(item.get("exchange") or normalize_exchange(symbol))
            vts = vt_symbol(symbol, exchange)
            name = str(item.get("name") or symbol)
            values = {
                "sector_id": sector_id,
                "vt_symbol": vts,
                "symbol": symbol,
                "exchange": exchange,
                "name": name,
                "change_pct": item.get("change_pct"),
                "return_5d": item.get("return_5d"),
                "return_10d": item.get("return_10d"),
                "return_20d": item.get("return_20d"),
                "turnover": item.get("turnover"),
                "market_cap": item.get("market_cap"),
                "source": str(item.get("source") or "akshare"),
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.sector_memberships).where(
                    (schema.sector_memberships.c.sector_id == sector_id)
                    & (schema.sector_memberships.c.vt_symbol == vts)
                )
            ).first()
            if existing:
                session.execute(
                    schema.sector_memberships.update()
                    .where((schema.sector_memberships.c.sector_id == sector_id) & (schema.sector_memberships.c.vt_symbol == vts))
                    .values(**values)
                )
            else:
                session.execute(schema.sector_memberships.insert().values(**values))
            written += 1
    return written


def _upsert_stock_sector_memberships(items: list[dict[str, Any]]) -> int:
    """Upsert stock-sector membership index rows."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            vts = str(item.get("vt_symbol") or "")
            sector_id = str(item.get("sector_id") or "")
            if not vts or not sector_id:
                continue
            values = {
                "vt_symbol": vts,
                "sector_id": sector_id,
                "sector_name": str(item.get("sector_name") or ""),
                "sector_type": str(item.get("sector_type") or "concept"),
                "rank": item.get("rank"),
                "confirmed": item.get("confirmed"),
                "is_precise": item.get("is_precise"),
                "source": str(item.get("source") or "akshare"),
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stock_sector_memberships).where(
                    (schema.stock_sector_memberships.c.vt_symbol == vts)
                    & (schema.stock_sector_memberships.c.sector_id == sector_id)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_sector_memberships.update()
                    .where(
                        (schema.stock_sector_memberships.c.vt_symbol == vts)
                        & (schema.stock_sector_memberships.c.sector_id == sector_id)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_sector_memberships.insert().values(**values))
            written += 1
    return written


def _upsert_daily_bars(symbol: str, exchange: str, items: list[dict[str, Any]]) -> int:
    """Upsert daily bar rows for a single stock."""
    if not items:
        return 0
    normalized = normalize_exchange(symbol, exchange)
    vts = vt_symbol(symbol, normalized)
    written = 0
    with session_scope() as session:
        for item in items:
            trade_date_raw = item.get("trade_date")
            if trade_date_raw is None:
                continue
            # Parse trade_date
            if isinstance(trade_date_raw, date):
                trade_date = trade_date_raw
            elif isinstance(trade_date_raw, str):
                try:
                    trade_date = date.fromisoformat(str(trade_date_raw)[:10])
                except ValueError:
                    continue
            else:
                continue
            values = {
                "vt_symbol": vts,
                "trade_date": trade_date,
                "open_price": float(item.get("open") or item.get("open_price") or 0),
                "close_price": float(item.get("close") or item.get("close_price") or 0),
                "high_price": float(item.get("high") or item.get("high_price") or 0),
                "low_price": float(item.get("low") or item.get("low_price") or 0),
                "volume": item.get("volume"),
                "turnover": item.get("turnover"),
                "change_pct": item.get("change_pct"),
                "source": str(item.get("source") or "akshare"),
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stock_daily_bars).where(
                    (schema.stock_daily_bars.c.vt_symbol == vts)
                    & (schema.stock_daily_bars.c.trade_date == trade_date)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_daily_bars.update()
                    .where(
                        (schema.stock_daily_bars.c.vt_symbol == vts)
                        & (schema.stock_daily_bars.c.trade_date == trade_date)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_daily_bars.insert().values(**values))
            written += 1
    return written


def _upsert_minute_bars(
    symbol: str,
    exchange: str,
    items: list[dict[str, Any]],
    interval: str,
    source: str = "akshare",
) -> int:
    """Upsert intraday bar rows for one stock."""
    if not items:
        return 0
    normalized = normalize_exchange(symbol, exchange)
    vts = vt_symbol(symbol, normalized)
    written = 0
    with session_scope() as session:
        exists = session.execute(select(schema.stocks.c.vt_symbol).where(schema.stocks.c.vt_symbol == vts)).scalar()
        if not exists:
            return 0
        for item in items:
            bar_time = _parse_datetime(item.get("trade_date") or item.get("bar_time") or item.get("time"))
            if bar_time is None:
                continue
            values = {
                "vt_symbol": vts,
                "bar_time": bar_time,
                "interval": interval,
                "trade_date": bar_time.date(),
                "open_price": float(item.get("open") or item.get("open_price") or 0),
                "close_price": float(item.get("close") or item.get("close_price") or 0),
                "high_price": float(item.get("high") or item.get("high_price") or 0),
                "low_price": float(item.get("low") or item.get("low_price") or 0),
                "volume": item.get("volume"),
                "turnover": item.get("turnover"),
                "source": str(item.get("source") or source or "akshare"),
                "raw": item.get("raw") or item,
            }
            existing = session.execute(
                select(schema.stock_minute_bars).where(
                    (schema.stock_minute_bars.c.vt_symbol == vts)
                    & (schema.stock_minute_bars.c.bar_time == bar_time)
                    & (schema.stock_minute_bars.c.interval == interval)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_minute_bars.update()
                    .where(
                        (schema.stock_minute_bars.c.vt_symbol == vts)
                        & (schema.stock_minute_bars.c.bar_time == bar_time)
                        & (schema.stock_minute_bars.c.interval == interval)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_minute_bars.insert().values(**values))
            written += 1
    return written


def _rebuild_stock_sector_memberships() -> int:
    """Rebuild stock_sector_memberships from sector_memberships."""
    with session_scope() as session:
        session.execute(text("DELETE FROM stock_sector_memberships"))
    with session_scope() as session:
        rows = session.execute(
            select(schema.sector_memberships).distinct(schema.sector_memberships.c.vt_symbol)
        ).mappings().all()
    items: list[dict[str, Any]] = []
    with session_scope() as session:
        member_rows = session.execute(select(schema.sector_memberships)).mappings().all()
        sector_by_id: dict[str, dict[str, Any]] = {}
        for row in session.execute(select(schema.sectors)).mappings().all():
            sector_by_id[str(row["id"])] = dict(row)
        for m in member_rows:
            sid = str(m["sector_id"])
            sector = sector_by_id.get(sid, {})
            items.append({
                "vt_symbol": str(m["vt_symbol"]),
                "sector_id": sid,
                "sector_name": str(sector.get("name") or sid),
                "sector_type": str(sector.get("type") or "concept"),
                "source": str(m.get("source") or "akshare"),
            })
    return _upsert_stock_sector_memberships(items)


# ─── Shenwan upsert helpers ──────────────────────────────────────────────

def _upsert_shenwan_industries(items: list[dict[str, Any]], level: int) -> int:
    """Upsert Shenwan industry classification rows."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            code = str(item.get("code") or "")
            if not code:
                continue
            name = str(item.get("name") or "")
            if not name:
                continue
            parent_code = item.get("parent_code") or item.get("parent_name") or None
            # If parent_name but not code, try to resolve
            if parent_code and not isinstance(parent_code, str) or (isinstance(parent_code, str) and len(parent_code) > 10):
                parent_code = None  # It's a name, not a code
            values = {
                "code": code,
                "name": name,
                "level": level,
                "parent_code": parent_code,
                "path": item.get("path") or [],
                "stock_count": item.get("stock_count"),
                "change_pct": item.get("change_pct"),
                "market_cap": item.get("market_cap"),
                "source": "akshare.sw_index",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.shenwan_industries).where(schema.shenwan_industries.c.code == code)
            ).first()
            if existing:
                session.execute(
                    schema.shenwan_industries.update()
                    .where(schema.shenwan_industries.c.code == code)
                    .values(**values)
                )
            else:
                session.execute(schema.shenwan_industries.insert().values(**values))
            written += 1
    return written


def _upsert_shenwan_industry_members(industry_code: str, items: list[dict[str, Any]]) -> int:
    """Upsert Shenwan industry member stocks."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            symbol = str(item.get("symbol") or "")
            exchange = str(item.get("exchange") or normalize_exchange(symbol))
            vts = vt_symbol(symbol, exchange)
            name = str(item.get("name") or symbol)
            values = {
                "industry_code": industry_code,
                "vt_symbol": vts,
                "symbol": symbol,
                "exchange": exchange,
                "name": name,
                "market_cap": item.get("market_cap"),
                "change_pct": item.get("change_pct"),
                "source": "akshare.sw_index",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.shenwan_industry_members).where(
                    (schema.shenwan_industry_members.c.industry_code == industry_code)
                    & (schema.shenwan_industry_members.c.vt_symbol == vts)
                )
            ).first()
            if existing:
                session.execute(
                    schema.shenwan_industry_members.update()
                    .where(
                        (schema.shenwan_industry_members.c.industry_code == industry_code)
                        & (schema.shenwan_industry_members.c.vt_symbol == vts)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.shenwan_industry_members.insert().values(**values))
            written += 1
    return written


def _build_industry_board_mapping(adapter: AkShareAdapter) -> int:
    """Build mapping between Shenwan industries and EastMoney boards."""
    # Load industries from DB
    with session_scope() as session:
        industries = session.execute(
            select(schema.shenwan_industries)
        ).mappings().all()
    if not industries:
        return 0
    # Load board lists
    board_items: list[dict[str, Any]] = []
    for board_type in ("concept", "industry"):
        try:
            data = adapter.list_sectors(board_type)
            items = data.get("items") or []
            for item in items:
                item["type"] = board_type
            board_items.extend(items)
        except Exception:
            continue
    # Build name-to-board map
    written = 0
    with session_scope() as session:
        for ind in industries:
            code = str(ind["code"])
            ind_name = str(ind["name"])
            # Find matching boards by name overlap
            level = int(ind["level"])
            for board in board_items:
                board_name = str(board.get("name") or "")
                board_id = str(board.get("id") or board.get("akshare_symbol") or "")
                if not board_name or not board_id:
                    continue
                # Check name similarity
                if ind_name in board_name or board_name in ind_name:
                    # Load members for both to compute overlap
                    overlap_count = 0
                    try:
                        ind_member_count = session.execute(
                            select(func.count()).select_from(schema.shenwan_industry_members)
                            .where(schema.shenwan_industry_members.c.industry_code == code)
                        ).scalar() or 0
                        if ind_member_count == 0:
                            overlap_ratio = 0.0
                        else:
                            # Count shared members
                            sector_member_count = session.execute(
                                select(func.count()).select_from(schema.sector_memberships)
                                .where(schema.sector_memberships.c.sector_id == board_id)
                            ).scalar() or 0
                            if sector_member_count == 0:
                                overlap_ratio = 0.0
                            else:
                                # Get vt_symbols from both
                                ind_symbols = set(
                                    session.execute(
                                        select(schema.shenwan_industry_members.c.vt_symbol)
                                        .where(schema.shenwan_industry_members.c.industry_code == code)
                                    ).scalars().all()
                                )
                                board_symbols = set(
                                    session.execute(
                                        select(schema.sector_memberships.c.vt_symbol)
                                        .where(schema.sector_memberships.c.sector_id == board_id)
                                    ).scalars().all()
                                )
                                overlap_count = len(ind_symbols & board_symbols)
                                overlap_ratio = overlap_count / max(min(len(ind_symbols), len(board_symbols)), 1)
                    except Exception:
                        overlap_ratio = 0.0
                        overlap_count = 0
                    values = {
                        "industry_code": code,
                        "board_id": board_id,
                        "board_name": board_name,
                        "board_type": str(board.get("type") or "concept"),
                        "overlap_count": overlap_count,
                        "overlap_ratio": round(overlap_ratio, 4),
                        "source": "alphaagent_industry_board_mapping",
                    }
                    existing = session.execute(
                        select(schema.industry_board_mapping).where(
                            (schema.industry_board_mapping.c.industry_code == code)
                            & (schema.industry_board_mapping.c.board_id == board_id)
                        )
                    ).first()
                    if existing:
                        session.execute(
                            schema.industry_board_mapping.update()
                            .where(
                                (schema.industry_board_mapping.c.industry_code == code)
                                & (schema.industry_board_mapping.c.board_id == board_id)
                            )
                            .values(**values)
                        )
                    else:
                        session.execute(schema.industry_board_mapping.insert().values(**values))
                    written += 1
    return written


def _upsert_industry_chain_edges(edges: list[dict[str, Any]], level: int) -> int:
    """Upsert supply chain edges inferred by supply_chain service."""
    if not edges:
        return 0
    written = 0
    with session_scope() as session:
        for edge in edges:
            source_code = str(edge.get("source_industry_code") or "")
            target_code = str(edge.get("target_industry_code") or "")
            rel_type = str(edge.get("relationship_type") or "end_product")
            if not source_code or not target_code:
                continue
            values = {
                "source_industry_code": source_code,
                "target_industry_code": target_code,
                "relationship_type": rel_type,
                "strength": float(edge.get("strength") or 0),
                "evidence_count": int(edge.get("evidence_count") or 0),
                "evidence_detail": edge.get("evidence_detail") or [],
                "level": level,
                "source": str(edge.get("source") or "alphaagent_supply_chain_inference"),
            }
            existing = session.execute(
                select(schema.industry_chain_edges).where(
                    (schema.industry_chain_edges.c.source_industry_code == source_code)
                    & (schema.industry_chain_edges.c.target_industry_code == target_code)
                    & (schema.industry_chain_edges.c.relationship_type == rel_type)
                    & (schema.industry_chain_edges.c.level == level)
                )
            ).first()
            if existing:
                session.execute(
                    schema.industry_chain_edges.update()
                    .where(
                        (schema.industry_chain_edges.c.source_industry_code == source_code)
                        & (schema.industry_chain_edges.c.target_industry_code == target_code)
                        & (schema.industry_chain_edges.c.relationship_type == rel_type)
                        & (schema.industry_chain_edges.c.level == level)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.industry_chain_edges.insert().values(**values))
            written += 1
    return written


# ─── API helper functions for DB row conversion ──────────────────────────

def _mapping_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a generic DB row dict to JSON-safe API response."""
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, date):
            result[key] = value.isoformat()
        elif isinstance(value, (bytes, bytearray)):
            continue
        else:
            result[key] = value
    return result


def _stock_db_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a stocks table row to API format."""
    return {
        "symbol": row.get("symbol"),
        "exchange": row.get("exchange"),
        "vt_symbol": row.get("vt_symbol"),
        "name": row.get("name"),
        "last_price": row.get("last_price"),
        "change_pct": row.get("change_pct"),
        "return_5d": row.get("return_5d"),
        "return_10d": row.get("return_10d"),
        "return_20d": row.get("return_20d"),
        "turnover": row.get("turnover"),
        "market_cap": row.get("market_cap"),
        "pe": row.get("pe"),
        "pb": row.get("pb"),
        "turnover_rate": row.get("turnover_rate"),
        "volume_ratio": row.get("volume_ratio"),
        "industry": row.get("industry"),
        "area": row.get("area"),
        "trade_time": row.get("trade_time"),
        "source": row.get("source", "postgresql"),
    }


def _sector_db_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a sectors table row to API format."""
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "type": row.get("type"),
        "category": row.get("category"),
        "path": row.get("path") or [],
        "stock_count": row.get("stock_count"),
        "change_pct": row.get("change_pct"),
        "market_cap": row.get("market_cap"),
        "turnover_rate": row.get("turnover_rate"),
        "rise_count": row.get("rise_count"),
        "fall_count": row.get("fall_count"),
        "leader_stock": row.get("leader_stock"),
        "leader_change_pct": row.get("leader_change_pct"),
        "source": row.get("source", "postgresql"),
    }


def _sector_member_db_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a sector_memberships table row to API format."""
    return {
        "symbol": row.get("symbol"),
        "exchange": row.get("exchange"),
        "vt_symbol": row.get("vt_symbol"),
        "name": row.get("name"),
        "last_price": row.get("last_price"),
        "change_pct": row.get("change_pct"),
        "return_5d": row.get("return_5d"),
        "return_10d": row.get("return_10d"),
        "return_20d": row.get("return_20d"),
        "turnover": row.get("turnover"),
        "market_cap": row.get("market_cap"),
        "source": row.get("source", "postgresql"),
    }


def _bar_db_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a stock_daily_bars table row to API format."""
    trade_date = row.get("trade_date")
    return {
        "trade_date": trade_date.isoformat() if hasattr(trade_date, "isoformat") else str(trade_date),
        "open": row.get("open_price"),
        "close": row.get("close_price"),
        "high": row.get("high_price"),
        "low": row.get("low_price"),
        "volume": row.get("volume"),
        "turnover": row.get("turnover"),
        "change_pct": row.get("change_pct"),
    }


def _stock_sector_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a stock_sector_memberships table row to API format."""
    return {
        "id": row.get("sector_id"),
        "name": row.get("sector_name"),
        "type": row.get("sector_type"),
        "rank": row.get("rank"),
        "confirmed": row.get("confirmed"),
        "is_precise": row.get("is_precise"),
        "source": row.get("source", "postgresql"),
    }


# ─── Shenwan API helpers ─────────────────────────────────────────────────

def _shenwan_industry_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a shenwan_industries table row to API format."""
    return {
        "code": row.get("code"),
        "name": row.get("name"),
        "level": row.get("level"),
        "parent_code": row.get("parent_code"),
        "path": row.get("path") or [],
        "stock_count": row.get("stock_count"),
        "change_pct": row.get("change_pct"),
        "market_cap": row.get("market_cap"),
        "source": row.get("source", "postgresql"),
    }


def _shenwan_member_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a shenwan_industry_members table row to API format."""
    return {
        "symbol": row.get("symbol"),
        "exchange": row.get("exchange"),
        "vt_symbol": row.get("vt_symbol"),
        "name": row.get("name"),
        "market_cap": row.get("market_cap"),
        "change_pct": row.get("change_pct"),
    }


def _resolve_edge_names(
    edges: list[dict[str, Any]],
    industries: Sequence[Any],
) -> list[dict[str, Any]]:
    """Resolve industry codes to names in edge dicts."""
    code_to_name: dict[str, str] = {}
    for ind in industries:
        if isinstance(ind, dict):
            code_to_name[str(ind.get("code") or "")] = str(ind.get("name") or "")
        else:
            code_to_name[str(ind["code"])] = str(ind["name"])
    for edge in edges:
        edge["source_industry_name"] = code_to_name.get(edge.get("source_industry_code", ""), "")
        edge["target_industry_name"] = code_to_name.get(edge.get("target_industry_code", ""), "")
    return edges


# ─── Research data upsert helpers ─────────────────────────────────────────


def _upsert_sector_daily_bars(
    sector_id: str,
    items: list[dict[str, Any]],
    source: str = "akshare",
) -> int:
    """Upsert sector historical K-line bars."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            trade_date_raw = item.get("trade_date")
            if not trade_date_raw:
                continue
            trade_date = _parse_date(trade_date_raw)
            if trade_date is None:
                continue
            values = {
                "sector_id": sector_id,
                "trade_date": trade_date,
                "open_price": float(item.get("open") or 0),
                "close_price": float(item.get("close") or 0),
                "high_price": float(item.get("high") or 0),
                "low_price": float(item.get("low") or 0),
                "volume": item.get("volume"),
                "turnover": item.get("turnover"),
                "change_pct": item.get("change_pct"),
                "source": source,
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.sector_daily_bars).where(
                    (schema.sector_daily_bars.c.sector_id == sector_id)
                    & (schema.sector_daily_bars.c.trade_date == trade_date)
                )
            ).first()
            if existing:
                session.execute(
                    schema.sector_daily_bars.update()
                    .where(
                        (schema.sector_daily_bars.c.sector_id == sector_id)
                        & (schema.sector_daily_bars.c.trade_date == trade_date)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.sector_daily_bars.insert().values(**values))
            written += 1
    return written


def _upsert_sector_fund_flows(
    items: list[dict[str, Any]],
    period: str,
    sector_type: str,
) -> int:
    """Upsert sector fund flow records."""
    if not items:
        return 0
    today_str = date.today().isoformat()
    written = 0
    with session_scope() as session:
        for item in items:
            name = str(item.get("name") or "")
            code = str(item.get("code") or name)
            sector_id = str(item.get("id") or item.get("akshare_symbol") or code)
            if not sector_id:
                continue
            values = {
                "sector_id": sector_id,
                "trade_date": today_str,
                "period": period,
                "main_net_inflow": item.get("main_net_inflow"),
                "main_net_inflow_ratio": item.get("main_net_inflow_pct"),
                "rank": item.get("rank"),
                "source": "akshare",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.sector_fund_flows).where(
                    (schema.sector_fund_flows.c.sector_id == sector_id)
                    & (schema.sector_fund_flows.c.trade_date == today_str)
                    & (schema.sector_fund_flows.c.period == period)
                )
            ).first()
            if existing:
                session.execute(
                    schema.sector_fund_flows.update()
                    .where(
                        (schema.sector_fund_flows.c.sector_id == sector_id)
                        & (schema.sector_fund_flows.c.trade_date == today_str)
                        & (schema.sector_fund_flows.c.period == period)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.sector_fund_flows.insert().values(**values))
            written += 1
    return written


def _upsert_limit_up_events(
    items: list[dict[str, Any]],
    pool_type: str,
    trade_date: str,
) -> int:
    """Upsert limit-up/limit-down pool items as stock_events."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        known_symbols = set(
            session.execute(select(schema.stocks.c.vt_symbol)).scalars().all()
        )
        for item in items:
            vts = str(item.get("vt_symbol") or "")
            if not vts or vts not in known_symbols:
                continue
            title = f"{pool_type}: {item.get('name', vts)}"
            values = {
                "vt_symbol": vts,
                "event_date": trade_date,
                "event_type": f"limit_pool_{pool_type}",
                "title": title,
                "summary": str(item.get("raw") or {}),
                "url": None,
                "keywords": [pool_type],
                "sentiment": "positive" if pool_type in ("zt", "strong") else "negative",
                "importance": 0.8 if pool_type in ("zt", "strong") else 0.5,
                "source": "akshare.stock_ztb_em",
                "raw": item.get("raw") or {},
            }
            session.execute(schema.stock_events.insert().values(**values))
            written += 1
    return written


def _upsert_stock_fund_flows(
    symbol: str,
    exchange: str,
    items: list[dict[str, Any]],
    period: str,
) -> int:
    """Upsert individual stock fund flow records."""
    if not items:
        return 0
    vts = vt_symbol(symbol, exchange)
    today_str = date.today().isoformat()
    written = 0
    with session_scope() as session:
        for item in items:
            item_vts = str(item.get("vt_symbol") or vts)
            values = {
                "vt_symbol": item_vts,
                "trade_date": today_str,
                "period": period,
                "main_net_inflow": item.get("main_net_inflow"),
                "main_net_inflow_ratio": item.get("main_net_inflow_pct"),
                "super_large_net_inflow": item.get("super_large_net_inflow"),
                "large_net_inflow": item.get("large_net_inflow"),
                "medium_net_inflow": item.get("medium_net_inflow"),
                "small_net_inflow": item.get("small_net_inflow"),
                "source": "akshare",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stock_fund_flows).where(
                    (schema.stock_fund_flows.c.vt_symbol == item_vts)
                    & (schema.stock_fund_flows.c.trade_date == today_str)
                    & (schema.stock_fund_flows.c.period == period)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_fund_flows.update()
                    .where(
                        (schema.stock_fund_flows.c.vt_symbol == item_vts)
                        & (schema.stock_fund_flows.c.trade_date == today_str)
                        & (schema.stock_fund_flows.c.period == period)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_fund_flows.insert().values(**values))
            written += 1
    return written


def _upsert_stock_fund_flow_items(items: list[dict[str, Any]], period: str) -> int:
    """Upsert stock fund-flow records from an already fetched all-market list."""
    if not items:
        return 0
    today_str = date.today().isoformat()
    written = 0
    with session_scope() as session:
        known_symbols = set(
            session.execute(select(schema.stocks.c.vt_symbol)).scalars().all()
        )
        for item in items:
            item_vts = str(item.get("vt_symbol") or "")
            if not item_vts or item_vts not in known_symbols:
                continue
            values = {
                "vt_symbol": item_vts,
                "trade_date": today_str,
                "period": period,
                "main_net_inflow": item.get("main_net_inflow"),
                "main_net_inflow_ratio": item.get("main_net_inflow_pct"),
                "super_large_net_inflow": item.get("super_large_net_inflow"),
                "large_net_inflow": item.get("large_net_inflow"),
                "medium_net_inflow": item.get("medium_net_inflow"),
                "small_net_inflow": item.get("small_net_inflow"),
                "source": "akshare",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stock_fund_flows).where(
                    (schema.stock_fund_flows.c.vt_symbol == item_vts)
                    & (schema.stock_fund_flows.c.trade_date == today_str)
                    & (schema.stock_fund_flows.c.period == period)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_fund_flows.update()
                    .where(
                        (schema.stock_fund_flows.c.vt_symbol == item_vts)
                        & (schema.stock_fund_flows.c.trade_date == today_str)
                        & (schema.stock_fund_flows.c.period == period)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_fund_flows.insert().values(**values))
            written += 1
    return written


def _upsert_stock_hot_ranks(items: list[dict[str, Any]]) -> int:
    """Upsert stock hot rank records."""
    if not items:
        return 0
    now_str = datetime.now(timezone.utc).isoformat()[:30]
    written = 0
    with session_scope() as session:
        known_symbols = set(
            session.execute(select(schema.stocks.c.vt_symbol)).scalars().all()
        )
        for item in items:
            vts = str(item.get("vt_symbol") or "")
            if not vts or vts not in known_symbols:
                continue
            values = {
                "vt_symbol": vts,
                "rank_time": now_str,
                "rank": item.get("rank"),
                "rank_change": item.get("rank_change"),
                "keywords": item.get("keywords") or [],
                "source": "akshare.stock_hot_rank_em",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stock_hot_ranks).where(
                    (schema.stock_hot_ranks.c.vt_symbol == vts)
                    & (schema.stock_hot_ranks.c.rank_time == now_str)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_hot_ranks.update()
                    .where(
                        (schema.stock_hot_ranks.c.vt_symbol == vts)
                        & (schema.stock_hot_ranks.c.rank_time == now_str)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_hot_ranks.insert().values(**values))
            written += 1
    return written


def _upsert_stock_lhb_records(items: list[dict[str, Any]]) -> int:
    """Upsert dragon-tiger board records."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        known_symbols = set(
            session.execute(select(schema.stocks.c.vt_symbol)).scalars().all()
        )
        for item in items:
            vts = str(item.get("vt_symbol") or "")
            trade_date = str(item.get("trade_date") or "")
            reason = str(item.get("reason") or "")
            if not vts or vts not in known_symbols or not trade_date:
                continue
            values = {
                "vt_symbol": vts,
                "trade_date": trade_date,
                "reason": reason[:200],
                "buy_amount": item.get("buy_amount"),
                "sell_amount": item.get("sell_amount"),
                "net_amount": item.get("net_buy"),
                "departments": item.get("raw"),
                "source": "akshare.stock_lhb_detail_em",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stock_lhb_records).where(
                    (schema.stock_lhb_records.c.vt_symbol == vts)
                    & (schema.stock_lhb_records.c.trade_date == trade_date)
                    & (schema.stock_lhb_records.c.reason == reason[:200])
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_lhb_records.update()
                    .where(
                        (schema.stock_lhb_records.c.vt_symbol == vts)
                        & (schema.stock_lhb_records.c.trade_date == trade_date)
                        & (schema.stock_lhb_records.c.reason == reason[:200])
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_lhb_records.insert().values(**values))
            written += 1
    return written


def _financial_sync_stock_rows(stock_limit: int, only_missing: bool = True) -> list[dict[str, Any]]:
    limit = min(max(int(stock_limit or 100), 1), 1000)
    with session_scope() as session:
        query = select(schema.stocks).order_by(desc(schema.stocks.c.turnover), desc(schema.stocks.c.market_cap))
        if only_missing:
            report_counts = (
                select(
                    schema.stock_financial_reports.c.vt_symbol.label("vt_symbol"),
                    func.count().label("report_count"),
                )
                .where(schema.stock_financial_reports.c.publish_date.is_not(None))
                .group_by(schema.stock_financial_reports.c.vt_symbol)
                .subquery()
            )
            query = (
                select(schema.stocks)
                .join(report_counts, schema.stocks.c.vt_symbol == report_counts.c.vt_symbol, isouter=True)
                .where(func.coalesce(report_counts.c.report_count, 0) < 4)
                .order_by(desc(schema.stocks.c.turnover), desc(schema.stocks.c.market_cap))
            )
        return session.execute(query.limit(limit)).mappings().all()


def _upsert_stock_financial_reports(
    symbol: str,
    exchange: str,
    items: list[dict[str, Any]],
    period_type: str,
) -> int:
    """Upsert stock financial report records (quarterly or indicator)."""
    if not items:
        return 0
    vts = vt_symbol(symbol, exchange)
    written = 0
    with session_scope() as session:
        for item in items:
            report_date = str(item.get("report_date") or "")
            if not report_date:
                continue
            values = {
                "vt_symbol": vts,
                "report_date": report_date,
                "period_type": period_type,
                "publish_date": item.get("publish_date"),
                "revenue": item.get("revenue"),
                "revenue_yoy": item.get("revenue_yoy"),
                "revenue_qoq": item.get("revenue_qoq"),
                "net_profit": item.get("net_profit"),
                "net_profit_yoy": item.get("net_profit_yoy"),
                "net_profit_qoq": item.get("net_profit_qoq"),
                "deducted_net_profit": item.get("deducted_net_profit"),
                "eps": item.get("eps"),
                "gross_margin": item.get("gross_margin"),
                "net_margin": item.get("net_margin"),
                "roe": item.get("roe"),
                "debt_asset_ratio": item.get("debt_ratio"),
                "operating_cash_flow": item.get("operating_cash_flow"),
                "cash_flow_quality": item.get("cash_flow_quality"),
                "source": "akshare",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stock_financial_reports).where(
                    (schema.stock_financial_reports.c.vt_symbol == vts)
                    & (schema.stock_financial_reports.c.report_date == report_date)
                    & (schema.stock_financial_reports.c.period_type == period_type)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_financial_reports.update()
                    .where(
                        (schema.stock_financial_reports.c.vt_symbol == vts)
                        & (schema.stock_financial_reports.c.report_date == report_date)
                        & (schema.stock_financial_reports.c.period_type == period_type)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_financial_reports.insert().values(**values))
            written += 1
    return written


def _upsert_stock_business_segments(
    symbol: str,
    exchange: str,
    items: list[dict[str, Any]],
) -> int:
    """Upsert stock business segment records (multi-period)."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            seg_name = str(item.get("segment_name") or item.get("name") or "")
            report_date = str(item.get("report_date") or item.get("REPORT_DATE") or "")
            if not seg_name:
                continue
            values = {
                "vt_symbol": vt_symbol(symbol, exchange),
                "segment_name": seg_name,
                "segment_type": item.get("segment_type") or "product",
                "report_date": report_date or None,
                "revenue": item.get("revenue"),
                "revenue_ratio": item.get("revenue_ratio"),
                "revenue_yoy": item.get("revenue_yoy"),
                "gross_profit": item.get("gross_profit"),
                "gross_profit_ratio": item.get("gross_profit_ratio"),
                "gross_margin": item.get("gross_margin"),
                "profit_ratio": item.get("profit_ratio"),
                "rank": item.get("rank"),
                "confidence": item.get("confidence"),
                "source": "akshare",
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.stock_business_segments).where(
                    (schema.stock_business_segments.c.vt_symbol == values["vt_symbol"])
                    & (schema.stock_business_segments.c.segment_name == seg_name)
                    & (schema.stock_business_segments.c.report_date == report_date or None)
                )
            ).first()
            if existing:
                session.execute(
                    schema.stock_business_segments.update()
                    .where(
                        (schema.stock_business_segments.c.id == existing[0])
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.stock_business_segments.insert().values(**values))
            written += 1
    return written


def _upsert_stock_events(
    symbol: str,
    items: list[dict[str, Any]],
    event_type: str,
) -> int:
    """Upsert stock events (notices, announcements, etc.)."""
    if not items:
        return 0
    written = 0
    with session_scope() as session:
        for item in items:
            event_date = str(item.get("date") or item.get("event_date") or date.today().isoformat())
            title = str(item.get("title") or item.get("name") or "")
            if not title:
                continue
            values = {
                "vt_symbol": vt_symbol(symbol, normalize_exchange(symbol)),
                "event_date": event_date,
                "event_type": event_type,
                "title": title,
                "summary": item.get("summary"),
                "url": item.get("url") or item.get("pdf_url"),
                "keywords": item.get("keywords") or [],
                "sentiment": None,
                "importance": None,
                "source": "akshare",
                "raw": item.get("raw") or {},
            }
            session.execute(schema.stock_events.insert().values(**values))
            written += 1
    return written


def _parse_date(value: Any) -> date | None:
    """Parse various date formats into a date object."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()[:10]
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: Any) -> datetime | None:
    """Parse common market data datetime strings into a naive local datetime."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text_value = str(value or "").strip()
    if not text_value:
        return None
    text_value = text_value.replace("T", " ").replace("Z", "")
    if "+" in text_value:
        text_value = text_value.split("+", 1)[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text_value[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text_value).replace(tzinfo=None)
    except ValueError:
        return None
