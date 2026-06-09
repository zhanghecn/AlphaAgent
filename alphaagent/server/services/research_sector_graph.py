"""Sector relation graph algorithm — compute edges between sectors.

Reads from local PostgreSQL tables (sectors, sector_memberships,
sector_daily_bars, sector_fund_flows, stock_events) and writes
computed edges to sector_relation_edges.

Edge score formula (per plan section 7.3):
  relation_score = 0.35 * constituent_overlap
                 + 0.20 * price_correlation
                 + 0.15 * fund_correlation
                 + 0.10 * limit_up_cooccurrence
                 + 0.10 * keyword_similarity
                 + 0.10 * leader_overlap

Evidence types:
  - shared_stocks: common constituent stocks
  - co_movement: correlated price movement
  - fund_sync: synchronized fund flow direction
  - limit_up_sync: co-occurring limit-up events
  - keyword_match: name/keyword similarity
  - leader_overlap: same stock is leader in multiple sectors
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.engine import Engine

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope

logger = logging.getLogger(__name__)

# ── Edge score weights ──

W_CONSTITUENT = 0.35
W_PRICE_CORR = 0.20
W_FUND_CORR = 0.15
W_LIMIT_UP = 0.10
W_KEYWORD = 0.10
W_LEADER = 0.10

MIN_OVERLAP_FOR_EDGE = 2
MIN_SCORE_FOR_EDGE = 5.0


# ── Data classes ──

@dataclass
class SectorEdge:
    """A computed edge between two sectors."""

    source_sector_id: str
    target_sector_id: str

    score: float = 0.0
    shared_stock_count: int = 0
    shared_stock_ratio: float = 0.0
    jaccard: float = 0.0
    price_correlation: float | None = None
    fund_correlation: float | None = None
    limit_up_cooccurrence: float = 0.0
    keyword_similarity: float = 0.0
    leader_overlap: float = 0.0

    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    def is_valid(self) -> bool:
        """Check if this edge has enough evidence to be stored."""
        return (
            self.shared_stock_count >= MIN_OVERLAP_FOR_EDGE
            or self.score >= MIN_SCORE_FOR_EDGE
        )


# ── Main computation entry point ──

def compute_sector_relation_edges(
    as_of_date: date | None = None,
    period: str = "20d",
    sector_types: Sequence[str] | None = None,
    sector_limit: int = 0,
) -> list[SectorEdge]:
    """Compute relation edges between all sector pairs.

    Args:
        as_of_date: Score as of this date. Defaults to today.
        period: Lookback period (e.g., "20d").
        sector_types: Only consider these sector types (None = all).
        sector_limit: Max sectors to process (0 = all).

    Returns:
        List of valid SectorEdge objects.
    """
    if not is_database_configured():
        logger.warning("Database not configured, skipping sector relation graph")
        return []

    if as_of_date is None:
        as_of_date = date.today()

    trading_days = int(period.replace("d", "")) if period.endswith("d") else 20

    # Load sectors
    with session_scope() as session:
        query = select(schema.sectors)
        if sector_types:
            query = query.where(schema.sectors.c.type.in_(sector_types))
        sector_rows = session.execute(query).mappings().all()

    if not sector_rows:
        return []

    if sector_limit > 0:
        sector_rows = sector_rows[:sector_limit]

    sectors = [dict(r) for r in sector_rows]
    sector_ids = [str(s["id"]) for s in sectors]
    sector_by_id = {str(s["id"]): s for s in sectors}

    # ── Pre-compute data for all sectors ──

    # 1. Membership sets (sector_id -> set of vt_symbols)
    membership_sets = _load_membership_sets(sector_ids)

    # 2. Price returns (sector_id -> list of daily change_pct)
    price_series = _load_price_series(sector_ids, as_of_date, trading_days)

    # 3. Fund flows (sector_id -> latest net inflow)
    fund_flows = _load_fund_flows(sector_ids, as_of_date)

    # 4. Limit-up events per sector (sector_id -> set of vt_symbols with limit-up)
    limit_up_sets = _load_limit_up_sets(sector_ids, as_of_date)

    # 5. Leader map (sector_id -> leader_vt_symbol)
    leader_map = {
        sid: (str(sector_by_id[sid].get("leader_stock") or "") if sector_by_id[sid].get("leader_stock") else None)
        for sid in sector_ids
    }

    # 6. Sector names for keyword similarity
    name_map = {sid: str(sector_by_id[sid].get("name") or "") for sid in sector_ids}

    # ── Compute pairwise edges ──
    edges: list[SectorEdge] = []
    n = len(sector_ids)

    for i in range(n):
        for j in range(i + 1, n):
            sid_a = sector_ids[i]
            sid_b = sector_ids[j]

            edge = _compute_edge(
                sid_a, sid_b,
                membership_sets, price_series, fund_flows,
                limit_up_sets, leader_map, name_map,
                trading_days,
            )

            if edge.is_valid():
                edges.append(edge)

    return edges


def persist_edges(
    edges: list[SectorEdge],
    as_of_date: date | None = None,
    period: str = "20d",
) -> int:
    """Persist computed edges to sector_relation_edges table."""
    if not edges:
        return 0

    if as_of_date is None:
        as_of_date = date.today()

    written = 0
    with session_scope() as session:
        for edge in edges:
            values = {
                "as_of_date": as_of_date,
                "period": period,
                "source_sector_id": edge.source_sector_id,
                "target_sector_id": edge.target_sector_id,
                "score": round(edge.score, 4),
                "shared_stock_count": edge.shared_stock_count,
                "shared_stock_ratio": round(edge.shared_stock_ratio, 4),
                "jaccard": round(edge.jaccard, 4),
                "price_correlation": edge.price_correlation,
                "fund_correlation": edge.fund_correlation,
                "limit_up_cooccurrence": round(edge.limit_up_cooccurrence, 4),
                "keyword_similarity": round(edge.keyword_similarity, 4),
                "leader_overlap": round(edge.leader_overlap, 4),
                "evidence": edge.evidence,
                "confidence": round(edge.confidence, 2),
                "source": "alphaagent.sector_relation_graph",
                "computed_at": datetime.now(timezone.utc),
            }
            existing = session.execute(
                select(schema.sector_relation_edges).where(
                    (schema.sector_relation_edges.c.as_of_date == as_of_date)
                    & (schema.sector_relation_edges.c.period == period)
                    & (schema.sector_relation_edges.c.source_sector_id == edge.source_sector_id)
                    & (schema.sector_relation_edges.c.target_sector_id == edge.target_sector_id)
                )
            ).first()
            if existing:
                session.execute(
                    schema.sector_relation_edges.update()
                    .where(
                        (schema.sector_relation_edges.c.as_of_date == as_of_date)
                        & (schema.sector_relation_edges.c.period == period)
                        & (schema.sector_relation_edges.c.source_sector_id == edge.source_sector_id)
                        & (schema.sector_relation_edges.c.target_sector_id == edge.target_sector_id)
                    )
                    .values(**values)
                )
            else:
                session.execute(schema.sector_relation_edges.insert().values(**values))
            written += 1
    return written


def compute_and_persist(
    as_of_date: date | None = None,
    period: str = "20d",
    sector_types: Sequence[str] | None = None,
    sector_limit: int = 0,
) -> dict[str, Any]:
    """Compute edges and persist. Returns summary."""
    edges = compute_sector_relation_edges(as_of_date, period, sector_types, sector_limit)
    written = persist_edges(edges, as_of_date, period)
    return {
        "edges_computed": len(edges),
        "rows_written": written,
        "as_of_date": (as_of_date or date.today()).isoformat(),
        "period": period,
    }


# ── Edge computation ──

def _compute_edge(
    sid_a: str,
    sid_b: str,
    membership_sets: dict[str, set[str]],
    price_series: dict[str, list[float]],
    fund_flows: dict[str, float | None],
    limit_up_sets: dict[str, set[str]],
    leader_map: dict[str, str | None],
    name_map: dict[str, str],
    trading_days: int,
) -> SectorEdge:
    """Compute a single edge between two sectors."""
    edge = SectorEdge(source_sector_id=sid_a, target_sector_id=sid_b)

    evidence_list: list[str] = []
    confidence_factors: list[float] = []

    # 1. Constituent overlap (Jaccard + shared count)
    members_a = membership_sets.get(sid_a, set())
    members_b = membership_sets.get(sid_b, set())

    intersection = members_a & members_b
    union = members_a | members_b
    edge.shared_stock_count = len(intersection)
    edge.jaccard = len(intersection) / max(len(union), 1)
    edge.shared_stock_ratio = len(intersection) / max(min(len(members_a), len(members_b)), 1)

    # Constituent overlap score (0-100)
    overlap_score = min(edge.shared_stock_ratio * 100, 100)

    if edge.shared_stock_count > 0:
        evidence_list.append("shared_stocks")
    confidence_factors.append(min(edge.shared_stock_count / 10.0, 1.0))

    # 2. Price correlation
    series_a = price_series.get(sid_a, [])
    series_b = price_series.get(sid_b, [])

    if series_a and series_b and len(series_a) >= 5 and len(series_b) >= 5:
        corr = _pearson_correlation(series_a, series_b)
        if corr is not None:
            edge.price_correlation = round(corr, 4)
            price_score = max(0, (corr + 1) * 50)  # Map [-1, 1] to [0, 100]
            evidence_list.append("co_movement")
            confidence_factors.append(min(len(series_a) / 20.0, 1.0))
        else:
            price_score = 50.0
    else:
        price_score = 50.0

    # 3. Fund correlation
    fund_a = fund_flows.get(sid_a)
    fund_b = fund_flows.get(sid_b)

    if fund_a is not None and fund_b is not None:
        # Both positive or both negative => correlated
        same_direction = (fund_a > 0 and fund_b > 0) or (fund_a < 0 and fund_b < 0)
        fund_score = 80.0 if same_direction else 20.0
        # Scale by magnitude similarity
        magnitude_sim = 1.0 - abs(abs(fund_a) - abs(fund_b)) / max(abs(fund_a) + abs(fund_b), 1)
        fund_score = fund_score * 0.7 + magnitude_sim * 30
        edge.fund_correlation = round(magnitude_sim if same_direction else -magnitude_sim, 4)
        evidence_list.append("fund_sync")
        confidence_factors.append(0.8)
    else:
        fund_score = 50.0

    # 4. Limit-up co-occurrence
    zt_a = limit_up_sets.get(sid_a, set())
    zt_b = limit_up_sets.get(sid_b, set())
    zt_overlap = zt_a & zt_b

    if zt_a or zt_b:
        cooccurrence = len(zt_overlap) / max(len(zt_a | zt_b), 1)
        edge.limit_up_cooccurrence = round(cooccurrence, 4)
        lu_score = min(cooccurrence * 100, 100)
        if zt_overlap:
            evidence_list.append("limit_up_sync")
        confidence_factors.append(min(len(zt_a | zt_b) / 5.0, 1.0))
    else:
        lu_score = 0.0

    # 5. Keyword similarity (simple character overlap)
    name_a = name_map.get(sid_a, "")
    name_b = name_map.get(sid_b, "")
    kw_score = _keyword_similarity_score(name_a, name_b)
    edge.keyword_similarity = round(kw_score / 100.0, 4)
    if kw_score > 10:
        evidence_list.append("keyword_match")
    confidence_factors.append(0.5 if kw_score > 10 else 0.1)

    # 6. Leader overlap
    leader_a = leader_map.get(sid_a)
    leader_b = leader_map.get(sid_b)
    if leader_a and leader_b and leader_a == leader_b:
        edge.leader_overlap = 1.0
        leader_score = 100.0
        evidence_list.append("leader_overlap")
    elif leader_a and leader_a in members_b:
        edge.leader_overlap = 0.5
        leader_score = 50.0
        evidence_list.append("leader_in_other")
    elif leader_b and leader_b in members_a:
        edge.leader_overlap = 0.5
        leader_score = 50.0
        evidence_list.append("leader_in_other")
    else:
        leader_score = 0.0

    # ── Composite score ──
    edge.score = (
        W_CONSTITUENT * overlap_score
        + W_PRICE_CORR * price_score
        + W_FUND_CORR * fund_score
        + W_LIMIT_UP * lu_score
        + W_KEYWORD * kw_score
        + W_LEADER * leader_score
    )

    # ── Confidence ──
    edge.confidence = round(
        sum(confidence_factors) / max(len(confidence_factors), 1), 2
    ) if confidence_factors else 0.0

    # ── Evidence ──
    edge.evidence = {
        "shared_stocks": edge.shared_stock_count,
        "shared_symbols": sorted(list(intersection))[:10],
        "evidence_types": evidence_list,
    }

    return edge


# ── Data loaders ──

def _load_membership_sets(sector_ids: list[str]) -> dict[str, set[str]]:
    """Load membership vt_symbol sets for each sector."""
    result: dict[str, set[str]] = {sid: set() for sid in sector_ids}
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.sector_memberships.c.sector_id,
                schema.sector_memberships.c.vt_symbol,
            ).where(schema.sector_memberships.c.sector_id.in_(sector_ids))
        ).all()
    for sector_id, vt_symbol in rows:
        result.setdefault(str(sector_id), set()).add(str(vt_symbol))
    return result


def _load_price_series(
    sector_ids: list[str],
    as_of_date: date,
    trading_days: int,
) -> dict[str, list[float]]:
    """Load daily change_pct series for each sector's bars."""
    result: dict[str, list[float]] = {}
    for sid in sector_ids:
        with session_scope() as session:
            rows = session.execute(
                select(schema.sector_daily_bars.c.change_pct)
                .where(
                    (schema.sector_daily_bars.c.sector_id == sid)
                    & (schema.sector_daily_bars.c.trade_date <= as_of_date)
                )
                .order_by(desc(schema.sector_daily_bars.c.trade_date))
                .limit(trading_days)
            ).scalars().all()
        result[sid] = [float(v) for v in rows if v is not None]
    return result


def _load_fund_flows(
    sector_ids: list[str],
    as_of_date: date,
) -> dict[str, float | None]:
    """Load latest fund flow net inflow for each sector."""
    result: dict[str, float | None] = {}
    for sid in sector_ids:
        with session_scope() as session:
            row = session.execute(
                select(schema.sector_fund_flows.c.main_net_inflow)
                .where(schema.sector_fund_flows.c.sector_id == sid)
                .order_by(desc(schema.sector_fund_flows.c.trade_date))
                .limit(1)
            ).scalar()
        result[sid] = float(row) if row is not None else None
    return result


def _load_limit_up_sets(
    sector_ids: list[str],
    as_of_date: date,
) -> dict[str, set[str]]:
    """Load sets of vt_symbols that had limit-up events, per sector."""
    result: dict[str, set[str]] = {sid: set() for sid in sector_ids}
    date_str = as_of_date.isoformat()

    with session_scope() as session:
        # Get limit-up events
        events = session.execute(
            select(
                schema.stock_events.c.vt_symbol,
            ).where(
                (schema.stock_events.c.event_date == date_str)
                & (schema.stock_events.c.event_type == "limit_pool_zt")
            )
        ).scalars().all()

    if not events:
        return result

    zt_symbols = set(str(v) for v in events)

    # Map back to sectors
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.sector_memberships.c.sector_id,
                schema.sector_memberships.c.vt_symbol,
            ).where(
                (schema.sector_memberships.c.sector_id.in_(sector_ids))
                & (schema.sector_memberships.c.vt_symbol.in_(zt_symbols))
            )
        ).all()

    for sector_id, vt_symbol in rows:
        sid = str(sector_id)
        if sid in result:
            result[sid].add(str(vt_symbol))

    return result


# ── Utility functions ──

def _pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """Compute Pearson correlation coefficient between two series."""
    n = min(len(x), len(y))
    if n < 3:
        return None

    x = x[:n]
    y = y[:n]

    mean_x = sum(x) / n
    mean_y = sum(y) / n

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)

    if var_x == 0 or var_y == 0:
        return None

    return cov / math.sqrt(var_x * var_y)


def _keyword_similarity_score(name_a: str, name_b: str) -> float:
    """Compute simple keyword overlap score between two sector names.

    Uses bigram overlap as a simple measure. Returns 0-100.
    """
    if not name_a or not name_b:
        return 0.0

    # Generate character bigrams
    def bigrams(s: str) -> set[str]:
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

    bg_a = bigrams(name_a)
    bg_b = bigrams(name_b)

    if not bg_a or not bg_b:
        return 0.0

    intersection = bg_a & bg_b
    union = bg_a | bg_b

    # Jaccard on bigrams, scaled to 0-100
    jaccard = len(intersection) / max(len(union), 1)
    return jaccard * 100
