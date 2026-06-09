"""Dynamic industry chain graph — entity extraction + relationship scoring.

Builds a dynamic industry chain graph from:
  - Sector names and types
  - Stock business segments
  - Stock-sector memberships
  - Existing industry chain edges (from Shenwan supply chain inference)

Design constraints:
  - NO hardcoded industry templates or fixed upstream/downstream mappings.
  - Stage inference (upstream/midstream/downstream) is evidence-based.
  - When evidence is insufficient, stage = "unknown" and confidence is low.
  - Every node and edge includes evidence and confidence.

Node sources:
  1. Sectors (from sectors table)
  2. Business segments (from stock_business_segments, aggregated)
  3. Stock entities (from stocks table, via sector membership)

Edge sources:
  1. Existing industry_chain_edges (Shenwan-based)
  2. Shared membership (stocks in multiple sectors)
  3. Business segment overlap (companies doing similar things)
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.engine import Engine

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, is_database_configured, session_scope

logger = logging.getLogger(__name__)

# ── Constants ──

NODE_TYPE_SECTOR = "sector"
NODE_TYPE_SEGMENT = "segment"
NODE_TYPE_STOCK = "stock"

STAGE_UPSTREAM = "upstream"
STAGE_MIDSTREAM = "midstream"
STAGE_DOWNSTREAM = "downstream"
STAGE_SERVICE = "service"
STAGE_APPLICATION = "application"
STAGE_UNKNOWN = "unknown"

RELATION_MEMBER_OF = "member_of"
RELATION_SUPPLY_TO = "supply_to"
RELATION_COMPETE_WITH = "compete_with"
RELATION_CO_OCCUR = "co_occur"
RELATION_SIMILAR_BUSINESS = "similar_business"
RELATION_CHAIN_LINK = "chain_link"

# ── Data classes ──


@dataclass
class ChainNode:
    """A node in the industry chain graph."""

    id: str
    name: str
    node_type: str  # sector, segment, stock
    stage: str = STAGE_UNKNOWN
    sector_id: str | None = None
    vt_symbol: str | None = None
    keywords: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class ChainEdge:
    """An edge in the industry chain graph."""

    source_node_id: str
    target_node_id: str
    relation_type: str
    score: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


# ── Main entry point ──

def compute_industry_chain_graph(
    as_of_date: date | None = None,
    sector_types: Sequence[str] | None = None,
    sector_limit: int = 0,
) -> tuple[list[ChainNode], list[ChainEdge]]:
    """Build a dynamic industry chain graph from available data.

    Returns:
        Tuple of (nodes, edges).
    """
    if not is_database_configured():
        logger.warning("Database not configured, skipping chain graph")
        return [], []

    if as_of_date is None:
        as_of_date = date.today()

    # ── Step 1: Extract nodes ──
    nodes: list[ChainNode] = []
    nodes_by_id: dict[str, ChainNode] = {}

    # 1a. Sector nodes
    sector_nodes = _extract_sector_nodes(sector_types, sector_limit)
    for node in sector_nodes:
        nodes.append(node)
        nodes_by_id[node.id] = node

    # 1b. Business segment nodes (aggregated across stocks)
    segment_nodes = _extract_segment_nodes(list(nodes_by_id.keys()))
    for node in segment_nodes:
        if node.id not in nodes_by_id:
            nodes.append(node)
            nodes_by_id[node.id] = node

    # 1c. Stock nodes (top members from key sectors)
    stock_nodes = _extract_stock_nodes(list(nodes_by_id.keys()), limit=50)
    for node in stock_nodes:
        if node.id not in nodes_by_id:
            nodes.append(node)
            nodes_by_id[node.id] = node

    # ── Step 2: Build edges ──
    edges: list[ChainEdge] = []

    # 2a. Stock-sector membership edges
    membership_edges = _build_membership_edges(stock_nodes, sector_nodes)
    edges.extend(membership_edges)

    # 2b. Segment-sector edges
    seg_edges = _build_segment_edges(segment_nodes, sector_nodes)
    edges.extend(seg_edges)

    # 2c. Existing industry chain edges (from supply chain inference)
    chain_edges = _build_chain_edges(sector_nodes, as_of_date)
    edges.extend(chain_edges)

    # 2d. Co-occurrence edges (shared stocks between sectors)
    cooc_edges = _build_cooccurrence_edges(sector_nodes)
    edges.extend(cooc_edges)

    # ── Step 3: Infer stages ──
    _infer_stages(nodes_by_id, edges)

    return nodes, edges


def persist_chain_graph(
    nodes: list[ChainNode],
    edges: list[ChainEdge],
    as_of_date: date | None = None,
) -> dict[str, int]:
    """Persist nodes and edges to DB. Returns {nodes_written, edges_written}."""
    if as_of_date is None:
        as_of_date = date.today()

    nodes_written = 0
    edges_written = 0

    # Persist nodes
    with session_scope() as session:
        for node in nodes:
            values = {
                "id": node.id,
                "as_of_date": as_of_date,
                "name": node.name,
                "node_type": node.node_type,
                "stage": node.stage,
                "sector_id": node.sector_id,
                "vt_symbol": node.vt_symbol,
                "keywords": node.keywords,
                "metrics": node.metrics,
                "evidence": node.evidence,
                "confidence": node.confidence,
                "source": "alphaagent.chain_graph",
            }
            existing = session.execute(
                select(schema.industry_chain_nodes).where(
                    schema.industry_chain_nodes.c.id == node.id
                )
            ).first()
            if existing:
                session.execute(
                    schema.industry_chain_nodes.update()
                    .where(schema.industry_chain_nodes.c.id == node.id)
                    .values(**values)
                )
            else:
                session.execute(schema.industry_chain_nodes.insert().values(**values))
            nodes_written += 1

    # Persist edges
    with session_scope() as session:
        for edge in edges:
            values = {
                "as_of_date": as_of_date,
                "period": "dynamic",
                "source_node_id": edge.source_node_id,
                "target_node_id": edge.target_node_id,
                "relation_type": edge.relation_type,
                "score": edge.score,
                "evidence": edge.evidence,
                "confidence": edge.confidence,
                "source": "alphaagent.chain_graph",
            }
            # Use the existing industry_chain_edges table with source/target node IDs
            session.execute(
                schema.industry_chain_edges.insert().values(
                    source_industry_code=edge.source_node_id[:32] if len(edge.source_node_id) > 32 else edge.source_node_id,
                    target_industry_code=edge.target_node_id[:32] if len(edge.target_node_id) > 32 else edge.target_node_id,
                    relationship_type=edge.relation_type,
                    strength=edge.score,
                    evidence_count=1,
                    evidence_detail=[edge.evidence],
                    level=0,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    relation_type=edge.relation_type,
                    score=edge.score,
                    evidence=edge.evidence,
                    confidence=edge.confidence,
                    source="alphaagent.chain_graph",
                )
            )
            edges_written += 1

    return {"nodes_written": nodes_written, "edges_written": edges_written}


def compute_and_persist(
    as_of_date: date | None = None,
    sector_types: Sequence[str] | None = None,
    sector_limit: int = 0,
) -> dict[str, Any]:
    """Compute and persist chain graph. Returns summary."""
    nodes, edges = compute_industry_chain_graph(as_of_date, sector_types, sector_limit)
    stats = persist_chain_graph(nodes, edges, as_of_date)
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "nodes_written": stats["nodes_written"],
        "edges_written": stats["edges_written"],
        "as_of_date": (as_of_date or date.today()).isoformat(),
    }


# ── Node extraction ──

def _extract_sector_nodes(
    sector_types: Sequence[str] | None = None,
    sector_limit: int = 0,
) -> list[ChainNode]:
    """Create nodes from sectors table."""
    with session_scope() as session:
        query = select(schema.sectors)
        if sector_types:
            query = query.where(schema.sectors.c.type.in_(sector_types))
        rows = session.execute(query).mappings().all()

    if sector_limit > 0:
        rows = rows[:sector_limit]

    nodes: list[ChainNode] = []
    for row in rows:
        sector_id = str(row["id"])
        name = str(row["name"] or sector_id)
        node = ChainNode(
            id=f"s:{sector_id}",
            name=name,
            node_type=NODE_TYPE_SECTOR,
            sector_id=sector_id,
            keywords=_extract_keywords(name),
            metrics={
                "stock_count": row.get("stock_count"),
                "change_pct": row.get("change_pct"),
                "type": row.get("type"),
            },
            evidence={"source": "sectors_table"},
            confidence=1.0,
        )
        nodes.append(node)

    return nodes


def _extract_segment_nodes(
    sector_node_ids: list[str],
) -> list[ChainNode]:
    """Create nodes from aggregated business segments."""
    # Extract sector IDs from node IDs (format: "s:BK0001")
    sector_ids = [nid[2:] for nid in sector_node_ids if nid.startswith("s:")]

    if not sector_ids:
        return []

    # Get member vt_symbols for these sectors
    with session_scope() as session:
        member_rows = session.execute(
            select(schema.sector_memberships.c.vt_symbol)
            .where(schema.sector_memberships.c.sector_id.in_(sector_ids))
        ).scalars().all()

    if not member_rows:
        return []

    vt_symbols = list(set(str(v) for v in member_rows))

    # Get distinct segment names, limited
    with session_scope() as session:
        seg_rows = session.execute(
            select(
                schema.stock_business_segments.c.segment_name,
                func.count(func.distinct(schema.stock_business_segments.c.vt_symbol)).label("stock_count"),
                func.avg(schema.stock_business_segments.c.revenue_ratio).label("avg_revenue_ratio"),
            )
            .where(schema.stock_business_segments.c.vt_symbol.in_(vt_symbols))
            .group_by(schema.stock_business_segments.c.segment_name)
            .order_by(desc("stock_count"))
            .limit(100)
        ).all()

    nodes: list[ChainNode] = []
    for seg_name, stock_count, avg_ratio in seg_rows:
        seg_name_str = str(seg_name)
        if not seg_name_str or len(seg_name_str) < 2:
            continue
        node_id = f"seg:{_stable_id(seg_name_str)}"
        node = ChainNode(
            id=node_id,
            name=seg_name_str,
            node_type=NODE_TYPE_SEGMENT,
            keywords=_extract_keywords(seg_name_str),
            metrics={
                "stock_count": int(stock_count),
                "avg_revenue_ratio": float(avg_ratio) if avg_ratio else None,
            },
            evidence={"source": "business_segments_aggregation"},
            confidence=0.7,
        )
        nodes.append(node)

    return nodes


def _extract_stock_nodes(
    sector_node_ids: list[str],
    limit: int = 50,
) -> list[ChainNode]:
    """Create nodes for top stocks by market cap in these sectors."""
    sector_ids = [nid[2:] for nid in sector_node_ids if nid.startswith("s:")]
    if not sector_ids:
        return []

    with session_scope() as session:
        rows = session.execute(
            select(
                schema.sector_memberships.c.vt_symbol,
                schema.sector_memberships.c.name,
                schema.sector_memberships.c.market_cap,
                schema.sector_memberships.c.change_pct,
            )
            .where(schema.sector_memberships.c.sector_id.in_(sector_ids))
            .order_by(desc(schema.sector_memberships.c.market_cap))
            .limit(limit)
        ).mappings().all()

    # Deduplicate by vt_symbol (keep highest market cap)
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        vts = str(row["vt_symbol"])
        if vts not in seen or (row.get("market_cap") or 0) > (seen[vts].get("market_cap") or 0):
            seen[vts] = dict(row)

    nodes: list[ChainNode] = []
    for vts, data in seen.items():
        name = str(data.get("name") or vts)
        node = ChainNode(
            id=f"stk:{vts}",
            name=name,
            node_type=NODE_TYPE_STOCK,
            vt_symbol=vts,
            keywords=_extract_keywords(name),
            metrics={
                "market_cap": data.get("market_cap"),
                "change_pct": data.get("change_pct"),
            },
            evidence={"source": "sector_memberships"},
            confidence=1.0,
        )
        nodes.append(node)

    return nodes


# ── Edge builders ──

def _build_membership_edges(
    stock_nodes: list[ChainNode],
    sector_nodes: list[ChainNode],
) -> list[ChainEdge]:
    """Build edges connecting stocks to their sectors."""
    sector_by_real_id: dict[str, ChainNode] = {}
    for sn in sector_nodes:
        if sn.sector_id:
            sector_by_real_id[sn.sector_id] = sn

    edges: list[ChainEdge] = []
    for stock in stock_nodes:
        if not stock.vt_symbol:
            continue
        # Find which sectors this stock belongs to
        with session_scope() as session:
            memberships = session.execute(
                select(schema.stock_sector_memberships.c.sector_id)
                .where(schema.stock_sector_memberships.c.vt_symbol == stock.vt_symbol)
                .limit(10)
            ).scalars().all()

        for sector_id in memberships:
            sector_node = sector_by_real_id.get(str(sector_id))
            if sector_node:
                edges.append(ChainEdge(
                    source_node_id=stock.id,
                    target_node_id=sector_node.id,
                    relation_type=RELATION_MEMBER_OF,
                    score=1.0,
                    evidence={"vt_symbol": stock.vt_symbol, "sector_id": str(sector_id)},
                    confidence=1.0,
                ))

    return edges


def _build_segment_edges(
    segment_nodes: list[ChainNode],
    sector_nodes: list[ChainNode],
) -> list[ChainEdge]:
    """Build edges connecting segments to sectors via stock membership."""
    sector_by_real_id: dict[str, ChainNode] = {}
    for sn in sector_nodes:
        if sn.sector_id:
            sector_by_real_id[sn.sector_id] = sn

    edges: list[ChainEdge] = []

    # For each segment, find which sectors its stocks belong to
    for seg_node in segment_nodes:
        seg_name = seg_node.name

        with session_scope() as session:
            # Get stocks with this segment
            stock_vts = session.execute(
                select(func.distinct(schema.stock_business_segments.c.vt_symbol))
                .where(schema.stock_business_segments.c.segment_name == seg_name)
                .limit(50)
            ).scalars().all()

        if not stock_vts:
            continue

        # Find sectors for these stocks
        with session_scope() as session:
            sector_counts: dict[str, int] = defaultdict(int)
            rows = session.execute(
                select(schema.stock_sector_memberships.c.sector_id)
                .where(schema.stock_sector_memberships.c.vt_symbol.in_(
                    [str(v) for v in stock_vts]
                ))
            ).scalars().all()
            for sid in rows:
                sector_counts[str(sid)] += 1

        # Connect segment to top sectors
        for sector_id, count in sorted(sector_counts.items(), key=lambda x: -x[1])[:5]:
            sector_node = sector_by_real_id.get(sector_id)
            if sector_node and count >= 2:
                score = min(count / max(len(stock_vts), 1), 1.0)
                edges.append(ChainEdge(
                    source_node_id=seg_node.id,
                    target_node_id=sector_node.id,
                    relation_type=RELATION_SIMILAR_BUSINESS,
                    score=round(score, 4),
                    evidence={
                        "segment_name": seg_name,
                        "sector_id": sector_id,
                        "shared_stocks": count,
                    },
                    confidence=0.6,
                ))

    return edges


def _build_chain_edges(
    sector_nodes: list[ChainNode],
    as_of_date: date,
) -> list[ChainEdge]:
    """Import existing industry chain edges from supply chain inference."""
    sector_by_code: dict[str, ChainNode] = {}
    for sn in sector_nodes:
        if sn.sector_id:
            sector_by_code[sn.sector_id] = sn

    edges: list[ChainEdge] = []

    with session_scope() as session:
        rows = session.execute(
            select(schema.industry_chain_edges)
            .where(schema.industry_chain_edges.c.source == "alphaagent_supply_chain_inference")
        ).mappings().all()

    for row in rows:
        src_code = str(row["source_industry_code"])
        tgt_code = str(row["target_industry_code"])

        # Map to sector nodes - may not match directly, try via industry_board_mapping
        src_node = sector_by_code.get(src_code)
        tgt_node = sector_by_code.get(tgt_code)

        # If not direct match, try mapping via board mapping
        if not src_node:
            src_node = _resolve_industry_to_sector(src_code, sector_by_code)
        if not tgt_node:
            tgt_node = _resolve_industry_to_sector(tgt_code, sector_by_code)

        if src_node and tgt_node:
            edges.append(ChainEdge(
                source_node_id=src_node.id,
                target_node_id=tgt_node.id,
                relation_type=RELATION_CHAIN_LINK,
                score=float(row.get("strength") or 0),
                evidence={
                    "relationship_type": row.get("relationship_type"),
                    "evidence_count": row.get("evidence_count"),
                    "level": row.get("level"),
                },
                confidence=0.5,
            ))

    return edges


def _build_cooccurrence_edges(
    sector_nodes: list[ChainNode],
) -> list[ChainEdge]:
    """Build edges between sectors that share member stocks."""
    sector_by_real_id: dict[str, ChainNode] = {}
    for sn in sector_nodes:
        if sn.sector_id:
            sector_by_real_id[sn.sector_id] = sn

    sector_ids = list(sector_by_real_id.keys())
    edges: list[ChainEdge] = []

    # For each stock, find its sectors, then connect those sectors
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_sector_memberships.c.vt_symbol,
                schema.stock_sector_memberships.c.sector_id,
            )
        ).all()

    stock_to_sectors: dict[str, list[str]] = defaultdict(list)
    for vts, sid in rows:
        stock_to_sectors[str(vts)].append(str(sid))

    # Count co-occurrences
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for vts, sids in stock_to_sectors.items():
        for i, sid_a in enumerate(sids):
            for sid_b in sids[i + 1:]:
                pair = tuple(sorted([sid_a, sid_b]))
                pair_counts[pair] += 1

    # Create edges for significant pairs
    for (sid_a, sid_b), count in pair_counts.items():
        if count < 3:
            continue
        node_a = sector_by_real_id.get(sid_a)
        node_b = sector_by_real_id.get(sid_b)
        if node_a and node_b:
            edges.append(ChainEdge(
                source_node_id=node_a.id,
                target_node_id=node_b.id,
                relation_type=RELATION_CO_OCCUR,
                score=min(count / 10.0, 1.0),
                evidence={"shared_stock_count": count},
                confidence=0.4,
            ))

    return edges


# ── Stage inference ──

def _infer_stages(
    nodes_by_id: dict[str, ChainNode],
    edges: list[ChainEdge],
) -> None:
    """Infer upstream/midstream/downstream stage for sector nodes.

    Uses heuristic keyword matching and edge structure.
    Confidence is low when based only on keywords.
    """
    # Stage keyword hints (NOT a fixed template, just weak evidence)
    UPSTREAM_HINTS = {"原材料", "资源", "矿产", "开采", "芯片设计", "IP", "知识产权", "基础", "上游"}
    MIDSTREAM_HINTS = {"制造", "加工", "生产", "组装", "封装", "中游", "工艺"}
    DOWNSTREAM_HINTS = {"终端", "消费", "应用", "零售", "品牌", "渠道", "服务", "下游"}
    SERVICE_HINTS = {"金融", "物流", "软件", "平台", "云计算", "数据", "咨询"}

    for node in nodes_by_id.values():
        if node.node_type != NODE_TYPE_SECTOR:
            continue

        name = node.name
        hints = set()

        for keyword in node.keywords:
            if keyword in UPSTREAM_HINTS:
                hints.add(STAGE_UPSTREAM)
            if keyword in MIDSTREAM_HINTS:
                hints.add(STAGE_MIDSTREAM)
            if keyword in DOWNSTREAM_HINTS:
                hints.add(STAGE_DOWNSTREAM)
            if keyword in SERVICE_HINTS:
                hints.add(STAGE_SERVICE)

        # Also check name directly for common patterns
        for hint_words, stage in [
            (UPSTREAM_HINTS, STAGE_UPSTREAM),
            (MIDSTREAM_HINTS, STAGE_MIDSTREAM),
            (DOWNSTREAM_HINTS, STAGE_DOWNSTREAM),
            (SERVICE_HINTS, STAGE_SERVICE),
        ]:
            for word in hint_words:
                if word in name:
                    hints.add(stage)

        if len(hints) == 1:
            node.stage = hints.pop()
            node.confidence = 0.4  # Low confidence for keyword-only inference
            node.evidence["stage_source"] = "keyword_hint"
        elif len(hints) > 1:
            # Conflicting evidence, stay unknown
            node.stage = STAGE_UNKNOWN
            node.evidence["stage_hints"] = list(hints)
            node.evidence["stage_source"] = "ambiguous_keywords"
        # else: remains UNKNOWN with default confidence


# ── Utility functions ──

def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text."""
    if not text:
        return []

    # Remove common suffixes
    cleaned = re.sub(r"(板块|概念|行业|概念股|主题|指数|ETF|概念)$", "", text.strip())

    keywords: list[str] = []
    # Use the full name as a keyword
    if cleaned and len(cleaned) >= 2:
        keywords.append(cleaned)

    # Extract 2-char substrings as additional keywords
    if len(cleaned) >= 4:
        for i in range(len(cleaned) - 1):
            bigram = cleaned[i:i + 2]
            if bigram not in keywords:
                keywords.append(bigram)

    return keywords[:10]


def _stable_id(text: str) -> str:
    """Generate a stable short ID from text."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _resolve_industry_to_sector(
    industry_code: str,
    sector_by_code: dict[str, ChainNode],
) -> ChainNode | None:
    """Try to resolve a Shenwan industry code to a sector node via board mapping."""
    with session_scope() as session:
        row = session.execute(
            select(schema.industry_board_mapping.c.board_id)
            .where(schema.industry_board_mapping.c.industry_code == industry_code)
            .limit(1)
        ).scalar()

    if row:
        return sector_by_code.get(str(row))
    return None
