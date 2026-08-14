"""Mainline replay API — 历史日期回放概念主线/大盘/资金 + 概念共振关联.

Provides:
  - GET /api/mainline-replay/timeline  可回放的交易日列表
  - GET /api/mainline-replay/snapshot  单日快照(date) 或 区间delta(t1+t2)
  - GET /api/mainline-replay/relation  指定概念在指定日期的共振概念

设计文档：docs/superpowers/specs/2026-06-28-mainline-replay-design.md
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope
from alphaagent.server.services.mainline_replay import (
    compute_fund_strength_batch,
    compute_raw_sector_delta,
    compute_relations_aligned,
)

logger = logging.getLogger(__name__)

def _reject_sector_type_query(request: Request) -> None:
    if "sector_type" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "BAD_PARAMS",
                "message": "概念主线固定只看题材概念，不接受 sector_type 参数。",
                "data": {},
            },
        )


def _cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    cached = _RESPONSE_CACHE.get(key)
    if cached is None:
        return None
    expires_at, payload = cached
    if expires_at <= monotonic():
        _RESPONSE_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: tuple[Any, ...], payload: dict[str, Any], ttl_seconds: int | None = None) -> None:
    if ttl_seconds is None:
        ttl_seconds = _CACHE_DEFAULT_TTL_SECONDS
    _RESPONSE_CACHE[key] = (monotonic() + ttl_seconds, payload)


def _now_china() -> datetime:
    return datetime.now(_CHINA_TZ)


def _is_trading_weekday(d: date) -> bool:
    return d.weekday() < 5


def _is_mainline_realtime_window(now: datetime | None = None) -> bool:
    """Return whether /mainline should prefer today's realtime overlay.

    This is a pragmatic weekday/time guard, not a full exchange holiday calendar.
    The realtime source itself remains authoritative: if it only has yesterday,
    the response is marked delayed/fallback instead of inventing today's data.
    """

    current = now or _now_china()
    if not _is_trading_weekday(current.date()):
        return False
    t = current.time()
    return time(9, 15) <= t <= time(19, 0)


def _default_live_trade_date(session) -> date | None:
    if _is_mainline_realtime_window():
        return _now_china().date()
    latest_flow_date = _parse_optional_date(_latest_concept_flow_date(session))
    if latest_flow_date is not None:
        return latest_flow_date
    return _latest_complete_daily_date(session)


def _fetch_live_concept_flow(period: str = "即时") -> dict[str, Any]:
    """Fetch concept fund-flow rows for the UI hot path without writing DB.

    The cache is intentionally separate from historical sync state. Page refreshes
    read this cache and only one request can refresh it at a time; stale data is
    returned on source failure so the UI remains usable under public-source limits.
    """

    normalized_period = str(period or "即时")
    cache_key = ("concept", normalized_period)
    cached = _LIVE_FLOW_CACHE.get(cache_key)
    now_mono = monotonic()
    if cached and cached[0] > now_mono:
        return {**cached[1], "cache_state": "fresh"}

    with _LIVE_FLOW_LOCK:
        cached = _LIVE_FLOW_CACHE.get(cache_key)
        now_mono = monotonic()
        if cached and cached[0] > now_mono:
            return {**cached[1], "cache_state": "fresh"}
        try:
            payload = AkShareAdapter().sector_fund_flows(sector_type="concept", period=normalized_period)
            payload = {
                **payload,
                "cache_state": "fresh",
                "fetched_at": _now_china().isoformat(),
                "resolved_trade_date": _flow_payload_trade_date(payload),
            }
            _LIVE_FLOW_CACHE[cache_key] = (now_mono + _LIVE_FLOW_CACHE_TTL_SECONDS, payload)
            return payload
        except Exception as exc:
            if cached:
                stale = {
                    **cached[1],
                    "cache_state": "stale",
                    "source_error": exc.__class__.__name__,
                    "resolved_trade_date": cached[1].get("resolved_trade_date") or _flow_payload_trade_date(cached[1]),
                }
                return stale
            raise


def _flow_payload_trade_date(payload: dict[str, Any]) -> str | None:
    dates: list[str] = []
    for item in payload.get("items") or []:
        parsed = _parse_optional_date(item.get("trade_date"))
        if parsed is not None:
            dates.append(parsed.isoformat())
    return max(dates) if dates else None


router = APIRouter(
    prefix="/mainline-replay",
    tags=["mainline-replay"],
    dependencies=[Depends(_reject_sector_type_query)],
)

# 大盘指数 vt_symbol（与 alphaagent.market.symbols.INDEX_SYMBOLS 一致）
_INDEX_VT_SYMBOLS = [
    "000001.SSE", "399001.SZSE", "399006.SZSE",
    "000300.SSE", "000905.SSE", "000852.SSE", "000688.SSE",
]
_DEFAULT_PERIOD = "20d"
_MAINLINE_SECTOR_TYPE = "concept"
_WINDOW_DAYS = 20  # 概念共振窗口
_CONCEPT_INDEX_POINTS = 20
_CONCEPT_INDEX_LOOKBACK_DAYS = 90
_ACTIVE_HEAT_THRESHOLD = 60.0
_HISTORICAL_HOT_LIMIT = 120
_ROLLING_BOARD_DAYS = 7
_ROLLING_BOARD_TOP_N = 10
_LIVE_RANKING_CANDIDATE_LIMIT = 1000
_MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3000
# 注：stock_daily_bars PK (vt_symbol, trade_date) 保证每日 symbol 唯一，
# 各查询用 count(*) 代替 count(DISTINCT vt_symbol)（语义等价，省 distinct 排序）。
_STOCK_MOMENTUM_LOOKBACK_DAYS = 45
_SENTIMENT_DEFAULT_LOOKBACK = 60
_SENTIMENT_MAX_LOOKBACK = 180
# 连续情绪大周期：以最新完整日线为锚，一次计算的历史跨度（完整交易日数）。
# 所有 sentiment-cycle 请求（任意 date/lookback）都从这条曲线切片，
# 避免窗口随日期移动导致连板 streak 截断、同一日数值跳变。
# 2026-08-14: 250 → 1250(约5年)。连板复盘「明日推演」同景统计需要多年样本
# (近一年牛市里冰点/退潮日仅个位数,对齐 lianban 的同景量级需覆盖 2021-2024
# 弱市)。实测 250 日重建 39s,1250 日约 3.5 分钟,盘后窗口可接受。
_SENTIMENT_HISTORY_SPAN_DAYS = 1250
_SENTIMENT_SCAN_BATCH_SIZE = 10_000
_SENTIMENT_RESPONSE_TTL_SECONDS = 30
_SENTIMENT_RETRY_TTL_SECONDS = 3
_NORMAL_LIMIT_UP_THRESHOLD = 9.5
_WIDE_LIMIT_UP_THRESHOLD = 19.0
_BSE_LIMIT_UP_THRESHOLD = 29.0
_RELATION_CANDIDATE_LIMIT = 360
_CACHE_DEFAULT_TTL_SECONDS = 300
_CACHE_LIVE_TTL_SECONDS = 30
_LIVE_FLOW_CACHE_TTL_SECONDS = 60
_CHINA_TZ = timezone(timedelta(hours=8))
_RESPONSE_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_LIVE_FLOW_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_LIVE_FLOW_LOCK = threading.Lock()
_SENTIMENT_HISTORY_CACHE: dict[
    tuple[str, str], tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]
] = {}
_SENTIMENT_HISTORY_LOCK = threading.Lock()
_SENTIMENT_REFRESH_LOCK = threading.Lock()
_SENTIMENT_REFRESH_RUNNING = False
_STYLE_STATUS_KEYWORDS = (
    "大盘",
    "中盘",
    "小盘",
    "微盘",
    "低价",
    "高价",
    "百元",
    "破发",
    "破净",
    "次新",
    "新股",
    "亏损",
    "扭亏",
    "预增",
    "预减",
    "分红",
    "送转",
    "融资融券",
    "沪股通",
    "深股通",
    "陆股通",
    "MSCI",
    "富时",
    "标普",
    "证金",
    "社保",
    "QFII",
    "养老金",
    "机构重仓",
    "基金重仓",
    "昨日",
    "最近",
    "近期",
    "新高",
    "百日",
    "热股",
    "题材股",
    "趋势股",
    "强势股",
    "涨停",
    "连板",
    "多板",
    "打板",
    "炸板",
    "触板",
    "首板",
    "二板",
    "三板",
    "高振幅",
    "高换手",
    "龙虎榜",
    "上证",
    "中证",
    "沪深",
    "央视",
    "成份",
    "成分",
    "AH股",
    "茅指数",
    "宁组合",
    "风格",
    "股权激励",
    "专精特新",
    "创业板综",
    "科创板综",
    "创业板指",
    "科创板指",
    "深证",
    "深成",
    "HS300",
    "权重股",
    "行业龙头",
    "大盘成长",
    "大盘价值",
    "中盘成长",
    "小盘成长",
    "标准普尔",
)


@router.get("/timeline", response_model=None)
def timeline(limit: int = Query(400, ge=1, le=2000)) -> dict[str, Any]:
    """可回放的交易日列表（概念 sector_period_scores 里存在的 as_of_date 去重降序）。"""
    if not is_database_configured():
        return ok({"dates": [], "status": "unavailable", "message": "数据库未配置"})
    cache_key = ("mainline_replay.timeline", int(limit))
    cached = _cache_get(cache_key)
    if cached is not None:
        return ok(cached)
    with session_scope() as session:
        complete_trade_dates = (
            select(schema.stock_daily_bars.c.trade_date)
            .group_by(schema.stock_daily_bars.c.trade_date)
            .having(func.count() >= _MIN_COMPLETE_DAILY_SYMBOL_COUNT)
        ).subquery()
        rows = session.execute(
            select(schema.sector_period_scores.c.as_of_date)
            .where(schema.sector_period_scores.c.period == _DEFAULT_PERIOD)
            .where(schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE)
            .where(schema.sector_period_scores.c.as_of_date.in_(select(complete_trade_dates.c.trade_date)))
            .group_by(schema.sector_period_scores.c.as_of_date)
            .order_by(desc(schema.sector_period_scores.c.as_of_date))
            .limit(limit)
        ).all()
    dates = [str(r[0]) for r in rows]
    payload = {"dates": dates, "status": "ready" if dates else "empty"}
    _cache_set(cache_key, payload)
    return ok(payload)


@router.get("/live", response_model=None)
def live(
    trade_date: date | None = Query(None, description="盘中日期 YYYY-MM-DD；默认取最新概念资金流日期"),
    limit: int = Query(80, ge=1, le=300),
    flow_period: str = Query("即时", description="概念资金流周期：即时/3日/5日/10日/20日"),
) -> dict[str, Any]:
    """今日/盘中概念主线资金流。

    历史回放读 sector_period_scores；收盘前实时模式只读可覆盖当日的
    concept sector_fund_flows + sectors 快照，不把盘中数据写成历史评分。
    """
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})

    if not isinstance(trade_date, date):
        trade_date = None

    with session_scope() as session:
        resolved_date = trade_date or _default_live_trade_date(session)
        if resolved_date is None:
            return ok({"status": "empty", "ranking": [], "index": []})
        can_try_realtime = trade_date is None and _is_mainline_realtime_window()
        cache_key = (
            "mainline_replay.live",
            resolved_date.isoformat(),
            int(limit),
            flow_period,
            "realtime" if can_try_realtime else "history",
        )
        cached = _cache_get(cache_key)
        if cached is not None:
            return ok(cached)

        realtime_payload: dict[str, Any] | None = None
        realtime_source_error: str | None = None
        if can_try_realtime:
            try:
                realtime_payload = _fetch_live_concept_flow("即时")
                payload_date = _parse_optional_date(realtime_payload.get("resolved_trade_date"))
                if payload_date is not None:
                    resolved_date = payload_date
                ranking = _live_ranking_from_flow_items(
                    session,
                    resolved_date,
                    realtime_payload.get("items") or [],
                    max(limit, _LIVE_RANKING_CANDIDATE_LIMIT),
                )
            except Exception as exc:
                realtime_source_error = exc.__class__.__name__
                ranking = []
        else:
            ranking = []

        if not ranking:
            ranking = _live_ranking_for_date(session, resolved_date, max(limit, _LIVE_RANKING_CANDIDATE_LIMIT))
            if not ranking and trade_date is None:
                fallback_date = _parse_optional_date(_latest_concept_flow_date(session))
                if fallback_date is not None and fallback_date != resolved_date:
                    resolved_date = fallback_date
                    ranking = _live_ranking_for_date(session, resolved_date, max(limit, _LIVE_RANKING_CANDIDATE_LIMIT))

        _enrich_concept_index_context(session, ranking, resolved_date, include_live_projection=True)
        ranking = _sort_live_concept_ranking(ranking)
        flow_top = _live_flow_top_or_history(session, resolved_date, flow_period, realtime_payload)
        flow_top = _attach_ranking_context_to_flow_top(flow_top, ranking)
        ranking = ranking[:limit]
        latest_complete_daily = _latest_complete_daily_date(session)
        latest_snapshot_updated = session.execute(select(func.max(schema.stocks.c.updated_at))).scalar()
        latest_snapshot_trade_time = session.execute(select(func.max(schema.stocks.c.trade_time))).scalar()
        latest_minute_time = session.execute(
            select(func.max(schema.stock_minute_bars.c.bar_time)).where(
                schema.stock_minute_bars.c.trade_date == resolved_date,
                schema.stock_minute_bars.c.interval == "1m",
            )
        ).scalar()

    data_state = "realtime" if realtime_payload and ranking else "history_fallback"
    if realtime_payload and realtime_payload.get("cache_state") == "stale":
        data_state = "realtime_delayed"
    source_parts = ["sector_fund_flows:concept"]
    if realtime_payload:
        source_parts.insert(0, "eastmoney.sector_fund_flow_rank:hot_cache")
    if realtime_source_error:
        source_parts.append(f"realtime_error={realtime_source_error}")
    payload = {
        "mode": "live",
        "trade_date": resolved_date.isoformat(),
        "base_daily_date": _iso_or_none(latest_complete_daily),
        "ranking": ranking,
        "flow_top": flow_top,
        "index": [],
        "status": "ready" if ranking else "empty",
        "source": ",".join(source_parts),
        "data_state": data_state,
        "temporary_bar": True,
        "latest_minute_time": _iso_or_none(latest_minute_time),
        "snapshot_updated_at": _iso_or_none(latest_snapshot_updated),
        "realtime_updated_at": (
            realtime_payload.get("fetched_at")
            if realtime_payload
            else _iso_or_none(latest_snapshot_updated)
        ),
        "snapshot_trade_time": str(latest_snapshot_trade_time) if latest_snapshot_trade_time else None,
        "message": _live_message(data_state),
    }
    _cache_set(cache_key, payload, _CACHE_LIVE_TTL_SECONDS)
    return ok(payload)


@router.get("/snapshot", response_model=None)
def snapshot(
    date: date | None = Query(None, description="单日快照日期 YYYY-MM-DD"),
    t1: date | None = Query(None, description="区间起点"),
    t2: date | None = Query(None, description="区间终点"),
    limit: int = Query(50, ge=1, le=300),
    flow_period: str = Query("即时", description="概念资金流周期：即时/3日/5日/10日/20日"),
) -> dict[str, Any]:
    """单日快照(date) 或 区间delta(t1+t2)。

    返回概念主线榜(按 heat_score/fund_strength)、大盘指数。
    """
    if date is None and (t1 is None or t2 is None):
        return JSONResponse(
            status_code=400,
            content=fail("BAD_PARAMS", "需要 date 或 (t1,t2)", {}),
        )
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})

    with session_scope() as session:
        if date is not None:
            ranking = _ranking_for_date(session, date, max(limit, _LIVE_RANKING_CANDIDATE_LIMIT))
            mode = "single"
        else:
            ranking = _ranking_for_range(session, t1, t2, limit)  # type: ignore[arg-type]
            mode = "delta"
        index_data = _load_index(session, date or t2)  # type: ignore[arg-type]
        sectors_meta = _load_sectors_meta(session)
        for item in ranking:
            meta = sectors_meta.get(item["sector_id"], {})
            item["name"] = meta.get("name", item["sector_id"])
        _enrich_concept_index_context(session, ranking, date or t2, include_live_projection=False)  # type: ignore[arg-type]
        flow_top = _compute_flow_top(session, date, flow_period) if date is not None else None
        if date is not None:
            ranking = _sort_live_concept_ranking(ranking)
            if flow_top is not None:
                flow_top = _attach_ranking_context_to_flow_top(flow_top, ranking)
            ranking = ranking[:limit]

    return ok({"mode": mode, "ranking": ranking, "flow_top": flow_top, "index": index_data, "status": "ready"})


@router.get("/sentiment-cycle", response_model=None)
def sentiment_cycle(
    date: date | None = Query(None, description="情绪周期截止日期 YYYY-MM-DD；默认取最新实时资金流日或最新完整日线日"),
    lookback: int = Query(_SENTIMENT_DEFAULT_LOOKBACK, ge=5, le=_SENTIMENT_MAX_LOOKBACK),
    include_live: bool = Query(True, description="是否在可用时追加/替换当前日实时投影点"),
) -> dict[str, Any]:
    """短线情绪周期曲线。

    历史点只读完整 `stock_daily_bars`；当前日投影只读 `stocks` 快照和
    分钟高点，不写入历史评分。炸板/晋级是日K可见代理，不等同逐笔封板统计。
    """
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})

    # 缓存键只用请求参数（不含解析后日期）：重复请求跳过整个日期解析链，
    # 命中即毫秒返回。
    cache_key = (
        "mainline_replay.sentiment_cycle",
        date.isoformat() if date else "latest",
        int(lookback),
        bool(include_live),
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return ok(cached)

    with session_scope() as session:
        resolved_date = _resolve_sentiment_cycle_date(session, date)
        if resolved_date is None:
            return ok({
                "status": "empty",
                "mode": "history",
                "trade_date": None,
                "base_daily_date": None,
                "points": [],
                "ranges": [],
                "current": None,
                "source": "stock_daily_bars",
            })

        # 完整日线曲线在盘后预计算并持久化。首次或数据更新后由后台重建，
        # 请求线程只读最近可用曲线，避免页面等待全市场窗口计算。
        anchor_date, full_points, symbol_state, history_cache_state = _sentiment_history_for_request(session)
        if anchor_date is None or not full_points:
            return ok({
                "status": "building" if history_cache_state == "building" else "empty",
                "mode": "history",
                "trade_date": resolved_date.isoformat(),
                "base_daily_date": _iso_or_none(anchor_date),
                "points": [],
                "ranges": [],
                "current": None,
                "source": "stock_daily_bars",
                "cache_state": history_cache_state,
            })

        # as-of 切片：显式 date 时曲线截止到该日（版本热度回看）；否则锚定最新
        end_iso = min(date, anchor_date).isoformat() if date else anchor_date.isoformat()
        # dict(p) 浅拷贝：live 路径会重写 score_change，不能污染缓存里的全量曲线
        points = [dict(p) for p in full_points if p["date"] <= end_iso][-lookback:]
        mode = "history"
        source = "stock_daily_bars"
        latest_snapshot_updated = None
        latest_snapshot_trade_time = None
        latest_minute_time = None

        can_project_live = (
            include_live
            and history_cache_state == "ready"
            and resolved_date is not None
            and _can_use_intraday_snapshot(session, resolved_date)
        )
        if can_project_live:
            live_projection = _build_live_sentiment_point(session, resolved_date, symbol_state)
            if live_projection is not None:
                live_point, latest_minute_time = live_projection
                points = [p for p in points if p["date"] != live_point["date"]]
                points.append(live_point)
                points.sort(key=lambda item: item["date"])
                _attach_sentiment_score_changes(points)
                mode = "live"
                source = "stock_daily_bars,stocks_snapshot,stock_minute_bars"
                latest_snapshot_updated = session.execute(select(func.max(schema.stocks.c.updated_at))).scalar()
                latest_snapshot_trade_time = session.execute(select(func.max(schema.stocks.c.trade_time))).scalar()

        ranges = _sentiment_ranges(points, lookback)
        current = points[-1] if points else None

    payload = {
        "status": "ready" if points else "empty",
        "mode": mode,
        "trade_date": resolved_date.isoformat(),
        "base_daily_date": _iso_or_none(anchor_date),
        "points": points,
        "ranges": ranges,
        "current": current,
        "source": source,
        "temporary_bar": bool(current and current.get("temporary")),
        "latest_minute_time": _iso_or_none(latest_minute_time),
        "snapshot_updated_at": _iso_or_none(latest_snapshot_updated),
        "snapshot_trade_time": str(latest_snapshot_trade_time) if latest_snapshot_trade_time else None,
        "cache_state": history_cache_state,
        "limitations": [
            "炸板率使用日K高点触板但收盘未封板的代理，不等同逐笔盘口封板统计。",
            "晋级率使用昨日涨停股今日继续涨停的代理，不区分一进二、二进三等梯队。",
            "实时点来自当前快照和分钟高点，只作盘中投影，收盘后以完整日线为准。",
        ],
    }
    _cache_set(
        cache_key,
        payload,
        _SENTIMENT_RETRY_TTL_SECONDS
        if history_cache_state != "ready"
        else _SENTIMENT_RESPONSE_TTL_SECONDS,
    )
    return ok(payload)


@router.get("/relation", response_model=None)
def relation(
    sector_id: str = Query(..., description="目标概念ID"),
    date: date = Query(..., description="回放日期 YYYY-MM-DD"),
    limit: int = Query(12, ge=1, le=50),
) -> dict[str, Any]:
    """指定概念在指定日期的关联概念（按走势/资金共振和成分重叠计算）。"""
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})

    with session_scope() as session:
        sectors_meta = _load_sectors_meta(session)
        if not _is_mainline_concept_meta(sectors_meta.get(sector_id, {})):
            return ok({
                "target": sector_id,
                "target_date": str(date),
                "items": [],
                "status": "unsupported_target",
                "message": "概念主线只支持题材概念。",
            })

        # 目标概念最近 _WINDOW_DAYS 个评分日（as_of_date <= date，return_pct 非空）。
        # 数据源用 sector_period_scores，return_pct 为滚动周期收益率，
        # 序列共振仍反映概念间走势协同。
        tgt_rows = session.execute(
            select(
                schema.sector_period_scores.c.as_of_date,
                schema.sector_period_scores.c.return_pct,
                schema.sector_period_scores.c.fund_score,
            )
            .where(
                schema.sector_period_scores.c.sector_id == sector_id,
                schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
                schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE,
                schema.sector_period_scores.c.as_of_date <= date,
                schema.sector_period_scores.c.return_pct.isnot(None),
            )
            .order_by(schema.sector_period_scores.c.as_of_date.desc())
            .limit(_WINDOW_DAYS)
        ).all()
        target_map: dict[Any, float] = {}
        target_fund_map: dict[Any, float] = {}
        for r in tgt_rows:
            d, ret, fund = r[0], r[1], r[2]
            if ret is not None:
                target_map[d] = float(ret)
            if fund is not None:
                target_fund_map[d] = float(fund)
        if len(target_map) < 3:
            return ok({"target": sector_id, "items": [], "status": "insufficient_data"})
        tgt_dates = sorted(target_map.keys())

        tgt_members = {
            r[0]
            for r in session.execute(
                select(schema.sector_memberships.c.vt_symbol).where(
                    schema.sector_memberships.c.sector_id == sector_id
                )
            ).all()
        }
        overlap_candidate_rows = session.execute(
            select(
                schema.sector_memberships.c.sector_id,
            )
            .where(schema.sector_memberships.c.vt_symbol.in_(tgt_members))
            .where(schema.sector_memberships.c.sector_id != sector_id)
            .join(schema.sectors, schema.sectors.c.id == schema.sector_memberships.c.sector_id)
            .where(schema.sectors.c.type == _MAINLINE_SECTOR_TYPE)
            .group_by(schema.sector_memberships.c.sector_id)
            .order_by(func.count().desc())
            .limit(_RELATION_CANDIDATE_LIMIT)
        ).all()

        max_heat = func.max(schema.sector_period_scores.c.heat_score).label("max_heat")
        active_candidate_rows = session.execute(
            select(
                schema.sector_period_scores.c.sector_id,
                max_heat,
            )
            .where(
                schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
                schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE,
                schema.sector_period_scores.c.as_of_date.in_(tgt_dates),
                schema.sector_period_scores.c.return_pct.isnot(None),
                schema.sector_period_scores.c.sector_id != sector_id,
            )
            .group_by(schema.sector_period_scores.c.sector_id)
            .order_by(max_heat.desc())
            .limit(_RELATION_CANDIDATE_LIMIT)
        ).all()
        cand_ids: list[str] = []
        for sid in [str(r[0]) for r in overlap_candidate_rows] + [str(r[0]) for r in active_candidate_rows]:
            if sid in cand_ids or not _is_mainline_concept_meta(sectors_meta.get(sid, {})):
                continue
            cand_ids.append(sid)
            if len(cand_ids) >= _RELATION_CANDIDATE_LIMIT:
                break

        cand_members: dict[str, set[str]] = {sid: set() for sid in cand_ids}
        if cand_ids:
            member_rows = session.execute(
                select(
                    schema.sector_memberships.c.sector_id,
                    schema.sector_memberships.c.vt_symbol,
                ).where(schema.sector_memberships.c.sector_id.in_(cand_ids))
            ).all()
            for sid, vsym in member_rows:
                cand_members.setdefault(str(sid), set()).add(str(vsym))

        # 候选同期 return_pct + fund_score（按共同日期自动对齐，候选仅需 ≥3 个共同点）
        candidate_maps: dict[str, dict[Any, float]] = {}
        candidate_fund_maps: dict[str, dict[Any, float]] = {}
        if cand_ids:
            score_rows = session.execute(
                select(
                    schema.sector_period_scores.c.sector_id,
                    schema.sector_period_scores.c.as_of_date,
                    schema.sector_period_scores.c.return_pct,
                    schema.sector_period_scores.c.fund_score,
                ).where(
                    schema.sector_period_scores.c.sector_id.in_(cand_ids),
                    schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
                    schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE,
                    schema.sector_period_scores.c.as_of_date.in_(tgt_dates),
                )
            ).all()
            for sid, d, ret, fund in score_rows:
                if ret is not None:
                    candidate_maps.setdefault(sid, {})[d] = float(ret)
                if fund is not None:
                    candidate_fund_maps.setdefault(sid, {})[d] = float(fund)

        relation_groups = {
            sid: _sector_relation_group(sectors_meta.get(sid, {}))
            for sid in cand_ids
        }
        items = compute_relations_aligned(
            target_map=target_map,
            candidate_maps=candidate_maps,
            target_fund_map=target_fund_map if target_fund_map else None,
            candidate_fund_maps=candidate_fund_maps if candidate_fund_maps else None,
            target_members=tgt_members,
            candidate_members=cand_members,
            relation_groups=relation_groups,
            target_relation_group=_sector_relation_group(sectors_meta.get(sector_id, {})),
            min_points=3,
            top_n=limit,
        )
        for it in items:
            meta = sectors_meta.get(it["sector_id"], {})
            it["name"] = meta.get("name", it["sector_id"])
            it["relation_group"] = relation_groups.get(it["sector_id"], it.get("relation_group") or "theme")

    return ok({
        "target": sector_id,
        "target_date": str(date),
        "items": items,
        "status": "ready",
        "algorithm": {
            "name": "mainline_replay_relation_v2",
            "window_days": _WINDOW_DAYS,
            "basis": "sector_period_scores return_pct/fund_score aligned by common dates + full sector_memberships Jaccard",
            "candidate_basis": "shared constituents plus active scored concepts in the replay window",
        },
    })


# ── helpers ──


def _load_sectors_meta(session) -> dict[str, dict[str, Any]]:
    rows = session.execute(
        select(
            schema.sectors.c.id,
            schema.sectors.c.name,
            schema.sectors.c.type,
            schema.sectors.c.category,
            schema.sectors.c.path,
        )
    ).all()
    return {
        r[0]: {"name": r[1], "type": r[2], "category": r[3], "path": r[4]}
        for r in rows
    }


def _sector_relation_group(meta: dict[str, Any]) -> str:
    sector_type = str(meta.get("type") or "").lower()
    if sector_type == "industry":
        return "industry"
    if sector_type == "region":
        return "region"
    name = str(meta.get("name") or "")
    category = str(meta.get("category") or "")
    path_text = " ".join(str(v) for v in (meta.get("path") or []))
    text = f"{name} {category} {path_text}".lower()
    if any(keyword.lower() in text for keyword in _STYLE_STATUS_KEYWORDS):
        return "style_status"
    return "theme"


def _is_mainline_concept_meta(meta: dict[str, Any]) -> bool:
    return str(meta.get("type") or "").lower() == _MAINLINE_SECTOR_TYPE and _sector_relation_group(meta) == "theme"


def _latest_concept_flow_date(session) -> Any:
    return session.execute(
        select(func.max(schema.sector_fund_flows.c.trade_date))
        .select_from(schema.sector_fund_flows)
        .join(schema.sectors, schema.sectors.c.id == schema.sector_fund_flows.c.sector_id)
        .where(schema.sectors.c.type == _MAINLINE_SECTOR_TYPE)
    ).scalar()


def _latest_complete_daily_date(session) -> date | None:
    return _latest_complete_daily_date_at_or_before(session, None)


def _latest_complete_daily_date_at_or_before(session, d: date | None) -> date | None:
    stmt = (
        select(schema.stock_daily_bars.c.trade_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(func.count() >= _MIN_COMPLETE_DAILY_SYMBOL_COUNT)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(1)
    )
    if d is not None:
        stmt = stmt.where(schema.stock_daily_bars.c.trade_date <= d)
    row = session.execute(
        stmt
    ).first()
    return row[0] if row else None


def _parse_optional_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return _parse_date(str(value))
    except Exception:
        return None


def _resolve_sentiment_cycle_date(session, requested: date | None) -> date | None:
    if requested is not None:
        return requested
    latest_flow_date = _parse_optional_date(_latest_concept_flow_date(session))
    if latest_flow_date is not None:
        return latest_flow_date
    return _latest_complete_daily_date(session)


def _sentiment_history_for_request(
    session,
) -> tuple[date | None, list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    """Return the newest persisted curve without making a request wait for rebuild.

    A daily-bar revision invalidates the persisted revision.  When an older curve
    exists it remains usable while one background task rebuilds it; an empty
    cache returns ``building`` so the client can retry shortly instead of holding
    its HTTP connection during a full-market scan.
    """
    latest_anchor = _latest_complete_daily_date_at_or_before(session, None)
    if latest_anchor is None:
        return None, [], {}, "empty"
    source_revision = _sentiment_source_revision(session)
    memory_key = (latest_anchor.isoformat(), _iso_or_none(source_revision) or "")
    memory_value = _load_sentiment_history_memory(memory_key)
    if memory_value is not None:
        points, symbol_state = memory_value
        return latest_anchor, points, symbol_state, "ready"

    persisted = _load_persisted_sentiment_history(session)
    if persisted is not None:
        cached_anchor, cached_revision, points, symbol_state = persisted
        if cached_anchor == latest_anchor and _same_sentiment_revision(cached_revision, source_revision):
            _remember_sentiment_history(memory_key, points, symbol_state)
            return cached_anchor, points, symbol_state, "ready"
        _schedule_sentiment_history_refresh()
        return cached_anchor, points, symbol_state, "refreshing"

    _schedule_sentiment_history_refresh()
    return latest_anchor, [], {}, "building"


def _sentiment_source_revision(session) -> Any:
    """Use the newest daily-bar write as a cheap cross-process cache revision."""
    return session.execute(select(func.max(schema.stock_daily_bars.c.updated_at))).scalar()


def _load_persisted_sentiment_history(
    session,
) -> tuple[date, Any, list[dict[str, Any]], dict[str, dict[str, Any]]] | None:
    table = schema.mainline_sentiment_history
    row = session.execute(
        select(
            table.c.anchor_date,
            table.c.source_updated_at,
            table.c.points,
            table.c.symbol_state,
        ).where(table.c.id == 1)
    ).mappings().first()
    if row is None:
        return None
    anchor = _parse_optional_date(row.get("anchor_date"))
    raw_points = row.get("points")
    raw_state = row.get("symbol_state")
    if anchor is None or not isinstance(raw_points, list) or not isinstance(raw_state, dict):
        return None
    points = [dict(point) for point in raw_points if isinstance(point, dict)]
    symbol_state = {
        str(vt_symbol): dict(state)
        for vt_symbol, state in raw_state.items()
        if isinstance(state, dict)
    }
    return anchor, row.get("source_updated_at"), points, symbol_state


def _load_sentiment_history_memory(
    key: tuple[str, str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]] | None:
    with _SENTIMENT_HISTORY_LOCK:
        return _SENTIMENT_HISTORY_CACHE.get(key)


def _remember_sentiment_history(
    key: tuple[str, str],
    points: list[dict[str, Any]],
    symbol_state: dict[str, dict[str, Any]],
) -> None:
    with _SENTIMENT_HISTORY_LOCK:
        _SENTIMENT_HISTORY_CACHE.clear()
        _SENTIMENT_HISTORY_CACHE[key] = (points, symbol_state)


def _same_sentiment_revision(left: Any, right: Any) -> bool:
    return _iso_or_none(left) == _iso_or_none(right)


def _schedule_sentiment_history_refresh() -> None:
    """Start at most one local rebuild; callers always remain non-blocking."""
    global _SENTIMENT_REFRESH_RUNNING
    with _SENTIMENT_REFRESH_LOCK:
        if _SENTIMENT_REFRESH_RUNNING:
            return
        _SENTIMENT_REFRESH_RUNNING = True

    def _refresh() -> None:
        global _SENTIMENT_REFRESH_RUNNING
        try:
            rebuild_mainline_sentiment_history_cache()
        except Exception as exc:  # noqa: BLE001 - a later request can retry
            logger.warning("mainline sentiment history refresh failed: %s", exc.__class__.__name__)
        finally:
            with _SENTIMENT_REFRESH_LOCK:
                _SENTIMENT_REFRESH_RUNNING = False

    threading.Thread(
        target=_refresh,
        name="mainline-sentiment-history-refresh",
        daemon=True,
    ).start()


def rebuild_mainline_sentiment_history_cache() -> dict[str, Any]:
    """Rebuild and persist the complete sentiment curve after daily-bar sync."""
    with session_scope() as session:
        return _rebuild_mainline_sentiment_history_cache(session)


def _rebuild_mainline_sentiment_history_cache(session) -> dict[str, Any]:
    anchor = _latest_complete_daily_date_at_or_before(session, None)
    if anchor is None:
        return {"status": "empty", "rows_read": 0, "rows_written": 0}
    source_revision_before = _sentiment_source_revision(session)
    dates = _complete_stock_trade_dates(session, anchor, _SENTIMENT_HISTORY_SPAN_DAYS)
    if not dates:
        return {"status": "empty", "rows_read": 0, "rows_written": 0}

    points, symbol_state = _build_sentiment_cycle_points(
        _load_sentiment_daily_rows(session, dates),
        dates,
    )
    source_revision_after = _sentiment_source_revision(session)
    latest_anchor = _latest_complete_daily_date_at_or_before(session, None)
    if latest_anchor != anchor or not _same_sentiment_revision(source_revision_before, source_revision_after):
        return {
            "status": "stale",
            "rows_read": sum(int(point.get("total_stocks") or 0) for point in points),
            "rows_written": 0,
            "message": "日线同步仍在写入，等待下一次重建",
        }

    _save_persisted_sentiment_history(
        session,
        anchor=anchor,
        source_revision=source_revision_after,
        points=points,
        symbol_state=symbol_state,
        history_span_days=len(dates),
    )
    _remember_sentiment_history(
        (anchor.isoformat(), _iso_or_none(source_revision_after) or ""),
        points,
        symbol_state,
    )
    _clear_sentiment_response_cache()
    return {
        "status": "ready",
        "anchor_date": anchor.isoformat(),
        "history_days": len(dates),
        "rows_read": sum(int(point.get("total_stocks") or 0) for point in points),
        "rows_written": len(points),
    }


def _save_persisted_sentiment_history(
    session,
    *,
    anchor: date,
    source_revision: Any,
    points: list[dict[str, Any]],
    symbol_state: dict[str, dict[str, Any]],
    history_span_days: int,
) -> None:
    table = schema.mainline_sentiment_history
    values = {
        "anchor_date": anchor,
        "source_updated_at": source_revision,
        "history_span_days": history_span_days,
        "points": points,
        "symbol_state": symbol_state,
        "computed_at": func.now(),
    }
    exists = session.execute(select(table.c.id).where(table.c.id == 1)).first()
    if exists is None:
        session.execute(table.insert().values(id=1, **values))
        return
    session.execute(table.update().where(table.c.id == 1).values(**values))


def _clear_sentiment_response_cache() -> None:
    for key in list(_RESPONSE_CACHE):
        if key and key[0] == "mainline_replay.sentiment_cycle":
            _RESPONSE_CACHE.pop(key, None)


def _complete_stock_trade_dates(session, end_date: date, limit: int) -> list[date]:
    rows = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .where(schema.stock_daily_bars.c.trade_date <= end_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(func.count() >= _MIN_COMPLETE_DAILY_SYMBOL_COUNT)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(limit)
    ).all()
    return sorted([r[0] for r in rows])


def _load_sentiment_daily_rows(session, dates: list[date]) -> Iterable[Any]:
    if not dates:
        return ()
    bars = schema.stock_daily_bars
    statement = (
        select(
            bars.c.vt_symbol,
            schema.stocks.c.name,
            bars.c.trade_date,
            bars.c.close_price,
            bars.c.high_price,
            bars.c.change_pct,
        )
        .select_from(bars)
        .outerjoin(schema.stocks, schema.stocks.c.vt_symbol == bars.c.vt_symbol)
        .where(bars.c.trade_date.between(dates[0], dates[-1]))
        .order_by(bars.c.trade_date, bars.c.vt_symbol)
        .execution_options(stream_results=True)
    )
    return session.execute(statement).yield_per(_SENTIMENT_SCAN_BATCH_SIZE)


def _build_sentiment_cycle_points(
    rows: Iterable[Any],
    output_dates: list[date],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    output_set = set(output_dates)
    metrics_by_date = {d: _empty_sentiment_metrics(d) for d in output_dates}
    symbol_state: dict[str, dict[str, Any]] = {}

    for row in rows:
        vt_symbol, stock_name, trade_date, close_price, high_price, change_pct = row
        if close_price is None:
            continue
        vt_symbol = str(vt_symbol)
        stock_name = str(stock_name or "")
        close = float(close_price)
        state = symbol_state.get(vt_symbol, {})
        previous_close = _float_or_none(state.get("previous_close"))
        previous_streak = int(state.get("limit_up_streak") or 0)
        change = _float_or_none(change_pct)
        if change is None and previous_close:
            change = (close / previous_close - 1) * 100
        high_change = None
        if high_price is not None and previous_close:
            high_change = (float(high_price) / previous_close - 1) * 100

        threshold = _limit_up_threshold(vt_symbol, stock_name)
        is_limit_up = change is not None and change >= threshold
        is_limit_down = change is not None and change <= -threshold
        touched_limit_up = high_change is not None and high_change >= threshold

        if trade_date in output_set and change is not None:
            metrics = metrics_by_date[trade_date]
            _add_sentiment_sample(
                metrics,
                change=change,
                is_limit_up=is_limit_up,
                is_limit_down=is_limit_down,
                touched_limit_up=touched_limit_up,
                previous_streak=previous_streak,
            )

        symbol_state[vt_symbol] = {
            "previous_close": close,
            "limit_up_streak": previous_streak + 1 if is_limit_up else 0,
            "stock_name": stock_name,
        }

    points = [_finalize_sentiment_metrics(metrics_by_date[d]) for d in output_dates]
    _attach_sentiment_score_changes(points)
    return points, symbol_state


def _empty_sentiment_metrics(trade_date: date) -> dict[str, Any]:
    return {
        "date": trade_date,
        "total_stocks": 0,
        "rise_count": 0,
        "fall_count": 0,
        "flat_count": 0,
        "limit_up_count": 0,
        "limit_down_count": 0,
        "failed_limit_up_count": 0,
        "previous_limit_up_count": 0,
        "promoted_limit_up_count": 0,
        "max_limit_up_streak": 0,
        # ── v2 影子指标累计器（不进 score，只观察）──
        "prev_lu_change_sum": 0.0,  # 昨日涨停股今日涨幅合计（打板溢价）
        "prev_lu_rise_count": 0,  # 昨日涨停股今日上涨家数（打板赚钱面）
        "tier1_base": 0,  # 昨日首板数（一进二分母）
        "tier1_promoted": 0,  # 昨日首板今日续板数
        "tier2_base": 0,  # 昨日二板数（二进三分母）
        "tier2_promoted": 0,
        "tierh_base": 0,  # 昨日 3 板及以上数（高标分母）
        "tierh_promoted": 0,
        "consecutive_limit_up_count": 0,  # 今日连板（streak≥2）家数
        "temporary": False,
    }


def _add_sentiment_sample(
    metrics: dict[str, Any],
    *,
    change: float,
    is_limit_up: bool,
    is_limit_down: bool,
    touched_limit_up: bool,
    previous_streak: int,
) -> None:
    metrics["total_stocks"] += 1
    if change > 0:
        metrics["rise_count"] += 1
    elif change < 0:
        metrics["fall_count"] += 1
    else:
        metrics["flat_count"] += 1

    if previous_streak >= 1:
        metrics["previous_limit_up_count"] += 1
        # v2 影子：打板溢价（昨日涨停股今日表现）
        metrics["prev_lu_change_sum"] += change
        if change > 0:
            metrics["prev_lu_rise_count"] += 1
        # v2 影子：梯队晋级分母（一进二 / 二进三 / 高标）
        if previous_streak == 1:
            metrics["tier1_base"] += 1
        elif previous_streak == 2:
            metrics["tier2_base"] += 1
        else:
            metrics["tierh_base"] += 1

    if is_limit_up:
        metrics["limit_up_count"] += 1
        next_streak = previous_streak + 1
        metrics["max_limit_up_streak"] = max(metrics["max_limit_up_streak"], next_streak)
        if previous_streak >= 1:
            metrics["promoted_limit_up_count"] += 1
            metrics["consecutive_limit_up_count"] += 1
            # v2 影子：梯队晋级分子
            if previous_streak == 1:
                metrics["tier1_promoted"] += 1
            elif previous_streak == 2:
                metrics["tier2_promoted"] += 1
            else:
                metrics["tierh_promoted"] += 1
    elif touched_limit_up:
        metrics["failed_limit_up_count"] += 1

    if is_limit_down:
        metrics["limit_down_count"] += 1


def _finalize_sentiment_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    total = int(metrics["total_stocks"])
    limit_up = int(metrics["limit_up_count"])
    failed = int(metrics["failed_limit_up_count"])
    previous_limit_up = int(metrics["previous_limit_up_count"])
    promoted = int(metrics["promoted_limit_up_count"])
    up_ratio = metrics["rise_count"] / total if total else None
    down_ratio = metrics["fall_count"] / total if total else None
    limit_up_rate = limit_up / total if total else None
    limit_down_rate = metrics["limit_down_count"] / total if total else None
    failed_rate = failed / (failed + limit_up) if (failed + limit_up) else None
    promotion_rate = promoted / previous_limit_up if previous_limit_up else None
    score = _sentiment_score(
        up_ratio=up_ratio,
        down_ratio=down_ratio,
        limit_up_count=limit_up,
        limit_down_count=int(metrics["limit_down_count"]),
        max_streak=int(metrics["max_limit_up_streak"]),
        failed_rate=failed_rate,
        promotion_rate=promotion_rate,
    )
    phase = _sentiment_phase(
        score=score,
        up_ratio=up_ratio,
        down_ratio=down_ratio,
        limit_up_count=limit_up,
        limit_down_count=int(metrics["limit_down_count"]),
        max_streak=int(metrics["max_limit_up_streak"]),
        failed_rate=failed_rate,
        promotion_rate=promotion_rate,
    )
    return {
        "date": metrics["date"].isoformat(),
        "score": round(score, 1),
        "score_change": None,
        "phase": phase,
        "phase_label": _sentiment_phase_label(phase),
        "total_stocks": total,
        "rise_count": int(metrics["rise_count"]),
        "fall_count": int(metrics["fall_count"]),
        "flat_count": int(metrics["flat_count"]),
        "up_ratio": _round4(up_ratio),
        "down_ratio": _round4(down_ratio),
        "limit_up_count": limit_up,
        "limit_down_count": int(metrics["limit_down_count"]),
        "limit_up_rate": _round4(limit_up_rate),
        "limit_down_rate": _round4(limit_down_rate),
        "failed_limit_up_count": failed,
        "failed_limit_up_rate": _round4(failed_rate),
        "max_limit_up_streak": int(metrics["max_limit_up_streak"]),
        "previous_limit_up_count": previous_limit_up,
        "promoted_limit_up_count": promoted,
        "promotion_rate": _round4(promotion_rate),
        "shadow": _sentiment_shadow_metrics(metrics, previous_limit_up),
        "temporary": bool(metrics.get("temporary")),
    }


def _sentiment_shadow_metrics(metrics: dict[str, Any], previous_limit_up: int) -> dict[str, Any]:
    """v2 影子指标（观察用，不进 score）：
    - 打板溢价：昨日涨停股今日平均涨幅 / 上涨占比
    - 梯队晋级率：一进二 / 二进三 / 高标（昨日 3 板+）分层
    - 连板家数：今日 streak≥2 的广度
    """
    tier1_base = int(metrics["tier1_base"])
    tier2_base = int(metrics["tier2_base"])
    tierh_base = int(metrics["tierh_base"])
    return {
        "prev_limit_up_avg_change": (
            round(metrics["prev_lu_change_sum"] / previous_limit_up, 2)
            if previous_limit_up else None
        ),
        "prev_limit_up_rise_ratio": (
            _round4(metrics["prev_lu_rise_count"] / previous_limit_up)
            if previous_limit_up else None
        ),
        "promotion_1to2_rate": (
            _round4(metrics["tier1_promoted"] / tier1_base) if tier1_base else None
        ),
        "promotion_2to3_rate": (
            _round4(metrics["tier2_promoted"] / tier2_base) if tier2_base else None
        ),
        "promotion_high_rate": (
            _round4(metrics["tierh_promoted"] / tierh_base) if tierh_base else None
        ),
        "tier_samples": {"1to2": tier1_base, "2to3": tier2_base, "high": tierh_base},
        "consecutive_limit_up_count": int(metrics["consecutive_limit_up_count"]),
    }


def _sentiment_score(
    *,
    up_ratio: float | None,
    down_ratio: float | None,
    limit_up_count: int,
    limit_down_count: int,
    max_streak: int,
    failed_rate: float | None,
    promotion_rate: float | None,
) -> float:
    if up_ratio is None:
        return 0.0
    failed_quality = 1 - min(max(failed_rate if failed_rate is not None else 0.25, 0.0), 1.0)
    risk_quality = 1 - min(limit_down_count / 50, 1.0)
    score = 100 * (
        0.28 * up_ratio
        + 0.22 * min(limit_up_count / 100, 1.0)
        + 0.18 * min(max_streak / 7, 1.0)
        + 0.14 * min(max(promotion_rate if promotion_rate is not None else 0.35, 0.0), 1.0)
        + 0.10 * failed_quality
        + 0.08 * risk_quality
    )
    score -= min(limit_down_count / 80, 1.0) * 12
    if down_ratio is not None:
        score -= max(0.0, down_ratio - up_ratio) * 12
    return max(0.0, min(100.0, score))


def _sentiment_phase(
    *,
    score: float,
    up_ratio: float | None,
    down_ratio: float | None,
    limit_up_count: int,
    limit_down_count: int,
    max_streak: int,
    failed_rate: float | None,
    promotion_rate: float | None,
) -> str:
    failed = failed_rate if failed_rate is not None else 0.0
    if limit_down_count >= 80 or (down_ratio is not None and down_ratio >= 0.70 and score < 45):
        return "ice"
    if score >= 72 and limit_up_count >= 50 and max_streak >= 3 and failed <= 0.42 and limit_down_count < 30:
        return "climax"
    if limit_down_count >= 30:
        return "divergence"
    if failed >= 0.45 and (limit_up_count >= 20 or score >= 50):
        return "divergence"
    if promotion_rate is not None and promotion_rate < 0.18 and limit_up_count >= 30:
        return "divergence"
    if score >= 55:
        return "repair"
    if score >= 38:
        return "repair"
    return "ebb"


def _sentiment_phase_label(phase: str) -> str:
    return {
        "ice": "冰点",
        "repair": "修复",
        "divergence": "分歧",
        "climax": "高潮",
        "ebb": "退潮",
    }.get(phase, "未知")


def _attach_sentiment_score_changes(points: list[dict[str, Any]]) -> None:
    previous: float | None = None
    for point in points:
        score = _float_or_none(point.get("score"))
        point["score_change"] = round(score - previous, 1) if score is not None and previous is not None else None
        previous = score


def _build_live_sentiment_point(
    session,
    d: date,
    symbol_state: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], datetime | None] | None:
    rows = session.execute(
        select(
            schema.stocks.c.vt_symbol,
            schema.stocks.c.name,
            schema.stocks.c.last_price,
            schema.stocks.c.change_pct,
        )
        .where(schema.stocks.c.change_pct.isnot(None))
        .where(schema.stocks.c.last_price.isnot(None))
    ).all()
    if not rows:
        return None

    high_map, latest_minute_time = _load_live_high_map(session, d)
    metrics = _empty_sentiment_metrics(d)
    metrics["temporary"] = True

    for vt_symbol, stock_name, last_price, change_pct in rows:
        vt_symbol = str(vt_symbol)
        stock_name = str(stock_name or "")
        change = _float_or_none(change_pct)
        if change is None:
            continue
        state = symbol_state.get(vt_symbol, {})
        previous_close = _float_or_none(state.get("previous_close"))
        previous_streak = int(state.get("limit_up_streak") or 0)
        threshold = _limit_up_threshold(vt_symbol, stock_name)
        high_change = None
        if previous_close and vt_symbol in high_map:
            high_change = (high_map[vt_symbol] / previous_close - 1) * 100
        is_limit_up = change >= threshold
        is_limit_down = change <= -threshold
        touched_limit_up = high_change is not None and high_change >= threshold
        _add_sentiment_sample(
            metrics,
            change=change,
            is_limit_up=is_limit_up,
            is_limit_down=is_limit_down,
            touched_limit_up=touched_limit_up,
            previous_streak=previous_streak,
        )

    return _finalize_sentiment_metrics(metrics), latest_minute_time


def _load_live_high_map(session, d: date) -> tuple[dict[str, float], datetime | None]:
    """Load intraday highs and latest bar time with one date-scoped aggregation."""
    rows = session.execute(
        select(
            schema.stock_minute_bars.c.vt_symbol,
            func.max(schema.stock_minute_bars.c.high_price).label("high_price"),
            func.max(schema.stock_minute_bars.c.bar_time).label("latest_bar_time"),
        )
        .where(
            schema.stock_minute_bars.c.trade_date == d,
            schema.stock_minute_bars.c.interval == "1m",
        )
        .group_by(schema.stock_minute_bars.c.vt_symbol)
    ).all()
    out: dict[str, float] = {}
    latest_bar_time: datetime | None = None
    for vt_symbol, high_price, bar_time in rows:
        value = _float_or_none(high_price)
        if value is not None:
            out[str(vt_symbol)] = value
        if isinstance(bar_time, datetime) and (latest_bar_time is None or bar_time > latest_bar_time):
            latest_bar_time = bar_time
    return out, latest_bar_time


def _sentiment_ranges(points: list[dict[str, Any]], lookback: int) -> list[dict[str, Any]]:
    windows = []
    for days in (5, 20, lookback):
        if days not in windows:
            windows.append(days)
    ranges: list[dict[str, Any]] = []
    for days in windows:
        subset = points[-days:] if days < len(points) else points[:]
        if not subset:
            continue
        scores = [_float_or_none(p.get("score")) for p in subset]
        scores = [s for s in scores if s is not None]
        if not scores:
            continue
        phase_counts: dict[str, int] = {}
        for point in subset:
            phase = str(point.get("phase") or "unknown")
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
        dominant_phase = max(phase_counts.items(), key=lambda item: item[1])[0]
        ranges.append({
            "label": f"近{min(days, len(subset))}日",
            "days": len(subset),
            "start_date": subset[0]["date"],
            "end_date": subset[-1]["date"],
            "min_score": round(min(scores), 1),
            "max_score": round(max(scores), 1),
            "avg_score": round(sum(scores) / len(scores), 1),
            "score_change": round(scores[-1] - scores[0], 1) if len(scores) >= 2 else None,
            "dominant_phase": dominant_phase,
            "dominant_phase_label": _sentiment_phase_label(dominant_phase),
        })
    return ranges


def _round4(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _enrich_concept_index_context(
    session,
    ranking: list[dict[str, Any]],
    d: date,
    *,
    include_live_projection: bool,
) -> None:
    sector_ids = [str(item["sector_id"]) for item in ranking if item.get("sector_id")]
    if not sector_ids:
        return

    histories = _load_concept_index_histories(session, sector_ids, d)
    activity = _load_concept_activity(session, sector_ids, d)
    rolling = _rolling_board_stats(histories, d)
    for item in ranking:
        sector_id = str(item["sector_id"])
        points = histories.get(sector_id, [])
        if include_live_projection:
            points = _with_live_index_projection(points, item, d)
        stats = activity.get(sector_id, _empty_activity_stats())
        visible_points = points[-_CONCEPT_INDEX_POINTS:]
        item["index_points"] = visible_points
        item["index_change_pct"] = _index_change_pct(visible_points)
        item["continuation_days"] = stats["continuation_days"]
        item["activity_days_20"] = stats["activity_days_20"]
        item["activity_ratio_20"] = stats["activity_ratio_20"]
        # live/history（有 data_mode）走量价派发判定；delta/无 data_mode 保留 hot/cold
        item["continuation_status"] = _continuation_status(item, stats, bool(item.get("data_mode")))
        item["previous_hot"] = stats["previous_hot"]
        rolling_stats = rolling.get(sector_id, _empty_rolling_board_stats())
        item["rolling_board_count"] = rolling_stats["count"]
        item["rolling_board_dates"] = rolling_stats["dates"]
        item["rolling_board_avg_change_pct"] = rolling_stats["avg_change_pct"]


def _load_concept_index_histories(session, sector_ids: list[str], d: date) -> dict[str, list[dict[str, Any]]]:
    rows = session.execute(
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.change_pct,
            schema.sector_daily_bars.c.turnover,
        )
        .where(
            schema.sector_daily_bars.c.sector_id.in_(sector_ids),
            schema.sector_daily_bars.c.trade_date <= d,
            schema.sector_daily_bars.c.trade_date >= d - timedelta(days=_CONCEPT_INDEX_LOOKBACK_DAYS),
        )
        .order_by(schema.sector_daily_bars.c.sector_id, schema.sector_daily_bars.c.trade_date)
    ).all()

    histories: dict[str, list[dict[str, Any]]] = {}
    for sector_id, trade_date, close_price, change_pct, turnover in rows:
        histories.setdefault(str(sector_id), []).append({
            "date": _iso_or_none(trade_date),
            "close": close_price,
            "change_pct": change_pct,
            "turnover": turnover,
        })
    return histories


def _load_concept_activity(session, sector_ids: list[str], d: date) -> dict[str, dict[str, Any]]:
    rows = session.execute(
        select(
            schema.sector_period_scores.c.sector_id,
            schema.sector_period_scores.c.as_of_date,
            schema.sector_period_scores.c.heat_score,
            schema.sector_period_scores.c.rank_return,
            schema.sector_period_scores.c.trend_state,
        )
        .where(
            schema.sector_period_scores.c.sector_id.in_(sector_ids),
            schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
            schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE,
            schema.sector_period_scores.c.as_of_date <= d,
        )
        .order_by(schema.sector_period_scores.c.sector_id, schema.sector_period_scores.c.as_of_date.desc())
    ).all()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for sector_id, as_of_date, heat_score, rank_return, trend_state in rows:
        grouped.setdefault(str(sector_id), []).append({
            "date": as_of_date,
            "active": _is_active_score(heat_score, rank_return, trend_state),
        })

    return {
        sector_id: _activity_stats(score_rows)
        for sector_id, score_rows in grouped.items()
    }


def _is_active_score(heat_score: Any, rank_return: Any, trend_state: Any) -> bool:
    if heat_score is not None and float(heat_score) >= _ACTIVE_HEAT_THRESHOLD:
        return True
    if rank_return is not None and int(rank_return) <= _HISTORICAL_HOT_LIMIT:
        return True
    return str(trend_state or "") in {"MAINLINE_UP", "FAST_UP"}


def _activity_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    recent = rows[:_CONCEPT_INDEX_POINTS]
    continuation_days = 0
    for row in recent:
        if not row["active"]:
            break
        continuation_days += 1
    activity_days = sum(1 for row in recent if row["active"])
    return {
        "continuation_days": continuation_days,
        "activity_days_20": activity_days,
        "activity_ratio_20": activity_days / len(recent) if recent else None,
        "previous_hot": bool(recent[1]["active"]) if len(recent) > 1 else False,
        "current_hot": bool(recent[0]["active"]) if recent else False,
    }


def _empty_activity_stats() -> dict[str, Any]:
    return {
        "continuation_days": 0,
        "activity_days_20": 0,
        "activity_ratio_20": None,
        "previous_hot": False,
        "current_hot": False,
    }


def _with_live_index_projection(
    points: list[dict[str, Any]],
    item: dict[str, Any],
    d: date,
) -> list[dict[str, Any]]:
    change_pct = item.get("return_pct")
    if change_pct is None:
        return points
    date_text = d.isoformat()
    if points and points[-1].get("date") == date_text:
        return points
    last_close = points[-1].get("close") if points else None
    projected_close = last_close * (1 + float(change_pct) / 100) if last_close else None
    return points + [{
        "date": date_text,
        "close": projected_close,
        "change_pct": change_pct,
        "turnover": None,
        "temporary": True,
    }]


def _rolling_board_stats(
    histories: dict[str, list[dict[str, Any]]],
    d: date,
) -> dict[str, dict[str, Any]]:
    by_date: dict[str, list[tuple[str, float]]] = {}
    for sector_id, points in histories.items():
        for point in points:
            date_text = str(point.get("date") or "")
            if not date_text:
                continue
            change_pct = point.get("change_pct")
            if change_pct is None:
                continue
            by_date.setdefault(date_text, []).append((sector_id, float(change_pct)))

    recent_dates = sorted(by_date.keys(), reverse=True)[:_ROLLING_BOARD_DAYS]
    appearances: dict[str, list[float]] = {}
    dates: dict[str, list[str]] = {}
    for date_text in recent_dates:
        ranked = sorted(by_date[date_text], key=lambda row: row[1], reverse=True)[:_ROLLING_BOARD_TOP_N]
        for sector_id, change_pct in ranked:
            appearances.setdefault(sector_id, []).append(change_pct)
            dates.setdefault(sector_id, []).append(date_text)

    return {
        sector_id: {
            "count": len(changes),
            "dates": dates.get(sector_id, []),
            "avg_change_pct": sum(changes) / len(changes) if changes else None,
        }
        for sector_id, changes in appearances.items()
    }


def _empty_rolling_board_stats() -> dict[str, Any]:
    return {
        "count": 0,
        "dates": [],
        "avg_change_pct": None,
    }


def _index_change_pct(points: list[dict[str, Any]]) -> float | None:
    if len(points) < 2:
        return None
    first = points[0].get("close")
    last = points[-1].get("close")
    if not first or last is None:
        return None
    return (float(last) / float(first) - 1) * 100


def _continuation_status(item: dict[str, Any], stats: dict[str, Any], is_live: bool) -> str:
    if not is_live:
        return "hot" if stats.get("current_hot") else "cold"
    positive_price = item.get("return_pct") is not None and float(item["return_pct"]) > 0
    # 主力明确净流出视为顶部派发/撤退信号；资金流缺失(None) 不等同于流出，避免数据缺失误降级。
    has_outflow = item.get("main_net_inflow") is not None and float(item["main_net_inflow"]) < 0
    if has_outflow or not positive_price:
        return "broken" if stats.get("current_hot") else "watch"
    return "maintained" if stats.get("current_hot") else "new"


def _fund_flow_map(
    session, d: date, period: str = "即时"
) -> tuple[list[tuple[str, str, float]], int | None]:
    """返回 [(sector_id, name, net_inflow)] 按 period 查（过滤伪概念）。3日/20日累加即时。

    即时/5日/10日：period 字段现成值。3日/20日：SUM(即时) 最近 N 交易日（约11天，actual_days 可能不足）。
    """
    if period in ("即时", "5日", "10日"):
        rows = session.execute(
            select(
                schema.sector_fund_flows.c.sector_id,
                schema.sectors.c.name,
                schema.sectors.c.type,
                schema.sectors.c.category,
                schema.sectors.c.path,
                schema.sector_fund_flows.c.main_net_inflow,
            )
            .join(schema.sectors, schema.sectors.c.id == schema.sector_fund_flows.c.sector_id)
            .where(
                schema.sector_fund_flows.c.trade_date == d.isoformat(),
                schema.sector_fund_flows.c.period == period,
                schema.sectors.c.type == _MAINLINE_SECTOR_TYPE,
            )
        ).all()
        actual_days: int | None = None
    else:
        ndays = 3 if period == "3日" else 20
        dates_rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date)
            .group_by(schema.stock_daily_bars.c.trade_date)
            .having(func.count() >= _MIN_COMPLETE_DAILY_SYMBOL_COUNT)
            .where(schema.stock_daily_bars.c.trade_date <= d)
            .order_by(desc(schema.stock_daily_bars.c.trade_date))
            .limit(ndays)
        ).all()
        dates = [str(r[0]) for r in dates_rows]
        if not dates:
            return [], 0
        # 实际有即时资金流的天数（即时资金流只保留约11天，20日 actual_days 可能 <20）
        actual_days = session.execute(
            select(func.count(func.distinct(schema.sector_fund_flows.c.trade_date)))
            .where(
                schema.sector_fund_flows.c.trade_date.in_(dates),
                schema.sector_fund_flows.c.period == "即时",
            )
        ).scalar() or 0
        rows = session.execute(
            select(
                schema.sector_fund_flows.c.sector_id,
                schema.sectors.c.name,
                schema.sectors.c.type,
                schema.sectors.c.category,
                schema.sectors.c.path,
                func.sum(schema.sector_fund_flows.c.main_net_inflow).label("net"),
            )
            .join(schema.sectors, schema.sectors.c.id == schema.sector_fund_flows.c.sector_id)
            .where(
                schema.sector_fund_flows.c.trade_date.in_(dates),
                schema.sector_fund_flows.c.period == "即时",
                schema.sectors.c.type == _MAINLINE_SECTOR_TYPE,
            )
            .group_by(
                schema.sector_fund_flows.c.sector_id,
                schema.sectors.c.name,
                schema.sectors.c.type,
                schema.sectors.c.category,
                schema.sectors.c.path,
            )
        ).all()
    items = [
        (r[0], r[1], float(r[5]))
        for r in rows
        if r[5] is not None
        and _is_mainline_concept_meta({"name": r[1], "type": r[2], "category": r[3], "path": r[4]})
    ]
    return items, actual_days


def _compute_flow_top(
    session, d: date, period: str = "即时", n: int = 10
) -> dict[str, Any]:
    """概念资金流 top N（流入/流出），独立于 ranking _sort 截断。"""
    items, actual_days = _fund_flow_map(session, d, period)
    items.sort(key=lambda x: x[2], reverse=True)
    inflows = [{"sector_id": s, "name": nm, "net_inflow": net} for s, nm, net in items if net > 0][:n]
    outflows = [{"sector_id": s, "name": nm, "net_inflow": net} for s, nm, net in items if net < 0][-n:][::-1]
    return {"inflows": inflows, "outflows": outflows, "period": period, "actual_days": actual_days}


def _sort_live_concept_ranking(ranking: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        status_weight = {
            "maintained": 3.0,
            "hot": 3.0,
            "new": 2.0,
            "watch": 1.0,
            "broken": 0.0,
            "cold": 0.0,
        }.get(str(item.get("continuation_status") or ""), 0.0)
        rolling_count = float(item.get("rolling_board_count") or 0)
        continuation_days = float(item.get("continuation_days") or 0)
        index_change_pct = float(item.get("index_change_pct") or 0)
        rolling_avg_change_pct = float(item.get("rolling_board_avg_change_pct") or 0)
        heat_score = float(item.get("heat_score") or 0)
        main_net_inflow = float(item.get("main_net_inflow") or 0)
        return (
            status_weight,
            continuation_days,
            index_change_pct,
            rolling_count,
            rolling_avg_change_pct,
            heat_score,
            main_net_inflow,
        )

    return sorted(ranking, key=sort_key, reverse=True)


def _live_message(data_state: str) -> str:
    if data_state == "realtime":
        return "盘中实时：概念资金流走热缓存，页面刷新不写历史库。"
    if data_state == "realtime_delayed":
        return "实时源暂时延迟：继续展示最近一次成功热缓存。"
    return "实时源不可用或未到交易时段：已回退到本地最近历史资金流。"


def _live_flow_top_or_history(
    session,
    d: date,
    period: str,
    realtime_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if period in {"即时", "5日", "10日"}:
        payload = realtime_payload if period == "即时" else None
        if payload is None and _is_mainline_realtime_window():
            try:
                payload = _fetch_live_concept_flow(period)
            except Exception:
                payload = None
        if payload:
            return _compute_flow_top_from_items(payload.get("items") or [], period)
    return _compute_flow_top(session, d, period)


def _compute_flow_top_from_items(items: list[dict[str, Any]], period: str = "即时", n: int = 10) -> dict[str, Any]:
    rows: list[tuple[str, str, float]] = []
    for item in items:
        sector_id = str(item.get("id") or item.get("code") or "")
        name = str(item.get("name") or sector_id)
        net = _float_or_none(item.get("main_net_inflow"))
        if not sector_id or net is None:
            continue
        if not _is_mainline_concept_meta({"name": name, "type": _MAINLINE_SECTOR_TYPE}):
            continue
        rows.append((sector_id, name, net))
    rows.sort(key=lambda item: item[2], reverse=True)
    inflows = [{"sector_id": s, "name": nm, "net_inflow": net} for s, nm, net in rows if net > 0][:n]
    outflows = [{"sector_id": s, "name": nm, "net_inflow": net} for s, nm, net in rows if net < 0][-n:][::-1]
    return {"inflows": inflows, "outflows": outflows, "period": period, "actual_days": None}


def _attach_ranking_context_to_flow_top(
    flow_top: dict[str, Any],
    ranking: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach display context to flow top rows without changing flow ordering.

    The left ranking and the fund-flow strip intentionally use different
    rankings.  But a clicked flow row still needs the same detail payload as a
    ranking row: index curve, continuation state, activity stats, and live fund
    fields.  Keep ``net_inflow`` as the selected period's value.
    """

    return {
        **flow_top,
        "inflows": _attach_ranking_context_to_flow_items(flow_top.get("inflows") or [], ranking),
        "outflows": _attach_ranking_context_to_flow_items(flow_top.get("outflows") or [], ranking),
    }


def _attach_ranking_context_to_flow_items(
    flow_items: list[dict[str, Any]],
    ranking: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranking_by_id = {str(item.get("sector_id")): item for item in ranking if item.get("sector_id")}
    enriched: list[dict[str, Any]] = []
    for flow_item in flow_items:
        sector_id = str(flow_item.get("sector_id") or "")
        context = ranking_by_id.get(sector_id)
        if context is None:
            enriched.append(flow_item)
            continue
        merged = {**context, **flow_item}
        if merged.get("main_net_inflow") is None and flow_item.get("net_inflow") is not None:
            merged["main_net_inflow"] = flow_item["net_inflow"]
        if merged.get("accumulated_main_inflow") is None and flow_item.get("net_inflow") is not None:
            merged["accumulated_main_inflow"] = flow_item["net_inflow"]
        if "fund_inflow_available" not in merged:
            merged["fund_inflow_available"] = flow_item.get("net_inflow") is not None
        enriched.append(merged)
    return enriched


def _live_ranking_from_flow_items(
    session,
    d: date,
    flow_items: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    sector_ids = [
        str(item.get("id") or item.get("code") or "")
        for item in flow_items
        if item.get("id") or item.get("code")
    ]
    sector_ids = list(dict.fromkeys(sector_ids))
    if not sector_ids:
        return []

    meta_by_id = _live_sector_meta(session, sector_ids)
    score_by_id = _latest_score_map(session, sector_ids, d)
    ranking: list[dict[str, Any]] = []
    for item in flow_items:
        sector_id = str(item.get("id") or item.get("code") or "")
        if not sector_id:
            continue
        meta = meta_by_id.get(sector_id, {})
        name = meta.get("name") or item.get("name") or sector_id
        sector_type = meta.get("type") or _MAINLINE_SECTOR_TYPE
        category = meta.get("category")
        path = meta.get("path") or []
        if not _is_mainline_concept_meta({"name": name, "type": sector_type, "category": category, "path": path}):
            continue
        score = score_by_id.get(sector_id, {})
        ranking.append({
            "sector_id": sector_id,
            "name": name,
            "heat_score": score.get("heat_score"),
            "fund_score": score.get("fund_score"),
            "momentum_score": score.get("momentum_score"),
            "trend_state": score.get("trend_state"),
            "rank_return": item.get("rank"),
            "return_pct": item.get("change_pct"),
            "historical_return_pct": score.get("return_pct"),
            "confidence": None,
            "main_net_inflow": item.get("main_net_inflow"),
            "main_net_inflow_ratio": item.get("main_net_inflow_pct"),
            "accumulated_main_inflow": item.get("main_net_inflow"),
            "fund_inflow_available": item.get("main_net_inflow") is not None,
            "stock_count": meta.get("stock_count"),
            "leader_stock": item.get("leader_stock") or meta.get("leader_stock"),
            "leader_change_pct": meta.get("leader_change_pct"),
            "score_date": _iso_or_none(score.get("as_of_date")),
            "flow_updated_at": _now_china().isoformat(),
            "data_mode": "live",
        })
        if len(ranking) >= limit:
            break
    return ranking


def _live_sector_meta(session, sector_ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = session.execute(
        select(
            schema.sectors.c.id,
            schema.sectors.c.name,
            schema.sectors.c.type,
            schema.sectors.c.category,
            schema.sectors.c.path,
            schema.sectors.c.stock_count,
            schema.sectors.c.leader_stock,
            schema.sectors.c.leader_change_pct,
        ).where(schema.sectors.c.id.in_(sector_ids))
    ).all()
    return {
        str(row[0]): {
            "name": row[1],
            "type": row[2],
            "category": row[3],
            "path": row[4],
            "stock_count": row[5],
            "leader_stock": row[6],
            "leader_change_pct": row[7],
        }
        for row in rows
    }


def _latest_score_map(session, sector_ids: list[str], d: date) -> dict[str, dict[str, Any]]:
    latest_scores = (
        select(
            schema.sector_period_scores.c.sector_id,
            func.max(schema.sector_period_scores.c.as_of_date).label("latest_score_date"),
        )
        .where(
            schema.sector_period_scores.c.sector_id.in_(sector_ids),
            schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
            schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE,
            schema.sector_period_scores.c.as_of_date < d,
        )
        .group_by(schema.sector_period_scores.c.sector_id)
    ).subquery()
    rows = session.execute(
        select(
            schema.sector_period_scores.c.sector_id,
            schema.sector_period_scores.c.heat_score,
            schema.sector_period_scores.c.fund_score,
            schema.sector_period_scores.c.momentum_score,
            schema.sector_period_scores.c.trend_state,
            schema.sector_period_scores.c.return_pct,
            schema.sector_period_scores.c.as_of_date,
        )
        .join(
            latest_scores,
            (latest_scores.c.sector_id == schema.sector_period_scores.c.sector_id)
            & (latest_scores.c.latest_score_date == schema.sector_period_scores.c.as_of_date),
        )
    ).all()
    return {
        str(row[0]): {
            "heat_score": row[1],
            "fund_score": row[2],
            "momentum_score": row[3],
            "trend_state": row[4],
            "return_pct": row[5],
            "as_of_date": row[6],
        }
        for row in rows
    }


def _live_ranking_for_date(
    session,
    d: date,
    limit: int,
) -> list[dict[str, Any]]:
    latest_scores = (
        select(
            schema.sector_period_scores.c.sector_id,
            func.max(schema.sector_period_scores.c.as_of_date).label("latest_score_date"),
        )
        .where(
            schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
            schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE,
            schema.sector_period_scores.c.as_of_date < d,
        )
        .group_by(schema.sector_period_scores.c.sector_id)
    ).subquery()

    q = (
        select(
            schema.sector_fund_flows.c.sector_id,
            schema.sector_fund_flows.c.main_net_inflow,
            schema.sector_fund_flows.c.main_net_inflow_ratio,
            schema.sector_fund_flows.c.rank,
            schema.sector_fund_flows.c.updated_at,
            schema.sectors.c.name,
            schema.sectors.c.type,
            schema.sectors.c.category,
            schema.sectors.c.path,
            schema.sectors.c.change_pct,
            schema.sectors.c.stock_count,
            schema.sectors.c.leader_stock,
            schema.sectors.c.leader_change_pct,
            schema.sector_period_scores.c.heat_score,
            schema.sector_period_scores.c.fund_score,
            schema.sector_period_scores.c.momentum_score,
            schema.sector_period_scores.c.trend_state,
            schema.sector_period_scores.c.return_pct,
            schema.sector_period_scores.c.as_of_date.label("score_date"),
        )
        .select_from(schema.sector_fund_flows)
        .join(schema.sectors, schema.sectors.c.id == schema.sector_fund_flows.c.sector_id)
        .outerjoin(latest_scores, latest_scores.c.sector_id == schema.sector_fund_flows.c.sector_id)
        .outerjoin(
            schema.sector_period_scores,
            (schema.sector_period_scores.c.sector_id == schema.sector_fund_flows.c.sector_id)
            & (schema.sector_period_scores.c.period == _DEFAULT_PERIOD)
            & (schema.sector_period_scores.c.as_of_date == latest_scores.c.latest_score_date),
        )
        .where(
            schema.sector_fund_flows.c.trade_date == d.isoformat(),
            schema.sector_fund_flows.c.period == "即时",
            schema.sectors.c.type == _MAINLINE_SECTOR_TYPE,
        )
    )
    rows = session.execute(
        q.order_by(
            desc(schema.sector_fund_flows.c.main_net_inflow),
            schema.sector_fund_flows.c.rank.asc().nulls_last(),
        )
    ).all()

    ranking: list[dict[str, Any]] = []
    for row in rows:
        (
            sector_id,
            main_net_inflow,
            main_net_inflow_ratio,
            rank,
            updated_at,
            name,
            row_sector_type,
            category,
            path,
            change_pct,
            stock_count,
            leader_stock,
            leader_change_pct,
            heat_score,
            fund_score,
            momentum_score,
            trend_state,
            return_pct,
            score_date,
        ) = row
        if not _is_mainline_concept_meta({"name": name, "type": row_sector_type, "category": category, "path": path}):
            continue
        ranking.append({
            "sector_id": sector_id,
            "name": name or sector_id,
            "heat_score": heat_score,
            "fund_score": fund_score,
            "momentum_score": momentum_score,
            "trend_state": trend_state,
            "rank_return": rank,
            "return_pct": change_pct,
            "historical_return_pct": return_pct,
            "confidence": None,
            "main_net_inflow": main_net_inflow,
            "main_net_inflow_ratio": main_net_inflow_ratio,
            "accumulated_main_inflow": main_net_inflow,
            "fund_inflow_available": main_net_inflow is not None,
            "stock_count": stock_count,
            "leader_stock": leader_stock,
            "leader_change_pct": leader_change_pct,
            "score_date": _iso_or_none(score_date),
            "flow_updated_at": _iso_or_none(updated_at),
            "data_mode": "live",
        })
        if len(ranking) >= limit:
            break
    return ranking


def _ranking_for_date(session, d: date, limit: int) -> list[dict[str, Any]]:
    q = (
        select(
            schema.sector_period_scores.c.sector_id,
            schema.sector_period_scores.c.heat_score,
            schema.sector_period_scores.c.fund_score,
            schema.sector_period_scores.c.momentum_score,
            schema.sector_period_scores.c.trend_state,
            schema.sector_period_scores.c.rank_return,
            schema.sector_period_scores.c.return_pct,
            schema.sector_period_scores.c.confidence,
            schema.sectors.c.name,
            schema.sectors.c.type,
            schema.sectors.c.category,
            schema.sectors.c.path,
            schema.sector_fund_flows.c.main_net_inflow,
            schema.sector_fund_flows.c.main_net_inflow_ratio,
        )
        .join(schema.sectors, schema.sectors.c.id == schema.sector_period_scores.c.sector_id)
        .outerjoin(
            schema.sector_fund_flows,
            (schema.sector_fund_flows.c.sector_id == schema.sector_period_scores.c.sector_id)
            & (schema.sector_fund_flows.c.trade_date == d.isoformat())
            & (schema.sector_fund_flows.c.period == "即时"),
        )
        .where(
            schema.sector_period_scores.c.as_of_date == d,
            schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
            schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE,
            schema.sectors.c.type == _MAINLINE_SECTOR_TYPE,
        )
    )
    q = q.order_by(desc(schema.sector_period_scores.c.heat_score))
    rows = session.execute(q).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        (
            sector_id,
            heat_score,
            fund_score,
            momentum_score,
            trend_state,
            rank_return,
            return_pct,
            confidence,
            name,
            sector_type,
            category,
            path,
            main_net_inflow,
            main_net_inflow_ratio,
        ) = row
        if not _is_mainline_concept_meta({"name": name, "type": sector_type, "category": category, "path": path}):
            continue
        out.append({
            "sector_id": sector_id,
            "heat_score": heat_score,
            "fund_score": fund_score,
            "momentum_score": momentum_score,
            "trend_state": trend_state,
            "rank_return": rank_return,
            "return_pct": return_pct,
            "confidence": confidence,
            "main_net_inflow": main_net_inflow,
            "main_net_inflow_ratio": main_net_inflow_ratio,
            "fund_inflow_available": main_net_inflow is not None,
            "data_mode": "history",
        })
        if len(out) >= limit:
            break
    return out


def _ranking_for_range(
    session, t1: date, t2: date, limit: int
) -> list[dict[str, Any]]:
    """区间 delta：取 t1/t2 两日 scores + [t1,t2] 区间 bars 算 raw delta，再批量算 fund_strength。"""
    base = select(schema.sector_period_scores).where(
        schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
        schema.sector_period_scores.c.sector_type == _MAINLINE_SECTOR_TYPE,
        schema.sector_period_scores.c.as_of_date.in_([t1, t2]),
    )
    score_rows = session.execute(base).mappings().all()
    by_sector: dict[str, dict] = {"t1": {}, "t2": {}}
    for r in score_rows:
        d = r["as_of_date"]
        key = "t1" if d == t1 else "t2"
        by_sector[key][r["sector_id"]] = r

    sectors_meta = _load_sectors_meta(session)
    sector_ids = [
        sid
        for sid in set(by_sector["t1"].keys()) & set(by_sector["t2"].keys())
        if _is_mainline_concept_meta(sectors_meta.get(sid, {}))
    ]
    if not sector_ids:
        return []

    bar_rows = session.execute(
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.turnover,
        )
        .where(
            schema.sector_daily_bars.c.sector_id.in_(sector_ids),
            schema.sector_daily_bars.c.trade_date.between(t1, t2),
        )
        .order_by(schema.sector_daily_bars.c.sector_id, schema.sector_daily_bars.c.trade_date)
    ).all()
    bars_by_sector: dict[str, list] = {}
    for sid, d, close, turnover in bar_rows:
        bars_by_sector.setdefault(sid, []).append((d, close, turnover))

    span = (t2 - t1).days or 1
    prev_t0 = t1 - timedelta(days=span)
    prev_rows = session.execute(
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.turnover,
        ).where(
            schema.sector_daily_bars.c.sector_id.in_(sector_ids),
            schema.sector_daily_bars.c.trade_date.between(prev_t0, t1),
        )
    ).all()
    prev_turnover: dict[str, list[float]] = {}
    for sid, turnover in prev_rows:
        prev_turnover.setdefault(sid, []).append(float(turnover or 0.0))

    inflows = _load_range_inflows(session, sector_ids, t1, t2)

    raws: list[dict[str, Any]] = []
    meta_index: list[str] = []
    for sid in sector_ids:
        bars = bars_by_sector.get(sid, [])
        close_t1 = next((c for d, c, t in bars if d == t1), None)
        close_t2 = next((c for d, c, t in bars if d == t2), None)
        range_turnover = [float(t or 0.0) for d, c, t in bars]
        raw = compute_raw_sector_delta(
            bars_t1_close=close_t1,
            bars_t2_close=close_t2,
            range_turnover=range_turnover,
            prev_range_turnover=prev_turnover.get(sid, []),
            score_t1=by_sector["t1"].get(sid),
            score_t2=by_sector["t2"].get(sid),
            range_main_inflow=inflows.get(sid),
        )
        raw["sector_id"] = sid
        raws.append(raw)
        meta_index.append(sid)

    strengths = compute_fund_strength_batch(raws)
    for i, sid in enumerate(meta_index):
        raws[i]["fund_strength"] = strengths[i]
        s2 = by_sector["t2"].get(sid, {})
        raws[i]["heat_score"] = s2.get("heat_score")
        raws[i]["trend_state"] = s2.get("trend_state")

    raws.sort(
        key=lambda r: (r.get("fund_strength") is not None, r.get("fund_strength") or -1),
        reverse=True,
    )
    return raws[:limit]


def _load_range_inflows(
    session, sector_ids: list[str], t1: date, t2: date
) -> dict[str, list[float]]:
    """近端资金流：sector_fund_flows.trade_date 是 String，转成 date 比较。仅返回有数据的。"""
    rows = session.execute(
        select(
            schema.sector_fund_flows.c.sector_id,
            schema.sector_fund_flows.c.trade_date,
            schema.sector_fund_flows.c.main_net_inflow,
        ).where(
            schema.sector_fund_flows.c.sector_id.in_(sector_ids),
            schema.sector_fund_flows.c.period == "即时",
        )
    ).all()
    out: dict[str, list[float]] = {}
    for sid, td, inflow in rows:
        try:
            d = td if isinstance(td, date) else _parse_date(str(td))
        except Exception:
            continue
        if t1 <= d <= t2 and inflow is not None:
            out.setdefault(sid, []).append(float(inflow))
    return out


def _parse_date(s: str) -> date:
    s = str(s).strip()
    return date.fromisoformat(s[:10])


def _load_index(session, d: date) -> list[dict[str, Any]]:
    """大盘指数。stock_daily_bars.change_pct 字段多为 NULL，改从 close 算（今日/前一日-1）。"""
    names = {
        "000001.SSE": "上证指数", "399001.SZSE": "深证成指", "399006.SZSE": "创业板指",
        "000300.SSE": "沪深300", "000905.SSE": "中证500", "000852.SSE": "中证1000",
        "000688.SSE": "科创50",
    }
    today = {
        r[0]: r
        for r in session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.close_price,
                schema.stock_daily_bars.c.turnover,
            ).where(
                schema.stock_daily_bars.c.vt_symbol.in_(_INDEX_VT_SYMBOLS),
                schema.stock_daily_bars.c.trade_date == d,
            )
        ).all()
    }
    out: list[dict[str, Any]] = []
    for vsym in _INDEX_VT_SYMBOLS:
        t = today.get(vsym)
        if not t:
            continue
        close, turnover = t[1], t[2]
        prev = session.execute(
            select(schema.stock_daily_bars.c.close_price)
            .where(
                schema.stock_daily_bars.c.vt_symbol == vsym,
                schema.stock_daily_bars.c.trade_date < d,
            )
            .order_by(schema.stock_daily_bars.c.trade_date.desc())
            .limit(1)
        ).first()
        change_pct = (close / prev[0] - 1) * 100 if (prev and prev[0]) else None
        out.append({
            "vt_symbol": vsym, "name": names.get(vsym, vsym),
            "close": close, "change_pct": change_pct, "turnover": turnover,
        })
    return out


@router.get("/concept-search", response_model=None)
def concept_search(
    q: str = Query(..., min_length=1, description="概念名关键词"),
    trade_date: date = Query(..., description="日期 YYYY-MM-DD"),
    period: str = Query("即时", description="资金流周期：即时/3日/5日/10日/20日"),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    """按名称搜概念，返回匹配概念的资金流，用于搜索定位（CPO/PCB 等不在 top10 的概念）。"""
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})
    with session_scope() as session:
        source_flow_items: list[dict[str, Any]] | None = None
        if trade_date == _now_china().date() and period in {"即时", "5日", "10日"} and _is_mainline_realtime_window():
            try:
                payload = _fetch_live_concept_flow(period)
                source_flow_items = payload.get("items") or []
                items = [
                    (str(item.get("id") or item.get("code") or ""), str(item.get("name") or ""), net)
                    for item in source_flow_items
                    if (net := _float_or_none(item.get("main_net_inflow"))) is not None
                ]
            except Exception:
                items, _ = _fund_flow_map(session, trade_date, period)
        else:
            items, _ = _fund_flow_map(session, trade_date, period)
        q_upper = q.upper()
        matched = [(s, nm, net) for s, nm, net in items if q_upper in nm.upper()]
        matched.sort(key=lambda x: x[2], reverse=True)
        result = [
            {"sector_id": s, "name": nm, "net_inflow": net}
            for s, nm, net in matched[:limit]
        ]
        if result:
            if source_flow_items is not None:
                context_ranking = _live_ranking_from_flow_items(
                    session,
                    trade_date,
                    source_flow_items,
                    _LIVE_RANKING_CANDIDATE_LIMIT,
                )
            else:
                context_ranking = _live_ranking_for_date(session, trade_date, _LIVE_RANKING_CANDIDATE_LIMIT)
            _enrich_concept_index_context(
                session,
                context_ranking,
                trade_date,
                include_live_projection=trade_date == _now_china().date() and _is_mainline_realtime_window(),
            )
            result = _attach_ranking_context_to_flow_items(
                result,
                _sort_live_concept_ranking(context_ranking),
            )
    return ok({"items": result, "q": q, "total": len(matched), "status": "ready"})


@router.get("/sector-stocks", response_model=None)
def sector_stocks(
    sector_id: str = Query(..., description="概念ID"),
    date: date = Query(..., description="回放日期 YYYY-MM-DD"),
    sort_by: str = Query("change_pct", description="change_pct|net_inflow|name"),
    limit: int = Query(50, ge=1, le=200),
    industry_filter: bool = Query(True, description="只保留属概念核心行业的成分股，过滤东财宽泛杂股"),
) -> dict[str, Any]:
    """概念成分股 + 当日涨跌(从close算) + 个股资金流向(近端)，用于排查个股流入流出。

    东财概念成分股定义宽泛（如"半导体概念"含家电/教育/照明），industry_filter=True 时
    只保留属概念核心行业（成分股与 industry 板块重叠 top5）的股票。
    """
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})

    with session_scope() as session:
        members = session.execute(
            select(
                schema.sector_memberships.c.vt_symbol,
                schema.sector_memberships.c.name,
            ).where(schema.sector_memberships.c.sector_id == sector_id)
        ).all()
        if not members:
            return ok({"sector_id": sector_id, "items": [], "status": "no_members"})
        vt_symbols = [m[0] for m in members]
        name_map = {m[0]: m[1] for m in members}
        filtered_out = 0
        if industry_filter:
            # 找概念核心行业（概念成分股与 industry 板块重叠 top5），过滤东财宽泛杂股
            sc = schema.sector_memberships.alias()
            si = schema.sector_memberships.alias()
            core_industry_ids = session.execute(
                select(si.c.sector_id)
                .select_from(sc)
                .join(si, si.c.vt_symbol == sc.c.vt_symbol)
                .join(schema.sectors, schema.sectors.c.id == si.c.sector_id)
                .where(sc.c.sector_id == sector_id, schema.sectors.c.type == "industry")
                .group_by(si.c.sector_id)
                .order_by(desc(func.count()))
                .limit(2)
            ).scalars().all()
            if core_industry_ids:
                valid = set(session.execute(
                    select(schema.sector_memberships.c.vt_symbol)
                    .where(schema.sector_memberships.c.sector_id.in_(core_industry_ids))
                ).scalars().all())
                kept = [s for s in vt_symbols if s in valid]
                filtered_out = len(vt_symbols) - len(kept)
                vt_symbols = kept

        # 历史回放必须使用所选日期日线；今天盘中允许使用股票快照做临时价。
        today_rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.close_price,
            )
            .where(
                schema.stock_daily_bars.c.vt_symbol.in_(vt_symbols),
                schema.stock_daily_bars.c.trade_date == date,
            )
        ).all()
        today_close = {vsym: close for vsym, close in today_rows}
        snapshot_price: dict[str, tuple[float | None, float | None, str | None]] = {}
        if not today_close and _can_use_intraday_snapshot(session, date):
            snapshot_rows = session.execute(
                select(
                    schema.stocks.c.vt_symbol,
                    schema.stocks.c.last_price,
                    schema.stocks.c.change_pct,
                    schema.stocks.c.trade_time,
                ).where(schema.stocks.c.vt_symbol.in_(vt_symbols))
            ).all()
            snapshot_price = {
                vsym: (last_price, change_pct, trade_time)
                for vsym, last_price, change_pct, trade_time in snapshot_rows
                if last_price is not None or change_pct is not None
            }

        prev_rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.close_price,
            )
            .where(
                schema.stock_daily_bars.c.vt_symbol.in_(list(today_close.keys()) or list(snapshot_price.keys())),
                schema.stock_daily_bars.c.trade_date < date,
            )
            .order_by(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date.desc(),
            )
        ).all()
        prev_close: dict[str, float] = {}
        for vsym, close in prev_rows:
            prev_close.setdefault(vsym, close)

        recent_rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
                schema.stock_daily_bars.c.close_price,
                schema.stock_daily_bars.c.change_pct,
            )
            .where(
                schema.stock_daily_bars.c.vt_symbol.in_(vt_symbols),
                schema.stock_daily_bars.c.trade_date >= date - timedelta(days=_STOCK_MOMENTUM_LOOKBACK_DAYS),
                schema.stock_daily_bars.c.trade_date <= date,
            )
            .order_by(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
            )
        ).all()
        recent_bars = _group_recent_stock_bars(recent_rows)
        limit_up_events = _load_recent_limit_up_events(
            session=session,
            vt_symbols=vt_symbols,
            start=date - timedelta(days=_STOCK_MOMENTUM_LOOKBACK_DAYS),
            end=date,
        )

        # 个股资金流（trade_date 是 String，近端覆盖）
        flow_rows = session.execute(
            select(
                schema.stock_fund_flows.c.vt_symbol,
                schema.stock_fund_flows.c.main_net_inflow,
                schema.stock_fund_flows.c.main_net_inflow_ratio,
            ).where(
                schema.stock_fund_flows.c.vt_symbol.in_(vt_symbols),
                schema.stock_fund_flows.c.trade_date == str(date),
                schema.stock_fund_flows.c.period == "即时",
            )
        ).all()
        flow_map = {r[0]: (r[1], r[2]) for r in flow_rows}

        items: list[dict[str, Any]] = []
        for vsym in vt_symbols:
            close_today = today_close.get(vsym)
            snapshot = snapshot_price.get(vsym)
            price_source = "daily_bar" if close_today is not None else None
            trade_time = None
            if close_today is None and snapshot is not None:
                close_today, snapshot_change, trade_time = snapshot
                price_source = "intraday_snapshot"
            else:
                snapshot_change = None
            previous = prev_close.get(vsym)
            change_pct = (
                (close_today / previous - 1) * 100
                if close_today is not None and previous
                else None
            )
            if change_pct is None and snapshot_change is not None:
                change_pct = snapshot_change
            momentum = _recent_stock_momentum(
                vt_symbol=vsym,
                stock_name=name_map.get(vsym, vsym),
                selected_date=date,
                selected_close=close_today,
                selected_change_pct=change_pct,
                daily_bars=recent_bars.get(vsym, []),
                limit_up_event_dates=limit_up_events.get(vsym, set()),
            )
            net, ratio = flow_map.get(vsym, (None, None))
            items.append({
                "vt_symbol": vsym,
                "name": name_map.get(vsym, vsym),
                "close": close_today,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "return_5d": momentum["return_5d"],
                "limit_up_count_5d": momentum["limit_up_count_5d"],
                "price_date": str(date) if close_today is not None else None,
                "price_source": price_source,
                "trade_time": trade_time,
                "main_net_inflow": net,
                "main_net_inflow_ratio": ratio,
                "fund_inflow_available": net is not None,
            })

        if sort_by == "change_pct":
            items.sort(
                key=lambda x: (
                    x["change_pct"] is not None,
                    x["change_pct"] if x["change_pct"] is not None else -1e18,
                ),
                reverse=True,
            )
        elif sort_by == "name":
            items.sort(key=lambda x: x["name"])
        else:  # net_inflow（默认：主力净流入降序，None 在后）
            items.sort(
                key=lambda x: (
                    x["main_net_inflow"] is not None,
                    x["main_net_inflow"] if x["main_net_inflow"] is not None else -1e18,
                ),
                reverse=True,
            )

    return ok({
        "sector_id": sector_id,
        "date": str(date),
        "items": items[:limit],
        "total": len(items),
        "fund_flow_available": sum(1 for it in items if it["fund_inflow_available"]),
        "filtered_out": filtered_out,
        "price_source": "daily_bar" if today_close else "intraday_snapshot" if snapshot_price else None,
        "status": "ready",
    })


def _load_recent_limit_up_events(session, vt_symbols: list[str], start: date, end: date) -> dict[str, set[date]]:
    if not vt_symbols:
        return {}
    event_dates = _event_date_keys_between(start, end)
    rows = session.execute(
        select(
            schema.stock_events.c.vt_symbol,
            schema.stock_events.c.event_date,
        ).where(
            schema.stock_events.c.vt_symbol.in_(vt_symbols),
            schema.stock_events.c.event_type == "limit_pool_zt",
            schema.stock_events.c.event_date.in_(event_dates),
        )
    ).all()
    grouped: dict[str, set[date]] = {}
    for vt_symbol, event_date in rows:
        parsed_date = _parse_stock_event_date(event_date)
        if parsed_date is not None:
            grouped.setdefault(str(vt_symbol), set()).add(parsed_date)
    return grouped


def _event_date_keys_between(start: date, end: date) -> list[str]:
    keys: list[str] = []
    current = start
    while current <= end:
        keys.append(current.isoformat())
        keys.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return keys


def _parse_stock_event_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 8 and raw.isdigit():
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        return _parse_date(raw)
    except Exception:
        return None


def _group_recent_stock_bars(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for vsym, trade_date, close_price, change_pct in rows:
        if close_price is None:
            continue
        grouped.setdefault(str(vsym), []).append({
            "trade_date": trade_date,
            "close": float(close_price),
            "change_pct": float(change_pct) if change_pct is not None else None,
        })
    return grouped


def _recent_stock_momentum(
    *,
    vt_symbol: str,
    stock_name: str,
    selected_date: date,
    selected_close: float | None,
    selected_change_pct: float | None,
    daily_bars: list[dict[str, Any]],
    limit_up_event_dates: set[date],
) -> dict[str, Any]:
    if selected_close is None:
        return {"return_5d": None, "limit_up_count_5d": 0}

    bars = [bar for bar in daily_bars if bar["trade_date"] <= selected_date]
    if bars and bars[-1]["trade_date"] == selected_date:
        bars[-1] = {
            **bars[-1],
            "close": float(selected_close),
            "change_pct": selected_change_pct,
        }
    else:
        bars.append({
            "trade_date": selected_date,
            "close": float(selected_close),
            "change_pct": selected_change_pct,
        })
    bars = bars[-6:]

    return_5d = None
    if len(bars) >= 6 and bars[-6]["close"] > 0:
        return_5d = round((bars[-1]["close"] / bars[-6]["close"] - 1) * 100, 2)

    changes = _derived_stock_changes(bars)
    threshold = _limit_up_threshold(vt_symbol, stock_name)
    recent_pairs = zip(bars[-5:], changes[-5:])
    limit_up_count_5d = sum(
        1
        for bar, change in recent_pairs
        if bar["trade_date"] in limit_up_event_dates or (change is not None and change >= threshold)
    )
    return {"return_5d": return_5d, "limit_up_count_5d": limit_up_count_5d}


def _derived_stock_changes(bars: list[dict[str, Any]]) -> list[float | None]:
    changes: list[float | None] = []
    previous_close: float | None = None
    for bar in bars:
        if bar.get("change_pct") is not None:
            changes.append(float(bar["change_pct"]))
        elif previous_close:
            changes.append((float(bar["close"]) / previous_close - 1) * 100)
        else:
            changes.append(None)
        previous_close = float(bar["close"])
    return changes


def _limit_up_threshold(vt_symbol: str, stock_name: str = "") -> float:
    symbol, _, exchange = vt_symbol.partition(".")
    if "ST" in stock_name.upper():
        return 4.5
    if symbol.startswith(("8", "4")) or exchange in {"BJSE", "BSE"}:
        return _BSE_LIMIT_UP_THRESHOLD
    if symbol.startswith(("30", "68")):
        return _WIDE_LIMIT_UP_THRESHOLD
    return _NORMAL_LIMIT_UP_THRESHOLD


def _can_use_intraday_snapshot(session, d: date) -> bool:
    latest_complete = _latest_complete_daily_date(session)
    if latest_complete is not None and d <= latest_complete:
        return False
    minute_row = session.execute(
        select(schema.stock_minute_bars.c.vt_symbol)
        .where(
            schema.stock_minute_bars.c.trade_date == d,
            schema.stock_minute_bars.c.interval == "1m",
        )
        .limit(1)
    ).first()
    if minute_row:
        return True
    flow_row = session.execute(
        select(schema.stock_fund_flows.c.vt_symbol)
        .where(
            schema.stock_fund_flows.c.trade_date == d.isoformat(),
            schema.stock_fund_flows.c.period == "即时",
        )
        .limit(1)
    ).first()
    if flow_row:
        return True
    sector_flow_row = session.execute(
        select(schema.sector_fund_flows.c.sector_id)
        .where(
            schema.sector_fund_flows.c.trade_date == d.isoformat(),
            schema.sector_fund_flows.c.period == "即时",
        )
        .limit(1)
    ).first()
    return sector_flow_row is not None
