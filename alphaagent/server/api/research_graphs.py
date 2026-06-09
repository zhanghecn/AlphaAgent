"""Research graph API routes — industry chain graph.

Provides the backend API for the dynamic industry chain graph:
  - GET /api/research/industry-chain/graph — Full chain graph
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope

router = APIRouter(prefix="/research/industry-chain", tags=["research-graphs"])


@router.get("/graph")
def industry_chain_graph(
    node_type: str | None = Query(None, description="Filter by node type"),
    stage: str | None = Query(None, description="Filter by stage"),
    min_confidence: float = Query(0.0, description="Minimum confidence"),
) -> dict[str, Any]:
    """Return the full dynamic industry chain graph."""
    if not is_database_configured():
        return {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0, "status": "unavailable"}

    from sqlalchemy import select

    with session_scope() as session:
        # Load nodes
        node_query = select(schema.industry_chain_nodes)
        if node_type:
            node_query = node_query.where(schema.industry_chain_nodes.c.node_type == node_type)
        if stage:
            node_query = node_query.where(schema.industry_chain_nodes.c.stage == stage)
        if min_confidence > 0:
            node_query = node_query.where(schema.industry_chain_nodes.c.confidence >= min_confidence)

        node_rows = session.execute(node_query).mappings().all()
        nodes = [
            {
                "id": r["id"],
                "name": r["name"],
                "node_type": r.get("node_type"),
                "stage": r.get("stage"),
                "sector_id": r.get("sector_id"),
                "vt_symbol": r.get("vt_symbol"),
                "keywords": r.get("keywords"),
                "metrics": r.get("metrics"),
                "evidence": r.get("evidence"),
                "confidence": r.get("confidence"),
            }
            for r in node_rows
        ]

        # Load edges
        node_ids = [r["id"] for r in node_rows]
        if node_ids:
            edge_rows = session.execute(
                select(schema.industry_chain_edges).where(
                    (schema.industry_chain_edges.c.source_node_id.in_(node_ids))
                    | (schema.industry_chain_edges.c.target_node_id.in_(node_ids))
                ).limit(500)
            ).mappings().all()
        else:
            edge_rows = []

        edges = [
            {
                "source": r.get("source_node_id") or r.get("source_industry_code"),
                "target": r.get("target_node_id") or r.get("target_industry_code"),
                "relation_type": r.get("relation_type") or r.get("relationship_type"),
                "score": r.get("score") or r.get("strength"),
                "evidence": r.get("evidence") or r.get("evidence_detail"),
                "confidence": r.get("confidence"),
            }
            for r in edge_rows
        ]

    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "status": "ready" if nodes else "empty",
    }
