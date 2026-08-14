"""连板复盘 API: 复盘页单页 payload + 盘中实时五池 live 分流 + 进程缓存。

- GET /api/lianban/review?date=YYYY-MM-DD —— 显式 date: 中国时区当日且无当日
  zt 归档行 → live 分流(实时池空/疑似昨日快照 → 404, 源不可用 → 503,
  不回落 —— 用户明确点了日期就该看到"没数据"); 否则 final/rebuild。
  date 缺省 = 「打开复盘页=今日」语义: 今日是周一~周五 → 先试今日(已归档
  → final; 未归档 → live 窗口内试 live, 实时池 zt 非空且通过指纹闸 →
  live 返回); 今日无数据(窗口外/实时池空/疑似快照/源不可用) → 回落最近
  有数据日 final/rebuild, 并在 payload data_quality 加 "fallback_from":
  今日日期 标注隐含请求日无数据; 今日是周末 → 直接最近有数据日(不标
  fallback_from; 法定节假日无法判别, 由指纹闸兜底识别昨日快照后回落)。
- live 数据诚实性两道闸(东财涨停池在非交易时段返回最近交易日快照, 且
  payload 无日期自标注字段, 不能冒充"今日盘中数据"):
  1. 时间闸: live 仅在北京时间 [09:25, 15:30] 启用(含两端; 09:25 集合
     竞价结束涨停池开始填充, 15:30 后盘后归档链路接管)。窗外: 缺省路径
     直接回落(不试 live), 显式 ?date=今日 → 404。
  2. 指纹闸(兜节假日/边缘): 实时 zt 池 vt_symbol 集合与最近归档日的 zt
     名单完全一致 → 判定为最近交易日快照 → 缺省回落 / 显式 404。盘中真实
     滚动名单必然与昨日归档不同, 15:00-15:30 整理窗口是今日完整数据 vs
     昨日归档也不同, 两场景自然过闸。
- live 分流: AkShareAdapter().limit_up_pools(per_pool_limit=None 全量,
  适配器 TTL 缓存保护, 前端 30s 轮询不会打爆东财), 经 archive.pool_row
  映射成归档行形状后 build_review(pool_rows_override=...) 走 final 同路径
  聚合, payload mode="live" + data_quality.live=True。核心池(zt/zbgc/dtgc)
  不可用或实时源异常 → 显式请求 503(缺任一核心池家数/封板率必然失真);
  zt_previous/strong 不可用 → 降级空池 + data_quality.missing 标
  "pool:<type>"。live payload 的 indices 指数条用 get_indices() 实时行情
  填补(当日日线收盘后才落库, 盘中库里全 null), 实时接口异常则保留
  null 降级不阻塞 live。
- GET /api/lianban/dates —— 可复盘交易日(归档 ∪ 重建, 降序, 限 400)。
- GET /api/lianban/ladder-history?days=60 —— 连板天梯历史(研究型): 近 N
  个有涨停交易日的梯队 matrix / 窗口晋级率 promotion_matrix / 每日龙头
  leaders; days 合法区间 [5, 250] 由 FastAPI 校验(越界 422); 无数据返回
  ok 空结构(dates=[], matrix=[]); 窗口数据量小(两次索引查询 + Python
  聚合), as_of=今日时当日晚间 rebuild 后会变, 不引入缓存。
- 进程缓存: final/rebuild 且 trade_date < 今日的 payload 不可变 →
  review_payload_cache 长 TTL 兜底 P95; live 与"今日 final"不缓存。
  缓存 key 带该日两表 max(updated_at) 版本戳(每次请求两条索引轻查询,
  含命中路径), 任何进程落库后版本变 → 自然 miss 回源, 正确性不依赖
  跨进程的 invalidate 调用; invalidate_lianban_cache() 仍在
  data_sync.py runner 接线作同进程防御。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db import schema as db_schema
from alphaagent.server.db.session import is_database_configured, session_scope
from alphaagent.server.services.lianban import archive as archive_module
from alphaagent.server.services.lianban.ladder_history import ladder_history
from alphaagent.server.services.lianban.review import ReviewNotFound, build_review
from alphaagent.server.services.lianban.review_cache import (
    REVIEW_CACHE_TTL_SECONDS,
    review_cache_key,
    review_payload_cache,
    version_stamp,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lianban", tags=["lianban"])

SHANGHAI = ZoneInfo("Asia/Shanghai")

_DATES_LIMIT = 400
# live 分流核心池: 缺任一整页家数/封板率失真 → 显式请求 503 / 缺省请求回落。
_LIVE_CORE_POOLS = ("zt", "zbgc", "dtgc")
# live 时间闸(北京时间, 含两端): 09:25 集合竞价结束涨停池开始填充;
# 15:30 后盘后归档链路接管。窗外东财返回最近交易日快照, 不冒充今日盘中。
_LIVE_WINDOW_START = time(9, 25)
_LIVE_WINDOW_END = time(15, 30)


def _in_live_window(now: datetime) -> bool:
    """live 时间闸: 仅北京时间 [_LIVE_WINDOW_START, _LIVE_WINDOW_END] 含两端。"""
    current = now.time()
    return _LIVE_WINDOW_START <= current <= _LIVE_WINDOW_END


class _LivePoolsUnavailable(Exception):
    """实时五池不可用: 源异常或核心池缺失; detail 透给显式路径的 503。"""

    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__(str(detail))
        self.detail = detail


def _now_china() -> datetime:
    return datetime.now(SHANGHAI)


def _pool_unavailable(pool: Any) -> bool:
    """池缺失(非 dict)视同不可用, 与归档口径一致。"""
    return not isinstance(pool, dict) or pool.get("status") == "unavailable"


def _has_archived_zt(session, trade_date: date) -> bool:
    """当日是否已有 zt 池归档行(live 分流的判定条件)。"""
    table = db_schema.limit_up_pool_snapshots
    stmt = (
        select(table.c.vt_symbol)
        .where(table.c.trade_date == trade_date, table.c.pool_type == "zt")
        .limit(1)
    )
    return session.execute(stmt).first() is not None


def _latest_review_date(session) -> date | None:
    """最近有数据的交易日: 归档 ∪ 重建两表最大日期取大(与 /dates 口径一致)。"""
    snapshots = db_schema.limit_up_pool_snapshots
    daily = db_schema.stock_limit_up_daily
    pool_max = session.execute(select(func.max(snapshots.c.trade_date))).scalar()
    daily_max = session.execute(select(func.max(daily.c.trade_date))).scalar()
    candidates = [d for d in (pool_max, daily_max) if d is not None]
    return max(candidates) if candidates else None


def _latest_archived_zt_symbols(session, before: date) -> tuple[date | None, set[str]]:
    """最近归档日(< before)的 zt 名单 vt_symbol 集合(指纹闸比对基准)。

    无归档 → (None, 空集)。一次 max 索引查询 + 一次名单索引查询。
    """
    table = db_schema.limit_up_pool_snapshots
    latest = session.execute(
        select(func.max(table.c.trade_date)).where(table.c.pool_type == "zt")
    ).scalar()
    if latest is None or latest >= before:
        # live 只在该日无归档时触发, 正常 latest < before; 防御: 归档日 >=
        # 目标日时指纹比对无意义(同日复写场景上游已拦截), 直接放行。
        return None, set()
    symbols = session.execute(
        select(table.c.vt_symbol).where(
            table.c.trade_date == latest, table.c.pool_type == "zt"
        )
    ).scalars().all()
    return latest, {str(symbol) for symbol in symbols}


def _map_live_pool_rows(
    target: date, pools_payload: dict[str, Any], source: str
) -> tuple[dict[str, list[dict]], list[str]]:
    """实时五池 items → 归档行形状 override; 返回 (override, 降级池清单)。

    与归档同口径: 按 vt_symbol 去重、空符号剔除; 不可用/缺失的池不进
    override(聚合侧 pools.get(type, []) 自然拿空)并记入降级清单。
    """
    override: dict[str, list[dict]] = {}
    degraded: list[str] = []
    for pool_type in archive_module.POOL_TYPES:
        pool = pools_payload.get(pool_type)
        if _pool_unavailable(pool):
            degraded.append(pool_type)
            continue
        rows: list[dict] = []
        seen: set[str] = set()
        for item in pool.get("items") or []:
            vt_symbol = str(item.get("vt_symbol") or "").strip()
            if not vt_symbol or vt_symbol in seen:
                continue
            seen.add(vt_symbol)
            rows.append(archive_module.pool_row(target, pool_type, item, source))
        override[pool_type] = rows
    return override, degraded


def _live_pool_rows(target: date) -> tuple[dict[str, list[dict]], list[str]]:
    """拉实时五池并映射为归档行 override; 失败抛 _LivePoolsUnavailable。"""
    try:
        payload = AkShareAdapter().limit_up_pools(
            target.strftime("%Y%m%d"), per_pool_limit=None
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("lianban live pools fetch failed: %s", exc, exc_info=True)
        raise _LivePoolsUnavailable({"reason": exc.__class__.__name__}) from exc
    pools_payload = payload.get("pools") or {}
    core_down = [
        pool_type
        for pool_type in _LIVE_CORE_POOLS
        if _pool_unavailable(pools_payload.get(pool_type))
    ]
    if core_down:
        raise _LivePoolsUnavailable({"pools": core_down})
    source = str(payload.get("source") or archive_module.DEFAULT_SOURCE)
    return _map_live_pool_rows(target, pools_payload, source)


def _fill_live_indices(payload: dict) -> None:
    """live 盘中指数条实时化: 当日日线收盘后才落库, review 的 indices 盘中
    六格全 null, 这里用适配器实时指数行情(get_indices 覆盖 INDEX_SYMBOLS
    全 9 个, 自带 TTL 缓存)按 vt_symbol 映射填补 change_pct。

    实时接口异常 → 保留 null 降级(不阻塞 live); 某指数实时行情缺失/涨幅
    为 None → 该格保持原样。填补成功的格同步摘掉 missing 里的
    "indices:<key>" 标注, 避免前端把有数据的格渲染成缺失。
    """
    indices = payload.get("indices")
    if not isinstance(indices, list):
        return
    try:
        quotes = AkShareAdapter().get_indices()
    except Exception as exc:  # noqa: BLE001
        logger.warning("lianban live indices fetch failed: %s", exc, exc_info=True)
        return
    by_vt_symbol = {
        str(getattr(quote, "vt_symbol", "")): quote for quote in quotes
    }
    filled_keys: set[str] = set()
    for entry in indices:
        if not isinstance(entry, dict):
            continue
        quote = by_vt_symbol.get(str(entry.get("vt_symbol") or ""))
        change_pct = getattr(quote, "change_pct", None) if quote else None
        if change_pct is None:
            continue
        entry["change_pct"] = change_pct
        key = entry.get("key")
        if key:
            filled_keys.add(str(key))
    if filled_keys:
        missing = payload.get("data_quality", {}).get("missing")
        if isinstance(missing, list):
            missing[:] = [
                item for item in missing
                if not (isinstance(item, str) and item.startswith("indices:")
                        and item.removeprefix("indices:") in filled_keys)
            ]


def _live_payload(session, target: date) -> dict | None:
    """live 全路径聚合; 实时 zt 池为空或未过指纹闸 → None(调用方决定
    404 或回落)。

    Raises:
        _LivePoolsUnavailable: 实时源异常或核心池不可用。
    """
    override, degraded = _live_pool_rows(target)
    zt_symbols = {str(row["vt_symbol"]) for row in override.get("zt", [])}
    if zt_symbols:
        # 指纹闸: 与最近归档日 zt 名单完全一致 → 东财返回的是最近交易日
        # 快照(非交易时段/节假日), 不能冒充今日盘中数据。
        archived_date, archived_symbols = _latest_archived_zt_symbols(
            session, target
        )
        if archived_symbols and zt_symbols == archived_symbols:
            logger.info(
                "lianban live zt pool matches %s archived snapshot (%d symbols); "
                "treat as stale snapshot for %s",
                archived_date,
                len(zt_symbols),
                target,
            )
            return None
    try:
        payload = build_review(session, target, pool_rows_override=override)
    except ReviewNotFound:
        return None
    _fill_live_indices(payload)
    if degraded:
        missing = payload["data_quality"]["missing"]
        missing.extend(f"pool:{pool_type}" for pool_type in degraded)
    return payload


def _data_version(session, target: date) -> tuple[str, str]:
    """该日 归档/重建 两表 max(updated_at) 版本戳(跨进程缓存失效的核心:
    任何进程落库 → 版本变 → key 变 → 自然 miss 回源)。两条走主键/索引的
    轻查询(~1ms), 缓存命中路径也跑; 无数据 → "none"。"""
    snapshots = db_schema.limit_up_pool_snapshots
    daily = db_schema.stock_limit_up_daily
    pool_version = session.execute(
        select(func.max(snapshots.c.updated_at)).where(
            snapshots.c.trade_date == target
        )
    ).scalar()
    daily_version = session.execute(
        select(func.max(daily.c.updated_at)).where(
            daily.c.trade_date == target
        )
    ).scalar()
    return version_stamp(pool_version), version_stamp(daily_version)


def _build_or_cached(session, target: date, today: date) -> dict:
    """历史日期走进程缓存(key 带数据版本戳; get_or_set 命中返回深拷贝,
    调用方加 fallback_from 标注不污染缓存); 今日 final 不缓存(盘后可能
    补偿重归档/重建)。"""
    if target < today:
        version_pool, version_daily = _data_version(session, target)
        return review_payload_cache.get_or_set(
            review_cache_key(target, version_pool, version_daily),
            REVIEW_CACHE_TTL_SECONDS,
            lambda: build_review(session, target),
        )
    return build_review(session, target)


def _explicit_review(session, target: date, now: datetime):
    """显式 ?date= 路径: 今日无归档 → live(时间闸外/空池/疑似快照 → 404,
    源不可用 → 503, 不回落)。"""
    today = now.date()
    if target == today and not _has_archived_zt(session, target):
        if not _in_live_window(now):
            raise ReviewNotFound(
                f"复盘数据不存在: {target.isoformat()}"
                "(今日实时数据仅在 09:25-15:30 提供)"
            )
        try:
            payload = _live_payload(session, target)
        except _LivePoolsUnavailable as exc:
            return JSONResponse(
                status_code=503,
                content=fail(
                    "LIANBAN_LIVE_UNAVAILABLE",
                    "连板实时涨停池暂时不可用，请稍后刷新。",
                    exc.detail,
                ),
            )
        if payload is None:
            raise ReviewNotFound(
                f"复盘数据不存在: {target.isoformat()}(实时涨停池为空或为最近交易日快照)"
            )
        return ok(payload)
    return ok(_build_or_cached(session, target, today))


def _default_review(session, now: datetime):
    """缺省日期路径: 「打开复盘页=今日」。工作日先试今日(归档 final →
    时间闸内试 live), 今日无数据(窗外/空池/疑似快照/源不可用)回落最近
    有数据日并标 fallback_from; 周末直接最近日(不标 fallback_from)。"""
    today = now.date()
    fallback_from: date | None = None
    if today.weekday() < 5:
        if _has_archived_zt(session, today):
            return ok(build_review(session, today))  # 今日 final 不缓存
        fallback_from = today  # 工作日且无今日归档: 隐含请求的是今日
        if _in_live_window(now):
            try:
                payload = _live_payload(session, today)
            except _LivePoolsUnavailable:
                payload = None
            if payload is not None:
                return ok(payload)
    target = _latest_review_date(session)
    if target is None:
        raise ReviewNotFound("复盘数据不存在: 无任何涨停池归档或日线重建")
    payload = _build_or_cached(session, target, today)
    if fallback_from is not None and target != today:
        payload["data_quality"]["fallback_from"] = today.isoformat()
    return ok(payload)


@router.get("/review", response_model=None)
def lianban_review(trade_date: date | None = Query(default=None, alias="date")):
    """复盘页单页 payload; date 非法格式由 FastAPI 校验转 422。"""
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("LIANBAN_DB_UNAVAILABLE", "数据库未配置，连板复盘不可用。"),
        )
    now = _now_china()
    try:
        with session_scope() as session:
            if trade_date is not None:
                return _explicit_review(session, trade_date, now)
            return _default_review(session, now)
    except ReviewNotFound as exc:
        return JSONResponse(
            status_code=404,
            content=fail("REVIEW_NOT_FOUND", str(exc)),
        )


@router.get("/dates", response_model=None)
def lianban_dates():
    """可复盘交易日列表(归档 ∪ 重建, 降序, 限 400)。"""
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("LIANBAN_DB_UNAVAILABLE", "数据库未配置，连板复盘不可用。"),
        )
    snapshots = db_schema.limit_up_pool_snapshots
    daily = db_schema.stock_limit_up_daily
    with session_scope() as session:
        pool_dates = (
            session.execute(select(snapshots.c.trade_date).distinct()).scalars().all()
        )
        daily_dates = (
            session.execute(select(daily.c.trade_date).distinct()).scalars().all()
        )
    merged = sorted({*pool_dates, *daily_dates}, reverse=True)[:_DATES_LIMIT]
    return ok(
        {
            "dates": [d.isoformat() for d in merged],
            "latest": merged[0].isoformat() if merged else None,
        }
    )


@router.get("/ladder-history", response_model=None)
def lianban_ladder_history(
    days: int = Query(default=60, ge=5, le=250),
    include_st: bool = Query(default=False),
):
    """连板天梯历史: 近 N 个有涨停交易日的梯队/晋级率/龙头序列。

    days 越界/非整数由 FastAPI 校验转 422; 无数据返回 ok 空结构。
    数据量小(两次索引查询 + Python 聚合), 不引入进程缓存。
    """
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail(
                "LIANBAN_DB_UNAVAILABLE", "数据库未配置，连板天梯历史不可用。"
            ),
        )
    with session_scope() as session:
        return ok(ladder_history(session, days=days, include_st=include_st))
