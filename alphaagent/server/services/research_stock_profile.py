"""Stock research profile service — aggregate stock data for the workbench.

Provides a unified API for the stock research workbench page:
  - Basic info and latest quotes
  - Technical indicators
  - Financial history (quarterly reports, three statements)
  - Business segment history
  - Sector memberships and positions
  - Industry chain graph evidence
  - Events timeline (news, notices, fund flows, hot ranks, LHB)

All data is read from local PostgreSQL tables, falling back to the
AkShare adapter cache when local data is absent.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Sequence

from sqlalchemy import desc, func, select

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.symbols import normalize_exchange, vt_symbol
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope

logger = logging.getLogger(__name__)


# ── Main workbench aggregation ──

def get_stock_workbench(
    symbol: str,
    exchange: str | None = None,
) -> dict[str, Any]:
    """Build the complete stock research workbench payload.

    Returns a dict with sections: profile, technical, financial,
    business, sectors, chain, events, data_quality.
    """
    normalized = normalize_exchange(symbol, exchange)
    vts = vt_symbol(symbol, normalized)
    adapter = AkShareAdapter()

    result: dict[str, Any] = {
        "vt_symbol": vts,
        "symbol": symbol,
        "exchange": normalized,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Profile (basic info)
    result["profile"] = _get_stock_profile(vts, symbol, normalized, adapter)

    # 2. Technical (latest bars + indicators)
    result["technical"] = _get_stock_technical(vts, symbol, normalized, adapter)

    # 3. Financial history
    result["financial"] = _get_stock_financial(vts, symbol, normalized, adapter)

    # 4. Business segment history
    result["business"] = _get_stock_business(vts, symbol, normalized, adapter)

    # 5. Sector memberships
    result["sectors"] = _get_stock_sectors(vts)

    # 6. Industry chain evidence
    result["chain"] = _get_stock_chain(vts)

    # 7. Events timeline
    result["events"] = _get_stock_events(vts, symbol, normalized, adapter)

    # 8. Data quality assessment
    result["data_quality"] = _assess_data_quality(result)

    return result


# ── Section aggregators ──

def _get_stock_profile(
    vts: str,
    symbol: str,
    exchange: str,
    adapter: AkShareAdapter,
) -> dict[str, Any]:
    """Get stock basic profile info."""
    # Try local DB first
    if is_database_configured():
        with session_scope() as session:
            row = session.execute(
                select(schema.stocks).where(schema.stocks.c.vt_symbol == vts)
            ).mappings().first()
            if row:
                return {
                    "name": row.get("name"),
                    "industry": row.get("industry"),
                    "area": row.get("area"),
                    "last_price": row.get("last_price"),
                    "change_pct": row.get("change_pct"),
                    "market_cap": row.get("market_cap"),
                    "pe": row.get("pe"),
                    "pb": row.get("pb"),
                    "turnover_rate": row.get("turnover_rate"),
                    "source": "postgresql",
                }

    # Fallback to adapter
    try:
        data = adapter.stock_detail(symbol, exchange=exchange)
        item = (data.get("items") or [{}])[0] if data.get("items") else {}
        return {
            "name": item.get("name"),
            "last_price": item.get("last_price"),
            "change_pct": item.get("change_pct"),
            "market_cap": item.get("market_cap"),
            "pe": item.get("pe"),
            "pb": item.get("pb"),
            "source": data.get("source", "akshare_cache"),
        }
    except Exception:
        return {"source": "unavailable"}


def _get_stock_technical(
    vts: str,
    symbol: str,
    exchange: str,
    adapter: AkShareAdapter,
) -> dict[str, Any]:
    """Get stock technical data (bars + indicators)."""
    result: dict[str, Any] = {"source": "unavailable"}

    # Try local bars
    bars: list[dict[str, Any]] = []
    if is_database_configured():
        with session_scope() as session:
            rows = session.execute(
                select(schema.stock_daily_bars)
                .where(schema.stock_daily_bars.c.vt_symbol == vts)
                .order_by(desc(schema.stock_daily_bars.c.trade_date))
                .limit(250)
            ).mappings().all()
            bars = [
                {
                    "trade_date": str(r.get("trade_date")),
                    "open": r.get("open_price"),
                    "close": r.get("close_price"),
                    "high": r.get("high_price"),
                    "low": r.get("low_price"),
                    "volume": r.get("volume"),
                    "turnover": r.get("turnover"),
                    "change_pct": r.get("change_pct"),
                }
                for r in rows
            ]

    if not bars:
        try:
            data = adapter.stock_bars(symbol, exchange, limit=250, interval="1d")
            bars = data.get("items") or []
            result["source"] = data.get("source", "akshare_cache")
        except Exception:
            bars = []
    else:
        result["source"] = "postgresql"

    result["bars"] = bars
    result["bar_count"] = len(bars)

    # Technical indicators (from adapter cache)
    try:
        indicators = adapter.stock_indicators(symbol, exchange=exchange, limit=30)
        result["indicators"] = indicators.get("items") or []
    except Exception:
        result["indicators"] = []

    return result


def _get_stock_financial(
    vts: str,
    symbol: str,
    exchange: str,
    adapter: AkShareAdapter,
) -> dict[str, Any]:
    """Get stock financial data (quarterly reports, three statements)."""
    result: dict[str, Any] = {"source": "unavailable"}

    # Try local DB
    if is_database_configured():
        with session_scope() as session:
            report_rows = session.execute(
                select(schema.stock_financial_reports)
                .where(schema.stock_financial_reports.c.vt_symbol == vts)
                .order_by(desc(schema.stock_financial_reports.c.report_date))
                .limit(20)
            ).mappings().all()
            if report_rows:
                result["quarterly"] = [dict(r) for r in report_rows]
                result["source"] = "postgresql"

    # Fallback to adapter
    if "quarterly" not in result:
        try:
            data = adapter.stock_financial_quarterly(symbol, exchange=exchange, limit=12)
            result["quarterly"] = data.get("items") or []
            result["source"] = data.get("source", "akshare_cache")
        except Exception:
            result["quarterly"] = []

    # Financial indicators
    if is_database_configured():
        with session_scope() as session:
            ind_rows = session.execute(
                select(schema.stock_financial_reports)
                .where(
                    (schema.stock_financial_reports.c.vt_symbol == vts)
                    & (schema.stock_financial_reports.c.period_type == "indicator")
                )
                .order_by(desc(schema.stock_financial_reports.c.report_date))
                .limit(8)
            ).mappings().all()
            if ind_rows:
                result["indicators"] = [dict(r) for r in ind_rows]
    else:
        try:
            data = adapter.stock_financial_indicators(symbol, exchange=exchange)
            result["indicators"] = data.get("items") or []
        except Exception:
            result["indicators"] = []

    # Three statements (balance sheet, profit, cash flow)
    result["statements"] = {}
    for stmt_key, stmt_method in [
        ("balance_sheet", adapter.stock_balance_sheet),
        ("profit_sheet", adapter.stock_profit_sheet),
        ("cash_flow", adapter.stock_cash_flow_sheet),
    ]:
        try:
            data = stmt_method(symbol, exchange=exchange)
            result["statements"][stmt_key] = {
                "items": data.get("items") or [],
                "source": data.get("source", "akshare_cache"),
            }
        except Exception:
            result["statements"][stmt_key] = {"items": [], "source": "unavailable"}

    return result


def _get_stock_business(
    vts: str,
    symbol: str,
    exchange: str,
    adapter: AkShareAdapter,
) -> dict[str, Any]:
    """Get business segment history."""
    result: dict[str, Any] = {"source": "unavailable"}

    # Try local DB
    if is_database_configured():
        with session_scope() as session:
            rows = session.execute(
                select(schema.stock_business_segments)
                .where(schema.stock_business_segments.c.vt_symbol == vts)
                .order_by(desc(schema.stock_business_segments.c.report_date))
                .limit(100)
            ).mappings().all()
            if rows:
                result["items"] = [dict(r) for r in rows]
                result["source"] = "postgresql"

    # Fallback to adapter
    if "items" not in result:
        try:
            data = adapter.stock_business_segments_history(symbol, exchange=exchange, limit=100)
            result["items"] = data.get("items") or []
            result["source"] = data.get("source", "akshare_cache")
        except Exception:
            result["items"] = []

    # Group by report_date for timeline view
    by_date: dict[str, list[dict[str, Any]]] = {}
    for item in result.get("items", []):
        rd = str(item.get("report_date") or "unknown")
        by_date.setdefault(rd, []).append(item)
    result["by_report_date"] = by_date
    result["report_periods"] = sorted(by_date.keys(), reverse=True)

    return result


def _get_stock_sectors(vts: str) -> dict[str, Any]:
    """Get sector memberships and positions."""
    result: dict[str, Any] = {"memberships": [], "source": "unavailable"}

    if not is_database_configured():
        return result

    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_sector_memberships)
            .where(schema.stock_sector_memberships.c.vt_symbol == vts)
        ).mappings().all()

        result["memberships"] = [
            {
                "sector_id": r.get("sector_id"),
                "sector_name": r.get("sector_name"),
                "sector_type": r.get("sector_type"),
                "rank": r.get("rank"),
                "confirmed": r.get("confirmed"),
            }
            for r in rows
        ]
        result["source"] = "postgresql"

    # Try to get sector scores for these sectors
    sector_ids = [m["sector_id"] for m in result["memberships"] if m.get("sector_id")]
    if sector_ids:
        with session_scope() as session:
            scores = session.execute(
                select(schema.sector_period_scores)
                .where(
                    (schema.sector_period_scores.c.sector_id.in_(sector_ids))
                    & (schema.sector_period_scores.c.period == "20d")
                )
                .order_by(desc(schema.sector_period_scores.c.heat_score))
            ).mappings().all()
            result["sector_scores"] = [dict(s) for s in scores]

    return result


def _get_stock_chain(vts: str) -> dict[str, Any]:
    """Get industry chain graph evidence for this stock."""
    result: dict[str, Any] = {"edges": [], "source": "unavailable"}

    if not is_database_configured():
        return result

    # Find chain nodes that reference this stock
    with session_scope() as session:
        nodes = session.execute(
            select(schema.industry_chain_nodes)
            .where(schema.industry_chain_nodes.c.vt_symbol == vts)
        ).mappings().all()

        if nodes:
            node_ids = [str(n["id"]) for n in nodes]
            edges = session.execute(
                select(schema.industry_chain_edges).where(
                    (schema.industry_chain_edges.c.source_node_id.in_(node_ids))
                    | (schema.industry_chain_edges.c.target_node_id.in_(node_ids))
                ).limit(50)
            ).mappings().all()
            result["nodes"] = [dict(n) for n in nodes]
            result["edges"] = [dict(e) for e in edges]
            result["source"] = "postgresql"

    return result


def _get_stock_events(
    vts: str,
    symbol: str,
    exchange: str,
    adapter: AkShareAdapter,
) -> dict[str, Any]:
    """Get stock events timeline."""
    result: dict[str, Any] = {"timeline": [], "source": "unavailable"}

    # Local events
    if is_database_configured():
        with session_scope() as session:
            rows = session.execute(
                select(schema.stock_events)
                .where(schema.stock_events.c.vt_symbol == vts)
                .order_by(desc(schema.stock_events.c.event_date))
                .limit(50)
            ).mappings().all()
            if rows:
                result["timeline"].extend([dict(r) for r in rows])
                result["source"] = "postgresql"

    # Hot rank
    try:
        data = adapter.stock_hot_detail(symbol, exchange=exchange)
        result["hot_rank"] = {
            "rank": data.get("rank"),
            "keywords": data.get("keywords") or [],
        }
    except Exception:
        result["hot_rank"] = {"rank": None, "keywords": []}

    # Fund flows
    try:
        data = adapter.stock_fund_flows(symbol, exchange=exchange)
        result["fund_flows"] = data.get("items") or []
    except Exception:
        result["fund_flows"] = []

    # LHB
    try:
        data = adapter.stock_lhb_records(
            start_date=(date.today() - __import__("datetime").timedelta(days=90)).strftime("%Y%m%d")
        )
        items = data.get("items") or []
        # Filter for this symbol
        result["lhb"] = [
            item for item in items
            if item.get("vt_symbol") == vts or (item.get("raw") or {}).get("代码") == symbol
        ]
    except Exception:
        result["lhb"] = []

    return result


# ── Data quality assessment ──

def _assess_data_quality(workbench: dict[str, Any]) -> dict[str, Any]:
    """Assess data completeness and quality for each section."""
    sections = {
        "profile": workbench.get("profile", {}).get("source") != "unavailable",
        "technical_bars": len(workbench.get("technical", {}).get("bars") or []) > 10,
        "financial_quarterly": len(workbench.get("financial", {}).get("quarterly") or []) > 0,
        "business_segments": len(workbench.get("business", {}).get("items") or []) > 0,
        "sector_memberships": len(workbench.get("sectors", {}).get("memberships") or []) > 0,
        "chain_evidence": len(workbench.get("chain", {}).get("edges") or []) > 0,
        "events": len(workbench.get("events", {}).get("timeline") or []) > 0,
    }

    available = sum(1 for v in sections.values() if v)
    total = len(sections)

    # Suggest sync jobs for missing data
    suggestions: list[str] = []
    if not sections["technical_bars"]:
        suggestions.append("Run sync_stock_daily_bars to populate price history")
    if not sections["financial_quarterly"]:
        suggestions.append("Run sync_stock_financial_quarterly to populate financial reports")
    if not sections["business_segments"]:
        suggestions.append("Run sync_stock_business_segments_history to populate business data")
    if not sections["sector_memberships"]:
        suggestions.append("Run sync_stock_sector_memberships to populate sector data")
    if not sections["events"]:
        suggestions.append("Run sync_stock_notices to populate events")

    return {
        "sections": sections,
        "available": available,
        "total": total,
        "completeness": round(available / max(total, 1), 2),
        "missing_data_suggestions": suggestions,
    }
