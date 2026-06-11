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


# ── Concept Hint (概念组合解读) ──

# 主题关键词映射：概念名 → 主题大类
_THEME_KEYWORDS: list[tuple[str, list[str]]] = [
    ("AI算力", ["算力", "AI", "人工智能", "大模型", "GPU", "智算", "ChatGPT", "AIGC", "智谱"]),
    ("光通信", ["光模块", "光通信", "CPO", "F5G", "光器件", "光纤", "硅光"]),
    ("5G/通信", ["5G", "6G", "通信技术", "通信设备", "通信网络", "射频", "天线"]),
    ("新能源", ["锂电", "新能源", "光伏", "储能", "充电桩", "风电", "氢能", "钠电池"]),
    ("半导体", ["芯片", "半导体", "封装", "光刻", "EDA", "集成电路", "晶圆"]),
    ("智能驾驶", ["智能驾驶", "无人驾驶", "自动驾驶", "车联网", "毫米波", "激光雷达"]),
    ("军工", ["军工", "航天", "航空", "国防", "北斗", "军民融合"]),
    ("医药", ["医药", "生物", "创新药", "医疗", "中药", "CRO", "CXO"]),
    ("消费", ["消费", "白酒", "食品", "零售", "免税", "啤酒", "白酒"]),
    ("金融", ["银行", "证券", "保险", "金融", "期货", "信托"]),
    ("地产", ["地产", "房地产", "物业", "建材"]),
    ("数字经济", ["数据", "数字经济", "数字货币", "区块链", "信创", "云计算"]),
    ("机器人", ["机器人", "人形机器人", "工业母机", "自动化"]),
    ("华为", ["华为", "鸿蒙", "鲲鹏", "昇腾"]),
    ("苹果", ["苹果", "AirPods", "iPhone"]),
    ("新能源车", ["新能源车", "汽车", "特斯拉", "比亚迪"]),
]

# 噪音概念关键词（纯标签/资金属性，无行业含义）
_NOISE_KEYWORDS = [
    "融资融券", "深股通", "沪股通", "MSCI", "富时罗素",
    "大盘股", "权重股", "百元股", "基金重仓", "行业龙头",
    "大盘成长", "大盘价值", "小盘成长", "小盘价值",
    "预盈", "预增", "预亏", "预减",
    "创业", "深成", "上证", "HS300", "中证500", "沪深300",
    "科创板", "注册制", "次新股", "新股", "ST", "退市",
    "东方财富", "同花顺",
    "板块", "低价股", "高价股", "破发", "破净",
]

# 地域板块关键词后缀
_REGION_SUFFIXES = ["板块"]


def _is_noise_concept(name: str) -> bool:
    """判断概念是否为噪音标签（无行业含义）。"""
    for kw in _NOISE_KEYWORDS:
        if kw in name:
            return True
    for suffix in _REGION_SUFFIXES:
        if name.endswith(suffix) and len(name) <= 4:
            return True
    return False


def _match_theme(name: str) -> str | None:
    """将概念名匹配到主题大类。"""
    for theme_name, keywords in _THEME_KEYWORDS:
        for kw in keywords:
            if kw in name:
                return theme_name
    return None


def compute_concept_hint(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """根据概念卡片列表，计算概念组合解读。

    返回:
        themes: 匹配到的主题列表（按关联概念数排序）
        main_identity: 一句话核心定位
        resonance: 概念共振分析（涨跌比）
        summary: 可直接展示的解读文本
    """
    # 1) 过滤噪音，保留有含义的概念
    meaningful = [c for c in cards if not _is_noise_concept(c.get("name", ""))]

    # 2) 按主题聚类
    theme_map: dict[str, list[str]] = {}
    for c in meaningful:
        theme = _match_theme(c.get("name", ""))
        if theme:
            theme_map.setdefault(theme, []).append(c["name"])

    themes = [
        {"name": t, "concepts": cs, "strength": len(cs)}
        for t, cs in sorted(theme_map.items(), key=lambda x: -len(x[1]))
    ]

    # 3) 共振分析（基于有含义的概念）
    rising = sum(1 for c in meaningful if (c.get("change_pct") or 0) > 0)
    falling = sum(1 for c in meaningful if (c.get("change_pct") or 0) < 0)
    flat = len(meaningful) - rising - falling
    total = len(meaningful)

    if total == 0:
        return {"themes": [], "main_identity": "", "resonance": {}, "summary": ""}

    ratio = rising / total if total else 0
    if ratio >= 0.7:
        level = "强共振"
        level_color = "rise"
    elif ratio >= 0.5:
        level = "偏强"
        level_color = "rise"
    elif ratio >= 0.35:
        level = "中性"
        level_color = "neutral"
    elif ratio >= 0.2:
        level = "偏弱"
        level_color = "fall"
    else:
        level = "弱势"
        level_color = "fall"

    resonance = {
        "total": total,
        "rising": rising,
        "falling": falling,
        "flat": flat,
        "ratio": round(ratio, 2),
        "level": level,
        "level_color": level_color,
    }

    # 4) 生成核心定位和解读文本
    # 主线主题（取前 2-3 个）
    main_themes = themes[:3] if themes else []

    # 找到今日最强的概念
    best_concept: dict[str, Any] | None = None
    for c in meaningful:
        pct = c.get("change_pct") or 0
        if best_concept is None or pct > (best_concept.get("change_pct") or 0):
            best_concept = c

    # 生成一句话定位
    if main_themes:
        theme_names = [t["name"] for t in main_themes]
        if len(theme_names) == 1:
            identity = f"{theme_names[0]}概念股"
        elif len(theme_names) == 2:
            identity = f"{theme_names[0]}+{theme_names[1]}核心标的"
        else:
            identity = f"{theme_names[0]}+{theme_names[1]}+{theme_names[2]}多维概念股"
    else:
        identity = "多元概念股"

    # 生成解读
    parts = []
    if main_themes:
        combo = "+".join(t["name"] for t in main_themes[:2])
        top_concepts = []
        for t in main_themes[:2]:
            top_concepts.extend(t["concepts"][:2])
        concept_str = "、".join(top_concepts[:4])
        parts.append(f"{combo}组合 ({concept_str})")
    parts.append(f"今日概念共振{level} ({rising}/{total}上涨)")

    if best_concept and (best_concept.get("change_pct") or 0) > 0.5:
        parts.append(f"最强概念: {best_concept['name']}")

    summary = "; ".join(parts)

    return {
        "themes": themes,
        "main_identity": identity,
        "resonance": resonance,
        "summary": summary,
    }


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
        "concept_hint": compute_concept_hint(cards),
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
