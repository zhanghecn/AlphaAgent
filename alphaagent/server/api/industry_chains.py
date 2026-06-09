"""Industry-chain endpoints."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.market.cache import market_cache
from alphaagent.market.providers import RealMarketDataClient
from alphaagent.server.core.config import get_settings
from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.data_sync import local_sector_relation_graph, local_sector_stub_graph

router = APIRouter(prefix="/industry-chains", tags=["industry-chains"])

STAGE_DEFS = (
    ("source", "源头板块"),
    ("bridge", "桥接板块"),
    ("sink", "扩散板块"),
)

SECTOR_DISCOVERY_GROUP_DEFS = {
    "mainline_watch": {
        "title": "主线观察",
        "description": "按真实板块活动字段筛出的候选入口，先看持续性和成分扩散。",
    },
    "industry": {
        "title": "行业板块",
        "description": "更接近公司主营归属，适合做产业和同行比较。",
    },
    "theme": {
        "title": "题材概念",
        "description": "更接近市场交易题材，需要结合成分股和关系图验证。",
    },
    "style_status": {
        "title": "风格/状态",
        "description": "市值规模、价格状态、财报事件或交易状态，不是一条产业链。",
    },
    "region": {
        "title": "地域板块",
        "description": "地域归属，主要观察区域政策和本地产业集群。",
    },
}

STYLE_STATUS_KEYWORDS = (
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


def client() -> RealMarketDataClient:
    settings = get_settings()
    return RealMarketDataClient(timeout=settings.market_timeout_seconds)


@router.get("")
def list_industry_chains():
    market_client = client()
    try:
        key = "dynamic_industry_chains:12:40"
        payload = market_cache.get_or_set(
            key,
            300,
            lambda: discover_dynamic_industry_chains(market_client, limit=12, page_size=40),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "DYNAMIC_INDUSTRY_CHAINS_UNAVAILABLE",
                "动态产业链发现暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )
    return ok(payload)


@router.get("/graph")
def sector_relation_graph(
    q: str = Query(default=""),
    limit: int = Query(default=12, ge=4, le=18),
    page_size: int = Query(default=50, ge=20, le=80),
    deep: bool = Query(default=False),
):
    query = q.strip()
    market_client = client()
    try:
        key = f"sector_relation_graph:{query}:{limit}:{page_size}:deep={deep}"
        payload = market_cache.get_or_set(
            key,
            300,
            lambda: build_sector_relation_graph(market_client, query, limit=limit, page_size=page_size, deep=deep),
        )
    except Exception as exc:
        payload = build_unavailable_sector_graph(query, exc, limit=limit, page_size=page_size)
    return ok(payload)


@router.get("/{chain_id}/map")
def industry_chain_map(
    chain_id: str,
    page_size: int = Query(default=20, ge=5, le=50),
    deep: bool = Query(default=False),
):
    market_client = client()
    try:
        key = f"dynamic_industry_chain_map:{chain_id}:{page_size}:deep={deep}"
        payload = market_cache.get_or_set(
            key,
            600,
            lambda: build_dynamic_chain_map(market_client, chain_id, page_size=page_size, deep=deep),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "INDUSTRY_CHAIN_MAP_UNAVAILABLE",
                "真实产业链链路图数据暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )
    return ok(payload)


@router.get("/{chain_id}/stocks")
def industry_chain_stocks(
    chain_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
):
    market_client = client()
    try:
        key = f"dynamic_industry_chain_stocks:{chain_id}:{page_size}"
        data = market_cache.get_or_set(
            key,
            600,
            lambda: _load_dynamic_chain_stock_payload(market_client, chain_id, page_size),
        )
        related_sectors = data["related_sectors"]
        items = data["items"]
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "INDUSTRY_CHAIN_SOURCE_UNAVAILABLE",
                "真实产业链板块成分股暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )

    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return ok(
        {
            "chain_id": data["chain_id"],
            "name": data["name"],
            "items": page_items,
            "related_sectors": related_sectors,
            "page": page,
            "page_size": page_size,
            "total": len(items),
            "status": "ready" if page_items else "empty",
            "source": "eastmoney.push2.board,alphaagent_dynamic_graph",
        }
    )


@router.get("/{chain_id}")
def industry_chain_detail(chain_id: str):
    try:
        return ok(build_dynamic_chain_map(client(), chain_id, page_size=20))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "DYNAMIC_INDUSTRY_CHAIN_UNAVAILABLE",
                "动态产业链详情暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )


def build_sector_search(market_client: RealMarketDataClient, query: str, limit: int = 20) -> dict[str, Any]:
    """Search real boards only; no static industry-chain templates."""

    limit = min(max(limit, 1), 50)
    normalized_query = _normalize_for_match(query)
    sector_status = "ready"
    try:
        sector_nodes = load_sector_nodes(market_client)
    except Exception:
        sector_nodes = []
        sector_status = "unavailable"

    scored: list[tuple[int, str, dict[str, Any]]] = []

    if normalized_query:
        real_board_nodes = enrich_sector_nodes(
            [
                node
                for variant in _query_variants(query)
                for node in search_real_board_nodes(market_client, variant, limit=limit)
            ],
            sector_nodes,
        )
        for sector in real_board_nodes:
            score, matched = _score_sector(sector, normalized_query)
            scored.append(
                (
                    score + 120,
                    f"sector:{sector.get('id')}",
                    sector_search_item(
                        kind="sector",
                        sector=sector,
                        matched=_dedupe_strings([*matched, query])[:8],
                        source=sector.get("source") or "eastmoney.searchapi.board",
                    ),
                )
            )

        for sector in sector_nodes:
            score, matched = _score_sector(sector, normalized_query)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    f"sector:{sector.get('id')}",
                    sector_search_item(
                        kind="sector",
                        sector=sector,
                        matched=matched[:8],
                        source=sector.get("source") or "eastmoney.push2.board",
                    ),
                )
            )
    else:
        for rank, sector in enumerate(rank_default_sector_nodes(sector_nodes, limit=limit), start=1):
            scored.append(
                (
                    100 - rank,
                    f"sector:{sector.get('id')}",
                    sector_search_item(
                        kind="sector",
                        sector=sector,
                        matched=[],
                        source=sector.get("source") or "eastmoney.push2.board",
                    ),
                )
            )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, key, item in sorted(scored, key=lambda value: (-value[0], value[1])):
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break

    return {
        "query": query,
        "items": deduped,
        "total": len(deduped),
        "sector_status": sector_status,
        "hot_queries": dynamic_hot_queries(sector_nodes, limit=8),
        "discovery_groups": sector_discovery_groups(sector_nodes, limit=8),
        "source": "eastmoney.searchapi.board,eastmoney.push2.board",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_sector_relation_graph(
    market_client: RealMarketDataClient,
    query: str,
    limit: int = 14,
    page_size: int = 80,
    deep: bool = False,
) -> dict[str, Any]:
    """Build a real sector relation graph from constituent overlap and live metrics."""

    if not deep and not query_requires_live_graph(query):
        local_graph = local_sector_relation_graph(query, limit=limit)
        if local_graph and (not query.strip() or local_graph.get("edges")):
            return local_graph
        local_stub = local_sector_stub_graph(query, limit=limit)
        if local_stub and not query.strip():
            return local_stub

    strict_query_graph = query_requires_live_graph(query)
    sector_nodes = dynamic_sector_candidates(market_client, query, limit=max(limit, 12))
    if strict_query_graph:
        sector_nodes = [sector for sector in sector_nodes if sector_allowed_for_query_graph(sector, query)]
    seeds = _graph_seed_sectors(query, sector_nodes, limit=limit)
    payloads = _load_graph_sector_payloads(market_client, seeds, page_size=page_size)
    payloads = _expand_graph_payloads_by_overlap(
        market_client,
        payloads,
        [
            sector
            for sector in load_sector_nodes(market_client)
            if not strict_query_graph or sector_allowed_for_query_graph(sector, query)
        ],
        limit=limit,
        page_size=page_size,
        query=query if strict_query_graph else "",
    )
    edges = _graph_edges(payloads)
    clusters = _graph_clusters(payloads, edges)
    central_nodes = _graph_central_nodes(payloads, edges)

    return {
        "query": query,
        "nodes": [payload["node"] for payload in payloads],
        "edges": edges,
        "clusters": clusters,
        "central_nodes": central_nodes,
        "algorithm": {
            "name": "sector_constituent_overlap_graph",
            "node_basis": "东方财富真实板块搜索/板块列表 + 板块成分股实时行情",
            "edge_basis": "成分股交集、重叠比例、名称相似、行情共振综合评分",
            "score_formula": "shared_ratio*72 + jaccard*18 + name_similarity*7 + co_movement*3",
            "sample_page_size": page_size,
            "seed_count": len(seeds),
        },
        "status": "ready" if payloads else "empty",
        "source": "eastmoney.searchapi.board,eastmoney.push2.board,alphaagent_relation_algorithm",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_unavailable_sector_graph(
    query: str,
    exc: Exception,
    limit: int,
    page_size: int,
) -> dict[str, Any]:
    return {
        "query": query,
        "nodes": [],
        "edges": [],
        "clusters": [],
        "central_nodes": [],
        "algorithm": {
            "name": "sector_constituent_overlap_graph",
            "node_basis": "东方财富真实板块搜索/板块列表 + 板块成分股实时行情",
            "edge_basis": "成分股交集、重叠比例、名称相似、行情共振综合评分",
            "score_formula": "shared_ratio*72 + jaccard*18 + name_similarity*7 + co_movement*3",
            "sample_page_size": page_size,
            "seed_count": limit,
        },
        "status": "unavailable",
        "message": "真实板块关系图谱暂时不可用，通常是公开数据源临时限流或网络拒绝访问。",
        "error": {"type": exc.__class__.__name__},
        "source": "eastmoney.searchapi.board,eastmoney.push2.board,alphaagent_relation_algorithm",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def query_requires_live_graph(query: str) -> bool:
    normalized_query = _normalize_for_match(query)
    if not normalized_query:
        return False
    return any(term in normalized_query for term in ("cpo", "光模块", "光通信", "光纤", "光器件", "通信模块"))


def sector_allowed_for_query_graph(sector: dict[str, Any], query: str) -> bool:
    if sector_user_category(sector) == "style_status":
        return False
    normalized_query = _normalize_for_match(query)
    if not normalized_query:
        return True
    return sector_query_affinity(sector, normalized_query) >= 0.25


def sector_query_affinity(sector: dict[str, Any], normalized_query: str) -> float:
    fields = [
        sector.get("name"),
        sector.get("id"),
        *(sector.get("path") or []),
        *(sector.get("matched_keywords") or []),
    ]
    scores = [query_text_affinity(normalized_query, str(value or "")) for value in fields if value]
    return max(scores, default=0.0)


def query_text_affinity(normalized_query: str, value: str) -> float:
    normalized_query = semantic_query_text(normalized_query)
    normalized_value = semantic_query_text(value)
    if not normalized_query or not normalized_value:
        return 0.0
    if normalized_query == normalized_value:
        return 1.0
    if normalized_query in normalized_value or normalized_value in normalized_query:
        return 0.75
    if is_ascii_token(normalized_query) or is_ascii_token(normalized_value):
        return 0.0
    query_ascii = ascii_tokens(normalized_query)
    value_ascii = ascii_tokens(normalized_value)
    ascii_score = ascii_token_affinity(query_ascii, value_ascii)
    if query_ascii or value_ascii:
        query_han = strip_ascii_tokens(normalized_query)
        value_han = strip_ascii_tokens(normalized_value)
        return max(ascii_score, han_text_affinity(query_han, value_han))
    return han_text_affinity(normalized_query, normalized_value)


def han_text_affinity(query: str, value: str) -> float:
    if not query or not value:
        return 0.0
    similarity = _name_similarity(query, value)
    ordered = ordered_char_coverage(query, value)
    overlap = char_overlap_ratio(query, value)
    return max(similarity, ordered, overlap)


def ordered_char_coverage(query: str, value: str) -> float:
    if not query or not value:
        return 0.0
    position = 0
    matched = 0
    for char in query:
        index = value.find(char, position)
        if index < 0:
            continue
        matched += 1
        position = index + 1
    return matched / max(len(query), 1)


def char_overlap_ratio(query: str, value: str) -> float:
    query_chars = {char for char in query if char.strip()}
    value_chars = {char for char in value if char.strip()}
    if not query_chars or not value_chars:
        return 0.0
    return len(query_chars & value_chars) / len(query_chars)


def semantic_query_text(value: Any) -> str:
    text = _normalize_for_match(value)
    for suffix in ("概念板块", "行业板块", "题材概念", "概念", "板块", "行业", "主题", "地域"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def is_ascii_token(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+", value.lower()))


def ascii_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def strip_ascii_tokens(value: str) -> str:
    return re.sub(r"[a-z0-9]+", "", value.lower())


def ascii_token_affinity(query_tokens: list[str], value_tokens: list[str]) -> float:
    if not query_tokens or not value_tokens:
        return 0.0
    best = 0.0
    for query_token in query_tokens:
        for value_token in value_tokens:
            if query_token == value_token:
                best = max(best, 1.0)
            elif query_token in value_token or value_token in query_token:
                best = max(best, 0.75)
    return best


def _graph_seed_sectors(query: str, sector_nodes: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    normalized_query = _normalize_for_match(query)
    if not normalized_query:
        return sector_nodes[:limit]

    scored: list[tuple[int, str, dict[str, Any]]] = []

    for sector in sector_nodes:
        score, matched = _score_sector(sector, normalized_query)
        affinity = sector_query_affinity(sector, normalized_query)
        if score <= 0 and affinity < 0.25:
            continue
        exact_boost = 2000 if _normalize_for_match(sector.get("name")) == normalized_query else 0
        search_boost = 80 if str(sector.get("source") or "").startswith("eastmoney.searchapi") else 0
        affinity_boost = int(affinity * 100)
        scored.append((score + affinity_boost + exact_boost + search_boost + 30, str(sector.get("id") or sector.get("name")), {**sector, "matched_keywords": matched}))

    if not scored:
        for rank, sector in enumerate(sector_nodes[:limit], start=1):
            scored.append((10 - rank, str(sector.get("id") or sector.get("name")), sector))

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, key, sector in sorted(scored, key=lambda item: (-item[0], item[1])):
        if key in seen:
            continue
        seen.add(key)
        result.append(sector)
        if len(result) >= limit:
            break
    return result


def _load_graph_sector_payloads(
    market_client: RealMarketDataClient,
    sectors: list[dict[str, Any]],
    page_size: int,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="sector-graph") as executor:
        futures = {
            executor.submit(_load_one_graph_sector, market_client, sector, page_size): sector
            for sector in sectors
        }
        for future in as_completed(futures):
            try:
                payload = future.result()
            except Exception:
                continue
            if payload:
                payloads.append(payload)

    order = {str(sector.get("id") or ""): index for index, sector in enumerate(sectors)}
    return sorted(payloads, key=lambda payload: order.get(str(payload["node"].get("id") or ""), 999))


def _expand_graph_payloads_by_overlap(
    market_client: RealMarketDataClient,
    payloads: list[dict[str, Any]],
    sector_nodes: list[dict[str, Any]],
    limit: int,
    page_size: int,
    query: str = "",
) -> list[dict[str, Any]]:
    if not payloads:
        return payloads
    existing_edges = _graph_edges(payloads)
    if len(payloads) >= max(3, limit // 2) and existing_edges:
        return payloads

    existing_ids = {str(payload["node"].get("id")) for payload in payloads}
    normalized_query = _normalize_for_match(query)
    seed_symbols = {
        symbol
        for payload in payloads
        for symbol in payload.get("stock_symbols", set())
        if symbol
    }
    if not seed_symbols:
        return payloads

    candidate_nodes = _related_board_search_nodes(market_client, payloads, sector_nodes, limit=120)
    if len(candidate_nodes) < max(4, limit // 2):
        candidate_nodes.extend(
            sector
            for sector in sector_nodes
            if sector.get("type") == "industry"
        )
    candidate_nodes = [
        sector
        for sector in _dedupe_sector_nodes(candidate_nodes)
        if str(sector.get("id") or "") not in existing_ids
    ][:120]
    candidate_payloads = _load_graph_sector_payloads(market_client, candidate_nodes, page_size=page_size)

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for payload in candidate_payloads:
        node = payload["node"]
        if normalized_query and sector_query_affinity(node, normalized_query) < 0.25:
            continue
        symbols = payload.get("stock_symbols", set())
        if not symbols:
            continue
        shared_count = len(seed_symbols & symbols)
        shared_ratio = shared_count / max(min(len(seed_symbols), len(symbols)), 1)
        jaccard = shared_count / len(seed_symbols | symbols) if seed_symbols or symbols else 0
        name_similarity = max(
            _name_similarity(str(node.get("name") or ""), str(existing["node"].get("name") or ""))
            for existing in payloads
        )
        stock_count = _as_float(node.get("stock_count")) or len(symbols)
        broad_penalty = 1 + max(stock_count - 180, 0) / 90
        score = (shared_count * 18 + shared_ratio * 120 + name_similarity * 35) / broad_penalty
        if not _has_strong_relation_metrics(shared_count, shared_ratio, jaccard, name_similarity):
            continue
        scored.append((score, str(node.get("id") or ""), payload))

    needed = max(limit - len(payloads), 0)
    additions = [
        payload
        for score, _, payload in sorted(scored, key=lambda item: (-item[0], item[1]))
        if score > 0
    ][:needed]
    return [*payloads, *additions]


def _related_board_search_nodes(
    market_client: RealMarketDataClient,
    payloads: list[dict[str, Any]],
    sector_nodes: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    terms = _graph_expansion_terms(market_client, payloads, limit=32)
    found: list[dict[str, Any]] = []
    for term in terms:
        try:
            found.extend(search_real_board_nodes(market_client, term, limit=12))
        except Exception:
            continue
        if len(found) >= limit * 2:
            break
    return enrich_sector_nodes(found, sector_nodes)[:limit]


def _graph_expansion_terms(
    market_client: RealMarketDataClient,
    payloads: list[dict[str, Any]],
    limit: int,
) -> list[str]:
    terms: list[str] = []
    for payload in payloads:
        node_name = str(payload["node"].get("name") or "")
        terms.extend(_query_variants(node_name))
        for stock in (payload["node"].get("representative_stocks") or [])[:4]:
            symbol = str(stock.get("symbol") or "")
            exchange = str(stock.get("exchange") or "")
            if not symbol:
                continue
            try:
                business = market_client.stock_business(symbol, exchange)
            except Exception:
                continue
            terms.extend(_business_search_terms(business))
            if len(terms) >= limit * 4:
                break
    return _dedupe_strings(terms)[:limit]


def _business_search_terms(business: dict[str, Any]) -> list[str]:
    raw_values: list[Any] = []
    raw_values.extend(business.get("main_products") or [])
    raw_values.extend(business.get("business_tags") or [])
    raw_values.extend(
        segment.get("name")
        for segment in business.get("segments") or []
        if isinstance(segment, dict)
    )

    terms: list[str] = []
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        terms.append(text)
        normalized = _normalize_for_match(text)
        if len(normalized) >= 4:
            terms.extend(normalized[index : index + size] for size in (4, 3) for index in range(len(normalized) - size + 1))
        elif len(normalized) >= 2:
            terms.append(normalized)
    return [term for term in _dedupe_strings(terms) if 2 <= len(_normalize_for_match(term)) <= 12]


def _load_one_graph_sector(
    market_client: RealMarketDataClient,
    sector: dict[str, Any],
    page_size: int,
) -> dict[str, Any] | None:
    sector_id = str(sector.get("id") or "")
    if not sector_id:
        return None
    data = market_client.sector_stocks(sector_id, page=1, page_size=page_size, sort="amount")
    stocks = [stock for stock in data.get("items", []) if isinstance(stock, dict)]
    symbol_set = {
        str(stock.get("vt_symbol") or stock.get("symbol") or "")
        for stock in stocks
        if stock.get("vt_symbol") or stock.get("symbol")
    }
    stock_by_symbol = {
        str(stock.get("vt_symbol") or stock.get("symbol")): stock
        for stock in stocks
        if stock.get("vt_symbol") or stock.get("symbol")
    }
    return {
        "sector": sector,
        "stocks": stocks,
        "stock_symbols": symbol_set,
        "stock_by_symbol": stock_by_symbol,
        "node": _graph_node_from_sector(sector, stocks, data.get("total")),
    }


def _graph_node_from_sector(
    sector: dict[str, Any],
    stocks: list[dict[str, Any]],
    total_count: Any = None,
) -> dict[str, Any]:
    changes = [_as_float(stock.get("change_pct")) for stock in stocks]
    valid_changes = [value for value in changes if value is not None]
    rise_count = sum(1 for value in valid_changes if value > 0)
    fall_count = sum(1 for value in valid_changes if value < 0)
    turnover = sum(_as_float(stock.get("turnover")) or 0 for stock in stocks)
    market_cap = sum(_as_float(stock.get("market_cap")) or 0 for stock in stocks)
    leaders = sorted(stocks, key=lambda stock: _as_float(stock.get("turnover")) or 0, reverse=True)[:6]
    leader = leaders[0] if leaders else {}
    return {
        "id": sector.get("id"),
        "name": sector.get("name"),
        "type": sector.get("type"),
        "path": sector.get("path") or [],
        "matched_keywords": sector.get("matched_keywords") or [],
        "stock_count": sector.get("stock_count") or _as_int(total_count) or data_stock_count(sector, stocks),
        "loaded_stock_count": len(stocks),
        "change_pct": sector.get("change_pct"),
        "avg_change_pct": sector.get("change_pct") if sector.get("change_pct") is not None else sum(valid_changes) / len(valid_changes) if valid_changes else None,
        "rise_ratio": rise_count / len(valid_changes) * 100 if valid_changes else None,
        "turnover": turnover if stocks else None,
        "market_cap": sector.get("market_cap") or (market_cap if stocks else None),
        "rise_count": sector.get("rise_count") if sector.get("rise_count") is not None else rise_count if stocks else None,
        "fall_count": sector.get("fall_count") if sector.get("fall_count") is not None else fall_count if stocks else None,
        "leader_stock": sector.get("leader_stock") or leader.get("name"),
        "leader_change_pct": sector.get("leader_change_pct") if sector.get("leader_change_pct") is not None else leader.get("change_pct"),
        "dynamic_cluster": None,
        "representative_stocks": leaders,
        "source": sector.get("source") or "eastmoney.push2.board",
    }


def data_stock_count(sector: dict[str, Any], stocks: list[dict[str, Any]]) -> int | None:
    value = sector.get("count")
    if isinstance(value, int):
        return value
    return len(stocks) if stocks else None


def _graph_edges(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for left_index, left in enumerate(payloads):
        for right in payloads[left_index + 1 :]:
            edge = _graph_edge(left, right)
            if edge and _edge_has_strong_evidence(edge):
                edges.append(edge)
    edges.sort(key=lambda item: (-float(item["score"]), -int(item["shared_stock_count"]), str(item["source_name"])))
    return edges[:48]


def _graph_edge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    left_symbols: set[str] = left["stock_symbols"]
    right_symbols: set[str] = right["stock_symbols"]
    if not left_symbols or not right_symbols:
        return None

    shared = left_symbols & right_symbols
    union = left_symbols | right_symbols
    shared_count = len(shared)
    min_size = max(min(len(left_symbols), len(right_symbols)), 1)
    shared_ratio = shared_count / min_size
    jaccard = shared_count / len(union) if union else 0
    name_similarity = _name_similarity(str(left["node"].get("name") or ""), str(right["node"].get("name") or ""))
    co_movement = _co_movement_score(left["node"].get("avg_change_pct"), right["node"].get("avg_change_pct"))
    score = shared_ratio * 72 + jaccard * 18 + name_similarity * 7 + co_movement * 3

    if shared_count == 0 and score < 12:
        return None
    if score < 8:
        return None

    shared_stocks = _shared_stocks(shared, left["stock_by_symbol"], right["stock_by_symbol"])
    strong = _has_strong_relation_metrics(shared_count, shared_ratio, jaccard, name_similarity)
    return {
        "source": left["node"]["id"],
        "target": right["node"]["id"],
        "source_name": left["node"]["name"],
        "target_name": right["node"]["name"],
        "score": round(min(score, 100), 2),
        "shared_stock_count": shared_count,
        "shared_stock_ratio": round(shared_ratio * 100, 2),
        "jaccard": round(jaccard * 100, 2),
        "name_similarity": round(name_similarity * 100, 2),
        "co_movement": round(co_movement * 100, 2),
        "reasons": _edge_reasons(shared_count, shared_ratio, name_similarity, co_movement),
        "shared_stocks": shared_stocks,
        "evidence_level": "strong" if strong else "weak",
    }


def _edge_has_strong_evidence(edge: dict[str, Any]) -> bool:
    return _has_strong_relation_metrics(
        int(edge.get("shared_stock_count") or 0),
        (float(edge.get("shared_stock_ratio") or 0) / 100),
        (float(edge.get("jaccard") or 0) / 100),
        (float(edge.get("name_similarity") or 0) / 100),
    )


def _has_strong_relation_metrics(
    shared_count: int,
    shared_ratio: float,
    jaccard: float,
    name_similarity: float,
) -> bool:
    return (
        (shared_count >= 5 and shared_ratio >= 0.20)
        or (shared_count >= 2 and jaccard >= 0.12)
        or (shared_count >= 1 and name_similarity >= 0.35)
        or (shared_count >= 10 and shared_ratio >= 0.12)
    )


def _shared_stocks(
    shared_symbols: set[str],
    left_stock_by_symbol: dict[str, dict[str, Any]],
    right_stock_by_symbol: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    stocks: list[dict[str, Any]] = []
    for symbol in shared_symbols:
        stock = left_stock_by_symbol.get(symbol) or right_stock_by_symbol.get(symbol)
        if stock:
            stocks.append(stock)
    stocks.sort(key=lambda item: _as_float(item.get("turnover")) or 0, reverse=True)
    return stocks[:8]


def _edge_reasons(
    shared_count: int,
    shared_ratio: float,
    name_similarity: float,
    co_movement: float,
) -> list[str]:
    reasons: list[str] = []
    if shared_count:
        reasons.append(f"共享 {shared_count} 只成分股")
    if shared_ratio >= 0.35:
        reasons.append("成分股重叠高")
    if name_similarity >= 0.35:
        reasons.append("名称/关键词接近")
    if co_movement >= 0.65:
        reasons.append("当日表现共振")
    return reasons or ["弱关联"]


def _graph_clusters(payloads: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_ids = _connected_components(payloads, edges)
    node_by_id = {str(payload["node"].get("id")): payload["node"] for payload in payloads}

    clusters: list[dict[str, Any]] = []
    for index, node_ids in enumerate(grouped_ids, start=1):
        nodes = [node_by_id[node_id] for node_id in node_ids if node_id in node_by_id]
        name = _dynamic_cluster_name(nodes, index)
        cluster_edges = [edge for edge in edges if edge["source"] in node_ids and edge["target"] in node_ids]
        changes = [_as_float(node.get("avg_change_pct")) for node in nodes]
        valid_changes = [value for value in changes if value is not None]
        clusters.append(
            {
                "name": name,
                "node_ids": node_ids,
                "node_count": len(nodes),
                "edge_count": len(cluster_edges),
                "avg_change_pct": sum(valid_changes) / len(valid_changes) if valid_changes else None,
                "turnover": sum(_as_float(node.get("turnover")) or 0 for node in nodes),
            }
        )
    clusters.sort(key=lambda item: (-int(item["node_count"]), str(item["name"])))
    return clusters


def _connected_components(payloads: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[list[str]]:
    node_ids = [str(payload["node"].get("id")) for payload in payloads if payload["node"].get("id")]
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        if float(edge.get("score") or 0) < 12 and int(edge.get("shared_stock_count") or 0) == 0:
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)

    components: list[list[str]] = []
    seen: set[str] = set()
    for node_id in node_ids:
        if node_id in seen:
            continue
        stack = [node_id]
        group: list[str] = []
        seen.add(node_id)
        while stack:
            current = stack.pop()
            group.append(current)
            for next_id in adjacency.get(current, set()):
                if next_id in seen:
                    continue
                seen.add(next_id)
                stack.append(next_id)
        components.append(group)
    components.sort(key=lambda item: (-len(item), item[0]))
    return components


def _dynamic_cluster_name(nodes: list[dict[str, Any]], index: int) -> str:
    names = [str(node.get("name") or "") for node in nodes if node.get("name")]
    shared_terms = _common_name_terms(names)
    if shared_terms:
        return " / ".join(shared_terms[:2])
    leader = max(nodes, key=lambda node: _as_float(node.get("turnover")) or 0, default={})
    leader_name = str(leader.get("name") or "").strip()
    return leader_name or f"动态聚类 {index}"


def _graph_central_nodes(payloads: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    degree: dict[str, float] = {str(payload["node"].get("id")): 0.0 for payload in payloads}
    for edge in edges:
        score = float(edge.get("score") or 0)
        degree[str(edge["source"])] = degree.get(str(edge["source"]), 0.0) + score
        degree[str(edge["target"])] = degree.get(str(edge["target"]), 0.0) + score

    node_by_id = {str(payload["node"].get("id")): payload["node"] for payload in payloads}
    result = [
        {
            "id": node_id,
            "name": node_by_id[node_id].get("name"),
            "type": node_by_id[node_id].get("type"),
            "degree_score": round(score, 2),
            "avg_change_pct": node_by_id[node_id].get("avg_change_pct"),
            "turnover": node_by_id[node_id].get("turnover"),
        }
        for node_id, score in degree.items()
        if node_id in node_by_id
    ]
    result.sort(key=lambda item: (-float(item["degree_score"]), str(item["name"])))
    return result[:8]


def _name_similarity(left: str, right: str) -> float:
    left_text = _normalize_for_match(left)
    right_text = _normalize_for_match(right)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    if left_text in right_text or right_text in left_text:
        return 0.6
    left_terms = set(_char_ngrams(left_text))
    right_terms = set(_char_ngrams(right_text))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _char_ngrams(text: str) -> list[str]:
    if len(text) <= 2:
        return [text]
    return [text[index : index + 2] for index in range(len(text) - 1)]


def _co_movement_score(left_change: Any, right_change: Any) -> float:
    left = _as_float(left_change)
    right = _as_float(right_change)
    if left is None or right is None:
        return 0.0
    if left == 0 and right == 0:
        return 1.0
    if (left > 0 > right) or (left < 0 < right):
        return 0.0
    return max(0.0, 1 - min(abs(left - right) / 8, 1))


def _as_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _sector_type_label(sector_type: str) -> str:
    if sector_type == "industry":
        return "行业"
    if sector_type == "region":
        return "地域"
    if sector_type == "theme":
        return "主题"
    if sector_type == "concept":
        return "概念"
    return "板块"


def dynamic_sector_candidates(
    market_client: RealMarketDataClient,
    query: str,
    limit: int = 18,
) -> list[dict[str, Any]]:
    """Return real board candidates from upstream search and board lists."""

    query = query.strip()
    limit = min(max(limit, 1), 50)
    sector_nodes = load_sector_nodes(market_client)
    if not query:
        return rank_default_sector_nodes(sector_nodes, limit=limit)

    searched = [
        node
        for variant in _query_variants(query)
        for node in search_real_board_nodes(market_client, variant, limit=limit)
    ]
    candidates = enrich_sector_nodes(searched, sector_nodes)
    candidates.extend(fuzzy_match_sector_nodes(sector_nodes, query, limit=limit * 2))

    normalized_query = _normalize_for_match(query)
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for sector in candidates:
        sector_id = str(sector.get("id") or sector.get("name") or "")
        if not sector_id:
            continue
        score, matched = _score_sector(sector, normalized_query)
        if str(sector.get("source") or "").startswith("eastmoney.searchapi"):
            score += 100
        if matched:
            sector = {**sector, "matched_keywords": matched}
        scored.append((score, sector_id, sector))

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, sector_id, sector in sorted(scored, key=lambda item: (-item[0], item[1])):
        if sector_id in seen:
            continue
        seen.add(sector_id)
        result.append(sector)
        if len(result) >= limit:
            break
    return result


def load_sector_nodes(market_client: RealMarketDataClient) -> list[dict[str, Any]]:
    """Load available real boards from the configured data source."""

    nodes: list[dict[str, Any]] = []
    for sector_type in ("industry", "concept", "theme", "region"):
        try:
            data = market_client.list_sectors(sector_type)
        except Exception:
            continue
        source = data.get("source")
        for item in data.get("items", []):
            if not isinstance(item, dict):
                continue
            sector_id = str(item.get("id") or item.get("akshare_symbol") or "")
            name = str(item.get("name") or "")
            if not sector_id or not name:
                continue
            nodes.append(
                {
                    **item,
                    "id": sector_id,
                    "name": name,
                    "type": item.get("type") or sector_type,
                    "path": item.get("path") or [_sector_type_label(str(item.get("type") or sector_type))],
                    "source": item.get("source") or source,
                }
            )
    return _dedupe_sector_nodes(nodes)


def search_real_board_nodes(
    market_client: RealMarketDataClient,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search the upstream board service without local static query expansion."""

    query = query.strip()
    if not query:
        return []
    data = market_client.search_boards(query, limit=limit)
    result: list[dict[str, Any]] = []
    for item in data.get("items", []):
        if not isinstance(item, dict):
            continue
        sector_id = str(item.get("id") or item.get("akshare_symbol") or "")
        name = str(item.get("name") or "")
        if not sector_id or not name:
            continue
        result.append(
            {
                **item,
                "id": sector_id,
                "name": name,
                "type": item.get("type") or "concept",
                "path": item.get("path") or [_sector_type_label(str(item.get("type") or "concept"))],
                "source": item.get("source") or data.get("source"),
            }
        )
    return _dedupe_sector_nodes(result)


def _query_variants(query: str) -> list[str]:
    text = query.strip()
    normalized = _normalize_for_match(text)
    variants = [text] if text else []
    if len(normalized) >= 4:
        variants.extend(normalized[index : index + size] for size in (4, 3, 2) for index in range(len(normalized) - size + 1))
    elif len(normalized) >= 2:
        variants.append(normalized)
    return _dedupe_strings(variants)[:12]


def enrich_sector_nodes(
    sectors: list[dict[str, Any]],
    sector_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge live-search results with same-name board-list metrics when available."""

    by_id = {str(item.get("id")): item for item in sector_nodes if item.get("id")}
    by_name = {
        _normalize_for_match(item.get("name")): item
        for item in sector_nodes
        if item.get("name")
    }
    enriched: list[dict[str, Any]] = []
    for sector in sectors:
        existing = by_id.get(str(sector.get("id") or "")) or by_name.get(_normalize_for_match(sector.get("name")))
        enriched.append({**existing, **sector} if existing else sector)
    return _dedupe_sector_nodes(enriched)


def rank_default_sector_nodes(
    sector_nodes: list[dict[str, Any]],
    limit: int = 18,
) -> list[dict[str, Any]]:
    """Rank real boards by currently reported activity fields."""

    scored = []
    for index, sector in enumerate(sector_nodes):
        change = abs(_as_float(sector.get("change_pct")) or 0)
        market_cap = _as_float(sector.get("market_cap")) or 0
        stock_count = _as_float(sector.get("stock_count")) or 0
        rise_count = _as_float(sector.get("rise_count")) or 0
        fall_count = _as_float(sector.get("fall_count")) or 0
        activity = change * 10 + min(market_cap / 1_000_000_000, 100) + stock_count * 0.2 + rise_count + fall_count
        scored.append((activity, -index, sector))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [sector for _, _, sector in scored[:limit]]


def sector_search_item(
    *,
    kind: str,
    sector: dict[str, Any],
    matched: list[str],
    source: Any,
    user_category_override: str | None = None,
) -> dict[str, Any]:
    user_category = user_category_override or sector_user_category(sector)
    meta = SECTOR_DISCOVERY_GROUP_DEFS[user_category]
    return {
        "kind": kind,
        "id": sector.get("id"),
        "name": sector.get("name"),
        "type": sector.get("type"),
        "path": sector.get("path") or [],
        "matched": matched,
        "change_pct": sector.get("change_pct"),
        "stock_count": sector.get("stock_count"),
        "source": source,
        "user_category": user_category,
        "user_category_label": meta["title"],
        "user_explain": sector_user_explain(sector, user_category),
        "decision_hint": sector_decision_hint(user_category),
    }


def sector_discovery_groups(sector_nodes: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    ranked = rank_default_sector_nodes(sector_nodes, limit=max(limit * 5, 30))
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in SECTOR_DISCOVERY_GROUP_DEFS}
    for sector in ranked:
        key = sector_user_category(sector)
        if key not in grouped:
            key = "theme"
        if len(grouped[key]) >= limit:
            continue
        grouped[key].append(sector_search_item(kind="sector", sector=sector, matched=[], source=sector.get("source") or "eastmoney.push2.board"))

    mainline_sectors = [
        sector
        for sector in ranked
        if sector_user_category(sector) in {"industry", "theme"}
    ][:limit]
    mainline_items = [
        sector_search_item(
            kind="sector",
            sector=sector,
            matched=[],
            source=sector.get("source") or "eastmoney.push2.board",
            user_category_override="mainline_watch",
        )
        for sector in mainline_sectors
    ]
    grouped["mainline_watch"] = mainline_items

    result: list[dict[str, Any]] = []
    for key in ("mainline_watch", "industry", "theme", "style_status", "region"):
        items = grouped.get(key) or []
        if not items:
            continue
        meta = SECTOR_DISCOVERY_GROUP_DEFS[key]
        result.append(
            {
                "id": key,
                "title": meta["title"],
                "description": meta["description"],
                "items": items,
            }
        )
    return result


def sector_user_category(sector: dict[str, Any]) -> str:
    sector_type = str(sector.get("type") or "").lower()
    name = str(sector.get("name") or "")
    category = str(sector.get("category") or "")
    path_text = " ".join(str(value) for value in (sector.get("path") or []))
    text = f"{name} {category} {path_text}"
    if sector_type == "industry":
        return "industry"
    if sector_type == "region":
        return "region"
    if _is_style_status_sector(text):
        return "style_status"
    return "theme"


def _is_style_status_sector(text: str) -> bool:
    normalized = text.lower()
    return any(keyword.lower() in normalized for keyword in STYLE_STATUS_KEYWORDS) or bool(re.search(r"\d{4}年报|st股|预[增减盈亏]", normalized, re.I))


def sector_user_explain(sector: dict[str, Any], user_category: str) -> str:
    stock_count = _as_int(sector.get("stock_count"))
    count_text = f"{stock_count} 只成分股" if stock_count is not None else "成分股数量待同步"
    if user_category == "industry":
        return f"行业归属板块，适合先看行业趋势和龙头股；当前覆盖 {count_text}。"
    if user_category == "style_status":
        return f"这是风格或状态筛选，不代表产业链；适合辅助过滤股票，当前覆盖 {count_text}。"
    if user_category == "region":
        return f"地域归属板块，适合结合区域政策和本地产业集群观察；当前覆盖 {count_text}。"
    if user_category == "mainline_watch":
        return f"按活动字段筛出的主线候选，需要继续看 5/20/60 日趋势和成分扩散；当前覆盖 {count_text}。"
    return f"题材概念板块，适合看市场交易方向和关联板块；当前覆盖 {count_text}。"


def sector_decision_hint(user_category: str) -> str:
    if user_category == "industry":
        return "先看行业趋势，再看龙头和中军。"
    if user_category == "style_status":
        return "只作为过滤条件，不直接当主线。"
    if user_category == "region":
        return "需要结合区域政策和产业分布。"
    if user_category == "mainline_watch":
        return "继续验证持续性、扩散度和龙头强度。"
    return "先验证题材强度，再看成分股扩散。"


def fuzzy_match_sector_nodes(
    sector_nodes: list[dict[str, Any]],
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    normalized_query = _normalize_for_match(query)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for sector in sector_nodes:
        score, matched = _score_sector(sector, normalized_query)
        if score <= 0:
            continue
        if sector_user_category(sector) == "style_status":
            score -= 15
        scored.append((score, str(sector.get("id") or sector.get("name")), {**sector, "matched_keywords": matched}))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [sector for _, _, sector in scored[:limit]]


def dynamic_hot_queries(sector_nodes: list[dict[str, Any]], limit: int = 8) -> list[str]:
    return [
        str(sector.get("name"))
        for sector in rank_default_sector_nodes(sector_nodes, limit=limit)
        if sector.get("name")
    ]


def _score_sector(sector: dict[str, Any], normalized_query: str) -> tuple[int, list[str]]:
    if not normalized_query:
        return 1, []
    semantic_query = semantic_query_text(normalized_query)
    if not semantic_query:
        return 0, []
    fields = [
        sector.get("id"),
        sector.get("akshare_symbol"),
        sector.get("name"),
        *(sector.get("matched_keywords") or []),
    ]
    matched: list[str] = []
    score = 0
    for value in fields:
        text = str(value or "")
        normalized = _normalize_for_match(text)
        if not normalized:
            continue
        semantic_value = semantic_query_text(normalized)
        if semantic_value == semantic_query:
            score += 120
            matched.append(text)
        elif semantic_query in semantic_value:
            score += 60 + min(len(semantic_query), 20)
            matched.append(text)
        elif semantic_value in semantic_query:
            score += 35 + min(len(semantic_value), 20)
            matched.append(text)
        else:
            similarity = query_text_affinity(semantic_query, semantic_value)
            if similarity >= 0.50:
                score += int(similarity * 70)
                matched.append(text)
    if score > 0 and str(sector.get("type") or "") == "industry":
        score += 2
    return score, _dedupe_strings(matched)


def _dedupe_sector_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        sector_id = str(node.get("id") or node.get("name") or "")
        if not sector_id or sector_id in seen:
            continue
        seen.add(sector_id)
        result.append(node)
    return result



def discover_dynamic_industry_chains(
    market_client: RealMarketDataClient,
    limit: int = 12,
    page_size: int = 40,
) -> dict[str, Any]:
    """Discover chain-like board clusters from real boards and constituent overlap."""

    graph = build_sector_relation_graph(market_client, "", limit=min(max(limit, 4), 18), page_size=page_size)
    clusters = []
    node_by_id = {str(node.get("id")): node for node in graph.get("nodes", [])}
    for cluster in graph.get("clusters", []):
        node_ids = [str(item) for item in cluster.get("node_ids", [])]
        nodes = [node_by_id[node_id] for node_id in node_ids if node_id in node_by_id]
        if not nodes:
            continue
        leader = max(nodes, key=lambda node: _as_float(node.get("turnover")) or 0)
        clusters.append(
            {
                "id": str(leader.get("id") or cluster.get("name")),
                "name": cluster.get("name") or leader.get("name"),
                "keywords": _common_name_terms([str(node.get("name") or "") for node in nodes]),
                "upstream": [],
                "midstream": [str(node.get("name")) for node in nodes[:4] if node.get("name")],
                "downstream": [],
                "segments": _segments_from_dynamic_nodes(nodes, graph.get("edges", [])),
                "related_sectors": [sector_from_graph_node(node) for node in nodes],
                "node_count": len(nodes),
                "edge_count": cluster.get("edge_count"),
                "avg_change_pct": cluster.get("avg_change_pct"),
                "turnover": cluster.get("turnover"),
                "source": "eastmoney.push2.board,alphaagent_dynamic_graph",
            }
        )
    return {
        "items": clusters[:limit],
        "source": "eastmoney.push2.board,alphaagent_dynamic_graph",
        "sector_status": "ready" if clusters else "empty",
        "algorithm": graph.get("algorithm"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_dynamic_chain_map(
    market_client: RealMarketDataClient,
    chain_id: str,
    page_size: int = 20,
    deep: bool = False,
) -> dict[str, Any]:
    graph = build_sector_relation_graph(market_client, chain_id, limit=12, page_size=max(page_size, 20), deep=deep)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not nodes:
        return {
            "chain_id": chain_id,
            "name": chain_id,
            "keywords": [],
            "related_sectors": [],
            "focus_stocks": [],
            "segments": [],
            "nodes": [],
            "edges": [],
            "stage_exposure": [],
            "status": graph.get("status") or "empty",
            "source": graph.get("source"),
            "data_origin": graph.get("data_origin"),
            "storage_table": graph.get("storage_table"),
            "fallback_used": graph.get("fallback_used"),
            "coverage": graph.get("coverage"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    segments = _segments_from_dynamic_nodes(nodes, edges)
    stage_exposure = _stage_exposure_from_segments(segments)
    return {
        "chain_id": chain_id,
        "name": _dynamic_chain_name(nodes, chain_id),
        "keywords": _common_name_terms([str(node.get("name") or "") for node in nodes]),
        "related_sectors": [sector_from_graph_node(node) for node in nodes],
        "focus_stocks": _focus_stocks_from_graph_nodes(nodes),
        "segments": segments,
        "nodes": [chain_node for segment in segments for chain_node in segment.get("nodes", [])],
        "edges": _dynamic_chain_edges(segments, edges),
        "stage_exposure": stage_exposure,
        "exposure_basis": "按真实板块成分股样本聚合成交额、市值和涨跌表现；链路分层由图谱中心性和关联强度动态计算。",
        "status": graph.get("status") or "ready",
        "message": graph.get("message"),
        "source": graph.get("source") or "eastmoney.push2.board,alphaagent_dynamic_graph",
        "data_origin": graph.get("data_origin"),
        "storage_table": graph.get("storage_table"),
        "fallback_used": graph.get("fallback_used"),
        "coverage": graph.get("coverage"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_dynamic_chain_stock_payload(
    market_client: RealMarketDataClient,
    chain_id: str,
    page_size: int,
) -> dict[str, Any]:
    chain_map = build_dynamic_chain_map(market_client, chain_id, page_size=page_size)
    related_sectors = chain_map.get("related_sectors", [])
    return {
        "chain_id": chain_map.get("chain_id") or chain_id,
        "name": chain_map.get("name") or chain_id,
        "related_sectors": related_sectors,
        "items": _load_dynamic_chain_stocks(market_client, related_sectors, page_size),
    }


def _segments_from_dynamic_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage_by_id = _dynamic_stage_by_node(nodes, edges)
    segments: list[dict[str, Any]] = []
    for stage, label in STAGE_DEFS:
        stage_nodes = [node for node in nodes if stage_by_id.get(str(node.get("id"))) == stage]
        chain_nodes = [_dynamic_chain_node(node, stage, label, nodes) for node in stage_nodes]
        exposure = _exposure_from_graph_nodes(stage_nodes)
        segments.append(
            {
                "stage": stage,
                "label": label,
                "items": [str(node.get("name")) for node in stage_nodes if node.get("name")],
                "nodes": chain_nodes,
                "related_sectors": [sector_from_graph_node(node) for node in stage_nodes],
                **exposure,
            }
        )
    total_turnover = sum(float(segment.get("turnover") or 0) for segment in segments)
    for segment in segments:
        turnover = segment.get("turnover")
        segment["turnover_ratio"] = (
            float(turnover) / total_turnover * 100
            if isinstance(turnover, (int, float)) and total_turnover > 0
            else None
        )
    return segments


def _dynamic_stage_by_node(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, str]:
    degree: dict[str, float] = {str(node.get("id")): 0.0 for node in nodes if node.get("id")}
    incoming: dict[str, float] = {node_id: 0.0 for node_id in degree}
    outgoing: dict[str, float] = {node_id: 0.0 for node_id in degree}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        score = float(edge.get("score") or 0)
        shared = float(edge.get("shared_stock_count") or 0)
        if source not in degree or target not in degree:
            continue
        weight = score + shared
        degree[source] += weight
        degree[target] += weight
        source_turnover = _node_turnover(nodes, source)
        target_turnover = _node_turnover(nodes, target)
        if source_turnover >= target_turnover:
            outgoing[source] += weight
            incoming[target] += weight
        else:
            outgoing[target] += weight
            incoming[source] += weight

    ordered = sorted(degree, key=lambda node_id: (-degree[node_id], node_id))
    if not ordered:
        return {}
    stage_by_id: dict[str, str] = {}
    top_count = max(1, round(len(ordered) * 0.25))
    for node_id in ordered[:top_count]:
        stage_by_id[node_id] = "bridge"
    for node_id in ordered[top_count:]:
        stage_by_id[node_id] = "source" if outgoing[node_id] >= incoming[node_id] else "sink"
    if all(stage == "bridge" for stage in stage_by_id.values()) and len(ordered) > 1:
        stage_by_id[ordered[-1]] = "sink"
    return stage_by_id


def _node_turnover(nodes: list[dict[str, Any]], node_id: str) -> float:
    for node in nodes:
        if str(node.get("id")) == node_id:
            return _as_float(node.get("turnover")) or 0.0
    return 0.0


def _dynamic_chain_node(
    node: dict[str, Any],
    stage: str,
    label: str,
    all_nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    total_turnover = sum(_as_float(item.get("turnover")) or 0 for item in all_nodes)
    turnover = _as_float(node.get("turnover")) or 0
    return {
        "id": str(node.get("id")),
        "name": str(node.get("name") or node.get("id")),
        "stage": stage,
        "stage_label": label,
        "matched_sectors": [sector_from_graph_node(node)],
        "sector_count": 1,
        "weight": turnover / total_turnover * 100 if total_turnover > 0 else None,
    }


def _exposure_from_graph_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    changes = [_as_float(node.get("avg_change_pct")) for node in nodes]
    valid_changes = [value for value in changes if value is not None]
    return {
        "stock_count": sum(int(node.get("stock_count") or 0) for node in nodes),
        "turnover": sum(_as_float(node.get("turnover")) or 0 for node in nodes) if nodes else None,
        "market_cap": sum(_as_float(node.get("market_cap")) or 0 for node in nodes) if nodes else None,
        "avg_change_pct": sum(valid_changes) / len(valid_changes) if valid_changes else None,
        "representative_stocks": [stock for node in nodes for stock in (node.get("representative_stocks") or [])][:8],
    }


def _stage_exposure_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "stage": segment.get("stage"),
            "label": segment.get("label"),
            "stock_count": segment.get("stock_count"),
            "sector_count": len(segment.get("related_sectors") or []),
            "turnover": segment.get("turnover"),
            "market_cap": segment.get("market_cap"),
            "avg_change_pct": segment.get("avg_change_pct"),
            "turnover_ratio": segment.get("turnover_ratio"),
        }
        for segment in segments
    ]


def _focus_stocks_from_graph_nodes(nodes: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        sector_id = str(node.get("id") or "")
        sector_name = str(node.get("name") or "")
        for stock in node.get("representative_stocks") or []:
            key = str(stock.get("vt_symbol") or stock.get("symbol") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            items.append({**stock, "related_sector_id": sector_id, "related_sector_name": sector_name})
    items.sort(key=lambda item: (_as_float(item.get("turnover")) or 0, _as_float(item.get("change_pct")) or -999), reverse=True)
    return items[:limit]


def _dynamic_chain_edges(segments: list[dict[str, Any]], graph_edges: list[dict[str, Any]]) -> list[dict[str, str]]:
    valid_ids = {str(node.get("id")) for segment in segments for node in (segment.get("nodes") or [])}
    edge_pairs = {
        (str(edge.get("source")), str(edge.get("target")))
        for edge in graph_edges
        if str(edge.get("source")) in valid_ids and str(edge.get("target")) in valid_ids
    }
    return [{"source": source, "target": target} for source, target in sorted(edge_pairs)]


def _dynamic_chain_name(nodes: list[dict[str, Any]], fallback: str) -> str:
    terms = _common_name_terms([str(node.get("name") or "") for node in nodes])
    if terms:
        return " / ".join(terms[:2])
    leader = max(nodes, key=lambda node: _as_float(node.get("turnover")) or 0, default={})
    return str(leader.get("name") or fallback)


def sector_from_graph_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type"),
        "path": node.get("path") or [],
        "source": node.get("source"),
        "stock_count": node.get("stock_count"),
        "change_pct": node.get("change_pct") or node.get("avg_change_pct"),
        "market_cap": node.get("market_cap"),
        "rise_count": node.get("rise_count"),
        "fall_count": node.get("fall_count"),
        "leader_stock": node.get("leader_stock"),
    }


def _common_name_terms(names: list[str]) -> list[str]:
    token_counts: dict[str, int] = {}
    for name in names:
        for token in _name_tokens(name):
            token_counts[token] = token_counts.get(token, 0) + 1
    threshold = 2 if len(names) > 2 else 1
    ranked = sorted(token_counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [token for token, count in ranked if count >= threshold][:4]


def _name_tokens(name: str) -> list[str]:
    text = _normalize_for_match(name)
    if not text:
        return []
    tokens = [text]
    max_size = min(len(text), 5)
    for size in range(max_size, 1, -1):
        tokens.extend(text[index : index + size] for index in range(len(text) - size + 1))
    return _dedupe_strings([token for token in tokens if len(token) >= 2])


def _load_dynamic_chain_stocks(
    market_client: RealMarketDataClient,
    related_sectors: list[dict[str, Any]],
    page_size: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sector in related_sectors[:6]:
        sector_id = str(sector.get("id") or "")
        if not sector_id:
            continue
        data = market_client.sector_stocks(sector_id, page=1, page_size=page_size, sort="changepercent")
        for stock in data.get("items", []):
            key = str(stock.get("vt_symbol") or stock.get("symbol") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            items.append({**stock, "related_sector_id": sector_id, "related_sector_name": sector.get("name")})
    return items


def _normalize_for_match(value: Any) -> str:
    text = str(value or "").lower()
    return re.sub(r"[\s\-_./\\|:：()（）]+", "", text)


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
