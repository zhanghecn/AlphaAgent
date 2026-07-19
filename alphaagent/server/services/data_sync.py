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
import re
import threading
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Literal, Sequence
from uuid import uuid4

from sqlalchemy import and_, desc, func, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from alphaagent.data_sources.akshare_adapter import (
    SECTOR_DAILY_DEFAULT_HISTORY_SESSIONS,
    SECTOR_DAILY_MAX_HISTORY_SESSIONS,
    AkShareAdapter,
)
from alphaagent.market.cache import market_cache
from alphaagent.market.symbols import INDEX_SYMBOLS, normalize_exchange, vt_symbol
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope
from alphaagent.server.services import market_snapshot_repository
from alphaagent.server.services import research_sector_scores
from alphaagent.server.services.completed_session import completed_daily_bar_cutoff
from alphaagent.server.services.low_suction import (
    baostock_security_source,
    forward_leader_identity,
    forward_membership,
    forward_membership_repository,
    forward_security_repository,
)
from alphaagent.server.services.limit_up.data_quality import (
    backfill_limit_up_event_minutes,
    backfill_limit_up_exit_minutes,
    backfill_limit_up_radar_minutes,
)
from alphaagent.server.services.limit_up.domain import is_eligible_main_board
from alphaagent.server.services.limit_up.concept_live_service import (
    CONCEPT_REFRESH_SECONDS,
    refresh_live_concept_snapshot,
)
from alphaagent.server.services.limit_up.historical_evidence_import import import_ths_evidence
from alphaagent.server.services.limit_up.live_service import (
    LIVE_SCAN_INTERVAL_SECONDS,
    refresh_live_snapshot,
)
from alphaagent.server.services.limit_up.live_trace_repository import (
    prune_live_trace_snapshots,
)
from alphaagent.server.services.limit_up.next_session_plan import refresh_next_session_plan

logger = logging.getLogger(__name__)
INTERRUPTED_SYNC_JOB_MESSAGE = "API process restarted before this sync job finished."
INTERRUPTED_SCHEDULE_MESSAGE = "API process restarted before this schedule finished."
INTERRUPTED_SCHEDULE_RECOVERY_DELAY_SECONDS = 30
INTERRUPTED_SCHEDULE_RECOVERY_WAIT_SECONDS = 6 * 60 * 60
INTERRUPTED_SCHEDULE_RECOVERY_POLL_SECONDS = 5
SCHEDULER_TICK_SECONDS = 5
# 单只股/板块同步的超时上限：AkShare 正常请求数秒，超时则跳过该 item（防 hang 拖死整批）
SYNC_PER_ITEM_TIMEOUT_SECONDS = 60.0
# 东方财富三张财报各自需要分页读取；单股使用独立预算，避免通用 60 秒在有效响应完成前取消。
FINANCIAL_SYNC_PER_ITEM_TIMEOUT_SECONDS = 180.0
FINANCIAL_SYNC_MAX_STOCK_CONCURRENCY = 3
FINANCIAL_SYNC_RETRY_DELAY = timedelta(days=1)
# 内存批次 running 超过此时长视为僵尸，看门狗清理（防卡死批次挡住新调度）
ZOMBIE_BATCH_THRESHOLD_SECONDS = 2 * 60 * 60
CANONICAL_SECTOR_DAILY_SOURCE = "eastmoney.board_kline"
LIMIT_POOL_EVENT_SOURCE = "akshare.stock_ztb_em"
STOCK_LIST_MAX_PAGES = 200
SECTOR_MEMBER_MAX_PAGES = 100
STOCK_DAILY_INCREMENTAL_REFRESH_DAYS = 5
STOCK_DAILY_COMPLETE_COVERAGE_RATIO = 0.95
MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3000
STOCK_DAILY_HISTORY_TARGET_DAYS = 750
STOCK_DAILY_HISTORY_BOOTSTRAP_LIMIT = 800
STOCK_DAILY_HISTORY_MIN_UNIVERSE = MIN_COMPLETE_DAILY_SYMBOL_COUNT
SECTOR_DAILY_MIN_COVERAGE_TOTAL = 100
SECTOR_DAILY_MIN_COVERAGE_RATIO = 0.8

_INTERRUPTED_RECOVERY_LOCK = threading.Lock()
_INTERRUPTED_SCHEDULE_RECOVERY_IDS: set[str] = set()
_interrupted_recovery_thread: threading.Thread | None = None


def _load_financial_quarterly_bundle(
    adapter: Any,
    symbol: str,
    exchange: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load independent financial statements concurrently for one stock."""

    with ThreadPoolExecutor(max_workers=3) as pool:
        quarterly_future = pool.submit(
            adapter.stock_financial_quarterly,
            symbol,
            exchange=exchange,
        )
        balance_future = pool.submit(
            adapter.stock_balance_sheet,
            symbol,
            exchange=exchange,
        )
        cash_flow_future = pool.submit(
            adapter.stock_cash_flow_sheet,
            symbol,
            exchange=exchange,
        )
        quarterly = quarterly_future.result()
        balance_items = _optional_financial_items(balance_future, symbol, "balance")
        cash_flow_items = _optional_financial_items(cash_flow_future, symbol, "cash_flow")

    return (
        quarterly if isinstance(quarterly, dict) else {},
        balance_items,
        cash_flow_items,
    )


def _optional_financial_items(future: Any, symbol: str, dataset: str) -> list[dict[str, Any]]:
    try:
        payload = future.result()
    except Exception as exc:
        logger.debug("financial %s enrichment failed for %s: %s", dataset, symbol, exc)
        return []
    if not isinstance(payload, dict):
        return []
    return [item for item in (payload.get("items") or []) if isinstance(item, dict)]


def _bounded_parallel_map(
    fn: Callable[[Any], None],
    items: Sequence[Any],
    *,
    concurrency: int,
    per_item_timeout: float,
    on_timeout: Callable[[Any], None] | None = None,
) -> None:
    """并发执行 ``fn(item)``，单 item 超时 ``per_item_timeout`` 秒后跳过，不阻塞整批。

    替代无超时的 ``ThreadPoolExecutor.map``——后者在某 item 的底层请求 hang 住
    （如 AkShare 对某只股不返回）时会永久阻塞，拖死整批同步并卡住后续调度。

    超时项对应的底层线程仍在运行（Python 无法强制中止线程），但主流程不再
    等它：超时项经 ``on_timeout`` 回调上报，其余 item 正常推进。业务异常由
    ``fn`` 自身的 try-except 处理，这里不重复抛出。
    """

    if not items:
        return
    queue = deque(items)
    active: dict[Any, Any] = {}
    submitted_at: dict[Any, float] = {}

    def submit_available(pool: ThreadPoolExecutor) -> None:
        while queue and len(active) < max(1, concurrency):
            item = queue.popleft()
            future = pool.submit(fn, item)
            active[future] = item
            submitted_at[future] = time.monotonic()

    pool = ThreadPoolExecutor(max_workers=max(1, concurrency))
    try:
        submit_available(pool)
        while active:
            done_set, _ = wait(set(active), timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done_set:
                active.pop(future, None)
                submitted_at.pop(future, None)
                try:
                    future.result()
                except Exception:
                    pass  # 业务异常由 fn 内部 try-except 处理
            now = time.monotonic()
            stale = [future for future in active if now - submitted_at[future] >= per_item_timeout]
            for future in stale:
                item = active.pop(future, None)
                submitted_at.pop(future, None)
                if on_timeout is not None:
                    try:
                        on_timeout(item)
                    except Exception:
                        logger.warning("on_timeout callback failed", exc_info=True)
            submit_available(pool)
    finally:
        # wait=False：超时未完成的 worker 在后台继续跑完（Python 无法强杀线程），
        # 但主流程立即返回、不阻塞整批。cancel_futures 取消尚未开始的排队任务。
        pool.shutdown(wait=False, cancel_futures=True)


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
    "tdx_public_hq": {
        "id": "tdx_public_hq",
        "name": "通达信公开行情",
        "kind": "tdx",
        "base_url": "",
        "enabled": True,
        "priority": 120,
    },
    "baostock": {
        "id": "baostock",
        "name": "BaoStock 免费证券状态",
        "kind": "baostock",
        "base_url": "",
        "enabled": True,
        "priority": 110,
    },
    "alphaagent_local": {
        "id": "alphaagent_local",
        "name": "AlphaAgent 本地点时研究",
        "kind": "local",
        "base_url": "",
        "enabled": True,
        "priority": 130,
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
        description="同步系统数据源的最近分钟线；历史事件缺口由覆盖审计和夜间任务自动补偿。",
        source_id="akshare",
        target_table="stock_minute_bars",
        default_params={"mode": "recent", "stock_limit": 100, "limit": 240, "interval": "1m", "only_missing": True},
    ),
    JobDefinition(
        id="sync_limit_up_event_minutes",
        name="涨停事件分钟路径补数",
        description="按持久化退避账本限量补齐涨停事件股票的09:15-15:00历史1分钟路径。",
        source_id="tdx_public_hq",
        target_table="stock_minute_bars",
        default_params={"max_gaps": 200, "dry_run": False},
    ),
    JobDefinition(
        id="sync_limit_up_radar_minutes",
        name="3%雷达候选分钟路径补数",
        description="按独立退避作用域补齐当天实际观察候选的09:15-15:00完整1分钟路径。",
        source_id="tdx_public_hq",
        target_table="stock_minute_bars",
        default_params={"max_gaps": 300, "dry_run": False},
    ),
    JobDefinition(
        id="sync_limit_up_exit_minutes",
        name="候选D+1 14:30分钟补数",
        description="从历史候选池和正式实时推荐派生卖出日，限量补齐精确14:30历史1分钟价格。",
        source_id="tdx_public_hq",
        target_table="stock_minute_bars",
        default_params={"max_gaps": 200, "dry_run": False},
    ),
    JobDefinition(
        id="sync_stock_auction_snapshots",
        name="集合竞价快照",
        description="在09:25集合竞价结束后保存主板非ST股票的价格、撮合量额和字段完整度。",
        source_id="akshare",
        target_table="stock_auction_snapshots",
        default_params={"page_size": 200},
    ),
    JobDefinition(
        id="sync_stock_sector_memberships",
        name="股票-板块反向索引",
        description="重建每只股票所属板块的反向索引。",
        source_id="akshare",
        target_table="stock_sector_memberships",
        default_params={},
    ),
    JobDefinition(
        id="sync_low_suction_security_snapshot",
        name="低吸研究证券状态快照",
        description="盘后保存完整沪深主板 ST、停牌和上市退市状态前向证据。",
        source_id="baostock",
        target_table="low_suction_security_snapshots",
        default_params={},
    ),
    JobDefinition(
        id="sync_low_suction_forward_top3",
        name="低吸研究前向 Top3 冻结",
        description="按同源日严格成员、证券状态、概念主升和日线冻结三套无收益龙头身份。",
        source_id="alphaagent_local",
        target_table="low_suction_forward_leader_rank_snapshots",
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
        default_params={
            "limit": SECTOR_DAILY_DEFAULT_HISTORY_SESSIONS,
            "sector_limit": 0,
        },
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
    "sync_limit_up_event_minutes": JobCadence(CADENCE_EOD_DAILY, CATEGORY_MARKET_BARS, 1, "limit_up_minute_backfill_attempts", "last_attempt_at"),
    "sync_limit_up_radar_minutes": JobCadence(CADENCE_EOD_DAILY, CATEGORY_MARKET_BARS, 1, "limit_up_minute_backfill_attempts", "last_attempt_at"),
    "sync_limit_up_exit_minutes": JobCadence(CADENCE_EOD_DAILY, CATEGORY_MARKET_BARS, 1, "limit_up_minute_backfill_attempts", "last_attempt_at"),
    "sync_stock_auction_snapshots": JobCadence(CADENCE_INTRADAY, CATEGORY_MARKET_REALTIME, 1, "stock_auction_snapshots", "captured_at"),
    "sync_stock_financial_quarterly": JobCadence(CADENCE_QUARTERLY, CATEGORY_FINANCIALS, 45, "stock_financial_reports", "updated_at"),
    "sync_stock_financial_indicators": JobCadence(CADENCE_QUARTERLY, CATEGORY_FINANCIALS, 45, "stock_financial_reports", "updated_at"),
    "sync_stock_business_segments_history": JobCadence(CADENCE_QUARTERLY, CATEGORY_FINANCIALS, 45, "stock_business_segments", "updated_at"),
    "sync_stock_lhb_records": JobCadence(CADENCE_LHB, CATEGORY_EVENTS, 1, "stock_lhb_records", "trade_date"),
    "sync_stock_notices": JobCadence(CADENCE_EOD_DAILY, CATEGORY_EVENTS, 2, "stock_events", "updated_at"),
    "sync_sector_period_scores": JobCadence(CADENCE_EOD_DAILY, CATEGORY_SECTOR_RESEARCH, 1, "sector_period_scores", "updated_at"),
    "sync_sector_list": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 7, "sectors", "updated_at"),
    "sync_sector_members": JobCadence(CADENCE_IRREGULAR, CATEGORY_MARKET_BASIC, 7, "sector_memberships", "updated_at"),
    "sync_stock_sector_memberships": JobCadence(CADENCE_EOD_DAILY, CATEGORY_MARKET_BASIC, 1, "stock_sector_memberships", "updated_at"),
    "sync_low_suction_security_snapshot": JobCadence(CADENCE_EOD_DAILY, CATEGORY_MARKET_BASIC, 1, "low_suction_security_snapshot_scopes", "updated_at"),
    "sync_low_suction_forward_top3": JobCadence(CADENCE_EOD_DAILY, CATEGORY_SECTOR_RESEARCH, 1, "low_suction_forward_leader_rank_snapshot_scopes", "updated_at"),
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
    "sync_low_suction_security_snapshot",
    "sync_low_suction_forward_top3",
    "sync_shenwan_industry_members", "sync_industry_board_mapping",
    "sync_supply_chain_edges",
    "sync_stock_daily_bars", "sync_index_daily_bars", "sync_sector_daily_bars",
    "sync_stock_minute_bars",
    "sync_limit_up_event_minutes",
    "sync_limit_up_radar_minutes",
    "sync_stock_auction_snapshots",
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
CURRENT_EOD_SCHEDULE_ID = "eod_1900"
LEGACY_DEFAULT_BATCH_SCHEDULE_IDS = {"eod_18h", "tail_quant_1430"}
LEGACY_SCHEDULE_ACTIONS = {"quant_research", "tail_preview"}

DEFAULT_BATCH_SCHEDULES: list[dict[str, Any]] = [
    {
        "id": "auction_0926",
        "name": "集合竞价快照（09:26）",
        "cron": "26 9 * * 1-5",
        "action": "sync",
        "enabled": True,
        "concurrency": 1,
        "job_ids": ["sync_stock_auction_snapshots"],
    },
    {
        "id": "limit_up_live_scan",
        "name": "实时打板扫描（每15秒）",
        "cron": "* 9-14 * * 1-5",
        "action": "limit_up_live_scan",
        "enabled": True,
        "concurrency": 1,
        "job_ids": [],
    },
    {
        "id": "limit_up_concept_scan",
        "name": "实时概念共振（每30秒）",
        "cron": "* 9-14 * * 1-5",
        "action": "limit_up_concept_scan",
        "enabled": True,
        "concurrency": 1,
        "job_ids": [],
    },
    {
        "id": "intraday_hourly",
        "name": "盘中低频同步（每小时）",
        "cron": "30 9,10,11,13,14 * * 1-5",
        "action": "sync",
        "enabled": True,
        "concurrency": 4,
        "job_ids": [
            "sync_sector_fund_flows",
            "sync_stock_fund_flows",
            "sync_stock_hot_ranks",
        ],
    },
    {
        "id": "limit_up_plan_1505",
        "name": "次交易时段初步观察（15:05）",
        "cron": "5 15 * * 1-5",
        "action": "sync",
        "enabled": True,
        "concurrency": 1,
        "job_ids": ["limit_up_next_session_plan_preliminary"],
    },
    {
        "id": CURRENT_EOD_SCHEDULE_ID,
        "name": "盘后统一更新（19:00）",
        "cron": "0 19 * * 1-5",
        "action": "sync",
        "enabled": True,
        "concurrency": 8,
        "job_ids": [
            "sync_stock_list",
            "sync_sector_fund_flows",
            "sync_stock_fund_flows",
            "sync_stock_daily_bars",
            "sync_index_daily_bars",
            "sync_sector_list",
            "sync_sector_daily_bars",
            "sync_sector_period_scores",
            "sync_sector_members",
            "sync_stock_sector_memberships",
            "sync_low_suction_security_snapshot",
            "sync_low_suction_forward_top3",
            "sync_limit_up_pools",
            "sync_limit_up_radar_minutes",
            "sync_stock_lhb_records",
            "sync_stock_notices",
            "sync_stock_financial_quarterly",
            "sync_stock_financial_indicators",
            "sync_stock_business_segments_history",
            "limit_up_next_session_plan_final",
            "limit_up_live_trace_prune",
        ],
    },
    {
        "id": "eod_finalize_2130",
        "name": "晚间补偿重试（21:30）",
        "cron": "30 21 * * 1-5",
        "action": "sync",
        "enabled": True,
        "concurrency": 8,
        "job_ids": [
            "sync_stock_daily_bars",
            "sync_index_daily_bars",
            "sync_sector_fund_flows",
            "sync_stock_fund_flows",
            "sync_sector_list",
            "sync_sector_daily_bars",
            "sync_sector_period_scores",
            "sync_sector_members",
            "sync_stock_sector_memberships",
            "sync_low_suction_security_snapshot",
            "sync_low_suction_forward_top3",
            "sync_limit_up_pools",
            "sync_limit_up_ths_evidence",
            "sync_limit_up_event_minutes",
            "sync_limit_up_radar_minutes",
            "limit_up_history_rebuild",
            "limit_up_next_session_plan_final",
            "limit_up_live_trace_prune",
        ],
    },
]

LIMIT_UP_THS_EVIDENCE_BATCH_JOB_ID = "sync_limit_up_ths_evidence"
LIMIT_UP_HISTORY_REBUILD_BATCH_JOB_ID = "limit_up_history_rebuild"
LIMIT_UP_NEXT_SESSION_PLAN_PRELIMINARY_BATCH_JOB_ID = "limit_up_next_session_plan_preliminary"
LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID = "limit_up_next_session_plan_final"
LIMIT_UP_LIVE_TRACE_PRUNE_BATCH_JOB_ID = "limit_up_live_trace_prune"
INTERNAL_BATCH_JOB_IDS = {
    LIMIT_UP_THS_EVIDENCE_BATCH_JOB_ID,
    LIMIT_UP_HISTORY_REBUILD_BATCH_JOB_ID,
    LIMIT_UP_NEXT_SESSION_PLAN_PRELIMINARY_BATCH_JOB_ID,
    LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID,
    LIMIT_UP_LIVE_TRACE_PRUNE_BATCH_JOB_ID,
}
STALE_BATCH_SUMMARY_RE = re.compile(r"^\s*(\d+)\s+成功\s*/\s*(\d+)\s+失败\s*$")


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
            if page > STOCK_LIST_MAX_PAGES:
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
        counters = {"read": 0, "written": 0, "done": 0, "failed": 0}
        failed_sector_ids: list[str] = []
        failed_sector_id_set: set[str] = set()
        complete_members_by_sector: dict[str, tuple[dict[str, Any], ...]] = {}

        def _record_failure(sector_id: str) -> tuple[int, int, int]:
            with lock:
                if sector_id not in failed_sector_id_set:
                    failed_sector_id_set.add(sector_id)
                    counters["failed"] += 1
                    counters["done"] += 1
                    if len(failed_sector_ids) < 20:
                        failed_sector_ids.append(sector_id)
                return counters["done"], counters["read"], counters["written"]

        def _do_one(sector_row: dict[str, Any]) -> None:
            sector_id = str(sector_row["id"])
            sector_name = str(sector_row.get("name") or sector_id)
            label = f"{sector_name} {sector_id}"
            try:
                capture = _fetch_sector_stock_capture(
                    self.adapter,
                    sector_id,
                    page_size,
                )
                items = list(capture.items)
                if not items:
                    raise DataSyncError("板块成员响应为空")
                with lock:
                    if sector_id in failed_sector_id_set:
                        return
                    written = _upsert_sector_memberships(sector_id, items)
                    if capture.pagination_complete:
                        complete_members_by_sector[sector_id] = capture.items
                    counters["read"] += len(items)
                    counters["written"] += written
                    counters["done"] += 1
                    cur_done = counters["done"]
                    cur_read = counters["read"]
                    cur_written = counters["written"]
            except Exception as exc:
                logger.warning("sector_stocks(%s) failed: %s", sector_id, exc)
                cur_done, cur_read, cur_written = _record_failure(sector_id)
                self._report_progress(
                    "读取板块成分股",
                    current=cur_done,
                    total=total_sectors,
                    current_label=f"{label} 失败：{exc.__class__.__name__}",
                    rows_read=cur_read,
                    rows_written=cur_written,
                )
                return
            self._report_progress(
                "写入板块成分股",
                current=cur_done,
                total=total_sectors,
                current_label=f"{label}，{len(items)} 只",
                rows_read=cur_read,
                rows_written=cur_written,
                sample_items=items,
            )

        _bounded_parallel_map(
            _do_one,
            sector_rows,
            concurrency=self.concurrency,
            per_item_timeout=SYNC_PER_ITEM_TIMEOUT_SECONDS,
            on_timeout=lambda row: _record_failure(str(row["id"])),
        )

        _save_low_suction_forward_membership_capture(
            sector_rows=sector_rows,
            members_by_sector=complete_members_by_sector,
            failed_sector_ids=tuple(sorted(failed_sector_id_set)),
            observed_at=_now_china(),
        )

        excluded_sector_ids = sorted(failed_sector_id_set)
        removed_rows = _delete_sector_memberships(excluded_sector_ids)
        if counters["read"] == 0:
            failed = ", ".join(failed_sector_ids)
            suffix = " ..." if counters["failed"] > len(failed_sector_ids) else ""
            raise DataSyncError(
                f"没有可用板块成员：failed={counters['failed']}; "
                f"sectors={failed}{suffix}"
            )

        message = ""
        if excluded_sector_ids:
            message = (
                f"成员不可用板块已剔除 {len(excluded_sector_ids)} 个："
                + ", ".join(excluded_sector_ids[:20])
                + (" ..." if len(excluded_sector_ids) > 20 else "")
            )
        return {
            "rows_read": counters["read"],
            "rows_written": counters["written"],
            "excluded_sector_count": len(excluded_sector_ids),
            "excluded_sector_ids": excluded_sector_ids,
            "removed_stale_membership_rows": removed_rows,
            "message": message,
        }

    def _run_sync_stock_daily_bars(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = int(params.get("limit", 250))
        stock_limit = int(params.get("stock_limit", 0) or 0)
        refresh_days = max(int(params.get("refresh_days", STOCK_DAILY_INCREMENTAL_REFRESH_DAYS) or 0), 0)
        symbols = _param_list(params.get("symbols"))
        stock_rows = _select_daily_bar_stocks(symbols, stock_limit)
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks in DB; run sync_stock_list first."}

        incremental = _truthy(params.get("incremental", True))
        vt_symbols = [vt_symbol(str(r["symbol"]), str(r["exchange"])) for r in stock_rows]
        history_bootstrap = _stock_daily_history_bootstrap_plan(
            symbols=symbols,
            stock_limit=stock_limit,
            total_stocks=len(stock_rows),
            incremental=incremental,
        )
        if history_bootstrap["required"]:
            incremental = False
            limit = max(limit, int(history_bootstrap["request_limit"]))
        last_dates = _last_bar_dates_daily(vt_symbols) if incremental else {}

        total_stocks = len(stock_rows)
        self._report_progress("同步股票日 K 线", current=0, total=total_stocks)

        lock = threading.Lock()
        counters = {"read": 0, "written": 0, "done": 0, "timed_out": 0}
        timed_out_symbols: set[str] = set()

        def _do_one(stock_row: dict[str, Any]) -> None:
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            start_date = _incremental_daily_start_date(last_dates.get(current_vts), refresh_days) if incremental else None
            try:
                data = self.adapter.stock_bars(symbol, exchange, limit=limit, interval="1d", start_date=start_date)
            except Exception as exc:
                with lock:
                    if current_vts in timed_out_symbols:
                        return
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
            with lock:
                if current_vts in timed_out_symbols:
                    return
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

        def _on_timeout(stock_row: dict[str, Any]) -> None:
            current_vts = vt_symbol(str(stock_row["symbol"]), str(stock_row["exchange"]))
            stock_name = str(stock_row.get("name") or stock_row["symbol"])
            with lock:
                timed_out_symbols.add(current_vts)
                counters["timed_out"] += 1
                counters["done"] += 1
                cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
            self._report_progress(
                "读取股票日 K 线",
                current=cur_done,
                total=total_stocks,
                current_label=f"{current_vts} {stock_name} 超时跳过",
                rows_read=cur_read,
                rows_written=cur_written,
            )

        _bounded_parallel_map(
            _do_one,
            stock_rows,
            concurrency=self.concurrency,
            per_item_timeout=SYNC_PER_ITEM_TIMEOUT_SECONDS,
            on_timeout=_on_timeout,
        )

        coverage_cleanup = None
        if _should_cleanup_partial_daily_sync(symbols, stock_limit, total_stocks):
            coverage_cleanup = _discard_incomplete_latest_daily_bars(total_stocks)

        logger.info("sync_stock_daily_bars: processed %d stocks", counters["done"])
        result = {"rows_read": counters["read"], "rows_written": counters["written"]}
        if history_bootstrap["required"]:
            reliable_days_after = _reliable_stock_daily_trade_days()
            result["history_bootstrap"] = {
                "performed": True,
                "reliable_trade_days_before": history_bootstrap[
                    "reliable_trade_days_before"
                ],
                "reliable_trade_days_after": reliable_days_after,
                "target_trade_days": history_bootstrap["target_trade_days"],
                "request_limit": limit,
                "target_achieved": (
                    reliable_days_after >= history_bootstrap["target_trade_days"]
                ),
            }
        if counters["timed_out"]:
            result["timed_out"] = counters["timed_out"]
        if coverage_cleanup is not None:
            result["coverage_cleanup"] = coverage_cleanup
        return result

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
        counters = {"read": 0, "written": 0, "done": 0, "timed_out": 0}
        timed_out_symbols: set[str] = set()

        def _do_one(stock_row: dict[str, Any]) -> None:
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            stock_start = _minute_incremental_start_date(last_dates.get(current_vts)) if last_dates.get(current_vts) else start_date
            adapter_start = _minute_adapter_start_date(stock_start, end_date)
            try:
                data = self.adapter.stock_bars(symbol, exchange, limit=limit, interval=interval, start_date=adapter_start, end_date=end_date)
            except Exception as exc:
                with lock:
                    if current_vts in timed_out_symbols:
                        return
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
            with lock:
                if current_vts in timed_out_symbols:
                    return
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

        def _on_timeout(stock_row: dict[str, Any]) -> None:
            current_vts = vt_symbol(str(stock_row["symbol"]), str(stock_row["exchange"]))
            stock_name = str(stock_row.get("name") or stock_row["symbol"])
            with lock:
                timed_out_symbols.add(current_vts)
                counters["timed_out"] += 1
                counters["done"] += 1
                cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
            self._report_progress(
                "读取股票分钟 K 线",
                current=cur_done,
                total=total_stocks,
                current_label=f"{current_vts} {stock_name} 超时跳过",
                rows_read=cur_read,
                rows_written=cur_written,
            )

        _bounded_parallel_map(
            _do_one,
            stock_rows,
            concurrency=self.concurrency,
            per_item_timeout=SYNC_PER_ITEM_TIMEOUT_SECONDS,
            on_timeout=_on_timeout,
        )

        logger.info("sync_stock_minute_bars: processed %d stocks", counters["done"])
        return {
            "mode": "recent",
            "provider": "akshare",
            "interval": interval,
            "rows_read": counters["read"],
            "rows_written": counters["written"],
            "timed_out": counters["timed_out"],
        }

    def _run_sync_limit_up_event_minutes(self, params: dict[str, Any]) -> dict[str, Any]:
        result = backfill_limit_up_event_minutes(
            max_gaps=int(params.get("max_gaps") or 200),
            dry_run=_truthy(params.get("dry_run")),
        )
        backfill_status = str(result.get("status") or "unknown")
        requested = int(result.get("requested_gap_count") or 0)
        covered = int(result.get("covered_gap_count") or 0)
        message = str(result.get("message") or "").strip()
        if requested:
            message = f"涨停事件分钟补数：覆盖 {covered} / {requested}，写入 {int(result.get('rows_written') or 0)} 根"
        if backfill_status in {"error", "unavailable", "unsupported_interval"}:
            raise DataSyncError(message or f"涨停事件分钟补数失败：{backfill_status}")
        return {
            **{key: value for key, value in result.items() if key != "status"},
            "backfill_status": backfill_status,
            "message": message,
        }

    def _run_sync_limit_up_radar_minutes(self, params: dict[str, Any]) -> dict[str, Any]:
        result = backfill_limit_up_radar_minutes(
            max_gaps=int(params.get("max_gaps") or 300),
            dry_run=_truthy(params.get("dry_run")),
        )
        backfill_status = str(result.get("status") or "unknown")
        requested = int(result.get("requested_gap_count") or 0)
        covered = int(result.get("covered_gap_count") or 0)
        message = str(result.get("message") or "").strip()
        if requested:
            message = (
                f"3%雷达候选分钟补数：覆盖 {covered} / {requested}，"
                f"写入 {int(result.get('rows_written') or 0)} 根"
            )
        if backfill_status in {
            "error",
            "partial",
            "unavailable",
            "unsupported_interval",
        }:
            raise DataSyncError(
                message or f"3%雷达候选分钟补数失败：{backfill_status}"
            )
        return {
            **{key: value for key, value in result.items() if key != "status"},
            "backfill_status": backfill_status,
            "message": message,
        }

    def _run_sync_limit_up_exit_minutes(self, params: dict[str, Any]) -> dict[str, Any]:
        result = backfill_limit_up_exit_minutes(
            max_gaps=int(params.get("max_gaps") or 200),
            dry_run=_truthy(params.get("dry_run")),
        )
        backfill_status = str(result.get("status") or "unknown")
        requested = int(result.get("requested_gap_count") or 0)
        covered = int(result.get("covered_gap_count") or 0)
        message = str(result.get("message") or "").strip()
        if requested:
            message = (
                f"候选D+1 14:30分钟补数：覆盖 {covered} / {requested}，"
                f"写入 {int(result.get('rows_written') or 0)} 根"
            )
        if backfill_status in {"error", "unavailable", "unsupported_interval"}:
            raise DataSyncError(message or f"候选D+1 14:30分钟补数失败：{backfill_status}")
        return {
            **{key: value for key, value in result.items() if key != "status"},
            "backfill_status": backfill_status,
            "message": message,
        }

    def _run_sync_stock_auction_snapshots(self, params: dict[str, Any]) -> dict[str, Any]:
        captured_at = _now_china()
        if not _auction_capture_window_open(captured_at):
            return {
                "rows_read": 0,
                "rows_written": 0,
                "message": "集合竞价快照仅允许在交易日09:25-09:29采集",
            }

        probe = self.adapter.stock_detail("600000", "SSE")
        market_time = _auction_market_datetime(probe.get("trade_time"))
        if market_time is None:
            raise DataSyncError("集合竞价行情缺少可验证的源时间")
        if market_time.date() != captured_at.date():
            raise DataSyncError(
                f"集合竞价行情日期不是当天：source={market_time.date()} capture={captured_at.date()}"
            )
        if not _auction_source_time_ready(market_time):
            raise DataSyncError(f"集合竞价行情尚未完成：source={market_time.time().isoformat()}")

        page_size = min(max(int(params.get("page_size") or 200), 1), 200)
        all_items: list[dict[str, Any]] = []
        total: int | None = None
        for page in range(1, STOCK_LIST_MAX_PAGES + 1):
            data = self.adapter.list_stocks(page=page, page_size=page_size, sort="mktcap")
            items = [dict(item) for item in (data.get("items") or []) if isinstance(item, dict)]
            total = int(data["total"]) if data.get("total") is not None else total
            if not items:
                break
            all_items.extend(items)
            if total is not None and len(all_items) >= total:
                break
            if total is None and len(items) < page_size:
                break
        if total is not None and len(all_items) < total:
            raise DataSyncError(
                f"集合竞价全市场行情不完整：read={len(all_items)} total={total}"
            )
        unique_items = {
            str(item.get("vt_symbol") or "").strip().upper(): item
            for item in all_items
            if item.get("vt_symbol")
        }
        if total is not None and len(unique_items) < total:
            raise DataSyncError(
                f"集合竞价全市场行情去重后不完整：unique={len(unique_items)} total={total}"
            )
        all_items = list(unique_items.values())

        eligible = [
            item
            for item in all_items
            if is_eligible_main_board(
                str(item.get("vt_symbol") or ""),
                str(item.get("name") or ""),
            )
        ]
        rows_written = market_snapshot_repository.save_stock_auction_snapshots(
            eligible,
            trade_date=captured_at.date(),
            captured_at=captured_at,
        )
        return {
            "rows_read": len(all_items),
            "rows_written": rows_written,
            "eligible_rows": len(eligible),
            "excluded_rows": len(all_items) - len(eligible),
            "source_market_time": market_time.isoformat(),
            "message": f"集合竞价主板快照 {rows_written} 条；公共源未提供未匹配量时严格门禁保持关闭",
        }

    def _run_sync_stock_sector_memberships(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        captured_at = _now_china()
        reliable_date = _latest_complete_daily_date_for_research()
        if reliable_date != captured_at.date():
            return {
                "status": "skipped",
                "rows_read": 0,
                "rows_written": 0,
                "snapshot_rows_written": 0,
                "message": (
                    "当前日期不是最新可靠完整交易日，跳过板块成员快照："
                    f"capture_date={captured_at.date().isoformat()} "
                    f"reliable_date={reliable_date.isoformat() if reliable_date else '-'}"
                ),
            }
        rows_written = _rebuild_stock_sector_memberships()
        snapshot_rows_written = 0
        if rows_written > 0:
            snapshot_rows_written = (
                market_snapshot_repository.save_current_stock_sector_membership_snapshot(
                    snapshot_date=captured_at.date(),
                    captured_at=captured_at,
                )
            )
        return {
            "rows_read": rows_written,
            "rows_written": rows_written,
            "snapshot_rows_written": snapshot_rows_written,
            "message": f"反向索引 {rows_written} 条；逐日成员快照 {snapshot_rows_written} 条",
        }

    def _run_sync_low_suction_security_snapshot(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        del params
        observed_at = _now_china()
        reliable_date = _latest_complete_daily_date_for_research()
        if reliable_date != observed_at.date():
            return {
                "status": "skipped",
                "rows_read": 0,
                "rows_written": 0,
                "message": (
                    "当前日期不是最新可靠完整交易日，跳过低吸证券状态快照："
                    f"capture_date={observed_at.date().isoformat()} "
                    f"reliable_date={reliable_date.isoformat() if reliable_date else '-'}"
                ),
            }

        snapshot = baostock_security_source.fetch_forward_security_snapshot(
            source_trade_date=reliable_date,
            observed_at=observed_at,
        )
        rows_written = (
            forward_security_repository.replace_forward_security_snapshot(snapshot)
        )
        return {
            "rows_read": snapshot.returned_symbol_count,
            "rows_written": rows_written,
            "expected_rows": snapshot.expected_symbol_count,
            "risk_warning_rows": snapshot.risk_warning_count,
            "suspended_rows": snapshot.suspended_count,
            "message": (
                f"低吸证券状态快照 {rows_written} 条；"
                f"ST/退市整理 {snapshot.risk_warning_count} 条；"
                f"停牌 {snapshot.suspended_count} 条"
            ),
        }

    def _run_sync_low_suction_forward_top3(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        del params
        observed_at = _now_china()
        reliable_date = _latest_complete_daily_date_for_research()
        if reliable_date != observed_at.date():
            return {
                "status": "skipped",
                "rows_read": 0,
                "rows_written": 0,
                "message": (
                    "当前日期不是最新可靠完整交易日，跳过低吸前向 Top3："
                    f"capture_date={observed_at.date().isoformat()} "
                    f"reliable_date={reliable_date.isoformat() if reliable_date else '-'}"
                ),
            }

        result = forward_leader_identity.freeze_forward_leader_source(
            reliable_date,
            attempted_at=observed_at,
        )
        complete = bool(result.get("complete"))
        rank_rows = int(result.get("rank_rows") or 0)
        rows_written = int(result.get("rows_written") or 0)
        top3_rows = int(result.get("top3_rows") or 0)
        blockers = [
            str(value)
            for value in (result.get("blocking_reasons") or [])
            if str(value)
        ]
        message = (
            f"低吸前向 Top3 {result.get('save_status')}；"
            f"排名 {rank_rows} 行；Top3 {top3_rows} 行；"
            f"指纹 {result.get('input_fingerprint')}"
        )
        if blockers:
            message += "；关闭原因 " + ", ".join(blockers)
        return {
            **({} if complete else {"status": "skipped"}),
            "rows_read": rank_rows,
            "rows_written": rows_written,
            "top3_rows": top3_rows,
            "input_fingerprint": result.get("input_fingerprint"),
            "message": message,
        }

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
        limit = min(
            max(
                int(
                    params.get(
                        "limit",
                        SECTOR_DAILY_DEFAULT_HISTORY_SESSIONS,
                    )
                ),
                1,
            ),
            SECTOR_DAILY_MAX_HISTORY_SESSIONS,
        )
        sector_limit = int(params.get("sector_limit", 0))
        requested_sector_types = params.get("sector_types")
        sector_types: set[str] | None = None
        if requested_sector_types is not None:
            if isinstance(requested_sector_types, str):
                requested_sector_types = [requested_sector_types]
            sector_types = {
                str(value).strip().lower()
                for value in requested_sector_types
                if str(value).strip()
            }
            allowed_sector_types = {"concept", "industry", "theme"}
            invalid_sector_types = sorted(sector_types - allowed_sector_types)
            if not sector_types or invalid_sector_types:
                invalid = ", ".join(invalid_sector_types) or "empty"
                raise DataSyncError(f"invalid sector_types: {invalid}")
        allow_fallback_source = _truthy(params.get("allow_fallback_source", False))
        min_coverage_ratio = float(params.get("min_coverage_ratio", SECTOR_DAILY_MIN_COVERAGE_RATIO))
        market_cache.clear()
        with session_scope() as session:
            sector_rows = session.execute(select(schema.sectors)).mappings().all()
        if not sector_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No sectors in DB; run sync_sector_list first."}
        if sector_types is not None:
            sector_rows = [
                row
                for row in sector_rows
                if str(row.get("type") or "").strip().lower() in sector_types
            ]
            if not sector_rows:
                raise DataSyncError(
                    "no sectors matched sector_types: "
                    + ", ".join(sorted(sector_types))
                )
        if sector_limit > 0:
            sector_rows = sector_rows[:sector_limit]
        total_sectors = len(sector_rows)
        self._report_progress("同步板块历史 K 线", current=0, total=total_sectors)

        lock = threading.Lock()
        counters = {"read": 0, "written": 0, "done": 0, "failed": 0, "empty": 0, "covered": 0, "fallback": 0}

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
            source = str(data.get("source") or "akshare")
            if source != CANONICAL_SECTOR_DAILY_SOURCE and not allow_fallback_source:
                logger.warning("sector_daily_bars(%s) returned non-canonical source: %s", sector_id, source)
                with lock:
                    counters["done"] += 1
                    counters["failed"] += 1
                    counters["fallback"] += 1
                    cur_done, cur_read, cur_written = counters["done"], counters["read"], counters["written"]
                self._report_progress(
                    "读取板块历史 K 线",
                    current=cur_done,
                    total=total_sectors,
                    current_label=f"{label} 非规范来源：{source}",
                    rows_read=cur_read,
                    rows_written=cur_written,
                )
                return
            written = _upsert_sector_daily_bars(sector_id, items, source)
            with lock:
                counters["read"] += len(items)
                counters["written"] += written
                counters["done"] += 1
                if not items:
                    counters["empty"] += 1
                else:
                    counters["covered"] += 1
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

        _bounded_parallel_map(
            _do_one,
            sector_rows,
            concurrency=self.concurrency,
            per_item_timeout=SYNC_PER_ITEM_TIMEOUT_SECONDS,
        )

        if counters["read"] == 0:
            raise DataSyncError(
                "sync_sector_daily_bars read 0 rows "
                f"from {total_sectors} sectors (failed={counters['failed']}, empty={counters['empty']})"
            )
        min_covered = int(total_sectors * min_coverage_ratio)
        if total_sectors >= SECTOR_DAILY_MIN_COVERAGE_TOTAL and counters["covered"] < min_covered:
            raise DataSyncError(
                "sync_sector_daily_bars coverage too low "
                f"covered={counters['covered']}/{total_sectors}, "
                f"failed={counters['failed']}, empty={counters['empty']}, fallback={counters['fallback']}"
            )
        return {
            "rows_read": counters["read"],
            "rows_written": counters["written"],
            "message": (
                f"limit={limit}, covered={counters['covered']}, failed={counters['failed']}, "
                f"empty={counters['empty']}, fallback={counters['fallback']}"
            ),
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
                captured_at = _parse_aware_datetime(data.get("updated_at")) or datetime.now(timezone.utc)
                written = _upsert_sector_fund_flows(
                    items,
                    period,
                    sector_type,
                    captured_at=captured_at,
                )
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
        symbols = _param_list(params.get("symbols"))
        if symbols:
            stock_rows = _financial_sync_stock_rows(
                stock_limit,
                only_missing,
                symbols=symbols,
            )
        else:
            stock_rows = _financial_sync_stock_rows(stock_limit, only_missing)
        if not stock_rows:
            return {"rows_read": 0, "rows_written": 0, "message": "No stocks in DB."}
        total_stocks = len(stock_rows)
        self._report_progress("同步个股季度财报", current=0, total=total_stocks)

        lock = threading.Lock()
        counters = {"read": 0, "written": 0, "done": 0, "timed_out": 0}
        timed_out_symbols: set[str] = set()

        def _do_one(stock_row: dict[str, Any]) -> None:
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            label = f"{current_vts} {stock_name}"
            with lock:
                current = counters["done"]
                rows_read = counters["read"]
                rows_written = counters["written"]
            self._report_progress(
                "读取个股季度财报",
                current=current,
                total=total_stocks,
                current_label=label,
                rows_read=rows_read,
                rows_written=rows_written,
            )

            try:
                quarterly, balance_items, cash_flow_items = _load_financial_quarterly_bundle(
                    self.adapter,
                    symbol,
                    exchange,
                )
                items = [
                    item
                    for item in (quarterly.get("items") or [])
                    if isinstance(item, dict)
                ]
                with lock:
                    if current_vts in timed_out_symbols:
                        return
                self._enrich_quarterly_with_roe(items, balance_items)
                self._enrich_quarterly_with_cash_flow(items, cash_flow_items)
                with lock:
                    if current_vts in timed_out_symbols:
                        return
                    written = _upsert_stock_financial_reports(
                        symbol,
                        exchange,
                        items,
                        "quarterly",
                    )
                    counters["read"] += len(items)
                    counters["written"] += written
                    counters["done"] += 1
                    current = counters["done"]
                    rows_read = counters["read"]
                    rows_written = counters["written"]
            except Exception as exc:
                with lock:
                    if current_vts in timed_out_symbols:
                        return
                    counters["done"] += 1
                    current = counters["done"]
                    rows_read = counters["read"]
                    rows_written = counters["written"]
                _record_financial_sync_attempt(
                    current_vts,
                    "failed",
                    error=exc.__class__.__name__,
                    next_retry_at=_financial_retry_at(),
                )
                logger.debug("stock_financial_quarterly(%s) failed: %s", symbol, exc)
                self._report_progress(
                    "读取个股季度财报",
                    current=current,
                    total=total_stocks,
                    current_label=label,
                    rows_read=rows_read,
                    rows_written=rows_written,
                    message=f"{current_vts} 失败：{exc.__class__.__name__}",
                )
                return

            attempt_status = "succeeded" if items else "empty"
            _record_financial_sync_attempt(
                current_vts,
                attempt_status,
                error=None if items else "provider returned no quarterly reports",
                next_retry_at=None if items else _financial_retry_at(),
            )

            sample_items = [{**item, "vt_symbol": current_vts, "name": stock_name} for item in items[-3:]]
            self._report_progress(
                "写入个股季度财报",
                current=current,
                total=total_stocks,
                current_label=f"{label}，{len(items)} 期",
                rows_read=rows_read,
                rows_written=rows_written,
                sample_items=sample_items,
            )

        def _on_timeout(stock_row: dict[str, Any]) -> None:
            symbol = str(stock_row["symbol"])
            exchange = str(stock_row["exchange"])
            stock_name = str(stock_row.get("name") or symbol)
            current_vts = vt_symbol(symbol, exchange)
            with lock:
                if current_vts in timed_out_symbols:
                    return
                timed_out_symbols.add(current_vts)
                counters["timed_out"] += 1
                counters["done"] += 1
                current = counters["done"]
                rows_read = counters["read"]
                rows_written = counters["written"]
            _record_financial_sync_attempt(
                current_vts,
                "timed_out",
                error="financial item timeout",
                next_retry_at=_financial_retry_at(),
            )
            self._report_progress(
                "读取个股季度财报",
                current=current,
                total=total_stocks,
                current_label=f"{current_vts} {stock_name} 超时跳过",
                rows_read=rows_read,
                rows_written=rows_written,
            )

        _bounded_parallel_map(
            _do_one,
            stock_rows,
            concurrency=min(self.concurrency, FINANCIAL_SYNC_MAX_STOCK_CONCURRENCY),
            per_item_timeout=FINANCIAL_SYNC_PER_ITEM_TIMEOUT_SECONDS,
            on_timeout=_on_timeout,
        )

        return {
            "rows_read": counters["read"],
            "rows_written": counters["written"],
            "timed_out": counters["timed_out"],
        }

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
        balance_items: list[dict[str, Any]],
    ) -> None:
        """Enrich quarterly items with computed ROE, margins, and EPS.

        ROE requires equity from the balance sheet.
        Gross margin = (revenue - cost) / revenue * 100.
        Net margin = net_profit / revenue * 100.
        EPS is extracted from BASIC_EPS in raw data.
        """
        if not items:
            return

        equity_map: dict[str, float] = {}
        for balance_item in balance_items:
            report_date_raw = balance_item.get("REPORT_DATE")
            if not report_date_raw:
                continue
            report_date = str(report_date_raw)[:10]
            equity = self._to_float(balance_item.get("TOTAL_PARENT_EQUITY"))
            if equity:
                equity_map[report_date] = equity

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
        cash_flow_items: list[dict[str, Any]],
    ) -> None:
        """Enrich quarterly items with operating cash flow and disclosure date."""
        if not items:
            return

        cash_flow_map: dict[str, dict[str, Any]] = {}
        for record in cash_flow_items:
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
        stock_rows = _financial_sync_stock_rows(
            stock_limit,
            only_missing,
            rotate_attempts=False,
        )
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
    "sync_limit_up_event_minutes": "_run_sync_limit_up_event_minutes",
    "sync_limit_up_radar_minutes": "_run_sync_limit_up_radar_minutes",
    "sync_limit_up_exit_minutes": "_run_sync_limit_up_exit_minutes",
    "sync_stock_auction_snapshots": "_run_sync_stock_auction_snapshots",
    "sync_stock_sector_memberships": "_run_sync_stock_sector_memberships",
    "sync_low_suction_security_snapshot": "_run_sync_low_suction_security_snapshot",
    "sync_low_suction_forward_top3": "_run_sync_low_suction_forward_top3",
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


# ─── Schema bootstrap ────────────────────────────────────────────────────

def ensure_sync_schema() -> None:
    """Create sync tables if they are missing."""
    if not is_database_configured():
        return
    schema.ensure_schema_once(get_engine())
    seed_default_registry()
    mark_interrupted_runs()


def _stale_batch_summary_status_reset(existing_sched: Any, current_job_count: int) -> dict[str, Any]:
    mapping = (
        existing_sched
        if isinstance(existing_sched, dict)
        else getattr(existing_sched, "_mapping", None)
    )
    if not mapping or mapping.get("last_status") != "partial":
        return {}

    match = STALE_BATCH_SUMMARY_RE.match(str(mapping.get("last_message") or ""))
    if not match:
        return {}

    previous_job_count = int(match.group(1)) + int(match.group(2))
    if previous_job_count == current_job_count:
        return {}

    return {
        "last_status": None,
        "last_started_at": None,
        "last_finished_at": None,
        "last_message": None,
    }


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
                    sched_values.update(
                        _stale_batch_summary_status_reset(existing_sched, len(sched["job_ids"]))
                    )
                    session.execute(
                        schema.sync_batch_schedules.update()
                        .where(schema.sync_batch_schedules.c.id == sched["id"])
                        .values(**sched_values)
                    )
            default_schedule_ids = [str(sched["id"]) for sched in DEFAULT_BATCH_SCHEDULES]
            if LEGACY_DEFAULT_BATCH_SCHEDULE_IDS:
                session.execute(
                    schema.sync_batch_schedules.delete().where(
                        schema.sync_batch_schedules.c.id.in_(LEGACY_DEFAULT_BATCH_SCHEDULE_IDS)
                    )
                )
            session.execute(
                schema.sync_batch_schedules.delete().where(
                    schema.sync_batch_schedules.c.action.in_(LEGACY_SCHEDULE_ACTIONS)
                )
            )
            session.execute(
                schema.sync_batch_schedules.delete().where(
                    and_(
                        schema.sync_batch_schedules.c.id.not_in(default_schedule_ids),
                        schema.sync_batch_schedules.c.enabled == False,  # noqa: E712
                        schema.sync_batch_schedules.c.last_status == "disabled",
                    )
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


def _select_zombie_batch_ids(
    batches: list[dict[str, Any]],
    now: datetime,
    threshold_seconds: float,
) -> list[str]:
    """从批次列表挑出僵尸：status=running 且 started_at 早于 ``now - threshold``。

    started_at 兼容 ISO 字符串与 datetime；None / 非 running 跳过。纯函数，
    便于单测；DB/内存交互由 ``reap_zombie_batches`` 负责。
    """
    cutoff = now - timedelta(seconds=threshold_seconds)
    ids: list[str] = []
    for batch in batches:
        if batch.get("status") != "running":
            continue
        started = batch.get("started_at")
        if started is None:
            continue
        if isinstance(started, str):
            try:
                started = datetime.fromisoformat(started.replace("Z", "+00:00"))
            except ValueError:
                continue
        if started < cutoff:
            ids.append(str(batch.get("id")))
    return ids


def reap_zombie_batches(
    now: datetime | None = None,
    threshold_seconds: float = ZOMBIE_BATCH_THRESHOLD_SECONDS,
) -> list[str]:
    """看门狗：清理内存 ``_SYNC_BATCHES`` 里 running 超过阈值的僵尸批次。

    线上根因：内存批次 ``status='running'`` 永不结束 → ``start_sync_batch`` 检测
    到上次还在 running 就拒绝新批次 → 后续调度全部被挡。重启能清（内存重置），
    但不重启时由本函数自愈。顺带清理 DB 里残留的 running run。
    """
    if not is_database_configured():
        return []
    now = now or datetime.now(timezone.utc)
    with _BATCH_LOCK:
        batches = list(_SYNC_BATCHES.values())
    zombie_ids = _select_zombie_batch_ids(batches, now, threshold_seconds)
    if not zombie_ids:
        return []
    with _BATCH_LOCK:
        for batch_id in zombie_ids:
            batch = _SYNC_BATCHES.get(batch_id)
            if batch is None:
                continue
            batch["status"] = "failed"
            batch["finished_at"] = _utc_now_iso()
            batch["message"] = f"Reaped by zombie watchdog (running > {int(threshold_seconds)}s)"
    logger.warning("reap_zombie_batches: cleaned %d zombie batches: %s", len(zombie_ids), zombie_ids)
    try:
        with session_scope() as session:
            session.execute(
                schema.sync_job_runs.update()
                .where(schema.sync_job_runs.c.status == "running")
                .values(
                    status="failed",
                    message="Reaped by zombie watchdog",
                    error_type="Zombie",
                    finished_at=datetime.now(timezone.utc),
                )
            )
    except Exception as exc:
        logger.warning("reap_zombie_batches: DB cleanup failed: %s", exc)
    return zombie_ids


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
    allow_limit_up_ths_evidence: bool = False,
    allow_limit_up_history_rebuild: bool = False,
    allow_limit_up_next_session_plan: bool = False,
    allow_limit_up_live_trace_prune: bool = False,
) -> None:
    valid = {job.id for job in DEFAULT_JOBS}
    unknown = [
        j for j in job_ids
        if j not in valid
        and not (
            allow_limit_up_ths_evidence
            and j == LIMIT_UP_THS_EVIDENCE_BATCH_JOB_ID
        )
        and not (
            allow_limit_up_history_rebuild
            and j == LIMIT_UP_HISTORY_REBUILD_BATCH_JOB_ID
        )
        and not (
            allow_limit_up_next_session_plan
            and j in {
                LIMIT_UP_NEXT_SESSION_PLAN_PRELIMINARY_BATCH_JOB_ID,
                LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID,
            }
        )
        and not (
            allow_limit_up_live_trace_prune
            and j == LIMIT_UP_LIVE_TRACE_PRUNE_BATCH_JOB_ID
        )
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
    if action != "sync":
        return
    if not job_ids:
        raise DataSyncError(f"{action} schedules require at least one job_id")
    _assert_known_jobs(
        job_ids,
        allow_limit_up_ths_evidence=True,
        allow_limit_up_history_rebuild=True,
        allow_limit_up_next_session_plan=True,
        allow_limit_up_live_trace_prune=True,
    )


def _schedule_action(payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or "sync").strip()
    if action not in {
        "sync",
        "limit_up_live_scan",
        "limit_up_concept_scan",
    }:
        raise DataSyncError(f"Unsupported schedule action: {action}")
    return action


def create_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise DataSyncError("name is required")
    cron = str(payload.get("cron") or "").strip()
    action = _schedule_action(payload)
    job_ids = _schedule_job_ids(payload.get("job_ids") or [])
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
        if "action" in updates or "job_ids" in updates:
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
    if action == "limit_up_live_scan":
        snapshot = _run_schedule_action(dict(row), raise_errors=True) or {}
        return _live_scan_schedule_status(schedule_id, snapshot)
    if action == "limit_up_concept_scan":
        snapshot = _run_schedule_action(dict(row), raise_errors=True) or {}
        return _concept_scan_schedule_status(schedule_id, snapshot)
    return _start_sync_schedule(dict(row), source="manual")


def _live_scan_schedule_status(schedule_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Represent one synchronous live scan as a batch-like response."""

    saved = _live_scan_snapshot_saved(snapshot)
    status = "succeeded" if saved else "skipped"
    rows_read = len(snapshot.get("candidates") or [])
    rows_written = 1 if saved else 0
    created_at = _utc_now_iso()
    finished_at = created_at
    message = _live_scan_status_message(snapshot, saved=saved)
    return {
        "id": f"live_scan_{uuid4().hex}",
        "profile": "limit_up_live_scan",
        "source": "manual",
        "schedule_id": schedule_id,
        "concurrency": 1,
        "status": status,
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": finished_at,
        "current_job_id": None,
        "total_jobs": 1,
        "completed_jobs": 1,
        "succeeded_jobs": 1 if saved else 0,
        "failed_jobs": 0,
        "skipped_jobs": 0 if saved else 1,
        "rows_read": rows_read,
        "rows_written": rows_written,
        "progress_pct": 100.0,
        "message": message,
        "jobs": [
            {
                "job_id": "limit_up_live_scan",
                "status": status,
                "started_at": created_at,
                "finished_at": finished_at,
                "rows_read": rows_read,
                "rows_written": rows_written,
                "progress_current": 1,
                "progress_total": 1,
                "progress_pct": 100.0,
                "stage": str(snapshot.get("session_stage") or ""),
                "current_label": "",
                "sample_items": [],
                "message": message,
            }
        ],
    }


def _concept_scan_schedule_status(
    schedule_id: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    quality = snapshot.get("data_quality")
    quality = quality if isinstance(quality, dict) else {}
    succeeded = quality.get("status") == "ready"
    concept_count = int(snapshot.get("concept_count") or 0)
    created_at = _utc_now_iso()
    status = "succeeded" if succeeded else "skipped"
    message = (
        f"已更新 {concept_count} 个实时概念强度"
        if succeeded
        else f"概念行情不可用于新买点：{quality.get('status') or 'unavailable'}"
    )
    return {
        "id": f"concept_scan_{uuid4().hex}",
        "profile": "limit_up_concept_scan",
        "source": "manual",
        "schedule_id": schedule_id,
        "concurrency": 1,
        "status": status,
        "created_at": created_at,
        "started_at": created_at,
        "finished_at": created_at,
        "current_job_id": None,
        "total_jobs": 1,
        "completed_jobs": 1,
        "succeeded_jobs": 1 if succeeded else 0,
        "failed_jobs": 0,
        "skipped_jobs": 0 if succeeded else 1,
        "rows_read": int(quality.get("quote_count") or 0),
        "rows_written": concept_count if succeeded else 0,
        "progress_pct": 100.0,
        "message": message,
        "jobs": [
            {
                "job_id": "limit_up_concept_scan",
                "status": status,
                "started_at": created_at,
                "finished_at": created_at,
                "rows_read": int(quality.get("quote_count") or 0),
                "rows_written": concept_count if succeeded else 0,
                "message": message,
            }
        ],
    }


def _start_sync_schedule(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    job_ids = _schedule_job_ids(row.get("job_ids"))
    action = str(row.get("action") or "sync")
    _assert_schedule_jobs(action, job_ids)
    params = _schedule_batch_params(row, action, job_ids)
    return start_sync_batch(
        job_ids=job_ids,
        params=params,
        concurrency=int(row.get("concurrency") or 8),
        source=source,
        schedule_id=str(row["id"]),
    )


def _schedule_batch_params(row: dict[str, Any], action: str, job_ids: list[str]) -> dict[str, Any]:
    """Return explicit per-job parameters for a scheduled batch."""

    if (
        action == "sync"
        and str(row.get("id") or "")
        in {CURRENT_EOD_SCHEDULE_ID, "eod_finalize_2130"}
        and "sync_sector_daily_bars" in job_ids
    ):
        return {
            "jobs": {
                "sync_sector_daily_bars": {
                    "limit": 30,
                    "sector_types": ["concept", "theme"],
                }
            }
        }
    return {}


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

    # 启动新批次前先清僵尸——避免上次卡死的 running 批次挡住本次调度
    reap_zombie_batches()

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
_BASE_SYNC_JOBS = {"sync_stock_list", "sync_sector_list", "sync_sector_members"}


def _depends_on(job_id: str, upstream: str) -> bool:
    """Whether ``job_id`` depends on a failed base ``upstream`` job.

    Used only to skip downstream jobs when a base job fails: per-stock jobs
    depend on the stock list, sector jobs on the sector list.
    """
    if upstream == "sync_stock_list":
        return (
            job_id.startswith("sync_stock_") and job_id not in _BASE_SYNC_JOBS
        ) or job_id == "sync_low_suction_forward_top3"
    if upstream == "sync_sector_list":
        return (
            job_id.startswith("sync_sector_")
            or job_id
            in {
                "sync_stock_sector_memberships",
                "sync_low_suction_forward_top3",
            }
        )
    if upstream == "sync_sector_members":
        return job_id in {
            "sync_stock_sector_memberships",
            "sync_low_suction_forward_top3",
        }
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

    history_inputs_changed = False
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
            if job_id == LIMIT_UP_THS_EVIDENCE_BATCH_JOB_ID:
                result = _run_limit_up_ths_evidence_batch_job(
                    _batch_job_params(job_id, params),
                    progress=_batch_progress_callback(batch_id, job_id),
                )
            elif job_id == LIMIT_UP_HISTORY_REBUILD_BATCH_JOB_ID:
                result = _run_limit_up_history_rebuild_batch_job(
                    force=history_inputs_changed
                )
            elif job_id == LIMIT_UP_NEXT_SESSION_PLAN_PRELIMINARY_BATCH_JOB_ID:
                result = _run_limit_up_next_session_plan_batch_job("preliminary")
            elif job_id == LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID:
                result = _run_limit_up_next_session_plan_batch_job("final")
            elif job_id == LIMIT_UP_LIVE_TRACE_PRUNE_BATCH_JOB_ID:
                result = _run_limit_up_live_trace_prune_batch_job()
            else:
                result = run_job(job_id, _batch_job_params(job_id, params), progress=_batch_progress_callback(batch_id, job_id))
            rows_read = int(result.get("rows_read") or 0)
            rows_written = int(result.get("rows_written") or 0)
            history_inputs_changed = history_inputs_changed or (
                _changes_limit_up_history_inputs(job_id, result)
            )
            skipped = str(result.get("status") or "") == "skipped"
            _update_batch_job(
                batch_id,
                job_id,
                {
                    "status": "skipped" if skipped else "succeeded",
                    "finished_at": _utc_now_iso(),
                    "rows_read": rows_read,
                    "rows_written": rows_written,
                    "progress_pct": 100,
                    "stage": "跳过" if skipped else "完成",
                    "current_label": "",
                    "message": str(result.get("message") or ""),
                    "run_id": result.get("run_id") or result.get("id"),
                },
            )
            _increment_batch(
                batch_id,
                completed=1,
                skipped=1 if skipped else 0,
                succeeded=0 if skipped else 1,
                rows_read=rows_read,
                rows_written=rows_written,
            )
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


def _changes_limit_up_history_inputs(
    job_id: str,
    result: dict[str, Any],
) -> bool:
    if int(result.get("rows_written") or 0) <= 0:
        return False
    if job_id in {
        LIMIT_UP_THS_EVIDENCE_BATCH_JOB_ID,
        "sync_limit_up_event_minutes",
        "sync_limit_up_exit_minutes",
    }:
        return True
    if job_id != "sync_stock_daily_bars":
        return False
    bootstrap = result.get("history_bootstrap")
    return isinstance(bootstrap, dict) and bootstrap.get("performed") is True


def _run_limit_up_next_session_plan_batch_job(
    phase: Literal["preliminary", "final"],
) -> dict[str, Any]:
    snapshot = refresh_next_session_plan(phase)
    recommendations = snapshot.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, dict) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, dict) else {}
    observations = lanes.get("next_auction")
    observations = observations if isinstance(observations, list) else []
    quality = snapshot.get("data_quality")
    quality = quality if isinstance(quality, dict) else {}
    status = str(snapshot.get("status") or quality.get("status") or "empty")
    return {
        "rows_read": len(observations),
        "rows_written": len(observations),
        "status": "skipped" if status == "empty" else status,
        "message": f"次交易时段{phase}观察计划：{len(observations)} 个候选",
    }


def _run_limit_up_live_trace_prune_batch_job() -> dict[str, Any]:
    deleted = prune_live_trace_snapshots()
    return {
        "rows_read": deleted,
        "rows_written": deleted,
        "status": "succeeded",
        "message": f"实时打板诊断缓存保留最近2个交易日，清理 {deleted} 行",
    }


def _run_limit_up_ths_evidence_batch_job(
    params: dict[str, Any],
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    result = import_ths_evidence(
        max_dates=int(params.get("max_dates") or 252),
        only_missing=_truthy(params.get("only_missing", True)),
        progress=progress,
    )
    status = str(result.get("status") or "unknown")
    if status in {"error", "rejected", "unavailable"}:
        raise DataSyncError(str(result.get("message") or f"同花顺历史证据补数失败：{status}"))
    return result


def _run_limit_up_history_rebuild_batch_job(
    *,
    force: bool = False,
) -> dict[str, Any]:
    from alphaagent.server.services.limit_up import history_service

    latest_reliable_date = _latest_complete_daily_date_for_research()
    result = history_service.refresh_history_if_needed(
        latest_reliable_date,
        force=force,
    )
    history_service.start_backtest_cache_warmup()
    if str(result.get("status") or "") == "skipped":
        return {
            **result,
            "rows_read": 0,
            "rows_written": 0,
            "message": (
                "打板历史账本已覆盖最新完整交易日，"
                f"无需重建：{result.get('persisted_end') or '-'}"
            ),
        }

    persisted_days = int(result.get("persisted_days") or 0)
    return {
        **result,
        "rows_read": persisted_days,
        "rows_written": persisted_days,
        "message": (
            "打板历史账本已刷新："
            f"{result.get('start') or '-'}..{result.get('end') or '-'}，"
            f"{persisted_days} 个交易日"
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

# 覆盖率/健康仪表盘走进程内 TTL 缓存：三端点（/data/status、/data-sync/coverage、
# /data-sync/health）共享同一份结果，60s 内的重复请求零 DB 成本。
_COVERAGE_CACHE_KEY = "data_sync.coverage"
_COVERAGE_TTL_SECONDS = 60.0
_HEALTH_CACHE_KEY = "data_sync.data_health"
_HEALTH_TTL_SECONDS = 60.0

# 行数超此阈值的大表用 pg_class.reltuples 估算（毫秒级），小表仍精确 COUNT。
_COVERAGE_ESTIMATE_MIN_ROWS = 100_000


def coverage(force_refresh: bool = False) -> dict[str, Any]:
    """Return per-table row counts and freshness."""
    if not is_database_configured():
        return {"status": "unavailable", "tables": {}, "message": "DATABASE_URL not configured"}
    if force_refresh:
        return market_cache.refresh(_COVERAGE_CACHE_KEY, _COVERAGE_TTL_SECONDS, _coverage_uncached)
    return market_cache.get_or_set(_COVERAGE_CACHE_KEY, _COVERAGE_TTL_SECONDS, _coverage_uncached)


def _coverage_uncached() -> dict[str, Any]:
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
        estimates = _table_row_estimates(session, table_names)
        for table_name in table_names:
            table_obj = getattr(schema, table_name, None)
            if table_obj is None:
                continue
            count = _coverage_table_count(session, table_obj, table_name, estimates)
            # MAX(updated_at) 代替 ORDER BY + LIMIT（免排序），大表有 updated_at 索引
            freshness = None
            try:
                latest = session.execute(select(func.max(table_obj.c.updated_at))).scalar()
                if latest is not None:
                    freshness = latest.isoformat() if hasattr(latest, "isoformat") else str(latest)
            except Exception:
                pass
            tables[table_name] = {"count": count, "last_updated": freshness}
            if table_name == "stock_daily_bars":
                tables[table_name].update(_stock_daily_bar_coverage(session))

    return {
        "status": "ready" if any(t["count"] > 0 for t in tables.values()) else "empty",
        "tables": tables,
    }


def _table_row_estimates(session, table_names: list[str]) -> dict[str, int]:
    """pg_class.reltuples 批量行数估算：一次查询覆盖所有表（毫秒级）。"""
    try:
        rows = session.execute(
            text("SELECT relname, GREATEST(reltuples, 0)::bigint AS estimate FROM pg_class WHERE relname = ANY(:names)"),
            {"names": list(table_names)},
        ).all()
        return {str(name): int(estimate) for name, estimate in rows}
    except Exception:
        return {}


def _coverage_table_count(session, table_obj, table_name: str, estimates: dict[str, int]) -> int:
    """大表用估算（展示语义足够），小表精确 COUNT。"""
    estimate = estimates.get(table_name)
    if estimate is not None and estimate > _COVERAGE_ESTIMATE_MIN_ROWS:
        return estimate
    try:
        return int(session.execute(select(func.count()).select_from(table_obj)).scalar() or 0)
    except Exception:
        return estimate or 0


def usage() -> dict[str, Any]:
    """Return capability usage report for the health / readiness endpoint."""
    return {
        "capabilities": _usage_capabilities(),
        "coverage": coverage(),
    }


def data_health(force_refresh: bool = False) -> dict[str, Any]:
    """数据健康仪表盘（60s TTL 缓存；force_refresh 由前端「刷新」按钮触发）。"""
    if not is_database_configured():
        return _data_health_uncached()
    if force_refresh:
        return market_cache.refresh(_HEALTH_CACHE_KEY, _HEALTH_TTL_SECONDS, _data_health_uncached)
    return market_cache.get_or_set(_HEALTH_CACHE_KEY, _HEALTH_TTL_SECONDS, _data_health_uncached)


def _data_health_uncached() -> dict[str, Any]:
    """合并覆盖率 + 最新交易日 + 任务节奏，算出每类数据的新鲜度与推荐同步清单。

    前端 `/data` 健康首页直消费。合并同表查询（每个 (table, col) 只探一次 MAX）。
    """
    now = _now_china()
    cov = coverage()
    tables_cov = cov.get("tables", {}) if isinstance(cov, dict) else {}
    stock_daily_cov = tables_cov.get("stock_daily_bars", {})

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
        if job.id == "sync_stock_daily_bars":
            override = _stock_daily_incomplete_health(tables_cov.get("stock_daily_bars", {}))
            if override is not None:
                severity, reason, is_stale = override
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
            "latest_daily_trade_date": stock_daily_cov.get("latest_trade_date"),
            "latest_complete_trade_date": stock_daily_cov.get("latest_complete_trade_date"),
            "latest_trade_date_symbol_count": stock_daily_cov.get("latest_trade_date_symbol_count"),
            "min_complete_daily_symbol_count": MIN_COMPLETE_DAILY_SYMBOL_COUNT,
            "reliable_history_start": stock_daily_cov.get("reliable_history_start"),
            "reliable_history_end": stock_daily_cov.get("reliable_history_end"),
            "reliable_history_trade_days": stock_daily_cov.get(
                "reliable_history_trade_days"
            ),
            "target_history_trade_days": stock_daily_cov.get(
                "target_history_trade_days",
                STOCK_DAILY_HISTORY_TARGET_DAYS,
            ),
            "history_depth_ready": stock_daily_cov.get("history_depth_ready", False),
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
    """用本地完整 stock_daily_bars 反推历史研究可用交易日。

    空库时返回 (None, "unknown")，调用方走 staleness 兜底，不阻塞。
    """
    if not is_database_configured():
        return None, "unknown"
    try:
        with session_scope() as session:
            value = _latest_complete_daily_date(session)
            if value is not None:
                return _as_date(value), "stock_daily_bars.complete"
            value = session.execute(select(func.max(schema.stock_daily_bars.c.trade_date))).scalar()
            if value is not None:
                return _as_date(value), "stock_daily_bars"
    except Exception as exc:  # noqa: BLE001 — 健康检查不能因查询失败而崩
        logger.warning("resolve latest trade date failed: %s", exc)
    return None, "unknown"


def _stock_daily_bar_coverage(session) -> dict[str, Any]:
    latest_trade_date = session.execute(select(func.max(schema.stock_daily_bars.c.trade_date))).scalar()
    latest_complete_trade_date = _latest_complete_daily_date(session)
    latest_count = _stock_daily_symbol_count(session, latest_trade_date)
    latest_complete_count = _stock_daily_symbol_count(session, latest_complete_trade_date)
    min_count = MIN_COMPLETE_DAILY_SYMBOL_COUNT
    history = _reliable_stock_daily_history_coverage(session)
    return {
        "latest_trade_date": _iso_or_none(latest_trade_date),
        "latest_trade_date_symbol_count": latest_count,
        "latest_trade_date_is_complete": bool(
            latest_trade_date
            and latest_trade_date == latest_complete_trade_date
            and latest_count >= min_count
        ),
        "latest_complete_trade_date": _iso_or_none(latest_complete_trade_date),
        "latest_complete_trade_date_symbol_count": latest_complete_count,
        "min_complete_daily_symbol_count": min_count,
        "reliable_history_trade_days": history["trade_days"],
        "reliable_history_start": history["start"],
        "reliable_history_end": history["end"],
        "target_history_trade_days": STOCK_DAILY_HISTORY_TARGET_DAYS,
        "history_depth_ready": (
            history["trade_days"] >= STOCK_DAILY_HISTORY_TARGET_DAYS
        ),
    }


def _stock_daily_symbol_count(session, trade_date: date | None) -> int:
    if trade_date is None:
        return 0
    # PK (vt_symbol, trade_date) 唯一：count(*) 等价 count(DISTINCT vt_symbol)
    return int(
        session.execute(
            select(func.count()).where(schema.stock_daily_bars.c.trade_date == trade_date)
        ).scalar()
        or 0
    )


def _stock_daily_incomplete_health(table_cov: dict[str, Any]) -> tuple[str, str, bool] | None:
    history_ready = table_cov.get("history_depth_ready")
    if history_ready is False:
        history_days = int(table_cov.get("reliable_history_trade_days") or 0)
        target_days = int(
            table_cov.get("target_history_trade_days")
            or STOCK_DAILY_HISTORY_TARGET_DAYS
        )
        return (
            "stale",
            f"可靠历史仅 {history_days}/{target_days} 个交易日，等待全市场日线自动回补",
            True,
        )
    latest_trade_date = table_cov.get("latest_trade_date")
    latest_count = int(table_cov.get("latest_trade_date_symbol_count") or 0)
    min_count = int(table_cov.get("min_complete_daily_symbol_count") or MIN_COMPLETE_DAILY_SYMBOL_COUNT)
    if not latest_trade_date or latest_count >= min_count:
        return None
    latest_complete = table_cov.get("latest_complete_trade_date")
    suffix = f"，最新完整日线为 {latest_complete}" if latest_complete else ""
    return "partial", f"{latest_trade_date} 日线仅覆盖 {latest_count}/{min_count} 只{suffix}", False


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


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _latest_complete_daily_date(session, min_symbol_count: int = MIN_COMPLETE_DAILY_SYMBOL_COUNT) -> date | None:
    completed_cutoff = completed_daily_bar_cutoff(_now_china())
    row = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date <= completed_cutoff)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(func.count() >= min_symbol_count)  # PK 唯一，count(*) 等价 distinct
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(1)
    ).first()
    return row[0] if row else None


def _latest_complete_daily_date_before(
    session,
    before_date: date,
    min_symbol_count: int = MIN_COMPLETE_DAILY_SYMBOL_COUNT,
) -> date | None:
    row = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date < before_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(func.count() >= min_symbol_count)  # PK 唯一，count(*) 等价 distinct
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(1)
    ).first()
    return row[0] if row else None


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
    """Main scheduler loop with a fast tick for time-sensitive board scans."""
    while not _scheduler_stop.is_set():
        try:
            _run_scheduled_jobs()
        except Exception as exc:
            logger.error("Scheduler tick error: %s", exc)
        _scheduler_stop.wait(timeout=SCHEDULER_TICK_SECONDS)


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
    """Trigger schedules whose cron matches or whose cron window was missed."""
    now_china = _now_china()
    for row in _load_batch_schedules():
        cron = row.get("cron")
        if not cron:
            continue
        action = str(row.get("action") or "sync")
        if action in {"limit_up_live_scan", "limit_up_concept_scan"} and not _limit_up_live_scan_window_open(now_china):
            continue
        if action == "limit_up_live_scan":
            recently_started = _recently_started(
                row,
                within_seconds=max(LIVE_SCAN_INTERVAL_SECONDS - 1, 1),
            )
        elif action == "limit_up_concept_scan":
            recently_started = _recently_started(
                row,
                within_seconds=max(CONCEPT_REFRESH_SECONDS - 1, 1),
            )
        else:
            recently_started = _recently_started(row)
        if recently_started:
            continue
        try:
            if _cron_matches(cron, now_china) or _schedule_catchup_due(row, now_china):
                _run_schedule_action(row)
        except Exception:
            pass


def _schedule_catchup_due(row: dict[str, Any], now_china: datetime) -> bool:
    """Return whether a default schedule should run after a missed cron window."""

    schedule_id = str(row.get("id") or "")
    if schedule_id not in {CURRENT_EOD_SCHEDULE_ID, "eod_finalize_2130"}:
        return False

    scheduled_at = _cron_scheduled_at_today(str(row.get("cron") or ""), now_china)
    if scheduled_at is None or now_china < scheduled_at:
        return False
    last_started = _as_aware_datetime(row.get("last_started_at"))
    if last_started is None:
        return True
    if last_started.astimezone(scheduled_at.tzinfo) < scheduled_at:
        return True

    return False


def _run_schedule_action(row: dict[str, Any], *, raise_errors: bool = False) -> dict[str, Any] | None:
    schedule_id = str(row["id"])
    action = str(row.get("action") or "sync")
    try:
        if action == "limit_up_concept_scan":
            _touch_schedule(
                schedule_id,
                last_started_at=datetime.now(timezone.utc),
                last_status="running",
            )
            snapshot = refresh_live_concept_snapshot()
            quality = snapshot.get("data_quality")
            quality = quality if isinstance(quality, dict) else {}
            succeeded = quality.get("status") == "ready"
            _touch_schedule(
                schedule_id,
                last_status="succeeded" if succeeded else "skipped",
                last_finished_at=datetime.now(timezone.utc),
                last_message=(
                    f"已更新 {int(snapshot.get('concept_count') or 0)} 个实时概念强度"
                    if succeeded
                    else f"概念行情不可用于新买点：{quality.get('status') or 'unavailable'}"
                ),
            )
            return snapshot
        if action == "limit_up_live_scan":
            _touch_schedule(
                schedule_id,
                last_started_at=datetime.now(timezone.utc),
                last_status="running",
            )
            snapshot = refresh_live_snapshot()
            saved = _live_scan_snapshot_saved(snapshot)
            _touch_schedule(
                schedule_id,
                last_status="succeeded" if saved else "skipped",
                last_finished_at=datetime.now(timezone.utc),
                last_message=_live_scan_status_message(snapshot, saved=saved),
            )
            return snapshot
        if action != "sync":
            raise DataSyncError(f"Unsupported schedule action: {action}")
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


def _live_scan_snapshot_saved(snapshot: dict[str, Any]) -> bool:
    quality = snapshot.get("data_quality")
    return (
        snapshot.get("mode") == "live_snapshot"
        and isinstance(quality, dict)
        and quality.get("is_stale") is False
    )


def _live_scan_actionable_count(snapshot: dict[str, Any]) -> int:
    recommendations = snapshot.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, dict) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, dict) else {}
    return sum(
        1
        for rows in lanes.values()
        if isinstance(rows, list)
        for signal in rows
        if isinstance(signal, dict) and signal.get("action") in {"buy_now", "next_auction"}
    )


def _live_scan_status_message(snapshot: dict[str, Any], *, saved: bool) -> str:
    actionable = _live_scan_actionable_count(snapshot)
    quality = snapshot.get("data_quality")
    quality = quality if isinstance(quality, dict) else {}
    trace_suffix = (
        f"；诊断缓存写入失败：{str(quality.get('trace_cache_error') or '未知错误')[:200]}"
        if quality.get("trace_cache_status") == "error"
        else ""
    )
    if saved:
        return f"已保存实时打板快照，{actionable} 个可执行动作{trace_suffix}"
    return f"行情非有效实时状态，快照未保存，{actionable} 个可执行动作{trace_suffix}"


def _limit_up_live_scan_window_open(now_china: datetime) -> bool:
    minute = now_china.hour * 60 + now_china.minute
    return (
        9 * 60 + 15 <= minute <= 11 * 60 + 30
        or 13 * 60 <= minute <= 14 * 60 + 57
    )


def _cron_matches(cron_expr: str, now: datetime) -> bool:
    """Minimal cron matcher — supports minute/hour/day-of-month/month/day-of-week."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    minute_pat, hour_pat, dom_pat, month_pat, dow_pat = parts

    # Cron day-of-week uses 0/7 for Sunday and 1-6 for Monday-Saturday.
    # Python datetime.weekday() uses 0 for Monday, so translate explicitly.
    cron_dow = (now.weekday() + 1) % 7

    return (
        _cron_field_matches(minute_pat, now.minute)
        and _cron_field_matches(hour_pat, now.hour)
        and _cron_field_matches(dom_pat, now.day)
        and _cron_field_matches(month_pat, now.month)
        and _cron_field_matches(dow_pat, cron_dow)
    )


def _cron_scheduled_at_today(cron_expr: str, now: datetime) -> datetime | None:
    """Return today's concrete scheduled time for simple minute/hour crons."""

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return None
    minute_pat, hour_pat, dom_pat, month_pat, dow_pat = parts
    if not minute_pat.isdigit() or not hour_pat.isdigit():
        return None

    cron_dow = (now.weekday() + 1) % 7
    if not (
        _cron_field_matches(dom_pat, now.day)
        and _cron_field_matches(month_pat, now.month)
        and _cron_field_matches(dow_pat, cron_dow)
    ):
        return None
    return now.replace(hour=int(hour_pat), minute=int(minute_pat), second=0, microsecond=0)


def _cron_field_matches(pattern: str, value: int) -> bool:
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


def _as_aware_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


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
    current_symbols: set[str] = set()
    with session_scope() as session:
        for item in items:
            symbol = str(item.get("symbol") or "")
            exchange = str(item.get("exchange") or normalize_exchange(symbol))
            vts = vt_symbol(symbol, exchange)
            if not symbol:
                continue
            current_symbols.add(vts)
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
        if current_symbols:
            session.execute(
                schema.sector_memberships.delete().where(
                    (schema.sector_memberships.c.sector_id == sector_id)
                    & schema.sector_memberships.c.vt_symbol.not_in(sorted(current_symbols))
                )
            )
    return written


def _delete_sector_memberships(sector_ids: Sequence[str]) -> int:
    """Remove stale rows for sectors that failed the current capture."""

    normalized = sorted({str(sector_id).strip() for sector_id in sector_ids if sector_id})
    if not normalized:
        return 0
    with session_scope() as session:
        result = session.execute(
            schema.sector_memberships.delete().where(
                schema.sector_memberships.c.sector_id.in_(normalized)
            )
        )
    return max(int(getattr(result, "rowcount", 0) or 0), 0)


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


@dataclass(frozen=True)
class SectorMemberFetchCapture:
    items: tuple[dict[str, Any], ...]
    expected_total: int | None
    source: str
    pagination_complete: bool


def _fetch_sector_stock_capture(
    adapter: AkShareAdapter,
    sector_id: str,
    page_size: int,
) -> SectorMemberFetchCapture:
    items: list[dict[str, Any]] = []
    identities: set[str] = set()
    expected_total: int | None = None
    source = ""
    page = 1
    bounded_page_size = min(max(page_size, 1), 500)
    while True:
        data = adapter.sector_stocks(sector_id, page=page, page_size=bounded_page_size)
        current_source = str(data.get("source") or "").strip()
        if source and current_source and current_source != source:
            raise DataSyncError(
                f"sector member source changed during pagination: {sector_id}"
            )
        source = current_source or source
        reported_total = data.get("total")
        if reported_total is not None:
            current_total = int(reported_total)
            if current_total < 0:
                raise DataSyncError(
                    f"sector member total is negative: {sector_id}"
                )
            if expected_total is not None and current_total != expected_total:
                raise DataSyncError(
                    f"sector member total changed during pagination: {sector_id}"
                )
            expected_total = current_total
        page_items = data.get("items") or []
        if not page_items:
            if expected_total is not None and len(items) < expected_total:
                raise DataSyncError(
                    f"sector member pagination incomplete: {sector_id}; "
                    f"returned={len(items)} expected={expected_total}"
                )
            break
        for item in page_items:
            identity = _sector_member_identity(item)
            if identity in identities:
                raise DataSyncError(
                    f"duplicate member across sector pages: {sector_id}:{identity}"
                )
            identities.add(identity)
            items.append(dict(item))
        if expected_total is not None and len(items) >= expected_total:
            break
        if expected_total is None and len(page_items) < bounded_page_size:
            break
        page += 1
        if page > SECTOR_MEMBER_MAX_PAGES:
            if expected_total is not None and len(items) < expected_total:
                raise DataSyncError(
                    f"sector member pagination exceeded page cap: {sector_id}; "
                    f"returned={len(items)} expected={expected_total}"
                )
            break
    if expected_total is not None and len(items) != expected_total:
        raise DataSyncError(
            f"sector member pagination count mismatch: {sector_id}; "
            f"returned={len(items)} expected={expected_total}"
        )
    return SectorMemberFetchCapture(
        items=tuple(items),
        expected_total=expected_total,
        source=source,
        pagination_complete=(expected_total is not None and len(items) == expected_total),
    )


def _fetch_all_sector_stocks(
    adapter: AkShareAdapter,
    sector_id: str,
    page_size: int,
) -> list[dict[str, Any]]:
    return list(_fetch_sector_stock_capture(adapter, sector_id, page_size).items)


def _sector_member_identity(item: dict[str, Any]) -> str:
    current = str(item.get("vt_symbol") or "").strip().upper()
    if current:
        return current
    symbol = str(item.get("symbol") or "").strip()
    if not symbol:
        raise DataSyncError("sector member symbol is empty")
    exchange = str(item.get("exchange") or normalize_exchange(symbol))
    return vt_symbol(symbol, exchange).upper()


def _save_low_suction_forward_membership_capture(
    *,
    sector_rows: Sequence[dict[str, Any]],
    members_by_sector: dict[str, tuple[dict[str, Any], ...]],
    failed_sector_ids: Sequence[str],
    observed_at: datetime,
) -> forward_membership.ForwardMembershipCapture | None:
    try:
        source_trade_date = _latest_complete_daily_date_for_research()
        observed_local = observed_at.astimezone(forward_membership.SHANGHAI)
        if (
            source_trade_date is None
            or source_trade_date != observed_local.date()
            or observed_local.time() < forward_membership.POST_CLOSE_START
        ):
            return None
        capture = forward_membership.build_forward_membership_capture(
            sectors=sector_rows,
            members_by_sector=members_by_sector,
            failed_sector_ids=failed_sector_ids,
            source_trade_date=source_trade_date,
            observed_at=observed_at,
        )
        forward_membership_repository.save_forward_membership_capture(capture)
    except Exception as exc:
        logger.warning(
            "low-suction forward membership scope remains closed: %s",
            exc,
        )
        return None
    return capture


def _next_day(date_value: Any) -> str | None:
    """Return ISO date of the day after ``date_value`` (str/date), or None."""
    try:
        d = date.fromisoformat(str(date_value)[:10])
    except Exception:
        return None
    return (d + timedelta(days=1)).isoformat()


def _minute_incremental_start_date(last_date: Any) -> str | None:
    parsed = _parse_date(last_date)
    if parsed is None:
        return None
    if parsed >= _now_china().date():
        return None
    return _next_day(parsed)


def _minute_adapter_start_date(start_date: Any, end_date: date | None) -> Any:
    """Use the live minute endpoint for current-day incremental refreshes.

    AkShare/EastMoney historical minute queries can return empty rows for the
    current trading day when a start date is supplied. For realtime 14:30 syncs
    we fetch the latest live minute window and let the DB upsert skip existing
    bars. Historical bounded requests keep their explicit start date.
    """

    if end_date is not None or not start_date:
        return start_date
    parsed = _parse_date(start_date)
    if parsed == _now_china().date():
        return None
    return start_date


def _incremental_daily_start_date(date_value: Any, refresh_days: int) -> str | None:
    """Return the start date for an incremental daily-bar refresh window."""
    if not date_value:
        return None
    if refresh_days <= 0:
        return _next_day(date_value)
    try:
        d = date.fromisoformat(str(date_value)[:10])
    except Exception:
        return None
    return (d - timedelta(days=refresh_days)).isoformat()


def _stock_daily_history_bootstrap_plan(
    *,
    symbols: list[str],
    stock_limit: int,
    total_stocks: int,
    incremental: bool,
) -> dict[str, int | bool]:
    plan: dict[str, int | bool] = {
        "required": False,
        "reliable_trade_days_before": 0,
        "target_trade_days": STOCK_DAILY_HISTORY_TARGET_DAYS,
        "request_limit": STOCK_DAILY_HISTORY_BOOTSTRAP_LIMIT,
    }
    if (
        not incremental
        or symbols
        or stock_limit > 0
        or total_stocks < STOCK_DAILY_HISTORY_MIN_UNIVERSE
    ):
        return plan

    reliable_days = _reliable_stock_daily_trade_days()
    plan["reliable_trade_days_before"] = reliable_days
    plan["required"] = reliable_days < STOCK_DAILY_HISTORY_TARGET_DAYS
    return plan


def _reliable_stock_daily_trade_days() -> int:
    with session_scope() as session:
        coverage = _reliable_stock_daily_history_coverage(session)
    return int(coverage["trade_days"])


def _reliable_stock_daily_history_coverage(session) -> dict[str, Any]:
    # PK (vt_symbol, trade_date) 保证每 (symbol, date) 唯一：count(*) 与
    # count(DISTINCT vt_symbol) 语义等价，但省掉 distinct 排序；配合
    # ix_stock_daily_bars_date_symbol 复合索引走 index-only scan。
    daily_counts = (
        select(
            schema.stock_daily_bars.c.trade_date,
            func.count().label("symbol_count"),
        )
        .group_by(schema.stock_daily_bars.c.trade_date)
        .subquery()
    )
    row = session.execute(
        select(
            func.count(),
            func.min(daily_counts.c.trade_date),
            func.max(daily_counts.c.trade_date),
        )
        .select_from(daily_counts)
        .where(
            daily_counts.c.trade_date
            <= completed_daily_bar_cutoff(_now_china()),
            daily_counts.c.symbol_count
            >= MIN_COMPLETE_DAILY_SYMBOL_COUNT
        )
    ).one()
    return {
        "trade_days": int(row[0] or 0),
        "start": _iso_or_none(row[1]),
        "end": _iso_or_none(row[2]),
    }


def _should_cleanup_partial_daily_sync(symbols: list[str], stock_limit: int, total_stocks: int) -> bool:
    """Only full-universe daily syncs may clean up partial cross-section dates."""

    return not symbols and stock_limit <= 0 and total_stocks >= MIN_COMPLETE_DAILY_SYMBOL_COUNT


def _daily_sync_complete_min_symbol_count(total_stocks: int) -> int:
    ratio_count = int(total_stocks * STOCK_DAILY_COMPLETE_COVERAGE_RATIO)
    return max(MIN_COMPLETE_DAILY_SYMBOL_COUNT, ratio_count)


def _daily_sync_cleanup_min_symbol_count(total_stocks: int, previous_complete_count: int) -> int:
    reference_count = previous_complete_count if previous_complete_count > 0 else total_stocks
    return _daily_sync_complete_min_symbol_count(reference_count)


def _discard_incomplete_latest_daily_bars(total_stocks: int) -> dict[str, Any]:
    """Remove a latest daily-bar date when the cross-section is still partial.

    Public quote sources can expose the new trade date for only part of the
    market during the evening. Keeping those rows makes MAX(trade_date) look
    like a valid close, so full-universe syncs discard that date until a later
    retry reaches the minimum cross-section coverage.
    """

    with session_scope() as session:
        latest_trade_date = session.execute(select(func.max(schema.stock_daily_bars.c.trade_date))).scalar()
        fallback_min_count = _daily_sync_complete_min_symbol_count(total_stocks)
        if latest_trade_date is None:
            return {"status": "empty", "latest_trade_date": None, "min_symbol_count": int(fallback_min_count)}
        completed_cutoff = completed_daily_bar_cutoff(_now_china())
        latest_count = _stock_daily_symbol_count(session, latest_trade_date)
        if latest_trade_date > completed_cutoff:
            latest_complete_date = _latest_complete_daily_date(
                session,
                MIN_COMPLETE_DAILY_SYMBOL_COUNT,
            )
            latest_complete_count = _stock_daily_symbol_count(
                session,
                latest_complete_date,
            )
            return {
                "status": "intraday_retained",
                "latest_trade_date": _iso_or_none(latest_trade_date),
                "latest_symbol_count": latest_count,
                "latest_complete_trade_date": _iso_or_none(latest_complete_date),
                "latest_complete_symbol_count": latest_complete_count,
                "completed_cutoff": completed_cutoff.isoformat(),
            }
        previous_complete_date = _latest_complete_daily_date_before(
            session,
            latest_trade_date,
            MIN_COMPLETE_DAILY_SYMBOL_COUNT,
        )
        previous_complete_count = _stock_daily_symbol_count(session, previous_complete_date)
        min_symbol_count = _daily_sync_cleanup_min_symbol_count(total_stocks, previous_complete_count)
        if latest_count >= min_symbol_count:
            return {
                "status": "complete",
                "latest_trade_date": _iso_or_none(latest_trade_date),
                "latest_symbol_count": latest_count,
                "reference_trade_date": _iso_or_none(previous_complete_date),
                "reference_symbol_count": previous_complete_count,
                "min_symbol_count": int(min_symbol_count),
            }
        delete_result = session.execute(
            schema.stock_daily_bars.delete().where(schema.stock_daily_bars.c.trade_date == latest_trade_date)
        )
        return {
            "status": "discarded_incomplete",
            "discarded_trade_date": _iso_or_none(latest_trade_date),
            "discarded_symbol_count": latest_count,
            "deleted_rows": int(delete_result.rowcount or latest_count or 0),
            "latest_complete_trade_date": _iso_or_none(previous_complete_date),
            "reference_symbol_count": previous_complete_count,
            "min_symbol_count": int(min_symbol_count),
        }


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
    """Upsert one stock's daily bars in a single PostgreSQL statement."""
    if not items:
        return 0
    normalized = normalize_exchange(symbol, exchange)
    vts = vt_symbol(symbol, normalized)
    values_by_date: dict[date, dict[str, Any]] = {}
    for item in items:
        trade_date_raw = item.get("trade_date")
        if isinstance(trade_date_raw, date):
            trade_date = trade_date_raw
        elif isinstance(trade_date_raw, str):
            try:
                trade_date = date.fromisoformat(trade_date_raw[:10])
            except ValueError:
                continue
        else:
            continue
        values_by_date[trade_date] = {
            "vt_symbol": vts,
            "trade_date": trade_date,
            "open_price": float(item.get("open") or item.get("open_price") or 0),
            "close_price": float(item.get("close") or item.get("close_price") or 0),
            "high_price": float(item.get("high") or item.get("high_price") or 0),
            "low_price": float(item.get("low") or item.get("low_price") or 0),
            "volume": item.get("volume"),
            "turnover": item.get("turnover"),
            "turnover_rate": item.get("turnover_rate"),
            "change_pct": item.get("change_pct"),
            "source": str(item.get("source") or "akshare"),
            "raw": item.get("raw") or {},
        }
    values = list(values_by_date.values())
    if not values:
        return 0

    statement = postgresql_insert(schema.stock_daily_bars).values(values)
    update_columns = (
        "open_price",
        "close_price",
        "high_price",
        "low_price",
        "volume",
        "turnover",
        "turnover_rate",
        "change_pct",
        "source",
        "raw",
    )
    statement = statement.on_conflict_do_update(
        index_elements=(schema.stock_daily_bars.c.vt_symbol, schema.stock_daily_bars.c.trade_date),
        set_={
            **{column: getattr(statement.excluded, column) for column in update_columns},
            "updated_at": func.now(),
        },
    )
    with session_scope() as session:
        session.execute(statement)
    return len(values)


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
    """Atomically rebuild the current reverse index from sector memberships."""

    items = _load_stock_sector_membership_items()
    if not items:
        raise DataSyncError("板块成员为空，保留上一版股票-板块反向索引")
    return _replace_stock_sector_memberships(items)


def _load_stock_sector_membership_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with session_scope() as session:
        member_rows = session.execute(select(schema.sector_memberships)).mappings().all()
        sector_by_id = {
            str(row["id"]): dict(row)
            for row in session.execute(select(schema.sectors)).mappings().all()
        }
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
    return items


def _replace_stock_sector_memberships(items: list[dict[str, Any]]) -> int:
    table = schema.stock_sector_memberships
    values = [
        {
            "vt_symbol": str(item.get("vt_symbol") or ""),
            "sector_id": str(item.get("sector_id") or ""),
            "sector_name": str(item.get("sector_name") or ""),
            "sector_type": str(item.get("sector_type") or "concept"),
            "rank": item.get("rank"),
            "confirmed": item.get("confirmed"),
            "is_precise": item.get("is_precise"),
            "source": str(item.get("source") or "akshare"),
            "raw": item.get("raw") or {},
        }
        for item in items
        if item.get("vt_symbol") and item.get("sector_id")
    ]
    if not values:
        raise DataSyncError("板块成员无有效主键，保留上一版股票-板块反向索引")

    with session_scope() as session:
        session.execute(table.delete())
        for offset in range(0, len(values), 500):
            session.execute(table.insert().values(values[offset:offset + 500]))
    return len(values)


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
    current_symbols: set[str] = set()
    with session_scope() as session:
        for item in items:
            symbol = str(item.get("symbol") or "")
            exchange = str(item.get("exchange") or normalize_exchange(symbol))
            if not symbol:
                continue
            vts = vt_symbol(symbol, exchange)
            current_symbols.add(vts)
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
        if current_symbols:
            session.execute(
                schema.shenwan_industry_members.delete().where(
                    (schema.shenwan_industry_members.c.industry_code == industry_code)
                    & schema.shenwan_industry_members.c.vt_symbol.not_in(sorted(current_symbols))
                )
            )
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
    source = str(source or "akshare")
    parsed_items: dict[date, dict[str, Any]] = {}
    for item in items:
        trade_date_raw = item.get("trade_date")
        if not trade_date_raw:
            continue
        trade_date = _parse_date(trade_date_raw)
        if trade_date is None:
            continue
        parsed_items[trade_date] = item
    if not parsed_items:
        return 0

    values = [
        {
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
        for trade_date, item in sorted(parsed_items.items())
    ]

    with session_scope() as session:
        if source == CANONICAL_SECTOR_DAILY_SOURCE:
            session.execute(
                schema.sector_daily_bars.delete().where(
                    (schema.sector_daily_bars.c.sector_id == sector_id)
                    & (schema.sector_daily_bars.c.source != source)
                )
            )
        statement = postgresql_insert(schema.sector_daily_bars).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=["sector_id", "trade_date"],
            set_={
                column: getattr(statement.excluded, column)
                for column in (
                    "open_price",
                    "close_price",
                    "high_price",
                    "low_price",
                    "volume",
                    "turnover",
                    "change_pct",
                    "source",
                    "raw",
                )
            }
            | {"updated_at": func.now()},
        )
        session.execute(statement)
    return len(values)


def _upsert_sector_fund_flows(
    items: list[dict[str, Any]],
    period: str,
    sector_type: str,
    *,
    captured_at: datetime | None = None,
) -> int:
    """Upsert sector fund flow records."""
    if not items:
        return 0
    written = 0
    snapshot_captured_at = captured_at or datetime.now(timezone.utc)
    with session_scope() as session:
        for item in items:
            name = str(item.get("name") or "")
            code = str(item.get("code") or name)
            sector_id = str(item.get("id") or item.get("akshare_symbol") or code)
            if not sector_id:
                continue
            trade_date = str(
                item.get("trade_date")
                or snapshot_captured_at.astimezone(timezone(timedelta(hours=8))).date().isoformat()
            )
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
    market_snapshot_repository.save_sector_fund_flow_snapshots(
        items,
        period=period,
        sector_type=sector_type,
        captured_at=snapshot_captured_at,
    )
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
    """Replace one trade date's limit-up/limit-down pool events."""
    if not items:
        return 0
    event_type = f"limit_pool_{pool_type}"
    event_dates = _limit_pool_event_date_keys(trade_date)
    written = 0
    with session_scope() as session:
        session.execute(
            schema.stock_events.delete().where(
                (schema.stock_events.c.source == LIMIT_POOL_EVENT_SOURCE)
                & (schema.stock_events.c.event_type == event_type)
                & (schema.stock_events.c.event_date.in_(event_dates))
            )
        )
        known_symbols = set(
            session.execute(select(schema.stocks.c.vt_symbol)).scalars().all()
        )
        seen_symbols: set[str] = set()
        for item in items:
            vts = str(item.get("vt_symbol") or "")
            if not vts or vts in seen_symbols or vts not in known_symbols:
                continue
            seen_symbols.add(vts)
            title = f"{pool_type}: {item.get('name', vts)}"
            values = {
                "vt_symbol": vts,
                "event_date": event_dates[0],
                "event_type": event_type,
                "title": title,
                "summary": str(item.get("raw") or {}),
                "url": None,
                "keywords": [pool_type],
                "sentiment": "positive" if pool_type in ("zt", "strong") else "negative",
                "importance": 0.8 if pool_type in ("zt", "strong") else 0.5,
                "source": LIMIT_POOL_EVENT_SOURCE,
                "raw": item.get("raw") or {},
            }
            session.execute(schema.stock_events.insert().values(**values))
            written += 1
    return written


def _limit_pool_event_date_keys(trade_date: str) -> list[str]:
    """Return both event_date formats used by historical limit-pool rows."""
    raw = str(trade_date or date.today().strftime("%Y%m%d")).strip()
    keys = [raw] if raw else []
    parsed: date | None = None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue
    if parsed:
        keys.extend([parsed.strftime("%Y%m%d"), parsed.isoformat()])
    return list(dict.fromkeys(key for key in keys if key))


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


def _financial_sync_stock_rows(
    stock_limit: int,
    only_missing: bool = True,
    *,
    symbols: list[str] | None = None,
    rotate_attempts: bool = True,
) -> list[dict[str, Any]]:
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
        if symbols:
            query = query.where(schema.stocks.c.vt_symbol.in_(symbols))
        rows = [dict(row) for row in session.execute(query).mappings().all()]

    if symbols or not rotate_attempts:
        return rows[:limit]
    attempts = _load_financial_sync_attempts(
        [str(row.get("vt_symbol") or "") for row in rows],
    )
    return _select_financial_candidates(
        rows,
        attempts,
        stock_limit=limit,
        now=datetime.now(timezone.utc),
    )


def _select_financial_candidates(
    stock_rows: Sequence[Any],
    attempts: dict[str, dict[str, Any]],
    *,
    stock_limit: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Rotate eligible stocks so slow symbols cannot starve the queue."""

    aware_now = _financial_attempt_datetime(now) or datetime.now(timezone.utc)
    eligible: list[dict[str, Any]] = []
    for source_row in stock_rows:
        row = dict(source_row)
        attempt = attempts.get(str(row.get("vt_symbol") or ""), {})
        next_retry_at = _financial_attempt_datetime(attempt.get("next_retry_at"))
        if next_retry_at is not None and next_retry_at > aware_now:
            continue
        eligible.append(row)

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def sort_key(row: dict[str, Any]) -> tuple[bool, datetime, float, str]:
        vt_symbol_value = str(row.get("vt_symbol") or "")
        last_attempt_at = _financial_attempt_datetime(
            attempts.get(vt_symbol_value, {}).get("last_attempt_at")
        )
        return (
            last_attempt_at is not None,
            last_attempt_at or epoch,
            -_financial_turnover(row.get("turnover")),
            vt_symbol_value,
        )

    eligible.sort(key=sort_key)
    limit = min(max(int(stock_limit or 100), 1), 1000)
    return eligible[:limit]


def _financial_turnover(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _financial_attempt_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _financial_retry_at() -> datetime:
    return datetime.now(timezone.utc) + FINANCIAL_SYNC_RETRY_DELAY


def _load_financial_sync_attempts(
    symbols: Sequence[str],
) -> dict[str, dict[str, Any]]:
    normalized_symbols = sorted({str(symbol) for symbol in symbols if symbol})
    if not normalized_symbols or not is_database_configured():
        return {}
    try:
        with session_scope() as session:
            rows = session.execute(
                select(schema.stock_financial_sync_attempts).where(
                    schema.stock_financial_sync_attempts.c.vt_symbol.in_(normalized_symbols),
                )
            ).mappings().all()
    except Exception:
        logger.warning("load financial sync attempts failed", exc_info=True)
        return {}
    return {str(row["vt_symbol"]): dict(row) for row in rows}


def _record_financial_sync_attempt(
    vt_symbol_value: str,
    status: str,
    *,
    error: str | None = None,
    next_retry_at: datetime | None = None,
) -> None:
    if not is_database_configured():
        return
    attempted_at = datetime.now(timezone.utc)
    table = schema.stock_financial_sync_attempts
    statement = postgresql_insert(table).values(
        vt_symbol=vt_symbol_value,
        status=status,
        attempt_count=1,
        last_error=str(error)[:500] if error else None,
        last_attempt_at=attempted_at,
        next_retry_at=next_retry_at,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.vt_symbol],
        set_={
            "status": statement.excluded.status,
            "attempt_count": table.c.attempt_count + 1,
            "last_error": statement.excluded.last_error,
            "last_attempt_at": statement.excluded.last_attempt_at,
            "next_retry_at": statement.excluded.next_retry_at,
            "updated_at": func.now(),
        },
    )
    try:
        with session_scope() as session:
            session.execute(statement)
    except Exception:
        logger.warning(
            "record financial sync attempt failed for %s",
            vt_symbol_value,
            exc_info=True,
        )


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


def _parse_aware_datetime(value: Any) -> datetime | None:
    """Parse an adapter timestamp and normalize it to UTC."""

    if isinstance(value, datetime):
        parsed = value
    else:
        text_value = str(value or "").strip()
        if not text_value:
            return None
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _auction_capture_window_open(value: datetime) -> bool:
    local = value.astimezone(timezone(timedelta(hours=8))) if value.tzinfo else value
    minute = local.hour * 60 + local.minute
    return 9 * 60 + 25 <= minute <= 9 * 60 + 29


def _auction_market_datetime(value: Any) -> datetime | None:
    text_value = str(value or "").strip()
    if len(text_value) < 10:
        return None
    parsed = _parse_datetime(text_value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=timezone(timedelta(hours=8)))


def _auction_source_time_ready(value: datetime) -> bool:
    local = value.astimezone(timezone(timedelta(hours=8)))
    minute = local.hour * 60 + local.minute
    return 9 * 60 + 25 <= minute <= 9 * 60 + 29
