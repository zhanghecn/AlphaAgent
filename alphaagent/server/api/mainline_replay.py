"""Mainline replay API — 历史日期回放主线板块/大盘/资金 + 行情反推关联.

Provides:
  - GET /api/mainline-replay/timeline  可回放的交易日列表
  - GET /api/mainline-replay/snapshot  单日快照(date) 或 区间delta(t1+t2)
  - GET /api/mainline-replay/relation  指定板块在指定日期的关联板块(行情反推)

设计文档：docs/superpowers/specs/2026-06-28-mainline-replay-design.md
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope
from alphaagent.server.services.mainline_replay import (
    compute_fund_strength_batch,
    compute_raw_sector_delta,
    compute_relations_aligned,
)

router = APIRouter(prefix="/mainline-replay", tags=["mainline-replay"])

# 大盘指数 vt_symbol（与 alphaagent.market.symbols.INDEX_SYMBOLS 一致）
_INDEX_VT_SYMBOLS = [
    "000001.SSE", "399001.SZSE", "399006.SZSE",
    "000300.SSE", "000905.SSE", "000852.SSE", "000688.SSE",
]
_DEFAULT_PERIOD = "20d"
_WINDOW_DAYS = 20  # 关联反推的行情窗口
_MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3000
_RELATION_CANDIDATE_LIMIT = 360
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
    "涨停",
    "连板",
    "打板",
    "炸板",
    "首板",
    "二板",
    "三板",
    "龙虎榜",
)


@router.get("/timeline", response_model=None)
def timeline(limit: int = Query(400, ge=1, le=2000)) -> dict[str, Any]:
    """可回放的交易日列表（sector_period_scores 里存在的 as_of_date 去重降序）。"""
    if not is_database_configured():
        return ok({"dates": [], "status": "unavailable", "message": "数据库未配置"})
    with session_scope() as session:
        complete_trade_dates = (
            select(schema.stock_daily_bars.c.trade_date)
            .group_by(schema.stock_daily_bars.c.trade_date)
            .having(func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)) >= _MIN_COMPLETE_DAILY_SYMBOL_COUNT)
        ).subquery()
        rows = session.execute(
            select(schema.sector_period_scores.c.as_of_date)
            .where(schema.sector_period_scores.c.period == _DEFAULT_PERIOD)
            .where(schema.sector_period_scores.c.as_of_date.in_(select(complete_trade_dates.c.trade_date)))
            .group_by(schema.sector_period_scores.c.as_of_date)
            .order_by(desc(schema.sector_period_scores.c.as_of_date))
            .limit(limit)
        ).all()
    dates = [str(r[0]) for r in rows]
    return ok({"dates": dates, "status": "ready" if dates else "empty"})


@router.get("/live", response_model=None)
def live(
    trade_date: date | None = Query(None, description="盘中日期 YYYY-MM-DD；默认取最新板块资金流日期"),
    sector_type: str | None = Query(None, description="板块类型过滤"),
    limit: int = Query(80, ge=1, le=300),
) -> dict[str, Any]:
    """今日/盘中主线资金流。

    历史回放读 sector_period_scores；收盘前实时模式只读可覆盖当日的
    sector_fund_flows + sectors 快照，不把盘中数据写成历史评分。
    """
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})

    if not isinstance(trade_date, date):
        trade_date = None
    if not isinstance(sector_type, str):
        sector_type = None

    with session_scope() as session:
        latest_flow_date = session.execute(
            select(func.max(schema.sector_fund_flows.c.trade_date))
        ).scalar()
        resolved_date = trade_date or _parse_optional_date(latest_flow_date)
        if resolved_date is None:
            return ok({"status": "empty", "ranking": [], "index": []})

        ranking = _live_ranking_for_date(session, resolved_date, sector_type, limit)
        latest_complete_daily = _latest_complete_daily_date(session)
        latest_snapshot_updated = session.execute(select(func.max(schema.stocks.c.updated_at))).scalar()
        latest_snapshot_trade_time = session.execute(select(func.max(schema.stocks.c.trade_time))).scalar()
        latest_minute_time = session.execute(
            select(func.max(schema.stock_minute_bars.c.bar_time)).where(
                schema.stock_minute_bars.c.trade_date == resolved_date,
                schema.stock_minute_bars.c.interval == "1m",
            )
        ).scalar()

    return ok({
        "mode": "live",
        "trade_date": resolved_date.isoformat(),
        "base_daily_date": _iso_or_none(latest_complete_daily),
        "ranking": ranking,
        "index": [],
        "status": "ready" if ranking else "empty",
        "source": "sector_fund_flows",
        "temporary_bar": True,
        "latest_minute_time": _iso_or_none(latest_minute_time),
        "snapshot_updated_at": _iso_or_none(latest_snapshot_updated),
        "snapshot_trade_time": str(latest_snapshot_trade_time) if latest_snapshot_trade_time else None,
        "message": "收盘前动态计算：板块实时资金流 + 盘中快照；历史回放仍读 sector_period_scores。",
    })


@router.get("/snapshot", response_model=None)
def snapshot(
    date: date | None = Query(None, description="单日快照日期 YYYY-MM-DD"),
    t1: date | None = Query(None, description="区间起点"),
    t2: date | None = Query(None, description="区间终点"),
    sector_type: str | None = Query(None, description="板块类型过滤"),
    limit: int = Query(50, ge=1, le=300),
) -> dict[str, Any]:
    """单日快照(date) 或 区间delta(t1+t2)。

    返回主线板块榜(按 heat_score/fund_strength)、大盘指数。
    """
    if date is None and (t1 is None or t2 is None):
        return JSONResponse(
            status_code=400,
            content=fail("BAD_PARAMS", "需要 date 或 (t1,t2)", {}),
        )
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})

    with session_scope() as session:
        sectors_meta = _load_sectors_meta(session)
        if date is not None:
            ranking = _ranking_for_date(session, date, sector_type, limit)
            mode = "single"
        else:
            ranking = _ranking_for_range(session, t1, t2, sector_type, limit)  # type: ignore[arg-type]
            mode = "delta"
        index_data = _load_index(session, date or t2)  # type: ignore[arg-type]
        for item in ranking:
            meta = sectors_meta.get(item["sector_id"], {})
            item["name"] = meta.get("name", item["sector_id"])
            item["sector_type"] = meta.get("type")

    return ok({"mode": mode, "ranking": ranking, "index": index_data, "status": "ready"})


@router.get("/relation", response_model=None)
def relation(
    sector_id: str = Query(..., description="目标板块ID"),
    date: date = Query(..., description="回放日期 YYYY-MM-DD"),
    limit: int = Query(12, ge=1, le=50),
) -> dict[str, Any]:
    """指定板块在指定日期的关联板块（行情反推，涨跌共振为主权重）。"""
    if not is_database_configured():
        return ok({"status": "unavailable", "message": "数据库未配置"})

    with session_scope() as session:
        # 目标板块最近 _WINDOW_DAYS 个评分日（as_of_date <= date，return_pct 非空）
        # 数据源用 sector_period_scores（覆盖广 ~240 板块），而非 sector_daily_bars（仅 ~42 板块），
        # 保证关联反推对绝大多数板块可用。return_pct 为滚动周期收益率，序列共振仍反映板块间走势协同。
        tgt_rows = session.execute(
            select(
                schema.sector_period_scores.c.as_of_date,
                schema.sector_period_scores.c.return_pct,
                schema.sector_period_scores.c.fund_score,
            )
            .where(
                schema.sector_period_scores.c.sector_id == sector_id,
                schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
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
            if sid in cand_ids:
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
                    schema.sector_period_scores.c.as_of_date.in_(tgt_dates),
                )
            ).all()
            for sid, d, ret, fund in score_rows:
                if ret is not None:
                    candidate_maps.setdefault(sid, {})[d] = float(ret)
                if fund is not None:
                    candidate_fund_maps.setdefault(sid, {})[d] = float(fund)

        sectors_meta = _load_sectors_meta(session)
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
            it["sector_type"] = meta.get("type")
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
            "candidate_basis": "shared constituents plus active scored sectors in the replay window",
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


def _latest_complete_daily_date(session) -> date | None:
    row = session.execute(
        select(schema.stock_daily_bars.c.trade_date)
        .group_by(schema.stock_daily_bars.c.trade_date)
        .having(func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)) >= _MIN_COMPLETE_DAILY_SYMBOL_COUNT)
        .order_by(desc(schema.stock_daily_bars.c.trade_date))
        .limit(1)
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


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _live_ranking_for_date(
    session,
    d: date,
    sector_type: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    latest_scores = (
        select(
            schema.sector_period_scores.c.sector_id,
            func.max(schema.sector_period_scores.c.as_of_date).label("latest_score_date"),
        )
        .where(
            schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
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
        )
    )
    if sector_type:
        q = q.where(schema.sectors.c.type == sector_type)
    rows = session.execute(
        q.order_by(
            desc(schema.sector_fund_flows.c.main_net_inflow),
            schema.sector_fund_flows.c.rank.asc().nulls_last(),
        ).limit(limit)
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
        ranking.append({
            "sector_id": sector_id,
            "name": name or sector_id,
            "sector_type": row_sector_type,
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
    return ranking


def _ranking_for_date(session, d: date, sector_type: str | None, limit: int) -> list[dict[str, Any]]:
    q = (
        select(schema.sector_period_scores)
        .where(
            schema.sector_period_scores.c.as_of_date == d,
            schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
        )
    )
    if sector_type:
        q = q.where(schema.sector_period_scores.c.sector_type == sector_type)
    q = q.order_by(desc(schema.sector_period_scores.c.heat_score)).limit(limit)
    rows = session.execute(q).mappings().all()
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        out.append({
            "sector_id": r["sector_id"],
            "heat_score": r.get("heat_score"),
            "fund_score": r.get("fund_score"),
            "momentum_score": r.get("momentum_score"),
            "trend_state": r.get("trend_state"),
            "rank_return": r.get("rank_return"),
            "return_pct": r.get("return_pct"),
            "confidence": r.get("confidence"),
        })
    return out


def _ranking_for_range(
    session, t1: date, t2: date, sector_type: str | None, limit: int
) -> list[dict[str, Any]]:
    """区间 delta：取 t1/t2 两日 scores + [t1,t2] 区间 bars 算 raw delta，再批量算 fund_strength。"""
    base = select(schema.sector_period_scores).where(
        schema.sector_period_scores.c.period == _DEFAULT_PERIOD,
        schema.sector_period_scores.c.as_of_date.in_([t1, t2]),
    )
    if sector_type:
        base = base.where(schema.sector_period_scores.c.sector_type == sector_type)
    score_rows = session.execute(base).mappings().all()
    by_sector: dict[str, dict] = {"t1": {}, "t2": {}}
    for r in score_rows:
        d = r["as_of_date"]
        key = "t1" if d == t1 else "t2"
        by_sector[key][r["sector_id"]] = r

    sector_ids = list(set(by_sector["t1"].keys()) & set(by_sector["t2"].keys()))
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


@router.get("/sector-stocks", response_model=None)
def sector_stocks(
    sector_id: str = Query(..., description="板块ID"),
    date: date = Query(..., description="回放日期 YYYY-MM-DD"),
    sort_by: str = Query("net_inflow", description="net_inflow|change_pct|name"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """板块成分股 + 当日涨跌(从close算) + 个股资金流向(近端)，用于排查个股流入流出。"""
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
            net, ratio = flow_map.get(vsym, (None, None))
            items.append({
                "vt_symbol": vsym,
                "name": name_map.get(vsym, vsym),
                "close": close_today,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "price_date": str(date) if close_today is not None else None,
                "price_source": price_source,
                "trade_time": trade_time,
                "main_net_inflow": net,
                "main_net_inflow_ratio": ratio,
                "fund_inflow_available": net is not None,
            })

        if sort_by == "change_pct":
            items.sort(key=lambda x: (x["change_pct"] is not None, x["change_pct"] or -999), reverse=True)
        elif sort_by == "name":
            items.sort(key=lambda x: x["name"])
        else:  # net_inflow（默认：主力净流入降序，None 在后）
            items.sort(key=lambda x: (x["main_net_inflow"] is not None, x["main_net_inflow"] or -1e18), reverse=True)

    return ok({
        "sector_id": sector_id,
        "date": str(date),
        "items": items[:limit],
        "total": len(items),
        "fund_flow_available": sum(1 for it in items if it["fund_inflow_available"]),
        "price_source": "daily_bar" if today_close else "intraday_snapshot" if snapshot_price else None,
        "status": "ready",
    })


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
