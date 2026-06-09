"""Sector research API routes — ranking, dashboard, detail, relation graph.

Provides the backend API for the Sector Mainline Dashboard:
  - GET /api/research/sectors/ranking — Composite ranking (live AkShare)
  - GET /api/research/sectors/dashboard — Main dashboard with period scores
  - GET /api/research/sectors/{sector_id}/overview — Sector detail overview
  - GET /api/research/sectors/{sector_id}/relation-graph — Sector relation graph
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope

router = APIRouter(prefix="/research/sectors", tags=["research-sectors"])


@router.get("/ranking")
def sector_ranking(
    sector_type: str = Query("concept", description="concept|industry|all"),
    sort_by: str = Query("change_pct", description="change_pct|fund_flow|stock_count"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Return composite sector/concept ranking from live AkShare data.

    Combines board listing with fund flow data to produce a ranked view
    usable by the Theme Explorer and Market Pulse pages.
    """
    from alphaagent.data_sources.akshare_adapter import AkShareAdapter

    adapter = AkShareAdapter()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1) Load board listings
    items: list[dict[str, Any]] = []
    board_types = ["concept", "industry"] if sector_type in ("all", "") else [sector_type]
    for bt in board_types:
        try:
            data = adapter.board_names(bt, limit=500)
            for row in data.get("items") or []:
                row["_board_type"] = bt
                items.append(row)
        except Exception:
            continue

    if not items:
        return {
            "items": [],
            "total": 0,
            "sort_by": sort_by,
            "status": "unavailable",
            "message": "No board data available",
            "updated_at": now_iso,
        }

    # 2) Enrich with fund flow data (best-effort)
    fund_map: dict[str, float] = {}
    for bt in board_types:
        try:
            ff = adapter.sector_fund_flows(bt, period="即时")
            for f in ff.get("items") or []:
                fid = str(f.get("代码") or f.get("code") or f.get("sector_id") or "")
                name_key = str(f.get("名称") or f.get("name") or "")
                net = f.get("主力净流入-净额") or f.get("main_net_inflow")
                if net is not None:
                    fund_map[fid] = float(net)
                    fund_map[name_key] = float(net)
        except Exception:
            continue

    # 3) Build ranking items
    ranking_items: list[dict[str, Any]] = []
    for row in items:
        sector_id = str(row.get("id") or row.get("akshare_symbol") or "")
        name = str(row.get("name") or "")
        bt = str(row.get("_board_type") or row.get("type") or "concept")
        change_pct = row.get("change_pct")
        stock_count = row.get("stock_count")
        rise_count = row.get("rise_count")
        fall_count = row.get("fall_count")
        leader_stock = row.get("leader_stock")
        leader_change_pct = row.get("leader_change_pct")
        market_cap = row.get("market_cap")
        turnover_rate = row.get("turnover_rate")

        # Match fund flow by id or name
        main_net_inflow = fund_map.get(sector_id) or fund_map.get(name)

        ranking_items.append({
            "sector_id": sector_id,
            "name": name,
            "type": bt,
            "change_pct": change_pct,
            "stock_count": stock_count,
            "rise_count": rise_count,
            "fall_count": fall_count,
            "leader_stock": leader_stock,
            "leader_change_pct": leader_change_pct,
            "market_cap": market_cap,
            "turnover_rate": turnover_rate,
            "main_net_inflow": main_net_inflow,
        })

    # 4) Sort
    def _sort_key(item: dict[str, Any]) -> tuple:
        if sort_by == "fund_flow":
            v = item.get("main_net_inflow")
            return (0, -(v if v is not None else 0))
        if sort_by == "stock_count":
            v = item.get("stock_count")
            return (0, -(v if v is not None else 0))
        # Default: change_pct (hottest first)
        v = item.get("change_pct")
        return (0, -(v if v is not None else -9999))

    ranking_items.sort(key=_sort_key)

    bounded = ranking_items[:min(limit, 200)]

    return {
        "items": bounded,
        "total": len(ranking_items),
        "sort_by": sort_by,
        "status": "ready",
        "updated_at": now_iso,
    }


@router.get("/dashboard")
def sector_dashboard(
    period: str = Query("20d", description="Scoring period (1d/3d/5d/10d/20d/60d/120d/250d)"),
    sector_type: str | None = Query(None, description="Filter by sector type"),
    sort_by: str = Query("heat_score", description="Sort field"),
    sort_order: str = Query("desc", description="Sort direction: asc/desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
    q: str = Query("", description="Search query"),
) -> dict[str, Any]:
    """Return the sector mainline dashboard with period scores."""
    if not is_database_configured():
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "period": period,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "status": "unavailable",
            "message": "Database not configured",
        }

    with session_scope() as session:
        from sqlalchemy import asc, desc as sql_desc, func, select

        query = (
            select(schema.sector_period_scores)
            .where(schema.sector_period_scores.c.period == period)
        )

        if sector_type:
            query = query.where(schema.sector_period_scores.c.sector_type == sector_type)

        # Search filter
        if q.strip():
            # Join with sectors for name search
            query = query.join(
                schema.sectors,
                schema.sector_period_scores.c.sector_id == schema.sectors.c.id,
            ).where(
                schema.sectors.c.name.ilike(f"%{q.strip()}%")
            )

        # Total count
        total = session.execute(
            select(func.count()).select_from(query.subquery())
        ).scalar() or 0

        # Sort
        sort_column = getattr(schema.sector_period_scores.c, sort_by, None)
        if sort_column is None:
            sort_column = schema.sector_period_scores.c.heat_score

        if sort_order == "asc":
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(sql_desc(sort_column))

        # Pagination
        offset = (page - 1) * page_size
        rows = session.execute(
            query.offset(offset).limit(page_size)
        ).mappings().all()

        # Enrich with sector names
        items = []
        for row in rows:
            item = dict(row)
            # Get sector name
            sector = session.execute(
                select(schema.sectors.c.name, schema.sectors.c.type, schema.sectors.c.stock_count)
                .where(schema.sectors.c.id == item["sector_id"])
            ).mappings().first()
            if sector:
                item["sector_name"] = sector["name"]
                item["sector_type"] = sector["type"] or item.get("sector_type")
                item["stock_count"] = sector["stock_count"]
            items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "period": period,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "status": "ready" if total > 0 else "empty",
    }


@router.get("/{sector_id}/overview")
def sector_overview(sector_id: str) -> dict[str, Any]:
    """Return detailed overview for a single sector."""
    if not is_database_configured():
        return {"status": "unavailable", "message": "Database not configured"}

    from sqlalchemy import func, select

    result: dict[str, Any] = {"sector_id": sector_id, "status": "empty"}

    with session_scope() as session:
        # Sector basic info
        sector = session.execute(
            select(schema.sectors).where(schema.sectors.c.id == sector_id)
        ).mappings().first()

        if not sector:
            raise HTTPException(status_code=404, detail=f"Sector {sector_id} not found")

        result["info"] = dict(sector)
        result["status"] = "ready"

        # Latest daily metrics
        metrics = session.execute(
            select(schema.sector_daily_metrics)
            .where(schema.sector_daily_metrics.c.sector_id == sector_id)
            .order_by(schema.sector_daily_metrics.c.trade_date.desc())
            .limit(1)
        ).mappings().first()
        result["daily_metrics"] = dict(metrics) if metrics else None

        # Period scores (all periods)
        scores = session.execute(
            select(schema.sector_period_scores)
            .where(schema.sector_period_scores.c.sector_id == sector_id)
            .order_by(schema.sector_period_scores.c.period)
        ).mappings().all()
        result["period_scores"] = [dict(s) for s in scores]

        # Top members (by change_pct)
        members = session.execute(
            select(schema.sector_memberships)
            .where(schema.sector_memberships.c.sector_id == sector_id)
            .order_by(schema.sector_memberships.c.change_pct.desc())
            .limit(20)
        ).mappings().all()
        result["top_members"] = [dict(m) for m in members]

        # Recent sector bars
        bars = session.execute(
            select(schema.sector_daily_bars)
            .where(schema.sector_daily_bars.c.sector_id == sector_id)
            .order_by(schema.sector_daily_bars.c.trade_date.desc())
            .limit(60)
        ).mappings().all()
        result["recent_bars"] = [dict(b) for b in bars]

        # Fund flows
        fund_flows = session.execute(
            select(schema.sector_fund_flows)
            .where(schema.sector_fund_flows.c.sector_id == sector_id)
            .order_by(schema.sector_fund_flows.c.trade_date.desc())
            .limit(10)
        ).mappings().all()
        result["fund_flows"] = [dict(f) for f in fund_flows]

    return result


@router.get("/{sector_id}/relation-graph")
def sector_relation_graph(
    sector_id: str,
    period: str = Query("20d", description="Lookback period"),
    min_score: float = Query(5.0, description="Minimum edge score"),
) -> dict[str, Any]:
    """Return the relation graph for a sector and its neighbors."""
    if not is_database_configured():
        return {"nodes": [], "edges": [], "status": "unavailable"}

    from sqlalchemy import func, select

    with session_scope() as session:
        # Get edges involving this sector
        edges = session.execute(
            select(schema.sector_relation_edges).where(
                (
                    (schema.sector_relation_edges.c.source_sector_id == sector_id)
                    | (schema.sector_relation_edges.c.target_sector_id == sector_id)
                )
                & (schema.sector_relation_edges.c.score >= min_score)
            ).order_by(schema.sector_relation_edges.c.score.desc()).limit(50)
        ).mappings().all()

        if not edges:
            return {"nodes": [], "edges": [], "sector_id": sector_id, "status": "no_edges"}

        # Collect all involved sector IDs
        sector_ids = set()
        for edge in edges:
            sector_ids.add(str(edge["source_sector_id"]))
            sector_ids.add(str(edge["target_sector_id"]))

        # Load sector info for nodes
        sector_rows = session.execute(
            select(schema.sectors).where(schema.sectors.c.id.in_(sector_ids))
        ).mappings().all()

        nodes = [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "type": r["type"],
                "stock_count": r.get("stock_count"),
                "change_pct": r.get("change_pct"),
            }
            for r in sector_rows
        ]

        edge_list = [
            {
                "source": str(e["source_sector_id"]),
                "target": str(e["target_sector_id"]),
                "score": e.get("score"),
                "shared_stock_count": e.get("shared_stock_count"),
                "jaccard": e.get("jaccard"),
                "price_correlation": e.get("price_correlation"),
                "fund_correlation": e.get("fund_correlation"),
                "evidence": e.get("evidence"),
                "confidence": e.get("confidence"),
            }
            for e in edges
        ]

    return {
        "sector_id": sector_id,
        "nodes": nodes,
        "edges": edge_list,
        "period": period,
        "status": "ready",
    }
