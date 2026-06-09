"""Stock research API routes — concept cards, workbench, financials, events.

Provides the backend API for the Stock Research Workbench:
  - GET /api/research/stocks/{vt_symbol}/concept-cards — Concept tag cards
  - GET /api/research/stocks/{vt_symbol}/workbench — Complete workbench payload
  - GET /api/research/stocks/{vt_symbol}/finance/quarterly — Quarterly financial reports
  - GET /api/research/stocks/{vt_symbol}/finance/statements — Three statements
  - GET /api/research/stocks/{vt_symbol}/business — Business segment history
  - GET /api/research/stocks/{vt_symbol}/events — Events timeline
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.symbols import normalize_exchange, vt_symbol
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope
from alphaagent.server.services.research_stock_profile import get_stock_workbench

router = APIRouter(prefix="/research/stocks", tags=["research-stocks"])


@router.get("/{vt_symbol}/concept-cards")
def stock_concept_cards(vt_symbol: str) -> dict[str, Any]:
    """Return all concept/industry cards for a stock.

    Each card includes the concept name, type, today's change_pct,
    stock count, and fund flow — so the frontend can render a
    multi-dimensional identity card.
    """
    from datetime import datetime, timezone

    parts = vt_symbol.split(".", 1)
    symbol = parts[0] if parts else vt_symbol
    exchange = parts[1] if len(parts) > 1 else None
    normalized = normalize_exchange(symbol, exchange)

    adapter = AkShareAdapter()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1) Get all sector memberships for this stock
    try:
        sectors_data = adapter.stock_sectors(symbol, normalized)
        sector_items = sectors_data.get("items") or []
    except Exception:
        sector_items = []

    # 2) Build a lookup of board change_pct from cached board listings
    board_change: dict[str, dict[str, Any]] = {}
    for bt in ("concept", "industry"):
        try:
            boards = adapter.board_names(bt, limit=1000)
            for b in boards.get("items") or []:
                bid = str(b.get("id") or b.get("akshare_symbol") or "")
                if bid:
                    board_change[bid] = {
                        "change_pct": b.get("change_pct"),
                        "stock_count": b.get("stock_count"),
                        "rise_count": b.get("rise_count"),
                        "fall_count": b.get("fall_count"),
                        "leader_stock": b.get("leader_stock"),
                        "turnover_rate": b.get("turnover_rate"),
                    }
                # Also index by name for fallback matching
                bname = str(b.get("name") or "")
                if bname:
                    board_change[bname] = {
                        "change_pct": b.get("change_pct"),
                        "stock_count": b.get("stock_count"),
                        "rise_count": b.get("rise_count"),
                        "fall_count": b.get("fall_count"),
                        "leader_stock": b.get("leader_stock"),
                        "turnover_rate": b.get("turnover_rate"),
                    }
        except Exception:
            continue

    # 3) Build concept cards
    cards: list[dict[str, Any]] = []
    for item in sector_items:
        sector_id = str(item.get("id") or item.get("akshare_symbol") or "")
        name = str(item.get("name") or "")
        stype = str(item.get("type") or item.get("category") or "concept")
        if "行业" in stype or stype in ("industry", "东方财富行业板块"):
            stype = "industry"
        else:
            stype = "concept"

        # Match board data
        bd = board_change.get(sector_id) or board_change.get(name) or {}

        cards.append({
            "sector_id": sector_id,
            "name": name,
            "type": stype,
            "change_pct": bd.get("change_pct"),
            "stock_count": bd.get("stock_count"),
            "rise_count": bd.get("rise_count"),
            "fall_count": bd.get("fall_count"),
            "leader_stock": bd.get("leader_stock"),
            "turnover_rate": bd.get("turnover_rate"),
            "confirmed": item.get("confirmed", True),
        })

    # Sort: concepts first, then by |change_pct| desc
    cards.sort(key=lambda c: (0 if c["type"] == "concept" else 1, -(abs(c.get("change_pct") or 0))))

    # 4) Shenwan classification
    shenwan: dict[str, Any] = {}
    try:
        sw = adapter.shenwan_stock_classification(symbol)
        shenwan = sw.get("levels") or {}
    except Exception:
        pass

    # 5) Stock name
    stock_name = symbol
    try:
        detail = adapter.stock_detail(symbol, normalized)
        stock_name = str(detail.get("name") or stock_name)
    except Exception:
        pass

    return {
        "vt_symbol": vt_symbol,
        "name": stock_name,
        "cards": cards,
        "shenwan": shenwan,
        "total_cards": len(cards),
        "status": "ready" if cards else "empty",
        "updated_at": now_iso,
    }


@router.get("/{vt_symbol}/workbench")
def stock_workbench(vt_symbol: str) -> dict[str, Any]:
    """Return the complete stock research workbench payload.

    This single endpoint provides all data needed for the stock detail page.
    Falls back gracefully when data is unavailable.
    """
    # Parse vt_symbol
    parts = vt_symbol.split(".", 1)
    symbol = parts[0] if parts else vt_symbol
    exchange = parts[1] if len(parts) > 1 else None

    return get_stock_workbench(symbol, exchange)


@router.get("/{vt_symbol}/finance/quarterly")
def stock_finance_quarterly(
    vt_symbol: str,
    limit: int = Query(12, ge=1, le=40),
) -> dict[str, Any]:
    """Return quarterly financial report history."""
    from alphaagent.market.symbols import vt_symbol as _make_vts

    parts = vt_symbol.split(".", 1)
    symbol = parts[0] if parts else vt_symbol
    exchange = parts[1] if len(parts) > 1 else None
    normalized = normalize_exchange(symbol, exchange)

    # Try local DB first
    if is_database_configured():
        vts = _make_vts(symbol, normalized)
        with session_scope() as session:
            from sqlalchemy import desc, select
            rows = session.execute(
                select(schema.stock_financial_reports)
                .where(schema.stock_financial_reports.c.vt_symbol == vts)
                .order_by(desc(schema.stock_financial_reports.c.report_date))
                .limit(limit)
            ).mappings().all()
            if rows:
                return {
                    "vt_symbol": vts,
                    "items": [dict(r) for r in rows],
                    "total": len(rows),
                    "source": "postgresql",
                }

    # Fallback to adapter
    adapter = AkShareAdapter()
    try:
        data = adapter.stock_financial_quarterly(symbol, exchange=normalized, limit=limit)
        return {
            **data,
            "vt_symbol": vt_symbol,
        }
    except Exception as exc:
        return {
            "vt_symbol": vt_symbol,
            "items": [],
            "total": 0,
            "source": "unavailable",
            "message": str(exc),
        }


@router.get("/{vt_symbol}/finance/statements")
def stock_finance_statements(
    vt_symbol: str,
    statement_type: str = Query("balance_sheet", description="balance_sheet/profit_sheet/cash_flow"),
) -> dict[str, Any]:
    """Return one of the three financial statements."""
    parts = vt_symbol.split(".", 1)
    symbol = parts[0] if parts else vt_symbol
    exchange = parts[1] if len(parts) > 1 else None
    normalized = normalize_exchange(symbol, exchange)

    adapter = AkShareAdapter()
    method_map = {
        "balance_sheet": adapter.stock_balance_sheet,
        "profit_sheet": adapter.stock_profit_sheet,
        "cash_flow": adapter.stock_cash_flow_sheet,
    }

    method = method_map.get(statement_type)
    if not method:
        raise HTTPException(status_code=400, detail=f"Unknown statement type: {statement_type}")

    try:
        data = method(symbol, exchange=normalized)
        return {
            **data,
            "vt_symbol": vt_symbol,
        }
    except Exception as exc:
        return {
            "vt_symbol": vt_symbol,
            "items": [],
            "total": 0,
            "source": "unavailable",
            "message": str(exc),
        }


@router.get("/{vt_symbol}/business")
def stock_business(
    vt_symbol: str,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Return business segment history with multi-period data."""
    from alphaagent.market.symbols import vt_symbol as _make_vts

    parts = vt_symbol.split(".", 1)
    symbol = parts[0] if parts else vt_symbol
    exchange = parts[1] if len(parts) > 1 else None
    normalized = normalize_exchange(symbol, exchange)
    vts = _make_vts(symbol, normalized)

    # Try local DB first
    if is_database_configured():
        with session_scope() as session:
            from sqlalchemy import desc, select
            rows = session.execute(
                select(schema.stock_business_segments)
                .where(schema.stock_business_segments.c.vt_symbol == vts)
                .order_by(desc(schema.stock_business_segments.c.report_date))
                .limit(limit)
            ).mappings().all()
            if rows:
                items = [dict(r) for r in rows]
                # Group by report_date
                by_date: dict[str, list[dict[str, Any]]] = {}
                for item in items:
                    rd = str(item.get("report_date") or "unknown")
                    by_date.setdefault(rd, []).append(item)
                return {
                    "vt_symbol": vts,
                    "items": items,
                    "by_report_date": by_date,
                    "report_periods": sorted(by_date.keys(), reverse=True),
                    "total": len(items),
                    "source": "postgresql",
                }

    # Fallback to adapter
    adapter = AkShareAdapter()
    try:
        data = adapter.stock_business_segments_history(symbol, exchange=normalized, limit=limit)
        return {
            **data,
            "vt_symbol": vts,
        }
    except Exception as exc:
        return {
            "vt_symbol": vts,
            "items": [],
            "total": 0,
            "source": "unavailable",
            "message": str(exc),
        }


@router.get("/{vt_symbol}/events")
def stock_events(
    vt_symbol: str,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Return stock events timeline."""
    from alphaagent.market.symbols import vt_symbol as _make_vts

    parts = vt_symbol.split(".", 1)
    symbol = parts[0] if parts else vt_symbol
    exchange = parts[1] if len(parts) > 1 else None
    normalized = normalize_exchange(symbol, exchange)
    vts = _make_vts(symbol, normalized)

    events: list[dict[str, Any]] = []

    # Local DB events
    if is_database_configured():
        with session_scope() as session:
            from sqlalchemy import desc, select
            rows = session.execute(
                select(schema.stock_events)
                .where(schema.stock_events.c.vt_symbol == vts)
                .order_by(desc(schema.stock_events.c.event_date))
                .limit(limit)
            ).mappings().all()
            events.extend([dict(r) for r in rows])

    # Hot rank info
    adapter = AkShareAdapter()
    hot_rank: dict[str, Any] = {}
    try:
        data = adapter.stock_hot_detail(symbol, exchange=normalized)
        hot_rank = {"rank": data.get("rank"), "keywords": data.get("keywords") or []}
    except Exception:
        hot_rank = {"rank": None, "keywords": []}

    return {
        "vt_symbol": vts,
        "timeline": events,
        "total": len(events),
        "hot_rank": hot_rank,
        "source": "postgresql" if events else "partial",
    }
