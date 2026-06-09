"""Supply chain inference service.

Infers upstream/downstream relationships between Shenwan industries by
cross-analyzing company financial report business segment data. The key
insight: if companies in Industry A and Industry B both list the same product
as a major revenue source, there is likely a supply chain relationship.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope


# Minimum revenue ratio to consider a product significant
_MIN_REVENUE_RATIO = 5.0
# Minimum number of evidence pairs to emit an edge
_MIN_EVIDENCE_COUNT = 2


def infer_supply_chain_edges(level: int = 2) -> list[dict[str, Any]]:
    """Infer supply chain edges between Shenwan industries at the given level.

    Algorithm:
    1. Load all industries at `level` and their constituent stocks from DB.
    2. For each stock, load its business segments (products + revenue ratio).
    3. Build a product-name → [(industry_code, vt_symbol, revenue_ratio)] map.
    4. For products appearing in >= 2 industries, compute cross-industry edges.
    5. Classify relationships and compute strength scores.
    """
    # Step 1: Load industries and members
    with session_scope() as session:
        industry_rows = session.execute(
            select(schema.shenwan_industries).where(schema.shenwan_industries.c.level == level)
        ).mappings().all()
        member_rows = session.execute(
            select(schema.shenwan_industry_members)
        ).mappings().all()

    if not industry_rows or not member_rows:
        return []

    # Build industry_code -> set(vt_symbol) map
    industry_by_code: dict[str, dict[str, Any]] = {
        str(row["code"]): dict(row) for row in industry_rows
    }
    members_by_industry: dict[str, list[str]] = defaultdict(list)
    for row in member_rows:
        members_by_industry[str(row["industry_code"])].append(str(row["vt_symbol"]))

    # Step 2: Load business segments for all member stocks
    all_symbols = set()
    for symbols in members_by_industry.values():
        all_symbols.update(symbols)

    with session_scope() as session:
        segment_rows = session.execute(
            select(schema.stock_business_segments)
            .where(schema.stock_business_segments.c.vt_symbol.in_(all_symbols))
        ).mappings().all()

    # Build vt_symbol -> [{segment_name, revenue_ratio}]
    segments_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in segment_rows:
        symbol = str(row["vt_symbol"])
        ratio = _float_value(row.get("revenue_ratio"))
        name = str(row.get("segment_name") or "").strip()
        if not name or ratio is None or ratio < _MIN_REVENUE_RATIO:
            continue
        segments_by_symbol[symbol].append({
            "name": name,
            "revenue_ratio": ratio,
            "report_date": str(row.get("report_date") or ""),
        })

    # Step 3: Build product → industry map
    product_map: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for industry_code, symbols in members_by_industry.items():
        if industry_code not in industry_by_code:
            continue
        for symbol in symbols:
            for segment in segments_by_symbol.get(symbol, []):
                # Normalize and split product names into atomic terms
                for product in _normalize_and_split(segment["name"]):
                    product_map[product].append(
                        (industry_code, symbol, segment["revenue_ratio"])
                    )

    # Step 4: Compute cross-industry edges
    edges = _compute_edges(product_map, industry_by_code, level)
    return edges


def infer_edges_for_industry(industry_code: str, level: int = 2) -> list[dict[str, Any]]:
    """Focused version: compute edges only for a single industry and its neighbors."""

    # Get the industry's member symbols
    with session_scope() as session:
        members = session.execute(
            select(schema.shenwan_industry_members.c.vt_symbol)
            .where(schema.shenwan_industry_members.c.industry_code == industry_code)
        ).scalars().all()

    if not members:
        return []

    # Load segments for these stocks
    with session_scope() as session:
        segment_rows = session.execute(
            select(schema.stock_business_segments)
            .where(schema.stock_business_segments.c.vt_symbol.in_(set(members)))
        ).mappings().all()

    # Build product terms for this industry
    products: set[str] = set()
    for row in segment_rows:
        ratio = _float_value(row.get("revenue_ratio"))
        name = str(row.get("segment_name") or "").strip()
        if name and ratio is not None and ratio >= _MIN_REVENUE_RATIO:
            products.update(_normalize_and_split(name))

    if not products:
        return []

    # Find other industries whose stocks also have these products
    # Use a simplified approach: find stocks with matching segments
    product_like_conditions = []
    for product in list(products)[:30]:
        product_like_conditions.append(schema.stock_business_segments.c.segment_name.contains(product))

    if not product_like_conditions:
        return []

    from sqlalchemy import or_
    with session_scope() as session:
        matching_segments = session.execute(
            select(schema.stock_business_segments)
            .where(or_(*product_like_conditions))
            .limit(500)
        ).mappings().all()

    # Get industry memberships for matching stocks
    matching_symbols = {str(row["vt_symbol"]) for row in matching_segments}
    if not matching_symbols:
        return []

    with session_scope() as session:
        matching_members = session.execute(
            select(schema.shenwan_industry_members)
            .where(schema.shenwan_industry_members.c.vt_symbol.in_(matching_symbols))
        ).mappings().all()
        related_industries = session.execute(
            select(schema.shenwan_industries).where(schema.shenwan_industries.c.level == level)
        ).mappings().all()

    # Now run the full inference for just these industries
    industry_by_code = {str(row["code"]): dict(row) for row in related_industries}
    members_by_industry: dict[str, list[str]] = defaultdict(list)
    for row in matching_members:
        members_by_industry[str(row["industry_code"])].append(str(row["vt_symbol"]))
    # Make sure the focus industry is included
    for symbol in members:
        members_by_industry.setdefault(industry_code, []).append(str(symbol))

    # Build product map from matching segments
    product_map: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    segments_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in matching_segments:
        symbol = str(row["vt_symbol"])
        ratio = _float_value(row.get("revenue_ratio"))
        name = str(row.get("segment_name") or "").strip()
        if name and ratio is not None and ratio >= _MIN_REVENUE_RATIO:
            segments_by_symbol[symbol].append({"name": name, "revenue_ratio": ratio})

    for industry_code_key, symbols in members_by_industry.items():
        if industry_code_key not in industry_by_code:
            continue
        for symbol in symbols:
            for segment in segments_by_symbol.get(symbol, []):
                for product in _normalize_and_split(segment["name"]):
                    product_map[product].append(
                        (industry_code_key, symbol, segment["revenue_ratio"])
                    )

    return _compute_edges(product_map, industry_by_code, level)


def _compute_edges(
    product_map: dict[str, list[tuple[str, str, float]]],
    industry_by_code: dict[str, dict[str, Any]],
    level: int,
) -> list[dict[str, Any]]:
    """Compute supply chain edges from the product-to-industry map."""

    # For each product appearing in >= 2 industries, generate candidate edges
    edge_accumulator: dict[tuple[str, str], dict[str, Any]] = {}

    for product, entries in product_map.items():
        if len(entries) < 2:
            continue

        # Group by industry
        by_industry: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for industry_code, vt_symbol, revenue_ratio in entries:
            by_industry[industry_code].append((vt_symbol, revenue_ratio))

        if len(by_industry) < 2:
            continue

        # For each pair of industries sharing this product
        industry_codes = list(by_industry.keys())
        for left_index in range(len(industry_codes)):
            for right_index in range(left_index + 1, len(industry_codes)):
                left_code = industry_codes[left_index]
                right_code = industry_codes[right_index]

                left_entries = by_industry[left_code]
                right_entries = by_industry[right_code]

                # Determine direction based on industry characteristics
                source_code, target_code = _determine_direction(
                    left_code, right_code,
                    industry_by_code.get(left_code, {}),
                    industry_by_code.get(right_code, {}),
                    product,
                )

                # Accumulate evidence
                key = (source_code, target_code)
                if key not in edge_accumulator:
                    edge_accumulator[key] = {
                        "source_industry_code": source_code,
                        "target_industry_code": target_code,
                        "relationship_type": _classify_relationship(product),
                        "strength": 0.0,
                        "evidence_count": 0,
                        "evidence_detail": [],
                        "level": level,
                    }

                edge = edge_accumulator[key]
                edge["evidence_count"] += len(left_entries) + len(right_entries)

                # Add evidence details (limit to avoid huge payloads)
                for left_sym, left_ratio in left_entries[:3]:
                    for right_sym, right_ratio in right_entries[:3]:
                        if len(edge["evidence_detail"]) < 8:
                            edge["evidence_detail"].append({
                                "source_stock": left_sym,
                                "target_stock": right_sym,
                                "product": product,
                                "revenue_ratio": round((left_ratio + right_ratio) / 2, 2),
                            })

                # Accumulate strength
                for _, ratio in left_entries:
                    edge["strength"] += ratio
                for _, ratio in right_entries:
                    edge["strength"] += ratio

    # Normalize strength to 0-1 range and filter by minimum evidence
    if not edge_accumulator:
        return []

    max_strength = max(edge["strength"] for edge in edge_accumulator.values()) or 1.0
    result = []
    for edge in edge_accumulator.values():
        if edge["evidence_count"] < _MIN_EVIDENCE_COUNT:
            continue
        edge["strength"] = round(min(edge["strength"] / max_strength, 1.0), 4)
        edge["source"] = "alphaagent_supply_chain_inference"
        result.append(edge)

    # Sort by strength descending
    result.sort(key=lambda e: (-e["strength"], e["source_industry_code"]))
    return result


def _determine_direction(
    left_code: str,
    right_code: str,
    left_industry: dict[str, Any],
    right_industry: dict[str, Any],
    product: str,
) -> tuple[str, str]:
    """Determine upstream/downstream direction between two industries.

    Uses industry name heuristics and common supply chain patterns.
    Returns (source/upstream_code, target/downstream_code).
    """
    left_name = str(left_industry.get("name") or "").lower()
    right_name = str(right_industry.get("name") or "").lower()

    # Common upstream keywords (raw materials, extraction)
    upstream_keywords = {"采掘", "化工", "有色金属", "钢铁", "煤炭", "石油", "矿业", "材料"}
    # Common downstream keywords (end products, services)
    downstream_keywords = {"汽车", "家电", "食品", "饮料", "医药", "电子", "通信", "计算机", "传媒", "零售", " consumer"}

    left_is_upstream = any(kw in left_name for kw in upstream_keywords)
    right_is_upstream = any(kw in right_name for kw in upstream_keywords)
    left_is_downstream = any(kw in left_name for kw in downstream_keywords)
    right_is_downstream = any(kw in right_name for kw in downstream_keywords)

    if left_is_upstream and not right_is_upstream:
        return left_code, right_code
    if right_is_upstream and not left_is_upstream:
        return right_code, left_code
    if left_is_downstream and not right_is_downstream:
        return right_code, left_code
    if right_is_downstream and not left_is_downstream:
        return left_code, right_code

    # Default: alphabetical order for determinism
    if left_code < right_code:
        return left_code, right_code
    return right_code, left_code


def _classify_relationship(product: str) -> str:
    """Classify the supply chain relationship type based on product name."""

    text = product.lower()

    raw_material_terms = {"矿", "盐", "酸", "碱", "油", "气", "煤", "铁", "铜", "铝", "锂", "钴", "镍", "硅", "树脂", "橡胶", "纤维", "钢", "金属", "纸浆", "原油", "原片"}
    if any(term in text for term in raw_material_terms):
        return "raw_material"

    intermediate_terms = {"芯片", "模组", "组件", "零件", "配件", "板材", "管材", "线缆", "电机", "轴承", "齿轮", "密封", "涂料", "胶粘", "添加剂"}
    if any(term in text for term in intermediate_terms):
        return "intermediate"

    core_terms = {"电池", "发动机", "显示屏", "传感器", "处理器", "控制器", "变频器", "逆变器", "激光器", "光模块", "天线", "滤波器"}
    if any(term in text for term in core_terms):
        return "core_component"

    return "end_product"


def _normalize_and_split(name: str) -> list[str]:
    """Normalize a product/segment name and split into atomic search terms."""

    text = name.strip()
    if not text:
        return []

    # Remove common suffixes
    for suffix in ("业务", "产品", "服务", "销售", "制造", "生产", "收入", "板块", "收入占比"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]

    text = text.strip()
    if len(text) < 2:
        return []

    # Split on common delimiters
    parts = re.split(r"[、，,/\s·&与及和]+", text)
    # Filter short tokens and dedupe
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        part = part.strip()
        if len(part) >= 2 and part not in seen:
            seen.add(part)
            result.append(part)

    return result


def _float_value(value: Any) -> float | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None
