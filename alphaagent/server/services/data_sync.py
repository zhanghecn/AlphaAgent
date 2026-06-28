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
from concurrent.futures import ThreadPoolExecutor
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
from alphaagent.market.symbols import INDEX_SYMBOLS, normalize_exchange, vt_symbol
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services import minute_gaps, minute_imports, minute_provider_imports
from alphaagent.server.services import research_sector_scores
from alphaagent.server.services.quant import research_jobs, screening

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALLOWED_IMPORT_DIRS = (
    PROJECT_ROOT / "data" / "imports",
    PROJECT_ROOT / "memory" / "06_backtests",
)
INTERRUPTED_SYNC_JOB_MESSAGE = "API process restarted before this sync job finished."
INTERRUPTED_SCHEDULE_MESSAGE = "API process restarted before this schedule finished."
INTERRUPTED_SCHEDULE_RECOVERY_DELAY_SECONDS = 30
INTERRUPTED_SCHEDULE_RECOVERY_WAIT_SECONDS = 6 * 60 * 60
INTERRUPTED_SCHEDULE_RECOVERY_POLL_SECONDS = 5

_INTERRUPTED_RECOVERY_LOCK = threading.Lock()
_INTERRUPTED_SCHEDULE_RECOVERY_IDS: set[str] = set()
_interrupted_recovery_thread: threading.Thread | None = None

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
    ),
    JobDefinition(
        id="sync_sector_list",
        name="板块 / 概念清单",
        description="同步行业板块、概念板块、主题板块列表。",
        source_id="akshare",
        target_table="sectors",
        default_params={"types": ["concept", "industry", "theme"]},
    ),
    JobDefinition(
        id="sync_sector_members",
        name="板块成分股",
        description="同步每个板块的成分股列表及实时行情。",
        source_id="akshare",
        target_table="sector_memberships",
        default_params={"page_size": 200},
    ),
    JobDefinition(
        id="sync_stock_daily_bars",
        name="股票日 K 线",
        description="增量同步全 A 股票日线行情 (OHLCV)。",
        source_id="akshare",
        target_table="stock_daily_bars",
        default_params={"limit": 250},
    ),
    JobDefinition(
        id="sync_index_daily_bars",
        name="核心指数日 K 线",
        description="同步上证、沪深300、中证500/1000、创业板、科创50等核心指数日线，供大盘画像和回测审计使用。",
        source_id="akshare",
        target_table="stock_daily_bars",
        default_params={"limit": 500},
    ),
    JobDefinition(
        id="sync_stock_minute_bars",
        name="股票分钟 K 线",
        description="同步最近分钟线，或按严格回测缺口补执行日 14:30 尾盘快照。",
        source_id="akshare",
        target_table="stock_minute_bars",
        default_params={"mode": "recent", "stock_limit": 100, "limit": 240, "interval": "1m", "only_missing": True},
    ),
    JobDefinition(
        id="sync_stock_sector_memberships",
        name="股票-板块反向索引",
        description="重建每只股票所属板块的反向索引。",
        source_id="akshare",
        target_table="stock_sector_memberships",
        default_params={},
    ),
    # ── Shenwan Industry Classification ──
    JobDefinition(
        id="sync_shenwan_industry_tree",
        name="申万行业分类树",
        description="同步申万一/二/三级行业分类。",
        source_id="akshare",
        target_table="shenwan_industries",
        default_params={"levels": [1, 2, 3]},
    ),
    JobDefinition(
        id="sync_shenwan_industry_members",
        name="申万行业成分股",
        description="同步三级行业成分股列表。",
        source_id="akshare",
        target_table="shenwan_industry_members",
        default_params={},
    ),
    JobDefinition(
        id="sync_industry_board_mapping",
        name="行业-板块映射",
        description="构建申万行业与东方财富板块的映射关系。",
        source_id="akshare",
        target_table="industry_board_mapping",
        default_params={},
    ),
    JobDefinition(
        id="sync_supply_chain_edges",
        name="供应链关系推断",
        description="基于主营构成交叉分析推断行业间供应链关系。",
        source_id="akshare",
        target_table="industry_chain_edges",
        default_params={"level": 2},
    ),
    # ── Research data: sector dashboard ──
    JobDefinition(
        id="sync_sector_daily_bars",
        name="板块历史 K 线",
        description="同步行业/概念板块历史日 K 线数据。",
        source_id="akshare",
        target_table="sector_daily_bars",
        default_params={"limit": 250, "sector_limit": 0},
    ),
    JobDefinition(
        id="sync_sector_fund_flows",
        name="板块资金流",
        description="同步行业/概念板块资金流向数据。",
        source_id="akshare",
        target_table="sector_fund_flows",
        default_params={"periods": ["即时", "5日", "10日"]},
    ),
    JobDefinition(
        id="sync_sector_period_scores",
        name="板块周期评分",
        description="根据板块 K 线、资金流、成员涨跌和情绪事件计算主线热度评分。",
        source_id="akshare",
        target_table="sector_period_scores",
        default_params={"periods": ["20d"], "sector_limit": 0},
    ),
    JobDefinition(
        id="sync_limit_up_pools",
        name="涨停池 / 跌停池",
        description="同步涨停、强势、炸板、跌停池数据。",
        source_id="akshare",
        target_table="stock_events",
        default_params={},
    ),
    JobDefinition(
        id="sync_stock_fund_flows",
        name="个股资金流",
        description="同步个股资金流向数据。",
        source_id="akshare",
        target_table="stock_fund_flows",
        default_params={"stock_limit": 200},
    ),
    JobDefinition(
        id="sync_stock_hot_ranks",
        name="个股热度排行",
        description="同步个股热度排行和关键词数据。",
        source_id="akshare",
        target_table="stock_hot_ranks",
        default_params={"limit": 100},
    ),
    JobDefinition(
        id="sync_stock_lhb_records",
        name="龙虎榜",
        description="同步龙虎榜交易明细数据。",
        source_id="akshare",
        target_table="stock_lhb_records",
        default_params={"days": 30},
    ),
    # ── Research data: stock financials ──
    JobDefinition(
        id="sync_stock_financial_quarterly",
        name="个股季度财报",
        description="同步个股利润表/资产负债表/现金流季度数据。",
        source_id="akshare",
        target_table="stock_financial_reports",
        default_params={"stock_limit": 100},
    ),
    JobDefinition(
        id="sync_stock_financial_indicators",
        name="个股财务指标",
        description="同步 ROE、毛利率、净利率等财务分析指标。",
        source_id="akshare",
        target_table="stock_financial_reports",
        default_params={"stock_limit": 100},
    ),
    JobDefinition(
        id="sync_stock_business_segments_history",
        name="主营构成历史",
        description="同步个股主营构成多报告期历史数据。",
        source_id="akshare",
        target_table="stock_business_segments",
        default_params={"stock_limit": 100},
    ),
    JobDefinition(
        id="sync_stock_notices",
        name="个股公告",
        description="同步个股公告/公告数据。",
        source_id="akshare",
        target_table="stock_events",
        default_params={},
    ),
)

# ─── Job cadence (data freshness rhythm) ─────────────────────────────────
# 静态元数据：描述每个任务"什么时候才有新数据"，让健康仪表盘能区分
# "落后了，该补" 与 "新鲜，无需更新"。不入库——这是数据源固有的更新节奏。

CADENCE_INTRADAY = "intraday"    # 盘中实时：快照 / 资金流 / 热度 / 涨跌停池
CADENCE_EOD_DAILY = "eod_daily"  # 每日盘后：日K / 指数 / 板块K线 / 周期评分
CADENCE_QUARTERLY = "quarterly"  # 财报披露季(1/4/7/10月)：季报 / 财务指标 / 主营构成
CADENCE_LHB = "lhb"              # 龙虎榜：交易日 18:00 后才有当日数据
CADENCE_IRREGULAR = "irregular"  # 低频：板块清单 / 申万行业 / 供应链（每周/每月级）

# 前端卡片分组 key（按展示顺序）
CATEGORY_MARKET_BASIC = "market_basic"
CATEGORY_MARKET_BARS = "market_bars"
CATEGORY_MARKET_REALTIME = "market_realtime"
CATEGORY_SECTOR_RESEARCH = "sector_research"
CATEGORY_FINANCIALS = "financials"
CATEGORY_EVENTS = "events"

CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_MARKET_BASIC: "基础清单",
    CATEGORY_MARKET_BARS: "行情 K 线",
    CATEGORY_MARKET_REALTIME: "资金与热度",
    CATEGORY_SECTOR_RESEARCH: "板块研究",
    CATEGORY_FINANCIALS: "财务数据",
    CATEGORY_EVENTS: "事件与公告",
}

CATEGORY_ORDER: tuple[str, ...] = (
    CATEGORY_MARKET_BASIC,
    CATEGORY_MARKET_BARS,
    CATEGORY_MARKET_REALTIME,
    CATEGORY_SECTOR_RESEARCH,
    CATEGORY_FINANCIALS,
    CATEGORY_EVENTS,
)


@dataclass(frozen=True)
class JobCadence:
    """单个同步任务的更新节奏与新鲜度探针配置。"""

    cadence: str
    category: str
    staleness_days: int      # 兜底阈值（无法对齐交易日时按天判断）
    freshness_table: str     # 取新鲜度的表
    freshness_col: str       # 取新鲜度的列：updated_at/bar_time(时间戳) 或 trade_date(日期)


# 22 个任务的节奏映射。共表任务（如 financial_quarterly 与 financial_indicators
# 都写 stock_financial_reports）首版共用 MAX(updated_at) 粗粒度判定，前端同组展示。
JOB_CADENCES: dict[str, JobCadence] = {
    "sync_stock_list": JobCadence(CADENCE_INTRADAY, CATEGORY_MARKET_REALTIME, 1, "stocks", "updated_at"),
    "sync_stock_fund_flows": JobCadence(CADENCE_INTRADAY, CATEGORY_MARKET_REALTIME, 1, "stock_fund_flows", "updated_at"),
    "sync_sector_fund_flows": JobCadence(CADENCE_INTRADAY, CATEGORY_MARKET_REALTIME, 1, "sector_fund_flows", "updated_at"),
    "sync_stock_hot_ranks": JobCadence(CADENCE_INTRADAY, CATEGORY_MARKET_REALTIME, 1, "stock_hot_ranks", "updated_at"),
    "sync_limit_up_pools": JobCadence(CADENCE_INTRADAY, CATEGORY_MARKET_REALTIME, 1, "stock_events", "updated_at"),
    "sync_stock_daily_bars": JobCadence(CADENCE_EOD_DAILY, CATEGORY_MARKET_BARS, 1, "stock_daily_bars", "trade_date"),
    "sync_index_daily_bars": JobCadence(CADENCE_EOD_DAILY, CATEGORY_MARKET_BARS, 1, "stock_daily_bars", "trade_date"),
    "sync_sector_daily_bars": JobCadence(CADENCE_EOD_DAILY, CATEGORY_MARKET_BARS, 1, "sector_daily_bars", "trade_date"),
    "sync_stock_minute_bars": JobCadence(CADENCE_INTRADAY, CATEGORY_MARKET_BARS, 1, "stock_minute_bars", "bar_time"),
    "sync_stock_financial_quarterly": JobCadence(CADENCE_QUARTERLY, CATEGORY_FINANCIALS, 45, "stock_financial_reports", "updated_at"),
    "sync_stock_financial_indicators": JobCadence(CADENCE_QUARTERLY, CATEGORY_FINANCIALS, 45, "stock_financial_reports", "updated_at"),
    "sync_stock_business_segments_history": JobCadence(CADENCE_QUARTERLY, CATEGORY_FINANCIALS, 45, "stock_business_segments", "updated_at"),
    "sync_stock_lhb_records": JobCadence(CADENCE_LHB, CATEGORY_EVENTS, 1, "stock_lhb_records", "trade_date"),
    "sync_stock_notices": JobCadence(CADENCE_EOD_DAILY, CATEGORY_EVENTS, 2, "stock_events", "updated_at"),
    "sync_sector_period_scores": JobCadence(CADENCE_EOD_DAILY, CATEGORY_SECTOR_RESEARCH, 1, "sector_period_scores", "updated_at"),
    "sync_sector_list": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 7, "sectors", "updated_at"),
    "sync_sector_members": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 7, "sector_memberships", "updated_at"),
    "sync_stock_sector_memberships": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 7, "stock_sector_memberships", "updated_at"),
    "sync_shenwan_industry_tree": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 30, "shenwan_industries", "updated_at"),
    "sync_shenwan_industry_members": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 30, "shenwan_industry_members", "updated_at"),
    "sync_industry_board_mapping": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 30, "industry_board_mapping", "updated_at"),
    "sync_supply_chain_edges": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 30, "industry_chain_edges", "updated_at"),
}

# 核心表为空 = 数据库从未初始化过
EMPTY_CORE_TABLES = ("stocks", "stock_daily_bars")

# 推荐 job_ids 的展示顺序（上游依赖在前，与 DEFAULT_BATCH_SCHEDULES 优先级一致）
_RECOMMENDED_PRIORITY: tuple[str, ...] = (
    "sync_stock_list", "sync_sector_list", "sync_sector_members",
    "sync_stock_sector_memberships", "sync_shenwan_industry_tree",
    "sync_shenwan_industry_members", "sync_industry_board_mapping",
    "sync_supply_chain_edges",
    "sync_stock_daily_bars", "sync_index_daily_bars", "sync_sector_daily_bars",
    "sync_stock_minute_bars",
    "sync_stock_fund_flows", "sync_sector_fund_flows",
    "sync_stock_hot_ranks", "sync_limit_up_pools",
    "sync_sector_period_scores",
    "sync_stock_financial_quarterly", "sync_stock_financial_indicators",
    "sync_stock_business_segments_history",
    "sync_stock_lhb_records", "sync_stock_notices",
)


# Unified batch-sync schedules. Execution priority = list order (upstream
# jobs first to satisfy data dependencies). Replaces the per-job crons that
# used to live on DEFAULT_JOBS. See
# requirements/alphaagent_unified_incremental_schedule_plan.md.
DEFAULT_BATCH_SCHEDULES: list[dict[str, Any]] = [
    {
        "id": "tail_preview_14h",
        "name": "尾盘预览缓存（14:00，快照后生成）",
        "cron": "0 14 * * 1-5",
        "action": "tail_preview",
        "enabled": True,
        "concurrency": 12,
        "job_ids": [
            "sync_stock_list",          # realtime snapshot (price / change / volume ratio)
            "sync_stock_minute_bars",   # intraday minute bars up to 14:00
            "sync_stock_fund_flows",    # per-stock fund flow
            "sync_sector_fund_flows",   # sector fund flow for market/mainline context
            "sync_stock_hot_ranks",     # per-stock hotness
            "sync_limit_up_pools",      # limit-up / limit-down pools
        ],
    },
    {
        "id": "tail_quant_1430",
        "name": "尾盘预览缓存（14:30，尾盘确认）",
        "cron": "30 14 * * 1-5",
        "action": "tail_preview",
        "enabled": True,
        "concurrency": 12,
        "job_ids": [
            "sync_stock_list",
            "sync_stock_minute_bars",
            "sync_stock_fund_flows",
            "sync_sector_fund_flows",
            "sync_stock_hot_ranks",
            "sync_limit_up_pools",
        ],
    },
    {
        "id": "eod_18h",
        "name": "盘后同步（18:00，补完整数据）",
        "cron": "0 18 * * 1-5",
        "action": "sync",
        "enabled": True,
        "concurrency": 8,
        "job_ids": [
            "sync_stock_list",
            "sync_stock_daily_bars",    # full daily bars (true incremental)
            "sync_index_daily_bars",    # market context benchmarks
            "sync_sector_list",
            "sync_sector_members",
            "sync_stock_sector_memberships",
            "sync_sector_daily_bars",
            "sync_sector_fund_flows",
            "sync_sector_period_scores",
            "eod_quant_research",       # 候选生成:基础数据(daily+板块)就绪即跑,读DB已有财报评分,不等慢/晚job,让候选早出
            "sync_stock_lhb_records",   # LHB publishes after 18:00 -> run late
            "sync_stock_notices",
            "sync_stock_financial_quarterly",
            "sync_stock_financial_indicators",
            "sync_stock_business_segments_history",
        ],
    },
]

OBSOLETE_BATCH_SCHEDULE_IDS = {
    "intraday_14h": "已由 tail_preview_14h 替代：14:00 生成今日尾盘预览缓存。",
    "tail_prepare_14h": "已由 tail_preview_14h 替代：14:00 同步关键数据并生成预览缓存。",
}
TAIL_PREVIEW_BATCH_JOB_ID = "tail_preview_cache"
EOD_QUANT_RESEARCH_BATCH_JOB_ID = "eod_quant_research"
INTERNAL_BATCH_JOB_IDS = {TAIL_PREVIEW_BATCH_JOB_ID, EOD_QUANT_RESEARCH_BATCH_JOB_ID}


SYNC_BATCH_PROFILES: dict[str, tuple[str, ...]] = {
    "core": (
        "sync_stock_list",
        "sync_sector_list",
        "sync_stock_daily_bars",
        "sync_index_daily_bars",
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

    def __init__(self, adapter: AkShareAdapter | None = None, progress: ProgressCallback | None = None, concurrency: int = 8) -> None:
        self.adapter = adapter or AkShareAdapter()
        self.progress = progress
        self.concurrency = max(1, int(concurrency))

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
        sector_rows = [dict(row) for row in sector_rows]
        total_sectors = len(sector_rows)
        self._report_progress("同步板块成分股", current=0, total=total_sectors)

        lock = threading.Lock()
        counters = {"read": 0, "written": 0, "done": 0}

        def _do_one(sector_row: dict[str, Any]) -> None:
            sector_id = str(sector_row["id"])
            sector_name = str(sector_row.get("name") or sector_id)
            label = f"{sector_name} {sector_id}"
            try:
                data = self.adapter.sector_stocks(sector_id, page=1, page_size=page_size)
            except Exception as exc:
                logger.warning("sector_stocks(%s) failed: %s", sector_id, exc)
                with lock:
                    counters["done"] += 1
                    cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
                self._report_progress(
                    "读取板块成分股",
                    current=cur_done,
                    total=total_sectors,
                    current_label=f"{label} 失败：{exc.__class__.__name__}",
                    rows_read=cur_read,
                    rows_written=cur_written,
                )
                return
            items = data.get("items") or []
            written = _upsert_sector_memberships(sector_id, items)
            with lock:
                counters["read"] += len(items)
                counters["written"] += written
                counters["done"] += 1
                cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
            self._report_progress(
                "写入板块成分股",
                current=cur_done,
                total=total_sectors,
                current_label=f"{label}，{len(items)} 只",
                rows_read=cur_read,
                rows_written=cur_written,
                sample_items=items,
            )

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            list(pool.map(_do_one, sector_rows))

        return {"rows_read": counters["read"], "rows_written": counters["written"]}

    def _run_sync_stock_daily_bars(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit", 250))
        stock_limit = int(params.get("stock_limit", 0) or 0)
        symbols = _param_list(params.get("symbols"))
        stock_rows = _select_daily_bar_stocks(symbols, stock_limit)
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks in DB; run sync_stock_list first."}

        incremental = _truthy(params.get("incremental", True))
        vt_symbols = [vt_symbol(str(r["symbol"]), str(r["exchange"])) for r in stock_rows]
        last_dates = _last_bar_dates_daily(vt_symbols) if incremental else {}

        total_stocks = len(stock_rows)
        self._report_progress("同步股票日 K 线", current=0, total=total_stocks)

        lock = threading.Lock()
        counters = {"read": 0, "written": 0, "done": 0}

        def _do_one(stock_row: dict[str, Any]) -> None:
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            start_date = _next_day(last_dates.get(current_vts)) if last_dates.get(current_vts) else None
            try:
                data = self.adapter.stock_bars(symbol, exchange, limit=limit, interval="1d", start_date=start_date)
            except Exception as exc:
                logger.debug("stock_bars(%s) failed: %s", symbol, exc)
                with lock:
                    counters["done"] += 1
                    cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
                self._report_progress(
                    "读取股票日 K 线",
                    current=cur_done,
                    total=total_stocks,
                    current_label=f"{current_vts} 失败：{exc.__class__.__name__}",
                    rows_read=cur_read,
                    rows_written=cur_written,
                )
                return
            items = data.get("items") or []
            items = _fill_change_pct_from_close(items)
            written = _upsert_daily_bars(symbol, exchange, items)
            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name} for item in items[-3:]]
            with lock:
                counters["read"] += len(items)
                counters["written"] += written
                counters["done"] += 1
                cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
            self._report_progress(
                "写入股票日 K 线",
                current=cur_done,
                total=total_stocks,
                current_label=f"{current_vts} {stock_name}，{len(items)} 根",
                rows_read=cur_read,
                rows_written=cur_written,
                sample_items=sample_items,
            )

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            list(pool.map(_do_one, stock_rows))

        logger.info("sync_stock_daily_bars: processed %d stocks", counters["done"])
        return {"rows_read": counters["read"], "rows_written": counters["written"]}

    def _run_sync_index_daily_bars(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit", 500))
        symbols = _param_list(params.get("symbols"))
        index_rows = [
            item
            for item in INDEX_SYMBOLS
            if not symbols or vt_symbol(str(item["symbol"]), str(item["exchange"])) in symbols or str(item["symbol"]) in symbols
        ]
        if not index_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No matching index symbols."}

        _upsert_stocks(
            [
                {
                    "symbol": str(row["symbol"]),
                    "exchange": str(row["exchange"]),
                    "name": str(row.get("name") or row["symbol"]),
                    "source": "index_benchmark",
                    "raw": {"instrument_type": "index"},
                }
                for row in index_rows
            ]
        )
        incremental = _truthy(params.get("incremental", True))
        vt_symbols = [vt_symbol(str(row["symbol"]), str(row["exchange"])) for row in index_rows]
        last_dates = _last_bar_dates_daily(vt_symbols) if incremental else {}
        total_indexes = len(index_rows)
        total_read = 0
        total_written = 0
        self._report_progress("同步核心指数日 K 线", current=0, total=total_indexes)
        for index, row in enumerate(index_rows, start=1):
            symbol = str(row["symbol"])
            exchange = str(row["exchange"])
            name = str(row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            start_date = _next_day(last_dates.get(current_vts)) if last_dates.get(current_vts) else None
            try:
                data = self.adapter.stock_bars(symbol, exchange, limit=limit, interval="1d", start_date=start_date)
            except Exception as exc:
                logger.debug("index stock_bars(%s) failed: %s", current_vts, exc)
                self._report_progress(
                    "读取核心指数日 K 线",
                    current=index,
                    total=total_indexes,
                    current_label=f"{current_vts} {name} 失败：{exc.__class__.__name__}",
                    rows_read=total_read,
                    rows_written=total_written,
                )
                continue
            items = data.get("items") or []
            total_read += len(items)
            written = _upsert_daily_bars(symbol, exchange, items)
            total_written += written
            sample_items = [{**item, "vt_symbol": current_vts, "name": name} for item in items[-3:]]
            self._report_progress(
                "写入核心指数日 K 线",
                current=index,
                total=total_indexes,
                current_label=f"{current_vts} {name}，{len(items)} 根",
                rows_read=total_read,
                rows_written=total_written,
                sample_items=sample_items,
            )
        return {"rows_read": total_read, "rows_written": total_written}

    def _run_sync_stock_minute_bars(self, params: dict[str, Any]) -> dict[str, Any]:
        mode = str(params.get("mode") or "recent").strip().lower()
        if mode in {"backtest_gap", "backtest_gaps", "gaps", "gap"}:
            return self._run_sync_stock_minute_gap_bars(params)
        if mode not in {"recent", "latest", "normal"}:
            raise DataSyncError(f"Unsupported stock minute sync mode: {mode}")

        limit = int(params.get("limit", 240))
        stock_limit = int(params.get("stock_limit", 100))
        interval = str(params.get("interval", "1m")).strip().lower()
        incremental = _truthy(params.get("incremental", True))
        # incremental (per-stock 续传当日新 bar) 与 only_missing (跳过已同步整只) 互斥：
        # 增量模式下不跳过，对每只活跃股从最后 bar 续传，避免定时档只补历史而不拉当日新数据。
        only_missing = _truthy(params.get("only_missing", True)) and not incremental
        symbols = _param_list(params.get("symbols"))
        start_date = _parse_date(params.get("start_date"))
        end_date = _parse_date(params.get("end_date"))
        if interval not in {"1m", "5m", "15m", "30m", "60m"}:
            raise DataSyncError(f"Unsupported minute interval: {interval}")

        stock_rows = _select_minute_bar_stocks(symbols, stock_limit, interval, only_missing, start_date, end_date, limit)
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks need minute sync."}

        vt_symbols = [vt_symbol(str(r["symbol"]), str(r["exchange"])) for r in stock_rows]
        last_dates = _last_bar_dates_minute(vt_symbols, interval) if incremental else {}

        total_stocks = len(stock_rows)
        self._report_progress("同步股票分钟 K 线", current=0, total=total_stocks)

        lock = threading.Lock()
        counters = {"read": 0, "written": 0, "done": 0}

        def _do_one(stock_row: dict[str, Any]) -> None:
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            stock_start = _next_day(last_dates.get(current_vts)) if last_dates.get(current_vts) else start_date
            try:
                data = self.adapter.stock_bars(symbol, exchange, limit=limit, interval=interval, start_date=stock_start, end_date=end_date)
            except Exception as exc:
                logger.debug("stock_minute_bars(%s, %s) failed: %s", symbol, interval, exc)
                with lock:
                    counters["done"] += 1
                    cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
                self._report_progress(
                    "读取股票分钟 K 线",
                    current=cur_done,
                    total=total_stocks,
                    current_label=f"{current_vts} 失败：{exc.__class__.__name__}",
                    rows_read=cur_read,
                    rows_written=cur_written,
                )
                return
            items = data.get("items") or []
            written = _upsert_minute_bars(symbol, exchange, items, interval, data.get("source", "akshare"))
            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name, "interval": interval} for item in items[-3:]]
            with lock:
                counters["read"] += len(items)
                counters["written"] += written
                counters["done"] += 1
                cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
            self._report_progress(
                "写入股票分钟 K 线",
                current=cur_done,
                total=total_stocks,
                current_label=f"{current_vts} {stock_name}，{len(items)} 根",
                rows_read=cur_read,
                rows_written=cur_written,
                sample_items=sample_items,
            )

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            list(pool.map(_do_one, stock_rows))

        logger.info("sync_stock_minute_bars: processed %d stocks", counters["done"])
        return {
            "mode": "recent",
            "provider": "akshare",
            "interval": interval,
            "rows_read": counters["read"],
            "rows_written": counters["written"],
        }

    def _run_sync_stock_minute_gap_bars(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fill strict-tail backtest minute gaps through the data-sync job."""

        provider = _normalize_minute_gap_provider(params.get("provider") or params.get("source") or "tdx")
        interval = "1m"
        fetch_interval = _minute_gap_fetch_interval(provider, interval)
        gap_source = minute_provider_imports.minute_gap_source_label(params)
        self._report_progress(
            "同步回测分钟缺口",
            current=0,
            total=1,
            current_label=f"{provider} {interval}",
            message=gap_source,
        )

        try:
            result = minute_provider_imports.import_minute_bars_for_gaps(params)
        except minute_provider_imports.MinuteProviderImportError as exc:
            raise DataSyncError(str(exc)) from exc

        rows_read = int(result.get("rows_read") or 0)
        rows_written = int(result.get("rows_written") or 0)
        self._report_progress(
            "同步回测分钟缺口",
            current=1,
            total=1,
            current_label=f"{provider} {result.get('status') or 'done'}",
            rows_read=rows_read,
            rows_written=rows_written,
            message=str(result.get("message") or result.get("note") or ""),
        )
        return {**result, "rows_read": rows_read, "rows_written": rows_written, "fetch_interval": fetch_interval}

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
        total_sectors = len(sector_rows)
        self._report_progress("同步板块历史 K 线", current=0, total=total_sectors)

        lock = threading.Lock()
        counters = {"read": 0, "written": 0, "done": 0, "failed": 0, "empty": 0}

        def _do_one(sector_row: dict[str, Any]) -> None:
            sector_id = str(sector_row["id"])
            sector_type = str(sector_row["type"])
            sector_name = str(sector_row.get("name") or sector_id)
            label = f"{sector_name} {sector_id}"
            try:
                data = self.adapter.sector_daily_bars(sector_id, board_type=sector_type, limit=limit)
            except Exception as exc:
                logger.debug("sector_daily_bars(%s) failed: %s", sector_id, exc)
                with lock:
                    counters["done"] += 1
                    counters["failed"] += 1
                    cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
                self._report_progress(
                    "读取板块历史 K 线",
                    current=cur_done,
                    total=total_sectors,
                    current_label=f"{label} 失败：{exc.__class__.__name__}",
                    rows_read=cur_read,
                    rows_written=cur_written,
                )
                return
            items = data.get("items") or []
            written = _upsert_sector_daily_bars(sector_id, items, data.get("source", "akshare"))
            with lock:
                counters["read"] += len(items)
                counters["written"] += written
                counters["done"] += 1
                if not items:
                    counters["empty"] += 1
                cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
            self._report_progress(
                "写入板块历史 K 线",
                current=cur_done,
                total=total_sectors,
                current_label=f"{label}，{len(items)} 根",
                rows_read=cur_read,
                rows_written=cur_written,
                sample_items=[{**item, "id": sector_id, "name": sector_name} for item in items[-3:]],
            )

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            list(pool.map(_do_one, sector_rows))

        if counters["read"] == 0:
            raise DataSyncError(
                "sync_sector_daily_bars read 0 rows "
                f"from {total_sectors} sectors (failed={counters['failed']}, empty={counters['empty']})"
            )
        return {
            "rows_read": counters["read"],
            "rows_written": counters["written"],
            "message": f"failed={counters['failed']}, empty={counters['empty']}",
        }

    def _run_sync_sector_fund_flows(self, params: dict[str, Any]) -> dict[str, Any]:
        periods = params.get("periods", ["即时"])
        if isinstance(periods, str):
            periods = [periods]
        total_read = 0
        total_written = 0
        for sector_type in ("concept", "industry"):
            for period in periods:
                self._report_progress(
                    "读取板块资金流",
                    current_label=f"{sector_type} / {period}",
                    rows_read=total_read,
                    rows_written=total_written,
                )
                try:
                    data = self.adapter.sector_fund_flows(sector_type=sector_type, period=period)
                except Exception as exc:
                    logger.debug("sector_fund_flows(%s, %s) failed: %s", sector_type, period, exc)
                    continue
                items = data.get("items") or []
                total_read += len(items)
                written = _upsert_sector_fund_flows(items, period, sector_type)
                total_written += written
                self._report_progress(
                    "写入板块资金流",
                    current_label=f"{sector_type} / {period} / {written} 条",
                    rows_read=total_read,
                    rows_written=total_written,
                    sample_items=items,
                )
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
        sector_limit = int(params.get("sector_limit", 0) or 0)
        as_of = (
            _parse_date(params.get("as_of_date"))
            if params.get("as_of_date")
            else _latest_complete_daily_date_for_research()
        )
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
    "sync_index_daily_bars": "_run_sync_index_daily_bars",
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


def _normalize_minute_gap_provider(value: Any) -> str:
    return minute_provider_imports.normalize_minute_gap_provider(value)


def _minute_gap_csv_from_sync_params(params: dict[str, Any]) -> tuple[str, str]:
    try:
        return minute_provider_imports.minute_gap_csv_from_sync_params(params)
    except minute_provider_imports.MinuteProviderImportError as exc:
        raise DataSyncError(str(exc)) from exc


def minute_gap_requirements_from_params(params: dict[str, Any]) -> dict[str, Any]:
    """Load strict-tail gap requirements from backtest id, inline CSV, or file."""

    gap_csv_text, gap_source = _minute_gap_csv_from_sync_params(params)
    gap_file_path = str(params.get("gap_file_path") or params.get("file_path") or "").strip()
    requirements = load_minute_gap_requirements(gap_csv_text, file_path=gap_file_path)
    requirements["gap_source"] = gap_source
    return requirements


def _minute_gap_fetch_interval(provider: str, interval: str) -> str:
    try:
        return minute_provider_imports.minute_gap_fetch_interval(provider, interval)
    except minute_provider_imports.MinuteProviderImportError as exc:
        raise DataSyncError(str(exc)) from exc


def _normalize_csv_key(value: Any) -> str:
    return minute_imports.normalize_csv_key(value)


def _minute_csv_symbol_exchange(row: dict[str, Any]) -> tuple[str, str]:
    return minute_imports.minute_csv_symbol_exchange(row)


def _minute_csv_item(row: dict[str, Any]) -> dict[str, Any]:
    return minute_imports.minute_csv_item(row)


def _required_number(row: dict[str, Any], *keys: str) -> float:
    return minute_imports.required_number(row, *keys)


def _optional_number(row: dict[str, Any], *keys: str) -> float | None:
    return minute_imports.optional_number(row, *keys)


# ─── Schema bootstrap ────────────────────────────────────────────────────

def ensure_sync_schema() -> None:
    """Create sync tables if they are missing."""
    if not is_database_configured():
        return
    schema.ensure_schema_once(get_engine())
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
                else:
                    session.execute(
                        schema.sync_job_definitions.update()
                        .where(schema.sync_job_definitions.c.id == job.id)
                        .values(
                            name=job.name,
                            description=job.description,
                            source_id=job.source_id,
                            target_table=job.target_table,
                            enabled=job.enabled,
                            default_params=job.default_params,
                            schedule_cron=job.schedule_cron,
                        )
                    )

            # Seed default batch schedules (unified incremental sync slots).
            for sched in DEFAULT_BATCH_SCHEDULES:
                existing_sched = session.execute(
                    select(schema.sync_batch_schedules).where(
                        schema.sync_batch_schedules.c.id == sched["id"]
                    )
                ).first()
                sched_values = {
                    "id": sched["id"],
                    "name": sched["name"],
                    "cron": sched["cron"],
                    "action": sched.get("action") or "sync",
                    "job_ids": sched["job_ids"],
                    "enabled": sched["enabled"],
                    "concurrency": sched["concurrency"],
                }
                if existing_sched is None:
                    session.execute(schema.sync_batch_schedules.insert().values(**sched_values))
                else:
                    session.execute(
                        schema.sync_batch_schedules.update()
                        .where(schema.sync_batch_schedules.c.id == sched["id"])
                        .values(**sched_values)
                    )
            for schedule_id, reason in OBSOLETE_BATCH_SCHEDULE_IDS.items():
                session.execute(
                    schema.sync_batch_schedules.update()
                    .where(schema.sync_batch_schedules.c.id == schedule_id)
                    .values(
                        enabled=False,
                        last_status="disabled",
                        last_finished_at=datetime.now(timezone.utc),
                        last_message=reason,
                    )
                )
    except Exception as exc:
        logger.warning("seed_default_registry failed: %s", exc)


def mark_interrupted_runs() -> list[str]:
    """Mark runs left in running state by a previous API process as failed."""
    interrupted_schedule_ids: list[str] = []
    try:
        with session_scope() as session:
            interrupted_schedule_ids = [
                str(schedule_id)
                for schedule_id in session.execute(
                    select(schema.sync_batch_schedules.c.id).where(
                        schema.sync_batch_schedules.c.last_status == "running"
                    )
                )
                .scalars()
                .all()
            ]
            session.execute(
                schema.sync_job_runs.update()
                .where(schema.sync_job_runs.c.status == "running")
                .values(
                    status="failed",
                    message=INTERRUPTED_SYNC_JOB_MESSAGE,
                    error_type="Interrupted",
                    finished_at=datetime.now(timezone.utc),
                )
            )
            session.execute(
                schema.sync_job_definitions.update()
                .where(schema.sync_job_definitions.c.last_status == "running")
                .values(
                    last_status="failed",
                    last_message=INTERRUPTED_SYNC_JOB_MESSAGE,
                    last_finished_at=datetime.now(timezone.utc),
                )
            )
            session.execute(
                schema.sync_batch_schedules.update()
                .where(schema.sync_batch_schedules.c.last_status == "running")
                .values(
                    last_status="failed",
                    last_message=INTERRUPTED_SCHEDULE_MESSAGE,
                    last_finished_at=datetime.now(timezone.utc),
                )
            )
    except Exception as exc:
        logger.warning("mark_interrupted_runs failed: %s", exc)
        return []
    _queue_interrupted_schedule_recovery(interrupted_schedule_ids)
    return interrupted_schedule_ids


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


# ─── Batch schedule CRUD ─────────────────────────────────────────────────


def list_schedules() -> list[dict[str, Any]]:
    if not is_database_configured():
        return []
    with session_scope() as session:
        rows = session.execute(
            select(schema.sync_batch_schedules).order_by(schema.sync_batch_schedules.c.id)
        ).mappings().all()
    return [dict(row) for row in rows]


def _assert_cron(cron: str) -> None:
    if not cron or len(cron.split()) != 5:
        raise DataSyncError("cron must be a 5-field expression")


def _assert_known_jobs(
    job_ids: list[str],
    *,
    allow_tail_preview_cache: bool = False,
    allow_eod_quant_research: bool = False,
) -> None:
    valid = {job.id for job in DEFAULT_JOBS}
    unknown = [
        j for j in job_ids
        if j not in valid
        and not (allow_tail_preview_cache and j == TAIL_PREVIEW_BATCH_JOB_ID)
        and not (allow_eod_quant_research and j == EOD_QUANT_RESEARCH_BATCH_JOB_ID)
    ]
    if unknown:
        raise DataSyncError(f"Unknown job_ids: {unknown}")


def _schedule_job_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DataSyncError("job_ids must be a list")
    return [str(item) for item in value]


def _assert_schedule_jobs(action: str, job_ids: list[str]) -> None:
    if action not in {"sync", "tail_preview"}:
        return
    if not job_ids:
        raise DataSyncError(f"{action} schedules require at least one job_id")
    _assert_known_jobs(
        job_ids,
        allow_tail_preview_cache=action == "tail_preview",
        allow_eod_quant_research=action == "sync",
    )


def _schedule_action(payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or "sync").strip()
    if action not in {"sync", "quant_research", "tail_preview"}:
        raise DataSyncError(f"Unsupported schedule action: {action}")
    return action


def create_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise DataSyncError("name is required")
    cron = str(payload.get("cron") or "").strip()
    action = _schedule_action(payload)
    job_ids = [] if action == "quant_research" else _schedule_job_ids(payload.get("job_ids") or [])
    _assert_cron(cron)
    _assert_schedule_jobs(action, job_ids)
    schedule_id = str(payload.get("id") or f"custom_{uuid4().hex[:8]}")
    values = {
        "id": schedule_id,
        "name": name,
        "cron": cron,
        "action": action,
        "job_ids": job_ids,
        "enabled": bool(payload.get("enabled", True)),
        "concurrency": int(payload.get("concurrency", 8)),
    }
    with session_scope() as session:
        existing = session.execute(
            select(schema.sync_batch_schedules).where(schema.sync_batch_schedules.c.id == schedule_id)
        ).first()
        if existing:
            raise DataSyncError(f"schedule {schedule_id} already exists")
        session.execute(schema.sync_batch_schedules.insert().values(**values))
    return values


def update_schedule(schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = ("name", "cron", "action", "job_ids", "enabled", "concurrency")
    updates: dict[str, Any] = {k: payload[k] for k in allowed if k in payload}
    if "cron" in updates:
        _assert_cron(str(updates["cron"]))
    with session_scope() as session:
        existing = session.execute(
            select(schema.sync_batch_schedules).where(schema.sync_batch_schedules.c.id == schedule_id)
        ).mappings().first()
        if not existing:
            raise DataSyncError(f"schedule {schedule_id} not found")
        next_action = _schedule_action(updates) if "action" in updates else str(existing.get("action") or "sync")
        if "job_ids" in updates:
            updates["job_ids"] = _schedule_job_ids(updates["job_ids"])
        if next_action == "quant_research":
            if "action" in updates or "job_ids" in updates:
                updates["job_ids"] = []
        elif "action" in updates or "job_ids" in updates:
            next_job_ids = updates.get("job_ids")
            if next_job_ids is None:
                next_job_ids = _schedule_job_ids(existing.get("job_ids") or [])
            _assert_schedule_jobs(next_action, list(next_job_ids))
        if updates:
            session.execute(
                schema.sync_batch_schedules.update()
                .where(schema.sync_batch_schedules.c.id == schedule_id)
                .values(**updates)
            )
    return {"id": schedule_id, **updates}


def delete_schedule(schedule_id: str) -> dict[str, Any]:
    with session_scope() as session:
        existing = session.execute(
            select(schema.sync_batch_schedules).where(schema.sync_batch_schedules.c.id == schedule_id)
        ).first()
        if not existing:
            raise DataSyncError(f"schedule {schedule_id} not found")
        session.execute(
            schema.sync_batch_schedules.delete().where(schema.sync_batch_schedules.c.id == schedule_id)
        )
    return {"id": schedule_id, "deleted": True}


def run_schedule_now(schedule_id: str) -> dict[str, Any]:
    if not is_database_configured():
        raise DataSyncError("DATABASE_URL is not configured")
    with session_scope() as session:
        row = session.execute(
            select(schema.sync_batch_schedules).where(schema.sync_batch_schedules.c.id == schedule_id)
        ).mappings().first()
    if not row:
        raise DataSyncError(f"schedule {schedule_id} not found")
    action = str(row.get("action") or "sync")
    if action == "quant_research":
        research_run = _run_schedule_action(dict(row), raise_errors=True) or {}
        return _quant_research_schedule_status(schedule_id, research_run)
    return _start_sync_schedule(dict(row), source="manual")


def run_tail_prepare_now() -> dict[str, Any]:
    """Start the default fast tail-session preparation batch."""

    return run_schedule_now("tail_preview_14h")


def _quant_research_schedule_status(schedule_id: str, research_run: dict[str, Any]) -> dict[str, Any]:
    """Represent a quant-research schedule trigger as a batch-like response."""

    status = str(research_run.get("status") or "running")
    completed = 0 if status == "running" else 1
    progress_pct = float(research_run.get("progress_pct") or (0 if status == "running" else 100))
    created_at = str(research_run.get("created_at") or _utc_now_iso())
    started_at = research_run.get("started_at") or created_at
    finished_at = research_run.get("finished_at")
    message = str(research_run.get("message") or "尾盘量化任务已启动")
    return {
        "id": f"quant_{research_run.get('id') or uuid4().hex}",
        "profile": "quant_research",
        "source": "manual",
        "schedule_id": schedule_id,
        "concurrency": 1,
        "status": status,
        "created_at": created_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "current_job_id": "quant_research" if status == "running" else None,
        "total_jobs": 1,
        "completed_jobs": completed,
        "succeeded_jobs": 1 if status == "succeeded" else 0,
        "failed_jobs": 1 if status == "failed" else 0,
        "skipped_jobs": 0,
        "rows_read": 0,
        "rows_written": 0,
        "progress_pct": progress_pct,
        "message": message,
        "jobs": [
            {
                "job_id": "quant_research",
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "rows_read": 0,
                "rows_written": 0,
                "progress_current": int(research_run.get("progress_current") or completed),
                "progress_total": int(research_run.get("progress_total") or 1),
                "progress_pct": progress_pct,
                "stage": str(research_run.get("stage") or ""),
                "current_label": "",
                "sample_items": [],
                "message": message,
            }
        ],
    }


def _start_sync_schedule(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    job_ids = _schedule_job_ids(row.get("job_ids"))
    action = str(row.get("action") or "sync")
    _assert_schedule_jobs(action, job_ids)
    if action == "tail_preview" and TAIL_PREVIEW_BATCH_JOB_ID not in job_ids:
        job_ids = [*job_ids, TAIL_PREVIEW_BATCH_JOB_ID]
    return start_sync_batch(
        job_ids=job_ids,
        concurrency=int(row.get("concurrency") or 8),
        source=source,
        schedule_id=str(row["id"]),
    )


# ─── Sync batches ────────────────────────────────────────────────────────

def _new_batch_job_item(job_id: str) -> dict[str, Any]:
    """Fresh per-job status entry inside a sync batch."""
    return {
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


def start_sync_batch(
    profile: str = "core",
    job_ids: list[str] | None = None,
    params: dict[str, Any] | None = None,
    concurrency: int = 8,
    source: str = "manual",
    schedule_id: str | None = None,
) -> dict[str, Any]:
    """Start a background batch that runs sync jobs in priority order.

    ``job_ids`` (explicit, e.g. from a schedule) takes precedence over
    ``profile``; ``concurrency`` controls per-job inner parallelism.
    """
    global _LATEST_BATCH_ID

    if not is_database_configured():
        raise DataSyncError("DATABASE_URL is not configured")

    with _BATCH_LOCK:
        if _LATEST_BATCH_ID:
            latest = _SYNC_BATCHES.get(_LATEST_BATCH_ID)
            if latest and latest.get("status") == "running":
                return _copy_batch(latest)

    batch_id = uuid4().hex
    resolved = list(job_ids) if job_ids is not None else list(SYNC_BATCH_PROFILES.get(profile, SYNC_BATCH_PROFILES["core"]))
    created_at = _utc_now_iso()
    batch = {
        "id": batch_id,
        "profile": profile if job_ids is None else "custom",
        "source": source,
        "schedule_id": schedule_id,
        "concurrency": int(concurrency),
        "status": "running",
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": None,
        "current_job_id": resolved[0] if resolved else None,
        "total_jobs": len(resolved),
        "completed_jobs": 0,
        "succeeded_jobs": 0,
        "failed_jobs": 0,
        "skipped_jobs": 0,
        "rows_read": 0,
        "rows_written": 0,
        "message": "",
        "jobs": [_new_batch_job_item(job_id) for job_id in resolved],
    }

    with _BATCH_LOCK:
        _SYNC_BATCHES[batch_id] = batch
        _LATEST_BATCH_ID = batch_id
        _trim_batches_locked()

    thread = threading.Thread(
        target=_run_sync_batch,
        args=(batch_id, {**(params or {}), "_job_ids": resolved}),
        kwargs={"concurrency": int(concurrency), "source": source, "schedule_id": schedule_id},
        name=f"data-sync-batch-{batch_id[:8]}",
        daemon=True,
    )
    thread.start()
    if schedule_id:
        _touch_schedule(schedule_id, last_started_at=datetime.now(timezone.utc), last_status="running")
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


# Base jobs whose failure should skip their downstream dependents.
_BASE_SYNC_JOBS = {"sync_stock_list", "sync_sector_list"}


def _depends_on(job_id: str, upstream: str) -> bool:
    """Whether ``job_id`` depends on a failed base ``upstream`` job.

    Used only to skip downstream jobs when a base job fails: per-stock jobs
    depend on the stock list, sector jobs on the sector list.
    """
    if upstream == "sync_stock_list":
        if job_id == TAIL_PREVIEW_BATCH_JOB_ID:
            return True
        return job_id.startswith("sync_stock_") and job_id not in _BASE_SYNC_JOBS
    if upstream == "sync_sector_list":
        return job_id.startswith("sync_sector_") or job_id == "sync_stock_sector_memberships"
    return False


def _run_sync_batch(
    batch_id: str,
    params: dict[str, Any],
    *,
    concurrency: int = 8,
    source: str = "manual",
    schedule_id: str | None = None,
) -> None:
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if not batch:
            return
        job_ids = [item["job_id"] for item in batch["jobs"]]

    for index, job_id in enumerate(job_ids):
        # Skip jobs already marked skipped due to an upstream base-job failure.
        with _BATCH_LOCK:
            snapshot = _SYNC_BATCHES.get(batch_id)
            item = next((it for it in snapshot.get("jobs", []) if it["job_id"] == job_id), None) if snapshot else None
        if item and item.get("status") == "skipped":
            continue

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
            if job_id == TAIL_PREVIEW_BATCH_JOB_ID:
                result = _run_tail_preview_cache_batch_job(params, schedule_id=schedule_id)
            elif job_id == EOD_QUANT_RESEARCH_BATCH_JOB_ID:
                result = _run_eod_quant_research_batch_job(
                    _batch_job_params(job_id, params),
                    progress=_batch_progress_callback(batch_id, job_id),
                )
            else:
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
            # A failed base job skips its downstream dependents, but the batch continues.
            if job_id in _BASE_SYNC_JOBS:
                for later_id in job_ids[index + 1:]:
                    if _depends_on(later_id, job_id):
                        _update_batch_job(
                            batch_id,
                            later_id,
                            {
                                "status": "skipped",
                                "finished_at": _utc_now_iso(),
                                "message": f"上游 {job_id} 失败，跳过",
                                "stage": "跳过",
                            },
                        )
                        _increment_batch(batch_id, completed=1, skipped=1)
            continue

        with _BATCH_LOCK:
            batch = _SYNC_BATCHES.get(batch_id)
            if batch:
                batch["current_job_id"] = job_ids[index + 1] if index + 1 < len(job_ids) else None

    # Determine terminal status from success/failure counts (no early abort).
    with _BATCH_LOCK:
        final = _SYNC_BATCHES.get(batch_id)
        failed = int(final.get("failed_jobs") or 0) if final else 0
        succeeded = int(final.get("succeeded_jobs") or 0) if final else 0
    if not final:
        return
    if failed and succeeded == 0:
        _finish_batch(batch_id, "failed", "全部失败")
    elif failed:
        _finish_batch(batch_id, "partial", f"{succeeded} 成功 / {failed} 失败")
    else:
        _finish_batch(batch_id, "succeeded", "同步完成")


def _run_tail_preview_cache_batch_job(params: dict[str, Any], *, schedule_id: str | None = None) -> dict[str, Any]:
    preview_params = _batch_job_params(TAIL_PREVIEW_BATCH_JOB_ID, params)
    result = screening.generate_tail_preview_cache(
        _parse_date(preview_params.get("trade_date")),
        strategy_id=str(preview_params.get("strategy") or screening.STRATEGY_ID),
        max_symbols=int(preview_params.get("max_symbols") or 5000),
        recommendation_limit=int(preview_params.get("recommendation_limit") or 100),
        min_recommendation_score=float(preview_params.get("min_recommendation_score") or 60),
        included_boards=preview_params.get("included_boards"),
        source_schedule_id=schedule_id,
    )
    return {
        "rows_read": int(result.get("total") or 0),
        "rows_written": int(result.get("recommendation_count") or 0),
        "message": (
            f"今日预览 {result.get('trade_date') or '-'}："
            f"{result.get('recommendation_count') or 0} 个推荐 / {result.get('total') or 0} 个候选"
        ),
        "trade_date": result.get("trade_date"),
        "status": result.get("status"),
    }


def _run_eod_quant_research_batch_job(
    params: dict[str, Any] | None = None,
    *,
    progress: ProgressCallback | None = None,
    poll_interval_seconds: float = 2.0,
    timeout_seconds: float = 1800.0,
) -> dict[str, Any]:
    """Run the true post-close quant workflow after complete daily bars exist."""

    run_params = params or {}
    latest_complete_date = _latest_complete_daily_date_for_research()
    if latest_complete_date is None:
        return {
            "rows_read": 0,
            "rows_written": 0,
            "status": "empty",
            "message": "完整日线不足，跳过盘后真实量化。",
        }
    if progress:
        progress(
            {
                "stage": "盘后量化",
                "current_label": latest_complete_date.isoformat(),
                "progress_current": 0,
                "progress_total": 1,
                "message": f"正在生成 {latest_complete_date.isoformat()} 真实候选并回测",
            }
        )
    research_run = research_jobs.start_research_run(
        start=_parse_date(run_params.get("start") or run_params.get("start_date")),
        end=_parse_date(run_params.get("end") or run_params.get("end_date")) or latest_complete_date,
        strategy_id=str(run_params.get("strategy") or screening.STRATEGY_ID),
        max_symbols=int(run_params.get("max_symbols") or 5000),
        recommendation_limit=int(run_params.get("recommendation_limit") or screening.DEFAULT_RECOMMENDATION_LIMIT),
        min_recommendation_score=float(run_params.get("min_recommendation_score") or 60),
        min_entry_score=_float_or_none(run_params.get("min_entry_score")),
        persist=bool(run_params.get("persist", True)),
        auto_portfolio=bool(run_params.get("auto_portfolio", True)),
        included_boards=run_params.get("included_boards"),
        initial_cash=float(run_params.get("initial_cash") or 1_000_000),
        max_positions=int(run_params.get("max_positions") or 10),
        candidate_limit=int(run_params.get("candidate_limit") or 20),
        max_position_pct=float(run_params.get("max_position_pct") or 0.1),
        strict_entry=bool(run_params.get("strict_entry", True)),
        execution_model=str(run_params.get("execution_model") or "legacy_next_open"),
        force_refresh=bool(run_params.get("force_refresh", False)),
    )
    run_id = str(research_run.get("id") or "")
    started = time.monotonic()
    latest = research_run
    while str(latest.get("status") or "") == "running":
        if time.monotonic() - started > timeout_seconds:
            raise DataSyncError(f"盘后量化超时：research_run={run_id}")
        if progress:
            progress(
                {
                    "stage": str(latest.get("stage") or "盘后量化"),
                    "current_label": str(latest.get("message") or latest_complete_date.isoformat()),
                    "progress_current": int(latest.get("progress_current") or 0),
                    "progress_total": int(latest.get("progress_total") or 1),
                    "message": str(latest.get("message") or "盘后量化运行中"),
                }
            )
        time.sleep(max(float(poll_interval_seconds), 0.05))
        latest = research_jobs.get_research_run(run_id)
    if str(latest.get("status") or "") != "succeeded":
        raise DataSyncError(str(latest.get("message") or "盘后量化失败"))
    backtest = latest.get("backtest") if isinstance(latest.get("backtest"), dict) else {}
    screen_run = latest.get("screen_run") if isinstance(latest.get("screen_run"), dict) else {}
    if progress:
        progress(
            {
                "stage": "完成",
                "current_label": latest_complete_date.isoformat(),
                "progress_current": 1,
                "progress_total": 1,
                "message": "盘后真实候选和组合回测完成",
            }
        )
    return {
        "rows_read": int(screen_run.get("total") or 0),
        "rows_written": int(screen_run.get("recommendation_count") or 0),
        "status": "succeeded",
        "run_id": run_id,
        "backtest_id": backtest.get("backtest_id") or latest.get("backtest_id"),
        "trade_date": latest_complete_date.isoformat(),
        "message": (
            f"盘后真实量化完成：{latest_complete_date.isoformat()}，"
            f"候选 {screen_run.get('recommendation_count') or 0}，"
            f"回测 #{backtest.get('backtest_id') or latest.get('backtest_id') or '-'}"
        ),
    }


def _latest_complete_daily_date_for_research() -> date | None:
    if not is_database_configured():
        return None
    with session_scope() as session:
        return _latest_complete_daily_date(session)


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


def _increment_batch(batch_id: str, completed: int = 0, succeeded: int = 0, failed: int = 0, skipped: int = 0, rows_read: int = 0, rows_written: int = 0) -> None:
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if not batch:
            return
        batch["completed_jobs"] = int(batch.get("completed_jobs") or 0) + completed
        batch["succeeded_jobs"] = int(batch.get("succeeded_jobs") or 0) + succeeded
        batch["failed_jobs"] = int(batch.get("failed_jobs") or 0) + failed
        batch["skipped_jobs"] = int(batch.get("skipped_jobs") or 0) + skipped
        batch["rows_read"] = int(batch.get("rows_read") or 0) + rows_read
        batch["rows_written"] = int(batch.get("rows_written") or 0) + rows_written


def _touch_schedule(schedule_id: str | None, **fields: Any) -> None:
    """Best-effort update of status fields on a batch schedule row."""
    if not schedule_id or not is_database_configured():
        return
    try:
        with session_scope() as session:
            session.execute(
                schema.sync_batch_schedules.update()
                .where(schema.sync_batch_schedules.c.id == schedule_id)
                .values(**fields)
            )
    except Exception:
        logger.debug("touch schedule %s failed", schedule_id, exc_info=True)


def _finish_batch(batch_id: str, status: str, message: str) -> None:
    with _BATCH_LOCK:
        batch = _SYNC_BATCHES.get(batch_id)
        if not batch:
            return
        batch["status"] = status
        batch["finished_at"] = _utc_now_iso()
        batch["current_job_id"] = None
        batch["message"] = message
        schedule_id = batch.get("schedule_id")
    # Reflect terminal status back onto the originating schedule (best-effort).
    if schedule_id:
        _touch_schedule(
            schedule_id,
            last_status=status,
            last_finished_at=datetime.now(timezone.utc),
            last_message=(message or "")[:500],
        )


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


def data_health() -> dict[str, Any]:
    """数据健康仪表盘：合并覆盖率 + 最新交易日 + 任务节奏，算出每类数据的新鲜度与推荐同步清单。

    前端 `/data` 健康首页直消费。合并同表查询（每个 (table, col) 只探一次 MAX）。
    """
    now = _now_china()
    cov = coverage()
    tables_cov = cov.get("tables", {}) if isinstance(cov, dict) else {}

    is_empty = _is_empty_database(tables_cov)
    latest_trade_date, cal_source = _resolve_latest_trade_date()
    disclosure_season = _is_disclosure_season(now)

    probes = _collect_freshness_probes()

    job_results: dict[str, dict[str, Any]] = {}
    for job in DEFAULT_JOBS:
        cad = JOB_CADENCES.get(job.id)
        if cad is None:
            continue
        probe_value = probes.get((cad.freshness_table, cad.freshness_col))
        severity, reason, is_stale = _evaluate_job_staleness(
            cad, now, latest_trade_date, disclosure_season, probe_value,
        )
        job_results[job.id] = {
            "job_id": job.id,
            "name": job.name,
            "cadence": cad.cadence,
            "category": cad.category,
            "is_stale": is_stale,
            "severity": severity,
            "local_latest": _iso_or_none(probe_value),
            "staleness_days": cad.staleness_days,
            "reason": reason,
            "recommended": is_stale,
        }

    recommended = _compute_recommended_jobs(job_results)
    categories = _group_health_categories(job_results)
    stale_count = sum(1 for info in job_results.values() if info["is_stale"])
    fresh_count = sum(1 for info in job_results.values() if not info["is_stale"])
    overall_health, summary = _overall_health(is_empty, job_results, stale_count)

    return {
        "generated_at": now.isoformat(),
        "overall": {
            "health": overall_health,
            "summary": summary,
            "is_empty_database": is_empty,
            "empty_core_tables": (
                [t for t in EMPTY_CORE_TABLES if tables_cov.get(t, {}).get("count", 0) == 0]
                if is_empty else []
            ),
            "stale_count": stale_count,
            "fresh_count": fresh_count,
            "recommended_count": len(recommended),
        },
        "market_context": {
            "now": now.isoformat(),
            "latest_trade_date": _iso_or_none(latest_trade_date),
            "is_disclosure_season": disclosure_season,
            "trade_calendar_source": cal_source,
        },
        "categories": categories,
        "recommended": {
            "job_ids": recommended,
            "count": len(recommended),
            "rationale": _recommended_rationale(recommended, job_results),
        },
        "bootstrap": {
            "needed": is_empty,
            "core_profile_job_ids": list(SYNC_BATCH_PROFILES["core"]),
            "message": (
                "检测到核心表为空，建议先执行「核心数据」初始化同步（首次全量耗时较长，建议非交易时段）。"
                if is_empty else None
            ),
        },
    }


def _resolve_latest_trade_date() -> tuple[date | None, str]:
    """用本地 stock_daily_bars.MAX(trade_date) 反推最新交易日（最可靠）。

    空库时返回 (None, "unknown")，调用方走 staleness 兜底，不阻塞。
    """
    if not is_database_configured():
        return None, "unknown"
    try:
        with session_scope() as session:
            value = session.execute(
                select(func.max(schema.stock_daily_bars.c.trade_date))
            ).scalar()
            if value is not None:
                return _as_date(value), "stock_daily_bars"
    except Exception as exc:  # noqa: BLE001 — 健康检查不能因查询失败而崩
        logger.warning("resolve latest trade date failed: %s", exc)
    return None, "unknown"


def _collect_freshness_probes() -> dict[tuple[str, str], Any]:
    """对每个唯一的 (table, col) 探一次 MAX(col)，结果缓存复用。"""
    pairs: set[tuple[str, str]] = {(c.freshness_table, c.freshness_col) for c in JOB_CADENCES.values()}
    probes: dict[tuple[str, str], Any] = {}
    if not is_database_configured():
        return probes
    with session_scope() as session:
        for table_name, col_name in pairs:
            table_obj = getattr(schema, table_name, None)
            if table_obj is None:
                continue
            column = getattr(table_obj.c, col_name, None)
            if column is None:
                continue
            try:
                probes[(table_name, col_name)] = session.execute(select(func.max(column))).scalar()
            except Exception as exc:  # noqa: BLE001 — 列缺失/查询失败退化为 None
                logger.debug("freshness probe %s.%s failed: %s", table_name, col_name, exc)
                probes[(table_name, col_name)] = None
    return probes


def _as_date(value: Any) -> date | None:
    """把 date/datetime/iso 字符串统一转 date。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _is_disclosure_season(now: datetime) -> bool:
    """A股财报披露窗口：一季报(4)、半年报(7-8)、三季报(10)、年报(1-4/15)。"""
    month, day = now.month, now.day
    return month in (1, 4, 7, 8, 10) or (month == 5 and day <= 15)


def _is_empty_database(tables_cov: dict[str, Any]) -> bool:
    return all(tables_cov.get(t, {}).get("count", 0) == 0 for t in EMPTY_CORE_TABLES)


def _evaluate_job_staleness(
    cad: JobCadence,
    now: datetime,
    latest_trade_date: date | None,
    disclosure_season: bool,
    probe_value: Any,
) -> tuple[str, str, bool]:
    """返回 (severity, reason, is_stale)。severity: fresh/stale/empty。"""
    if probe_value is None:
        return "empty", "本地暂无数据", True

    # 季报：非披露季不提醒，避免 6 月误报"财务落后"
    if cad.cadence == CADENCE_QUARTERLY:
        if not disclosure_season:
            return "fresh", "非财报披露季，无需同步", False
        days = (now.date() - _as_date(probe_value)).days
        if days > cad.staleness_days:
            return "stale", f"披露季内已 {days} 天未更新", True
        return "fresh", f"披露季内，{days} 天前更新", False

    # 日线 / 龙虎榜：对齐最新交易日
    if cad.cadence in (CADENCE_EOD_DAILY, CADENCE_LHB):
        local_date = _as_date(probe_value)
        if latest_trade_date is None or local_date is None:
            days = (now.date() - (local_date or now.date())).days
            return ("stale", f"已 {days} 天未同步（交易日历未知）", True) if days > cad.staleness_days else ("fresh", f"{days} 天前同步", False)
        # 龙虎榜当日 18:00 后才发布：盘中（now<18）容忍本地停在上一交易日的龙虎榜（跨周末最多 3 天）
        if cad.cadence == CADENCE_LHB and now.hour < 18:
            if (latest_trade_date - local_date).days <= 3:
                return "fresh", f"今日龙虎榜 18:00 后发布，本地已含 {local_date}", False
        if local_date >= latest_trade_date:
            return "fresh", f"已同步至 {local_date}", False
        gap = (latest_trade_date - local_date).days
        return "stale", f"落后约 {gap} 天（最新 {latest_trade_date}，本地 {local_date}）", True

    # 盘中实时：按小时判定（时间戳列）
    if isinstance(probe_value, datetime):
        probe_aware = probe_value if probe_value.tzinfo else probe_value.replace(tzinfo=timezone.utc)
        now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        hours = (now_aware - probe_aware).total_seconds() / 3600
        if hours > cad.staleness_days * 24:
            return "stale", f"已 {int(hours)} 小时未刷新", True
        return "fresh", f"{int(hours)} 小时前刷新", False

    # 低频：按天判定
    days = (now.date() - _as_date(probe_value)).days
    if days > cad.staleness_days:
        return "stale", f"已 {days} 天未同步", True
    return "fresh", f"{days} 天前同步", False


def _compute_recommended_jobs(job_results: dict[str, dict[str, Any]]) -> list[str]:
    """筛 is_stale 的任务，按依赖优先级排序。"""
    priority_index = {jid: i for i, jid in enumerate(_RECOMMENDED_PRIORITY)}
    stale = [jid for jid, info in job_results.items() if info["is_stale"]]
    return sorted(stale, key=lambda j: priority_index.get(j, 999))


def _group_health_categories(job_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """按 category 分组，返回前端卡片网格用结构。"""
    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in CATEGORY_ORDER}
    for info in job_results.values():
        buckets.setdefault(info["category"], []).append(info)
    categories: list[dict[str, Any]] = []
    for key in CATEGORY_ORDER:
        jobs = buckets.get(key, [])
        if not jobs:
            continue
        categories.append({
            "key": key,
            "label": CATEGORY_LABELS.get(key, key),
            "health": _category_health(jobs),
            "jobs": sorted(jobs, key=lambda j: j["job_id"]),
        })
    return categories


def _category_health(jobs: list[dict[str, Any]]) -> str:
    if any(j["severity"] == "empty" for j in jobs):
        return "red"
    if any(j["is_stale"] for j in jobs):
        return "yellow"
    return "green"


def _overall_health(
    is_empty: bool,
    job_results: dict[str, dict[str, Any]],
    stale_count: int,
) -> tuple[str, str]:
    if is_empty:
        return "red", "核心表为空，需要初始化数据"
    critical_empty = any(
        info["severity"] == "empty"
        and info["category"] in (CATEGORY_MARKET_BASIC, CATEGORY_MARKET_BARS)
        for info in job_results.values()
    )
    if critical_empty or stale_count >= 5:
        return "red", f"{stale_count} 项数据需要同步"
    if stale_count > 0:
        return "yellow", f"{stale_count} 项数据建议同步"
    return "green", "数据新鲜，无需同步"


def _recommended_rationale(
    recommended: list[str],
    job_results: dict[str, dict[str, Any]],
) -> str:
    if not recommended:
        return "当前数据新鲜，暂无推荐同步项"
    names = [job_results[jid]["name"] for jid in recommended[:5] if jid in job_results]
    tail = f" 等 {len(recommended)} 项" if len(recommended) > len(names) else ""
    return "建议同步：" + "、".join(names) + tail


def tail_workflow_status() -> dict[str, Any]:
    """Return the compact state needed by the ordinary tail-preparation UI."""

    if not is_database_configured():
        return {"status": "unavailable", "message": "DATABASE_URL not configured"}
    with session_scope() as session:
        latest_daily_date = session.execute(select(func.max(schema.stock_daily_bars.c.trade_date))).scalar()
        latest_complete_daily_date = _latest_complete_daily_date(session)
        latest_daily_updated = session.execute(select(func.max(schema.stock_daily_bars.c.updated_at))).scalar()
        latest_snapshot_updated = session.execute(select(func.max(schema.stocks.c.updated_at))).scalar()
        latest_snapshot_trade_time = session.execute(select(func.max(schema.stocks.c.trade_time))).scalar()
        latest_minute_date = session.execute(select(func.max(schema.stock_minute_bars.c.trade_date))).scalar()
        latest_tail_intraday_date = session.execute(
            select(func.max(schema.stock_minute_bars.c.trade_date)).where(
                schema.stock_minute_bars.c.interval == "1m"
            )
        ).scalar()
        latest_minute_time = session.execute(select(func.max(schema.stock_minute_bars.c.bar_time))).scalar()
        latest_candidate = session.execute(
            select(schema.quant_signal_runs)
            .where(
                schema.quant_signal_runs.c.status == "succeeded",
                schema.quant_signal_runs.c.strategy_id == screening.STRATEGY_ID,
                schema.quant_signal_runs.c.strategy_version == screening.STRATEGY_VERSION,
            )
            .order_by(desc(schema.quant_signal_runs.c.trade_date), desc(schema.quant_signal_runs.c.id))
            .limit(1)
        ).mappings().first()
        latest_tail_cache = session.execute(
            select(schema.quant_tail_preview_cache)
            .order_by(
                desc(schema.quant_tail_preview_cache.c.trade_date),
                desc(schema.quant_tail_preview_cache.c.generated_at),
            )
            .limit(1)
        ).mappings().first()
        latest_replay_run = session.execute(
            select(schema.strategy_replay_runs)
            .where(
                schema.strategy_replay_runs.c.strategy_id == screening.STRATEGY_ID,
                schema.strategy_replay_runs.c.strategy_version == screening.STRATEGY_VERSION,
            )
            .order_by(desc(schema.strategy_replay_runs.c.end_date), desc(schema.strategy_replay_runs.c.id))
            .limit(1)
        ).mappings().first()
        latest_backtest = session.execute(
            select(schema.backtest_runs)
            .where(
                schema.backtest_runs.c.strategy_id == screening.STRATEGY_ID,
                schema.backtest_runs.c.strategy_version == screening.STRATEGY_VERSION,
                schema.backtest_runs.c.status == "succeeded",
            )
            .order_by(desc(schema.backtest_runs.c.end_date), desc(schema.backtest_runs.c.id))
            .limit(50)
        ).mappings().all()
        schedule_rows = session.execute(select(schema.sync_batch_schedules)).mappings().all()
    schedules = {str(row["id"]): dict(row) for row in schedule_rows}
    latest_research = _compact_latest_research_run(research_jobs.get_latest_research_run()) or _latest_research_summary_from_db(
        latest_candidate,
        latest_replay_run,
        latest_backtest,
    )
    candidate_date = latest_candidate["trade_date"] if latest_candidate else None
    tail_preview_trade_date = _tail_preview_trade_date(latest_tail_intraday_date, latest_complete_daily_date)
    tail_preview_ready = bool(
        tail_preview_trade_date
        and latest_complete_daily_date
        and tail_preview_trade_date > latest_complete_daily_date
    )
    usable_tail_cache = (
        latest_tail_cache
        if latest_tail_cache
        and tail_preview_trade_date
        and latest_tail_cache.get("trade_date") == tail_preview_trade_date
        and _tail_preview_cache_has_intraday(dict(latest_tail_cache))
        else None
    )
    usable_tail_cache_payload = (
        usable_tail_cache.get("payload")
        if usable_tail_cache and isinstance(usable_tail_cache.get("payload"), dict)
        else {}
    )
    return {
        "status": "ready",
        "daily_bar_latest_date": _iso_or_none(latest_daily_date),
        "daily_bar_latest_complete_date": _iso_or_none(latest_complete_daily_date),
        "daily_bar_updated_at": _iso_or_none(latest_daily_updated),
        "intraday_snapshot_updated_at": _iso_or_none(latest_snapshot_updated),
        "intraday_snapshot_trade_time": str(latest_snapshot_trade_time) if latest_snapshot_trade_time else None,
        "minute_latest_date": _iso_or_none(latest_minute_date),
        "minute_latest_time": _iso_or_none(latest_minute_time),
        "candidate_latest_date": _iso_or_none(candidate_date),
        "candidate_updated_at": _iso_or_none(latest_candidate.get("finished_at")) if latest_candidate else None,
        "latest_research_run": latest_research,
        "tail_prepare_schedule": schedules.get("tail_preview_14h") or schedules.get("tail_prepare_14h"),
        "tail_quant_schedule": schedules.get("tail_quant_1430"),
        "eod_schedule": schedules.get("eod_18h"),
        "tail_prepare_ready": bool(tail_preview_ready or usable_tail_cache),
        "tail_preview": {
            "status": "ready" if (tail_preview_ready or usable_tail_cache) else "waiting",
            "trade_date": tail_preview_trade_date.isoformat() if tail_preview_trade_date else None,
            "data_source": screening.TAIL_PREVIEW_DATA_SOURCE,
            "temporary_bar": True,
            "base_daily_date": str(usable_tail_cache_payload.get("base_daily_date") or "") or _iso_or_none(latest_complete_daily_date or latest_daily_date),
            "cached_trade_date": _iso_or_none(usable_tail_cache.get("trade_date")) if usable_tail_cache else None,
            "cached_generated_at": _iso_or_none(usable_tail_cache.get("generated_at")) if usable_tail_cache else None,
            "cached_recommendation_count": int(usable_tail_cache.get("recommendation_count") or 0) if usable_tail_cache else 0,
            "cached_total": int(usable_tail_cache.get("total") or 0) if usable_tail_cache else 0,
            "snapshot_updated_at": _iso_or_none(latest_snapshot_updated),
            "latest_intraday_date": _iso_or_none(latest_tail_intraday_date),
            "minute_latest_date": _iso_or_none(latest_minute_date),
            "message": (
                "今日尾盘预览可用；使用盘中快照/分钟线临时K线，不写入历史候选。"
                if tail_preview_ready or usable_tail_cache
                else "等待晚于最新完整日线的盘中分钟线；不会只用同步时间生成尾盘预览。"
            ),
        },
        "message": "历史候选仍使用完整日线；今日尾盘预览使用盘中临时K线，不参与回测收益统计。",
    }


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _tail_preview_trade_date(latest_intraday_date: Any, latest_complete_daily_date: Any) -> date | None:
    if latest_intraday_date is None:
        return None
    candidate = latest_intraday_date
    if isinstance(candidate, datetime):
        candidate = candidate.date()
    elif not isinstance(candidate, date):
        candidate = _parse_date(candidate)
    if candidate is None:
        return None
    complete = latest_complete_daily_date
    if isinstance(complete, datetime):
        complete = complete.date()
    elif complete is not None and not isinstance(complete, date):
        complete = _parse_date(complete)
    if complete is not None and candidate <= complete:
        return None
    return candidate


def _tail_preview_cache_has_intraday(cache_row: dict[str, Any]) -> bool:
    payload = cache_row.get("payload") if isinstance(cache_row.get("payload"), dict) else {}
    if int(payload.get("intraday_bar_count") or 0) > 0:
        return True
    return bool(payload.get("latest_intraday_date"))


def _compact_latest_research_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a status-card sized research payload.

    Full research runs can include every daily candidate in ``screen_run.items``.
    ``tail-workflow`` is polled by the UI, so keep it to progress, coverage and
    summary metrics; detailed candidates stay behind the quant endpoints.
    """

    if not isinstance(run, dict):
        return None
    screen_run = run.get("screen_run") if isinstance(run.get("screen_run"), dict) else {}
    replay_run = run.get("replay_run") if isinstance(run.get("replay_run"), dict) else {}
    if not replay_run and isinstance(screen_run.get("replay_run"), dict):
        replay_run = screen_run.get("replay_run") or {}
    backtest = run.get("backtest") if isinstance(run.get("backtest"), dict) else {}
    return {
        "id": run.get("id"),
        "status": run.get("status"),
        "strategy_id": run.get("strategy_id"),
        "strategy_version": run.get("strategy_version"),
        "created_at": run.get("created_at"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "stage": run.get("stage"),
        "message": run.get("message"),
        "progress_current": run.get("progress_current"),
        "progress_total": run.get("progress_total"),
        "progress_pct": run.get("progress_pct"),
        "params": run.get("params") if isinstance(run.get("params"), dict) else {},
        "screen_run": _compact_screen_run_summary(screen_run),
        "replay_run": _compact_replay_run_summary(replay_run),
        "replay_run_id": run.get("replay_run_id") or replay_run.get("replay_run_id") or screen_run.get("replay_run_id"),
        "backtest_id": run.get("backtest_id") or backtest.get("backtest_id"),
        "backtest": _compact_backtest_summary(backtest),
        "error_type": run.get("error_type"),
        "error_detail": run.get("error_detail"),
    }


def _latest_research_summary_from_db(
    latest_candidate: Any,
    latest_replay_run: Any,
    latest_backtests: Sequence[Any],
) -> dict[str, Any] | None:
    if latest_candidate is None and latest_replay_run is None and not latest_backtests:
        return None
    latest_backtest = _latest_portfolio_backtest_row(latest_backtests)
    screen_summary = _screen_run_summary_from_row(latest_candidate)
    replay_summary = _replay_run_summary_from_row(latest_replay_run)
    backtest_summary = _backtest_summary_from_row(latest_backtest)
    status = "succeeded" if (screen_summary or backtest_summary) else "empty"
    return {
        "id": None,
        "status": status,
        "strategy_id": screening.STRATEGY_ID,
        "strategy_version": screening.STRATEGY_VERSION,
        "created_at": None,
        "started_at": _iso_or_none((latest_backtest or latest_candidate or {}).get("started_at") if isinstance((latest_backtest or latest_candidate or {}), dict) else None),
        "finished_at": _iso_or_none((latest_backtest or latest_candidate or {}).get("finished_at") if isinstance((latest_backtest or latest_candidate or {}), dict) else None),
        "stage": "persisted",
        "message": "最近一次已落库策略研究摘要",
        "progress_current": 1,
        "progress_total": 1,
        "progress_pct": 100,
        "params": {},
        "screen_run": screen_summary,
        "replay_run": replay_summary,
        "replay_run_id": replay_summary.get("replay_run_id") if replay_summary else None,
        "backtest_id": backtest_summary.get("backtest_id") if backtest_summary else None,
        "backtest": backtest_summary,
        "error_type": None,
        "error_detail": None,
    }


def _latest_portfolio_backtest_row(rows: Sequence[Any]) -> dict[str, Any] | None:
    for row in rows:
        item = dict(row)
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        if not params.get("symbols"):
            return item
    return None


def _screen_run_summary_from_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    trade_date = item.get("trade_date")
    return {
        "status": item.get("status"),
        "strategy_id": item.get("strategy_id"),
        "strategy_version": item.get("strategy_version"),
        "start_date": _iso_or_none(trade_date),
        "end_date": _iso_or_none(trade_date),
        "trade_date": _iso_or_none(trade_date),
        "run_id": item.get("id"),
        "total": item.get("candidate_count"),
        "recommendation_count": item.get("recommendation_count"),
        "message": item.get("message"),
    }


def _replay_run_summary_from_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    return {
        "status": item.get("status"),
        "replay_run_id": item.get("id"),
        "strategy_id": item.get("strategy_id"),
        "strategy_version": item.get("strategy_version"),
        "start_date": _iso_or_none(item.get("start_date")),
        "end_date": _iso_or_none(item.get("end_date")),
        "metrics": item.get("metrics") or {},
        "message": item.get("message"),
    }


def _backtest_summary_from_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    return {
        "status": "ready" if item.get("status") == "succeeded" else item.get("status"),
        "backtest_id": item.get("id"),
        "strategy": item.get("strategy_id"),
        "strategy_version": item.get("strategy_version"),
        "start": _iso_or_none(item.get("start_date")),
        "end": _iso_or_none(item.get("end_date")),
        "metrics": item.get("metrics") or {},
        "message": item.get("message"),
    }


def _compact_screen_run_summary(screen_run: dict[str, Any]) -> dict[str, Any] | None:
    if not screen_run:
        return None
    keys = (
        "status",
        "strategy_id",
        "strategy_version",
        "start_date",
        "end_date",
        "trade_date",
        "run_id",
        "total_dates",
        "succeeded_count",
        "processed_count",
        "generated_count",
        "skipped_existing_count",
        "force_refreshed_count",
        "force_refresh",
        "range_recommendation_count",
        "total",
        "recommendation_count",
        "included_boards",
        "replay_run_id",
        "message",
    )
    return {key: screen_run.get(key) for key in keys if key in screen_run}


def _compact_replay_run_summary(replay_run: dict[str, Any]) -> dict[str, Any] | None:
    if not replay_run:
        return None
    keys = (
        "status",
        "replay_run_id",
        "strategy_id",
        "strategy_version",
        "start_date",
        "end_date",
        "metrics",
        "message",
    )
    return {key: replay_run.get(key) for key in keys if key in replay_run}


def _compact_backtest_summary(backtest: dict[str, Any]) -> dict[str, Any] | None:
    if not backtest:
        return None
    keys = (
        "status",
        "backtest_id",
        "strategy",
        "strategy_version",
        "start",
        "end",
        "metrics",
        "message",
    )
    return {key: backtest.get(key) for key in keys if key in backtest}


def _latest_complete_daily_date(session, min_symbol_count: int = screening.MIN_COMPLETE_DAILY_SYMBOL_COUNT) -> date | None:
    row = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)) >= min_symbol_count)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(1)
    ).first()
    return row[0] if row else None


def minute_csv_template() -> str:
    """Return a minimal CSV template for importing historical minute bars."""

    return minute_imports.minute_csv_template()


def import_stock_minute_bars_csv(
    csv_text: str,
    *,
    interval: str = "1m",
    source: str = "manual_csv",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import historical minute bars from CSV text into stock_minute_bars."""

    try:
        return minute_imports.import_stock_minute_bars_csv(
            csv_text,
            interval=interval,
            source=source,
            dry_run=dry_run,
            ensure_schema=ensure_sync_schema,
            database_configured=is_database_configured,
            upsert=_upsert_minute_bars,
        )
    except minute_imports.MinuteImportError as exc:
        raise DataSyncError(str(exc)) from exc


def import_stock_minute_bars_file(
    file_path: str,
    *,
    interval: str = "1m",
    source: str = "manual_csv_file",
    dry_run: bool = False,
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Import historical minute bars from an allowed local CSV file path."""

    try:
        return minute_imports.import_stock_minute_bars_file(
            file_path,
            interval=interval,
            source=source,
            dry_run=dry_run,
            encoding=encoding,
            project_root=PROJECT_ROOT,
            allowed_import_dirs=ALLOWED_IMPORT_DIRS,
            ensure_schema=ensure_sync_schema,
            database_configured=is_database_configured,
            upsert=_upsert_minute_bars,
        )
    except minute_imports.MinuteImportError as exc:
        raise DataSyncError(str(exc)) from exc


def _import_stock_minute_bars_from_reader(
    reader: csv.DictReader,
    *,
    interval: str,
    source: str,
    dry_run: bool,
) -> dict[str, Any]:
    return minute_imports.import_stock_minute_bars_from_reader(
        reader,
        interval=interval,
        source=source,
        dry_run=dry_run,
        ensure_schema=ensure_sync_schema,
        upsert=_upsert_minute_bars,
    )


def _import_stock_minute_bars_from_reader_streaming(
    reader: csv.DictReader,
    *,
    interval: str,
    source: str,
    dry_run: bool,
    batch_size: int = 2000,
) -> dict[str, Any]:
    """Import minute bars from a CSV reader without holding the whole file."""

    return minute_imports.import_stock_minute_bars_from_reader_streaming(
        reader,
        interval=interval,
        source=source,
        dry_run=dry_run,
        ensure_schema=ensure_sync_schema,
        upsert=_upsert_minute_bars,
        batch_size=batch_size,
    )


def audit_minute_gap_csv(
    gap_csv_text: str,
    *,
    interval: str = "1m",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
    min_tail_bars: int = 1,
) -> dict[str, Any]:
    """Check whether stock_minute_bars covers a strict-tail backtest gap CSV."""

    interval = _strict_gap_interval(interval)
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
    tail_entry_end: str = "14:30",
    min_tail_bars: int = 1,
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Check minute-bar coverage for a strict-tail gap CSV file."""

    interval = _strict_gap_interval(interval)
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
    return minute_gaps.audit_minute_gap_requirements(
        requirements,
        interval=interval,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        min_tail_bars=min_tail_bars,
        coverage_counts=_minute_gap_coverage_counts,
    )


def minute_gap_import_template(gap_csv_text: str, *, sample_limit: int = 200) -> str:
    """Build a minute-bar import template scoped to rows from a gap CSV."""

    return minute_gaps.minute_gap_import_template(gap_csv_text, sample_limit=sample_limit)


def minute_gap_vendor_manifest(
    gap_csv_text: str = "",
    *,
    file_path: str = "",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Build a provider-facing request manifest from a strict-tail gap CSV."""

    return minute_gaps.minute_gap_vendor_manifest(
        gap_csv_text,
        file_path=file_path,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        sample_limit=sample_limit,
        allowed_import_file=_allowed_import_file,
    )


def minute_gap_vendor_manifest_csv(
    gap_csv_text: str = "",
    *,
    file_path: str = "",
    tail_entry_start: str = "14:30",
    tail_entry_end: str = "14:30",
) -> str:
    """Return a provider-facing CSV request list for strict-tail gaps."""

    return minute_gaps.minute_gap_vendor_manifest_csv(
        gap_csv_text,
        file_path=file_path,
        tail_entry_start=tail_entry_start,
        tail_entry_end=tail_entry_end,
        allowed_import_file=_allowed_import_file,
    )


def load_minute_gap_requirements(gap_csv_text: str = "", *, file_path: str = "") -> dict[str, Any]:
    """Load strict-tail gap requirements from inline CSV text or an allowed file."""

    return minute_gaps.load_minute_gap_requirements(
        gap_csv_text,
        file_path=file_path,
        allowed_import_file=_allowed_import_file,
    )


def _minute_gap_vendor_rows(items: list[dict[str, Any]], tail_entry_start: str, tail_entry_end: str) -> list[dict[str, Any]]:
    return minute_gaps.minute_gap_vendor_rows(items, tail_entry_start, tail_entry_end)


def _split_vt_symbol(value: str) -> tuple[str, str]:
    return minute_gaps.split_vt_symbol(value)


def _tushare_ts_code(symbol: str, exchange: str) -> str:
    return minute_gaps.tushare_ts_code(symbol, exchange)


def _vendor_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return minute_gaps.vendor_row_to_api(row)


def _parse_minute_gap_requirements(gap_csv_text: str) -> dict[str, Any]:
    return minute_gaps.parse_minute_gap_requirements(gap_csv_text)


def _strict_gap_interval(value: Any) -> str:
    try:
        return minute_gaps.strict_gap_interval(value)
    except minute_gaps.MinuteGapError as exc:
        raise DataSyncError(str(exc)) from exc


def _parse_minute_gap_reader(reader: csv.DictReader) -> dict[str, Any]:
    return minute_gaps.parse_minute_gap_reader(reader)


def _allowed_import_file(file_path: str) -> Path:
    try:
        return minute_imports.allowed_import_file(
            file_path,
            project_root=PROJECT_ROOT,
            allowed_import_dirs=ALLOWED_IMPORT_DIRS,
        )
    except minute_imports.MinuteImportError as exc:
        raise DataSyncError(str(exc)) from exc


def _minute_gap_coverage_counts(
    items: list[dict[str, Any]],
    interval: str,
    tail_entry_start: str,
    tail_entry_end: str,
) -> dict[tuple[str, date], int]:
    return minute_gaps.minute_gap_coverage_counts(items, interval, tail_entry_start, tail_entry_end)


def _parse_time_value(value: Any) -> str:
    return minute_gaps.parse_time_value(value)


def _minute_gap_rows_to_api(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return minute_gaps.minute_gap_rows_to_api(rows)


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
        _finish_run(
            run_id,
            "succeeded",
            rows_read=result.get("rows_read", 0),
            rows_written=result.get("rows_written", 0),
            message=_sync_result_message(result),
        )
        return {
            "run_id": run_id,
            "job_id": job_id,
            "status": "succeeded",
            **result,
        }
    except Exception as exc:
        _finish_run(run_id, "failed", message=str(exc), error_type=exc.__class__.__name__)
        raise DataSyncError(str(exc)) from exc


def _sync_result_message(result: dict[str, Any]) -> str | None:
    message = str(result.get("message") or "").strip()
    if message:
        return message[:500]
    audit = result.get("audit_after")
    if isinstance(audit, dict) and audit.get("status"):
        return (
            f"audit_after={audit.get('status')}, "
            f"covered={audit.get('covered_count', 0)}, "
            f"missing={audit.get('missing_count', 0)}"
        )[:500]
    note = str(result.get("note") or "").strip()
    return note[:500] if note else None


# ─── Scheduler ────────────────────────────────────────────────────────────

def start_data_sync_scheduler() -> None:
    """Start a background thread that runs scheduled jobs."""
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        start_interrupted_schedule_recovery()
        return
    _scheduler_stop.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, name="data-sync-scheduler", daemon=True)
    _scheduler_thread.start()
    start_interrupted_schedule_recovery()
    logger.info("Data sync scheduler started")


def stop_data_sync_scheduler() -> None:
    """Signal the scheduler to stop."""
    _scheduler_stop.set()


def _queue_interrupted_schedule_recovery(schedule_ids: Sequence[str]) -> None:
    if not schedule_ids:
        return
    with _INTERRUPTED_RECOVERY_LOCK:
        _INTERRUPTED_SCHEDULE_RECOVERY_IDS.update(str(schedule_id) for schedule_id in schedule_ids if schedule_id)


def start_interrupted_schedule_recovery(
    *,
    delay_seconds: int = INTERRUPTED_SCHEDULE_RECOVERY_DELAY_SECONDS,
) -> None:
    """Start a one-shot recovery pass for schedules interrupted by process restart."""
    global _interrupted_recovery_thread
    with _INTERRUPTED_RECOVERY_LOCK:
        if not _INTERRUPTED_SCHEDULE_RECOVERY_IDS:
            return
        if _interrupted_recovery_thread is not None and _interrupted_recovery_thread.is_alive():
            return
        schedule_ids = sorted(_INTERRUPTED_SCHEDULE_RECOVERY_IDS)
        _INTERRUPTED_SCHEDULE_RECOVERY_IDS.clear()

    _interrupted_recovery_thread = threading.Thread(
        target=_delayed_interrupted_schedule_recovery,
        args=(schedule_ids, max(0, int(delay_seconds))),
        name="data-sync-interrupted-recovery",
        daemon=True,
    )
    _interrupted_recovery_thread.start()


def _finish_interrupted_schedule_recovery() -> None:
    global _interrupted_recovery_thread
    with _INTERRUPTED_RECOVERY_LOCK:
        _interrupted_recovery_thread = None
        has_pending = bool(_INTERRUPTED_SCHEDULE_RECOVERY_IDS)
    if has_pending and not _scheduler_stop.is_set():
        start_interrupted_schedule_recovery(delay_seconds=0)


def _delayed_interrupted_schedule_recovery(schedule_ids: list[str], delay_seconds: int) -> None:
    try:
        if delay_seconds:
            _scheduler_stop.wait(timeout=delay_seconds)
            if _scheduler_stop.is_set():
                _queue_interrupted_schedule_recovery(schedule_ids)
                return
        _recover_interrupted_schedules(schedule_ids)
    finally:
        _finish_interrupted_schedule_recovery()


def _load_recoverable_interrupted_schedule(schedule_id: str) -> dict[str, Any] | None:
    if not is_database_configured():
        return None
    with session_scope() as session:
        row = session.execute(
            select(schema.sync_batch_schedules).where(
                schema.sync_batch_schedules.c.id == schedule_id,
                schema.sync_batch_schedules.c.enabled == True,  # noqa: E712
                schema.sync_batch_schedules.c.last_status == "failed",
                schema.sync_batch_schedules.c.last_message == INTERRUPTED_SCHEDULE_MESSAGE,
            )
        ).mappings().first()
    return dict(row) if row else None


def _latest_sync_batch_running() -> bool:
    with _BATCH_LOCK:
        if not _LATEST_BATCH_ID:
            return False
        latest = _SYNC_BATCHES.get(_LATEST_BATCH_ID)
        return bool(latest and latest.get("status") == "running")


def _recover_interrupted_schedules(schedule_ids: Sequence[str]) -> None:
    """Retry schedules that were interrupted by the immediately previous process."""
    deadline = time.monotonic() + INTERRUPTED_SCHEDULE_RECOVERY_WAIT_SECONDS
    unique_schedule_ids = list(dict.fromkeys(str(item) for item in schedule_ids if item))
    for index, schedule_id in enumerate(unique_schedule_ids):
        while True:
            if _scheduler_stop.is_set():
                _queue_interrupted_schedule_recovery(unique_schedule_ids[index:])
                return
            row = _load_recoverable_interrupted_schedule(schedule_id)
            if row is None:
                break
            if _latest_sync_batch_running():
                if time.monotonic() >= deadline:
                    logger.warning("Interrupted schedule recovery %s timed out waiting for active batch", schedule_id)
                    break
                time.sleep(INTERRUPTED_SCHEDULE_RECOVERY_POLL_SECONDS)
                continue
            try:
                _run_schedule_action(row)
                break
            except Exception as exc:
                logger.warning("Interrupted schedule recovery %s failed: %s", schedule_id, exc)
                break


def _scheduler_loop() -> None:
    """Main scheduler loop — wakes up every 60 seconds."""
    while not _scheduler_stop.is_set():
        try:
            _run_scheduled_jobs()
        except Exception as exc:
            logger.error("Scheduler tick error: %s", exc)
        _scheduler_stop.wait(timeout=60)


def _now_china() -> datetime:
    """Current time in China timezone (cron schedules are China-local)."""
    return datetime.now(timezone(timedelta(hours=8)))


def _load_batch_schedules() -> list[dict[str, Any]]:
    """Return enabled batch schedules for the scheduler to consider."""
    if not is_database_configured():
        return []
    with session_scope() as session:
        rows = session.execute(
            select(schema.sync_batch_schedules).where(schema.sync_batch_schedules.c.enabled == True)  # noqa: E712
        ).mappings().all()
    return [dict(row) for row in rows]


def _recently_started(row: dict[str, Any], within_seconds: int = 1800) -> bool:
    """True if the schedule's last batch started within the throttle window."""
    last_started = row.get("last_started_at")
    if last_started is None:
        return False
    if hasattr(last_started, "tzinfo") and last_started.tzinfo is None:
        last_started = last_started.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last_started).total_seconds() < within_seconds


def _run_scheduled_jobs() -> None:
    """Trigger batch schedules whose cron matches the current China time."""
    now_china = _now_china()
    for row in _load_batch_schedules():
        cron = row.get("cron")
        if not cron:
            continue
        if _recently_started(row):
            continue
        try:
            if _cron_matches(cron, now_china):
                _run_schedule_action(row)
        except Exception:
            pass


def _run_schedule_action(row: dict[str, Any], *, raise_errors: bool = False) -> dict[str, Any] | None:
    schedule_id = str(row["id"])
    action = str(row.get("action") or "sync")
    try:
        if action == "quant_research":
            _touch_schedule(schedule_id, last_started_at=datetime.now(timezone.utc), last_status="running")
            research_run = research_jobs.start_research_run(persist=True, auto_portfolio=True, force_refresh=False)
            _touch_schedule(
                schedule_id,
                last_status="succeeded",
                last_finished_at=datetime.now(timezone.utc),
                last_message="尾盘量化任务已启动",
            )
            return research_run
        _start_sync_schedule(row, source="schedule")
        return None
    except Exception as exc:
        _touch_schedule(
            schedule_id,
            last_status="failed",
            last_finished_at=datetime.now(timezone.utc),
            last_message=str(exc)[:500],
        )
        logger.warning("Scheduled action %s failed: %s", schedule_id, exc)
        if raise_errors:
            raise
        return None


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

    # Cron day-of-week uses 0/7 for Sunday and 1-6 for Monday-Saturday.
    # Python datetime.weekday() uses 0 for Monday, so translate explicitly.
    cron_dow = (now.weekday() + 1) % 7

    return (
        _field_matches(minute_pat, now.minute)
        and _field_matches(hour_pat, now.hour)
        and _field_matches(dom_pat, now.day)
        and _field_matches(month_pat, now.month)
        and _field_matches(dow_pat, cron_dow)
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


def _next_day(date_value: Any) -> str | None:
    """Return ISO date of the day after ``date_value`` (str/date), or None."""
    try:
        d = date.fromisoformat(str(date_value)[:10])
    except Exception:
        return None
    return (d + timedelta(days=1)).isoformat()


def _last_bar_dates_daily(vt_symbols: list[str]) -> dict[str, str]:
    """Return {vt_symbol: max trade_date} for daily bars that already exist."""
    if not vt_symbols:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                func.max(schema.stock_daily_bars.c.trade_date),
            )
            .where(schema.stock_daily_bars.c.vt_symbol.in_(vt_symbols))
            .group_by(schema.stock_daily_bars.c.vt_symbol)
        ).all()
    return {str(r[0]): str(r[1]) for r in rows if r[1] is not None}


def _last_bar_dates_minute(vt_symbols: list[str], interval: str) -> dict[str, str]:
    """Return {vt_symbol: max trade_date} for minute bars that already exist."""
    if not vt_symbols:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_minute_bars.c.vt_symbol,
                func.max(schema.stock_minute_bars.c.trade_date),
            )
            .where(
                (schema.stock_minute_bars.c.interval == interval)
                & schema.stock_minute_bars.c.vt_symbol.in_(vt_symbols)
            )
            .group_by(schema.stock_minute_bars.c.vt_symbol)
        ).all()
    return {str(r[0]): str(r[1]) for r in rows if r[1] is not None}


def _select_daily_bar_stocks(symbols: list[str], stock_limit: int) -> list[dict[str, Any]]:
    """Return stock rows to sync daily bars for, ordered by liquidity."""
    with session_scope() as session:
        query = select(schema.stocks).order_by(desc(schema.stocks.c.turnover), desc(schema.stocks.c.market_cap))
        if symbols:
            query = query.where(schema.stocks.c.vt_symbol.in_(symbols))
        if stock_limit > 0:
            query = query.limit(stock_limit)
        return [dict(row) for row in session.execute(query).mappings().all()]


def _select_minute_bar_stocks(
    symbols: list[str],
    stock_limit: int,
    interval: str,
    only_missing: bool,
    start_date: date | None,
    end_date: date | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Return stock rows to sync minute bars for (recent mode)."""
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
        return [dict(row) for row in session.execute(query).mappings().all()]


def _fill_change_pct_from_close(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 close 序列补算 change_pct（%）。

    tencent/eastmoney K 线源只返回 OHLCV 没有涨跌幅，导致 stock_daily_bars.change_pct
    全空。这里按交易日期排序，change_pct = (close / prev_close - 1) * 100；
    已有 change_pct 的保留。返回值同时按日期升序排序。
    """
    sorted_items = sorted(items, key=lambda x: x.get("trade_date") or "")
    prev_close: float | None = None
    for item in sorted_items:
        close = item.get("close")
        if close is None:
            prev_close = None
            continue
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            prev_close = None
            continue
        if item.get("change_pct") is None and prev_close and prev_close > 0:
            item["change_pct"] = round((close_f / prev_close - 1) * 100, 4)
        prev_close = close_f
    return sorted_items


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
    written = 0
    with session_scope() as session:
        for item in items:
            name = str(item.get("name") or "")
            code = str(item.get("code") or name)
            sector_id = str(item.get("id") or item.get("akshare_symbol") or code)
            if not sector_id:
                continue
            trade_date = str(item.get("trade_date") or date.today().isoformat())
            if name:
                _ensure_sector_row(session, sector_id, name, sector_type, item)
            values = {
                "sector_id": sector_id,
                "trade_date": trade_date,
                "period": period,
                "main_net_inflow": item.get("main_net_inflow"),
                "main_net_inflow_ratio": item.get("main_net_inflow_pct"),
                "rank": item.get("rank"),
                "source": str(item.get("source") or "akshare"),
                "raw": item.get("raw") or {},
            }
            existing = session.execute(
                select(schema.sector_fund_flows).where(
                    (schema.sector_fund_flows.c.sector_id == sector_id)
                    & (schema.sector_fund_flows.c.trade_date == trade_date)
                    & (schema.sector_fund_flows.c.period == period)
                )
            ).first()
            if existing:
                session.execute(
                    schema.sector_fund_flows.update()
                    .where(
                        (schema.sector_fund_flows.c.sector_id == sector_id)
                        & (schema.sector_fund_flows.c.trade_date == trade_date)
                        & (schema.sector_fund_flows.c.period == period)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.sector_fund_flows.insert().values(**values))
            written += 1
    return written


def _ensure_sector_row(session, sector_id: str, name: str, sector_type: str, item: dict[str, Any]) -> None:
    values = {
        "id": sector_id,
        "name": name,
        "type": sector_type,
        "category": item.get("category"),
        "path": item.get("path") or [],
        "change_pct": item.get("change_pct"),
        "source": str(item.get("source") or "akshare"),
        "raw": item.get("raw") or {},
    }
    existing = session.execute(select(schema.sectors).where(schema.sectors.c.id == sector_id)).first()
    if existing:
        session.execute(schema.sectors.update().where(schema.sectors.c.id == sector_id).values(**values))
    else:
        session.execute(schema.sectors.insert().values(**values))


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


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
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
