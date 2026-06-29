"""Stock browsing endpoints for the first real-data display stage."""

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select

from alphaagent.market.indicators import compute_bar_indicators
from alphaagent.market.symbols import normalize_exchange, vt_symbol as build_vt_symbol
from alphaagent.market.providers import RealMarketDataClient
from alphaagent.server.core.config import get_settings
from alphaagent.server.core.responses import fail, ok
from alphaagent.server.db import schema
from alphaagent.server.db.session import is_database_configured, session_scope

router = APIRouter(prefix="/stocks", tags=["stocks"])


def client() -> RealMarketDataClient:
    settings = get_settings()
    return RealMarketDataClient(timeout=settings.market_timeout_seconds)


@router.get("", response_model=None)
def list_stocks(
    q: str = Query(default=""),
    industry: str = Query(default=""),
    sector: str = Query(default=""),
    market: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    sort: str = Query(default="mktcap"),
    order: str = Query(default="desc"),
):
    # Filters beyond q/sort become database-backed in the next stage.
    del industry, sector, market
    try:
        market_client = client()
        if q.strip():
            data = market_client.search_stocks(q, page_size=page_size)
        else:
            try:
                data = market_client.list_stocks(page, page_size, sort, order)
            except TypeError:
                data = market_client.list_stocks(page, page_size, sort)
        return ok(data)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "真实股票行情暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/search", response_model=None)
def search_stocks(
    q: str = Query(default=""),
    page_size: int = Query(default=50, ge=1, le=100),
):
    try:
        data = client().search_stocks(q, page_size=page_size) if q.strip() else {"items": [], "page": 1, "page_size": page_size, "total": 0, "source": "empty_query"}
        return ok(data)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "真实股票搜索暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/{vt_symbol}", response_model=None)
def stock_detail(
    vt_symbol: str,
    date: date | None = Query(default=None, description="历史回放日期 YYYY-MM-DD"),
):
    if date is not None:
        return historical_stock_detail(vt_symbol, date)

    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        return ok(client().stock_detail(symbol, exchange))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "真实股票详情暂时不可用。", {"reason": exc.__class__.__name__}),
        )


def historical_stock_detail(vt_symbol: str, trade_date: date):
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "历史股票详情需要本地数据库。", {}),
        )

    symbol, exchange = parse_vt_symbol(vt_symbol)
    normalized_vt_symbol = build_vt_symbol(symbol, exchange)
    with session_scope() as session:
        stock = session.execute(
            select(schema.stocks)
            .where(schema.stocks.c.vt_symbol == normalized_vt_symbol)
            .limit(1)
        ).mappings().first()
        bar = session.execute(
            select(schema.stock_daily_bars)
            .where(
                schema.stock_daily_bars.c.vt_symbol == normalized_vt_symbol,
                schema.stock_daily_bars.c.trade_date == trade_date,
            )
            .limit(1)
        ).mappings().first()
        if bar is None:
            if _can_use_intraday_snapshot(session, trade_date):
                snapshot = _intraday_snapshot_detail(stock, normalized_vt_symbol, trade_date)
                if snapshot is not None:
                    return ok(snapshot)
            return JSONResponse(
                status_code=404,
                content=fail(
                    "HISTORICAL_BAR_NOT_FOUND",
                    "该回放日期没有这只股票的日线数据，不能用最新行情代替历史行情。",
                    {"vt_symbol": normalized_vt_symbol, "date": trade_date.isoformat()},
                ),
            )
        prev = session.execute(
            select(schema.stock_daily_bars.c.close_price)
            .where(
                schema.stock_daily_bars.c.vt_symbol == normalized_vt_symbol,
                schema.stock_daily_bars.c.trade_date < trade_date,
            )
            .order_by(desc(schema.stock_daily_bars.c.trade_date))
            .limit(1)
        ).first()

    previous_close = prev[0] if prev else None
    close_price = bar["close_price"]
    change = close_price - previous_close if previous_close is not None else None
    change_pct = (close_price / previous_close - 1) * 100 if previous_close else None
    resolved_exchange = str((stock or {}).get("exchange") or normalize_exchange(symbol, exchange))

    return ok({
        "symbol": str((stock or {}).get("symbol") or symbol),
        "exchange": resolved_exchange,
        "vt_symbol": normalized_vt_symbol,
        "name": str((stock or {}).get("name") or normalized_vt_symbol),
        "last_price": close_price,
        "change": change,
        "change_pct": change_pct,
        "open_price": bar["open_price"],
        "high_price": bar["high_price"],
        "low_price": bar["low_price"],
        "previous_close": previous_close,
        "volume": bar["volume"],
        "turnover": bar["turnover"],
        "market_cap": (stock or {}).get("market_cap"),
        "pe": (stock or {}).get("pe"),
        "pb": (stock or {}).get("pb"),
        "turnover_rate": (stock or {}).get("turnover_rate"),
        "volume_ratio": (stock or {}).get("volume_ratio"),
        "return_5d": (stock or {}).get("return_5d"),
        "return_10d": (stock or {}).get("return_10d"),
        "return_20d": (stock or {}).get("return_20d"),
        "industry": (stock or {}).get("industry"),
        "area": (stock or {}).get("area"),
        "trade_time": trade_date.isoformat(),
        "source": "postgresql.stock_daily_bars.as_of_date",
    })


def _can_use_intraday_snapshot(session, trade_date: date) -> bool:
    latest_complete = session.execute(select(func.max(schema.stock_daily_bars.c.trade_date))).scalar_one_or_none()
    if latest_complete is not None and trade_date <= latest_complete:
        return False

    minute_row = session.execute(
        select(schema.stock_minute_bars.c.vt_symbol)
        .where(
            schema.stock_minute_bars.c.trade_date == trade_date,
            schema.stock_minute_bars.c.interval == "1m",
        )
        .limit(1)
    ).first()
    if minute_row:
        return True

    flow_row = session.execute(
        select(schema.stock_fund_flows.c.vt_symbol)
        .where(schema.stock_fund_flows.c.trade_date == trade_date.isoformat())
        .limit(1)
    ).first()
    return bool(flow_row)


def _intraday_snapshot_detail(stock: dict | None, normalized_vt_symbol: str, trade_date: date) -> dict | None:
    if not stock or stock.get("last_price") is None:
        return None

    change_pct = stock.get("change_pct")
    last_price = stock.get("last_price")
    previous_close = None
    change = None
    if last_price is not None and change_pct not in (None, -100):
        try:
            previous_close = float(last_price) / (1 + float(change_pct) / 100)
            change = float(last_price) - previous_close
        except (TypeError, ValueError, ZeroDivisionError):
            previous_close = None
            change = None

    trade_time = stock.get("trade_time")
    return {
        "symbol": str(stock.get("symbol") or normalized_vt_symbol.split(".")[0]),
        "exchange": str(stock.get("exchange") or normalize_exchange(normalized_vt_symbol.split(".")[0])),
        "vt_symbol": normalized_vt_symbol,
        "name": str(stock.get("name") or normalized_vt_symbol),
        "last_price": last_price,
        "change": change,
        "change_pct": change_pct,
        "open_price": stock.get("open_price") or previous_close,
        "high_price": stock.get("high_price") or last_price,
        "low_price": stock.get("low_price") or last_price,
        "previous_close": previous_close,
        "volume": stock.get("volume"),
        "turnover": stock.get("turnover"),
        "market_cap": stock.get("market_cap"),
        "pe": stock.get("pe"),
        "pb": stock.get("pb"),
        "turnover_rate": stock.get("turnover_rate"),
        "volume_ratio": stock.get("volume_ratio"),
        "return_5d": stock.get("return_5d"),
        "return_10d": stock.get("return_10d"),
        "return_20d": stock.get("return_20d"),
        "industry": stock.get("industry"),
        "area": stock.get("area"),
        "trade_time": f"{trade_date.isoformat()} {trade_time}" if trade_time else trade_date.isoformat(),
        "source": "postgresql.stocks.intraday_snapshot",
        "price_source": "intraday_snapshot",
    }


@router.get("/{vt_symbol}/bars", response_model=None)
def stock_bars(
    vt_symbol: str,
    interval: str = Query(default="1d"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    limit: int = Query(default=120, ge=5, le=3000),
):
    del start, end
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        return ok(market_client.stock_bars(symbol, exchange, limit=limit, interval=interval))
    except Exception as exc:
        return ok(empty_bar_series(symbol, exchange, interval, exc))


@router.get("/{vt_symbol}/indicators")
def stock_indicators(
    vt_symbol: str,
    interval: str = Query(default="1d"),
    limit: int = Query(default=120, ge=20, le=3000),
):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        bars = market_client.stock_bars(symbol, exchange, limit=limit, interval=interval)
        return ok(compute_bar_indicators(build_vt_symbol(symbol, exchange), bars["items"], source=bars.get("source")))
    except Exception as exc:
        return ok(empty_indicators(vt_symbol, exc))


@router.get("/{vt_symbol}/business")
def stock_business(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        return ok(market_client.stock_business(symbol, exchange))
    except Exception as exc:
        return ok(empty_business(vt_symbol, exc))


@router.get("/{vt_symbol}/sectors")
def stock_sectors(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        return ok(market_client.stock_sectors(symbol, exchange))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("SECTOR_DATA_SOURCE_UNAVAILABLE", "真实板块数据暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/{vt_symbol}/industry-chain")
def stock_industry_chain(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        return ok(market_client.stock_industry_chain(symbol, exchange))
    except Exception as exc:
        return ok(empty_industry_chain(vt_symbol, exc))


@router.get("/{vt_symbol}/snapshot", response_model=None)
def stock_snapshot(
    vt_symbol: str,
    date: date | None = Query(default=None, description="盘中日期 YYYY-MM-DD；用于把实时快照临时并入指标"),
):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    market_client = client()
    try:
        quote = market_client.stock_detail(symbol, exchange)
        symbol = str(quote.get("symbol") or symbol)
        exchange = str(quote.get("exchange") or exchange or "")
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "股票快照暂时不可用。", {"reason": exc.__class__.__name__}),
        )

    resolved_vt_symbol = build_vt_symbol(symbol, exchange)
    missing = []

    try:
        bars = market_client.stock_bars(symbol, exchange, limit=120, interval="1d")
        bar_items = _bars_with_intraday_snapshot(resolved_vt_symbol, bars["items"], quote, date)
        bars = {**bars, "items": bar_items}
        indicators = compute_bar_indicators(resolved_vt_symbol, bars["items"], source=bars.get("source"))
        if bar_items and date and str(bar_items[-1].get("trade_date")) == date.isoformat():
            quote = {**quote, "price_source": "intraday_snapshot"}
            indicators = {**indicators, "temporary_bar": True, "temporary_bar_date": date.isoformat()}
    except Exception as exc:
        bars = empty_bar_series(symbol, exchange, "1d", exc)
        indicators = empty_indicators(resolved_vt_symbol, exc)
        missing.extend(["bars", "technical_indicators"])

    try:
        business = market_client.stock_business(symbol, exchange)
    except Exception:
        business = empty_business(resolved_vt_symbol)

    try:
        sectors = market_client.stock_sectors(symbol, exchange).get("items", [])
    except Exception:
        sectors = []

    try:
        industry_chain = market_client.stock_industry_chain_from_data(symbol, exchange, business, sectors)
    except AttributeError:
        try:
            industry_chain = market_client.stock_industry_chain(symbol, exchange)
        except Exception:
            industry_chain = empty_industry_chain(resolved_vt_symbol)
    except Exception:
        industry_chain = empty_industry_chain(resolved_vt_symbol)

    if not business.get("summary") and not business.get("business_scope"):
        missing.append("business")
    if not sectors:
        missing.append("sectors")
    if not industry_chain.get("chain_name") and not industry_chain.get("midstream"):
        missing.append("industry_chain")

    return ok(
        {
            "quote": quote,
            "bars": bars["items"],
            "technical_indicators": indicators,
            "business": business,
            "sectors": sectors,
            "industry_chain": industry_chain,
            "data_quality": {
                "missing": missing,
                "sources": [quote.get("source"), bars.get("source"), business.get("source")],
            },
        }
    )


def _bars_with_intraday_snapshot(
    vt_symbol: str,
    bars: list[dict],
    quote: dict,
    trade_date: date | None,
) -> list[dict]:
    if trade_date is None or not is_database_configured():
        return bars
    with session_scope() as session:
        if not _can_use_intraday_snapshot(session, trade_date):
            return bars
    if not quote.get("last_price"):
        return bars

    if bars and str(bars[-1].get("trade_date")) >= trade_date.isoformat():
        return bars

    temp_bar = _quote_to_temp_bar(quote, trade_date)
    if temp_bar is None:
        return bars
    return [*bars, temp_bar]


def _quote_to_temp_bar(quote: dict, trade_date: date) -> dict | None:
    last_price = quote.get("last_price")
    if last_price is None:
        return None
    return {
        "trade_date": trade_date.isoformat(),
        "open": quote.get("open_price") or last_price,
        "close": last_price,
        "high": quote.get("high_price") or last_price,
        "low": quote.get("low_price") or last_price,
        "volume": quote.get("volume"),
        "turnover": quote.get("turnover") or quote.get("amount"),
        "change_pct": quote.get("change_pct"),
        "source": "intraday_snapshot",
    }


def parse_vt_symbol(vt_symbol: str) -> tuple[str, str | None]:
    if "." in vt_symbol:
        symbol, exchange = vt_symbol.split(".", 1)
        return symbol.strip(), exchange.strip()
    return vt_symbol.strip(), None


def resolve_symbol_exchange(
    market_client: RealMarketDataClient,
    symbol: str,
    exchange: str | None,
) -> tuple[str, str | None]:
    """Use the live AkShare quote row as the source of truth for exchange."""

    try:
        detail = market_client.stock_detail(symbol, exchange)
    except Exception:
        return symbol, exchange
    return str(detail.get("symbol") or symbol), str(detail.get("exchange") or exchange or "")


def empty_bar_series(symbol: str, exchange: str | None, interval: str, exc: Exception) -> dict[str, object]:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "vt_symbol": build_vt_symbol(symbol, exchange),
        "interval": interval,
        "items": [],
        "source": "unavailable",
        "message": f"AkShare 暂未返回该股票的 K 线数据: {exc.__class__.__name__}",
    }


def empty_indicators(vt_symbol: str, exc: Exception) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "status": "pending",
        "source": "unavailable",
        "sample_size": 0,
        "message": f"AkShare K 线样本不可用，暂不能计算技术指标: {exc.__class__.__name__}",
    }


def empty_business(vt_symbol: str, exc: Exception | None = None) -> dict[str, object]:
    reason = f": {exc.__class__.__name__}" if exc else ""
    return {
        "vt_symbol": vt_symbol,
        "summary": None,
        "business_scope": None,
        "main_products": [],
        "segments": [],
        "source": "unavailable",
        "message": f"AkShare 暂未返回该股票的主营业务数据{reason}",
    }


def empty_industry_chain(vt_symbol: str, exc: Exception | None = None) -> dict[str, object]:
    reason = f": {exc.__class__.__name__}" if exc else ""
    return {
        "vt_symbol": vt_symbol,
        "chain_name": None,
        "position": None,
        "upstream": [],
        "midstream": [],
        "downstream": [],
        "exposure": [],
        "sectors": [],
        "evidence": [],
        "status": "unavailable",
        "source": "unavailable",
        "message": f"AkShare 暂未返回足够的产业链线索{reason}",
    }
